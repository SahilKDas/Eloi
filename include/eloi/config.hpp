#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace eloi {

struct Board;

enum class RuntimeVariant {
  standard, chess960, horde, king_of_the_hill, atomic, antichess, unsupported
};

RuntimeVariant runtime_variant_from_key(std::string_view key);
std::string_view runtime_variant_key(RuntimeVariant variant);
bool supported_runtime_variant(std::string_view key);
bool runtime_variant_is_fairy(RuntimeVariant variant);
bool runtime_variant_uses_caissa(RuntimeVariant variant);
bool runtime_variant_allows_book(RuntimeVariant variant);
bool runtime_variant_allows_ponder(RuntimeVariant variant);
std::string_view runtime_variant_brain_route(RuntimeVariant variant);
void configure_board_variant(Board& board, RuntimeVariant variant);

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
  std::vector<std::string> variants{
      "standard", "chess960", "horde", "kingOfTheHill", "atomic",
      "antichess"};
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
