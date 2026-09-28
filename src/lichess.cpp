#include "eloi/config.hpp"
#include "eloi/chess.hpp"
#include "eloi/brain.hpp"
#include "eloi/lichess_operations.hpp"
#include "eloi/version.hpp"
#include "eloi/version_match.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <functional>
#include <fstream>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string_view>
#include <thread>
#include <vector>

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

std::filesystem::path running_executable_path() {
  std::wstring path(32768, L'\0');
  const DWORD length = GetModuleFileNameW(
      nullptr, path.data(), static_cast<DWORD>(path.size()));
  path.resize(length);
  return std::filesystem::path(path);
}

std::filesystem::path executable_directory() {
  return running_executable_path().parent_path();
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

class HttpClient final : public LichessTransport {
 public:
  explicit HttpClient(const RuntimeConfig& config,
                      BridgeController* operations = nullptr)
      : token_(wide(config.lichess_token)), operations_(operations) {
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
    cancel();
    if (connection_) WinHttpCloseHandle(connection_);
    if (session_) WinHttpCloseHandle(session_);
  }

  bool valid() const override { return connection_ != nullptr; }
  int last_status() const override { return last_status_; }
  int retry_after_seconds() const override { return retry_after_seconds_; }

  void cancel() override {
    std::vector<HINTERNET> requests;
    {
      std::scoped_lock lock(requests_mutex_);
      requests.swap(active_requests_);
    }
    for (const HINTERNET request : requests) WinHttpCloseHandle(request);
  }

  bool request(std::wstring_view method, std::wstring_view path,
               std::string_view body, std::string* output,
               const std::function<bool(std::string_view)>& line_handler = {}) {
    if (!connection_) return false;
    retry_after_seconds_ = 0;
    const DWORD flags = secure_ ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET request{};
    {
      std::scoped_lock lock(requests_mutex_);
      request = WinHttpOpenRequest(
          connection_, std::wstring(method).c_str(), std::wstring(path).c_str(),
          nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
      if (!request) return false;
      active_requests_.push_back(request);
    }
    auto close_request = [&] {
      bool owned = false;
      {
        std::scoped_lock lock(requests_mutex_);
        const auto item = std::ranges::find(active_requests_, request);
        if (item != active_requests_.end()) {
          active_requests_.erase(item);
          owned = true;
        }
      }
      if (owned) WinHttpCloseHandle(request);
    };
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
      last_status_ = 0;
      if (operations_) operations_->set_http_status(0);
      close_request();
      return false;
    }
    DWORD status = 0, status_size = sizeof(status);
    WinHttpQueryHeaders(request,
        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX, &status, &status_size,
        WINHTTP_NO_HEADER_INDEX);
    last_status_ = static_cast<int>(status);
    if (operations_) operations_->set_http_status(last_status_);
    if (status == 429) {
      wchar_t retry[32]{};
      DWORD retry_size = sizeof(retry);
      if (WinHttpQueryHeaders(request, WINHTTP_QUERY_CUSTOM,
            L"Retry-After", retry, &retry_size, WINHTTP_NO_HEADER_INDEX)) {
        try { retry_after_seconds_ = std::max(0, std::stoi(retry)); }
        catch (...) { retry_after_seconds_ = 0; }
      }
    }
    if (status < 200 || status >= 300) {
      std::cerr << "Lichess HTTP " << status << " for "
                << std::string(path.begin(), path.end()) << '\n';
      close_request();
      return false;
    }
    if (line_handler) {
      std::cout << "Lichess stream connected: "
                << std::string(path.begin(), path.end()) << '\n';
      if (operations_) operations_->transition(
          BridgeState::connected, "Lichess stream connected");
    }
    std::string pending;
    char buffer[8192];
    for (;;) {
      DWORD available = 0;
      if (!WinHttpQueryDataAvailable(request, &available)) break;
      if (!available) {
        close_request();
        return true;
      }
      DWORD read = 0;
      const DWORD requested = std::min<DWORD>(available, sizeof(buffer));
      if (!WinHttpReadData(request, buffer, requested, &read)) break;
      if (!read) {
        close_request();
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
            close_request();
            return true;
          }
        }
      }
    }
    close_request();
    return false;
  }

  bool get(std::wstring_view path, std::string& output) override {
    return request(L"GET", path, {}, &output);
  }
  bool post(std::wstring_view path, std::string_view body = {}) override {
    return request(L"POST", path, body, nullptr);
  }
  bool stream(std::wstring_view path,
              const std::function<bool(std::string_view)>& handler) override {
    return request(L"GET", path, {}, nullptr, handler);
  }

 private:
  HINTERNET session_{};
  HINTERNET connection_{};
  std::wstring host_;
  std::wstring token_;
  INTERNET_PORT port_{};
  bool secure_{true};
  BridgeController* operations_{};
  std::mutex requests_mutex_;
  std::vector<HINTERNET> active_requests_;
  int last_status_{};
  int retry_after_seconds_{};
};

