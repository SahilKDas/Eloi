#include "eloi/config.hpp"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <ranges>
#include <string_view>

namespace eloi {

bool save_runtime_config(const std::filesystem::path& path,
                         const RuntimeConfig& config,
                         std::string* error) {
  const bool token_is_yaml_safe = std::ranges::all_of(
      config.lichess_token, [](unsigned char character) {
        return !std::iscntrl(character) && character != '"' &&
               character != '\\';
      });
  if (config.lichess_url != "https://lichess.org" ||
      config.min_base_seconds < 0 ||
      config.max_base_seconds < config.min_base_seconds ||
      config.depth < 0 || config.depth > 17'697 ||
      config.hash_mb < 0 || config.move_overhead_ms < 0 ||
      config.variants.empty() || !token_is_yaml_safe ||
      !std::ranges::all_of(config.variants, [](const std::string& variant) {
        return variant == "standard" || variant == "chess960" ||
               variant == "horde";
      })) {
    if (error) *error = "configuration values are outside supported ranges";
    return false;
  }
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) {
    if (error) *error = "could not write " + path.string();
    return false;
  }
  output << "# Eloi runtime configuration. Keep your token private.\n\n"
            "lichess:\n"
            "  enabled: " << (config.lichess_enabled ? "true" : "false") << "\n"
            "  token: \"" << config.lichess_token << "\"\n"
            "  url: \"https://lichess.org\"\n\n"
            "challenge:\n"
            "  min_base_seconds: " << config.min_base_seconds << "\n"
            "  max_base_seconds: " << config.max_base_seconds << "\n"
            "  allow_bots: " << (config.allow_bots ? "true" : "false") << "\n"
            "  variants:\n";
  for (const auto& variant : config.variants)
    output << "    - " << variant << "\n";
  output << "\nengine:\n"
            "  depth: " << config.depth << "\n"
            "  hash_mb: " << config.hash_mb << "\n"
            "  move_overhead_ms: " << config.move_overhead_ms << "\n"
            "  own_book: " << (config.own_book ? "true" : "false") << "\n";
  if (!output.good()) {
    if (error) *error = "could not finish writing " + path.string();
    return false;
  }
  return true;
}

}  // namespace eloi
