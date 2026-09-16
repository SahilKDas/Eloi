#pragma once

#include "eloi/chess.hpp"

#include <array>
#include <filesystem>
#include <string>
#include <utility>
#include <vector>

namespace eloi {

struct PolicyValuePrediction {
  std::array<float, 3> value_wdl{};
  std::vector<std::pair<Move, float>> policy;
};

class PolicyValueNetwork {
 public:
  static constexpr std::uint32_t input_count = 781;
  static constexpr std::uint32_t hidden_count = 64;
  static constexpr std::uint32_t promotion_count = 5;
  static constexpr std::uint32_t piece_count = 6;
  static constexpr std::uint32_t move_count = 64 * 64 * promotion_count;

  bool load(const std::filesystem::path& path, std::string* error = nullptr);
  bool available() const noexcept { return available_; }
  bool interaction_policy() const noexcept { return interaction_policy_; }
  PolicyValuePrediction predict(const Board& board,
                                const MoveList& candidates) const;

 private:
  bool available_{false};
  bool interaction_policy_{false};
  std::vector<float> input_;
  std::array<float, hidden_count> bias_{};
  std::array<float, hidden_count * 3> value_{};
  std::array<float, 3> value_bias_{};
  std::array<float, 64 * hidden_count> policy_from_{};
  std::array<float, 64 * hidden_count> policy_to_{};
  std::array<float, promotion_count * hidden_count> policy_promotion_{};
  std::array<float, piece_count * hidden_count> policy_piece_{};
  std::vector<float> policy_move_;
};

}  // namespace eloi
