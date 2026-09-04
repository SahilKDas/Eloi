#include "SearchUtils.hpp"

#include "Game.hpp"
#include "Search.hpp"

#include <algorithm>

void SearchUtils::Init() {}

bool SearchUtils::CanReachGameCycle(const NodeInfo&) {
  // Conservative correctness choice: do not claim an upcoming cycle without
  // proving one. Ordinary repetition is still handled below.
  return false;
}

void SearchUtils::GetPvLine(const NodeInfo& root, std::uint32_t maximum,
                            std::vector<Move>& line) {
  line.clear();
  Position position = root.position;
  const auto count = std::min<std::uint32_t>(maximum, root.pvLength);
  for (std::uint32_t index = 0; index < count; ++index) {
    if (!root.pvLine[index].IsValid()) break;
    const Move move = position.MoveFromPacked(root.pvLine[index]);
    if (!move.IsValid() || !position.DoMove(move)) break;
    line.push_back(move);
  }
}

bool SearchUtils::IsRepetition(const NodeInfo& node, const Game& game,
                               bool is_pv_node) {
  const NodeInfo* cursor = &node;
  std::uint32_t matches = 0;
  for (std::uint32_t distance = 1; cursor->ply > 0; ++distance) {
    if (cursor->previousMove.IsValid() &&
        (cursor->previousMove.GetPiece() == Piece::Pawn ||
         cursor->previousMove.IsCapture())) {
      break;
    }
    --cursor;
    if ((distance & 1u) != 0) continue;
    if (cursor->position.GetHash() != node.position.GetHash() ||
        cursor->position != node.position) {
      continue;
    }
    if (!is_pv_node && cursor->ply > 0) return true;
    ++matches;
    if (matches >= 2) return true;
  }
  return matches + game.GetRepetitionCount(node.position) >= 2;
}
