#include "eloi/brain.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <optional>
#include <stdexcept>
#include <vector>

namespace eloi {

namespace {

SearchLimits slice_limits(const SearchLimits& source, int percent) {
  SearchLimits result = source;
  result.collect_diagnostics = true;
  if (source.nodes > 0) {
    result.nodes = std::max<std::uint64_t>(
        1, source.nodes * static_cast<std::uint64_t>(percent) / 100);
  }
  if (source.deadline) {
    const auto now = std::chrono::steady_clock::now();
    const auto remaining = std::max(source.deadline.value() - now,
                                    std::chrono::steady_clock::duration::zero());
    result.deadline = now + remaining * percent / 100;
    result.remaining_ms = 0;
  } else if (source.remaining_ms > 0) {
    result.remaining_ms = std::max(1, source.remaining_ms * percent / 100);
    result.increment_ms = source.increment_ms * percent / 100;
  }
  return result;
}

double expected_score(int centipawns, double pawn_scale) {
  return 1.0 / (1.0 + std::pow(10.0, -centipawns / pawn_scale));
}

std::optional<Move> first_legal(const Board& board,
                                const BrainResponse& response) {
  if (!response.has_legal_move(board)) return std::nullopt;
  return response.search.pv.front();
}

struct VerifiedCandidate {
  Move move{};
  double pessimistic{0.0};
  int eloi_score_cp{0};
  int caissa_score_cp{0};
  int mate{0};
  std::uint64_t nodes{0};
  std::vector<Move> continuation;
};

}  // namespace

bool HybridBudget::valid() const noexcept {
  return caissa_percent >= 0 && eloi_percent >= 0 &&
         verification_percent >= 0 &&
         caissa_percent + eloi_percent + verification_percent == 100;
}

HybridBrain::HybridBrain(Brain& eloi, Brain& caissa, HybridBudget budget)
    : eloi_(eloi), caissa_(caissa), budget_(budget) {
  if (eloi_.identity() != BrainIdentity::eloi_e2)
    throw std::invalid_argument("hybrid Eloi slot must contain the E2 brain");
  if (caissa_.identity() != BrainIdentity::caissa_1_26)
    throw std::invalid_argument("hybrid Caissa slot must contain Caissa 1.26");
  if (!budget_.valid())
    throw std::invalid_argument("hybrid budget percentages must total 100");
}

BrainIdentity HybridBrain::identity() const noexcept {
  return BrainIdentity::hybrid;
}

bool HybridBrain::available() const noexcept {
  return eloi_.available();
}

BrainResponse HybridBrain::search(Board board, SearchLimits limits,
                                  const BrainInfoCallback& info) {
  const bool unsupported_variant = board.horde || board.chess960;
  const bool donor_unavailable = !caissa_.available();

  // This is a deliberate fail-closed checkpoint. Do not spend only Eloi's
  // nominal 20% slice when it is the sole functioning brain.
  if (unsupported_variant || donor_unavailable) {
    BrainResponse response = eloi_.search(std::move(board), limits, info);
    response.requested = BrainIdentity::hybrid;
    response.used_fallback = true;
    if (unsupported_variant) {
      response.detail =
          "Caissa bypassed: Chess960 and Horde remain Eloi-only until parity";
    } else {
      response.detail =
          "Caissa unavailable: hybrid used the complete E2 budget";
    }
    return response;
  }

  const auto started = std::chrono::steady_clock::now();
  BrainResponse caissa = caissa_.search(
      board, slice_limits(limits, budget_.caissa_percent));
  BrainResponse eloi = eloi_.search(
      board, slice_limits(limits, budget_.eloi_percent));
  const auto caissa_move = first_legal(board, caissa);
  const auto eloi_move = first_legal(board, eloi);

  if (!caissa_move || !eloi_move) {
    BrainResponse response = caissa_move ? std::move(caissa) : std::move(eloi);
    response.requested = BrainIdentity::hybrid;
    response.used_fallback = true;
    response.detail = caissa_move
        ? "E2 failed; hybrid used Eloi-verified Caissa fallback"
        : "Caissa failed; hybrid used Eloi E2 fallback";
    if (!caissa_move && !eloi_move) {
      response.status = BrainStatus::failed;
      response.selected = BrainIdentity::hybrid;
      response.detail = "both hybrid brains failed to return a legal move";
    }
    if (info) info(response);
    return response;
  }

  if (caissa_move->same_coordinates(*eloi_move) &&
      caissa_move->promotion == eloi_move->promotion) {
    BrainResponse response = std::move(caissa);
    response.requested = BrainIdentity::hybrid;
    response.selected = BrainIdentity::hybrid;
    response.search.nodes += eloi.search.nodes;
    response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started);
    response.confidence = 1.0;
    response.detail = "E2 and Caissa agreed; verification slice was not spent";
    if (info) info(response);
    return response;
  }

