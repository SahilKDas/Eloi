#include "eloi/chess.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <thread>

#if defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))
#include <immintrin.h>
#define ELOI_GNU_X86_BITOPS 1
#else
#define ELOI_GNU_X86_BITOPS 0
#endif

namespace eloi {
namespace {

constexpr int infinity = 32000;
constexpr int mate_score = 30000;

int color_index(Color c) { return c == Color::white ? 0 : 1; }

char piece_letter(Piece piece) {
  switch (piece) {
    case Piece::pawn: return 'p';
    case Piece::bishop: return 'b';
    case Piece::knight: return 'n';
    case Piece::rook: return 'r';
    case Piece::queen: return 'q';
    case Piece::king: return 'k';
    default: return '?';
  }
}

Piece char_piece(char c) {
  switch (static_cast<char>(std::tolower(static_cast<unsigned char>(c)))) {
    case 'p': return Piece::pawn;
    case 'b': return Piece::bishop;
    case 'n': return Piece::knight;
    case 'r': return Piece::rook;
    case 'q': return Piece::queen;
    case 'k': return Piece::king;
    default: return Piece::none;
  }
}

constexpr bool inside(int file, int rank) {
  return file >= 0 && file < 8 && rank >= 0 && rank < 8;
}

constexpr std::uint64_t square_bit(int square) {
  return square >= 0 && square < 64 ? (std::uint64_t{1} << square) : 0;
}

int pop_square(std::uint64_t& bits) {
  const int square = static_cast<int>(std::countr_zero(bits));
  bits &= bits - 1;
  return square;
}

using AttackTable = std::array<std::uint64_t, 64>;

consteval AttackTable make_step_attacks(
    const std::array<std::array<int, 2>, 8>& steps) {
  AttackTable table{};
  for (int square = 0; square < 64; ++square) {
    for (const auto& step : steps) {
      const int file = file_of(square) + step[0];
      const int rank = rank_of(square) + step[1];
      if (inside(file, rank)) table[square] |= square_bit(square_of(file, rank));
    }
  }
  return table;
}

consteval std::array<AttackTable, 2> make_pawn_attacks() {
  std::array<AttackTable, 2> tables{};
  for (int square = 0; square < 64; ++square) {
    for (int side = 0; side < 2; ++side) {
      const int rank_step = side == 0 ? 1 : -1;
      for (int file_step : {-1, 1}) {
        const int file = file_of(square) + file_step;
        const int rank = rank_of(square) + rank_step;
        if (inside(file, rank))
          tables[side][square] |= square_bit(square_of(file, rank));
      }
    }
  }
  return tables;
}

consteval std::array<AttackTable, 2> make_passed_pawn_masks() {
  std::array<AttackTable, 2> tables{};
  for (int side = 0; side < 2; ++side) {
    const int direction = side == 0 ? 1 : -1;
    for (int square = 0; square < 64; ++square) {
      for (int file = std::max(0, file_of(square) - 1);
           file <= std::min(7, file_of(square) + 1); ++file)
        for (int rank = rank_of(square) + direction; inside(file, rank);
             rank += direction)
          tables[side][square] |= square_bit(square_of(file, rank));
    }
  }
  return tables;
}

inline constexpr auto knight_attack_table = make_step_attacks({{
    {{1, 2}}, {{2, 1}}, {{2, -1}}, {{1, -2}},
    {{-1, -2}}, {{-2, -1}}, {{-2, 1}}, {{-1, 2}},
}});
inline constexpr auto king_attack_table = make_step_attacks({{
    {{1, 0}}, {{1, 1}}, {{0, 1}}, {{-1, 1}},
    {{-1, 0}}, {{-1, -1}}, {{0, -1}}, {{1, -1}},
}});
inline constexpr auto pawn_attack_table = make_pawn_attacks();
inline constexpr auto passed_pawn_masks = make_passed_pawn_masks();

std::uint64_t sliding_attacks_scalar(int square, std::uint64_t occupied,
                                     bool diagonal) {
  constexpr std::array<std::array<int, 2>, 4> rook_directions{{
      {{1, 0}}, {{-1, 0}}, {{0, 1}}, {{0, -1}},
  }};
  constexpr std::array<std::array<int, 2>, 4> bishop_directions{{
      {{1, 1}}, {{1, -1}}, {{-1, 1}}, {{-1, -1}},
  }};
  const auto& directions = diagonal ? bishop_directions : rook_directions;
  std::uint64_t attacks = 0;
  for (const auto& direction : directions) {
    int file = file_of(square) + direction[0];
    int rank = rank_of(square) + direction[1];
    while (inside(file, rank)) {
      const int target = square_of(file, rank);
      const std::uint64_t target_bit = square_bit(target);
      attacks |= target_bit;
      if (occupied & target_bit) break;
      file += direction[0];
      rank += direction[1];
    }
  }
  return attacks;
}

std::uint64_t slider_relevant_mask(int square, bool diagonal) {
  constexpr std::array<std::array<int, 2>, 4> rook_directions{{
      {{1, 0}}, {{-1, 0}}, {{0, 1}}, {{0, -1}},
  }};
  constexpr std::array<std::array<int, 2>, 4> bishop_directions{{
      {{1, 1}}, {{1, -1}}, {{-1, 1}}, {{-1, -1}},
  }};
  const auto& directions = diagonal ? bishop_directions : rook_directions;
  std::uint64_t mask = 0;
  for (const auto& direction : directions) {
    int file = file_of(square) + direction[0];
    int rank = rank_of(square) + direction[1];
    while (inside(file, rank)) {
      const int beyond_file = file + direction[0];
      const int beyond_rank = rank + direction[1];
      if (!inside(beyond_file, beyond_rank)) break;
      mask |= square_bit(square_of(file, rank));
      file = beyond_file;
      rank = beyond_rank;
    }
  }
  return mask;
}

std::uint64_t expand_occupancy(std::uint64_t index, std::uint64_t mask) {
  std::uint64_t occupied = 0;
  int bit_index = 0;
  while (mask) {
    const int square = pop_square(mask);
    if (index & (std::uint64_t{1} << bit_index))
      occupied |= square_bit(square);
    ++bit_index;
  }
  return occupied;
}

struct SliderAttackTables {
  std::array<std::uint64_t, 64> rook_masks{};
  std::array<std::uint64_t, 64> bishop_masks{};
  std::array<std::vector<std::uint64_t>, 64> rook{};
  std::array<std::vector<std::uint64_t>, 64> bishop{};

  SliderAttackTables() {
    for (int square = 0; square < 64; ++square) {
      rook_masks[square] = slider_relevant_mask(square, false);
      bishop_masks[square] = slider_relevant_mask(square, true);
      const std::size_t rook_size =
          std::size_t{1} << std::popcount(rook_masks[square]);
      const std::size_t bishop_size =
          std::size_t{1} << std::popcount(bishop_masks[square]);
      rook[square].resize(rook_size);
      bishop[square].resize(bishop_size);
      for (std::size_t index = 0; index < rook_size; ++index) {
        const auto occupied = expand_occupancy(index, rook_masks[square]);
        rook[square][index] =
            sliding_attacks_scalar(square, occupied, false);
      }
      for (std::size_t index = 0; index < bishop_size; ++index) {
        const auto occupied = expand_occupancy(index, bishop_masks[square]);
        bishop[square][index] =
            sliding_attacks_scalar(square, occupied, true);
      }
    }
  }
};

const SliderAttackTables& slider_attack_tables() {
  static const SliderAttackTables tables;
  return tables;
}

#if ELOI_GNU_X86_BITOPS
bool runtime_has_bmi2() {
  static const bool available = [] {
    __builtin_cpu_init();
    return __builtin_cpu_supports("bmi2");
  }();
  return available;
}

__attribute__((target("bmi2")))
std::uint64_t sliding_attacks_bmi2(int square, std::uint64_t occupied,
                                   bool diagonal) {
  const auto& tables = slider_attack_tables();
  const std::uint64_t mask = diagonal
      ? tables.bishop_masks[square] : tables.rook_masks[square];
  const std::size_t index =
      static_cast<std::size_t>(_pext_u64(occupied, mask));
  return diagonal ? tables.bishop[square][index]
                  : tables.rook[square][index];
}
#endif

std::uint64_t sliding_attacks(int square, std::uint64_t occupied,
                              bool diagonal) {
#if ELOI_GNU_X86_BITOPS
  if (runtime_has_bmi2())
    return sliding_attacks_bmi2(square, occupied, diagonal);
#endif
  return sliding_attacks_scalar(square, occupied, diagonal);
}

std::vector<std::string> split(std::string_view value) {
  std::istringstream input{std::string(value)};
  std::vector<std::string> result;
  for (std::string part; input >> part;) result.push_back(part);
  return result;
}

int nominal(Piece p) {
  switch (p) {
    case Piece::pawn: return 100;
    case Piece::bishop:
    case Piece::knight: return 300;
    case Piece::rook: return 500;
    case Piece::queen: return 900;
    case Piece::king: return 10000;
    default: return 0;
  }
}

int static_exchange_score(const Position& position, Color side,
                          const Move& move) {
  if (!move.is_capture()) return 0;
  int score = nominal(move.capture);
  const Piece landing = move.is_promotion() ? move.promotion : move.piece;
  if (move.is_promotion()) score += nominal(move.promotion) - nominal(Piece::pawn);
  if (position.attackers(opponent(side), move.to) > 0) {
    score -= nominal(landing);
    if (position.attackers(side, move.to) > 1) score += nominal(landing) / 2;
  }
  return score;
}

int king_distance(int a, int b) {
  return std::max(std::abs(file_of(a) - file_of(b)),
                  std::abs(rank_of(a) - rank_of(b)));
}

bool pawn_attacks(Color side, int from, int target) {
  const int step = side == Color::white ? 1 : -1;
  return rank_of(target) - rank_of(from) == step &&
         std::abs(file_of(target) - file_of(from)) == 1;
}

// Exact KPK knowledge. The table is solved as a win/draw reachability graph at
// first use; it occupies one byte per normalized state (512 KiB) and needs no
// runtime file or dependency.
class KpkBitbase {
 public:
  static constexpr std::size_t state_count = 2 * 64 * 64 * 64;

  KpkBitbase() {
    for (int turn = 0; turn < 2; ++turn)
      for (int pawn = 8; pawn < 56; ++pawn)
        for (int white_king = 0; white_king < 64; ++white_king)
          for (int black_king = 0; black_king < 64; ++black_king)
            valid_[index(turn, pawn, white_king, black_king)] =
                valid(turn, pawn, white_king, black_king);

    bool changed = true;
    while (changed) {
      changed = false;
      for (int turn = 0; turn < 2; ++turn)
        for (int pawn = 8; pawn < 56; ++pawn)
          for (int white_king = 0; white_king < 64; ++white_king)
            for (int black_king = 0; black_king < 64; ++black_king) {
              const std::size_t state = index(turn, pawn, white_king, black_king);
              if (!valid_[state] || wins_[state]) continue;
              const KpkMoves moves = successors(turn, pawn, white_king, black_king);
              bool is_win = false;
              if (turn == 0) {
                is_win = moves.terminal_win;
                for (int i = 0; i < moves.count && !is_win; ++i)
                  is_win = wins_[moves.next[i]] != 0;
              } else if (moves.count == 0) {
                is_win = moves.in_check;
              } else if (!moves.terminal_draw) {
                is_win = true;
                for (int i = 0; i < moves.count && is_win; ++i)
                  is_win = wins_[moves.next[i]] != 0;
              }
              if (is_win) { wins_[state] = 1; changed = true; }
            }
    }
  }

  bool win(int turn, int pawn, int white_king, int black_king) const {
    const std::size_t state = index(turn, pawn, white_king, black_king);
    return valid_[state] && wins_[state];
  }

 private:
  struct KpkMoves {
    std::array<std::size_t, 10> next{};
    int count{0};
    bool terminal_win{false};
    bool terminal_draw{false};
    bool in_check{false};
  };
  std::array<std::uint8_t, state_count> wins_{};
  std::array<std::uint8_t, state_count> valid_{};

  static constexpr std::size_t index(int turn, int pawn, int white_king,
                                     int black_king) {
    return (((static_cast<std::size_t>(turn) * 64 + pawn) * 64 + white_king) *
            64 + black_king);
  }

  static bool valid(int turn, int pawn, int white_king, int black_king) {
    if (pawn == white_king || pawn == black_king ||
        white_king == black_king || king_distance(white_king, black_king) <= 1)
      return false;
    if (rank_of(pawn) < 1 || rank_of(pawn) > 6) return false;
    return turn != 0 || !pawn_attacks(Color::white, pawn, black_king);
  }

