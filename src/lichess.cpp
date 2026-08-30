#include "eloi/config.hpp"
#include "eloi/chess.hpp"
#include "eloi/version.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <functional>
#include <iostream>
#include <optional>
#include <sstream>
#include <string_view>
#include <thread>

namespace eloi {
namespace {

std::wstring wide(std::string_view text) {
  if (text.empty()) return {};
  const int count = MultiByteToWideChar(
      CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
  std::wstring result(count, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count);
  return result;
}

std::filesystem::path executable_directory() {
  std::wstring path(32768, L'\0');
  const DWORD length = GetModuleFileNameW(
      nullptr, path.data(), static_cast<DWORD>(path.size()));
  path.resize(length);
  return std::filesystem::path(path).parent_path();
}

std::optional<std::size_t> json_value_start(
    std::string_view json, std::string_view key) {
  const std::string needle = "\"" + std::string(key) + "\"";
  std::size_t position = json.find(needle);
  if (position == std::string_view::npos) return std::nullopt;
  position = json.find(':', position + needle.size());
  if (position == std::string_view::npos) return std::nullopt;
  ++position;
  while (position < json.size() &&
         std::isspace(static_cast<unsigned char>(json[position]))) ++position;
  return position;
}

std::optional<std::string> json_string(
    std::string_view json, std::string_view key) {
  auto start = json_value_start(json, key);
  if (!start || *start >= json.size() || json[*start] != '"') return std::nullopt;
  std::string result;
  bool escaped = false;
  for (std::size_t i = *start + 1; i < json.size(); ++i) {
    const char c = json[i];
    if (escaped) {
      switch (c) {
        case 'n': result += '\n'; break;
        case 'r': result += '\r'; break;
        case 't': result += '\t'; break;
        default: result += c; break;
      }
      escaped = false;
    } else if (c == '\\') {
      escaped = true;
    } else if (c == '"') {
      return result;
    } else {
      result += c;
    }
  }
  return std::nullopt;
}

std::optional<int> json_int(std::string_view json, std::string_view key) {
  auto start = json_value_start(json, key);
  if (!start) return std::nullopt;
  std::size_t end = *start;
  if (end < json.size() && json[end] == '-') ++end;
  while (end < json.size() &&
         std::isdigit(static_cast<unsigned char>(json[end]))) ++end;
  if (end == *start) return std::nullopt;
  try { return std::stoi(std::string(json.substr(*start, end - *start))); }
  catch (...) { return std::nullopt; }
}

std::optional<std::string_view> json_object(
    std::string_view json, std::string_view key) {
  auto start = json_value_start(json, key);
  if (!start || *start >= json.size() || json[*start] != '{') return std::nullopt;
  int depth = 0;
  bool quoted = false, escaped = false;
  for (std::size_t i = *start; i < json.size(); ++i) {
    const char c = json[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (c == '\\') escaped = true;
      else if (c == '"') quoted = false;
      continue;
    }
    if (c == '"') quoted = true;
    else if (c == '{') ++depth;
    else if (c == '}' && --depth == 0)
      return json.substr(*start, i - *start + 1);
  }
  return std::nullopt;
}

class HttpClient {
 public:
  explicit HttpClient(const RuntimeConfig& config) : token_(wide(config.lichess_token)) {
    URL_COMPONENTS parts{};
    parts.dwStructSize = sizeof(parts);
    std::wstring url = wide(config.lichess_url);
    wchar_t host[256]{};
    parts.lpszHostName = host;
    parts.dwHostNameLength = static_cast<DWORD>(std::size(host));
    if (!WinHttpCrackUrl(url.c_str(), 0, 0, &parts)) return;
    secure_ = parts.nScheme == INTERNET_SCHEME_HTTPS;
    port_ = parts.nPort;
    host_.assign(parts.lpszHostName, parts.dwHostNameLength);
    if (!secure_ || port_ != INTERNET_DEFAULT_HTTPS_PORT ||
        CompareStringOrdinal(host_.c_str(), -1, L"lichess.org", -1, TRUE) !=
            CSTR_EQUAL) {
      host_.clear();
      return;
    }
    const std::wstring agent = L"Eloi/" + wide(version) +
                               L" native Lichess client";
    session_ = WinHttpOpen(agent.c_str(),
                           WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                           WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (session_) {
      WinHttpSetTimeouts(session_, 10'000, 10'000, 10'000, 60'000);
      connection_ = WinHttpConnect(session_, host_.c_str(), port_, 0);
    }
  }

  ~HttpClient() {
    if (connection_) WinHttpCloseHandle(connection_);
    if (session_) WinHttpCloseHandle(session_);
  }

  bool valid() const { return connection_ != nullptr; }

  bool request(std::wstring_view method, std::wstring_view path,
               std::string_view body, std::string* output,
               const std::function<bool(std::string_view)>& line_handler = {}) {
    if (!connection_) return false;
    const DWORD flags = secure_ ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET request = WinHttpOpenRequest(
        connection_, std::wstring(method).c_str(), std::wstring(path).c_str(),
        nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!request) return false;
    const std::wstring headers =
        L"Authorization: Bearer " + token_ +
        L"\r\nAccept: application/x-ndjson\r\n"
        L"Content-Type: application/x-www-form-urlencoded\r\n";
    const BOOL sent = WinHttpSendRequest(
        request, headers.c_str(), static_cast<DWORD>(-1L),
        body.empty() ? WINHTTP_NO_REQUEST_DATA
                     : const_cast<char*>(body.data()),
        static_cast<DWORD>(body.size()), static_cast<DWORD>(body.size()), 0);
    if (!sent || !WinHttpReceiveResponse(request, nullptr)) {
      WinHttpCloseHandle(request);
      return false;
    }
    DWORD status = 0, status_size = sizeof(status);
    WinHttpQueryHeaders(request,
        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX, &status, &status_size,
        WINHTTP_NO_HEADER_INDEX);
    if (status < 200 || status >= 300) {
      std::cerr << "Lichess HTTP " << status << " for "
                << std::string(path.begin(), path.end()) << '\n';
      WinHttpCloseHandle(request);
      return false;
    }
    std::string pending;
    char buffer[8192];
    for (;;) {
      DWORD read = 0;
      if (!WinHttpReadData(request, buffer, sizeof(buffer), &read)) break;
      if (!read) {
        WinHttpCloseHandle(request);
        return true;
      }
      if (output) output->append(buffer, read);
      if (line_handler) {
        pending.append(buffer, read);
        for (;;) {
          const std::size_t newline = pending.find('\n');
          if (newline == std::string::npos) break;
          std::string line = pending.substr(0, newline);
          pending.erase(0, newline + 1);
          if (!line.empty() && !line_handler(line)) {
            WinHttpCloseHandle(request);
            return true;
          }
        }
      }
    }
    WinHttpCloseHandle(request);
    return false;
  }

  bool get(std::wstring_view path, std::string& output) {
    return request(L"GET", path, {}, &output);
  }
  bool post(std::wstring_view path, std::string_view body = {}) {
    return request(L"POST", path, body, nullptr);
  }
  bool stream(std::wstring_view path,
              const std::function<bool(std::string_view)>& handler) {
    return request(L"GET", path, {}, nullptr, handler);
  }

 private:
  HINTERNET session_{};
  HINTERNET connection_{};
  std::wstring host_;
  std::wstring token_;
  INTERNET_PORT port_{};
  bool secure_{true};
};

bool variant_allowed(const RuntimeConfig& config, std::string_view variant) {
  return std::ranges::find(config.variants, variant) != config.variants.end();
}

void play_game(const RuntimeConfig& config, std::string_view game_id,
               std::string_view account_id) {
  HttpClient client(config);
  if (!client.valid()) return;
  std::string initial(initial_fen);
  bool chess960 = false;
  std::optional<Color> bot_side;
  std::string last_acted_moves;
  const std::wstring path = L"/api/bot/game/stream/" + wide(game_id);

  auto act = [&](std::string_view state) {
    const std::string status = json_string(state, "status").value_or("started");
    if (status != "started" && status != "created") return;
    const std::string moves = json_string(state, "moves").value_or("");
    if (!bot_side || moves == last_acted_moves) return;
    auto board = parse_fen(initial == "startpos" ? initial_fen : initial);
    if (!board) return;
    board->chess960 = chess960;
    std::istringstream history(moves);
    for (std::string move; history >> move;)
      if (!board->push_uci(move)) return;
    if (board->turn != *bot_side) return;

    EngineConfig engine = default_config(EngineKind::eloi);
    engine.depth = config.depth;
    engine.hash_mb = config.hash_mb;
    engine.move_overhead_ms = config.move_overhead_ms;
    engine.own_book = config.own_book && !chess960;
    SearchLimits limits;
    limits.depth = config.depth;
    limits.remaining_ms = json_int(
        state, *bot_side == Color::white ? "wtime" : "btime").value_or(0);
    limits.increment_ms = json_int(
        state, *bot_side == Color::white ? "winc" : "binc").value_or(0);
    limits.move_overhead_ms = config.move_overhead_ms;
    std::atomic_bool stopped{false};
    Searcher searcher(engine, stopped);
    const SearchResult result = searcher.iterative(*board, limits);
    if (result.pv.empty()) return;
    const std::string move = uci_move(
        result.pv.front(), board->position, chess960);
    const std::wstring move_path =
        L"/api/bot/game/" + wide(game_id) + L"/move/" + wide(move);
    if (client.post(move_path)) {
      last_acted_moves = moves;
      std::cout << "game " << game_id << " move " << move
                << " depth " << result.depth << '\n';
    }
  };

  client.stream(path, [&](std::string_view line) {
    const std::string type = json_string(line, "type").value_or("");
    if (type == "gameFull") {
      initial = json_string(line, "initialFen").value_or(std::string(initial_fen));
      if (const auto variant = json_object(line, "variant"))
        chess960 = json_string(*variant, "key").value_or("") == "chess960";
      if (const auto white = json_object(line, "white")) {
        const std::string white_id = json_string(*white, "id").value_or("");
        bot_side = white_id == account_id ? Color::white : Color::black;
      }
      if (const auto state = json_object(line, "state")) act(*state);
    } else if (type == "gameState") {
      act(line);
      const std::string status = json_string(line, "status").value_or("");
      if (status != "started" && status != "created") return false;
    }
    return true;
  });
}

}  // namespace

int run_lichess(int argc, char** argv) {
  std::filesystem::path path = executable_directory() / "config.yml";
  bool check_only = false;
  for (int i = 1; i < argc; ++i) {
    const std::string_view arg = argv[i];
    if (arg == "--config" && i + 1 < argc) path = argv[++i];
    else if (arg == "--check-config") check_only = true;
  }
  std::string error;
  auto config = load_runtime_config(path, &error);
  if (!config) {
    std::cerr << "config error: " << error << '\n';
    return 2;
  }
  if (check_only) {
    std::cout << "config ok\n";
    return 0;
  }
  if (!config->lichess_enabled) {
    std::cerr << "Lichess mode is disabled in config.yml\n";
    return 2;
  }
  if (config->lichess_token.empty() ||
      config->lichess_token.starts_with("lip_") == false) {
    std::cerr << "Set a valid Lichess API token in config.yml\n";
    return 2;
  }
  HttpClient client(*config);
  if (!client.valid()) {
    std::cerr << "Could not initialize Windows HTTPS\n";
    return 2;
  }
  std::string account;
  if (!client.get(L"/api/account", account)) return 2;
  const std::string account_id = json_string(account, "id").value_or("");
  const std::string username = json_string(account, "username").value_or(account_id);
  if (account_id.empty()) {
    std::cerr << "Lichess account response was invalid\n";
    return 2;
  }
  std::cout << "Welcome " << username << " — native Eloi Lichess mode\n";

  bool busy = false;
  for (;;) {
    client.stream(L"/api/stream/event", [&](std::string_view line) {
      const std::string type = json_string(line, "type").value_or("");
      if (type == "challenge") {
        const auto challenge = json_object(line, "challenge");
        if (!challenge) return true;
        const std::string id = json_string(*challenge, "id").value_or("");
        const auto variant_object = json_object(*challenge, "variant");
        const auto clock = json_object(*challenge, "timeControl");
        const auto challenger = json_object(*challenge, "challenger");
        const std::string variant = variant_object
            ? json_string(*variant_object, "key").value_or("") : "";
        const int base = clock ? json_int(*clock, "limit").value_or(-1) : -1;
        const bool bot = challenger &&
            json_string(*challenger, "title").value_or("") == "BOT";
        const bool accept = !busy && !id.empty() &&
            variant_allowed(*config, variant) &&
            base >= config->min_base_seconds &&
            base <= config->max_base_seconds &&
            (config->allow_bots || !bot);
        const std::wstring action = L"/api/challenge/" + wide(id) +
            (accept ? L"/accept" : L"/decline");
        if (client.post(action, accept ? "" : "reason=standard") && accept)
          busy = true;
        std::cout << (accept ? "accepted " : "declined ")
                  << id << " " << variant << " " << base << "+x\n";
      } else if (type == "gameStart") {
        if (const auto game = json_object(line, "game")) {
          const std::string id = json_string(*game, "id").value_or("");
          if (!id.empty()) play_game(*config, id, account_id);
        }
        busy = false;
      } else if (type == "challengeCanceled" ||
                 type == "challengeDeclined") {
        busy = false;
      }
      return true;
    });
    std::cerr << "Lichess event stream disconnected; reconnecting\n";
    std::this_thread::sleep_for(std::chrono::seconds(2));
  }
}

}  // namespace eloi

#else

namespace eloi {
int run_lichess(int, char**) { return 2; }
}  // namespace eloi

#endif
