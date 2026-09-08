#include "eloi/brain.hpp"

#include <algorithm>

namespace eloi {

bool BrainResponse::has_legal_move(const Board& board) const {
  if (search.pv.empty()) return false;
  const auto legal = board.legal_moves();
  return std::ranges::any_of(legal, [&](const Move& move) {
    return move.same_coordinates(search.pv.front()) &&
           move.promotion == search.pv.front().promotion;
  });
}

EloiBrain::EloiBrain(EngineConfig config, std::atomic_bool& stopped)
    : config_(std::move(config)), stopped_(stopped) {}

BrainIdentity EloiBrain::identity() const noexcept {
  return BrainIdentity::eloi_e2;
}

bool EloiBrain::available() const noexcept {
  return true;
}

BrainResponse EloiBrain::search(Board board, SearchLimits limits,
                                const BrainInfoCallback& info) {
  Searcher searcher(config_, stopped_);
  const Board root = board;
  BrainResponse response;
  response.requested = BrainIdentity::eloi_e2;
  response.selected = BrainIdentity::eloi_e2;
  response.search = searcher.iterative(
      std::move(board), limits,
      [&](const SearchResult& result) {
        if (!info) return;
        BrainResponse update;
        update.requested = BrainIdentity::eloi_e2;
        update.selected = BrainIdentity::eloi_e2;
        update.status = stopped_ ? BrainStatus::stopped : BrainStatus::complete;
        update.search = result;
        info(update);
      });
  response.status = stopped_ ? BrainStatus::stopped : BrainStatus::complete;
  if (!response.search.pv.empty()) {
    response.lines.push_back(
        {response.search.pv, response.search.score_cp, response.search.mate});
  }
  for (const RootMoveDiagnostic& root : response.search.root_moves) {
    if (!root.score_cp || root.pv.empty()) continue;
    if (!response.lines.empty() &&
        root.pv.front().same_coordinates(response.lines.front().pv.front()))
      continue;
    response.lines.push_back({root.pv, *root.score_cp, 0});
  }
  if (!response.search.pv.empty() && !response.has_legal_move(root)) {
    response.status = BrainStatus::invalid_move;
    response.detail = "E2 returned a move outside Eloi's authoritative legal list";
  }
  return response;
}

}  // namespace eloi
