#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <vector>

namespace eloi {

inline constexpr std::string_view initial_fen =
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
inline constexpr int maximum_search_depth = 40;
inline constexpr int nnue_hidden_size = 64;
using NnueAccumulator = std::array<std::int32_t, nnue_hidden_size>;
struct NnueState {
  std::array<NnueAccumulator, 2> perspective{};
  bool operator==(const NnueState&) const = default;
};

enum class Color : std::uint8_t { white, black };
enum class Piece : std::uint8_t { none, pawn, bishop, knight, rook, queen, king };
enum class MoveType : std::uint8_t {
  normal, push, jump, en_passant, queen_castle, king_castle, capture,
  promotion, capture_promotion
};
enum Castling : std::uint8_t {
  white_king = 1, white_queen = 2, black_king = 4, black_queen = 8
};

constexpr Color opponent(Color c) { return c == Color::white ? Color::black : Color::white; }
constexpr int file_of(int square) { return square & 7; }
constexpr int rank_of(int square) { return square >> 3; }
constexpr int square_of(int file, int rank) { return rank * 8 + file; }

struct Move {
  MoveType type{MoveType::normal};
  int from{-1};
  int to{-1};
  Piece piece{Piece::none};
  Piece promotion{Piece::none};
  Piece capture{Piece::none};

  bool is_capture() const;
  bool is_promotion() const;
  bool is_castle() const;
  bool same_coordinates(const Move& other) const;
  std::string uci() const;
  std::string describe() const;
};

class MoveList {
 public:
  static constexpr std::size_t capacity = 256;
  using iterator = std::array<Move, capacity>::iterator;
  using const_iterator = std::array<Move, capacity>::const_iterator;

  iterator begin() { return moves_.begin(); }
  iterator end() { return moves_.begin() + static_cast<std::ptrdiff_t>(size_); }
  const_iterator begin() const { return moves_.begin(); }
  const_iterator end() const { return moves_.begin() + static_cast<std::ptrdiff_t>(size_); }
  bool empty() const { return size_ == 0; }
  std::size_t size() const { return size_; }
  Move& front() { return moves_.front(); }
  const Move& front() const { return moves_.front(); }
  Move& operator[](std::size_t index) { return moves_[index]; }
  const Move& operator[](std::size_t index) const { return moves_[index]; }
  void reserve(std::size_t) {}
  void push_back(const Move& move) {
    if (size_ < capacity) moves_[size_++] = move;
  }
  void resize(std::size_t size) { size_ = std::min(size, capacity); }
  iterator erase(iterator first, iterator last) {
    size_ -= static_cast<std::size_t>(last - first);
    return first;
  }

 private:
  std::array<Move, capacity> moves_{};
  std::size_t size_{};
};

struct Position {
  // Positive entries are white pieces, negative entries are black pieces.
  std::array<std::int8_t, 64> cells{};
  std::uint8_t castling{white_king | white_queen | black_king | black_queen};
  int en_passant{-1};

  Piece piece_at(int square) const;
  std::optional<Color> color_at(int square) const;
  bool empty(int square) const;
  int king_square(Color side) const;
  bool attacked_by(Color side, int square) const;
  int attackers(Color side, int square) const;
  bool in_check(Color side) const;
  bool insufficient_material() const;
  MoveList pseudo_legal(Color side) const;
  MoveList legal(Color side) const;
  std::optional<Position> apply(const Move& move) const;
};

NnueState nnue_refresh(const Position& position);
void nnue_update(NnueState& accumulator, const Position& before,
                 const Position& after);
int nnue_evaluate(const NnueState& accumulator, Color side_to_move);
std::uint64_t position_key(const Position& position, Color turn);

struct Board {
  struct Snapshot {
    Color turn{Color::white};
    int halfmove{0};
    int fullmove{1};
    Move move{};
    std::array<bool, 2> has_castled{};
    std::uint8_t castling{};
    std::int8_t en_passant{-1};
    std::int8_t effective_en_passant{-1};
    std::uint64_t key{};
    std::array<std::uint64_t, 4> packed_cells{};
  };

  Position position;
  Color turn{Color::white};
  int halfmove{0};
  int fullmove{1};
  std::array<bool, 2> has_castled{};
  NnueState nnue{};
  std::uint64_t key{};
  std::vector<Snapshot> history;

