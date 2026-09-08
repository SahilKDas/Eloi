#include "eloi/wdl_calibration.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace eloi {

double expected_score_from_cp(int centipawns, double pawn_scale) {
  if (!std::isfinite(pawn_scale) || pawn_scale <= 0.0)
    throw std::invalid_argument("WDL pawn scale must be positive and finite");
  return 1.0 /
         (1.0 + std::pow(10.0, -static_cast<double>(centipawns) /
                                   pawn_scale));
}

int cp_from_expected_score(double expectation, double pawn_scale) {
  if (!std::isfinite(pawn_scale) || pawn_scale <= 0.0)
    throw std::invalid_argument("WDL pawn scale must be positive and finite");
  const double bounded = std::clamp(expectation, 0.000001, 0.999999);
  return static_cast<int>(std::lround(
      pawn_scale * std::log10(bounded / (1.0 - bounded))));
}

}  // namespace eloi
