#include "eloi/chess.hpp"

#include "eloi/nnue_weights.hpp"

#include <algorithm>
#include <cstdlib>

namespace eloi {
namespace {

constexpr int quantization = 8;

int perspective_index(Color side) { return side == Color::white ? 0 : 1; }

int oriented_square(int square, Color perspective) {
  return perspective == Color::white ? square : square ^ 56;
}

int king_bucket(const Position& position, Color perspective) {
  const int king = position.king_square(perspective);
  if (king < 0) return 0;
  const int square = oriented_square(king, perspective);
  return (file_of(square) >= 4 ? 1 : 0) + 2 * (rank_of(square) / 2);
}

int feature_of(std::int8_t cell, int square, int bucket,
               Color perspective) {
  if (!cell) return -1;
  const Color piece_color = cell > 0 ? Color::white : Color::black;
  const int relative_color = piece_color == perspective ? 0 : 1;
  const int piece = std::abs(static_cast<int>(cell)) - 1;
  const int plane = relative_color * 6 + piece;
  return (bucket * 12 + plane) * 64 + oriented_square(square, perspective);
}

void add_feature(NnueAccumulator& accumulator, int feature, int sign) {
  if (feature < 0) return;
  const std::size_t offset = static_cast<std::size_t>(feature) * nnue_hidden_size;
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden)
    accumulator[hidden] += sign * nnue_weights::input[offset + hidden];
}

NnueAccumulator refresh_perspective(const Position& position,
                                    Color perspective) {
  NnueAccumulator result{};
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden)
    result[hidden] = nnue_weights::bias[hidden];
  const int bucket = king_bucket(position, perspective);
  for (int square = 0; square < 64; ++square)
    add_feature(result,
                feature_of(position.cells[square], square, bucket, perspective),
                1);
  return result;
}

std::int64_t activate(const NnueAccumulator& accumulator) {
  std::int64_t sum = 0;
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden) {
    const int value = std::clamp(accumulator[hidden], 0, 127);
    sum += static_cast<std::int64_t>(value) * nnue_weights::output[hidden];
  }
  return sum;
}

}  // namespace

NnueState nnue_refresh(const Position& position) {
  NnueState state;
  state.perspective[0] = refresh_perspective(position, Color::white);
  state.perspective[1] = refresh_perspective(position, Color::black);
  return state;
}

void nnue_update(NnueState& state, const Position& before,
                 const Position& after) {
  for (Color perspective : {Color::white, Color::black}) {
    const int index = perspective_index(perspective);
    const int before_bucket = king_bucket(before, perspective);
    const int after_bucket = king_bucket(after, perspective);
    if (before_bucket != after_bucket) {
      state.perspective[index] = refresh_perspective(after, perspective);
      continue;
    }
    for (int square = 0; square < 64; ++square) {
      if (before.cells[square] == after.cells[square]) continue;
      add_feature(state.perspective[index],
                  feature_of(before.cells[square], square, before_bucket,
                             perspective), -1);
      add_feature(state.perspective[index],
                  feature_of(after.cells[square], square, after_bucket,
                             perspective), 1);
    }
  }
}

int nnue_evaluate(const NnueState& state, Color side_to_move) {
  const std::int64_t white_score = activate(state.perspective[0]);
  const std::int64_t black_score = activate(state.perspective[1]);
  int score = static_cast<int>((white_score - black_score) / quantization);
  if (side_to_move == Color::black) score = -score;
  return score + 10;
}

}  // namespace eloi
