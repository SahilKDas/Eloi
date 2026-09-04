#include "eloi/brain.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <optional>
#include <stdexcept>
#include <vector>

namespace eloi {

namespace {

// Development-only mappings. These are deliberately separate so calibration
// can replace either scale without ever comparing raw engine centipawns.
constexpr double eloi_wdl_pawn_scale = 400.0;
constexpr double caissa_wdl_pawn_scale = 360.0;
constexpr double hybrid_report_pawn_scale = 400.0;

SearchLimits slice_limits(
    const SearchLimits& source, int percent,
    std::chrono::steady_clock::time_point campaign_started) {
  SearchLimits result = source;
  result.collect_diagnostics = true;
  if (source.nodes > 0) {
    result.nodes = std::max<std::uint64_t>(
        1, source.nodes * static_cast<std::uint64_t>(percent) / 100);
  }
  if (source.deadline) {
    const auto now = std::chrono::steady_clock::now();
    const auto total = std::max(source.deadline.value() - campaign_started,
                                std::chrono::steady_clock::duration::zero());
    result.deadline = std::min(source.deadline.value(),
                               now + total * percent / 100);
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

int normalized_score(double expectation) {
  const double bounded = std::clamp(expectation, 0.000001, 0.999999);
  return static_cast<int>(std::lround(
      hybrid_report_pawn_scale * std::log10(bounded / (1.0 - bounded))));
}

std::optional<Move> first_legal(const Board& board,
                                const BrainResponse& response) {
  if (!response.has_legal_move(board)) return std::nullopt;
  return response.search.pv.front();
}

const BrainLine* find_line(const BrainResponse& response, const Move& move) {
  const auto found = std::ranges::find_if(
      response.lines, [&](const BrainLine& line) {
        return !line.pv.empty() &&
               line.pv.front().same_coordinates(move) &&
               line.pv.front().promotion == move.promotion;
      });
  return found == response.lines.end() ? nullptr : &*found;
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
  if (board.legal_moves().empty()) {
    BrainResponse response;
    response.requested = response.selected = BrainIdentity::hybrid;
    response.status = BrainStatus::complete;
    response.detail = board.position.in_check(board.turn)
        ? "terminal checkmate; no move"
        : "terminal draw; no move";
    if (info) info(response);
    return response;
  }

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
  SearchLimits shared_limits = limits;
  if (!shared_limits.deadline && shared_limits.remaining_ms > 0) {
    const TimeBudget clock = plan_time_budget(board, shared_limits);
    shared_limits.deadline = started +
        std::chrono::milliseconds(std::max(1, clock.hard_ms));
    shared_limits.remaining_ms = 0;
  }
  BrainResponse caissa = caissa_.search(
      board, slice_limits(shared_limits, budget_.caissa_percent, started));
  if (caissa.status == BrainStatus::stopped) {
    caissa.requested = BrainIdentity::hybrid;
    caissa.used_fallback = true;
    caissa.search.elapsed =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started);
    caissa.detail = "hybrid stopped during the Caissa slice";
    if (info) info(caissa);
    return caissa;
  }
  BrainResponse eloi = eloi_.search(
      board, slice_limits(shared_limits, budget_.eloi_percent, started));
  if (eloi.status == BrainStatus::stopped) {
    eloi.requested = BrainIdentity::hybrid;
    eloi.used_fallback = true;
    eloi.search.nodes += caissa.search.nodes;
    eloi.search.elapsed =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started);
    eloi.detail = "hybrid stopped during the E2 slice";
    if (info) info(eloi);
    return eloi;
  }
  const auto caissa_move = first_legal(board, caissa);
  const auto eloi_move = first_legal(board, eloi);

  if (!caissa_move || !eloi_move) {
    BrainResponse response = caissa_move ? std::move(caissa) : std::move(eloi);
    response.requested = BrainIdentity::hybrid;
    response.used_fallback = true;
    response.detail = caissa_move
        ? "E2 failed; hybrid used Eloi-legal Caissa fallback"
        : "Caissa failed; hybrid used Eloi E2 fallback";
    if (!caissa_move && !eloi_move) {
      response.status = BrainStatus::failed;
      response.selected = BrainIdentity::hybrid;
      response.detail = "both hybrid brains failed to return a legal move";
    }
    response.search.nodes = caissa.search.nodes + eloi.search.nodes;
    response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started);
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

  // Each candidate is already scored by the brain that proposed it. The
  // verification slice therefore pays only for the missing cross-check, not
  // for re-searching both candidates with both brains.
  const int verification_share = std::max(
      1, budget_.verification_percent / static_cast<int>(candidates.size()));
  std::vector<VerifiedCandidate> verified;
  for (const Move& candidate : candidates) {
    if (shared_limits.deadline &&
        std::chrono::steady_clock::now() >= *shared_limits.deadline)
      break;
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

    const BrainLine* eloi_line = find_line(eloi, candidate);
    const BrainLine* caissa_line = find_line(caissa, candidate);
    std::optional<BrainLine> eloi_cross;
    std::optional<BrainLine> caissa_cross;

    const auto parent_line = [&](const BrainResponse& child_response) {
      BrainLine line;
      line.score_cp = -child_response.search.score_cp;
      line.mate = -child_response.search.mate;
      line.pv.push_back(candidate);
      line.pv.insert(line.pv.end(), child_response.search.pv.begin(),
                     child_response.search.pv.end());
      return line;
    };

    if (!eloi_line) {
      if (shared_limits.deadline &&
          std::chrono::steady_clock::now() >= *shared_limits.deadline)
        break;
      const BrainResponse check = eloi_.search(
          child, slice_limits(shared_limits, verification_share, started));
      current.nodes += check.search.nodes;
      if (!first_legal(child, check)) continue;
      eloi_cross = parent_line(check);
      eloi_line = &*eloi_cross;
    }
    if (!caissa_line) {
      if (shared_limits.deadline &&
          std::chrono::steady_clock::now() >= *shared_limits.deadline)
        break;
      const BrainResponse check = caissa_.search(
          child, slice_limits(shared_limits, verification_share, started));
      current.nodes += check.search.nodes;
      if (!first_legal(child, check)) continue;
      caissa_cross = parent_line(check);
      caissa_line = &*caissa_cross;
    }

    current.eloi_score_cp = eloi_line->score_cp;
    current.caissa_score_cp = caissa_line->score_cp;
    const BrainLine* pessimistic_line = nullptr;
    if (eloi_line->mate < 0 || caissa_line->mate < 0) {
      current.pessimistic = 0.0;
      if (eloi_line->mate < 0 && caissa_line->mate < 0) {
        // A mate loss closer to zero happens sooner and is therefore the
        // more pessimistic of two losing reports.
        current.mate = std::max(eloi_line->mate, caissa_line->mate);
        pessimistic_line = current.mate == eloi_line->mate
                               ? eloi_line
                               : caissa_line;
      } else if (eloi_line->mate < 0) {
        current.mate = eloi_line->mate;
        pessimistic_line = eloi_line;
      } else {
        current.mate = caissa_line->mate;
        pessimistic_line = caissa_line;
      }
    } else if (eloi_line->mate > 0 && caissa_line->mate > 0) {
      current.pessimistic = 1.0;
      current.mate = std::min(eloi_line->mate, caissa_line->mate);
      pessimistic_line = current.mate == eloi_line->mate
                             ? eloi_line
                             : caissa_line;
    } else {
      // The mappings are intentionally independent; raw centipawns from the
      // two networks are never compared directly.
      const double eloi_wdl =
          expected_score(current.eloi_score_cp, eloi_wdl_pawn_scale);
      const double caissa_wdl =
          expected_score(current.caissa_score_cp, caissa_wdl_pawn_scale);
      current.pessimistic = std::min(eloi_wdl, caissa_wdl);
      pessimistic_line = eloi_wdl <= caissa_wdl ? eloi_line : caissa_line;
    }
    current.continuation.assign(pessimistic_line->pv.begin() + 1,
                                pessimistic_line->pv.end());
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
    response.search.nodes = caissa.search.nodes + eloi.search.nodes;
    response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started);
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
  response.search.score_cp = best->mate
      ? best->eloi_score_cp
      : normalized_score(best->pessimistic);
  response.search.mate = best->mate;
  response.search.depth = std::min(caissa.search.depth, eloi.search.depth);
  response.search.nodes = caissa.search.nodes + eloi.search.nodes;
  for (const auto& candidate : verified)
    response.search.nodes += candidate.nodes;
  response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  response.confidence = best->pessimistic;
  response.lines.push_back(
      {response.search.pv, response.search.score_cp, response.search.mate});
  for (const auto& candidate : verified) {
    if (candidate.move.same_coordinates(best->move) &&
        candidate.move.promotion == best->move.promotion)
      continue;
    BrainLine alternative;
    alternative.pv.push_back(candidate.move);
    alternative.pv.insert(alternative.pv.end(),
                          candidate.continuation.begin(),
                          candidate.continuation.end());
    alternative.score_cp = candidate.mate
        ? candidate.eloi_score_cp
        : normalized_score(candidate.pessimistic);
    alternative.mate = candidate.mate;
    response.lines.push_back(std::move(alternative));
  }
  response.detail =
      "hybrid disagreement resolved by pessimistic cross-verification";
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
