#pragma once

#include <string_view>

namespace eloi {

struct WdlCalibrationProfile {
  std::string_view identity;
  double eloi_pawn_scale;
  double caissa_pawn_scale;
  double report_pawn_scale;
};

// Eloi's scale remains supported by its game-separated calibration. Caissa's
// scale was reset to the v1.25 network's native expected-score mapping after
// replacing the v1.26 SCReLU net; it is provisional until fresh, disjoint
// outcome calibration is complete. The public report scale remains 400 cp.
inline constexpr WdlCalibrationProfile hybrid_wdl_v2{
    "hybrid-wdl-v3-v126-code-v125-network-provisional",
    1300.0, 400.0, 400.0};

double expected_score_from_cp(int centipawns, double pawn_scale);
int cp_from_expected_score(double expectation, double pawn_scale);

}  // namespace eloi
