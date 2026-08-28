#include "morlock/chess.hpp"

#include "morlock/opening_data.hpp"

#include <algorithm>

namespace morlock {
namespace {

Move decoded_move(std::uint16_t encoded) {
  Move move;
  move.from = encoded & 63;
  move.to = (encoded >> 6) & 63;
  move.promotion = static_cast<Piece>((encoded >> 12) & 7);
  return move;
}

std::string_view family_name(std::uint8_t family) {
  if (family == 1) return "Italian Game";
  if (family == 2) return "Nimzo-Indian Defense";
  return "General repertoire";
}

}  // namespace

std::optional<BookMove> opening_move(const EngineConfig& config,
                                     const Board& board) {
  if (!config.own_book || board.history.size() >= 32) return std::nullopt;
  const auto node = std::ranges::lower_bound(
      opening_data::nodes, board.key, {}, &opening_data::Node::key);
  if (node == opening_data::nodes.end() || node->key != board.key)
    return std::nullopt;

  const auto legal = board.legal_moves();
  const opening_data::Edge* best = nullptr;
  Move best_move;
  for (std::size_t index = node->first;
       index < static_cast<std::size_t>(node->first + node->count); ++index) {
    const auto* entry = &opening_data::edges[index];
    const bool signature =
        (entry->family == 1 && board.turn == Color::white) ||
        (entry->family == 2 && board.turn == Color::black);
    const bool best_signature = best &&
        ((best->family == 1 && board.turn == Color::white) ||
         (best->family == 2 && board.turn == Color::black));
    const Move wanted = decoded_move(entry->move);
    const auto found = std::ranges::find_if(legal, [&](const Move& move) {
      return move.same_coordinates(wanted);
    });
    if (found == legal.end()) continue;
    if (!best || (signature != best_signature ? signature
                                               : entry->weight > best->weight)) {
      best = entry;
      best_move = *found;
    }
  }
  if (!best) return std::nullopt;
  return BookMove{best_move, family_name(best->family)};
}

std::size_t opening_book_size() { return opening_data::edges.size(); }
std::size_t opening_book_node_count() { return opening_data::nodes.size(); }

}  // namespace morlock
