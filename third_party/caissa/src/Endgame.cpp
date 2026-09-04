#include "Endgame.hpp"

// Specialized donor endgames are intentionally excluded because the pinned
// implementation includes a Stockfish-derived KPK bitbase. The generic Caissa
// network remains responsible for these positions in the local experiment.
void InitEndgame() {}

bool EvaluateEndgame(const Position&, std::int32_t&) {
  return false;
}
