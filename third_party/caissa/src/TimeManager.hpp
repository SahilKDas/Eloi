#pragma once

#include "Search.hpp"

enum class PreviousSearchHint {
  Hit,
  Miss,
  Unknown,
};

struct TimeManagerInitData {
  std::int32_t moveTime{INT32_MAX};
  std::int32_t remainingTime{INT32_MAX};
  std::int32_t timeIncrement{0};
  std::int32_t theirRemainingTime{INT32_MAX};
  std::int32_t theirTimeIncrement{0};
  std::uint32_t movesToGo{UINT32_MAX};
  std::int32_t moveOverhead{0};
  PreviousSearchHint previousSearchHint{PreviousSearchHint::Unknown};
};

struct TimeManagerUpdateData {
  std::uint32_t depth;
  const SearchResult& currResult;
  const SearchResult& prevResult;
  double bestMoveNodeFraction{0.0};
};

struct TimeManagerState {
  std::uint32_t stabilityCounter{0};
};

void InitTimeManager(const Game& game, const TimeManagerInitData& data,
                     SearchLimits& limits);
void UpdateTimeManager(const TimeManagerUpdateData& data,
                       SearchLimits& limits, TimeManagerState& state);
