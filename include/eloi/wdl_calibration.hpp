#pragma once

#include <string_view>

namespace eloi {

struct WdlCalibrationProfile {
  std::string_view identity;
  double eloi_pawn_scale;
  double caissa_pawn_scale;
  double report_pawn_scale;
};

// Provisional Caissa 1.25 screening profile. Twenty complete Standard games
// supplied the game-separated fit/holdout sample and twenty disjoint games
// supplied external validation. The unconstrained Caissa fit was unstable;
// 600 cp is the conservative external minimum, not a release calibration.
inline constexpr WdlCalibrationProfile hybrid_wdl_v2{
    "caissa125-fresh-screening-v1-provisional", 800.0, 600.0, 400.0};

double expected_score_from_cp(int centipawns, double pawn_scale);
int cp_from_expected_score(double expectation, double pawn_scale);

}  // namespace eloi
