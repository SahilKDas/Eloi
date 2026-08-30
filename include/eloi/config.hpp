#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace eloi {

inline constexpr int lichess_ponder_base_limit_ms = 240'000;
constexpr bool lichess_ponder_enabled(int initial_ms) {
  return initial_ms >= 0 && initial_ms < lichess_ponder_base_limit_ms;
}

struct RuntimeConfig {
  bool lichess_enabled{false};
  std::string lichess_token;
  std::string lichess_url{"https://lichess.org"};
  int min_base_seconds{0};
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
bool save_runtime_config(const std::filesystem::path& path,
                         const RuntimeConfig& config,
                         std::string* error = nullptr);
int run_lichess(int argc, char** argv);
int run_lichess_configurator();

}  // namespace eloi
