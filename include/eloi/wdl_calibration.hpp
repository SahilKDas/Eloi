#pragma once

#include <string_view>

namespace eloi {

struct WdlCalibrationProfile {
  std::string_view identity;
  double eloi_pawn_scale;
  double caissa_pawn_scale;
  double report_pawn_scale;
};

// These values preserve the behavior used by the retained hybrid gauntlets.
// Change them only after a game-separated calibration/validation report has
// been reviewed and the resulting engine has been requalified.
inline constexpr WdlCalibrationProfile hybrid_wdl_v1{
    "hybrid-wdl-v1-uncalibrated", 400.0, 360.0, 400.0};

double expected_score_from_cp(int centipawns, double pawn_scale);
int cp_from_expected_score(double expectation, double pawn_scale);

}  // namespace eloi
