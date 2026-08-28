#include "morlock/chess.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <thread>

namespace morlock {
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

bool inside(int file, int rank) { return file >= 0 && file < 8 && rank >= 0 && rank < 8; }

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

void add_move(const Position& pos, Color side, std::vector<Move>& out, int from, int to,
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
  const int target = side == Color::white ? static_cast<int>(Piece::king)
                                           : -static_cast<int>(Piece::king);
  for (int sq = 0; sq < 64; ++sq)
    if (cells[sq] == target) return sq;
  return -1;
}

int Position::attackers(Color side, int target) const {
  if (target < 0 || target >= 64) return 0;
  int count = 0;
  const int tf = file_of(target), tr = rank_of(target);
  const int pawn_rank = tr + (side == Color::white ? -1 : 1);
  for (int df : {-1, 1}) {
    const int f = tf + df;
    if (!inside(f, pawn_rank)) continue;
    const int sq = square_of(f, pawn_rank);
    if (color_at(sq) == side && piece_at(sq) == Piece::pawn) ++count;
  }

  constexpr int knight_steps[8][2] = {
      {1,2},{2,1},{2,-1},{1,-2},{-1,-2},{-2,-1},{-2,1},{-1,2}};
  for (auto& step : knight_steps) {
    int f = tf + step[0], r = tr + step[1];
    if (inside(f, r)) {
      int sq = square_of(f, r);
      if (color_at(sq) == side && piece_at(sq) == Piece::knight) ++count;
    }
  }

  for (int df = -1; df <= 1; ++df) for (int dr = -1; dr <= 1; ++dr) {
    if ((!df && !dr) || !inside(tf + df, tr + dr)) continue;
    int sq = square_of(tf + df, tr + dr);
    if (color_at(sq) == side && piece_at(sq) == Piece::king) ++count;
  }

  constexpr int dirs[8][2] = {
      {1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}};
  for (int i = 0; i < 8; ++i) {
    int f = tf + dirs[i][0], r = tr + dirs[i][1];
    while (inside(f, r)) {
      int sq = square_of(f, r);
      if (!empty(sq)) {
        if (color_at(sq) == side) {
          Piece p = piece_at(sq);
          if (p == Piece::queen || (i < 4 && p == Piece::rook) ||
              (i >= 4 && p == Piece::bishop)) ++count;
        }
        break;
      }
      f += dirs[i][0]; r += dirs[i][1];
    }
  }
  return count;
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

std::vector<Move> Position::pseudo_legal(Color side) const {
  std::vector<Move> out;
  out.reserve(64);
  constexpr int knight_steps[8][2] = {
      {1,2},{2,1},{2,-1},{1,-2},{-1,-2},{-2,-1},{-2,1},{-1,2}};
  constexpr int king_steps[8][2] = {
      {1,0},{1,1},{0,1},{-1,1},{-1,0},{-1,-1},{0,-1},{1,-1}};
  constexpr int rook_dirs[4][2] = {{1,0},{-1,0},{0,1},{0,-1}};
  constexpr int bishop_dirs[4][2] = {{1,1},{1,-1},{-1,1},{-1,-1}};

  for (int from = 0; from < 64; ++from) {
    if (color_at(from) != side) continue;
    Piece piece = piece_at(from);
    int f = file_of(from), r = rank_of(from);
    if (piece == Piece::pawn) {
      int step = side == Color::white ? 1 : -1;
      int start = side == Color::white ? 1 : 6;
      int promo = side == Color::white ? 7 : 0;
      int to_rank = r + step;
      if (inside(f, to_rank) && empty(square_of(f, to_rank))) {
        int to = square_of(f, to_rank);
        if (to_rank == promo) {
          for (Piece p : {Piece::queen, Piece::rook, Piece::knight, Piece::bishop})
            out.push_back({MoveType::promotion, from, to, piece, p, Piece::none});
        } else {
          out.push_back({MoveType::push, from, to, piece, Piece::none, Piece::none});
          int jump_rank = r + 2 * step;
          if (r == start && empty(square_of(f, jump_rank)))
            out.push_back({MoveType::jump, from, square_of(f, jump_rank), piece,
                           Piece::none, Piece::none});
        }
      }
      for (int df : {-1, 1}) {
        int cf = f + df;
        if (!inside(cf, to_rank)) continue;
        int to = square_of(cf, to_rank);
        if (color_at(to) == opponent(side)) {
          Piece captured = piece_at(to);
          if (to_rank == promo) {
            for (Piece p : {Piece::queen, Piece::rook, Piece::knight, Piece::bishop})
              out.push_back({MoveType::capture_promotion, from, to, piece, p, captured});
          } else {
            out.push_back({MoveType::capture, from, to, piece, Piece::none, captured});
          }
        } else if (to == en_passant) {
          int victim = to - step * 8;
          if (color_at(victim) == opponent(side) && piece_at(victim) == Piece::pawn)
            out.push_back({MoveType::en_passant, from, to, piece, Piece::none, Piece::pawn});
        }
      }
      continue;
    }
    if (piece == Piece::knight) {
      for (auto& s : knight_steps) {
        int nf = f + s[0], nr = r + s[1];
        if (inside(nf, nr)) add_move(*this, side, out, from, square_of(nf, nr), piece);
      }
      continue;
    }
    if (piece == Piece::king) {
      for (auto& s : king_steps) {
        int nf = f + s[0], nr = r + s[1];
        if (inside(nf, nr)) add_move(*this, side, out, from, square_of(nf, nr), piece);
      }
      int home_rank = side == Color::white ? 0 : 7;
      std::uint8_t king_right = side == Color::white ? white_king : black_king;
      std::uint8_t queen_right = side == Color::white ? white_queen : black_queen;
      if (from == square_of(4, home_rank)) {
        if ((castling & king_right) && empty(square_of(5, home_rank)) &&
            empty(square_of(6, home_rank)) && color_at(square_of(7, home_rank)) == side &&
            piece_at(square_of(7, home_rank)) == Piece::rook)
          out.push_back({MoveType::king_castle, from, square_of(6, home_rank), piece});
        if ((castling & queen_right) && empty(square_of(1, home_rank)) &&
            empty(square_of(2, home_rank)) && empty(square_of(3, home_rank)) &&
            color_at(square_of(0, home_rank)) == side &&
            piece_at(square_of(0, home_rank)) == Piece::rook)
          out.push_back({MoveType::queen_castle, from, square_of(2, home_rank), piece});
      }
      continue;
    }
    const int (*dirs)[2] = piece == Piece::bishop ? bishop_dirs : rook_dirs;
    int dir_count = 4;
    auto slide = [&](const int direction[2]) {
      int nf = f + direction[0], nr = r + direction[1];
      while (inside(nf, nr)) {
        int to = square_of(nf, nr);
        if (color_at(to) == side) break;
        add_move(*this, side, out, from, to, piece);
        if (!empty(to)) break;
        nf += direction[0]; nr += direction[1];
      }
    };
    if (piece == Piece::queen) {
      for (auto& d : rook_dirs) slide(d);
      for (auto& d : bishop_dirs) slide(d);
    } else {
      for (int i = 0; i < dir_count; ++i) slide(dirs[i]);
    }
  }
  return out;
}

std::optional<Position> Position::apply(const Move& move) const {
  if (move.from < 0 || move.from >= 64 || move.to < 0 || move.to >= 64 || empty(move.from))
    return std::nullopt;
  const Color side = *color_at(move.from);
  if (color_at(move.to) == side) return std::nullopt;
  Position next = *this;
  const int sign = side == Color::white ? 1 : -1;
  const Piece moving = piece_at(move.from);
  if (move.is_castle()) {
    int rank = side == Color::white ? 0 : 7;
    int transit = square_of(move.type == MoveType::king_castle ? 5 : 3, rank);
    if (in_check(side) || attacked_by(opponent(side), transit) ||
        attacked_by(opponent(side), move.to)) return std::nullopt;
  }
  next.cells[move.from] = 0;
  if (move.type == MoveType::en_passant) {
    int victim = move.to + (side == Color::white ? -8 : 8);
    next.cells[victim] = 0;
  }
  Piece placed = move.is_promotion() ? move.promotion : moving;
  next.cells[move.to] = static_cast<std::int8_t>(sign * static_cast<int>(placed));
  if (move.type == MoveType::king_castle || move.type == MoveType::queen_castle) {
    int rank = side == Color::white ? 0 : 7;
    int rook_from = square_of(move.type == MoveType::king_castle ? 7 : 0, rank);
    int rook_to = square_of(move.type == MoveType::king_castle ? 5 : 3, rank);
    next.cells[rook_to] = next.cells[rook_from];
    next.cells[rook_from] = 0;
  }
  next.en_passant = move.type == MoveType::jump ? (move.from + move.to) / 2 : -1;
  auto lose = [&](std::uint8_t rights) { next.castling &= static_cast<std::uint8_t>(~rights); };
  if (moving == Piece::king) lose(side == Color::white ? white_king | white_queen
                                                       : black_king | black_queen);
  if (move.from == square_of(0, 0) || move.to == square_of(0, 0)) lose(white_queen);
  if (move.from == square_of(7, 0) || move.to == square_of(7, 0)) lose(white_king);
  if (move.from == square_of(0, 7) || move.to == square_of(0, 7)) lose(black_queen);
  if (move.from == square_of(7, 7) || move.to == square_of(7, 7)) lose(black_king);
  if (next.in_check(side)) return std::nullopt;
  return next;
}

std::vector<Move> Position::legal(Color side) const {
  std::vector<Move> result;
  for (const Move& move : pseudo_legal(side)) if (apply(move)) result.push_back(move);
  return result;
}

std::vector<Move> Board::legal_moves() const { return position.legal(turn); }

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

bool same_repetition_position(const Position& left, Color left_turn,
                              const Position& right, Color right_turn) {
  if (left_turn != right_turn || left.cells != right.cells ||
      left.castling != right.castling)
    return false;
  return effective_en_passant(left, left_turn) ==
         effective_en_passant(right, right_turn);
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
    if (position.castling & (1U << bit)) key ^= zobrist_value(768 + bit);
  if (turn == Color::black) key ^= zobrist_value(772);
  const int ep = effective_en_passant(position, turn);
  if (ep >= 0) key ^= zobrist_value(773 + file_of(ep));
  return key;
}

bool Board::push(const Move& move) {
  auto next = position.apply(move);
  if (!next) return false;
  history.push_back({position, turn, halfmove, fullmove, move, has_castled,
                     nnue, key});
  const Position before = position;
  position = *next;
  nnue_update(nnue, before, position);
  if (move.is_castle()) has_castled[color_index(turn)] = true;
  halfmove = (move.piece == Piece::pawn || move.is_capture() || move.is_castle()) ? 0 : halfmove + 1;
  if (turn == Color::black) ++fullmove;
  turn = opponent(turn);
  key = position_key(position, turn);
  return true;
}

bool Board::push_uci(std::string_view text) {
  auto parsed = parse_uci_move(text);
  if (!parsed) return false;
  for (const Move& move : legal_moves())
    if (move.same_coordinates(*parsed)) return push(move);
  return false;
}

bool Board::pop() {
  if (history.empty()) return false;
  auto state = history.back(); history.pop_back();
  position = state.position; turn = state.turn; halfmove = state.halfmove;
  fullmove = state.fullmove; has_castled = state.has_castled; nnue = state.nnue;
  key = state.key;
  return true;
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
  for (const Snapshot& state : history) {
    if (state.key == key &&
        same_repetition_position(position, turn, state.position, state.turn))
      ++count;
  }
  return count;
}

bool Board::is_threefold_repetition() const { return repetition_count() >= 3; }

bool Board::is_fifty_move_draw() const { return halfmove >= 100; }

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

std::optional<Board> parse_fen(std::string_view fen, std::string* error) {
  auto fail = [&](std::string message) -> std::optional<Board> {
    if (error) *error = std::move(message);
    return std::nullopt;
  };
  auto fields = split(fen);
  if (fields.size() != 6) return fail("FEN must contain six fields");
  Board board; board.position.cells.fill(0); board.position.castling = 0;
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
    board.position.cells[square_of(file++, rank)] = static_cast<std::int8_t>(sign * static_cast<int>(piece));
  }
  if (rank != 0 || file != 8) return fail("invalid piece placement");
  if (fields[1] == "w") board.turn = Color::white;
  else if (fields[1] == "b") board.turn = Color::black;
  else return fail("invalid active color");
  if (fields[2] != "-") for (char c : fields[2]) {
    switch (c) {
      case 'K': board.position.castling |= white_king; break;
      case 'Q': board.position.castling |= white_queen; break;
      case 'k': board.position.castling |= black_king; break;
      case 'q': board.position.castling |= black_queen; break;
      default: return fail("invalid castling rights");
    }
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
    if (board.position.castling & white_king) out << 'K';
    if (board.position.castling & white_queen) out << 'Q';
    if (board.position.castling & black_king) out << 'k';
    if (board.position.castling & black_queen) out << 'q';
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

Searcher::Searcher(EngineConfig config, std::atomic_bool& stopped)
    : config_(std::move(config)), stopped_(stopped) {}

bool Searcher::halted() {
  if (stopped_.load(std::memory_order_relaxed)) return true;
  if (limits_.nodes && nodes_ >= limits_.nodes) return true;
  if (limits_.deadline && std::chrono::steady_clock::now() >= *limits_.deadline) return true;
  return false;
}

int Searcher::material(const Position& pos, Color side, const std::array<int, 7>& values) const {
  int score = 0;
  for (int sq = 0; sq < 64; ++sq) {
    if (pos.empty(sq)) continue;
    int value = values[static_cast<int>(pos.piece_at(sq))];
    score += pos.color_at(sq) == side ? value : -value;
  }
  return score;
}

int Searcher::turochamp_eval(const Board& board) const {
  const auto count_material = [&](Color side) {
    double value = 0.0;
    for (int sq = 0; sq < 64; ++sq) if (board.position.color_at(sq) == side) {
      switch (board.position.piece_at(sq)) {
        case Piece::pawn: value += 1; break; case Piece::knight: value += 3; break;
        case Piece::bishop: value += 3.5; break; case Piece::rook: value += 5; break;
        case Piece::queen: value += 10; break; default: break;
      }
    }
    return value == 0 ? .5 : value;
  };
  const auto position_play = [&](Color side) {
    double score = 0.0;
    const auto moves = board.position.legal(side);
    std::array<int,64> mobility{};
    for (const auto& move : moves) if (move.piece != Piece::pawn && !move.is_castle())
      mobility[move.from] += move.is_capture() ? 2 : 1;
    for (int n : mobility) if (n) score += std::round(10 * std::sqrt(n)) / 10;
    for (int sq = 0; sq < 64; ++sq) if (board.position.color_at(sq) == side) {
      Piece p = board.position.piece_at(sq);
      if (p == Piece::rook || p == Piece::bishop || p == Piece::knight) {
        int d = board.position.attackers(side, sq); if (d) score += 1; if (d > 1) score += .5;
      }
      if (p == Piece::pawn) {
        score += .2 * (side == Color::white ? rank_of(sq) - 1 : 6 - rank_of(sq));
        if (board.position.attackers(side, sq) > 0) score += .3;
      }
    }
    if (board.position.castling & (side == Color::white ? white_king | white_queen : black_king | black_queen)) score += 1;
    if (board.has_castled[color_index(side)]) score += 1;
    if (board.position.in_check(opponent(side))) score += .5;
    int king = board.position.king_square(side);
    if (king >= 0) {
      Position empty_queen = board.position;
      int mobility_count = 0;
      for (const auto& m : empty_queen.pseudo_legal(side)) if (m.from == king && m.piece == Piece::king) ++mobility_count;
      score -= std::round(10 * std::sqrt(mobility_count)) / 10;
    }
    return score;
  };
  Color side = board.turn;
  double own = count_material(side), opp = count_material(opponent(side));
  double ratio = own == opp ? 0 : (own > opp ? own / opp : -opp / own);
  return static_cast<int>(std::round(ratio * 100) * 1000 +
                          std::round((position_play(side) - position_play(opponent(side))) * 100));
}

int Searcher::sargon_eval(const Board& board) const {
  static constexpr std::array<int,7> values{0,100,300,300,500,900,0};
  int score = material(board.position, board.turn, values) * 4;
  int mobility = static_cast<int>(board.position.legal(board.turn).size()) -
                 static_cast<int>(board.position.legal(opponent(board.turn)).size());
  int control = 0;
  for (int sq = 0; sq < 64; ++sq)
    control += board.position.attackers(board.turn, sq) - board.position.attackers(opponent(board.turn), sq);
  auto development = [&](Color side) {
    int result = 0, rank = side == Color::white ? 0 : 7;
    for (int f : {1,2,5,6}) {
      int sq = square_of(f, rank);
      Piece p = board.position.piece_at(sq);
      if (board.position.color_at(sq) == side && (p == Piece::bishop || p == Piece::knight)) result -= 200;
    }
    if (board.has_castled[color_index(side)]) result += 600;
    else if (board.has_moved_from(square_of(4, rank))) result -= 200;
    return result;
  };
  return score + std::clamp((mobility + control) * 10, -600, 600) +
         development(board.turn) - development(opponent(board.turn));
}

int Searcher::bernstein_eval(const Board& board) const {
  const auto value = [&](Color side) {
    static constexpr std::array<int,7> values{0,1,3,3,5,9,0};
    int mat = 0, control = 0;
    for (int sq = 0; sq < 64; ++sq) {
      if (board.position.color_at(sq) == side) mat += values[static_cast<int>(board.position.piece_at(sq))];
      if (board.position.attackers(side, sq) > board.position.attackers(opponent(side), sq)) ++control;
    }
    int mobility = static_cast<int>(board.position.legal(side).size());
    int defense = 0, king = board.position.king_square(side);
    if (king >= 0) for (int df=-1;df<=1;++df) for(int dr=-1;dr<=1;++dr) {
      int f=file_of(king)+df,r=rank_of(king)+dr;
      if ((df||dr)&&inside(f,r)&&board.position.attackers(side,square_of(f,r))>
          board.position.attackers(opponent(side),square_of(f,r))) ++defense;
    }
    return std::max(1, mobility + control + defense + config_.material_factor * mat);
  };
  int self = value(board.turn), opp = value(opponent(board.turn));
  if (self == opp) return 0;
  return self > opp ? self * 10000 / opp : -opp * 10000 / self;
}

int Searcher::evaluate(const Board& board) {
  int score = 0;
  switch (config_.kind) {
    case EngineKind::turochamp: score = turochamp_eval(board); break;
    case EngineKind::sargon: score = sargon_eval(board); break;
    case EngineKind::bernstein: score = bernstein_eval(board); break;
    default: score = nnue_evaluate(board.nnue, board.turn); break;
  }
  if (config_.noise_millipawns > 0) {
    std::uniform_int_distribution<int> noise(-config_.noise_millipawns, config_.noise_millipawns);
    score += noise(random_) / 10;
  }
  return score;
}

std::vector<Move> Searcher::ordered_moves(const Board& board) const {
  auto moves = board.legal_moves();
  auto priority = [&](const Move& move) {
    int p = move.is_capture() ? 100 * nominal(move.capture) - nominal(move.piece) : 0;
    if (move.is_promotion()) p += nominal(move.promotion);
    if (config_.kind == EngineKind::bernstein) {
      if (move.is_castle()) p += 200000;
      if (move.piece == Piece::bishop || move.piece == Piece::knight) {
        int home = board.turn == Color::white ? 0 : 7;
        if (rank_of(move.from) == home) p += 1300;
      }
      if (move.piece == Piece::pawn) {
        static constexpr int pawn_file[8]{1,3,6,7,8,5,4,2};
        p += 1000 + pawn_file[file_of(move.from)];
      }
    }
    return p;
  };
  std::stable_sort(moves.begin(), moves.end(), [&](const Move& a, const Move& b) {
    return priority(a) > priority(b);
  });
  if (config_.kind == EngineKind::sargon)
    moves.erase(std::remove_if(moves.begin(), moves.end(), [](const Move& m) {
      return m.is_promotion() && m.promotion != Piece::queen;
    }), moves.end());
  if (config_.kind == EngineKind::bernstein && config_.branch > 0 &&
      moves.size() > static_cast<std::size_t>(config_.branch)) moves.resize(config_.branch);
  return moves;
}

std::uint64_t Searcher::hash(const Board& board) const {
  std::uint64_t h = 1469598103934665603ULL;
  for (auto cell : board.position.cells) { h ^= static_cast<std::uint8_t>(cell + 8); h *= 1099511628211ULL; }
  h ^= board.position.castling; h *= 1099511628211ULL;
  h ^= static_cast<std::uint64_t>(board.position.en_passant + 1); h *= 1099511628211ULL;
  h ^= static_cast<int>(board.turn);
  return h;
}

int Searcher::quiescence(Board& board, int alpha, int beta, int ply) {
  if (halted()) return 0;
  ++nodes_;
  int stand = evaluate(board);
  if (stand >= beta) return beta;
  alpha = std::max(alpha, stand);
  if (ply >= 16) return alpha;
  for (const auto& move : ordered_moves(board)) {
    if (!move.is_capture() && !move.is_promotion()) continue;
    board.push(move);
    int score = -quiescence(board, -beta, -alpha, ply + 1);
    board.pop();
    if (halted()) return 0;
    if (score >= beta) return beta;
    alpha = std::max(alpha, score);
  }
  return alpha;
}

int Searcher::negamax(Board& board, int depth, int alpha, int beta, int ply,
                      std::vector<Move>& pv) {
  if (halted()) return 0;
  ++nodes_;
  // At the UCI root we still return a legal move; game adjudication belongs to
  // the host. Inside the tree, all claimable/dead positions score as draws.
  if (ply > 0 && (board.is_fifty_move_draw() ||
                  board.is_threefold_repetition() ||
                  board.position.insufficient_material()))
    return 0;
  auto moves = ordered_moves(board);
  if (moves.empty()) return board.position.in_check(board.turn) ? -mate_score + ply : 0;
  if (depth <= 0) {
    if (config_.kind == EngineKind::sargon && board.position.in_check(board.turn) && ply < 32) depth = 1;
    else if (config_.kind == EngineKind::turochamp) return quiescence(board, alpha, beta, 0);
    else return evaluate(board);
  }
  const int original_alpha = alpha;
  Move best;
  std::uint64_t key = hash(board);
  auto found = table_.find(key);
  if (found != table_.end() && found->second.depth >= depth) {
    const auto& e = found->second;
    if (e.flag == 0) return e.score;
    if (e.flag < 0 && e.score <= alpha) return e.score;
    if (e.flag > 0 && e.score >= beta) return e.score;
  }
  int best_score = -infinity;
  int move_index = 0;
  const bool in_check = board.position.in_check(board.turn);
  for (const auto& move : moves) {
    board.push(move);
    std::vector<Move> child;
    int score;
    const bool quiet = !move.is_capture() && !move.is_promotion() && !move.is_castle();
    const bool reduce = depth >= 3 && move_index >= 4 && quiet && !in_check;
    if (reduce) {
      const int reduction = 1 + (depth >= 6 && move_index >= 10 ? 1 : 0);
      ++lmr_reductions_;
      score = -negamax(board, std::max(0, depth - 1 - reduction),
                       -alpha - 1, -alpha, ply + 1, child);
      if (score > alpha && score < beta) {
        child.clear();
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1, child);
      }
    } else {
      score = -negamax(board, depth - 1, -beta, -alpha, ply + 1, child);
    }
    board.pop();
    if (halted()) return 0;
    if (score > best_score) { best_score = score; best = move; }
    if (score > alpha) { alpha = score; pv = {move}; pv.insert(pv.end(), child.begin(), child.end()); }
    if (alpha >= beta) break;
    ++move_index;
  }
  int flag = best_score <= original_alpha ? -1 : (best_score >= beta ? 1 : 0);
  if (config_.hash_mb > 0) {
    std::size_t cap = static_cast<std::size_t>(config_.hash_mb) * 1024 * 1024 / 40;
    if (table_.size() >= cap && cap) table_.clear();
    table_[key] = {depth, best_score, flag, best};
  }
  return best_score;
}

SearchResult Searcher::iterative(Board board, SearchLimits limits,
                                 const std::function<void(const SearchResult&)>& info) {
  limits_ = limits;
  limits_.depth = std::clamp(limits_.depth, 0, maximum_search_depth);
  nodes_ = 0; lmr_reductions_ = 0; table_.clear(); started_ = std::chrono::steady_clock::now();
  SearchResult last;
  int max_depth = limits_.depth > 0 ? limits_.depth : maximum_search_depth;
  for (int depth = 1; depth <= max_depth && !halted(); ++depth) {
    std::vector<Move> pv;
    int score = negamax(board, depth, -infinity, infinity, 0, pv);
    if (halted() && pv.empty()) break;
    last.depth = depth; last.score_cp = score; last.nodes = nodes_;
    last.lmr_reductions = lmr_reductions_; last.pv = std::move(pv);
    last.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - started_);
    if (std::abs(score) >= mate_score - 1000)
      last.mate = score > 0 ? (mate_score - score + 1) / 2 : -(mate_score + score + 1) / 2;
    if (info) info(last);
    if (limits_.depth > 0 && depth >= limits_.depth) break;
    if (last.mate != 0) break;
  }
  return last;
}

std::uint64_t perft(Position position, Color side, int depth,
                    std::vector<std::pair<Move, std::uint64_t>>* divide) {
  if (depth == 0) return 1;
  std::uint64_t total = 0;
  for (const Move& move : position.legal(side)) {
    auto next = position.apply(move);
    std::uint64_t count = perft(*next, opponent(side), depth - 1, nullptr);
    if (divide) divide->push_back({move, count});
    total += count;
  }
  return total;
}

std::optional<Move> opening_move(const EngineConfig& config, const Board& board) {
  if (!config.own_book) return std::nullopt;
  auto choose = [&](std::string_view uci) -> std::optional<Move> {
    auto parsed = parse_uci_move(uci); if (!parsed) return std::nullopt;
    for (const auto& move : board.legal_moves()) if (move.same_coordinates(*parsed)) return move;
    return std::nullopt;
  };
  if (board.history.empty() && board.turn == Color::white) {
    return config.kind == EngineKind::bernstein ? choose("e2e4") : choose("d2d4");
  }
  if (config.kind == EngineKind::sargon && board.history.size() == 1 && board.turn == Color::black) {
    const Move first = board.history.front().move;
    bool king_side_response = first.piece == Piece::pawn &&
      (file_of(first.from) == 0 || file_of(first.from) == 1 || file_of(first.from) == 2 || file_of(first.from) == 4);
    return choose(king_side_response ? "e7e5" : "d7d5");
  }
  return std::nullopt;
}

EngineConfig default_config(EngineKind kind) {
  EngineConfig config; config.kind = kind;
  switch (kind) {
    case EngineKind::turochamp:
      config.name = "TUROCHAMP (1948)"; config.author = "Alan Turing and David Champernowne";
      config.depth = 2; config.noise_millipawns = 10; config.hash_mb = 0; break;
    case EngineKind::sargon:
      config.name = "SARGON (1978)"; config.author = "Dan and Kathe Spracklen";
      config.depth = 1; config.noise_millipawns = 10; config.hash_mb = 0; config.own_book = true; break;
    case EngineKind::bernstein:
      config.name = "BERNSTEIN (1957)";
      config.author = "Alex Bernstein, Michael de V. Roberts, Timothy Arbuckle and Martin Belsky";
      config.depth = 4; config.branch = 7; config.noise_millipawns = 0; config.hash_mb = 0; config.own_book = true; break;
    default:
      config.name = "Eloi"; config.author = "Sahil Das";
      config.depth = 8; config.hash_mb = 128; config.noise_millipawns = 0;
      break;
  }
  return config;
}

}  // namespace morlock
