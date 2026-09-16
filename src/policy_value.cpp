#include "eloi/policy_value.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>

namespace eloi {
namespace {
constexpr std::array<char, 4> magic_v1{'E', 'P', 'V', '1'};
constexpr std::array<char, 4> magic_v2{'E', 'P', 'V', '2'};

int oriented(int square, Color side) {
  return side == Color::white ? square : square ^ 56;
}

int piece_plane(Piece piece) {
  switch (piece) {
    case Piece::pawn: return 0;
    case Piece::knight: return 1;
    case Piece::bishop: return 2;
    case Piece::rook: return 3;
    case Piece::queen: return 4;
    case Piece::king: return 5;
    default: return -1;
  }
}

int promotion_plane(Piece piece) {
  switch (piece) {
    case Piece::knight: return 1;
    case Piece::bishop: return 2;
    case Piece::rook: return 3;
    case Piece::queen: return 4;
    default: return 0;
  }
}

std::size_t move_index(const Move& move, Color side) {
  const std::size_t source = static_cast<std::size_t>(oriented(move.from, side));
  const std::size_t target = static_cast<std::size_t>(oriented(move.to, side));
  const std::size_t promotion = static_cast<std::size_t>(promotion_plane(move.promotion));
  return (source * 64 + target) * PolicyValueNetwork::promotion_count + promotion;
}

template <typename Range>
bool read_floats(std::ifstream& stream, Range& values) {
  stream.read(reinterpret_cast<char*>(values.data()),
              static_cast<std::streamsize>(values.size() * sizeof(float)));
  return stream.good() && std::ranges::all_of(
      values, [](float value) { return std::isfinite(value); });
}

std::array<float, PolicyValueNetwork::input_count> encode(const Board& board) {
  std::array<float, PolicyValueNetwork::input_count> result{};
  for (int square = 0; square < 64; ++square) {
    const auto color = board.position.color_at(square);
    if (!color) continue;
    const int piece = piece_plane(board.position.piece_at(square));
    if (piece < 0) continue;
    const int relative = *color == board.turn ? 0 : 6;
    result[(relative + piece) * 64 + oriented(square, board.turn)] = 1.0f;
  }
  result[768] = 1.0f;
  const bool white = board.turn == Color::white;
  const std::array<std::uint8_t, 4> rights = white
      ? std::array<std::uint8_t, 4>{white_king, white_queen,
                                    black_king, black_queen}
      : std::array<std::uint8_t, 4>{black_king, black_queen,
                                    white_king, white_queen};
  for (std::size_t index = 0; index < rights.size(); ++index)
    result[769 + index] = (board.position.castling & rights[index]) != 0;
  if (board.position.en_passant >= 0)
    result[773 + file_of(board.position.en_passant)] = 1.0f;
  return result;
}

template <std::size_t Size>
std::array<float, Size> softmax(std::array<float, Size> logits) {
  const float peak = *std::ranges::max_element(logits);
  float total = 0.0f;
  for (float& value : logits) {
    value = std::exp(value - peak);
    total += value;
  }
  for (float& value : logits) value /= total;
  return logits;
}
}  // namespace

bool PolicyValueNetwork::load(const std::filesystem::path& path,
                              std::string* error) {
  available_ = false;
  interaction_policy_ = false;
  policy_move_.clear();
  auto fail = [&](std::string message) {
    if (error) *error = std::move(message);
    return false;
  };
  std::ifstream stream(path, std::ios::binary);
  if (!stream) return fail("policy/value artifact is absent");
  std::array<char, 4> found_magic{};
  std::array<std::uint32_t, 4> dimensions{};
  stream.read(found_magic.data(), found_magic.size());
  stream.read(reinterpret_cast<char*>(dimensions.data()), sizeof(dimensions));
  const bool v1 = found_magic == magic_v1;
  const bool v2 = found_magic == magic_v2;
  if (!stream || (!v1 && !v2))
    return fail("policy/value artifact has an invalid header");
  const auto expected = v1
      ? std::array<std::uint32_t, 4>{input_count, hidden_count,
                                     promotion_count, piece_count}
      : std::array<std::uint32_t, 4>{input_count, hidden_count,
                                     promotion_count, move_count};
  if (dimensions != expected)
    return fail("policy/value artifact dimensions do not match Eloi");
  input_.resize(input_count * hidden_count);
  if (!read_floats(stream, input_) || !read_floats(stream, bias_) ||
      !read_floats(stream, value_) || !read_floats(stream, value_bias_))
    return fail("policy/value artifact is truncated or non-finite");
  if (v1) {
    if (!read_floats(stream, policy_from_) || !read_floats(stream, policy_to_) ||
        !read_floats(stream, policy_promotion_) ||
        !read_floats(stream, policy_piece_))
      return fail("policy/value artifact is truncated or non-finite");
  } else {
    policy_move_.resize(static_cast<std::size_t>(move_count) * hidden_count);
    if (!read_floats(stream, policy_move_))
      return fail("policy/value artifact is truncated or non-finite");
    interaction_policy_ = true;
  }
  if (stream.peek() != std::ifstream::traits_type::eof())
    return fail("policy/value artifact has trailing bytes");
  available_ = true;
  if (error) error->clear();
  return true;
}
PolicyValuePrediction PolicyValueNetwork::predict(
    const Board& board, const MoveList& candidates) const {
  PolicyValuePrediction result;
  if (!available_ || candidates.empty()) return result;
  const auto inputs = encode(board);
  std::array<float, hidden_count> hidden{};
  for (std::size_t unit = 0; unit < hidden.size(); ++unit) {
    float sum = bias_[unit];
    for (std::size_t feature = 0; feature < inputs.size(); ++feature)
      if (inputs[feature]) sum += input_[feature * hidden_count + unit];
    hidden[unit] = std::max(0.0f, sum);
  }
  std::array<float, 3> value_logits = value_bias_;
  for (std::size_t unit = 0; unit < hidden.size(); ++unit)
    for (std::size_t outcome = 0; outcome < value_logits.size(); ++outcome)
      value_logits[outcome] += hidden[unit] * value_[unit * 3 + outcome];
  result.value_wdl = softmax(value_logits);

  std::vector<float> logits;
  logits.reserve(candidates.size());
  for (const Move& move : candidates) {
    float score = 0.0f;
    if (interaction_policy_) {
      const std::size_t index = move_index(move, board.turn);
      for (std::size_t unit = 0; unit < hidden.size(); ++unit)
        score += hidden[unit] * policy_move_[index * hidden_count + unit];
    } else {
      const int source = oriented(move.from, board.turn);
      const int target = oriented(move.to, board.turn);
      const int promotion = promotion_plane(move.promotion);
      const int piece = piece_plane(move.piece);
      for (std::size_t unit = 0; unit < hidden.size(); ++unit)
        score += hidden[unit] * (
            policy_from_[source * hidden_count + unit] +
            policy_to_[target * hidden_count + unit] +
            policy_promotion_[promotion * hidden_count + unit] +
            policy_piece_[piece * hidden_count + unit]);
    }
    logits.push_back(score);
  }
  const float peak = *std::ranges::max_element(logits);
  float total = 0.0f;
  for (float& value : logits) {
    value = std::exp(value - peak);
    total += value;
  }
  for (std::size_t index = 0; index < candidates.size(); ++index)
    result.policy.push_back({candidates[index], logits[index] / total});
  return result;
}

}  // namespace eloi
