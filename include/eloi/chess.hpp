#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <vector>

#include "eloi/nnue_architecture.hpp"

namespace eloi {

inline constexpr std::string_view initial_fen =
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
inline constexpr std::string_view horde_initial_fen =
    "rnbqkbnr/pppppppp/8/1PP2PP1/PPPPPPPP/PPPPPPPP/PPPPPPPP/PPPPPPPP w kq - 0 1";
inline constexpr int recommended_search_depth = 40;
inline constexpr int maximum_gui_search_depth = 200;
inline constexpr int maximum_search_depth = 17'697;
inline constexpr int search_thread_count = 3;
using NnueAccumulator = std::array<std::int32_t, nnue_hidden_size>;
struct NnueState {
  std::array<NnueAccumulator, 2> perspective{};
  bool operator==(const NnueState&) const = default;
};

enum class Color : std::uint8_t { white, black };
enum class Piece : std::uint8_t { none, pawn, bishop, knight, rook, queen, king };
enum class MoveType : std::uint8_t {
  normal, push, jump, en_passant, queen_castle, king_castle, capture,
  promotion, capture_promotion, horde_jump
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

using PackedMove = std::uint16_t;
PackedMove pack_move(const Move& move);
Move unpack_move(PackedMove move);
int score_to_tt(int score, int ply);
int score_from_tt(int score, int ply);

struct Position;
int static_exchange_evaluation(const Position& position, Color side,
                               const Move& move);

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
  // Search-facing bitboards mirror cells. Keeping the mailbox makes FEN,
  // Chess960, Horde, and the GUI straightforward while move generation and
  // attack detection avoid rescanning all 64 squares at every node.
  std::array<std::array<std::uint64_t, 7>, 2> piece_bits{};
  std::array<std::uint64_t, 2> color_bits{};
  std::uint64_t occupied{};
  std::array<std::int8_t, 2> king_squares{-1, -1};
  std::uint8_t castling{white_king | white_queen | black_king | black_queen};
  // Rook origins for WK, WQ, BK, BQ rights. Chess960 castling always ends
  // with the king on g/c and rook on f/d, regardless of their start squares.
  std::array<std::int8_t, 4> castling_rooks{
      square_of(7, 0), square_of(0, 0),
      square_of(7, 7), square_of(0, 7)};
  int en_passant{-1};

  void clear_pieces();
  void set_cell(int square, std::int8_t cell);
  void rebuild_bitboards();
  std::uint64_t pieces(Color side, Piece piece) const;
  std::uint64_t occupancy(Color side) const;
  Piece piece_at(int square) const;
  std::optional<Color> color_at(int square) const;
  bool empty(int square) const;
  int king_square(Color side) const;
  bool attacked_by(Color side, int square) const;
  int attackers(Color side, int square) const;
  bool in_check(Color side) const;
  bool insufficient_material() const;
  MoveList pseudo_legal(Color side, bool horde = false) const;
  MoveList legal(Color side, bool horde = false) const;
  std::optional<Position> apply(const Move& move) const;
};

NnueState nnue_refresh(const Position& position);
NnueState nnue_refresh_scalar_reference(const Position& position);
bool nnue_runtime_has_avx2();
void nnue_update(NnueState& accumulator, const Position& before,
                 const Position& after);
void nnue_update_changed(NnueState& accumulator, const Position& before,
                         const Position& after,
                         const std::array<std::uint8_t, 4>& squares,
                         std::uint8_t count);
void nnue_update_delta(NnueState& accumulator,
                       const std::array<std::int8_t, 2>& before_kings,
                       const Position& after,
                       const std::array<std::uint8_t, 4>& squares,
                       const std::array<std::int8_t, 4>& before_cells,
                       std::uint8_t count);
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
    std::array<std::int8_t, 4> castling_rooks{};
    std::int8_t en_passant{-1};
    std::int8_t effective_en_passant{-1};
    std::uint64_t key{};
    std::array<std::uint64_t, 4> packed_cells{};
  };

  struct SearchUndo {
    Color turn{Color::white};
    int halfmove{0};
    int fullmove{1};
    std::array<bool, 2> has_castled{};
    std::uint8_t castling{};
    std::array<std::int8_t, 4> castling_rooks{};
    std::int8_t en_passant{-1};
    std::int8_t effective_en_passant{-1};
    std::array<std::int8_t, 2> king_squares{-1, -1};
    std::uint64_t key{};
    Move move{};
    std::array<std::uint8_t, 4> squares{};
    std::array<std::int8_t, 4> cells{};
    std::uint8_t changed{};
    bool null_move{false};
  };

  Position position;
  Color turn{Color::white};
  int halfmove{0};
  int fullmove{1};
  std::array<bool, 2> has_castled{};
  bool chess960{false};
  bool horde{false};
  NnueState nnue{};
  std::uint64_t key{};
  std::vector<Snapshot> history;

  MoveList legal_moves() const;
  bool push(const Move& move);
  bool push_uci(std::string_view text);
  bool pop();
  bool make_search_move(const Move& move, SearchUndo& undo);
  void unmake_search_move(const SearchUndo& undo);
  void make_null_move(SearchUndo& undo);
  std::optional<Move> last_move() const;
  std::optional<Move> second_last_move() const;
  bool has_moved_from(int square) const;
  int repetition_count() const;
  bool is_threefold_repetition() const;
  bool is_fifty_move_draw() const;
  bool horde_eliminated() const;
  std::optional<Color> variant_winner() const;
};