  std::vector<Move> candidates{*caissa_move};
  if (!eloi_move->same_coordinates(*caissa_move) ||
      eloi_move->promotion != caissa_move->promotion)
    candidates.push_back(*eloi_move);

  const int verification_share = std::max(
      1, budget_.verification_percent /
             static_cast<int>(2 * candidates.size()));
  std::vector<VerifiedCandidate> verified;
  for (const Move& candidate : candidates) {
    Board child = board;
    if (!child.push(candidate)) continue;

    VerifiedCandidate current;
    current.move = candidate;
    if (child.legal_moves().empty()) {
      const bool mate = child.position.in_check(child.turn);
      current.pessimistic = mate ? 1.0 : 0.5;
      current.mate = mate ? 1 : 0;
      verified.push_back(std::move(current));
      continue;
    }

    const BrainResponse eloi_check = eloi_.search(
        child, slice_limits(limits, verification_share));
    const BrainResponse caissa_check = caissa_.search(
        child, slice_limits(limits, verification_share));
    if (!first_legal(child, eloi_check) || !first_legal(child, caissa_check))
      continue;

    current.eloi_score_cp = -eloi_check.search.score_cp;
    current.caissa_score_cp = -caissa_check.search.score_cp;
    current.nodes = eloi_check.search.nodes + caissa_check.search.nodes;
    const bool eloi_forced_loss = eloi_check.search.mate > 0;
    const bool caissa_forced_loss = caissa_check.search.mate > 0;
    if (eloi_forced_loss || caissa_forced_loss) {
      current.pessimistic = 0.0;
      current.mate = -std::min(
          eloi_check.search.mate > 0 ? eloi_check.search.mate : INT_MAX,
          caissa_check.search.mate > 0 ? caissa_check.search.mate : INT_MAX);
    } else {
      // The mappings are intentionally independent; raw centipawns from the
      // two networks are never compared directly.
      const double eloi_wdl = expected_score(current.eloi_score_cp, 400.0);
      const double caissa_wdl = expected_score(current.caissa_score_cp, 360.0);
      current.pessimistic = std::min(eloi_wdl, caissa_wdl);
    }
    const BrainResponse& pessimistic_line =
        expected_score(current.eloi_score_cp, 400.0) <=
                expected_score(current.caissa_score_cp, 360.0)
            ? eloi_check
            : caissa_check;
    current.continuation = pessimistic_line.search.pv;
    verified.push_back(std::move(current));
  }

  BrainResponse response;
  response.requested = BrainIdentity::hybrid;
  response.selected = BrainIdentity::hybrid;
  if (verified.empty()) {
    response = std::move(eloi);
    response.requested = BrainIdentity::hybrid;
    response.used_fallback = true;
    response.detail = "disagreement verification failed; hybrid used E2";
    if (info) info(response);
    return response;
  }

  const auto best = std::ranges::max_element(
      verified, {}, &VerifiedCandidate::pessimistic);
  response.status = BrainStatus::complete;
  response.search.pv.push_back(best->move);
  response.search.pv.insert(response.search.pv.end(),
                            best->continuation.begin(),
                            best->continuation.end());
  response.search.score_cp = best->eloi_score_cp;
  response.search.mate = best->mate;
  response.search.nodes = caissa.search.nodes + eloi.search.nodes;
  for (const auto& candidate : verified)
    response.search.nodes += candidate.nodes;
  response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  response.confidence = best->pessimistic;
  response.lines.push_back(
      {response.search.pv, response.search.score_cp, response.search.mate});
  response.detail = "hybrid disagreement resolved by pessimistic dual verification";
  if (!response.has_legal_move(board)) {
    response.status = BrainStatus::invalid_move;
    response.detail = "arbiter selected a move outside Eloi's legal list";
  }
  if (info) info(response);
  return response;
}

const HybridBudget& HybridBrain::budget() const noexcept {
  return budget_;
}

}  // namespace eloi
