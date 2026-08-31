#include "eloi/config.hpp"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <fstream>
#include <string_view>

namespace eloi {
namespace {

std::string trim(std::string_view value) {
  while (!value.empty() &&
         std::isspace(static_cast<unsigned char>(value.front())))
    value.remove_prefix(1);
  while (!value.empty() &&
         std::isspace(static_cast<unsigned char>(value.back())))
    value.remove_suffix(1);
  return std::string(value);
}

std::string without_comment(std::string_view line) {
  bool quoted = false;
  char quote = 0;
  for (std::size_t i = 0; i < line.size(); ++i) {
    const char c = line[i];
    if ((c == '"' || c == '\'') && (i == 0 || line[i - 1] != '\\')) {
      if (!quoted) { quoted = true; quote = c; }
      else if (quote == c) quoted = false;
    } else if (c == '#' && !quoted) {
      return std::string(line.substr(0, i));
    }
  }
  return std::string(line);
}

std::string scalar(std::string value) {
  value = trim(value);
  if (value.size() >= 2 &&
      ((value.front() == '"' && value.back() == '"') ||
       (value.front() == '\'' && value.back() == '\'')))
    value = value.substr(1, value.size() - 2);
  return value;
}

bool parse_bool(std::string_view value, bool& output) {
  std::string lower(value);
  std::ranges::transform(lower, lower.begin(), [](unsigned char c) {
    return static_cast<char>(std::tolower(c));
  });
  if (lower == "true" || lower == "yes" || lower == "1") {
    output = true;
    return true;
  }
  if (lower == "false" || lower == "no" || lower == "0") {
    output = false;
    return true;
  }
  return false;
}

bool parse_int(std::string_view value, int& output) {
  const auto first = value.data();
  const auto last = value.data() + value.size();
  const auto result = std::from_chars(first, last, output);
  return result.ec == std::errc{} && result.ptr == last;
}

}  // namespace

std::optional<RuntimeConfig> load_runtime_config(
    const std::filesystem::path& path, std::string* error) {
  auto fail = [&](int line, std::string message)
      -> std::optional<RuntimeConfig> {
    if (error) *error = "config line " + std::to_string(line) + ": " + message;
    return std::nullopt;
  };
  std::ifstream input(path);
  if (!input) {
    if (error) *error = "could not open " + path.string();
    return std::nullopt;
  }

  RuntimeConfig config;
  config.variants.clear();
  std::string section;
  std::string line;
  int line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    line = without_comment(line);
    if (trim(line).empty()) continue;
    const std::size_t indent = line.find_first_not_of(" \t");
    const std::string content = trim(line);
    if (indent == 0 && content.ends_with(':')) {
      section = content.substr(0, content.size() - 1);
      continue;
    }
    if (content.starts_with("- ")) {
      if (section != "challenge")
        return fail(line_number, "list item outside challenge.variants");
      const std::string value = scalar(content.substr(2));
      if (value != "standard" && value != "chess960" && value != "horde")
        return fail(line_number, "unsupported variant " + value);
      config.variants.push_back(value);
      continue;
    }
    const std::size_t colon = content.find(':');
    if (colon == std::string::npos)
      return fail(line_number, "expected key: value");
    const std::string key = trim(std::string_view(content).substr(0, colon));
    const std::string value = scalar(content.substr(colon + 1));
    bool valid = true;
    if (section == "lichess") {
      if (key == "enabled") valid = parse_bool(value, config.lichess_enabled);
      else if (key == "token") config.lichess_token = value;
      else if (key == "url") config.lichess_url = value;
    } else if (section == "challenge") {
      if (key == "min_base_seconds")
        valid = parse_int(value, config.min_base_seconds);
      else if (key == "max_base_seconds")
        valid = parse_int(value, config.max_base_seconds);
      else if (key == "allow_bots")
        valid = parse_bool(value, config.allow_bots);
      else if (key == "variants") config.variants.clear();
    } else if (section == "engine") {
      if (key == "depth") valid = parse_int(value, config.depth);
      else if (key == "hash_mb") valid = parse_int(value, config.hash_mb);
      else if (key == "move_overhead_ms")
        valid = parse_int(value, config.move_overhead_ms);
      else if (key == "own_book") valid = parse_bool(value, config.own_book);
    }
    if (!valid) return fail(line_number, "invalid value for " + key);
  }
  if (config.variants.empty()) config.variants = {"standard"};
  if (config.min_base_seconds < 0 ||
      config.max_base_seconds < config.min_base_seconds)
    return fail(line_number, "invalid base-time range");
  if (config.depth < 0 || config.depth > 17'697 ||
      config.hash_mb < 0 || config.move_overhead_ms < 0)
    return fail(line_number, "engine setting outside supported range");
  if (config.lichess_url != "https://lichess.org")
    return fail(line_number,
                "lichess.url must be exactly https://lichess.org");
  return config;
}

}  // namespace eloi
