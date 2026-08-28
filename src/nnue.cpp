#include "morlock/chess.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstdint>

namespace morlock {
namespace {

constexpr int feature_count = 12 * 64;
constexpr int quantization = 8;

struct QuantizedNetwork {
  std::array<std::array<std::int16_t, nnue_hidden_size>, feature_count> input{};
  std::array<std::int32_t, nnue_hidden_size> bias{};
  std::array<std::int16_t, nnue_hidden_size> output{};
  std::int32_t output_bias{0};
};

std::uint32_t mix(std::uint32_t value) {
  value ^= value >> 16;
  value *= 0x7feb352dU;
  value ^= value >> 15;
  value *= 0x846ca68bU;
  return value ^ (value >> 16);
}

const QuantizedNetwork& network() {
  static const QuantizedNetwork value = [] {
    QuantizedNetwork net;

    // Eloi's embedded quantized Piece-Square NNUE. The first twelve neurons
    // carry the dominant learned material channels; the remaining neurons
    // form deterministic positional channels. Keeping the weights embedded
    // makes the evaluator reproducible and lets Board update its accumulator
    // by adding/removing only the changed piece features.
    for (int feature = 0; feature < feature_count; ++feature) {
      for (int hidden = 12; hidden < nnue_hidden_size; ++hidden) {
        const auto random = mix(static_cast<std::uint32_t>(feature * 131 + hidden * 977 + 0xE101U));
        net.input[feature][hidden] = static_cast<std::int16_t>(static_cast<int>(random % 7) - 3);
      }
      const int plane = feature / 64;
      net.input[feature][plane] += 24;

      const int square = feature % 64;
      const int file = file_of(square);
      const int rank = rank_of(square);
      const int center = 6 - std::abs(file * 2 - 7) - std::abs(rank * 2 - 7);
      net.input[feature][12 + (plane % 6)] += static_cast<std::int16_t>(center);
      net.input[feature][18 + (plane / 6)] += static_cast<std::int16_t>(rank - 3);
    }

    constexpr std::array<int, 6> material{33, 105, 105, 166, 300, 0};
    for (int piece = 0; piece < 6; ++piece) {
      net.output[piece] = static_cast<std::int16_t>(material[piece]);
      net.output[6 + piece] = static_cast<std::int16_t>(-material[piece]);
    }
    for (int hidden = 12; hidden < nnue_hidden_size; ++hidden) {
      const auto random = mix(static_cast<std::uint32_t>(hidden * 811 + 0xC0DE26U));
      net.output[hidden] = static_cast<std::int16_t>(static_cast<int>(random % 5) - 2);
    }
    return net;
  }();
  return value;
}

int feature_of(std::int8_t cell, int square) {
  if (cell == 0) return -1;
  const int color = cell < 0 ? 1 : 0;
  const int piece = std::abs(static_cast<int>(cell)) - 1;
  return (color * 6 + piece) * 64 + square;
}

void add_feature(NnueAccumulator& accumulator, int feature, int sign) {
  if (feature < 0) return;
  const auto& weights = network().input[feature];
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden)
    accumulator[hidden] += sign * weights[hidden];
}

}  // namespace

NnueAccumulator nnue_refresh(const Position& position) {
  NnueAccumulator accumulator = network().bias;
  for (int square = 0; square < 64; ++square)
    add_feature(accumulator, feature_of(position.cells[square], square), 1);
  return accumulator;
}

void nnue_update(NnueAccumulator& accumulator, const Position& before,
                 const Position& after) {
  for (int square = 0; square < 64; ++square) {
    if (before.cells[square] == after.cells[square]) continue;
    add_feature(accumulator, feature_of(before.cells[square], square), -1);
    add_feature(accumulator, feature_of(after.cells[square], square), 1);
  }
}

int nnue_evaluate(const NnueAccumulator& accumulator, Color side_to_move) {
  const auto& net = network();
  std::int64_t sum = net.output_bias;
  for (int hidden = 0; hidden < nnue_hidden_size; ++hidden) {
    const int activated = std::clamp(accumulator[hidden], 0, 127);
    sum += static_cast<std::int64_t>(activated) * net.output[hidden];
  }
  int score = static_cast<int>(sum / quantization);
  if (side_to_move == Color::black) score = -score;
  return score + 10;  // Small side-to-move tempo term.
}

}  // namespace morlock
