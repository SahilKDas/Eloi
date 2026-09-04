#pragma once

#include "Common.hpp"

extern std::uint32_t g_syzygyProbeLimit;

bool HasSyzygyTablebases();
bool HasGaviotaTablebases();
void LoadSyzygyTablebase(const char* path);
void LoadGaviotaTablebase(const char* path);
void SetGaviotaCacheSize(std::size_t cache_size);
void UnloadTablebase();
void ReleoadTablebase();
bool ProbeSyzygy_Root(const Position& position, Move& move,
                      std::uint32_t* distance_to_zero = nullptr,
                      std::int32_t* wdl = nullptr);
bool ProbeSyzygy_WDL(const Position& position, std::int32_t* wdl);
bool ProbeGaviota(const Position& position,
                  std::uint32_t* distance_to_mate = nullptr,
                  std::int32_t* wdl = nullptr);
bool ProbeGaviota_Root(const Position& position, Move& move,
                       std::uint32_t* distance_to_mate = nullptr,
                       std::int32_t* wdl = nullptr);
