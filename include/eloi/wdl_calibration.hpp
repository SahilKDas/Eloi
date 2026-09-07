#pragma once

#include <string_view>

namespace eloi {

struct WdlCalibrationProfile {
  std::string_view identity;
  double eloi_pawn_scale;
  double caissa_pawn_scale;
  double report_pawn_scale;
};

// Selected on 40 complete Standard games (160 positions) and confirmed on a
// disjoint 40-game/160-position campaign.  The exact game-separated report is
// data/v2_9_0_wdl_calibration.json.  The public report scale remains 400 cp;
// it does not participate in move selection.
inline constexpr WdlCalibrationProfile hybrid_wdl_v2{
    "hybrid-wdl-v2-standard-pgn-calibrated", 1300.0, 360.0, 400.0};

double expected_score_from_cp(int centipawns, double pawn_scale);
int cp_from_expected_score(double expectation, double pawn_scale);

}  // namespace eloi