bool variant_allowed(const RuntimeConfig& config, std::string_view variant) {
  return std::ranges::find(config.variants, variant) != config.variants.end();
}

std::string append_move(std::string_view moves, std::string_view move) {
  if (moves.empty()) return std::string(move);
  return std::string(moves) + " " + std::string(move);
}

std::string form_encode(std::string_view text) {
  constexpr char digits[] = "0123456789ABCDEF";
  std::string encoded;
  encoded.reserve(text.size());
  for (const unsigned char character : text) {
    if ((character >= 'a' && character <= 'z') ||
        (character >= 'A' && character <= 'Z') ||
        (character >= '0' && character <= '9') || character == '-' ||
        character == '_' || character == '.' || character == '~') {
      encoded += static_cast<char>(character);
    } else if (character == ' ') {
      encoded += '+';
    } else {
      encoded += '%';
      encoded += digits[character >> 4];
      encoded += digits[character & 15];
    }
  }
  return encoded;
}

std::string game_event_id(std::string_view game) {
  if (const auto id = json_string(game, "gameId"); id && !id->empty())
    return *id;
  if (const auto id = json_string(game, "id"); id && !id->empty())
    return *id;
  if (const auto full_id = json_string(game, "fullId");
      full_id && full_id->size() >= 8)
    return full_id->substr(0, 8);
  return {};
}

std::string json_escape(std::string_view text) {
  std::string result;
  for (const unsigned char c : text) {
    switch (c) {
      case '\\': result += "\\\\"; break;
      case '"': result += "\\\""; break;
      case '\n': result += "\\n"; break;
      case '\r': result += "\\r"; break;
      case '\t': result += "\\t"; break;
      default: if (c >= 0x20) result += static_cast<char>(c);
    }
  }
  return result;
}

std::filesystem::path autopsy_root() {
  const wchar_t* local = _wgetenv(L"LOCALAPPDATA");
  const auto base = local && *local ? std::filesystem::path(local)
                                    : executable_directory();
  return base / "Eloi" / "autopsy";
}

