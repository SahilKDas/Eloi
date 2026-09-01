#include "eloi/chess.hpp"

#include "eloi/nnue_weights.hpp"

#include <algorithm>
#include <cstdlib>

#if defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))
#include <immintrin.h>
#define ELOI_GNU_X86_DISPATCH 1
#else
#define ELOI_GNU_X86_DISPATCH 0
#endif

namespace eloi {
namespace {

constexpr int quantization = 8;

int perspective_index(Color side) { return side == Color::white ? 0 : 1; }

int oriented_square(int square, Color perspective) {
  return perspective == Color::white ? square : square ^ 56;
}

int king_bucket_square(int king, Color perspective) {
  if (king < 0) return 0;
  const int square = oriented_square(king, perspective);
  return (file_of(square) >= 4 ? 1 : 0) + 2 * (rank_of(square) / 2);
}

int king_bucket(const Position& position, Color perspective) {
  return king_bucket_square(position.king_square(perspective), perspective);
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

void add_feature_scalar(NnueAccumulator& accumulator, int feature, int sign) {
  if (feature < 0) return;
  const std::size_t offset = static_cast<std::size_t>(feature) * nnue_hidden_size;
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden)
    accumulator[hidden] += sign * nnue_weights::input[offset + hidden];
}

#if ELOI_GNU_X86_DISPATCH
__attribute__((target("avx2")))
void add_feature_avx2(NnueAccumulator& accumulator, int feature, int sign) {
  if (feature < 0) return;
  const std::size_t offset =
      static_cast<std::size_t>(feature) * nnue_hidden_size;
  const auto* weights = nnue_weights::input.data() + offset;
  const __m256i zero = _mm256_setzero_si256();
  for (int hidden = 0; hidden < nnue_hidden_size; hidden += 16) {
    const __m128i bytes = _mm_loadu_si128(
        reinterpret_cast<const __m128i*>(weights + hidden));
    __m256i low = _mm256_cvtepi8_epi32(bytes);
    __m256i high = _mm256_cvtepi8_epi32(_mm_srli_si128(bytes, 8));
    if (sign < 0) {
      low = _mm256_sub_epi32(zero, low);
      high = _mm256_sub_epi32(zero, high);
    }
    __m256i accumulator_low = _mm256_loadu_si256(
        reinterpret_cast<const __m256i*>(accumulator.data() + hidden));
    __m256i accumulator_high = _mm256_loadu_si256(
        reinterpret_cast<const __m256i*>(accumulator.data() + hidden + 8));
    _mm256_storeu_si256(
        reinterpret_cast<__m256i*>(accumulator.data() + hidden),
        _mm256_add_epi32(accumulator_low, low));
    _mm256_storeu_si256(
        reinterpret_cast<__m256i*>(accumulator.data() + hidden + 8),
        _mm256_add_epi32(accumulator_high, high));
  }
}

bool runtime_has_avx2() {
  static const bool available = [] {
    __builtin_cpu_init();
    return __builtin_cpu_supports("avx2");
  }();
  return available;
}
#endif

void add_feature(NnueAccumulator& accumulator, int feature, int sign) {
#if ELOI_GNU_X86_DISPATCH
  if (runtime_has_avx2()) {
    add_feature_avx2(accumulator, feature, sign);
    return;
  }
#endif
  add_feature_scalar(accumulator, feature, sign);
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

void nnue_update_changed(NnueState& state, const Position& before,
                         const Position& after,
                         const std::array<std::uint8_t, 4>& squares,
                         std::uint8_t count) {
  for (Color perspective : {Color::white, Color::black}) {
    const int index = perspective_index(perspective);
    const int before_bucket = king_bucket(before, perspective);
    const int after_bucket = king_bucket(after, perspective);
    if (before_bucket != after_bucket) {
      state.perspective[index] = refresh_perspective(after, perspective);
      continue;
    }
    for (std::uint8_t changed = 0; changed < count; ++changed) {
      const int square = squares[changed];
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

void nnue_update_delta(
    NnueState& state, const std::array<std::int8_t, 2>& before_kings,
    const Position& after, const std::array<std::uint8_t, 4>& squares,
    const std::array<std::int8_t, 4>& before_cells, std::uint8_t count) {
  for (Color perspective : {Color::white, Color::black}) {
    const int index = perspective_index(perspective);
    const int before_bucket =
        king_bucket_square(before_kings[index], perspective);
    const int after_bucket = king_bucket(after, perspective);
    if (before_bucket != after_bucket) {
      state.perspective[index] = refresh_perspective(after, perspective);
      continue;
    }
    for (std::uint8_t changed = 0; changed < count; ++changed) {
      const int square = squares[changed];
      const std::int8_t before_cell = before_cells[changed];
      const std::int8_t after_cell = after.cells[square];
      if (before_cell == after_cell) continue;
      add_feature(state.perspective[index],
                  feature_of(before_cell, square, before_bucket, perspective),
                  -1);
      add_feature(state.perspective[index],
                  feature_of(after_cell, square, after_bucket, perspective),
                  1);
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
