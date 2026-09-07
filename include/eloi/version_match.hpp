#pragma once

#include "eloi/chess.hpp"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace eloi {

struct UciVersionResult {
  std::string bestmove;
  std::string error;
  int depth{0};
  int score_cp{0};
  std::uint64_t nodes{0};
  std::uint64_t nps{0};
  std::uint64_t elapsed_ms{0};
  std::vector<std::string> pv;
};

class UciVersionEngine {
 public:
  explicit UciVersionEngine(std::filesystem::path executable);
  ~UciVersionEngine();

  UciVersionEngine(const UciVersionEngine&) = delete;
  UciVersionEngine& operator=(const UciVersionEngine&) = delete;

  UciVersionResult choose_move(const Board& board, int depth);
  void begin_new_game();
  void request_stop();
  const std::filesystem::path& executable() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

int run_version_match_smoke(const std::filesystem::path& current,
                            const std::filesystem::path& previous,
                            int depth = 2, int plies = 4);
std::string sha256_file(const std::filesystem::path& path);

}  // namespace eloi
