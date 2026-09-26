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

bool is_emergency_legal_fallback(const Board& board,
                                 const SearchResult& result) {
  if (result.depth != 0 || result.pv.empty()) return false;
  BrainResponse response;
  response.search = result;
  return response.has_legal_move(board);
}

EloiBrain::EloiBrain(EngineConfig config, std::atomic_bool& stopped,
                     SearchConcurrency concurrency,
                     Searcher::MovePrior move_prior)
    : config_(std::move(config)),
      stopped_(stopped),
      searcher_(std::make_unique<Searcher>(config_, stopped_, concurrency)) {
  searcher_->set_move_prior(std::move(move_prior));
}

BrainIdentity EloiBrain::identity() const noexcept {
  return BrainIdentity::eloi_e4_10;
}

bool EloiBrain::available() const noexcept {
  return true;
}

BrainResponse EloiBrain::search(Board board, SearchLimits limits,
                                const BrainInfoCallback& info) {
  const Board root = board;
  BrainResponse response;
  response.requested = BrainIdentity::eloi_e4_10;
  response.selected = BrainIdentity::eloi_e4_10;
  response.search = searcher_->iterative(
      std::move(board), limits,
      [&](const SearchResult& result) {
        if (!info) return;
        BrainResponse update;
        update.requested = BrainIdentity::eloi_e4_10;
        update.selected = BrainIdentity::eloi_e4_10;
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
    response.detail = "E4-10 returned a move outside Eloi's authoritative legal list";
  }
  return response;
}

}  // namespace eloi