  KpkMoves successors(int turn, int pawn, int white_king,
                      int black_king) const {
    KpkMoves result;
    result.in_check = pawn_attacks(Color::white, pawn, black_king);
    auto add = [&](int next_turn, int next_pawn, int next_white_king,
                   int next_black_king) {
      const std::size_t state =
          index(next_turn, next_pawn, next_white_king, next_black_king);
      if (valid_[state]) result.next[result.count++] = state;
    };
    if (turn == 0) {
      for (int df = -1; df <= 1; ++df)
        for (int dr = -1; dr <= 1; ++dr) {
          if ((!df && !dr) || !inside(file_of(white_king) + df,
                                      rank_of(white_king) + dr)) continue;
          const int to = square_of(file_of(white_king) + df,
                                   rank_of(white_king) + dr);
          if (to == pawn || to == black_king ||
              king_distance(to, black_king) <= 1) continue;
          add(1, pawn, to, black_king);
        }
      const int one = pawn + 8;
      if (one != black_king && one != white_king) {
        if (rank_of(one) == 7) {
          if (king_distance(black_king, one) > 1 ||
              king_distance(white_king, one) <= 1)
            result.terminal_win = true;
          else
            result.terminal_draw = true;
        } else {
          add(1, one, white_king, black_king);
          const int two = pawn + 16;
          if (rank_of(pawn) == 1 && two != black_king && two != white_king)
            add(1, two, white_king, black_king);
        }
      }
    } else {
      for (int df = -1; df <= 1; ++df)
        for (int dr = -1; dr <= 1; ++dr) {
          if ((!df && !dr) || !inside(file_of(black_king) + df,
                                      rank_of(black_king) + dr)) continue;
          const int to = square_of(file_of(black_king) + df,
                                   rank_of(black_king) + dr);
          if (to == white_king || king_distance(to, white_king) <= 1 ||
              pawn_attacks(Color::white, pawn, to)) continue;
          if (to == pawn) {
            result.terminal_draw = true;
            continue;
          }
          add(0, pawn, white_king, to);
        }
    }
    return result;
  }
};

std::optional<bool> kpk_win(const Board& board) {
  int pawn_square = -1, pawn_count = 0, other = 0;
  Color pawn_side = Color::white;
  for (int square = 0; square < 64; ++square) {
    const Piece piece = board.position.piece_at(square);
    if (piece == Piece::none || piece == Piece::king) continue;
    if (piece != Piece::pawn) { ++other; continue; }
    ++pawn_count;
    pawn_square = square;
    pawn_side = *board.position.color_at(square);
  }
  if (pawn_count != 1 || other != 0) return std::nullopt;
  int pawn_king = board.position.king_square(pawn_side);
  int defender_king = board.position.king_square(opponent(pawn_side));
  if (pawn_side == Color::black) {
    auto flip = [](int square) {
      return square_of(file_of(square), 7 - rank_of(square));
    };
    pawn_square = flip(pawn_square);
    pawn_king = flip(pawn_king);
    defender_king = flip(defender_king);
  }
  static const KpkBitbase bitbase;
  return bitbase.win(board.turn == pawn_side ? 0 : 1, pawn_square,
                     pawn_king, defender_king);
}

bool wrong_bishop_rook_pawn_draw(const Position& position) {
  for (Color attacker : {Color::white, Color::black}) {
    int bishop = -1, defender_non_king = 0, attacker_other = 0;
    std::vector<int> pawns;
    for (int square = 0; square < 64; ++square) {
      const auto color = position.color_at(square);
      if (!color) continue;
      const Piece piece = position.piece_at(square);
      if (*color == attacker) {
        if (piece == Piece::bishop && bishop < 0) bishop = square;
        else if (piece == Piece::pawn) pawns.push_back(square);
        else if (piece != Piece::king) ++attacker_other;
      } else if (piece != Piece::king) {
        ++defender_non_king;
      }
    }
    if (bishop < 0 || pawns.empty() || attacker_other || defender_non_king)
      continue;
    const int file = file_of(pawns.front());
    if ((file != 0 && file != 7) ||
        !std::all_of(pawns.begin(), pawns.end(),
                     [&](int square) { return file_of(square) == file; }))
      continue;
    const int corner = square_of(file, attacker == Color::white ? 7 : 0);
    if (((file_of(bishop) + rank_of(bishop)) & 1) ==
        ((file_of(corner) + rank_of(corner)) & 1)) continue;
    if (king_distance(position.king_square(opponent(attacker)), corner) <= 1)
      return true;
  }
  return false;
}

bool opposite_colored_bishops(const Position& position) {
  const std::uint64_t white_bishops =
      position.pieces(Color::white, Piece::bishop);
  const std::uint64_t black_bishops =
      position.pieces(Color::black, Piece::bishop);
  if (std::popcount(white_bishops) != 1 ||
      std::popcount(black_bishops) != 1)
    return false;
  const std::uint64_t allowed =
      white_bishops | black_bishops |
      position.pieces(Color::white, Piece::king) |
      position.pieces(Color::black, Piece::king) |
      position.pieces(Color::white, Piece::pawn) |
      position.pieces(Color::black, Piece::pawn);
  if (allowed != position.occupied) return false;
  const int white = static_cast<int>(std::countr_zero(white_bishops));
  const int black = static_cast<int>(std::countr_zero(black_bishops));
  return ((file_of(white) + rank_of(white)) & 1) !=
         ((file_of(black) + rank_of(black)) & 1);
}

bool passed_pawn(const Position& position, Color side, int square) {
  return !(position.pieces(opponent(side), Piece::pawn) &
           passed_pawn_masks[color_index(side)][square]);
}

int endgame_knowledge(const Board& board) {
  const Position& position = board.position;
  int adjustment = 0;
  std::array<int, 2> non_pawn_material{};
  std::array<int, 2> rooks{};
  std::array<int, 2> pawns{};
  std::array<int, 2> rook_square{-1, -1};
  std::array<int, 2> pawn_square{-1, -1};
  for (Color color : {Color::white, Color::black}) {
    const int side = color_index(color);
    const std::uint64_t bishops = position.pieces(color, Piece::bishop);
    const std::uint64_t knights = position.pieces(color, Piece::knight);
    const std::uint64_t rook_bits = position.pieces(color, Piece::rook);
    const std::uint64_t queens = position.pieces(color, Piece::queen);
    non_pawn_material[side] =
        300 * (std::popcount(bishops) + std::popcount(knights)) +
        500 * std::popcount(rook_bits) + 900 * std::popcount(queens);
    rooks[side] = std::popcount(rook_bits);
    if (rooks[side] == 1)
      rook_square[side] = static_cast<int>(std::countr_zero(rook_bits));

    std::uint64_t pawn_bits = position.pieces(color, Piece::pawn);
    pawns[side] = std::popcount(pawn_bits);
    if (pawns[side] == 1)
      pawn_square[side] = static_cast<int>(std::countr_zero(pawn_bits));
    while (pawn_bits) {
      const int square = pop_square(pawn_bits);
      if (passed_pawn(position, color, square)) {
        const int advance = color == Color::white ? rank_of(square)
                                                  : 7 - rank_of(square);
        const int promotion = square_of(file_of(square),
                                        color == Color::white ? 7 : 0);
        int moves = 7 - advance;
        if (board.turn == color && advance == 1) --moves;
        const bool outside_square =
            king_distance(position.king_square(opponent(color)), promotion) >
            moves;
        int bonus = advance * 12 + (outside_square ? 90 : 0);
        adjustment += board.turn == color ? bonus : -bonus;
      }
    }
  }

  // Direct and distant opposition/corresponding-square guidance matters most
  // when only kings and pawns remain.
  if (non_pawn_material[0] == 0 && non_pawn_material[1] == 0) {
    const int white_king = position.king_square(Color::white);
    const int black_king = position.king_square(Color::black);
    const int df = std::abs(file_of(white_king) - file_of(black_king));
    const int dr = std::abs(rank_of(white_king) - rank_of(black_king));
    if ((df == 0 && dr == 2) || (dr == 0 && df == 2) ||
        (df == dr && df > 0 && (df & 1) == 0))
      adjustment -= 35;  // The side not to move owns the opposition.
  }

  // Compact Lucena/Philidor classifiers for the canonical KRPKR geometry.
  for (Color attacker : {Color::white, Color::black}) {
    const int a = color_index(attacker), d = 1 - a;
    if (rooks[a] != 1 || rooks[d] != 1 || pawns[a] != 1 || pawns[d] != 0 ||
        non_pawn_material[a] != 500 || non_pawn_material[d] != 500) continue;
    const int relative_pawn_rank = attacker == Color::white
        ? rank_of(pawn_square[a]) : 7 - rank_of(pawn_square[a]);
    const int promotion = square_of(file_of(pawn_square[a]),
                                    attacker == Color::white ? 7 : 0);
    const bool lucena = relative_pawn_rank == 6 &&
        king_distance(position.king_square(attacker), promotion) <= 1 &&
        king_distance(position.king_square(opponent(attacker)), promotion) > 1;
    const int defender_rook_relative_rank = attacker == Color::white
        ? rank_of(rook_square[d]) : 7 - rank_of(rook_square[d]);
    const bool philidor = relative_pawn_rank <= 4 &&
        defender_rook_relative_rank == 5 &&
        file_of(position.king_square(opponent(attacker))) ==
            file_of(pawn_square[a]) &&
        (attacker == Color::white
             ? rank_of(position.king_square(opponent(attacker))) >
                   rank_of(pawn_square[a])
             : rank_of(position.king_square(opponent(attacker))) <
                   rank_of(pawn_square[a]));
    const int knowledge = lucena ? 260 : (philidor ? -220 : 0);
    adjustment += board.turn == attacker ? knowledge : -knowledge;
  }
  return adjustment;
}

void add_move(const Position& pos, Color side, MoveList& out, int from, int to,
              Piece piece, MoveType quiet = MoveType::normal) {
  if (!inside(file_of(to), rank_of(to))) return;
  const auto target = pos.color_at(to);
  if (target && *target == side) return;
  Move move;
  move.from = from;
  move.to = to;
  move.piece = piece;
  if (target) {
    move.type = MoveType::capture;
    move.capture = pos.piece_at(to);
  } else {
    move.type = quiet;
  }
  out.push_back(move);
}

}  // namespace

int static_exchange_evaluation(const Position& position, Color side,
                               const Move& move) {
  return static_exchange_score(position, side, move);
}

bool Move::is_capture() const {
  return type == MoveType::capture || type == MoveType::capture_promotion ||
         type == MoveType::en_passant;
}

bool Move::is_promotion() const {
  return type == MoveType::promotion || type == MoveType::capture_promotion;
}

bool Move::is_castle() const {
  return type == MoveType::king_castle || type == MoveType::queen_castle;
}

bool Move::same_coordinates(const Move& other) const {
  return from == other.from && to == other.to && promotion == other.promotion;
}

std::string Move::uci() const {
  if (from < 0 || to < 0) return "0000";
  std::string result = square_name(from) + square_name(to);
  if (promotion != Piece::none) result += piece_letter(promotion);
  return result;
}

std::string Move::describe() const {
  if (from < 0 || to < 0) return "invalid";
  if (type == MoveType::king_castle) return "0-0";
  if (type == MoveType::queen_castle) return "0-0-0";
  std::string result;
  if (piece != Piece::pawn && piece != Piece::none)
    result += static_cast<char>(std::toupper(piece_letter(piece)));
  result += square_name(from);
  result += is_capture() ? '*' : '-';
  result += square_name(to);
  if (is_promotion()) {
    result += '=';
    result += static_cast<char>(std::toupper(piece_letter(promotion)));
  }
  if (type == MoveType::en_passant) result += " e.p.";
  return result;
}

PackedMove pack_move(const Move& move) {
  if (move.from < 0 || move.from >= 64 || move.to < 0 || move.to >= 64)
    return 0;
  int promotion = 0;
  switch (move.promotion) {
    case Piece::queen: promotion = 1; break;
    case Piece::rook: promotion = 2; break;
    case Piece::bishop: promotion = 3; break;
    case Piece::knight: promotion = 4; break;
    default: break;
  }
  return static_cast<PackedMove>(
      1 + move.from + (move.to << 6) + (promotion << 12));
}

Move unpack_move(PackedMove packed) {
  if (!packed) return {};
  const unsigned value = static_cast<unsigned>(packed - 1);
  Move move;
  move.from = static_cast<int>(value & 63U);
  move.to = static_cast<int>((value >> 6) & 63U);
  switch ((value >> 12) & 7U) {
    case 1: move.promotion = Piece::queen; break;
    case 2: move.promotion = Piece::rook; break;
    case 3: move.promotion = Piece::bishop; break;
    case 4: move.promotion = Piece::knight; break;
    default: break;
  }
  return move;
}

int score_to_tt(int score, int ply) {
  constexpr int mate_threshold = mate_score - maximum_search_depth;
  if (score >= mate_threshold) return score + ply;
  if (score <= -mate_threshold) return score - ply;
  return score;
}

int score_from_tt(int score, int ply) {
  constexpr int mate_threshold = mate_score - maximum_search_depth;
  if (score >= mate_threshold) return score - ply;
  if (score <= -mate_threshold) return score + ply;
  return score;
}

void Position::clear_pieces() {
  cells.fill(0);
  piece_bits = {};
  color_bits = {};
  occupied = 0;
  king_squares = {-1, -1};
}

void Position::set_cell(int square, std::int8_t cell) {
  if (square < 0 || square >= 64) return;
  const std::int8_t previous = cells[square];
  if (previous == cell) return;
  const std::uint64_t bit = square_bit(square);
  auto remove = [&](std::int8_t value) {
    if (!value) return;
    const int side = value > 0 ? 0 : 1;
    const auto piece = static_cast<std::size_t>(
        std::abs(static_cast<int>(value)));
    piece_bits[side][piece] &= ~bit;
    color_bits[side] &= ~bit;
    if (piece == static_cast<std::size_t>(Piece::king) &&
        king_squares[side] == square)
      king_squares[side] = -1;
  };
  auto add = [&](std::int8_t value) {
    if (!value) return;
    const int side = value > 0 ? 0 : 1;
    const auto piece = static_cast<std::size_t>(
        std::abs(static_cast<int>(value)));
    piece_bits[side][piece] |= bit;
    color_bits[side] |= bit;
    if (piece == static_cast<std::size_t>(Piece::king))
      king_squares[side] = static_cast<std::int8_t>(square);
  };
  remove(previous);
  cells[square] = cell;
  add(cell);
  occupied = color_bits[0] | color_bits[1];
}

void Position::rebuild_bitboards() {
  piece_bits = {};
  color_bits = {};
  occupied = 0;
  king_squares = {-1, -1};
  for (int square = 0; square < 64; ++square) {
    const std::int8_t cell = cells[square];
    if (!cell) continue;
    const int side = cell > 0 ? 0 : 1;
    const auto piece = static_cast<std::size_t>(
        std::abs(static_cast<int>(cell)));
    const std::uint64_t bit = square_bit(square);
    piece_bits[side][piece] |= bit;
    color_bits[side] |= bit;
    if (piece == static_cast<std::size_t>(Piece::king))
      king_squares[side] = static_cast<std::int8_t>(square);
  }
  occupied = color_bits[0] | color_bits[1];
}

std::uint64_t Position::pieces(Color side, Piece piece) const {
  return piece_bits[color_index(side)][static_cast<std::size_t>(piece)];
}

std::uint64_t Position::occupancy(Color side) const {
  return color_bits[color_index(side)];
}

Piece Position::piece_at(int square) const {
  if (square < 0 || square >= 64) return Piece::none;
  return static_cast<Piece>(std::abs(static_cast<int>(cells[square])));
}

std::optional<Color> Position::color_at(int square) const {
  if (square < 0 || square >= 64 || cells[square] == 0) return std::nullopt;
  return cells[square] > 0 ? Color::white : Color::black;
}

bool Position::empty(int square) const { return !color_at(square).has_value(); }

int Position::king_square(Color side) const {
  return king_squares[color_index(side)];
}

int Position::attackers(Color side, int target) const {
  if (target < 0 || target >= 64) return 0;
  std::uint64_t sources = 0;
  sources |= pawn_attack_table[color_index(opponent(side))][target] &
             pieces(side, Piece::pawn);
  sources |= knight_attack_table[target] & pieces(side, Piece::knight);
  sources |= king_attack_table[target] & pieces(side, Piece::king);
  sources |= sliding_attacks(target, occupied, false) &
             (pieces(side, Piece::rook) | pieces(side, Piece::queen));
  sources |= sliding_attacks(target, occupied, true) &
             (pieces(side, Piece::bishop) | pieces(side, Piece::queen));
  return std::popcount(sources);
}

bool Position::attacked_by(Color side, int square) const { return attackers(side, square) > 0; }

bool Position::in_check(Color side) const {
  int king = king_square(side);
  return king >= 0 && attacked_by(opponent(side), king);
}

bool Position::insufficient_material() const {
  int knights = 0, bishops = 0, other = 0;
  int bishop_color = -1;
  bool same_bishop_color = true;
  for (int sq = 0; sq < 64; ++sq) {
    switch (piece_at(sq)) {
      case Piece::pawn:
      case Piece::rook:
      case Piece::queen: ++other; break;
      case Piece::knight: ++knights; break;
      case Piece::bishop:
        ++bishops;
        if (bishop_color < 0) bishop_color = (file_of(sq) + rank_of(sq)) & 1;
        else if (bishop_color != ((file_of(sq) + rank_of(sq)) & 1)) same_bishop_color = false;
        break;
      default: break;
    }
  }
  if (other) return false;
  if (knights + bishops <= 1) return true;
  return knights == 0 && same_bishop_color;
}

namespace {

int castling_slot(Color side, bool king_side) {
  return (side == Color::white ? 0 : 2) + (king_side ? 0 : 1);
}

std::uint8_t castling_right(Color side, bool king_side) {
  return static_cast<std::uint8_t>(1U << castling_slot(side, king_side));
}

int castling_king_destination(Color side, bool king_side) {
  return square_of(king_side ? 6 : 2, side == Color::white ? 0 : 7);
}

int castling_rook_destination(Color side, bool king_side) {
  return square_of(king_side ? 5 : 3, side == Color::white ? 0 : 7);
}

bool castling_path_clear(const Position& position, int king_from,
                         int rook_from, int king_to, int rook_to) {
  auto clear_segment = [&](int from, int to) {
    const int first = std::min(file_of(from), file_of(to));
    const int last = std::max(file_of(from), file_of(to));
    const int rank = rank_of(from);
    for (int file = first; file <= last; ++file) {
      const int square = square_of(file, rank);
      if (square != king_from && square != rook_from &&
          !position.empty(square)) return false;
    }
    return true;
  };
  return rank_of(king_from) == rank_of(rook_from) &&
         rank_of(king_from) == rank_of(king_to) &&
         rank_of(king_from) == rank_of(rook_to) &&
         clear_segment(king_from, king_to) &&
         clear_segment(rook_from, rook_to);
}

bool castling_king_path_safe(const Position& position, Color side,
                             int king_from, int rook_from, int king_to) {
  if (position.in_check(side)) return false;
  Position probe = position;
  probe.set_cell(king_from, 0);
  probe.set_cell(rook_from, 0);
  const int step = (file_of(king_to) > file_of(king_from)) -
                   (file_of(king_to) < file_of(king_from));
  if (!step) return true;
  for (int file = file_of(king_from) + step;; file += step) {
    const int square = square_of(file, rank_of(king_from));
    probe.set_cell(square, static_cast<std::int8_t>(
        (side == Color::white ? 1 : -1) * static_cast<int>(Piece::king)));
    const bool attacked = probe.attacked_by(opponent(side), square);
    probe.set_cell(square, 0);
    if (attacked) return false;
    if (file == file_of(king_to)) break;
  }
  return true;
}

void clear_castling_rights(Position& position, const Move& move,
                           Piece moving, Color side) {
  auto lose = [&](std::uint8_t rights) {
    position.castling &= static_cast<std::uint8_t>(~rights);
  };
  if (moving == Piece::king)
    lose(side == Color::white ? white_king | white_queen
                              : black_king | black_queen);
  for (int slot = 0; slot < 4; ++slot) {
    const std::uint8_t right = static_cast<std::uint8_t>(1U << slot);
    if ((position.castling & right) &&
        (move.from == position.castling_rooks[slot] ||
         move.to == position.castling_rooks[slot]))
      lose(right);
  }
}

}  // namespace

MoveList Position::pseudo_legal(Color side, bool horde) const {
  MoveList out;
  out.reserve(64);
  const std::uint64_t ours = occupancy(side);
  const int step = side == Color::white ? 1 : -1;
  const int start_rank = side == Color::white ? 1 : 6;
  const int promotion_rank = side == Color::white ? 7 : 0;

  std::uint64_t pawns = pieces(side, Piece::pawn);
  while (pawns) {
    const int from = pop_square(pawns);
    const int file = file_of(from);
    const int rank = rank_of(from);
    const int target_rank = rank + step;
    if (inside(file, target_rank)) {
      const int to = square_of(file, target_rank);
      if (!(occupied & square_bit(to))) {
        if (target_rank == promotion_rank) {
          for (Piece promotion :
               {Piece::queen, Piece::rook, Piece::knight, Piece::bishop})
            out.push_back({MoveType::promotion, from, to, Piece::pawn,
                           promotion, Piece::none});
        } else {
          out.push_back({MoveType::push, from, to, Piece::pawn});
          const int jump_rank = rank + 2 * step;
          if (inside(file, jump_rank) &&
              !(occupied & square_bit(square_of(file, jump_rank)))) {
            if (rank == start_rank)
              out.push_back({MoveType::jump, from,
                             square_of(file, jump_rank), Piece::pawn});
            else if (horde && side == Color::white && rank == 0)
              out.push_back({MoveType::horde_jump, from,
                             square_of(file, jump_rank), Piece::pawn});
          }
        }
      }
      for (int file_step : {-1, 1}) {
        const int capture_file = file + file_step;
        if (!inside(capture_file, target_rank)) continue;
        const int to = square_of(capture_file, target_rank);
        if (color_at(to) == opponent(side)) {
          const Piece captured = piece_at(to);
          if (target_rank == promotion_rank) {
            for (Piece promotion :
                 {Piece::queen, Piece::rook, Piece::knight, Piece::bishop})
              out.push_back({MoveType::capture_promotion, from, to,
                             Piece::pawn, promotion, captured});
          } else {
            out.push_back({MoveType::capture, from, to, Piece::pawn,
                           Piece::none, captured});
          }
        } else if (to == en_passant) {
          const int victim = to - step * 8;
          if (color_at(victim) == opponent(side) &&
              piece_at(victim) == Piece::pawn)
            out.push_back({MoveType::en_passant, from, to, Piece::pawn,
                           Piece::none, Piece::pawn});
        }
      }
    }
  }

  auto add_targets = [&](Piece piece, std::uint64_t sources,
                         auto attacks) {
    while (sources) {
      const int from = pop_square(sources);
      std::uint64_t targets = attacks(from) & ~ours;
      while (targets) {
        const int to = pop_square(targets);
        add_move(*this, side, out, from, to, piece);
      }
    }
  };
  add_targets(Piece::knight, pieces(side, Piece::knight),
              [](int from) { return knight_attack_table[from]; });
  add_targets(Piece::bishop, pieces(side, Piece::bishop),
              [&](int from) { return sliding_attacks(from, occupied, true); });
  add_targets(Piece::rook, pieces(side, Piece::rook),
              [&](int from) { return sliding_attacks(from, occupied, false); });
  add_targets(Piece::queen, pieces(side, Piece::queen), [&](int from) {
    return sliding_attacks(from, occupied, false) |
           sliding_attacks(from, occupied, true);
  });

  std::uint64_t kings = pieces(side, Piece::king);
  if (kings) {
    const int from = pop_square(kings);
    std::uint64_t targets = king_attack_table[from] & ~ours;
    while (targets) {
      const int to = pop_square(targets);
      add_move(*this, side, out, from, to, Piece::king);
    }
    const int home_rank = side == Color::white ? 0 : 7;
    if (rank_of(from) == home_rank) {
      for (const bool king_side : {true, false}) {
        const int slot = castling_slot(side, king_side);
        const std::uint8_t right = castling_right(side, king_side);
        const int rook_from = castling_rooks[slot];
        const int king_to = castling_king_destination(side, king_side);
        const int rook_to = castling_rook_destination(side, king_side);
        if ((castling & right) && rook_from >= 0 && rook_from < 64 &&
            color_at(rook_from) == side &&
            piece_at(rook_from) == Piece::rook &&
            castling_path_clear(*this, from, rook_from, king_to, rook_to))
          out.push_back({king_side ? MoveType::king_castle
                                   : MoveType::queen_castle,
                         from, king_to, Piece::king});
      }
    }
  }
  return out;
}

std::optional<Position> Position::apply(const Move& move) const {
  if (move.from < 0 || move.from >= 64 || move.to < 0 || move.to >= 64 || empty(move.from))
    return std::nullopt;
  const Color side = *color_at(move.from);
  const int sign = side == Color::white ? 1 : -1;
  const Piece moving = piece_at(move.from);
  if (move.is_castle()) {
    const bool king_side = move.type == MoveType::king_castle;
    const int slot = castling_slot(side, king_side);
    const std::uint8_t right = castling_right(side, king_side);
    const int rook_from = castling_rooks[slot];
    const int king_to = castling_king_destination(side, king_side);
    const int rook_to = castling_rook_destination(side, king_side);
    if (moving != Piece::king || !(castling & right) || move.to != king_to ||
        rook_from < 0 || rook_from >= 64 || color_at(rook_from) != side ||
        piece_at(rook_from) != Piece::rook ||
        !castling_path_clear(*this, move.from, rook_from, king_to, rook_to) ||
        !castling_king_path_safe(*this, side, move.from, rook_from, king_to))
      return std::nullopt;
    Position next = *this;
    next.set_cell(move.from, 0);
    next.set_cell(rook_from, 0);
    next.set_cell(king_to, static_cast<std::int8_t>(
        sign * static_cast<int>(Piece::king)));
    next.set_cell(rook_to, static_cast<std::int8_t>(
        sign * static_cast<int>(Piece::rook)));
    next.en_passant = -1;
    clear_castling_rights(next, move, moving, side);
    if (next.in_check(side)) return std::nullopt;
    return next;
  }
  if (color_at(move.to) == side) return std::nullopt;
  Position next = *this;
  next.set_cell(move.from, 0);
  if (move.type == MoveType::en_passant) {
    int victim = move.to + (side == Color::white ? -8 : 8);
    next.set_cell(victim, 0);
  }
  Piece placed = move.is_promotion() ? move.promotion : moving;
  next.set_cell(move.to, static_cast<std::int8_t>(
      sign * static_cast<int>(placed)));
  next.en_passant = move.type == MoveType::jump ? (move.from + move.to) / 2 : -1;
  clear_castling_rights(next, move, moving, side);
  if (next.in_check(side)) return std::nullopt;
  return next;
}

MoveList Position::legal(Color side, bool horde) const {
  MoveList result;
  for (const Move& move : pseudo_legal(side, horde))
    if (apply(move)) result.push_back(move);
  return result;
}

MoveList Board::legal_moves() const { return position.legal(turn, horde); }

namespace {

constexpr std::uint64_t splitmix64(std::uint64_t value) {
  value += 0x9e3779b97f4a7c15ULL;
  value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
  value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
  return value ^ (value >> 31);
}

constexpr std::uint64_t zobrist_value(std::uint64_t index) {
  return splitmix64(0xE101C0265A17ULL + index * 0x9e3779b97f4a7c15ULL);
}

int effective_en_passant(const Position& position, Color turn) {
  if (position.en_passant < 0) return -1;
  for (const Move& move : position.pseudo_legal(turn)) {
    if (move.type == MoveType::en_passant && position.apply(move))
      return position.en_passant;
  }
  return -1;
}

std::array<std::uint64_t, 4> pack_cells(const Position& position) {
  std::array<std::uint64_t, 4> packed{};
  for (int square = 0; square < 64; ++square) {
    const auto value = static_cast<std::uint64_t>(position.cells[square] + 6);
    packed[square / 16] |= value << ((square % 16) * 4);
  }
  return packed;
}

void unpack_cells(Position& position,
                  const std::array<std::uint64_t, 4>& packed) {
  for (int square = 0; square < 64; ++square) {
    const auto value = static_cast<std::int8_t>(
        (packed[square / 16] >> ((square % 16) * 4)) & 0x0fU);
    position.cells[square] = static_cast<std::int8_t>(value - 6);
  }
  position.rebuild_bitboards();
}

std::uint64_t cell_key(std::int8_t cell, int square) {
  if (!cell) return 0;
  const int color = cell < 0 ? 1 : 0;
  const int piece = std::abs(static_cast<int>(cell)) - 1;
  return zobrist_value(static_cast<std::uint64_t>(
      (color * 6 + piece) * 64 + square));
}

std::uint64_t castling_key_for_rook(int rook_square, int bit) {
  const int file = file_of(rook_square);
  const int orthodox_file = (bit & 1) ? 0 : 7;
  // Preserve all historical standard-chess keys because the embedded opening
  // table is keyed with them. Nonstandard rook origins use disjoint space.
  const std::uint64_t index = file == orthodox_file
      ? 768 + bit
      : 781 + bit * 8 + file;
  return zobrist_value(index);
}

std::uint64_t castling_key(const Position& position, int bit) {
  return castling_key_for_rook(position.castling_rooks[bit], bit);
}

std::uint64_t updated_position_key(std::uint64_t key,
                                   const Position& before, Color before_turn,
                                   const Position& after, Color after_turn) {
  for (int square = 0; square < 64; ++square) {
    if (before.cells[square] == after.cells[square]) continue;
    key ^= cell_key(before.cells[square], square);
    key ^= cell_key(after.cells[square], square);
  }
  for (int bit = 0; bit < 4; ++bit) {
    if (before.castling & (1U << bit))
      key ^= castling_key(before, bit);
    if (after.castling & (1U << bit))
      key ^= castling_key(after, bit);
  }
  if (before_turn != after_turn) key ^= zobrist_value(772);
  const int before_ep = effective_en_passant(before, before_turn);
  const int after_ep = effective_en_passant(after, after_turn);
  if (before_ep >= 0) key ^= zobrist_value(773 + file_of(before_ep));
  if (after_ep >= 0) key ^= zobrist_value(773 + file_of(after_ep));
  return key;
}

std::uint64_t updated_search_key_delta(
    std::uint64_t key, const Board::SearchUndo& undo,
    const Position& after, Color after_turn) {
  for (std::uint8_t changed = 0; changed < undo.changed; ++changed) {
    const int square = undo.squares[changed];
    key ^= cell_key(undo.cells[changed], square);
    key ^= cell_key(after.cells[square], square);
  }
  for (int bit = 0; bit < 4; ++bit) {
    const std::uint8_t right = static_cast<std::uint8_t>(1U << bit);
    if ((undo.castling & right) == (after.castling & right)) continue;
    if (undo.castling & right)
      key ^= castling_key_for_rook(undo.castling_rooks[bit], bit);
    if (after.castling & right)
      key ^= castling_key(after, bit);
  }
  if (undo.turn != after_turn) key ^= zobrist_value(772);
  if (undo.effective_en_passant >= 0)
    key ^= zobrist_value(773 + file_of(undo.effective_en_passant));
  const int after_ep = after.en_passant >= 0
      ? effective_en_passant(after, after_turn) : -1;
  if (after_ep >= 0) key ^= zobrist_value(773 + file_of(after_ep));
  return key;
}

}  // namespace

std::uint64_t position_key(const Position& position, Color turn) {
  std::uint64_t key = 0;
  for (int square = 0; square < 64; ++square) {
    const auto cell = position.cells[square];
    if (!cell) continue;
    const int color = cell < 0 ? 1 : 0;
    const int piece = std::abs(static_cast<int>(cell)) - 1;
    key ^= zobrist_value(static_cast<std::uint64_t>(
        (color * 6 + piece) * 64 + square));
  }
  for (int bit = 0; bit < 4; ++bit)
    if (position.castling & (1U << bit))
      key ^= castling_key(position, bit);
  if (turn == Color::black) key ^= zobrist_value(772);
  const int ep = effective_en_passant(position, turn);
  if (ep >= 0) key ^= zobrist_value(773 + file_of(ep));
  return key;
}

bool Board::push(const Move& move) {
  auto next = position.apply(move);
  if (!next) return false;
  history.push_back({turn, halfmove, fullmove, move, has_castled,
                     position.castling,
                     position.castling_rooks,
                     static_cast<std::int8_t>(position.en_passant),
                     static_cast<std::int8_t>(effective_en_passant(position, turn)),
                     key, pack_cells(position)});
  const Position before = position;
  position = *next;
  nnue_update(nnue, before, position);
  if (move.is_castle()) has_castled[color_index(turn)] = true;
  halfmove = (move.piece == Piece::pawn || move.is_capture() || move.is_castle()) ? 0 : halfmove + 1;
  if (turn == Color::black) ++fullmove;
  const Color previous_turn = turn;
  turn = opponent(turn);
  key = updated_position_key(key, before, previous_turn, position, turn);
  return true;
}

bool Board::push_uci(std::string_view text) {
  auto parsed = parse_uci_move(text);
  if (!parsed) return false;
  for (const Move& move : legal_moves()) {
    if (move.same_coordinates(*parsed)) return push(move);
    if (chess960 && move.is_castle() && parsed->from == move.from) {
      const bool king_side = move.type == MoveType::king_castle;
      const int rook_from = position.castling_rooks[
          castling_slot(turn, king_side)];
      if (parsed->to == rook_from) return push(move);
    }
  }
  return false;
}

bool Board::pop() {
  if (history.empty()) return false;
  auto state = history.back(); history.pop_back();
  const Position after = position;
  unpack_cells(position, state.packed_cells);
  position.castling = state.castling;
  position.castling_rooks = state.castling_rooks;
  position.en_passant = state.en_passant;
  turn = state.turn; halfmove = state.halfmove;
  fullmove = state.fullmove; has_castled = state.has_castled;
  nnue_update(nnue, after, position);
  key = state.key;
  return true;
}

bool Board::make_search_move(const Move& move, SearchUndo& undo) {
  if (move.from < 0 || move.from >= 64 || move.to < 0 || move.to >= 64 ||
      position.color_at(move.from) != turn ||
      (!move.is_castle() && position.color_at(move.to) == turn))
    return false;

  undo = {};
  undo.turn = turn;
  undo.halfmove = halfmove;
  undo.fullmove = fullmove;
  undo.has_castled = has_castled;
  undo.castling = position.castling;
  undo.castling_rooks = position.castling_rooks;
  undo.en_passant = static_cast<std::int8_t>(position.en_passant);
  undo.effective_en_passant = static_cast<std::int8_t>(
      position.en_passant >= 0
          ? effective_en_passant(position, turn) : -1);
  undo.king_squares = position.king_squares;
  undo.key = key;
  undo.move = move;

  auto remember = [&](int square) {
    for (int index = 0; index < undo.changed; ++index)
      if (undo.squares[index] == square) return;
    if (undo.changed < undo.squares.size()) {
      undo.squares[undo.changed] = static_cast<std::uint8_t>(square);
      undo.cells[undo.changed] = position.cells[square];
      ++undo.changed;
    }
  };

  const Color side = turn;
  const Piece moving = position.piece_at(move.from);
  const int sign = side == Color::white ? 1 : -1;
  if (move.is_castle()) {
    const auto next = position.apply(move);
    if (!next) return false;
    for (int square = 0; square < 64; ++square)
      if (position.cells[square] != next->cells[square]) remember(square);
    position = *next;
  } else {
    remember(move.from);
    remember(move.to);
    position.set_cell(move.from, 0);
    if (move.type == MoveType::en_passant) {
      const int victim = move.to + (side == Color::white ? -8 : 8);
      remember(victim);
      position.set_cell(victim, 0);
    }
    const Piece placed = move.is_promotion() ? move.promotion : moving;
    position.set_cell(move.to, static_cast<std::int8_t>(
        sign * static_cast<int>(placed)));
    position.en_passant = move.type == MoveType::jump
        ? (move.from + move.to) / 2 : -1;
    clear_castling_rights(position, move, moving, side);
  }

  if (position.in_check(side)) {
    for (int index = 0; index < undo.changed; ++index)
      position.set_cell(undo.squares[index], undo.cells[index]);
    position.castling = undo.castling;
    position.castling_rooks = undo.castling_rooks;
    position.en_passant = undo.en_passant;
    return false;
  }

  nnue_update_delta(nnue, undo.king_squares, position, undo.squares,
                    undo.cells, undo.changed);
  if (move.is_castle()) has_castled[color_index(side)] = true;
  halfmove = moving == Piece::pawn || move.is_capture() || move.is_castle()
      ? 0 : halfmove + 1;
  if (side == Color::black) ++fullmove;
  turn = opponent(side);
  key = updated_search_key_delta(undo.key, undo, position, turn);
  return true;
}

void Board::unmake_search_move(const SearchUndo& undo) {
  const auto after_kings = position.king_squares;
  std::array<std::int8_t, 4> after_cells{};
  for (int index = 0; index < undo.changed; ++index) {
    after_cells[index] = position.cells[undo.squares[index]];
    position.set_cell(undo.squares[index], undo.cells[index]);
  }
  position.castling = undo.castling;
  position.castling_rooks = undo.castling_rooks;
  position.en_passant = undo.en_passant;
  turn = undo.turn;
  halfmove = undo.halfmove;
  fullmove = undo.fullmove;
  has_castled = undo.has_castled;
  if (!undo.null_move)
    nnue_update_delta(nnue, after_kings, position, undo.squares,
                      after_cells, undo.changed);
  key = undo.key;
}

void Board::make_null_move(SearchUndo& undo) {
  undo = {};
  undo.turn = turn;
  undo.halfmove = halfmove;
  undo.fullmove = fullmove;
  undo.has_castled = has_castled;
  undo.castling = position.castling;
  undo.castling_rooks = position.castling_rooks;
  undo.en_passant = static_cast<std::int8_t>(position.en_passant);
  undo.effective_en_passant = static_cast<std::int8_t>(
      position.en_passant >= 0
          ? effective_en_passant(position, turn) : -1);
  undo.king_squares = position.king_squares;
  undo.key = key;
  undo.null_move = true;
  if (undo.effective_en_passant >= 0)
    key ^= zobrist_value(773 + file_of(undo.effective_en_passant));
  key ^= zobrist_value(772);
  position.en_passant = -1;
  ++halfmove;
  turn = opponent(turn);
}

std::optional<Move> Board::last_move() const {
  if (history.empty()) return std::nullopt;
  return history.back().move;
}

std::optional<Move> Board::second_last_move() const {
  if (history.size() < 2) return std::nullopt;
  return history[history.size() - 2].move;
}

bool Board::has_moved_from(int square) const {
  return std::any_of(history.begin(), history.end(),
                     [square](const Snapshot& s) { return s.move.from == square; });
}

int Board::repetition_count() const {
  int count = 1;
  const auto packed = pack_cells(position);
  const int ep = effective_en_passant(position, turn);
  for (const Snapshot& state : history) {
    if (state.key == key && state.turn == turn &&
        state.castling == position.castling &&
        state.castling_rooks == position.castling_rooks &&
        state.effective_en_passant == ep && state.packed_cells == packed)
      ++count;
  }
  return count;
}

bool Board::is_threefold_repetition() const { return repetition_count() >= 3; }

bool Board::is_fifty_move_draw() const { return halfmove >= 100; }

bool Board::horde_eliminated() const {
  return horde && position.occupancy(Color::white) == 0;
}

std::optional<Color> Board::variant_winner() const {
  if (horde_eliminated()) return Color::black;
  if (legal_moves().empty() && position.in_check(turn))
    return opponent(turn);
  return std::nullopt;
}

std::optional<int> parse_square(std::string_view text) {
  if (text.size() != 2) return std::nullopt;
  char file = static_cast<char>(std::tolower(static_cast<unsigned char>(text[0])));
  if (file < 'a' || file > 'h' || text[1] < '1' || text[1] > '8') return std::nullopt;
  return square_of(file - 'a', text[1] - '1');
}

std::string square_name(int square) {
  if (square < 0 || square >= 64) return "??";
  std::string result(2, ' ');
  result[0] = static_cast<char>('a' + file_of(square));
  result[1] = static_cast<char>('1' + rank_of(square));
  return result;
}

std::optional<Move> parse_uci_move(std::string_view text) {
  if (text.size() != 4 && text.size() != 5) return std::nullopt;
  auto from = parse_square(text.substr(0, 2)), to = parse_square(text.substr(2, 2));
  if (!from || !to) return std::nullopt;
  Move result; result.from = *from; result.to = *to;
  if (text.size() == 5) {
    result.promotion = char_piece(text[4]);
    if (result.promotion == Piece::none || result.promotion == Piece::pawn ||
        result.promotion == Piece::king) return std::nullopt;
  }
  return result;
}

std::string uci_move(const Move& move, const Position& position,
                     bool chess960) {
  if (!chess960 || !move.is_castle()) return move.uci();
  const auto side = position.color_at(move.from);
  if (!side) return move.uci();
  const bool king_side = move.type == MoveType::king_castle;
  const int rook_from = position.castling_rooks[
      castling_slot(*side, king_side)];
  if (rook_from < 0 || rook_from >= 64) return move.uci();
  return square_name(move.from) + square_name(rook_from);
}

std::optional<Board> parse_fen(std::string_view fen, std::string* error) {
  auto fail = [&](std::string message) -> std::optional<Board> {
    if (error) *error = std::move(message);
    return std::nullopt;
  };
  auto fields = split(fen);
  if (fields.size() != 6) return fail("FEN must contain six fields");
  Board board; board.position.clear_pieces(); board.position.castling = 0;
  int rank = 7, file = 0;
  for (char c : fields[0]) {
    if (c == '/') {
      if (file != 8 || rank == 0) return fail("invalid piece placement");
      --rank; file = 0; continue;
    }
    if (c >= '1' && c <= '8') { file += c - '0'; if (file > 8) return fail("invalid rank width"); continue; }
    Piece piece = char_piece(c);
    if (piece == Piece::none || file >= 8) return fail("invalid piece placement");
    int sign = std::isupper(static_cast<unsigned char>(c)) ? 1 : -1;
    board.position.set_cell(square_of(file++, rank),
                            static_cast<std::int8_t>(
                                sign * static_cast<int>(piece)));
  }
  if (rank != 0 || file != 8) return fail("invalid piece placement");
  if (fields[1] == "w") board.turn = Color::white;
  else if (fields[1] == "b") board.turn = Color::black;
  else return fail("invalid active color");
  if (fields[2] != "-") for (char c : fields[2]) {
    const bool white = std::isupper(static_cast<unsigned char>(c));
    const Color side = white ? Color::white : Color::black;
    const char lower = static_cast<char>(
        std::tolower(static_cast<unsigned char>(c)));
    const int home_rank = white ? 0 : 7;
    const int king = board.position.king_square(side);
    if (king < 0 || rank_of(king) != home_rank)
      return fail("castling right requires a king on its home rank");

    bool king_side = false;
    int rook_file = -1;
    if (lower == 'k' || lower == 'q') {
      king_side = lower == 'k';
      if (king_side) {
        for (int candidate = 7; candidate > file_of(king); --candidate) {
          const int square = square_of(candidate, home_rank);
          if (board.position.color_at(square) == side &&
              board.position.piece_at(square) == Piece::rook) {
            rook_file = candidate;
            break;
          }
        }
      } else {
        for (int candidate = 0; candidate < file_of(king); ++candidate) {
          const int square = square_of(candidate, home_rank);
          if (board.position.color_at(square) == side &&
              board.position.piece_at(square) == Piece::rook) {
            rook_file = candidate;
            break;
          }
        }
      }
      if (rook_file < 0) rook_file = king_side ? 7 : 0;
    } else if (lower >= 'a' && lower <= 'h') {
      rook_file = lower - 'a';
      const int rook = square_of(rook_file, home_rank);
      if (board.position.color_at(rook) != side ||
          board.position.piece_at(rook) != Piece::rook ||
          rook_file == file_of(king))
        return fail("Chess960 castling right does not name a valid rook");
      king_side = rook_file > file_of(king);
      board.chess960 = true;
    } else {
      return fail("invalid castling rights");
    }

    const int slot = castling_slot(side, king_side);
    const std::uint8_t right = castling_right(side, king_side);
    if (board.position.castling & right)
      return fail("duplicate castling right on one side of the king");
    board.position.castling |= right;
    board.position.castling_rooks[slot] = static_cast<std::int8_t>(
        square_of(rook_file, home_rank));
    const int orthodox_rook_file = king_side ? 7 : 0;
    if (file_of(king) != 4 || rook_file != orthodox_rook_file)
      board.chess960 = true;
  }
  board.position.en_passant = -1;
  if (fields[3] != "-") {
    auto sq = parse_square(fields[3]); if (!sq) return fail("invalid en passant square");
    board.position.en_passant = *sq;
  }
  try {
    std::size_t used = 0;
    board.halfmove = std::stoi(fields[4], &used); if (used != fields[4].size() || board.halfmove < 0) throw 0;
    board.fullmove = std::stoi(fields[5], &used); if (used != fields[5].size() || board.fullmove < 1) throw 0;
  } catch (...) { return fail("invalid move counters"); }
  board.nnue = nnue_refresh(board.position);
  board.key = position_key(board.position, board.turn);
  return board;
}

std::optional<Board> chess960_start(int index) {
  if (index < 0 || index >= 960) return std::nullopt;
  int code = index;
  std::array<char, 8> back{};
  back.fill(' ');
  back[(code % 4) * 2 + 1] = 'B';
  code /= 4;
  back[(code % 4) * 2] = 'B';
  code /= 4;

  auto empty_files = [&] {
    std::vector<int> result;
    for (int file = 0; file < 8; ++file)
      if (back[file] == ' ') result.push_back(file);
    return result;
  };
  auto empty = empty_files();
  back[empty[code % 6]] = 'Q';
  code /= 6;

  empty = empty_files();
  int combination = code % 10;
  int first = 0;
  while (combination >= 4 - first) {
    combination -= 4 - first;
    ++first;
  }
  const int second = first + 1 + combination;
  back[empty[first]] = 'N';
  back[empty[second]] = 'N';

  empty = empty_files();
  back[empty[0]] = 'R';
  back[empty[1]] = 'K';
  back[empty[2]] = 'R';

  std::string white(back.begin(), back.end());
  std::string black = white;
  std::ranges::transform(black, black.begin(), [](unsigned char character) {
    return static_cast<char>(std::tolower(character));
  });
  const int king_file = static_cast<int>(white.find('K'));
  const int queen_rook_file = static_cast<int>(white.find('R'));
  const int king_rook_file = static_cast<int>(white.find('R', king_file + 1));
  std::string rights;
  rights += static_cast<char>('A' + king_rook_file);
  rights += static_cast<char>('A' + queen_rook_file);
  rights += static_cast<char>('a' + king_rook_file);
  rights += static_cast<char>('a' + queen_rook_file);
  return parse_fen(black + "/pppppppp/8/8/8/8/PPPPPPPP/" + white +
                   " w " + rights + " - 0 1");
}

std::string to_fen(const Board& board) {
  std::ostringstream out;
  for (int rank = 7; rank >= 0; --rank) {
    int blanks = 0;
    for (int file = 0; file < 8; ++file) {
      int sq = square_of(file, rank);
      if (board.position.empty(sq)) { ++blanks; continue; }
      if (blanks) { out << blanks; blanks = 0; }
      char c = piece_letter(board.position.piece_at(sq));
      if (board.position.color_at(sq) == Color::white) c = static_cast<char>(std::toupper(c));
      out << c;
    }
    if (blanks) out << blanks;
    if (rank) out << '/';
  }
  out << (board.turn == Color::white ? " w " : " b ");
  if (!board.position.castling) out << '-';
  else {
    for (int slot = 0; slot < 4; ++slot) {
      if (!(board.position.castling & (1U << slot))) continue;
      if (board.chess960) {
        char right = static_cast<char>(
            'a' + file_of(board.position.castling_rooks[slot]));
        if (slot < 2) right = static_cast<char>(
            std::toupper(static_cast<unsigned char>(right)));
        out << right;
      } else {
        constexpr char orthodox[4] = {'K', 'Q', 'k', 'q'};
        out << orthodox[slot];
      }
    }
  }
  out << ' ' << (board.position.en_passant < 0 ? "-" : square_name(board.position.en_passant));
  out << ' ' << board.halfmove << ' ' << board.fullmove;
  return out.str();
}

std::string board_ascii(const Board& board) {
  std::ostringstream out;
  out << "    a   b   c   d   e   f   g   h\n  ---------------------------------\n";
  for (int rank = 7; rank >= 0; --rank) {
    out << rank + 1 << " |";
    for (int file = 0; file < 8; ++file) {
      int sq = square_of(file, rank); char c = ' ';
      if (!board.position.empty(sq)) {
        c = piece_letter(board.position.piece_at(sq));
        if (board.position.color_at(sq) == Color::white) c = static_cast<char>(std::toupper(c));
      }
      out << ' ' << c << " |";
    }
    out << "\n  ---------------------------------\n";
  }
  out << "fen: " << to_fen(board) << '\n';
  return out.str();
}

std::string_view parallel_mode_name(EngineConfig::ParallelMode mode) {
  switch (mode) {
    case EngineConfig::ParallelMode::root_split: return "RootSplit";
    case EngineConfig::ParallelMode::lazy_smp: return "LazySMP";
  }
  return "RootSplit";
}

std::optional<EngineConfig::ParallelMode> parse_parallel_mode(
    std::string_view value) {
  std::string normalized(value);
  std::ranges::transform(normalized, normalized.begin(),
                         [](unsigned char character) {
                           return static_cast<char>(std::tolower(character));
                         });
  normalized.erase(std::remove_if(normalized.begin(), normalized.end(),
                                  [](char character) {
                                    return character == '-' || character == '_';
                                  }),
                   normalized.end());
  if (normalized == "rootsplit")
    return EngineConfig::ParallelMode::root_split;
  if (normalized == "lazysmp")
    return EngineConfig::ParallelMode::lazy_smp;
  return std::nullopt;
}

Searcher::Searcher(EngineConfig config, std::atomic_bool& stopped)
    : Searcher(std::move(config), stopped, 0, {}) {}

Searcher::Searcher(EngineConfig config, std::atomic_bool& stopped, int lane)
    : Searcher(std::move(config), stopped, lane, {}) {}

Searcher::Searcher(EngineConfig config, std::atomic_bool& stopped, int lane,
                   std::shared_ptr<TTStorage> shared_table)
    : config_(std::move(config)), stopped_(stopped),
      killers_(maximum_search_depth + 32), lane_(lane) {
  table_ = std::move(shared_table);
  if (!table_ && config_.hash_mb > 0) {
    // Keep half of the fixed memory budget on the coherent principal search;
    // the two diversified helpers receive one quarter each. This preserves
    // the configured total instead of silently tripling memory usage. Lazy
    // SMP instead allocates the complete budget once and shares it.
    const std::size_t budget_parts =
        config_.parallel_mode == EngineConfig::ParallelMode::lazy_smp
            ? 4 : (lane_ == 0 ? 2 : 1);
    const std::size_t requested = static_cast<std::size_t>(config_.hash_mb) *
        1024 * 1024 * budget_parts / 4 / sizeof(TTBucket);
    const std::size_t buckets = std::bit_floor(std::max<std::size_t>(1, requested));
    table_ = std::make_shared<TTStorage>();
    table_->buckets.resize(buckets);
    table_->synchronized =
        config_.parallel_mode == EngineConfig::ParallelMode::lazy_smp;
  }
  if (lane_ == 0) {
    for (int index = 0; index < search_thread_count - 1; ++index) {
      std::shared_ptr<TTStorage> helper_table;
      if (config_.parallel_mode == EngineConfig::ParallelMode::lazy_smp)
        helper_table = table_;
      owned_helpers_[index] =
          std::unique_ptr<Searcher>(new Searcher(
              config_, stopped_, index + 1, std::move(helper_table)));
      root_helpers_[index] = owned_helpers_[index].get();
      root_worker_threads_[index] = std::thread([this, index] {
        std::uint64_t observed_epoch = 0;
        std::unique_lock lock(root_work_mutex_);
        for (;;) {
          root_work_ready_.wait(lock, [&] {
            return root_work_shutdown_ ||
                   root_work_epoch_ != observed_epoch;
          });
          if (root_work_shutdown_) return;
          observed_epoch = root_work_epoch_;
          auto work = root_work_;
          lock.unlock();
          work(index + 1);
          lock.lock();
          ++root_work_completed_;
          root_work_done_.notify_one();
        }
      });
    }
  }
}

Searcher::~Searcher() {
  if (lane_ != 0) return;
  {
    std::scoped_lock lock(root_work_mutex_);
    root_work_shutdown_ = true;
  }
  root_work_ready_.notify_all();
  for (std::thread& worker : root_worker_threads_)
    if (worker.joinable()) worker.join();
}

bool Searcher::halted() {
  if (stopped_.load(std::memory_order_relaxed)) return true;
  if (limits_.nodes && nodes_ >= limits_.nodes) return true;
  if (limits_.deadline && std::chrono::steady_clock::now() >= *limits_.deadline) return true;
  return false;
}

void Searcher::advance_generation() {
  if (++generation_ != 0) return;
  generation_ = 1;
  if (!table_) return;
  for (TTBucket& bucket : table_->buckets)
    for (TTEntry& entry : bucket.entries)
      entry.depth = -1;
}

void Searcher::reset_statistics() {
  nodes_ = qnodes_ = tt_hits_ = beta_cutoffs_ = lmr_reductions_ = 0;
  quiet_checks_ = null_cutoffs_ = probcut_cutoffs_ = 0;
  singular_extensions_ = late_move_prunes_ = 0;
  history_hits_ = countermove_hits_ = 0;
}

void Searcher::prepare_root_helper(const Searcher& principal,
                                   const Board&) {
  limits_ = principal.limits_;
  started_ = principal.started_;
  repetition_keys_ = principal.repetition_keys_;
  reset_statistics();
  advance_generation();
}

void Searcher::absorb_statistics(const Searcher& helper) {
  nodes_ += helper.nodes_;
  qnodes_ += helper.qnodes_;
  tt_hits_ += helper.tt_hits_;
  beta_cutoffs_ += helper.beta_cutoffs_;
  lmr_reductions_ += helper.lmr_reductions_;
  quiet_checks_ += helper.quiet_checks_;
  null_cutoffs_ += helper.null_cutoffs_;
  probcut_cutoffs_ += helper.probcut_cutoffs_;
  singular_extensions_ += helper.singular_extensions_;
  late_move_prunes_ += helper.late_move_prunes_;
  history_hits_ += helper.history_hits_;
  countermove_hits_ += helper.countermove_hits_;
}

std::optional<int> Searcher::search_root_move(
    Board root, const Move& move, int depth, int alpha, int beta,
    bool pv_node, const Move& previous) {
  const Color side = root.turn;
  Board::SearchUndo undo;
  if (!root.make_search_move(move, undo)) return std::nullopt;
  repetition_keys_.push_back(root.key);
  const bool gives_check = root.position.in_check(root.turn);
  const int relative_rank = move.piece == Piece::pawn
      ? (side == Color::white ? rank_of(move.to) : 7 - rank_of(move.to))
      : 0;
  const bool dangerous_passer = move.piece == Piece::pawn &&
      relative_rank >= 6 && passed_pawn(root.position, side, move.to);
  const bool recapture = move.is_capture() && previous.is_capture() &&
      move.to == previous.to &&
      static_exchange_score(root.position, side, move) >= 0;
  const int extension = (gives_check || dangerous_passer || recapture) ? 1 : 0;
  const int score = -negamax(
      root, std::max(0, depth - 1 + extension), -beta, -alpha, 1,
      pv_node, move, extension);
  repetition_keys_.pop_back();
  return score;
}

int Searcher::parallel_root(Board& board, const MoveList& moves, int depth,
                            int alpha, int beta, int static_score,
                            const Move& previous) {
  const int original_alpha = alpha;
  std::vector<std::optional<int>> speculative(moves.size());
  std::size_t first = 0;
  for (; first < moves.size(); ++first) {
    speculative[first] = search_root_move(
        board, moves[first], depth, alpha, beta, true, previous);
    if (speculative[first]) break;
  }
  if (first == moves.size())
    return board.position.in_check(board.turn) ? -mate_score : 0;

  Move best = moves[first];
  int best_score = *speculative[first];
  root_best_ = best;
  root_scores_.push_back({best, best_score});
  alpha = std::max(alpha, best_score);
  if (alpha >= beta) {
    ++beta_cutoffs_;
    store(board.key, depth, best_score, static_score, 1, best, 0);
    return best_score;
  }

  for (Searcher* helper : root_helpers_)
    helper->prepare_root_helper(*this, board);
  const int speculative_alpha = alpha;
  auto search_lane = [&](Searcher& worker, int lane) {
    for (std::size_t index = first + 1; index < moves.size(); ++index) {
      if (static_cast<int>((index - first - 1) % search_thread_count) != lane)
        continue;
      speculative[index] = worker.search_root_move(
          board, moves[index], depth, speculative_alpha,
          speculative_alpha + 1, false, previous);
      if (worker.halted()) break;
    }
  };
  {
    std::scoped_lock lock(root_work_mutex_);
    root_work_completed_ = 0;
    root_work_ = [&](int lane) {
      search_lane(*root_helpers_[lane - 1], lane);
    };
    ++root_work_epoch_;
  }
  root_work_ready_.notify_all();
  search_lane(*this, 0);
  {
    std::unique_lock lock(root_work_mutex_);
    root_work_done_.wait(lock, [&] {
      return root_work_completed_ == search_thread_count - 1;
    });
    root_work_ = {};
  }
  absorb_statistics(*root_helpers_[0]);
  absorb_statistics(*root_helpers_[1]);
  if (halted()) return 0;

  for (std::size_t index = first + 1; index < moves.size(); ++index) {
    if (!speculative[index]) continue;
    int score = *speculative[index];
    if (score > speculative_alpha) {
      const auto exact = search_root_move(
          board, moves[index], depth, alpha, beta, true, previous);
      if (!exact) continue;
      score = *exact;
      if (halted()) return 0;
    }
    root_scores_.push_back({moves[index], score});
    if (score > best_score) {
      best_score = score;
      best = moves[index];
      root_best_ = best;
    }
    alpha = std::max(alpha, score);
    if (alpha >= beta) {
      ++beta_cutoffs_;
      break;
    }
  }
  const int flag = best_score <= original_alpha
      ? -1 : (best_score >= beta ? 1 : 0);
  store(board.key, depth, best_score, static_score, flag, best, 0);
  return best_score;
}

ExactEndgame probe_exact_endgame(const Board& board) {
  if (board.horde) return ExactEndgame::none;
  // Every exact class currently recognized by Eloi has at most five pieces.
  // This guard keeps several detailed classifiers out of the middlegame
  // evaluation hot path without changing any covered endgame.
  if (std::popcount(board.position.occupied) > 5)
    return ExactEndgame::none;
  if (board.position.insufficient_material() ||
      wrong_bishop_rook_pawn_draw(board.position))
    return ExactEndgame::draw;
  const auto kpk = kpk_win(board);
  if (!kpk) return ExactEndgame::none;
  if (!*kpk) return ExactEndgame::draw;
  for (int square = 0; square < 64; ++square)
    if (board.position.piece_at(square) == Piece::pawn)
      return board.position.color_at(square) == Color::white
          ? ExactEndgame::white_win : ExactEndgame::black_win;
  return ExactEndgame::none;
}

int Searcher::evaluate(const Board& board) {
  if (board.horde) {
    int white = 0;
    int black = 0;
    for (int square = 0; square < 64; ++square) {
      const auto color = board.position.color_at(square);
      if (!color) continue;
      const Piece piece = board.position.piece_at(square);
      if (piece == Piece::king) continue;
      int value = piece == Piece::pawn ? 100 : nominal(piece);
      if (*color == Color::white) {
        if (piece == Piece::pawn) value += rank_of(square) * 6;
        white += value;
      } else {
        black += value;
      }
    }
    const int black_king = board.position.king_square(Color::black);
    if (black_king >= 0)
      white += board.position.attackers(Color::white, black_king) * 45;
    const int white_score = white - black;
    return board.turn == Color::white ? white_score : -white_score;
  }
  const ExactEndgame exact = probe_exact_endgame(board);
  if (exact == ExactEndgame::draw) return 0;
  if (exact == ExactEndgame::white_win)
    return board.turn == Color::white ? 1800 : -1800;
  if (exact == ExactEndgame::black_win)
    return board.turn == Color::black ? 1800 : -1800;
  int score = nnue_evaluate(board.nnue, board.turn) + endgame_knowledge(board);
  if (opposite_colored_bishops(board.position)) score = score * 55 / 100;
  if (config_.noise_millipawns > 0) {
    std::uniform_int_distribution<int> noise(-config_.noise_millipawns, config_.noise_millipawns);
    score += noise(random_) / 10;
  }
  return score;
}

int Searcher::volatility(const Board& board, std::size_t legal_count,
                         int evaluation_swing) const {
  int result = std::min(30, std::abs(evaluation_swing) / 4);
  if (board.position.in_check(board.turn)) result += 28;
  if (legal_count == 1) result += 24;
  else if (legal_count <= 3) result += 10;

  // Volatility gates pruning at nearly every interior node, so it must stay
  // substantially cheaper than evaluation. Use structural danger signals
  // here; exact attackers and SEE are already checked by the pruning rules
  // and move loop that consume this value.
  std::array<int, 2> advanced_pawns{};
  constexpr std::uint64_t white_advanced = 0xFFFFFF0000000000ULL;
  constexpr std::uint64_t black_advanced = 0x0000000000FFFFFFULL;
  advanced_pawns[0] = std::popcount(
      board.position.pieces(Color::white, Piece::pawn) & white_advanced);
  advanced_pawns[1] = std::popcount(
      board.position.pieces(Color::black, Piece::pawn) & black_advanced);
  result += std::min(20, 8 * (advanced_pawns[0] + advanced_pawns[1]));

  for (Color side : {Color::white, Color::black}) {
    const int king = board.position.king_square(side);
    if (king < 0) continue;
    const int direction = side == Color::white ? 1 : -1;
    const int forward = king + direction * 8;
    const std::uint64_t shield_mask = pawn_attack_table[color_index(side)][king] |
                                      square_bit(forward);
    const int shield = std::popcount(
        shield_mask & board.position.pieces(side, Piece::pawn));
    if (shield == 0) result += 6;
    else if (shield == 1) result += 2;
  }
  return std::clamp(result, 0, 100);
}

int Searcher::quiet_history(Color side, const Move& move,
                            const Move& previous) const {
  int score = history_scores_[color_index(side)][move.from][move.to];
  if (previous.from >= 0 && previous.to >= 0) {
    const unsigned previous_key =
        (static_cast<unsigned>(previous.piece) * 64U + previous.to) * 7U;
    const unsigned current_key =
        static_cast<unsigned>(move.piece) * 64U + move.to;
    score += continuation_history_[(previous_key * 64U + current_key) &
                                   (continuation_history_.size() - 1)];
  }
  return score;
}

void Searcher::update_quiet_history(Color side, const Move& move,
                                    const Move& previous, int bonus) {
  auto update = [bonus](std::int16_t& entry) {
    const int adjusted = static_cast<int>(entry) + bonus -
        static_cast<int>(entry) * std::abs(bonus) / 16'384;
    entry = static_cast<std::int16_t>(std::clamp(adjusted, -16'384, 16'384));
  };
  update(history_scores_[color_index(side)][move.from][move.to]);
  if (previous.from >= 0 && previous.to >= 0) {
    const unsigned previous_key =
        (static_cast<unsigned>(previous.piece) * 64U + previous.to) * 7U;
    const unsigned current_key =
        static_cast<unsigned>(move.piece) * 64U + move.to;
    update(continuation_history_[(previous_key * 64U + current_key) &
                                 (continuation_history_.size() - 1)]);
  }
}

MoveList Searcher::ordered_moves(const Board& board, PackedMove tt_move,
                                 int ply, const Move& previous,
                                 bool legal_only) {
  auto moves = legal_only
      ? board.legal_moves()
      : board.position.pseudo_legal(board.turn, board.horde);
  const Move unpacked_tt = unpack_move(tt_move);
  Move counter;
  if (previous.from >= 0 && previous.to >= 0)
    counter = countermoves_[color_index(board.turn)][previous.from][previous.to];
  auto priority = [&](const Move& move) {
    int p = 0;
    if (tt_move && move.same_coordinates(unpacked_tt)) p += 4'000'000;
    if (move.is_capture()) {
      const int see = static_exchange_score(board.position, board.turn, move);
      const int history = capture_history_[static_cast<int>(move.piece)]
          [move.to][static_cast<int>(move.capture)];
      p += (see >= 0 ? 3'000'000 : 400'000) +
           100 * nominal(move.capture) - nominal(move.piece) + see + history;
    }
    if (move.is_promotion()) p += 3'200'000 + nominal(move.promotion);
    if (!move.is_capture() && !move.is_promotion() &&
        ply >= 0 && ply < static_cast<int>(killers_.size())) {
      if (move.same_coordinates(killers_[ply][0])) p += 2'200'000;
      else if (move.same_coordinates(killers_[ply][1])) p += 2'100'000;
      if (counter.from >= 0 && move.same_coordinates(counter)) {
        p += 2'000'000;
      }
      const int history = quiet_history(board.turn, move, previous);
      p += history;
    }
    if (lane_ > 0) {
      const std::uint32_t mixed = static_cast<std::uint32_t>(pack_move(move)) *
          0x9e3779b1U + static_cast<std::uint32_t>(lane_) * 0x85ebca6bU;
      p += static_cast<int>(mixed % 31U) - 15;
    }
    return p;
  };
  std::array<int, MoveList::capacity> scores{};
  for (std::size_t index = 0; index < moves.size(); ++index)
    scores[index] = priority(moves[index]);
  for (std::size_t index = 1; index < moves.size(); ++index) {
    const Move move = moves[index];
    const int score = scores[index];
    std::size_t insertion = index;
    while (insertion > 0 && scores[insertion - 1] < score) {
      moves[insertion] = moves[insertion - 1];
      scores[insertion] = scores[insertion - 1];
      --insertion;
    }
    moves[insertion] = move;
    scores[insertion] = score;
  }
  return moves;
}

std::optional<Searcher::TTEntry> Searcher::probe(std::uint64_t key) {
  if (!table_ || table_->buckets.empty()) return std::nullopt;
  const std::size_t index = key & (table_->buckets.size() - 1);
  std::unique_lock<std::mutex> lock;
  if (table_->synchronized)
    lock = std::unique_lock(table_->stripes[index % table_->stripes.size()]);
  const TTBucket& bucket = table_->buckets[index];
  std::optional<TTEntry> principal_entry;
  for (const TTEntry& entry : bucket.entries) {
    if (entry.key == key && entry.depth >= 0 &&
        entry.generation == generation_) {
      if (entry.lane == lane_) {
        ++tt_hits_;
        return entry;
      }
      if (lane_ != 0 && entry.lane == 0) principal_entry = entry;
    }
  }
  if (principal_entry) ++tt_hits_;
  return principal_entry;
}

std::optional<Searcher::TTEntry> Searcher::find(std::uint64_t key) const {
  if (!table_ || table_->buckets.empty()) return std::nullopt;
  const std::size_t index = key & (table_->buckets.size() - 1);
  std::unique_lock<std::mutex> lock;
  if (table_->synchronized)
    lock = std::unique_lock(table_->stripes[index % table_->stripes.size()]);
  const TTBucket& bucket = table_->buckets[index];
  std::optional<TTEntry> principal_entry;
  for (const TTEntry& entry : bucket.entries) {
    if (entry.key != key || entry.depth < 0 ||
        entry.generation != generation_)
      continue;
    if (entry.lane == lane_) return entry;
    if (lane_ != 0 && entry.lane == 0) principal_entry = entry;
  }
  return principal_entry;
}

void Searcher::store(std::uint64_t key, int depth, int score, int static_eval,
                     int flag, const Move& best, int ply) {
  if (!table_ || table_->buckets.empty()) return;
  const std::size_t index = key & (table_->buckets.size() - 1);
  std::unique_lock<std::mutex> lock;
  if (table_->synchronized)
    lock = std::unique_lock(table_->stripes[index % table_->stripes.size()]);
  TTBucket& bucket = table_->buckets[index];
  TTEntry* replacement = nullptr;
  for (TTEntry& entry : bucket.entries) {
    if (entry.key == key && entry.lane == lane_) {
      replacement = &entry;
      break;
    }
    if (entry.depth < 0 || entry.generation != generation_) {
      replacement = &entry;
      break;
    }
    // Helpers may share and learn from principal entries, but never evict
    // them. Eloi's selective pruning is currently too move-order-sensitive
    // to let a speculative helper perturb the correctness-authoritative lane.
    if (lane_ != 0 && entry.lane == 0) continue;
    const int entry_value = entry.depth;
    const int replacement_value = replacement ? replacement->depth : infinity;
    if (entry_value < replacement_value) replacement = &entry;
  }
  if (!replacement) return;
  if (replacement->key == key && replacement->lane == lane_ &&
      replacement->depth > depth)
    return;
  *replacement = {
      key, score_to_tt(score, ply),
      static_cast<std::int16_t>(std::clamp(static_eval, -32'000, 32'000)),
      static_cast<std::int16_t>(depth), pack_move(best),
      static_cast<std::int8_t>(flag), static_cast<std::int8_t>(lane_),
      generation_};
}

bool Searcher::search_draw(const Board& board, int ply) const {
  if (ply <= 0) return false;
  if (board.is_fifty_move_draw())
    return true;
  if (!board.horde && std::popcount(board.position.occupied) <= 4 &&
      board.position.insufficient_material())
    return true;
  int repetitions = 0;
  for (std::uint64_t key : repetition_keys_)
    if (key == board.key && ++repetitions >= 3) return true;
  return false;
}

std::vector<Move> Searcher::reconstruct_pv(Board board, const Move& root,
                                           std::size_t maximum) const {
  std::vector<Move> result;
  result.reserve(std::min<std::size_t>(maximum, 128));
  Move candidate = root;
  std::vector<std::uint64_t> seen;
  seen.reserve(result.capacity());
  while (result.size() < maximum && candidate.from >= 0) {
    Move legal;
    bool found_legal = false;
    for (const Move& move : board.legal_moves())
      if (move.same_coordinates(candidate)) {
        legal = move;
        found_legal = true;
        break;
      }
    if (!found_legal) break;
    result.push_back(legal);
    if (!board.push(legal)) break;
    if (std::find(seen.begin(), seen.end(), board.key) != seen.end()) break;
    seen.push_back(board.key);
    const auto entry = find(board.key);
    if (!entry || !entry->best) break;
    candidate = unpack_move(entry->best);
  }
  return result;
}

int Searcher::quiescence(Board& board, int alpha, int beta, int ply,
                         int qply) {
  if (halted()) return 0;
  ++nodes_; ++qnodes_;
  if (board.horde_eliminated()) return -mate_score + ply;
  if (search_draw(board, ply)) return 0;
  const int original_alpha = alpha;
  const auto found = probe(board.key);
  const bool tt_authoritative = found && found->lane == lane_;
  if (found) {
    const int tt_score = score_from_tt(found->score, ply);
    if (tt_authoritative && found->flag == 0) return tt_score;
    if (tt_authoritative && found->flag < 0 && tt_score <= alpha)
      return tt_score;
    if (tt_authoritative && found->flag > 0 && tt_score >= beta)
      return tt_score;
  }
  const bool in_check = board.position.in_check(board.turn);
  int stand = -infinity;
  if (!in_check) {
    stand = evaluate(board);
    if (stand >= beta) return beta;
    alpha = std::max(alpha, stand);
  }
  if (qply >= 4 || ply >= maximum_search_depth)
    return in_check ? evaluate(board) : alpha;
  const auto moves = ordered_moves(board, found ? found->best : 0, ply, {});
  if (moves.empty()) return in_check ? -mate_score + ply : 0;
  int legal_moves = 0;
  Move best;
  for (const auto& move : moves) {
    const bool quiet = !move.is_capture() && !move.is_promotion();
    // Non-capturing checks at every leaf produced most of Eloi's depth-five
    // tree. A stable quiescence frontier searches captures/promotions and all
    // evasions when checked; forcing quiet checks remain part of normal
    // negamax instead of recursively extending the tactical horizon.
    if (!in_check && quiet) continue;
    if (!in_check && !move.is_promotion() &&
        !quiet && stand + nominal(move.capture) + 100 < alpha) continue;
    if (!in_check && move.is_capture() && !move.is_promotion() &&
        static_exchange_score(board.position, board.turn, move) < 0)
      continue;
    Board::SearchUndo undo;
    if (!board.make_search_move(move, undo)) continue;
    ++legal_moves;
    repetition_keys_.push_back(board.key);
    int score = -quiescence(board, -beta, -alpha, ply + 1, qply + 1);
    repetition_keys_.pop_back();
    board.unmake_search_move(undo);
    if (halted()) return 0;
    if (score >= beta) {
      ++beta_cutoffs_;
      store(board.key, 0, beta, stand, 1, move, ply);
      return beta;
    }
    if (score > alpha) {
      alpha = score;
      best = move;
    }
  }
  if (legal_moves == 0) {
    if (in_check) return -mate_score + ply;
    // Captures can be deliberately skipped by delta/SEE pruning before they
    // reach make_search_move(). Distinguish that case from a true stalemate.
    return board.legal_moves().empty() ? 0 : alpha;
  }
  store(board.key, 0, alpha, stand, alpha > original_alpha ? 0 : -1,
        best, ply);
  return alpha;
}

int Searcher::negamax(Board& board, int depth, int alpha, int beta, int ply,
                      bool pv_node, const Move& previous, int extensions,
                      PackedMove excluded, bool allow_null) {
  if (halted()) return 0;
  ++nodes_;
  if (board.horde_eliminated()) return -mate_score + ply;
  if (search_draw(board, ply)) return 0;
  alpha = std::max(alpha, -mate_score + ply);
  beta = std::min(beta, mate_score - ply - 1);
  if (alpha >= beta) return alpha;

  const bool in_check = board.position.in_check(board.turn);
  if (depth <= 0) {
    return quiescence(board, alpha, beta, ply, 0);
  }

  const int original_depth = depth;
  const int original_alpha = alpha;
  const auto found = probe(board.key);
  const bool tt_authoritative = found && found->lane == lane_;
  const PackedMove tt_move = found ? found->best : 0;
  const int tt_score = found ? score_from_tt(found->score, ply) : 0;
  // A Lazy SMP helper may finish this root depth before the principal lane.
  // Its TT score is useful for move ordering, but returning it here would
  // leave the principal's root_best_ unset (or stale from the prior depth).
  // Below the root, normal exact/lower/upper cutoffs remain enabled.
  if (ply > 0 && !excluded && tt_authoritative && found->depth >= depth) {
    if (found->flag == 0) return tt_score;
    if (found->flag < 0 && tt_score <= alpha) return tt_score;
    if (found->flag > 0 && tt_score >= beta) return tt_score;
  }

  int static_score = in_check ? -infinity
      : (found ? static_cast<int>(found->static_eval) : evaluate(board));
  const int base_volatility = depth >= 3
      ? volatility(board, 4) : (in_check ? 65 : 20);

  if (!pv_node && !excluded && !in_check && depth <= 5 &&
      base_volatility < 50 && std::abs(beta) < mate_score - 1'000 &&
      static_score - (70 + 85 * depth) >= beta)
    return static_score;

  if (!pv_node && !excluded && !in_check && depth <= 2 &&
      base_volatility < 55 && static_score + 180 * depth <= alpha) {
    const int razor = quiescence(board, alpha, beta, ply, 0);
    if (razor <= alpha) return razor;
  }

  if (!pv_node && !excluded && depth >= 6 && !tt_move)
    --depth;

  const auto bishops = board.position.pieces(board.turn, Piece::bishop);
  const auto knights = board.position.pieces(board.turn, Piece::knight);
  const auto rooks = board.position.pieces(board.turn, Piece::rook);
  const auto queens = board.position.pieces(board.turn, Piece::queen);
  const int minor_count = std::popcount(bishops) + std::popcount(knights);
  const int rook_count = std::popcount(rooks);
  const int queen_count = std::popcount(queens);
  const int non_pawn_value =
      300 * minor_count + 500 * rook_count + 900 * queen_count;
  const int non_pawn_count = minor_count + rook_count + queen_count;

  if (!board.horde && allow_null && !pv_node && !excluded && !in_check &&
      depth >= 3 && ply > 0 && board.halfmove < 80 &&
      base_volatility < 65 &&
      (non_pawn_value >= 500 || non_pawn_count >= 2) &&
      static_score >= beta - 80) {
    const int reduction = std::clamp(
        2 + depth / 4 + std::max(0, static_score - beta) / 240, 2, 5);
    Board::SearchUndo undo;
    board.make_null_move(undo);
    const int null_score = -negamax(
        board, std::max(0, depth - 1 - reduction), -beta, -beta + 1,
        ply + 1, false, {}, extensions, 0, false);
    board.unmake_search_move(undo);
    if (halted()) return 0;
    if (null_score >= beta) {
      bool verified = true;
      if (depth >= 8)
        verified = negamax(board, std::max(1, depth - reduction),
                           beta - 1, beta, ply, false, previous,
                           extensions, 0, false) >= beta;
      if (verified) {
        ++null_cutoffs_;
        ++beta_cutoffs_;
        return beta;
      }
    }
  }

  auto moves = ordered_moves(board, tt_move, ply, previous);
  if (moves.empty()) return in_check ? -mate_score + ply : 0;
  const int node_volatility = std::clamp(
      base_volatility + (moves.size() == 1 ? 24 : 0), 0, 100);

  if (config_.parallel_mode == EngineConfig::ParallelMode::root_split &&
      ply == 0 && !excluded && root_helpers_[0] && root_helpers_[1])
    return parallel_root(
        board, moves, depth, alpha, beta, static_score, previous);

  if (!pv_node && !excluded && !in_check && depth >= 5 &&
      node_volatility < 80 && beta < mate_score - 1'000) {
    const int prob_beta = std::min(mate_score - ply - 1, beta + 140);
    int candidates = 0;
    for (const Move& move : moves) {
      if (candidates >= 4) break;
      if (!move.is_capture() && !move.is_promotion()) continue;
      if (move.is_capture() &&
          static_exchange_score(board.position, board.turn, move) < 0)
        continue;
      ++candidates;
      Board::SearchUndo undo;
      if (!board.make_search_move(move, undo)) continue;
      repetition_keys_.push_back(board.key);
      const int score = -negamax(
          board, std::max(0, depth - 4), -prob_beta, -prob_beta + 1,
          ply + 1, false, move, extensions, 0, true);
      repetition_keys_.pop_back();
      board.unmake_search_move(undo);
      if (halted()) return 0;
      if (score >= prob_beta) {
        ++probcut_cutoffs_;
        store(board.key, depth - 3, score, static_score, 1, move, ply);
        return score;
      }
    }
  }

  Move best;
  int best_score = -infinity;
  int move_index = 0;
  int searched_moves = 0;
  const Color side = board.turn;
  const Move counter = previous.from >= 0
      ? countermoves_[color_index(side)][previous.from][previous.to] : Move{};
  for (const Move& move : moves) {
    if (excluded && pack_move(move) == excluded) continue;
    const bool quiet = !move.is_capture() && !move.is_promotion() &&
                       !move.is_castle();
    const int capture_see = move.is_capture()
        ? static_exchange_score(board.position, side, move) : 0;
    const int history = quiet ? quiet_history(side, move, previous) : 0;
    if (quiet && history > 0) ++history_hits_;
    if (quiet && counter.from >= 0 && move.same_coordinates(counter))
      ++countermove_hits_;
    const int futility_margin = node_volatility >= 55 ? 190
        : (node_volatility <= 22 ? 75 : 120);
    if (move_index > 0 && depth == 1 && quiet && !in_check &&
        static_score + futility_margin <= alpha) {
      ++late_move_prunes_;
      ++move_index;
      continue;
    }

    bool singular = false;
    if (!excluded && tt_authoritative && tt_move &&
        pack_move(move) == tt_move && depth >= 6 &&
        found->depth >= depth - 2 && found->flag >= 0 &&
        std::abs(tt_score) < mate_score - 1'000) {
      const int singular_beta = tt_score - 20 - depth * 2;
      const int exclusion_score = negamax(
          board, std::max(1, depth / 2), singular_beta - 1, singular_beta,
          ply, false, previous, extensions, tt_move, false);
      if (halted()) return 0;
      singular = exclusion_score < singular_beta;
      if (singular) ++singular_extensions_;
    }

    Board::SearchUndo undo;
    if (!board.make_search_move(move, undo)) {
      ++move_index;
      continue;
    }
    repetition_keys_.push_back(board.key);
    const bool gives_check = board.position.in_check(board.turn);
    const int relative_rank = move.piece == Piece::pawn
        ? (side == Color::white ? rank_of(move.to) : 7 - rank_of(move.to))
        : 0;
    const bool dangerous_passer = move.piece == Piece::pawn &&
        relative_rank >= 6 &&
        passed_pawn(board.position, side, move.to);
    const bool recapture = move.is_capture() && previous.is_capture() &&
        move.to == previous.to && capture_see >= 0;
    const bool forced_reply = moves.size() == 1;
    const bool checking_net = gives_check &&
        (pv_node || node_volatility >= 65 ||
         board.legal_moves().size() <= 2);

    const bool protected_quiet = gives_check || dangerous_passer ||
        move.same_coordinates(counter) ||
        (ply < static_cast<int>(killers_.size()) &&
         (move.same_coordinates(killers_[ply][0]) ||
          move.same_coordinates(killers_[ply][1])));
    const int lmp_threshold = 4 + depth * 2;
    if (!pv_node && !in_check && quiet && depth <= 3 &&
        move_index >= lmp_threshold && history < 0 &&
        node_volatility < 55 && !protected_quiet) {
      repetition_keys_.pop_back();
      board.unmake_search_move(undo);
      ++late_move_prunes_;
      ++move_index;
      continue;
    }

    int extension = 0;
    if (extensions < 2 &&
        (singular || forced_reply || dangerous_passer || recapture ||
         checking_net))
      extension = 1;
    const int child_extensions = extensions + extension;
    int child_depth = depth - 1 + extension;
    const bool reduce = child_depth >= 2 && move_index >= 2 &&
                        quiet && !in_check && !gives_check && !singular;
    int score;
    if (reduce) {
      int reduction = 1;
      if (depth >= 4 && move_index >= 6) ++reduction;
      if (!pv_node && depth >= 5 && move_index >= 12) ++reduction;
      if (history > 4'000 || node_volatility >= 55) --reduction;
      if (history < -2'000 && node_volatility <= 22 && depth >= 5)
        ++reduction;
      reduction = std::clamp(reduction, 0, std::max(0, child_depth - 1));
      if (reduction > 0) {
        ++lmr_reductions_;
        score = -negamax(board, child_depth - reduction,
                         -alpha - 1, -alpha, ply + 1, false, move,
                         child_extensions);
        if (score > alpha)
          score = -negamax(board, child_depth, -alpha - 1, -alpha,
                           ply + 1, false, move, child_extensions);
      } else {
        score = -negamax(board, child_depth, -alpha - 1, -alpha,
                         ply + 1, false, move, child_extensions);
      }
    } else if (searched_moves > 0) {
      score = -negamax(board, child_depth, -alpha - 1, -alpha,
                       ply + 1, false, move, child_extensions);
    } else {
      score = -negamax(board, child_depth, -beta, -alpha, ply + 1,
                       pv_node, move, child_extensions);
    }
    if (searched_moves > 0 && score > alpha && score < beta)
      score = -negamax(board, child_depth, -beta, -alpha, ply + 1,
                       pv_node, move, child_extensions);

    repetition_keys_.pop_back();
    board.unmake_search_move(undo);
    if (halted()) return 0;
    ++searched_moves;
    if (ply == 0 && !excluded) root_scores_.push_back({move, score});
    if (score > best_score) {
      best_score = score;
      best = move;
      if (ply == 0 && !excluded) root_best_ = move;
    }
    if (score > alpha) alpha = score;
    if (alpha >= beta) {
      ++beta_cutoffs_;
      const int bonus = std::min(8'000, 32 * depth * depth + 64);
      if (!excluded && quiet && ply < static_cast<int>(killers_.size())) {
        if (!move.same_coordinates(killers_[ply][0])) {
          killers_[ply][1] = killers_[ply][0];
          killers_[ply][0] = move;
        }
        update_quiet_history(side, move, previous, bonus);
        if (previous.from >= 0)
          countermoves_[color_index(side)][previous.from][previous.to] = move;
        for (int index = 0; index < move_index; ++index) {
          const Move& failed = moves[static_cast<std::size_t>(index)];
          if (!failed.is_capture() && !failed.is_promotion() &&
              pack_move(failed) != excluded)
            update_quiet_history(side, failed, previous, -bonus / 2);
        }
      } else if (!excluded && move.is_capture()) {
        auto& entry = capture_history_[static_cast<int>(move.piece)]
            [move.to][static_cast<int>(move.capture)];
        entry = static_cast<std::int16_t>(std::clamp(
            static_cast<int>(entry) + bonus / 2, -16'384, 16'384));
      }
      break;
    }
    ++move_index;
  }

  if (!searched_moves)
    return excluded ? alpha : (in_check ? -mate_score + ply : 0);
  if (!excluded) {
    const int flag = best_score <= original_alpha
        ? -1 : (best_score >= beta ? 1 : 0);
    store(board.key, original_depth, best_score, static_score,
          flag, best, ply);
  }
  return best_score;
}

std::string_view clock_mode_name(ClockMode mode) {
  switch (mode) {
    case ClockMode::normal: return "normal";
    case ClockMode::pressure: return "pressure";
    case ClockMode::emergency: return "emergency";
    case ClockMode::panic: return "panic";
    default: return "none";
  }
}

TimeBudget plan_time_budget(const Board& board, const SearchLimits& limits) {
  TimeBudget budget;
  if (limits.remaining_ms <= 0 || limits.deadline) return budget;

  const int remaining = std::max(1, limits.remaining_ms);
  const int overhead = std::clamp(limits.move_overhead_ms, 0, 5'000);
  int non_pawn_material = 0;
  for (int square = 0; square < 64; ++square) {
    const Piece piece = board.position.piece_at(square);
    if (piece != Piece::none && piece != Piece::pawn && piece != Piece::king)
      non_pawn_material += nominal(piece);
  }

  int horizon = non_pawn_material >= 5'000 ? 64
      : (non_pawn_material >= 2'200 ? 52 : 36);
  if (limits.moves_to_go > 0)
    horizon = std::clamp(limits.moves_to_go, 8, 80);

  int reserve_floor = 5'000;
  int reserve_divisor = 16;
  int increment_percent = 70;
  int hard_cap = 12'000;
  int hard_divisor = 24;
  int hard_multiplier = 200;
  if (remaining <= 20'000) {
    budget.mode = ClockMode::panic;
    horizon = std::max(horizon, 128);
    reserve_floor = 750;
    reserve_divisor = 4;
    increment_percent = 10;
    hard_cap = 250;
    hard_divisor = 48;
    hard_multiplier = 180;
  } else if (remaining <= 60'000) {
    budget.mode = ClockMode::emergency;
    horizon = std::max(horizon, 96);
    reserve_floor = 2'000;
    reserve_divisor = 6;
    increment_percent = 25;
    hard_cap = 1'200;
    hard_divisor = 24;
    hard_multiplier = 190;
  } else if (remaining <= 120'000) {
    budget.mode = ClockMode::pressure;
    horizon = std::max(horizon, 72);
    reserve_floor = 4'000;
    reserve_divisor = 10;
    increment_percent = 50;
    hard_cap = 4'000;
    hard_divisor = 20;
    hard_multiplier = 200;
  } else {
    budget.mode = ClockMode::normal;
  }

  const int network_reserve = overhead * 6 + 250;
  budget.reserve_ms = std::max({reserve_floor,
                                remaining / reserve_divisor,
                                network_reserve});
  budget.reserve_ms = std::clamp(budget.reserve_ms, 0,
                                 std::max(0, remaining - 1));
  const int usable = std::max(1, remaining - budget.reserve_ms);
  const int increment_credit = std::min(
      std::max(0, limits.increment_ms) * increment_percent / 100,
      usable / 8);
  budget.base_ms = std::clamp(usable / horizon + increment_credit, 1, usable);

  const int proportional_hard_cap = std::max(1, usable / hard_divisor);
  const int effective_hard_cap = std::max(
      1, std::min(hard_cap, proportional_hard_cap + increment_credit));
  budget.base_ms = std::min(budget.base_ms, effective_hard_cap);
  budget.hard_ms = std::clamp(
      budget.base_ms * hard_multiplier / 100,
      budget.base_ms, std::min(usable, effective_hard_cap));
  budget.soft_ms = std::min(budget.base_ms, budget.hard_ms);
  return budget;
}

SearchResult Searcher::iterative(Board board, SearchLimits limits,
                                 const std::function<void(const SearchResult&)>& info) {
  // Book moves require no tree search, so there is nothing useful for helper
  // lanes to do. All calculated moves use exactly three deterministic lanes.
  if (opening_move(config_, board))
    return iterative_single(std::move(board), limits, info);

  lane_ = 0;
  if (config_.parallel_mode == EngineConfig::ParallelMode::root_split)
    return iterative_single(std::move(board), limits, info);

  // Lazy SMP searches the complete tree on all three lanes. Two agreeing
  // lanes form a deterministic move consensus; the principal lane breaks a
  // three-way disagreement. This prevents one speculative lane from
  // overruling the other two while still letting independent searches matter.
  // Generation is advanced exactly once before any lane starts so helpers
  // neither invalidate one another nor race a wraparound clear.
  advance_generation();
  for (Searcher* helper : root_helpers_)
    helper->generation_ = generation_;

  std::array<SearchResult, search_thread_count - 1> helper_results;
  {
    std::scoped_lock lock(root_work_mutex_);
    root_work_completed_ = 0;
    root_work_ = [&](int lane) {
      helper_results[static_cast<std::size_t>(lane - 1)] =
          root_helpers_[static_cast<std::size_t>(lane - 1)]->iterative_single(
              board, limits, {}, false);
    };
    ++root_work_epoch_;
  }
  root_work_ready_.notify_all();
  SearchResult result = iterative_single(std::move(board), limits, info, false);
  {
    std::unique_lock lock(root_work_mutex_);
    root_work_done_.wait(lock, [&] {
      return root_work_completed_ == search_thread_count - 1;
    });
    root_work_ = {};
  }

  auto agrees = [](const SearchResult& left, const SearchResult& right) {
    return !left.pv.empty() && !right.pv.empty() &&
           left.pv.front().same_coordinates(right.pv.front());
  };
  const int principal_allocated_ms = result.allocated_ms;
  const int principal_hard_limit_ms = result.hard_limit_ms;
  const int principal_reserve_ms = result.clock_reserve_ms;
  const ClockMode principal_clock_mode = result.clock_mode;
  const auto principal_elapsed = result.elapsed;
  if (!agrees(result, helper_results[0]) &&
      agrees(helper_results[0], helper_results[1])) {
    result = helper_results[0];
    result.allocated_ms = principal_allocated_ms;
    result.hard_limit_ms = principal_hard_limit_ms;
    result.clock_reserve_ms = principal_reserve_ms;
    result.clock_mode = principal_clock_mode;
    result.elapsed = principal_elapsed;
  }

  auto add_statistics = [&](const SearchResult& helper) {
    result.nodes += helper.nodes;
    result.qnodes += helper.qnodes;
    result.tt_hits += helper.tt_hits;
    result.beta_cutoffs += helper.beta_cutoffs;
    result.lmr_reductions += helper.lmr_reductions;
    result.quiet_checks += helper.quiet_checks;
    result.null_cutoffs += helper.null_cutoffs;
    result.probcut_cutoffs += helper.probcut_cutoffs;
    result.singular_extensions += helper.singular_extensions;
    result.late_move_prunes += helper.late_move_prunes;
    result.history_hits += helper.history_hits;
    result.countermove_hits += helper.countermove_hits;
  };
  for (const SearchResult& helper : helper_results) add_statistics(helper);
  return result;
}

SearchResult Searcher::iterative_single(Board board, SearchLimits limits,
                                 const std::function<void(const SearchResult&)>& info,
                                 bool start_new_generation) {
  limits_ = limits;
  limits_.depth = std::clamp(limits_.depth, 0, maximum_search_depth);
  reset_statistics();
  std::fill(killers_.begin(), killers_.end(),
            std::array<Move, 2>{});
  history_scores_ = {};
  countermoves_ = {};
  capture_history_ = {};
  continuation_history_ = {};
  repetition_keys_.clear();
  repetition_keys_.reserve(board.history.size() + maximum_search_depth + 32);
  for (const Board::Snapshot& snapshot : board.history)
    repetition_keys_.push_back(snapshot.key);
  repetition_keys_.push_back(board.key);
  if (start_new_generation) advance_generation();
  started_ = std::chrono::steady_clock::now();
  SearchResult last;
  if (auto book = opening_move(config_, board)) {
    last.nodes = 1;
    last.pv.push_back(book->move);
    last.opening_family = std::string(book->family);
    if (info) info(last);
    return last;
  }

  const MoveList fallback_moves = board.legal_moves();
  if (fallback_moves.empty()) {
    last.volatility = volatility(board, 0, 0);
    const bool lost = board.horde_eliminated() ||
                      board.position.in_check(board.turn);
    if (lost) {
      last.score_cp = -mate_score;
      last.mate = -1;
    }
    return last;
  }
  last.pv.push_back(fallback_moves.front());

  int base_budget_ms = 0;
  int soft_budget_ms = 0;
  int hard_budget_ms = 0;
  TimeBudget clock_budget;
  const bool adaptive_clock = limits_.remaining_ms > 0 && !limits_.deadline;
  if (adaptive_clock) {
    clock_budget = plan_time_budget(board, limits_);
    base_budget_ms = clock_budget.base_ms;
    soft_budget_ms = clock_budget.soft_ms;
    hard_budget_ms = clock_budget.hard_ms;
    limits_.deadline = started_ + std::chrono::milliseconds(hard_budget_ms);
    last.allocated_ms = soft_budget_ms;
    last.hard_limit_ms = hard_budget_ms;
    last.clock_reserve_ms = clock_budget.reserve_ms;
    last.clock_mode = clock_budget.mode;
  } else if (limits_.deadline) {
    last.allocated_ms = static_cast<int>(std::max<std::int64_t>(
        1, std::chrono::duration_cast<std::chrono::milliseconds>(
               *limits_.deadline - started_).count()));
  }

  Move previous_best;
  bool have_previous_best = false;
  int stable_iterations = 0;
  int previous_score = 0;
  int evaluation_swing = 0;
  const Move game_previous = board.last_move().value_or(Move{});
  int max_depth = limits_.depth > 0 ? limits_.depth : maximum_search_depth;
  for (int depth = 1; depth <= max_depth && !halted(); ++depth) {
    const std::size_t root_legal_count = board.legal_moves().size();
    const int root_volatility = volatility(board, root_legal_count,
                                           evaluation_swing);
    int window = depth >= 4
        ? std::clamp(28 + root_volatility / 2 + evaluation_swing / 3,
                     28, 180)
        : infinity;
    int alpha = depth >= 4 ? std::max(-infinity, last.score_cp - window) : -infinity;
    int beta = depth >= 4 ? std::min(infinity, last.score_cp + window) : infinity;
    int score = 0;
    for (;;) {
      root_scores_.clear();
      root_best_ = {};
      score = negamax(board, depth, alpha, beta, 0, true,
                      game_previous, 0);
      if (halted() || (score > alpha && score < beta)) break;
      window = std::min(infinity, window * 2);
      alpha = std::max(-infinity, score - window);
      beta = std::min(infinity, score + window);
      if (window == infinity) { alpha = -infinity; beta = infinity; }
    }
    if (halted()) {
      if (last.depth == 0 && root_best_.from >= 0)
        last.pv.assign(1, root_best_);
      last.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - started_);
      break;
    }
    std::vector<Move> pv = reconstruct_pv(board, root_best_);
    evaluation_swing = depth > 1 ? std::abs(score - previous_score) : 0;
    previous_score = score;

    std::stable_sort(root_scores_.begin(), root_scores_.end(),
                     [](const auto& a, const auto& b) {
                       return a.second > b.second;
                     });
    int root_gap = 0;
    int credible_alternatives = 0;
    if (root_scores_.size() >= 2) {
      root_gap = std::max(0, root_scores_[0].second - root_scores_[1].second);
      for (std::size_t i = 1; i < root_scores_.size(); ++i)
        if (root_scores_[0].second - root_scores_[i].second <= 80)
          ++credible_alternatives;
    }
    if (!pv.empty() && have_previous_best &&
        pv.front().same_coordinates(previous_best))
      ++stable_iterations;
    else
      stable_iterations = 0;
    if (!pv.empty()) { previous_best = pv.front(); have_previous_best = true; }

    const int completed_volatility = volatility(
        board, root_legal_count, evaluation_swing);
    if (adaptive_clock) {
      int time_factor = 90 + completed_volatility / 2;
      if (evaluation_swing >= 120) time_factor += 35;
      else if (evaluation_swing >= 60) time_factor += 18;
      if (credible_alternatives >= 3) time_factor += 25;
      else if (credible_alternatives >= 1) time_factor += 10;
      if (root_gap >= 180) time_factor -= 25;
      else if (root_gap >= 100) time_factor -= 12;
      if (stable_iterations >= 3) time_factor -= 28;
      else if (stable_iterations >= 2) time_factor -= 14;
      int minimum_factor = 40;
      int maximum_factor = 180;
      switch (clock_budget.mode) {
        case ClockMode::pressure:
          minimum_factor = 30; maximum_factor = 120; break;
        case ClockMode::emergency:
          minimum_factor = 20; maximum_factor = 85; break;
        case ClockMode::panic:
          minimum_factor = 10; maximum_factor = 60; break;
        default: break;
      }
      time_factor = std::clamp(time_factor, minimum_factor, maximum_factor);
      soft_budget_ms = std::clamp(base_budget_ms * time_factor / 100,
                                  std::max(1, base_budget_ms * minimum_factor / 100),
                                  hard_budget_ms);
    }
    last.depth = depth; last.score_cp = score; last.nodes = nodes_;
    last.qnodes = qnodes_; last.tt_hits = tt_hits_;
    last.beta_cutoffs = beta_cutoffs_;
    last.lmr_reductions = lmr_reductions_;
    last.quiet_checks = quiet_checks_;
    last.null_cutoffs = null_cutoffs_;
    last.probcut_cutoffs = probcut_cutoffs_;
    last.singular_extensions = singular_extensions_;
    last.late_move_prunes = late_move_prunes_;
    last.history_hits = history_hits_;
    last.countermove_hits = countermove_hits_;
    last.pv = std::move(pv);
    last.allocated_ms = adaptive_clock ? soft_budget_ms : last.allocated_ms;
    last.hard_limit_ms = adaptive_clock ? hard_budget_ms : last.hard_limit_ms;
    last.clock_reserve_ms = adaptive_clock
        ? clock_budget.reserve_ms : last.clock_reserve_ms;
    last.clock_mode = adaptive_clock ? clock_budget.mode : last.clock_mode;
    last.volatility = completed_volatility;
    last.root_score_gap = root_gap;
    last.credible_alternatives = credible_alternatives;
    last.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started_);
    if (std::abs(score) >= mate_score - 1000)
      last.mate = score > 0 ? (mate_score - score + 1) / 2 : -(mate_score + score + 1) / 2;
    if (info) info(last);
    if (limits_.depth > 0 && depth >= limits_.depth) break;
    if (last.mate != 0) break;
    if (adaptive_clock && depth >= 2 &&
        last.elapsed.count() >= soft_budget_ms) break;
  }
  return last;
}

std::uint64_t perft(Position position, Color side, int depth,
                     std::vector<std::pair<Move, std::uint64_t>>* divide,
                     bool horde) {
  if (depth == 0) return 1;
  std::uint64_t total = 0;
  for (const Move& move : position.legal(side, horde)) {
    auto next = position.apply(move);
    std::uint64_t count = perft(
        *next, opponent(side), depth - 1, nullptr, horde);
    if (divide) divide->push_back({move, count});
    total += count;
  }
  return total;
}

EngineConfig default_config() {
  EngineConfig config;
  config.name = "Eloi";
  config.author = "Sahil Das";
  config.depth = 8;
  config.hash_mb = 32;
  config.noise_millipawns = 0;
  config.own_book = true;
  return config;
}

}  // namespace eloi