std::optional<int> parse_square(std::string_view text);
std::string square_name(int square);
std::optional<Move> parse_uci_move(std::string_view text);
std::string uci_move(const Move& move, const Position& position,
                     bool chess960);
std::optional<Board> parse_fen(std::string_view fen, std::string* error = nullptr);
std::optional<Board> chess960_start(int index);
std::string to_fen(const Board& board);
std::string board_ascii(const Board& board);

enum class ExactEndgame { none, draw, white_win, black_win };

ExactEndgame probe_exact_endgame(const Board& board);

struct EngineConfig {
  std::string name{"Eloi"};
  std::string author{"herohde"};
  int depth{0};
  int noise_millipawns{0};
  int hash_mb{64};
  int move_overhead_ms{50};
  bool own_book{false};
  bool operator==(const EngineConfig&) const = default;
};

struct SearchLimits {
  int depth{0};
  std::uint64_t nodes{0};
  std::optional<std::chrono::steady_clock::time_point> deadline;
  int remaining_ms{0};
  int increment_ms{0};
  int moves_to_go{0};
  int move_overhead_ms{50};
};

enum class ClockMode {
  none,
  normal,
  pressure,
  emergency,
  panic,
};

struct TimeBudget {
  int base_ms{0};
  int soft_ms{0};
  int hard_ms{0};
  int reserve_ms{0};
  ClockMode mode{ClockMode::none};
};

std::string_view clock_mode_name(ClockMode mode);
TimeBudget plan_time_budget(const Board& board, const SearchLimits& limits);

struct SearchResult {
  int depth{0};
  int score_cp{0};
  int mate{0};
  std::uint64_t nodes{0};
  std::uint64_t qnodes{0};
  std::uint64_t tt_hits{0};
  std::uint64_t beta_cutoffs{0};
  std::uint64_t lmr_reductions{0};
  std::uint64_t quiet_checks{0};
  std::uint64_t null_cutoffs{0};
  std::uint64_t probcut_cutoffs{0};
  std::uint64_t singular_extensions{0};
  std::uint64_t late_move_prunes{0};
  std::uint64_t history_hits{0};
  std::uint64_t countermove_hits{0};
  int allocated_ms{0};
  int hard_limit_ms{0};
  int clock_reserve_ms{0};
  ClockMode clock_mode{ClockMode::none};
  int volatility{0};
  int root_score_gap{0};
  int credible_alternatives{0};
  std::chrono::milliseconds elapsed{};
  std::vector<Move> pv;
  std::string opening_family;
};

class Searcher {
 public:
  Searcher(EngineConfig config, std::atomic_bool& stopped);
  Searcher(EngineConfig config, std::atomic_bool& stopped, int lane);
  ~Searcher();
  SearchResult iterative(Board board, SearchLimits limits,
                         const std::function<void(const SearchResult&)>& info = {});

