#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace eloi {

struct RuntimeConfig {
  bool lichess_enabled{false};
  std::string lichess_token;
  std::string lichess_url{"https://lichess.org"};
  int min_base_seconds{240};
  int max_base_seconds{10'800};
  bool allow_bots{true};
  std::vector<std::string> variants{"standard", "chess960"};
  int depth{0};
  int hash_mb{32};
  int move_overhead_ms{100};
  bool own_book{true};
};

std::optional<RuntimeConfig> load_runtime_config(
    const std::filesystem::path& path, std::string* error = nullptr);
int run_lichess(int argc, char** argv);

}  // namespace eloi