  MoveList legal_moves() const;
  bool push(const Move& move);
  bool push_uci(std::string_view text);
  bool pop();
  std::optional<Move> last_move() const;
  std::optional<Move> second_last_move() const;
  bool has_moved_from(int square) const;
  int repetition_count() const;
  bool is_threefold_repetition() const;
  bool is_fifty_move_draw() const;
};

std::optional<int> parse_square(std::string_view text);
std::string square_name(int square);
std::optional<Move> parse_uci_move(std::string_view text);
std::optional<Board> parse_fen(std::string_view fen, std::string* error = nullptr);
std::string to_fen(const Board& board);
std::string board_ascii(const Board& board);

enum class EngineKind { eloi, turochamp, sargon, bernstein };

struct EngineConfig {
  EngineKind kind{EngineKind::eloi};
  std::string name{"Eloi"};
  std::string author{"herohde"};
  int depth{0};
  int branch{0};
  int material_factor{20};
  int noise_millipawns{0};
  int hash_mb{64};
  bool own_book{false};
};

struct SearchLimits {
  int depth{0};
  std::uint64_t nodes{0};
  std::optional<std::chrono::steady_clock::time_point> deadline;
};

struct SearchResult {
  int depth{0};
  int score_cp{0};
  int mate{0};
  std::uint64_t nodes{0};
  std::uint64_t qnodes{0};
  std::uint64_t tt_hits{0};
  std::uint64_t beta_cutoffs{0};
  std::uint64_t lmr_reductions{0};
  std::chrono::milliseconds elapsed{};
  std::vector<Move> pv;
  std::string opening_family;
};

class Searcher {
 public:
  Searcher(EngineConfig config, std::atomic_bool& stopped);
  SearchResult iterative(Board board, SearchLimits limits,
                         const std::function<void(const SearchResult&)>& info = {});

 private:
  struct TTEntry {
    std::uint64_t key{};
    Move best{};
    std::int32_t score{};
    std::int16_t depth{-1};
    std::int8_t flag{};
    std::uint8_t generation{};
  };
  struct TTBucket { std::array<TTEntry, 4> entries{}; };
  EngineConfig config_;
  std::atomic_bool& stopped_;
  std::uint64_t nodes_{0};
  std::uint64_t qnodes_{0};
  std::uint64_t tt_hits_{0};
  std::uint64_t beta_cutoffs_{0};
  std::uint64_t lmr_reductions_{0};
  SearchLimits limits_;
  std::chrono::steady_clock::time_point started_{};
  std::mt19937 random_{0};
  std::vector<TTBucket> table_;
  std::uint8_t generation_{1};
  std::array<std::array<Move, 2>, maximum_search_depth + 32> killers_{};
  std::array<std::array<int, 64>, 64> history_scores_{};

  bool halted();
  int evaluate(const Board& board);
  int material(const Position& pos, Color side, const std::array<int, 7>& values) const;
  int turochamp_eval(const Board& board) const;
  int sargon_eval(const Board& board) const;
  int bernstein_eval(const Board& board) const;
  int quiescence(Board& board, int alpha, int beta, int ply);
  int negamax(Board& board, int depth, int alpha, int beta, int ply,
              std::vector<Move>& pv);
  MoveList ordered_moves(const Board& board, const Move* tt_move,
                         int ply) const;
  TTEntry* probe(std::uint64_t key);
  void store(std::uint64_t key, int depth, int score, int flag,
             const Move& best);
};

std::uint64_t perft(Position position, Color side, int depth,
                    std::vector<std::pair<Move, std::uint64_t>>* divide = nullptr);

struct BookMove {
  Move move{};
  std::string_view family;
};

std::optional<BookMove> opening_move(const EngineConfig& config,
                                     const Board& board);
std::size_t opening_book_size();
std::size_t opening_book_node_count();
EngineConfig default_config(EngineKind kind);
int run_engine(EngineConfig config, int argc, char** argv);
int run_perft(int argc, char** argv);
int run_benchmark(int argc, char** argv);
int run_livechess_adapter(int argc, char** argv);
int run_gui(int argc, char** argv);

}  // namespace eloi