 private:
  friend struct SearcherTestAccess;
  struct TTEntry {
    std::uint64_t key{};
    std::int32_t score{};
    std::int16_t static_eval{};
    std::int16_t depth{-1};
    PackedMove best{};
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
  std::uint64_t quiet_checks_{0};
  std::uint64_t null_cutoffs_{0};
  std::uint64_t probcut_cutoffs_{0};
  std::uint64_t singular_extensions_{0};
  std::uint64_t late_move_prunes_{0};
  std::uint64_t history_hits_{0};
  std::uint64_t countermove_hits_{0};
  SearchLimits limits_;
  std::chrono::steady_clock::time_point started_{};
  std::mt19937 random_{0};
  std::vector<TTBucket> table_;
  std::uint8_t generation_{1};
  std::vector<std::array<Move, 2>> killers_;
  std::array<std::array<std::array<std::int16_t, 64>, 64>, 2>
      history_scores_{};
  std::array<std::array<std::array<Move, 64>, 64>, 2> countermoves_{};
  std::array<std::array<std::array<std::int16_t, 7>, 64>, 7>
      capture_history_{};
  std::array<std::int16_t, 16'384> continuation_history_{};
  std::vector<std::pair<Move, int>> root_scores_;
  std::vector<std::uint64_t> repetition_keys_;
  Move root_best_{};
  int lane_{0};
  std::array<std::unique_ptr<Searcher>, search_thread_count - 1>
      owned_helpers_{};
  std::array<Searcher*, search_thread_count - 1> root_helpers_{};
  std::array<std::thread, search_thread_count - 1> root_worker_threads_{};
  std::mutex root_work_mutex_;
  std::condition_variable root_work_ready_;
  std::condition_variable root_work_done_;
  std::function<void(int)> root_work_;
  std::uint64_t root_work_epoch_{0};
  int root_work_completed_{0};
  bool root_work_shutdown_{false};

  bool halted();
  void advance_generation();
  void reset_statistics();
  void prepare_root_helper(const Searcher& principal, const Board& root);
  void absorb_statistics(const Searcher& helper);
  std::optional<int> search_root_move(Board root, const Move& move, int depth,
                                      int alpha, int beta, bool pv_node,
                                      const Move& previous);
  int parallel_root(Board& board, const MoveList& moves, int depth,
                    int alpha, int beta, int static_score,
                    const Move& previous);
  SearchResult iterative_single(
      Board board, SearchLimits limits,
      const std::function<void(const SearchResult&)>& info);
  int evaluate(const Board& board);
  int volatility(const Board& board, std::size_t legal_count,
                 int evaluation_swing = 0) const;
  int quiescence(Board& board, int alpha, int beta, int ply, int qply);
  int negamax(Board& board, int depth, int alpha, int beta, int ply,
              bool pv_node, const Move& previous, int extensions,
              PackedMove excluded = 0, bool allow_null = true);
  MoveList ordered_moves(const Board& board, PackedMove tt_move,
                         int ply, const Move& previous,
                         bool legal_only = false);
  std::vector<Move> reconstruct_pv(Board board, const Move& root,
                                   std::size_t maximum = 128) const;
  bool search_draw(const Board& board, int ply) const;
  void update_quiet_history(Color side, const Move& move,
                            const Move& previous, int bonus);
  int quiet_history(Color side, const Move& move,
                    const Move& previous) const;
  TTEntry* probe(std::uint64_t key);
  const TTEntry* find(std::uint64_t key) const;
  void store(std::uint64_t key, int depth, int score, int static_eval,
             int flag, const Move& best, int ply);
};

std::uint64_t perft(Position position, Color side, int depth,
                    std::vector<std::pair<Move, std::uint64_t>>* divide = nullptr,
                    bool horde = false);

struct BookMove {
  Move move{};
  std::string_view family;
};

std::optional<BookMove> opening_move(const EngineConfig& config,
                                     const Board& board);
std::size_t opening_book_size();
std::size_t opening_book_node_count();
EngineConfig default_config();
int run_engine(EngineConfig config, int argc, char** argv);
int run_perft(int argc, char** argv);
int run_benchmark(int argc, char** argv);
int run_livechess_adapter(int argc, char** argv);
int run_gui(int argc, char** argv);

}  // namespace eloi
