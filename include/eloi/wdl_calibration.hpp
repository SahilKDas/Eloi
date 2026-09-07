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
// replacing the v1.26 SCReLU net. Fresh game-separated calibration selected
// 340 cp on its fit partition, but 400 cp was better on both held-out
// partitions and is therefore retained. The public report scale is also 400.
inline constexpr WdlCalibrationProfile hybrid_wdl_v2{
    "hybrid-wdl-v4-v126-code-v125-network-calibrated",
    1300.0, 400.0, 400.0};

double expected_score_from_cp(int centipawns, double pawn_scale);
int cp_from_expected_score(double expectation, double pawn_scale);

}  // namespace eloi