void play_game(const RuntimeConfig& config, std::string_view game_id,
               std::string_view account_id,
               std::string_view tournament_id = {},
               std::string_view swiss_id = {},
               bool swiss_pairing = false,
               BridgeController* operations = nullptr) {
  HttpClient client(config, operations);
  if (!client.valid()) return;
  std::string initial(initial_fen);
  std::string variant_key{"standard"};
  RuntimeVariant game_variant{RuntimeVariant::standard};
  bool chess960 = false;
  bool horde = false;
  bool ponder_enabled = false;
  bool ponder_chat_sent = false;
  std::thread ponder_chat_thread;
  std::optional<Color> bot_side;
  std::string white_player;
  std::string black_player;
  std::optional<std::string> last_acted_moves;
  std::atomic_bool search_stopped{false};
  std::unique_ptr<Searcher> game_searcher;
  std::optional<EngineConfig> game_searcher_config;
  std::unique_ptr<IsolatedCaissaBrain> caissa_searcher;
  int caissa_hash_mb{-1};
  std::thread ponder_thread;
  std::optional<SearchResult> ponder_result;
  std::optional<SearchResult> last_search;
  std::string ponder_base_moves;
  std::string ponder_expected_moves;
  std::string active_tournament(tournament_id);
  std::string active_swiss(swiss_id);
  bool active_swiss_pairing = swiss_pairing || !active_swiss.empty();
  bool competition_announced = false;
  std::vector<std::string> journal_searches;
  std::string final_moves;
  std::string final_status{"unknown"};
  std::string final_winner;
  std::string last_brain_route{"unknown"};
  const auto journal_root = autopsy_root();
  std::error_code journal_error;
  std::filesystem::create_directories(journal_root / "queue", journal_error);
  const auto active_lock = journal_root / "active-game.lock";
  { std::ofstream lock(active_lock, std::ios::trunc);
    lock << game_id << '\n' << GetCurrentProcessId() << '\n'; }
  const std::wstring path = L"/api/bot/game/stream/" + wide(game_id);
  if (operations) {
    operations->begin_game(std::string(game_id), "pending");
    operations->set_cancel_callback([&] {
      search_stopped.store(true, std::memory_order_relaxed);
      client.cancel();
    });
  }

  auto announce_competition = [&] {
    if (competition_announced) return;
    if (active_swiss_pairing) {
      competition_announced = true;
      std::cout << "swiss";
      if (!active_swiss.empty()) std::cout << ' ' << active_swiss;
      std::cout << " pairing " << game_id << " started\n";
    } else if (!active_tournament.empty()) {
      competition_announced = true;
      std::cout << "arena " << active_tournament << " game "
                << game_id << " started\n";
    }
  };
  announce_competition();

  auto send_chat = [&](std::string_view message) {
    const std::wstring chat_path =
        L"/api/bot/game/" + wide(game_id) + L"/chat";
    return client.post(chat_path,
                       "room=player&text=" + form_encode(message));
  };

  auto handle_chat = [&](std::string_view line) {
    if (json_string(line, "room").value_or("") != "player") return;
    std::string username = json_string(line, "username").value_or("");
    std::string sender = username;
    std::ranges::transform(sender, sender.begin(), [](unsigned char character) {
      return static_cast<char>(std::tolower(character));
    });
    std::string self(account_id);
    std::ranges::transform(self, self.begin(), [](unsigned char character) {
      return static_cast<char>(std::tolower(character));
    });
    if (sender == self) return;

    std::string command = json_string(line, "text").value_or("");
    while (!command.empty() &&
           std::isspace(static_cast<unsigned char>(command.front())))
      command.erase(command.begin());
    while (!command.empty() &&
           std::isspace(static_cast<unsigned char>(command.back())))
      command.pop_back();
    std::ranges::transform(command, command.begin(), [](unsigned char character) {
      return static_cast<char>(std::tolower(character));
    });

    std::string response;
    if (command == "!help") {
      response = "Commands: !help, !version, !eval, !depth, !rematch";
    } else if (command == "!version") {
      response = "Eloi " + std::string(version) + " (native C++ Lichess client)";
    } else if (command == "!eval") {
      if (!last_search) {
        response = "No completed Eloi search yet.";
      } else if (std::abs(last_search->score_cp) >= 29'000) {
        response = "Eloi sees a forced mate.";
      } else {
        const int score = last_search->score_cp;
        response = "Eloi evaluation: " + std::string(score >= 0 ? "+" : "") +
                   std::to_string(score) + " cp (for Eloi).";
      }
    } else if (command == "!depth") {
      response = last_search
          ? "Last search: depth " + std::to_string(last_search->depth) +
                ", " + std::to_string(last_search->nodes) + " nodes."
          : "No completed Eloi search yet.";
    } else if (command == "!rematch") {
      response =
          "Request a Lichess rematch after the game; Eloi accepts when idle.";
    }
    if (!response.empty() && !send_chat(response))
      std::cerr << "Could not answer chat command in game " << game_id << '\n';
  };

  auto stop_ponder = [&] {
    if (!ponder_thread.joinable()) return;
    search_stopped.store(true, std::memory_order_relaxed);
    ponder_thread.join();
  };

  auto persistent_searcher = [&](const EngineConfig& engine) -> Searcher& {
    if (!game_searcher || game_searcher_config != engine) {
      game_searcher.reset();
      game_searcher = std::make_unique<Searcher>(engine, search_stopped);
      game_searcher_config = engine;
    }
    return *game_searcher;
  };

  auto search_position = [&](Board board, const EngineConfig& engine,
                             SearchLimits limits) -> SearchResult {
    if (runtime_variant_uses_caissa(game_variant)) {
      if (!caissa_searcher || caissa_hash_mb != engine.hash_mb) {
        const auto directory = executable_directory();
        caissa_searcher = std::make_unique<IsolatedCaissaBrain>(
            directory / "Eloi.exe", directory / "eval-71-v1.25.pnn",
            search_stopped,
            static_cast<std::size_t>(std::max(1, engine.hash_mb)) *
                1024u * 1024u);
        caissa_hash_mb = engine.hash_mb;
      }
      const auto caissa_started = std::chrono::steady_clock::now();
      BrainResponse response = caissa_searcher->search(board, limits);
      const auto caissa_elapsed =
          std::chrono::duration_cast<std::chrono::milliseconds>(
              std::chrono::steady_clock::now() - caissa_started);
      last_brain_route = "caissa_1_25";
      if (response.has_legal_move(board)) return std::move(response.search);
      if (response.status == BrainStatus::stopped) return {};
      last_brain_route = "eloi_e4_10_fallback";
      if (operations) operations->record_caissa_failure(true, false);
      std::cerr << "Caissa Lichess search failed; using Eloi E4-10 fallback: "
                << response.detail << '\n';
      search_stopped.store(false, std::memory_order_relaxed);
      limits = refresh_fallback_limits(
          std::move(limits), caissa_elapsed,
          std::chrono::steady_clock::now());
      SearchResult fallback =
          persistent_searcher(engine).iterative(board, limits);
      if (fallback.depth > 0) return fallback;

      if (!is_emergency_legal_fallback(board, fallback)) {
        std::cerr << "Refusing depth-0 Eloi fallback without a legal emergency "
                     "move\n";
        fallback.pv.clear();
        return fallback;
      }
      last_brain_route = "eloi_emergency_legal_move";
      if (operations) operations->record_caissa_failure(false, true);
      std::cerr << "Submitting Eloi-verified emergency legal move after "
                   "depth-0 fallback\n";
      return fallback;
    }
    last_brain_route = std::string(runtime_variant_brain_route(game_variant));
    return persistent_searcher(engine).iterative(std::move(board), limits);
  };
  auto take_ponder = [&](std::string_view moves, bool game_running)
      -> std::optional<SearchResult> {
    if (!ponder_thread.joinable()) return std::nullopt;
    if (game_running && moves == ponder_base_moves) return std::nullopt;
    stop_ponder();
    const bool hit = game_running && moves == ponder_expected_moves;
    ponder_base_moves.clear();
    ponder_expected_moves.clear();
    if (!hit || !ponder_result || ponder_result->pv.empty()) {
      ponder_result.reset();
      return std::nullopt;
    }
    auto result = std::move(ponder_result);
    ponder_result.reset();
    return result;
  };

  auto start_ponder = [&](const Board& board_before_move,
                          std::string_view moves_before_move,
                          const SearchResult& result) {
    if (!ponder_enabled || result.pv.size() < 2 ||
        ponder_thread.joinable()) return;
    Board predicted = board_before_move;
    const Move our_move = result.pv[0];
    if (!predicted.push(our_move)) return;
    const std::string our_uci = uci_move(
        our_move, board_before_move.position, chess960);
    const Move opponent_move = result.pv[1];
    const std::string opponent_uci = uci_move(
        opponent_move, predicted.position, chess960);
    if (!predicted.push(opponent_move)) return;

    ponder_base_moves = append_move(moves_before_move, our_uci);
    ponder_expected_moves = append_move(ponder_base_moves, opponent_uci);
    ponder_result.reset();
    search_stopped.store(false, std::memory_order_relaxed);
    EngineConfig engine = default_config();
    engine.depth = config.depth;
    engine.hash_mb = config.hash_mb;
    engine.move_overhead_ms = config.move_overhead_ms;
    engine.own_book = config.own_book &&
                      runtime_variant_allows_book(game_variant);
    ponder_thread = std::thread(
        [&, predicted = std::move(predicted), engine]() mutable {
          SearchLimits limits;
          limits.depth = config.depth;
          limits.move_overhead_ms = config.move_overhead_ms;
          ponder_result = search_position(
              std::move(predicted), engine, limits);
        });
    if (!ponder_chat_sent) {
      ponder_chat_sent = true;
      const std::string id(game_id);
      ponder_chat_thread = std::thread([config, id] {
        HttpClient chat_client(config);
        if (!chat_client.valid()) return;
        const std::wstring chat_path =
            L"/api/bot/game/" + wide(id) + L"/chat";
        const std::string message =
            "Eloi is pondering (enabled only below four minutes).";
        if (!chat_client.post(chat_path,
                              "room=player&text=" + form_encode(message)))
          std::cerr << "Could not announce pondering in game " << id << '\n';
      });
    }
  };

  auto act = [&](std::string_view state) {
    const std::string status = json_string(state, "status").value_or("started");
    const std::string moves = json_string(state, "moves").value_or("");
    final_status = status;
    final_winner = json_string(state, "winner").value_or(final_winner);
    final_moves = moves;
    const bool game_running = status == "started" || status == "created";
    if (operations) {
      const auto ply_count = static_cast<int>(std::ranges::count(moves, ' ') +
          (moves.empty() ? 0 : 1));
      operations->update_game_clock(
          ply_count, json_int(state, "wtime").value_or(-1),
          json_int(state, "btime").value_or(-1));
    }
    std::optional<SearchResult> ponder_hit = take_ponder(moves, game_running);
    if (!game_running) return;
    if (!bot_side ||
        (last_acted_moves && moves == *last_acted_moves)) return;
    auto board = parse_fen(initial == "startpos"
        ? (horde ? horde_initial_fen : initial_fen) : initial);
    if (!board) return;
    configure_board_variant(*board, game_variant);
    std::istringstream history(moves);
    for (std::string move; history >> move;)
      if (!board->push_uci(move)) return;
    if (board->turn != *bot_side) return;

    SearchResult result;
    if (ponder_hit) {
      result = std::move(*ponder_hit);
      std::cout << "game " << game_id << " ponder hit depth "
                << result.depth << '\n';
    } else {
      EngineConfig engine = default_config();
      engine.depth = config.depth;
      engine.hash_mb = config.hash_mb;
      engine.move_overhead_ms = config.move_overhead_ms;
      engine.own_book = config.own_book &&
                        runtime_variant_allows_book(game_variant);
      SearchLimits limits;
      limits.depth = config.depth;
      limits.remaining_ms = json_int(
          state, *bot_side == Color::white ? "wtime" : "btime").value_or(0);
      limits.increment_ms = json_int(
          state, *bot_side == Color::white ? "winc" : "binc").value_or(0);
      limits.move_overhead_ms = config.move_overhead_ms;
      search_stopped.store(false, std::memory_order_relaxed);
      result = search_position(*board, engine, limits);
    }
    if (last_brain_route == "eloi_e4_10_fallback" && result.depth == 0) {
      std::cerr << "Refusing unmarked depth-0 Eloi fallback at the Lichess "
                   "submission boundary\n";
      result.pv.clear();
    }
    if (last_brain_route == "eloi_emergency_legal_move" &&
        !is_emergency_legal_fallback(*board, result)) {
      std::cerr << "Refusing invalid emergency Eloi fallback at the Lichess "
                   "submission boundary\n";
      result.pv.clear();
    }
    last_search = result;
    {
      std::ostringstream record;
      record << "{\"moves_before\":\"" << json_escape(moves)
             << "\",\"wtime_ms\":" << json_int(state, "wtime").value_or(-1)
             << ",\"btime_ms\":" << json_int(state, "btime").value_or(-1)
             << ",\"winc_ms\":" << json_int(state, "winc").value_or(-1)
             << ",\"binc_ms\":" << json_int(state, "binc").value_or(-1)
             << ",\"elapsed_ms\":" << result.elapsed.count()
             << ",\"depth\":" << result.depth << ",\"seldepth\":" << result.seldepth
             << ",\"score_cp\":" << result.score_cp << ",\"mate\":" << result.mate
             << ",\"nodes\":" << result.nodes << ",\"brain_route\":\""
             << json_escape(last_brain_route) << "\",\"stop_reason\":\""
             << (ponder_hit ? "ponder_hit"
                            : (last_brain_route == "eloi_emergency_legal_move"
                                   ? "emergency_legal_move"
                                   : "completed_budgeted_search"))
             << "\",\"pv\":[";
      Board pv_board = *board;
      for (std::size_t i = 0; i < result.pv.size(); ++i) {
        if (i) record << ',';
        record << '\"' << json_escape(uci_move(result.pv[i], pv_board.position, chess960)) << '\"';
        if (!pv_board.push(result.pv[i])) break;
      }
      record << "]}";
      journal_searches.push_back(record.str());
    }
    if (result.pv.empty()) return;
    const std::string move = uci_move(
        result.pv.front(), board->position, chess960);
    const std::wstring move_path =
        L"/api/bot/game/" + wide(game_id) + L"/move/" + wide(move);
    if (client.post(move_path)) {
      last_acted_moves = moves;
      std::cout << "game " << game_id << " move " << move
                << " depth " << result.depth << '\n';
      if (operations) {
        std::ostringstream pv;
        Board pv_board = *board;
        bool first_pv_move = true;
        for (const auto& pv_move : result.pv) {
          if (!first_pv_move) pv << ' ';
          first_pv_move = false;
          pv << uci_move(pv_move, pv_board.position, chess960);
          if (!pv_board.push(pv_move)) break;
        }
        operations->record_search(
            last_brain_route,
            last_brain_route == "caissa_1_25"
                ? std::string(caissa_1_25_network_sha256)
                : std::string(nnue_model_source_sha256(
                    runtime_variant_nnue_model(game_variant))),
            move, result.depth, result.score_cp, result.nodes,
            result.elapsed.count(), pv.str(),
            last_brain_route == "eloi_emergency_legal_move"
                ? "emergency_legal_move" : "completed_budgeted_search");
      }
      start_ponder(*board, moves, result);
    }
  };

  client.stream(path, [&](std::string_view line) {
    const std::string type = json_string(line, "type").value_or("");
    if (type == "gameFull") {
      initial = json_string(line, "initialFen").value_or(std::string(initial_fen));
      if (const auto id = json_string(line, "tournamentId");
          id && !id->empty()) {
        active_tournament = *id;
        announce_competition();
      }
      if (const auto id = json_string(line, "swissId");
          id && !id->empty()) {
        active_swiss = *id;
        active_swiss_pairing = true;
        announce_competition();
      }
      if (json_string(line, "source").value_or("") == "swiss") {
        active_swiss_pairing = true;
        announce_competition();
      }
      if (const auto variant = json_object(line, "variant")) {
        variant_key = json_string(*variant, "key").value_or("standard");
        game_variant = runtime_variant_from_key(variant_key);
        chess960 = game_variant == RuntimeVariant::chess960;
        horde = game_variant == RuntimeVariant::horde;
        if (game_variant == RuntimeVariant::unsupported ||
            !variant_allowed(config, variant_key)) {
          final_status = "unsupported_variant";
          std::cerr << "Refusing unsupported or disabled Lichess variant "
                    << variant_key << " in game " << game_id << '\n';
          client.post(L"/api/bot/game/" + wide(game_id) + L"/resign");
          if (operations) operations->protocol_incident(
              "Unsupported or disabled variant reached game stream");
          return false;
        }
      }
      if (const auto clock = json_object(line, "clock")) {
        const int initial_ms = json_int(*clock, "initial").value_or(-1);
        ponder_enabled = lichess_ponder_enabled(initial_ms) &&
                         runtime_variant_allows_ponder(game_variant);
      }
      if (const auto white = json_object(line, "white")) {
        white_player = json_string(*white, "id").value_or("");
        bot_side = white_player == account_id ? Color::white : Color::black;
      }
      if (const auto black = json_object(line, "black"))
        black_player = json_string(*black, "id").value_or("");
      if (operations && bot_side) operations->begin_game(
          std::string(game_id), variant_key,
          *bot_side == Color::white ? black_player : white_player,
          *bot_side == Color::white ? "white" : "black");
      if (const auto state = json_object(line, "state")) act(*state);
    } else if (type == "gameState") {
      act(line);
      const std::string status = json_string(line, "status").value_or("");
      if (status != "started" && status != "created") {
        if (active_swiss_pairing) {
          std::cout << "swiss";
          if (!active_swiss.empty()) std::cout << ' ' << active_swiss;
          std::cout << " pairing " << game_id
                    << " finished with status " << status << '\n';
        }
        else if (!active_tournament.empty())
          std::cout << "arena " << active_tournament << " game "
                    << game_id << " finished with status " << status << '\n';
        return false;
      }
    } else if (type == "chatLine") {
      handle_chat(line);
    }
    return true;
  });
  stop_ponder();
  if (ponder_chat_thread.joinable()) ponder_chat_thread.join();
  {
    const auto output = journal_root / "queue" / (std::string(game_id) + ".json");
    const auto temporary = output.string() + ".new";
    std::ofstream journal(temporary, std::ios::binary | std::ios::trunc);
    journal << "{\n  \"schema\": \"eloi-lichess-game-journal-v1\",\n"
            << "  \"game_id\": \"" << json_escape(game_id) << "\",\n"
            << "  \"url\": \"https://lichess.org/" << json_escape(game_id) << "\",\n"
            << "  \"variant\": \"" << json_escape(variant_key) << "\",\n"
            << "  \"status\": \"" << json_escape(final_status) << "\",\n"
            << "  \"bot_color\": \"" << (bot_side == Color::white ? "white" : "black") << "\",\n"
            << "  \"moves\": \"" << json_escape(final_moves) << "\",\n"
            << "  \"version\": \"" << version << "\",\n"
            << "  \"executable_sha256\": \"" << sha256_file(running_executable_path()) << "\",\n"
            << "  \"network_sha256\": \""
            << (last_brain_route == "caissa_1_25"
                    ? caissa_1_25_network_sha256
                    : nnue_model_source_sha256(
                          runtime_variant_nnue_model(game_variant)))
            << "\",\n"
            << "  \"playing_model_role\": \"production_or_legacy\",\n"
            << "  \"searches\": [\n";
    for (std::size_t i = 0; i < journal_searches.size(); ++i)
      journal << (i ? ",\n" : "") << "    " << journal_searches[i];
    journal << "\n  ]\n}\n";
    journal.close();
    if (!std::filesystem::exists(output))
      std::filesystem::rename(temporary, output, journal_error);
    else
      std::filesystem::remove(temporary, journal_error);
  }
  std::filesystem::remove(active_lock, journal_error);
  if (operations) {
    std::string result = "incomplete";
    if (!final_winner.empty() && bot_side) {
      const bool bot_won = (final_winner == "white") == (*bot_side == Color::white);
      result = bot_won ? "win" : "loss";
    } else if (final_status == "draw" || final_status == "stalemate" ||
               final_status == "timeout" ||
               final_status == "insufficientMaterial") result = "draw";
    operations->end_game(result);
    operations->set_cancel_callback({});
  }
}

}  // namespace

