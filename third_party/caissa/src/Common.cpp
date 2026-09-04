#include "Common.hpp"

#include "Bitboard.hpp"
#include "Endgame.hpp"
#include "Numa.hpp"
#include "PositionHash.hpp"
#include "Square.hpp"

#include <mutex>

void InitEngine() {
  static std::once_flag initialized;
  std::call_once(initialized, [] {
    numa::Init();
    Square::Init();
    InitBitboards();
    InitZobristHash();
    InitEndgame();
  });
}

std::string GetExecutablePath() {
  // Eloi prohibits donor-side executable-directory dependency discovery.
  return {};
}
