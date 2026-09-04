#include "TimeManager.hpp"

#include "Game.hpp"

#include <algorithm>

void InitTimeManager(const Game&, const TimeManagerInitData& data,
                     SearchLimits& limits) {
  std::int32_t allocation = data.moveTime;
  if (allocation == INT32_MAX && data.remainingTime != INT32_MAX) {
    const std::uint32_t moves = data.movesToGo == UINT32_MAX
                                    ? 30
                                    : std::max(1u, data.movesToGo);
    allocation = data.remainingTime / static_cast<std::int32_t>(moves) +
                 data.timeIncrement;
  }
  if (allocation == INT32_MAX) return;

  allocation = std::max(1, allocation - std::max(0, data.moveOverhead));
  const auto duration = TimePoint::FromSeconds(allocation / 1000.0f);
  limits.idealTimeBase = duration;
  limits.idealTimeCurrent = duration;
  limits.maxTime = duration;
  limits.rootSingularityTime = TimePoint::FromSeconds(
      allocation / 5000.0f);
}

void UpdateTimeManager(const TimeManagerUpdateData& data,
                       SearchLimits&, TimeManagerState& state) {
  if (!data.currResult.empty() && !data.prevResult.empty() &&
      !data.currResult.front().moves.empty() &&
      !data.prevResult.front().moves.empty() &&
      data.currResult.front().moves.front() ==
          data.prevResult.front().moves.front()) {
    ++state.stabilityCounter;
  } else {
    state.stabilityCounter = 0;
  }
}
