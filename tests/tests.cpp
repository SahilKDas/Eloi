#include "morlock/chess.hpp"
#include "tactical_data.hpp"

#include <atomic>
#include <cstdlib>
#include <iostream>
#include <string>

using namespace morlock;

namespace {
int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void expect_perft(std::string_view fen, int depth, std::uint64_t expected) {
  std::string error;
  auto board = parse_fen(fen, &error);
  expect(board.has_value(), "parse perft FEN: " + error);
  if (!board) return;
  auto actual = perft(board->position, board->turn, depth);
  expect(actual == expected, "perft depth " + std::to_string(depth) + ": expected " +
                            std::to_string(expected) + ", got " + std::to_string(actual));
}
}  // namespace

int main() {
  static_assert(maximum_search_depth == 40,
                "Eloi's hard search ceiling must remain exactly 40 plies");
  {
    std::string error;
    auto board = parse_fen(initial_fen, &error);
    expect(board.has_value(), "initial FEN parses");
    if (board) expect(to_fen(*board) == initial_fen, "initial FEN round trip");
  }

  expect_perft(initial_fen, 1, 20);
  expect_perft(initial_fen, 2, 400);
  expect_perft(initial_fen, 3, 8902);
  expect_perft(initial_fen, 4, 197281);
  expect_perft("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862);
  expect_perft("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238);
  expect_perft("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/1PB1P1b1/P1NP1N2/2P1QPPP/R4RK1 b - b3 0 10", 1, 45);

  {
    auto board = *parse_fen(initial_fen);
    expect(board.push_uci("e2e4"), "e2e4 is legal");
    expect(board.position.en_passant == *parse_square("e3"), "double push sets en passant");
    expect(board.push_uci("a7a6") && board.push_uci("e4e5") && board.push_uci("d7d5"),
           "en-passant setup moves are legal");
    expect(board.push_uci("e5d6"), "en-passant capture is legal");
    expect(board.position.empty(*parse_square("d5")), "en-passant removes captured pawn");
  }

  {
    auto board = *parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
    expect(board.push_uci("e1g1"), "white king-side castle");
    expect(board.position.piece_at(*parse_square("f1")) == Piece::rook, "castling moves rook");
    expect(board.pop(), "take back castle");
    expect(board.push_uci("e1c1"), "white queen-side castle");
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
    const auto config = default_config(EngineKind::morlock);
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
    const auto config = default_config(EngineKind::morlock);
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
    const auto book = opening_move(default_config(EngineKind::morlock), board);
    expect(book && book->move.uci() == "f1c4",
           "Italian personality recognizes a transposition");
    auto disabled = default_config(EngineKind::morlock);
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
    auto config = default_config(EngineKind::morlock);
    config.own_book = false;
    Searcher searcher(config, stopped);
    auto result = searcher.iterative(board, limits);
    expect(result.depth == 4, "iterative search reaches requested depth");
    expect(result.lmr_reductions > 0, "late move reductions are exercised");
    expect(!result.pv.empty(), "search returns a principal variation");
    if (!result.pv.empty()) expect(board.push(result.pv.front()), "search best move is legal");
  }

  {
    auto solve = [](const tactical_data::Case& tactic, int depth) {
      auto board = *parse_fen(tactic.fen);
      auto config = default_config(EngineKind::morlock);
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
    for (const auto& tactic : tactical_data::mateIn3) {
      auto [board, result] = solve(tactic, 6);
      if (!result.pv.empty() && result.pv.front().uci() == tactic.best &&
          result.mate == 3) ++mate_three;
    }
    expect(mate_three * 4 >=
               static_cast<int>(tactical_data::mateIn3.size()) * 3,
           "at least 75% of CC0 mate-in-three positions are solved exactly");
  }

  if (failures) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "all tests passed\n";
  return EXIT_SUCCESS;
}
