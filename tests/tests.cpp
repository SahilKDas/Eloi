#include "eloi/chess.hpp"
#include "eloi/config.hpp"
#include "tactical_data.hpp"

#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

using namespace eloi;

namespace eloi {
struct SearcherTestAccess {
  struct Entry {
    std::uint64_t key{};
    int score{};
    int static_eval{};
    int depth{};
    PackedMove best{};
    int flag{};
    int generation{};
  };

  static void store(Searcher& searcher, std::uint64_t key, int depth,
                    int score, int static_eval, int flag,
                    const Move& best, int ply) {
    searcher.store(key, depth, score, static_eval, flag, best, ply);
  }

  static std::optional<Entry> lookup(Searcher& searcher, std::uint64_t key) {
    const auto found = searcher.probe(key);
    if (!found) return std::nullopt;
    return Entry{found->key, found->score, found->static_eval, found->depth,
                 found->best, found->flag, found->generation};
  }

  static std::size_t bucket_count(const Searcher& searcher) {
    return searcher.table_.size();
  }

  static void next_generation(Searcher& searcher) {
    searcher.advance_generation();
  }

  static std::size_t lane_count(const Searcher& searcher) {
    return 1 + std::ranges::count_if(searcher.root_helpers_,
                                     [](const Searcher* helper) {
                                       return helper != nullptr;
                                     });
  }

  static bool helpers_share_table(const Searcher& searcher) {
    return searcher.root_helpers_[0] && searcher.root_helpers_[1] &&
           searcher.table_.data() == searcher.root_helpers_[0]->table_.data() &&
           searcher.table_.data() == searcher.root_helpers_[1]->table_.data();
  }
};
}  // namespace eloi

namespace {
int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void expect_position_caches(const Position& position,
                            const std::string& context) {
  std::array<std::array<std::uint64_t, 7>, 2> expected_pieces{};
  std::array<std::uint64_t, 2> expected_colors{};
  std::array<int, 2> expected_kings{-1, -1};
  for (int square = 0; square < 64; ++square) {
    const int cell = position.cells[square];
    if (!cell) continue;
    const int side = cell > 0 ? 0 : 1;
    const int piece = std::abs(cell);
    const std::uint64_t bit = std::uint64_t{1} << square;
    expected_pieces[side][piece] |= bit;
    expected_colors[side] |= bit;
    if (piece == static_cast<int>(Piece::king))
      expected_kings[side] = square;
  }
  expect(position.piece_bits == expected_pieces,
         context + ": piece bitboards match mailbox");
  expect(position.color_bits == expected_colors,
         context + ": color bitboards match mailbox");
  expect(position.occupied == (expected_colors[0] | expected_colors[1]),
         context + ": occupied bitboard matches mailbox");
  expect(position.king_square(Color::white) == expected_kings[0] &&
             position.king_square(Color::black) == expected_kings[1],
         context + ": cached king squares match mailbox");
}

void expect_perft(std::string_view fen, int depth, std::uint64_t expected,
                  bool horde = false) {
  std::string error;
  auto board = parse_fen(fen, &error);
  expect(board.has_value(), "parse perft FEN: " + error);
  if (!board) return;
  auto actual = perft(board->position, board->turn, depth, nullptr, horde);
  expect(actual == expected, "perft depth " + std::to_string(depth) + ": expected " +
                            std::to_string(expected) + ", got " + std::to_string(actual));
}

void expect_search_round_trip(std::string_view fen, std::string_view uci) {
  auto board = parse_fen(fen);
  expect(board.has_value(), "parse search round-trip FEN");
  if (!board) return;
  const auto parsed = parse_uci_move(uci);
  expect(parsed.has_value(), "parse search round-trip move");
  if (!parsed) return;
  Move legal;
  bool matched = false;
  for (const Move& move : board->legal_moves())
    if (move.same_coordinates(*parsed) ||
        (board->chess960 &&
         uci_move(move, board->position, true) == uci)) {
      legal = move;
      matched = true;
      break;
    }
  expect(matched, std::string(uci) + " is legal for search round trip");
  if (!matched) return;
  const std::string before_fen = to_fen(*board);
  const auto before_nnue = board->nnue;
  const auto before_key = board->key;
  const auto before_castled = board->has_castled;
  const auto history_size = board->history.size();
  expect_position_caches(board->position, std::string(uci) + " before");
  Board::SearchUndo undo;
  expect(board->make_search_move(legal, undo),
         std::string(uci) + " makes in place");
  expect(board->history.size() == history_size,
         "search move does not modify public history");
  expect(board->key == position_key(board->position, board->turn),
         "search move keeps the incremental Zobrist key exact");
  expect(board->nnue == nnue_refresh(board->position),
         "search move keeps the incremental NNUE accumulator exact");
  expect_position_caches(board->position, std::string(uci) + " after");
  board->unmake_search_move(undo);
  expect(to_fen(*board) == before_fen,
         std::string(uci) + " restores the complete board state");
  expect(board->nnue == before_nnue && board->key == before_key &&
             board->has_castled == before_castled,
         std::string(uci) + " restores NNUE, key, and castling state");
  expect_position_caches(board->position, std::string(uci) + " restored");
}

struct EpdCase {
  std::string fen;
  std::string id;
  std::string category;
  std::string best;
  std::string avoid;
  int depth{4};
  std::optional<int> expected_score;
  std::optional<std::pair<int, int>> stable_depths;
  std::optional<int> maximum_swing;
};

std::string unquote(std::string value) {
  while (!value.empty() &&
         std::isspace(static_cast<unsigned char>(value.front())))
    value.erase(value.begin());
  while (!value.empty() &&
         std::isspace(static_cast<unsigned char>(value.back())))
    value.pop_back();
  if (value.size() >= 2 && value.front() == '"' && value.back() == '"')
    return value.substr(1, value.size() - 2);
  return value;
}

std::vector<EpdCase> load_epd(const std::filesystem::path& path) {
  std::ifstream input(path);
  std::vector<EpdCase> result;
  for (std::string line; std::getline(input, line);) {
    if (line.empty() || line.front() == '#') continue;
    std::istringstream fields(line);
    std::array<std::string, 4> fen_fields;
    if (!(fields >> fen_fields[0] >> fen_fields[1] >> fen_fields[2] >>
          fen_fields[3]))
      continue;
    std::string operations;
    std::getline(fields, operations);
    std::map<std::string, std::string> values;
    std::istringstream operation_stream(operations);
    for (std::string operation; std::getline(operation_stream, operation, ';');) {
      std::istringstream parts(operation);
      std::string key;
      if (!(parts >> key)) continue;
      std::string value;
      std::getline(parts, value);
      values[key] = unquote(value);
    }
    const std::string halfmove = values.contains("hmvc") ? values["hmvc"] : "0";
    const std::string fullmove = values.contains("fmvn") ? values["fmvn"] : "1";
    EpdCase test;
    test.fen = fen_fields[0] + " " + fen_fields[1] + " " + fen_fields[2] +
               " " + fen_fields[3] + " " + halfmove + " " + fullmove;
    test.id = values["id"];
    test.category = values["c0"];
    test.best = values["bm"];
    test.avoid = values["am"];
    if (values.contains("acd")) test.depth = std::stoi(values["acd"]);
    if (values.contains("ce")) test.expected_score = std::stoi(values["ce"]);
    if (values.contains("stable")) {
      std::istringstream depths(values["stable"]);
      int shallow = 0, deep = 0;
      if (depths >> shallow >> deep)
        test.stable_depths = std::pair{shallow, deep};
    }
    if (values.contains("swing"))
      test.maximum_swing = std::stoi(values["swing"]);
    result.push_back(std::move(test));
  }
  return result;
}

SearchResult fixed_depth_search(
    const Board& board, int depth) {
  auto config = default_config();
  config.own_book = false;
  config.hash_mb = 4;
  std::atomic_bool stopped{false};
  SearchLimits limits;
  limits.depth = depth;
  Searcher searcher(config, stopped);
  return searcher.iterative(board, limits);
}

std::string best_uci(const SearchResult& result) {
  return result.pv.empty() ? std::string{} : result.pv.front().uci();
}

std::optional<Move> legal_move(const Board& board, std::string_view uci) {
  const auto parsed = parse_uci_move(uci);
  if (!parsed) return std::nullopt;
  for (const Move& move : board.legal_moves())
    if (move.same_coordinates(*parsed)) return move;
  return std::nullopt;
}
}  // namespace

