#pragma once

#include "Common.hpp"

#include <vector>

class SearchUtils {
 public:
  static void Init();
  static bool IsRepetition(const NodeInfo& node, const Game& game,
                           bool is_pv_node);
  static bool CanReachGameCycle(const NodeInfo& node);
  static void GetPvLine(const NodeInfo& root, std::uint32_t maximum,
                        std::vector<Move>& line);
};
