#pragma once

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace morlock {

inline constexpr std::string_view initial_fen =
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
inline constexpr int maximum_search_depth = 40;
inline constexpr int nnue_hidden_size = 64;
using NnueAccumulator = std::array<std::int32_t, nnue_hidden_size>;

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
  std::vector<Move> pseudo_legal(Color side) const;
  std::vector<Move> legal(Color side) const;
  std::optional<Position> apply(const Move& move) const;
};

NnueAccumulator nnue_refresh(const Position& position);
void nnue_update(NnueAccumulator& accumulator, const Position& before,
                 const Position& after);
int nnue_evaluate(const NnueAccumulator& accumulator, Color side_to_move);

struct Board {
  struct Snapshot {
    Position position;
    Color turn{Color::white};
    int halfmove{0};
    int fullmove{1};
    Move move{};
    std::array<bool, 2> has_castled{};
    NnueAccumulator nnue{};
  };

  Position position;
  Color turn{Color::white};
  int halfmove{0};
  int fullmove{1};
  std::array<bool, 2> has_castled{};
  NnueAccumulator nnue{};
  std::vector<Snapshot> history;

  std::vector<Move> legal_moves() const;
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

enum class EngineKind { morlock, turochamp, sargon, bernstein };

struct EngineConfig {
  EngineKind kind{EngineKind::morlock};
  std::string name{"morlock"};
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
  std::uint64_t lmr_reductions{0};
  std::chrono::milliseconds elapsed{};
  std::vector<Move> pv;
};

class Searcher {
 public:
  Searcher(EngineConfig config, std::atomic_bool& stopped);
  SearchResult iterative(Board board, SearchLimits limits,
                         const std::function<void(const SearchResult&)>& info = {});

 private:
  struct TTEntry { int depth; int score; int flag; Move best; };
  EngineConfig config_;
  std::atomic_bool& stopped_;
  std::uint64_t nodes_{0};
  std::uint64_t lmr_reductions_{0};
  SearchLimits limits_;
  std::chrono::steady_clock::time_point started_{};
  std::mt19937 random_{0};
  std::unordered_map<std::uint64_t, TTEntry> table_;

  bool halted();
  int evaluate(const Board& board);
  int material(const Position& pos, Color side, const std::array<int, 7>& values) const;
  int turochamp_eval(const Board& board) const;
  int sargon_eval(const Board& board) const;
  int bernstein_eval(const Board& board) const;
  int quiescence(Board& board, int alpha, int beta, int ply);
  int negamax(Board& board, int depth, int alpha, int beta, int ply,
              std::vector<Move>& pv);
  std::vector<Move> ordered_moves(const Board& board) const;
  std::uint64_t hash(const Board& board) const;
};

std::uint64_t perft(Position position, Color side, int depth,
                    std::vector<std::pair<Move, std::uint64_t>>* divide = nullptr);

std::optional<Move> opening_move(const EngineConfig& config, const Board& board);
EngineConfig default_config(EngineKind kind);
int run_engine(EngineConfig config, int argc, char** argv);
int run_perft(int argc, char** argv);
int run_livechess_adapter(int argc, char** argv);
int run_gui(int argc, char** argv);

}  // namespace morlock
