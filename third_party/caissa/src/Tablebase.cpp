#include "Tablebase.hpp"

std::uint32_t g_syzygyProbeLimit = 0;

bool HasSyzygyTablebases() { return false; }
bool HasGaviotaTablebases() { return false; }
void LoadSyzygyTablebase(const char*) {}
void LoadGaviotaTablebase(const char*) {}
void SetGaviotaCacheSize(std::size_t) {}
void UnloadTablebase() {}
void ReleoadTablebase() {}

bool ProbeSyzygy_Root(const Position&, Move&, std::uint32_t*, std::int32_t*) {
  return false;
}

bool ProbeSyzygy_WDL(const Position&, std::int32_t*) {
  return false;
}

bool ProbeGaviota(const Position&, std::uint32_t*, std::int32_t*) {
  return false;
}

bool ProbeGaviota_Root(const Position&, Move&, std::uint32_t*, std::int32_t*) {
  return false;
}
