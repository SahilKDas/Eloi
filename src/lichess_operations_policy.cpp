#include "eloi/lichess_operations.hpp"

#include <algorithm>
#include <array>
#include <cctype>

namespace eloi {

int bridge_backoff_seconds(int retry_count) {
  constexpr std::array values{2, 4, 8, 15, 30, 60};
  return values[std::clamp(retry_count, 0,
      static_cast<int>(values.size()) - 1)];
}

bool bridge_http_retryable(int status) {
  return status == 0 || status == 408 || status == 429 || status >= 500;
}

bool bridge_http_fatal(int status) { return status == 401 || status == 403; }

std::string redact_bridge_text(std::string_view input) {
  std::string text(input);
  for (std::size_t start = text.find("lip_"); start != std::string::npos;
       start = text.find("lip_", start + 10)) {
    std::size_t end = start + 4;
    while (end < text.size() &&
           (std::isalnum(static_cast<unsigned char>(text[end])) ||
            text[end] == '_' || text[end] == '-'))
      ++end;
    text.replace(start, end - start, "[REDACTED]");
  }
  return text;
}

}  // namespace eloi
