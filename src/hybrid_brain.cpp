#include "eloi/brain.hpp"

#include <stdexcept>

namespace eloi {

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

  BrainResponse response;
  response.requested = BrainIdentity::hybrid;
  response.selected = BrainIdentity::hybrid;
  response.status = BrainStatus::unavailable;
  response.detail =
      "Two-brain arbitration is locked until the audited Caissa backend, "
      "WDL calibration, and bounded verification search are implemented";
  if (info) info(response);
  return response;
}

const HybridBudget& HybridBrain::budget() const noexcept {
  return budget_;
}

}  // namespace eloi