int run_lichess(int argc, char** argv, BridgeController* operations) {
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
    if (operations) operations->transition(BridgeState::fatal, error, true);
    return 2;
  }
  if (check_only) {
    std::cout << "config ok\n";
    return 0;
  }
  struct MutexGuard {
    HANDLE value{};
    ~MutexGuard() { if (value) CloseHandle(value); }
  } headless_mutex;
  if (!operations) {
    headless_mutex.value = CreateMutexW(
        nullptr, FALSE, L"Local\\EloiLichessOperationsCenter-v1");
    if (!headless_mutex.value) return 2;
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
      std::cerr << "Another Eloi Lichess bridge is already running\n";
      return 2;
    }
  }
  if (!config->lichess_enabled) {
    std::cerr << "Lichess mode is disabled in config.yml\n";
    if (operations) operations->transition(
        BridgeState::fatal, "Lichess mode is disabled in config.yml", true);
    return 2;
  }
  if (config->lichess_token.empty() ||
      config->lichess_token.starts_with("lip_") == false) {
    std::cerr << "Set a valid Lichess API token in config.yml\n";
    if (operations) operations->transition(
        BridgeState::fatal, "Set a valid Lichess API token in config.yml", true);
    return 2;
  }
  if (operations) {
    std::ostringstream variants;
    for (std::size_t i = 0; i < config->variants.size(); ++i) {
      if (i) variants << ", ";
      variants << config->variants[i];
    }
    operations->set_configuration(variants.str());
  }
  if (operations) operations->transition(
      BridgeState::connecting, "Connecting to Lichess");
  HttpClient client(*config, operations);
  if (operations) operations->set_cancel_callback([&] { client.cancel(); });
  struct CancelCallbackGuard {
    BridgeController* operations{};
    ~CancelCallbackGuard() {
      if (operations) operations->set_cancel_callback({});
    }
  } cancel_callback_guard{operations};
  if (!client.valid()) {
    std::cerr << "Could not initialize Windows HTTPS\n";
    if (operations) operations->transition(
        BridgeState::fatal, "Could not initialize Windows HTTPS", true);
    return 2;
  }
  std::string account;
  int authentication_retries = 0;
  while (!client.get(L"/api/account", account)) {
    if (operations && operations->stop_requested()) return 0;
    const int status = client.last_status();
    if (bridge_http_fatal(status) ||
        (status >= 400 && !bridge_http_retryable(status))) {
      if (operations) operations->transition(
          BridgeState::fatal, "Could not authenticate Lichess account (HTTP " +
              std::to_string(status) + ")", true);
      return 2;
    }
    const int delay = status == 429 && client.retry_after_seconds() > 0
        ? client.retry_after_seconds()
        : bridge_backoff_seconds(authentication_retries);
    ++authentication_retries;
    if (operations) {
      operations->set_retry(authentication_retries, delay);
      operations->transition(BridgeState::backing_off,
          "Lichess account request failed; retrying in " +
              std::to_string(delay) + " seconds", true);
      operations->wait_backoff(delay);
      operations->clear_reconnect();
      if (operations->stop_requested()) return 0;
      operations->transition(BridgeState::connecting,
                              "Retrying Lichess authentication");
    } else {
      std::this_thread::sleep_for(std::chrono::seconds(delay));
    }
    account.clear();
  }
  if (operations) operations->set_retry(0, 0);
  const std::string account_id = json_string(account, "id").value_or("");
  const std::string username = json_string(account, "username").value_or(account_id);
  if (account_id.empty()) {
    std::cerr << "Lichess account response was invalid\n";
    if (operations) operations->transition(
        BridgeState::fatal, "Lichess account response was invalid", true);
    return 2;
  }
  if (operations) operations->set_account(username);
  std::cout << "Welcome " << username << " — native Eloi Lichess mode\n";

  bool busy = false;
  int retries = 0;
  int protocol_corruption = 0;
  for (;;) {
    if (operations && operations->stop_requested()) break;
    if (operations) operations->clear_reconnect();
    client.stream(L"/api/stream/event", [&](std::string_view line) {
      if (retries != 0) {
        retries = 0;
        if (operations) operations->set_retry(0, 0);
      }
      const std::string type = json_string(line, "type").value_or("");
      if (type.empty()) {
        ++protocol_corruption;
        if (operations) operations->protocol_incident(
            "Malformed Lichess event without a type");
        return protocol_corruption < 3;
      }
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
        const bool rematch =
            json_string(*challenge, "rematchOf").has_value();
        const bool accept = (!operations || operations->accepting()) &&
            !busy && !id.empty() &&
            variant_allowed(*config, variant) &&
            base >= config->min_base_seconds &&
            base <= config->max_base_seconds &&
            (config->allow_bots || !bot);
        const std::wstring action = L"/api/challenge/" + wide(id) +
            (accept ? L"/accept" : L"/decline");
        const bool submitted = client.post(
            action, accept ? "" : "reason=standard");
        if (submitted && accept)
          busy = true;
        if (operations) {
          if (submitted) operations->record_challenge(accept);
          else operations->protocol_incident(
              "Could not submit Lichess challenge decision");
        }
        std::cout << (accept ? (rematch ? "accepted rematch " : "accepted ")
                             : "declined ")
                  << id << " " << variant << " " << base << "+x\n";
      } else if (type == "gameStart") {
        if (const auto game = json_object(line, "game")) {
          const std::string id = game_event_id(*game);
          const std::string tournament_id =
              json_string(*game, "tournamentId").value_or("");
          const std::string swiss_id =
              json_string(*game, "swissId").value_or("");
          const bool swiss_pairing =
              json_string(*game, "source").value_or("") == "swiss" ||
              !swiss_id.empty();
          if (!id.empty()) {
            busy = true;
            play_game(*config, id, account_id, tournament_id, swiss_id,
                      swiss_pairing, operations);
            if (operations) operations->set_cancel_callback(
                [&] { client.cancel(); });
            if (operations && (operations->stop_requested() ||
                               operations->reconnect_requested()))
              return false;
          } else {
            std::cerr << "Lichess gameStart event did not contain a game ID\n";
          }
        }
        busy = false;
      } else if (type == "challengeCanceled" ||
                 type == "challengeDeclined") {
        busy = false;
      }
      return true;
    });
    if (operations && operations->stop_requested()) break;
    if (protocol_corruption >= 3) {
      if (operations) operations->transition(
          BridgeState::fatal,
          "Repeated malformed Lichess events; bridge stopped", true);
      return 2;
    }
    const int status = client.last_status();
    if (bridge_http_fatal(status) || (status >= 400 &&
        !bridge_http_retryable(status))) {
      if (operations) operations->transition(
          BridgeState::fatal, "Non-retryable Lichess HTTP " +
              std::to_string(status), true);
      return 2;
    }
    std::cerr << "Lichess event stream disconnected; reconnecting\n";
    int delay = status == 429 && client.retry_after_seconds() > 0
        ? client.retry_after_seconds() : bridge_backoff_seconds(retries);
    ++retries;
    if (operations) {
      operations->set_retry(retries, delay);
      operations->transition(BridgeState::backing_off,
          "Lichess stream disconnected; retrying in " +
              std::to_string(delay) + " seconds", true);
      operations->wait_backoff(delay);
    } else {
      std::this_thread::sleep_for(std::chrono::seconds(delay));
    }
  }
  if (operations) operations->transition(BridgeState::stopped, "Bridge stopped");
  return 0;
}

}  // namespace eloi

#else

namespace eloi {
int run_lichess(int, char**, BridgeController*) { return 2; }
}  // namespace eloi

#endif