int main() {
  static_assert(search_thread_count == 3,
                "Eloi's search contract is fixed at exactly three threads");
  static_assert(recommended_search_depth == 40,
                "Eloi warns above exactly 40 plies");
  static_assert(maximum_gui_search_depth == 200,
                "Eloi's GUI maximum must remain exactly 200 plies");
  static_assert(maximum_search_depth == 17'697,
                "Eloi's ultimate limit matches the longest legal chess game");
  static_assert(sizeof(PackedMove) == 2, "TT moves remain exactly 16 bits");
  static_assert(lichess_ponder_enabled(239'999),
                "sub-four-minute games enable pondering");
  static_assert(!lichess_ponder_enabled(240'000),
                "four-minute games do not enable pondering");
  static_assert(!lichess_ponder_enabled(-1),
                "clockless games do not enable pondering");
  expect(RuntimeConfig{}.min_base_seconds == 0,
         "default challenge filter accepts sub-four-minute clocks");
  {
    const auto path = std::filesystem::current_path() / "eloi-config-test.yml";
    {
      std::ofstream output(path);
      output << "lichess:\n"
                "  enabled: true\n"
                "  token: \"lip_test_only\"\n"
                "challenge:\n"
                "  min_base_seconds: 0\n"
                "  max_base_seconds: 10800\n"
                "  allow_bots: false\n"
                "  variants:\n"
                "    - standard\n"
                "    - chess960\n"
                "    - horde\n"
                "engine:\n"
                "  depth: 12\n"
                "  hash_mb: 64\n"
                "  move_overhead_ms: 150\n"
                "  own_book: false\n";
    }
    std::string error;
    const auto config = load_runtime_config(path, &error);
    expect(config.has_value(), "human-readable config parses: " + error);
    if (config)
      expect(config->lichess_enabled &&
                 config->lichess_token == "lip_test_only" &&
                 config->min_base_seconds == 0 &&
                 config->max_base_seconds == 10'800 &&
                 !config->allow_bots && config->variants.size() == 3 &&
                 config->depth == 12 && config->hash_mb == 64 &&
                 config->move_overhead_ms == 150 && !config->own_book,
             "config values map exactly into runtime settings");
    if (config) {
      RuntimeConfig saved = *config;
      saved.lichess_token = "lip_test_only_round_trip";
      expect(save_runtime_config(path, saved, &error),
             "configuration GUI serializer writes YAML: " + error);
      const auto round_trip = load_runtime_config(path, &error);
      expect(round_trip.has_value() &&
                 round_trip->lichess_token == saved.lichess_token &&
                 round_trip->lichess_enabled == saved.lichess_enabled &&
                 round_trip->variants == saved.variants &&
                 round_trip->depth == saved.depth &&
                 round_trip->hash_mb == saved.hash_mb,
             "saved configuration round-trips without losing settings");
    }
    {
      std::ofstream output(path);
      output << "challenge:\n"
                "  min_base_seconds: 500\n"
                "  max_base_seconds: 240\n";
    }
    expect(!load_runtime_config(path, &error),
           "config rejects an inverted base-time range");
    {
      std::ofstream output(path);
      output << "lichess:\n"
                "  url: \"http://lichess.org\"\n";
    }
    expect(!load_runtime_config(path, &error),
           "config rejects a plaintext Lichess token endpoint");
    {
      std::ofstream output(path);
      output << "lichess:\n"
                "  url: \"https://lichess.org.attacker.invalid\"\n";
    }
    expect(!load_runtime_config(path, &error),
           "config rejects a lookalike bearer-token endpoint");
    std::filesystem::remove(path);
  }
  {
    for (Piece promotion : {Piece::none, Piece::queen, Piece::rook,
                            Piece::bishop, Piece::knight}) {
      Move move;
      move.from = *parse_square("a7");
      move.to = *parse_square("a8");
      move.promotion = promotion;
      const Move unpacked = unpack_move(pack_move(move));
      expect(unpacked.same_coordinates(move),
             "packed move preserves coordinates and promotion");
    }
    expect(pack_move({}) == 0 && unpack_move(0).from < 0,
           "zero is the packed no-move sentinel");
    expect(score_to_tt(321, 9) == 321 && score_from_tt(321, 3) == 321,
           "ordinary TT evaluations are ply independent");
    const int stored_win = score_to_tt(30'000 - 7, 7);
    const int stored_loss = score_to_tt(-30'000 + 7, 7);
    expect(score_from_tt(stored_win, 3) == 30'000 - 3,
           "winning TT mate distance normalizes across plies");
    expect(score_from_tt(stored_loss, 3) == -30'000 + 3,
           "losing TT mate distance normalizes across plies");
  }
  {
    auto expect_see = [](std::string_view fen, std::string_view uci,
                         int expected, std::string_view label) {
      auto board = parse_fen(fen);
      expect(board.has_value(), std::string(label) + ": SEE FEN parses");
      if (!board) return;
      const auto move = legal_move(*board, uci);
      expect(move.has_value(), std::string(label) + ": SEE move is legal");
      if (!move) return;
      const int actual = static_exchange_evaluation(
          board->position, board->turn, *move);
      expect(actual == expected,
             std::string(label) + ": expected SEE " +
                 std::to_string(expected) + ", got " +
                 std::to_string(actual));
    };
    expect_see("4k3/8/8/3q4/3R4/8/8/4K3 w - - 0 1",
               "d4d5", 900, "free queen capture");
    expect_see("3rk3/8/8/3q4/3R4/8/8/4K3 w - - 0 1",
               "d4d5", 400, "defended queen capture");
    expect_see("3rk3/8/8/3p4/3Q4/8/8/4K3 w - - 0 1",
               "d4d5", -800, "poisoned pawn capture");
    expect_see("k6r/6P1/8/8/8/8/8/4K3 w - - 0 1",
               "g7h8q", 1300, "capture promotion");
  }
  {
    auto config = default_config();
    config.own_book = false;
    config.hash_mb = 1;
    std::atomic_bool stopped{false};
    Searcher searcher(config, stopped);
    const auto best = parse_uci_move("a2a3").value();
    const std::size_t buckets = SearcherTestAccess::bucket_count(searcher);
    expect(buckets > 0 && std::has_single_bit(buckets),
           "TT test table has a power-of-two bucket count");

    for (int flag : {-1, 0, 1}) {
      const std::uint64_t key = 100 + static_cast<std::uint64_t>(flag + 1) *
          buckets;
      SearcherTestAccess::store(searcher, key, 6, 120 + flag, -35,
                                flag, best, 0);
      const auto entry = SearcherTestAccess::lookup(searcher, key);
      expect(entry && entry->flag == flag && entry->depth == 6 &&
                 entry->score == 120 + flag && entry->static_eval == -35,
             "TT preserves exact/lower/upper bound metadata");
    }

    const std::uint64_t mate_key = 777;
    SearcherTestAccess::store(searcher, mate_key, 9, 30'000 - 7,
                              500, 0, best, 7);
    const auto mate = SearcherTestAccess::lookup(searcher, mate_key);
    expect(mate && score_from_tt(mate->score, 3) == 30'000 - 3,
           "TT stored mate score decodes relative to the probing ply");

    const std::uint64_t deep_key = 991;
    SearcherTestAccess::store(searcher, deep_key, 8, 80, 20, 0, best, 0);
    SearcherTestAccess::store(searcher, deep_key, 3, -400, -20, -1,
                              best, 0);
    const auto deep = SearcherTestAccess::lookup(searcher, deep_key);
    expect(deep && deep->depth == 8 && deep->score == 80,
           "TT refuses to overwrite a deeper same-key entry");

    Searcher collision_table(config, stopped);
    const std::size_t collision_stride =
        SearcherTestAccess::bucket_count(collision_table);
    constexpr std::uint64_t bucket = 7;
    for (int index = 0; index < 4; ++index)
      SearcherTestAccess::store(
          collision_table,
          bucket + static_cast<std::uint64_t>(index) * collision_stride,
          index + 1, 10 * index, 0, 0, best, 0);
    const std::uint64_t replacement_key = bucket + 4 * collision_stride;
    SearcherTestAccess::store(collision_table, replacement_key, 5, 50,
                              0, 0, best, 0);
    expect(!SearcherTestAccess::lookup(collision_table, bucket) &&
               SearcherTestAccess::lookup(collision_table, replacement_key),
           "four-way TT collision replaces the shallowest entry");

    SearcherTestAccess::next_generation(collision_table);
    const std::uint64_t fresh_key = bucket + 5 * collision_stride;
    SearcherTestAccess::store(collision_table, fresh_key, 0, 5,
                              0, 0, best, 0);
    expect(SearcherTestAccess::lookup(collision_table, fresh_key).has_value(),
           "new TT generation replaces stale entries even at shallow depth");
  }
  {
    std::string error;
    auto board = parse_fen(initial_fen, &error);
    expect(board.has_value(), "initial FEN parses");
    if (board) {
      expect(to_fen(*board) == initial_fen, "initial FEN round trip");
      expect_position_caches(board->position, "initial position");
    }
  }

  expect_perft(initial_fen, 1, 20);
  expect_perft(initial_fen, 2, 400);
  expect_perft(initial_fen, 3, 8902);
  expect_perft(initial_fen, 4, 197281);
  expect_perft("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862);
  expect_perft("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238);
  expect_perft("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/1PB1P1b1/P1NP1N2/2P1QPPP/R4RK1 b - b3 0 10", 1, 45);
  // Oracle values generated by python-chess with chess960=True.
  expect_perft("7k/8/8/8/8/8/8/1K1R4 w D - 0 1", 2, 48);
  expect_perft("7k/8/8/8/8/8/8/6KR w H - 0 1", 2, 24);
  expect_perft("7k/8/8/8/8/8/8/4K1R1 w G - 0 1", 2, 21);
  expect_perft("7k/8/8/8/8/8/8/1R1K4 w B - 0 1", 2, 42);
  expect_perft("5r1k/8/8/8/8/8/8/1K1R4 w D - 0 1", 2, 244);
  expect_perft(horde_initial_fen, 2, 128, true);

  {
    std::set<std::string> unique_positions;
    for (int index = 0; index < 960; ++index) {
      auto board = chess960_start(index);
      expect(board.has_value() && board->chess960,
             "every numbered Chess960 start parses with Shredder rights");
      if (!board) continue;
      const int king = board->position.king_square(Color::white);
      const int left_rook = board->position.castling_rooks[1];
      const int right_rook = board->position.castling_rooks[0];
      expect(left_rook < king && king < right_rook,
             "Chess960 king begins between its rooks");
      std::array<int, 2> bishops{-1, -1};
      int bishop = 0;
      for (int file = 0; file < 8; ++file)
        if (board->position.piece_at(square_of(file, 0)) == Piece::bishop)
          bishops[bishop++] = file;
      expect(bishop == 2 && ((bishops[0] ^ bishops[1]) & 1),
             "Chess960 bishops begin on opposite colors");
      const std::string fen = to_fen(*board);
      unique_positions.insert(fen.substr(0, fen.find(' ')));
    }
    expect(unique_positions.size() == 960,
           "Chess960 generator produces all 960 unique starting arrays");
    const auto orthodox = chess960_start(518);
    expect(orthodox && to_fen(*orthodox).starts_with(
               "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"),
           "official Chess960 position 518 is the orthodox arrangement");
    expect(!chess960_start(-1) && !chess960_start(960),
           "Chess960 generator rejects indices outside 0..959");
  }

  {
    auto board = *parse_fen(initial_fen);
    expect(board.push_uci("e2e4"), "e2e4 is legal");
    expect(board.position.en_passant == *parse_square("e3"), "double push sets en passant");
    expect(board.push_uci("a7a6") && board.push_uci("e4e5") && board.push_uci("d7d5"),
           "en-passant setup moves are legal");
    expect(board.push_uci("e5d6"), "en-passant capture is legal");
    expect(board.position.empty(*parse_square("d5")), "en-passant removes captured pawn");
  }


  expect_search_round_trip(initial_fen, "e2e4");
  expect_search_round_trip(
      "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1");
  expect_search_round_trip(
      "7k/8/8/8/8/8/8/1K1R4 w D - 0 1", "b1d1");
  expect_search_round_trip(
      "7k/8/8/3pP3/8/8/8/7K w - d6 0 1", "e5d6");
  expect_search_round_trip(
      "1r5k/P7/8/8/8/8/8/7K w - - 0 1", "a7b8n");

  {
    auto board = *parse_fen("7k/8/8/3pP3/8/8/8/7K w - d6 37 20");
    const std::string before_fen = to_fen(board);
    const auto before_nnue = board.nnue;
    const auto before_key = board.key;
    Board::SearchUndo undo;
    board.make_null_move(undo);
    expect(board.turn == Color::black && board.position.en_passant < 0,
           "null move flips the side and clears en passant");
    expect(board.key == position_key(board.position, board.turn),
           "null move updates the Zobrist key exactly");
    expect(board.nnue == before_nnue,
           "null move leaves piece-based NNUE accumulators unchanged");
    board.unmake_search_move(undo);
    expect(to_fen(board) == before_fen && board.key == before_key &&
               board.nnue == before_nnue,
           "null move unmake restores the complete position");
  }

  {
    auto board = *parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
    expect(board.push_uci("e1g1"), "white king-side castle");
    expect(board.position.piece_at(*parse_square("f1")) == Piece::rook, "castling moves rook");
    expect(board.pop(), "take back castle");
    expect(board.push_uci("e1c1"), "white queen-side castle");
  }

  {
    auto board = parse_fen("7k/8/8/8/8/8/8/1K1R4 w D - 0 1");
    expect(board.has_value() && board->chess960,
           "Shredder-FEN rook-file rights enable Chess960");
    if (board) {
      expect(to_fen(*board) == "7k/8/8/8/8/8/8/1K1R4 w D - 0 1",
             "Chess960 FEN round trips with its rook origin");
      const auto moves = board->legal_moves();
      const auto castle = std::find_if(
          moves.begin(), moves.end(),
          [](const Move& move) { return move.type == MoveType::king_castle; });
      expect(castle != moves.end() &&
                 uci_move(*castle, board->position, true) == "b1d1",
             "Chess960 UCI encodes castling as king-to-rook");
      const auto before_key = board->key;
      const auto before_nnue = board->nnue;
      expect(board->push_uci("b1d1"),
             "Chess960 accepts king-to-rook castling notation");
      expect(board->position.piece_at(*parse_square("g1")) == Piece::king &&
                 board->position.piece_at(*parse_square("f1")) == Piece::rook &&
                 board->position.empty(*parse_square("b1")) &&
                 board->position.empty(*parse_square("d1")),
             "Chess960 castling lands the king on g1 and rook on f1");
      expect(board->key == position_key(board->position, board->turn) &&
                 board->nnue == nnue_refresh(board->position),
             "Chess960 castling updates Zobrist and NNUE exactly");
      expect(board->pop() && board->key == before_key &&
                 board->nnue == before_nnue &&
                 to_fen(*board) ==
                     "7k/8/8/8/8/8/8/1K1R4 w D - 0 1",
             "Chess960 castling pop restores every overlapping square");
    }
  }

  {
    auto stationary_king =
        *parse_fen("7k/8/8/8/8/8/8/6KR w H - 0 1");
    expect(stationary_king.push_uci("g1h1"),
           "Chess960 castles when the king already occupies g1");
    expect(stationary_king.position.piece_at(*parse_square("g1")) ==
               Piece::king &&
               stationary_king.position.piece_at(*parse_square("f1")) ==
               Piece::rook,
           "stationary-king castling moves only the rook to f1");

    auto rook_on_king_target =
        *parse_fen("7k/8/8/8/8/8/8/4K1R1 w G - 0 1");
    expect(rook_on_king_target.push_uci("e1g1"),
           "Chess960 castles when the rook starts on g1");
    expect(rook_on_king_target.position.piece_at(*parse_square("g1")) ==
               Piece::king &&
               rook_on_king_target.position.piece_at(*parse_square("f1")) ==
               Piece::rook,
           "king replaces the rook on g1 and rook finishes on f1");

    auto rook_on_king_origin =
        *parse_fen("7k/8/8/8/8/8/8/1R1K4 w B - 0 1");
    expect(rook_on_king_origin.push_uci("d1b1"),
           "Chess960 queen-side castling accepts king-to-rook notation");
    expect(rook_on_king_origin.position.piece_at(*parse_square("c1")) ==
               Piece::king &&
               rook_on_king_origin.position.piece_at(*parse_square("d1")) ==
               Piece::rook,
           "queen-side overlap leaves king c1 and rook d1");
  }

  {
    auto attacked =
        *parse_fen("5r1k/8/8/8/8/8/8/1K1R4 w D - 0 1");
    expect(!attacked.push_uci("b1d1"),
           "Chess960 rejects castling through an attacked transit square");

    auto moved_rook =
        *parse_fen("7k/8/8/8/8/8/8/1K1R4 w D - 0 1");
    expect(moved_rook.push_uci("d1d2") &&
               !(moved_rook.position.castling & white_king),
           "moving a non-corner Chess960 rook clears its castling right");
  }

  {
    constexpr std::array promotions{
        std::pair{'q', Piece::queen}, std::pair{'r', Piece::rook},
        std::pair{'b', Piece::bishop}, std::pair{'n', Piece::knight}};
    for (const auto [suffix, piece] : promotions) {
      auto board = *parse_fen("7k/P7/8/8/8/8/8/7K w - - 0 1");
      const std::string move = std::string("a7a8") + suffix;
      expect(board.push_uci(move), move + " promotion is legal");
      expect(board.position.piece_at(*parse_square("a8")) == piece,
             move + " places the selected piece");
    }
  }

  {
    auto board = *parse_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1");
    expect(board.legal_moves().empty(), "checkmate has no legal moves");
    expect(board.position.in_check(Color::black), "checkmate king is checked");
  }

  {
    auto board = *parse_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
    expect(board.legal_moves().empty(), "stalemate has no legal moves");
    expect(!board.position.in_check(Color::black),
           "stalemate is a draw, not a win for either player");
  }

  {
    auto board = *parse_fen(horde_initial_fen);
    board.horde = true;
    expect_position_caches(board.position, "initial Horde position");
    int white_pawns = 0;
    for (int square = 0; square < 64; ++square)
      if (board.position.color_at(square) == Color::white &&
          board.position.piece_at(square) == Piece::pawn)
        ++white_pawns;
    expect(white_pawns == 36, "Horde starts with exactly 36 white pawns");
    expect(board.position.king_square(Color::white) < 0,
           "Horde White is legal without a king");
    expect(!board.horde_eliminated(),
           "the initial Horde is not considered eliminated");
  }

  {
    auto board = *parse_fen("4k3/8/8/8/8/8/8/P7 w - - 0 1");
    board.horde = true;
    expect(board.push_uci("a1a3"),
           "a Horde pawn may make its special first-rank double-step");
    expect(board.position.en_passant < 0,
           "a first-rank Horde double-step does not create en passant");
    expect(board.pop(), "the Horde double-step can be undone");
  }

  {
    auto board = *parse_fen("4k3/8/8/8/8/8/r7/P7 b - - 0 1");
    board.horde = true;
    expect(board.push_uci("a2a1"), "Black can capture the last Horde piece");
    expect(board.horde_eliminated(),
           "capturing every Horde piece ends the game");
    expect(board.variant_winner() == Color::black,
           "Black wins when the Horde is eliminated");
  }

  {
    auto board = *parse_fen("7k/6Q1/5P2/8/8/8/8/8 b - - 0 1");
    board.horde = true;
    expect(board.legal_moves().empty() &&
               board.position.in_check(Color::black),
           "Horde can checkmate Black without a white king");
    expect(board.variant_winner() == Color::white,
           "White wins Horde by checkmating Black");
  }

  {
    auto board = *parse_fen(initial_fen);
    constexpr std::array cycle{"g1f3", "g8f6", "f3g1", "f6g8"};
    for (int repeat = 0; repeat < 2; ++repeat)
      for (const auto move : cycle)
        expect(board.push_uci(move), std::string("repetition move ") + move);
    expect(board.repetition_count() == 3,
           "the initial position is present three times");
    expect(board.is_threefold_repetition(),
           "threefold repetition is recognized as a draw");
    expect(board.pop(), "repetition can be undone");
    expect(!board.is_threefold_repetition(),
           "undo removes the third occurrence from history");
  }

  {
    auto board = *parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
    constexpr std::array cycle{"h1h2", "h8h7", "h2h1", "h7h8"};
    for (const auto move : cycle)
      expect(board.push_uci(move), std::string("castling-rights move ") + move);
    expect(board.repetition_count() == 1,
           "identical piece placement with changed castling rights is not repetition");
  }

  {
    auto board = *parse_fen("7k/8/8/8/8/8/8/K7 w - - 100 51");
    expect(board.is_fifty_move_draw(), "100 halfmoves triggers the fifty-move draw");
    expect(board.position.insufficient_material(), "bare kings are dead material");
  }

  {
    auto board = *parse_fen(initial_fen);
    const auto initial_accumulator = board.nnue;
    expect(board.push_uci("e2e4"), "NNUE update test move is legal");
    expect(board.nnue == nnue_refresh(board.position),
           "incremental NNUE accumulator matches a full refresh");
    expect(board.pop(), "NNUE update test move can be undone");
    expect(board.nnue == initial_accumulator,
           "undo restores the exact NNUE accumulator");
  }

  {
    auto board = *parse_fen(initial_fen);
    constexpr std::array moves{
        "e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4",
        "f3d4", "g8f6", "b1c3", "a7a6", "c1e3", "e7e5"};
    for (std::size_t ply = 0; ply <= moves.size(); ++ply) {
      const auto dispatched = nnue_refresh(board.position);
      const auto scalar = nnue_refresh_scalar_reference(board.position);
      expect(dispatched == scalar,
             "scalar and runtime-dispatched NNUE accumulators agree at ply " +
                 std::to_string(ply));
      expect(nnue_evaluate(dispatched, board.turn) ==
                 nnue_evaluate(scalar, board.turn),
             "scalar and runtime-dispatched NNUE scores agree at ply " +
                 std::to_string(ply));
      if (ply < moves.size())
        expect(board.push_uci(moves[ply]),
               "SIMD consistency sequence move is legal");
    }
    std::cout << "NNUE runtime path: "
              << (nnue_runtime_has_avx2() ? "AVX2" : "scalar") << '\n';
  }

  {
    auto board = *parse_fen(initial_fen);
    const auto config = default_config();
    expect(opening_book_size() >= 8000,
           "the embedded general repertoire contains at least 8,000 choices");
    expect(opening_book_node_count() >= 3000,
           "the opening graph merges thousands of transposing positions");
    auto book = opening_move(config, board);
    expect(book && book->move.uci() == "e2e4",
           "Eloi forces 1.e4 as White");
    expect(book && book->family == "Italian Game",
           "White opening personality is the Italian Game");
    expect(board.push_uci("e2e4") && board.push_uci("e7e5"),
           "Italian setup begins legally");
    book = opening_move(config, board);
    expect(book && book->move.uci() == "g1f3", "Eloi forces 2.Nf3");
    expect(board.push_uci("g1f3") && board.push_uci("b8c6"),
           "Italian setup reaches move three");
    book = opening_move(config, board);
    expect(book && book->move.uci() == "f1c4", "Eloi forces 3.Bc4");
  }

  {
    auto board = *parse_fen(initial_fen);
    const auto config = default_config();
    expect(board.push_uci("d2d4"), "Nimzo setup starts with 1.d4");
    auto book = opening_move(config, board);
    expect(book && book->move.uci() == "g8f6", "Eloi forces 1...Nf6");
    expect(book && book->family == "Nimzo-Indian Defense",
           "Black opening personality is the Nimzo-Indian");
    expect(board.push_uci("g8f6") && board.push_uci("c2c4"),
           "Nimzo setup reaches Black's second move");
    book = opening_move(config, board);
    expect(book && book->move.uci() == "e7e6", "Eloi forces 2...e6");
    expect(board.push_uci("e7e6") && board.push_uci("b1c3"),
           "Nimzo setup reaches Black's third move");
    book = opening_move(config, board);
    expect(book && book->move.uci() == "f8b4", "Eloi forces 3...Bb4");
  }

  {
    auto board = *parse_fen(initial_fen);
    expect(board.push_uci("g1f3") && board.push_uci("b8c6") &&
           board.push_uci("e2e4") && board.push_uci("e7e5"),
           "Italian transposition is legal");
    const auto book = opening_move(default_config(), board);
    expect(book && book->move.uci() == "f1c4",
           "Italian personality recognizes a transposition");
    auto disabled = default_config();
    disabled.own_book = false;
    expect(!opening_move(disabled, board), "OwnBook=false disables the repertoire");
  }

  {
    auto board = *parse_fen(initial_fen);
    constexpr std::array moves{"e2e4", "c7c5", "g1f3", "d7d6",
                               "d2d4", "c5d4", "f3d4"};
    for (const auto move : moves) {
      expect(board.push_uci(move), std::string("key test move ") + move);
      expect(board.key == position_key(board.position, board.turn),
             "incremental Zobrist key matches full refresh");
    }
  }

  {
    auto board = *parse_fen(initial_fen);
    std::atomic_bool stopped{false};
    SearchLimits limits; limits.depth = 4;
    auto config = default_config();
    config.own_book = false;
    Searcher searcher(config, stopped);
    auto result = searcher.iterative(board, limits);
    expect(result.depth == 4, "iterative search reaches requested depth");
    expect(result.lmr_reductions > 0, "late move reductions are exercised");
    expect(!result.pv.empty(), "search returns a principal variation");
    if (!result.pv.empty()) expect(board.push(result.pv.front()), "search best move is legal");
  }

  {
    auto board = *parse_fen(
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    auto config = default_config();
    config.own_book = false;
    std::atomic_bool stopped{false};
    SearchLimits limits; limits.depth = 6;
    Searcher searcher(config, stopped);
    const auto result = searcher.iterative(board, limits);
    expect(result.null_cutoffs > 0,
           "verified null-move pruning is exercised");
    expect(result.probcut_cutoffs > 0,
           "SEE-guarded ProbCut is exercised");
    expect(result.late_move_prunes > 0,
           "late-move pruning is exercised");
    expect(result.history_hits > 0 && result.countermove_hits > 0,
            "history and countermove ordering are exercised");
  }

  {
    auto board = *parse_fen(
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    auto config = default_config();
    config.own_book = false;
    std::atomic_bool stopped{false};
    // The singular-extension precondition starts at depth six, but whether a
    // qualifying TT entry already exists there depends on the NNUE move order.
    // Depth eight exercises the mechanism for both validated architectures.
    SearchLimits limits; limits.depth = 8;
    Searcher searcher(config, stopped);
    const auto result = searcher.iterative(board, limits);
    expect(result.singular_extensions > 0,
           "true singular extensions are exercised");
  }

  {
    auto board = *parse_fen(
        "4k3/8/8/2qR4/4P3/8/8/4K3 b - - 0 1");
    expect(board.push_uci("c5d5"),
           "recapture regression records the preceding capture");
    auto config = default_config();
    config.own_book = false;
    std::atomic_bool stopped{false};
    SearchLimits limits; limits.depth = 3;
    Searcher searcher(config, stopped);
    const auto result = searcher.iterative(board, limits);
    expect(!result.pv.empty() && result.pv.front().uci() == "e4d5",
           "recapture extension preserves the winning queen recapture");
  }

  {
    auto board = *parse_fen(
        "1r5k/P7/8/8/8/8/8/7K w - - 0 1");
    auto config = default_config();
    config.own_book = false;
    std::atomic_bool stopped{false};
    SearchLimits limits; limits.depth = 4;
    Searcher searcher(config, stopped);
    const auto result = searcher.iterative(board, limits);
    expect(!result.pv.empty() && result.pv.front().uci() == "a7b8q",
           "selective pruning never removes the winning capture-promotion");
  }

  {
    const auto win = *parse_fen("7k/P7/2K5/8/8/8/8/8 w - - 0 1");
    const auto draw = *parse_fen("k7/P7/2K5/8/8/8/8/8 w - - 0 1");
    const auto black_win = *parse_fen("8/8/8/8/8/2k5/p7/7K b - - 0 1");
    const auto wrong_bishop =
        *parse_fen("k7/P7/2K5/8/8/8/8/2B5 w - - 0 1");
    expect(probe_exact_endgame(win) == ExactEndgame::white_win,
           "KPK bitbase recognizes a White win");
    expect(probe_exact_endgame(draw) == ExactEndgame::draw,
           "KPK bitbase recognizes a rook-pawn draw");
    expect(probe_exact_endgame(black_win) == ExactEndgame::black_win,
           "KPK bitbase mirrors Black wins exactly");
    expect(probe_exact_endgame(wrong_bishop) == ExactEndgame::draw,
           "wrong-colored bishop and rook pawn is recognized as a draw");
  }

  {
    auto budget_for = [](std::string_view fen, int remaining,
                         int increment = 0, int overhead = 50) {
      SearchLimits limits;
      limits.remaining_ms = remaining;
      limits.increment_ms = increment;
      limits.move_overhead_ms = overhead;
      return plan_time_budget(*parse_fen(fen), limits);
    };
    const auto opening = budget_for(initial_fen, 300'000);
    const auto incremented = budget_for(initial_fen, 300'000, 5'000);
    const auto high_overhead = budget_for(initial_fen, 300'000, 0, 4'000);
    const auto endgame = budget_for(
        "7r/8/8/8/8/2k5/6R1/4K3 w - - 0 1", 300'000);
    const auto pressure = budget_for(initial_fen, 90'000);
    const auto emergency = budget_for(initial_fen, 30'000);
    const auto panic = budget_for(initial_fen, 10'000);
    const auto last_seconds = budget_for(initial_fen, 3'000);

    expect(opening.mode == ClockMode::normal &&
               opening.soft_ms >= 3'000 && opening.soft_ms <= 5'000 &&
               opening.hard_ms <= 9'000 && opening.reserve_ms >= 15'000,
           "five-minute clock keeps an opening move near four seconds");
    expect(incremented.soft_ms > opening.soft_ms &&
               incremented.hard_ms <= 12'000,
           "increment adds bounded thinking time");
    expect(high_overhead.reserve_ms > opening.reserve_ms &&
               high_overhead.soft_ms < opening.soft_ms,
           "network overhead increases the protected reserve");
    expect(endgame.soft_ms > opening.soft_ms,
           "game phase allocates a larger safe share in the endgame");
    expect(pressure.mode == ClockMode::pressure && pressure.hard_ms <= 4'000,
           "ninety seconds activates pressure mode");
    expect(emergency.mode == ClockMode::emergency &&
               emergency.hard_ms <= 1'200,
           "thirty seconds activates an enforceable emergency ceiling");
    expect(panic.mode == ClockMode::panic && panic.hard_ms <= 250 &&
               panic.reserve_ms >= 2'500,
           "ten seconds activates panic mode and protects a quarter clock");
    expect(last_seconds.mode == ClockMode::panic &&
               last_seconds.hard_ms <= 50 &&
               last_seconds.reserve_ms >= 750,
           "last seconds force near-instant play");
    expect(opening.soft_ms <= opening.hard_ms &&
               opening.hard_ms + opening.reserve_ms < 300'000,
           "soft, hard, and reserve budgets remain internally consistent");

    auto panic_board = *parse_fen(initial_fen);
    auto panic_config = default_config();
    panic_config.own_book = false;
    std::atomic_bool panic_stopped{false};
    SearchLimits panic_limits;
    panic_limits.remaining_ms = 1'000;
    panic_limits.move_overhead_ms = 50;
    Searcher panic_searcher(panic_config, panic_stopped);
    const auto panic_result = panic_searcher.iterative(
        panic_board, panic_limits);
    expect(!panic_result.pv.empty() &&
               panic_board.position.apply(panic_result.pv.front()).has_value(),
           "deadline fallback always returns a legal move");
    expect(panic_result.elapsed.count() < 250,
           "panic search obeys its wall-clock deadline");

    auto forced = *parse_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1");
    auto config = default_config();
    config.own_book = false;
    std::atomic_bool stopped{false};
    SearchLimits limits; limits.depth = 1;
    Searcher searcher(config, stopped);
    const auto volatile_result = searcher.iterative(forced, limits);
    SearchLimits quiet_limits; quiet_limits.depth = 1;
    Searcher quiet_searcher(config, stopped);
    const auto quiet_result = quiet_searcher.iterative(
        *parse_fen(initial_fen), quiet_limits);
    expect(volatile_result.volatility > quiet_result.volatility,
           "checks and singular replies make a position more volatile");
  }

  {
    auto solve = [](const tactical_data::Case& tactic, int depth) {
      auto board = *parse_fen(tactic.fen);
      auto config = default_config();
      config.own_book = false; config.hash_mb = 4;
      std::atomic_bool stopped{false};
      SearchLimits limits; limits.depth = depth;
      Searcher searcher(config, stopped);
      return std::pair{board, searcher.iterative(board, limits)};
    };
    int mate_one = 0;
    for (const auto& tactic : tactical_data::mateIn1) {
      auto [board, result] = solve(tactic, 2);
      if (result.pv.empty() || !board.push(result.pv.front())) continue;
      if (board.legal_moves().empty() && board.position.in_check(board.turn))
        ++mate_one;
    }
    expect(mate_one == static_cast<int>(tactical_data::mateIn1.size()),
           "all CC0 mate-in-one positions are solved");

    int mate_two = 0;
    for (const auto& tactic : tactical_data::mateIn2) {
      auto [board, result] = solve(tactic, 4);
      if (!result.pv.empty() && result.pv.front().uci() == tactic.best &&
          result.mate == 2) ++mate_two;
    }
    expect(mate_two * 100 >=
               static_cast<int>(tactical_data::mateIn2.size()) * 95,
           "at least 95% of CC0 mate-in-two positions are solved exactly");

    int mate_three = 0;
    int quiet_check_searches = 0;
    for (const auto& tactic : tactical_data::mateIn3) {
      auto [board, result] = solve(tactic, 6);
      if (result.quiet_checks > 0) ++quiet_check_searches;
      if (!result.pv.empty() && result.pv.front().uci() == tactic.best &&
          result.mate == 3) {
        ++mate_three;
      } else {
        std::cerr << "mate-in-three miss: expected " << tactic.best
                  << ", got "
                  << (result.pv.empty() ? "0000" : result.pv.front().uci())
                  << ", mate " << result.mate << ", score "
                  << result.score_cp << '\n';
      }
    }
    expect(mate_three * 4 >=
               static_cast<int>(tactical_data::mateIn3.size()) * 3,
           "at least 75% of CC0 mate-in-three positions are solved exactly");
    expect(quiet_check_searches == 0,
            "quiescence excludes non-capturing checks outside check evasions");
  }

  {
    std::atomic_bool stopped{false};
    auto root_config = default_config();
    root_config.hash_mb = 4;
    Searcher root_splitter(root_config, stopped);
    expect(SearcherTestAccess::lane_count(root_splitter) == 3 &&
               !SearcherTestAccess::helpers_share_table(root_splitter),
           "root splitter owns exactly three lanes with private TT shards");
  }

  {
    const auto epd_path = std::filesystem::path(ELOI_TEST_DATA_DIR) /
                          "epd" / "v2_5_regressions.epd";
    const auto regressions = load_epd(epd_path);
    expect(regressions.size() == 15,
           "v2.5 EPD corpus loads every categorized regression");
    std::set<std::string> categories;
    const std::string prefix = "RootSplit: ";
    for (const EpdCase& test : regressions) {
        categories.insert(test.category);
        auto board = parse_fen(test.fen);
        expect(board.has_value(), prefix + test.id + ": regression FEN parses");
        if (!board) continue;
        const auto result = fixed_depth_search(*board, test.depth);
        const std::string move = best_uci(result);
        if (!test.best.empty())
          expect(move == test.best,
                 prefix + test.id + ": expected " + test.best + ", got " + move);
        if (!test.avoid.empty())
          expect(move != test.avoid,
                 prefix + test.id + ": forbidden online blunder repeated: " + move);
        if (test.expected_score)
          expect(result.score_cp == *test.expected_score,
                 prefix + test.id + ": expected score " +
                     std::to_string(*test.expected_score) + ", got " +
                     std::to_string(result.score_cp));
        if (test.stable_depths) {
          const auto shallow = fixed_depth_search(
              *board, test.stable_depths->first);
          const auto deep = fixed_depth_search(
              *board, test.stable_depths->second);
          expect(best_uci(shallow) == best_uci(deep),
                 prefix + test.id +
                     ": best move remains stable across quiescence depths");
          if (test.maximum_swing)
            expect(std::abs(shallow.score_cp - deep.score_cp) <=
                       *test.maximum_swing,
                   prefix + test.id + ": fixed-depth score swing " +
                       std::to_string(std::abs(
                           shallow.score_cp - deep.score_cp)) +
                       " exceeds " + std::to_string(*test.maximum_swing));
      }
    }
    constexpr std::array required_categories{
        "hanging_piece", "trapped_piece", "quiet_defense",
        "horizon_sacrifice", "mate_distance", "repetition_fifty",
        "passed_pawn_race", "fortress_insufficient",
        "quiescence_stability", "online_catastrophe"};
    for (const std::string_view category : required_categories)
      expect(categories.contains(std::string(category)),
             "v2.5 EPD corpus covers " + std::string(category));
  }

  if (failures) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "all tests passed\n";
  return EXIT_SUCCESS;
}
