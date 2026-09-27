#include "eloi/lichess_operations.hpp"

#include "eloi/config.hpp"
#include "eloi/version.hpp"
#include "eloi/version_match.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <thread>

namespace eloi {
namespace {

constexpr UINT refresh_timer = 1;
constexpr UINT show_existing_message = WM_APP + 41;
constexpr int toggle_button = 2001;
constexpr int reconnect_button = 2002;
constexpr int configure_button = 2003;
constexpr int copy_button = 2004;
constexpr int logs_button = 2005;
constexpr int exit_button = 2006;
constexpr wchar_t operations_class[] = L"EloiLichessOperationsCenter";

std::wstring wide(std::string_view text) {
  if (text.empty()) return {};
  const int count = MultiByteToWideChar(CP_UTF8, 0, text.data(),
      static_cast<int>(text.size()), nullptr, 0);
  std::wstring result(count, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count);
  return result;
}

std::string iso_time(std::chrono::system_clock::time_point value) {
  const auto raw = std::chrono::system_clock::to_time_t(value);
  std::tm tm{};
  gmtime_s(&tm, &raw);
  std::ostringstream out;
  out << std::put_time(&tm, "%Y-%m-%dT%H:%M:%SZ");
  return out.str();
}

std::string json_escape_ops(std::string_view text) {
  std::string out;
  for (const unsigned char c : text) {
    if (c == '\\') out += "\\\\";
    else if (c == '"') out += "\\\"";
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if (c == '\t') out += "\\t";
    else if (c >= 0x20) out += static_cast<char>(c);
  }
  return out;
}

std::filesystem::path operations_root() {
  if (const wchar_t* local = _wgetenv(L"LOCALAPPDATA"); local && *local)
    return std::filesystem::path(local) / "Eloi";
  return std::filesystem::temp_directory_path() / "Eloi";
}

std::filesystem::path argument_config(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; ++i)
    if (std::string_view(argv[i]) == "--config") return argv[i + 1];
  std::wstring path(32768, L'\0');
  const DWORD size = GetModuleFileNameW(nullptr, path.data(),
                                        static_cast<DWORD>(path.size()));
  path.resize(size);
  return std::filesystem::path(path).parent_path() / "config.yml";
}

struct Dashboard {
  BridgeController* controller{};
  HWND window{};
  HWND state{};
  HWND details{};
  HWND counters{};
  HWND events{};
  HWND toggle{};
  HFONT font{};
  std::filesystem::path executable;
  std::filesystem::path config;
};

void set_text(HWND control, const std::string& value) {
  SetWindowTextW(control, wide(value).c_str());
}

std::string diagnostics(const BridgeSnapshot& s) {
  std::ostringstream out;
  out << "Eloi " << s.version << "\nstate: " << bridge_state_name(s.state)
      << "\nexecutable: " << s.executable_sha256
      << "\naccount: " << s.account
      << "\nhttp: " << s.last_http_status
      << "\nreconnects: " << s.reconnect_attempts
      << "\naccepting: " << (s.accepting ? "yes" : "no")
      << "\ngame: " << s.active_game_id << " " << s.variant
      << "\nroute: " << s.brain_route << "\nnetwork: " << s.network_sha256
      << "\nsearch: depth " << s.depth << " score " << s.score_cp
      << " nodes " << s.nodes << " time " << s.elapsed_ms << "ms"
      << "\nlast error: " << s.last_error;
  return redact_bridge_text(out.str());
}

void refresh(Dashboard& ui) {
  const auto s = ui.controller->snapshot();
  const auto uptime = std::chrono::duration_cast<std::chrono::seconds>(
      std::chrono::system_clock::now() - s.started_at).count();
  set_text(ui.state, "State: " + std::string(bridge_state_name(s.state)) +
      (s.account.empty() ? "" : "  |  " + s.account) +
      (s.next_retry_seconds ? "  |  retry in " +
          std::to_string(s.next_retry_seconds) + "s" : ""));
  std::ostringstream detail;
  detail << "Eloi " << s.version << "   SHA-256: " << s.executable_sha256
         << "   Uptime: " << uptime << "s   HTTP: " << s.last_http_status
         << "   Reconnects: " << s.reconnect_attempts
         << "\r\nEnabled variants: " << s.enabled_variants
         << "   Accepting: " << (s.accepting ? "yes" : "no")
         << "\r\nGame: " << (s.active_game_id.empty() ? "none" : s.active_game_id)
         << (s.active_game_id.empty() ? "" : "   https://lichess.org/" + s.active_game_id)
         << "   Opponent: " << (s.opponent.empty() ? "-" : s.opponent)
         << "   Color: " << (s.color.empty() ? "-" : s.color)
         << "   Variant: " << (s.variant.empty() ? "-" : s.variant)
         << "   Route: " << (s.brain_route.empty() ? "-" : s.brain_route)
         << "\r\nPly: " << s.ply << "   Clocks: " << s.white_time_ms
         << " / " << s.black_time_ms << " ms   Last result: "
         << (s.last_result.empty() ? "-" : s.last_result)
         << "\r\nLatest: " << (s.latest_move.empty() ? "-" : s.latest_move)
         << "   Depth: " << s.depth << "   Score: " << s.score_cp
         << " cp   Nodes: " << s.nodes << "   Time: " << s.elapsed_ms << " ms"
         << "   Stop: " << s.stop_reason << "\r\nPV: " << s.pv
         << "\r\nLast error: " << s.last_error;
  set_text(ui.details, detail.str());
  std::ostringstream counts;
  counts << "Challenges " << s.accepted << " accepted / " << s.declined
         << " declined   Games " << s.completed_wins << "W/"
         << s.completed_draws << "D/" << s.completed_losses
         << "L   Caissa failures " << s.caissa_failures
         << "   E4 fallbacks " << s.eloi_fallbacks
         << "   Emergency " << s.emergency_moves
         << "   Protocol " << s.protocol_incidents;
  set_text(ui.counters, counts.str());
  SetWindowTextW(ui.toggle, s.accepting ? L"Stop accepting" : L"Start accepting");
  SendMessageW(ui.events, LB_RESETCONTENT, 0, 0);
  for (const auto& event : s.events) {
    const std::wstring row = wide(iso_time(event.at) + "  " + event.message);
    SendMessageW(ui.events, LB_ADDSTRING, 0,
                 reinterpret_cast<LPARAM>(row.c_str()));
  }
  const auto count = SendMessageW(ui.events, LB_GETCOUNT, 0, 0);
  if (count > 0) SendMessageW(ui.events, LB_SETTOPINDEX, count - 1, 0);
}

void copy_text(HWND window, const std::string& text) {
  const std::wstring value = wide(text);
  if (!OpenClipboard(window)) return;
  EmptyClipboard();
  const SIZE_T bytes = (value.size() + 1) * sizeof(wchar_t);
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, bytes);
  if (memory) {
    std::memcpy(GlobalLock(memory), value.c_str(), bytes);
    GlobalUnlock(memory);
    SetClipboardData(CF_UNICODETEXT, memory);
  }
  CloseClipboard();
}

LRESULT CALLBACK dashboard_proc(HWND window, UINT message,
                                WPARAM wparam, LPARAM lparam) {
  auto* ui = reinterpret_cast<Dashboard*>(GetWindowLongPtrW(
      window, GWLP_USERDATA));
  if (message == WM_NCCREATE) {
    ui = static_cast<Dashboard*>(
        reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
    SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(ui));
    ui->window = window;
  }
  if (!ui) return DefWindowProcW(window, message, wparam, lparam);
  if (message == WM_TIMER) {
    refresh(*ui);
    return 0;
  }
  if (message == show_existing_message) {
    ShowWindow(window, SW_RESTORE);
    SetForegroundWindow(window);
    return 0;
  }
  if (message == WM_COMMAND) {
    switch (LOWORD(wparam)) {
      case toggle_button: ui->controller->toggle_accepting(); break;
      case reconnect_button: ui->controller->request_reconnect(); break;
      case configure_button: {
        std::wstring args = L"--lichess --configure --config \"" +
                            ui->config.wstring() + L"\"";
        ShellExecuteW(window, L"open", ui->executable.c_str(), args.c_str(),
                      ui->executable.parent_path().c_str(), SW_SHOWNORMAL);
        break;
      }
      case copy_button: copy_text(window, diagnostics(ui->controller->snapshot())); break;
      case logs_button:
        ShellExecuteW(window, L"open", ui->controller->log_directory().c_str(),
                      nullptr, nullptr, SW_SHOWNORMAL);
        break;
      case exit_button: SendMessageW(window, WM_CLOSE, 0, 0); break;
    }
    return 0;
  }
  if (message == WM_CLOSE) {
    const auto s = ui->controller->snapshot();
    if (s.active_game && MessageBoxW(window,
          L"A game is active. Stopping now may forfeit or time out the game. Exit immediately?",
          L"Stop Eloi Lichess", MB_YESNO | MB_ICONWARNING) != IDYES)
      return 0;
    ui->controller->request_stop();
    DestroyWindow(window);
    return 0;
  }
  if (message == WM_DESTROY) {
    PostQuitMessage(0);
    return 0;
  }
  return DefWindowProcW(window, message, wparam, lparam);
}

HWND add(HWND parent, const wchar_t* type, const wchar_t* label, DWORD style,
         int x, int y, int width, int height, int id, HFONT font) {
  HWND control = CreateWindowExW(
      std::wstring_view(type) == L"EDIT" ? WS_EX_CLIENTEDGE : 0,
      type, label, WS_CHILD | WS_VISIBLE | style, x, y, width, height,
      parent, reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
      GetModuleHandleW(nullptr), nullptr);
  SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
  return control;
}

}  // namespace

std::string_view bridge_state_name(BridgeState state) {
  switch (state) {
    case BridgeState::stopped: return "stopped";
    case BridgeState::connecting: return "connecting";
    case BridgeState::connected: return "connected";
    case BridgeState::playing: return "playing";
    case BridgeState::backing_off: return "backing off";
    case BridgeState::fatal: return "fatal";
    case BridgeState::stopping: return "stopping";
  }
  return "unknown";
}

BridgeController::BridgeController(std::filesystem::path executable,
                                   std::filesystem::path config)
    : executable_(std::move(executable)), config_path_(std::move(config)) {
  snapshot_.version = std::string(version);
  snapshot_.executable_sha256 = sha256_file(executable_);
  snapshot_.started_at = std::chrono::system_clock::now();
  const auto root = operations_root();
  log_directory_ = root / "logs" / "lichess";
  status_path_ = root / "status" / "lichess.json";
  std::error_code error;
  std::filesystem::create_directories(log_directory_, error);
  std::filesystem::create_directories(status_path_.parent_path(), error);
  rotate_logs();
  const auto stamp = std::chrono::system_clock::to_time_t(snapshot_.started_at);
  log_path_ = log_directory_ / ("bridge-" + std::to_string(stamp) + ".log");
}

BridgeController::~BridgeController() { request_stop(); }

void BridgeController::rotate_logs() {
  std::error_code error;
  std::vector<std::filesystem::directory_entry> files;
  for (const auto& item : std::filesystem::directory_iterator(log_directory_, error))
    if (item.is_regular_file() && item.path().extension() == ".log") files.push_back(item);
  std::ranges::sort(files, {}, [](const auto& item) {
    std::error_code ignored; return item.last_write_time(ignored);
  });
  std::uintmax_t total{};
  for (const auto& item : files) total += item.file_size(error);
  while (files.size() >= 10 || total > 10u * 1024u * 1024u) {
    const auto size = files.front().file_size(error);
    std::filesystem::remove(files.front().path(), error);
    total = total > size ? total - size : 0;
    files.erase(files.begin());
  }
}

void BridgeController::persist_event_locked(const BridgeEvent& event) {
  std::ofstream output(log_path_, std::ios::app);
  output << iso_time(event.at) << ' ' << bridge_state_name(event.state) << ' '
         << (event.error ? "ERROR " : "")
         << redact_bridge_text(event.message) << '\n';
  output.close();
  rotate_logs();
}

void BridgeController::write_snapshot_locked() const {
  const auto temporary = status_path_.string() + ".new";
  std::ofstream out(temporary, std::ios::trunc);
  out << "{\n  \"schema\": \"eloi-lichess-operations-v1\",\n"
      << "  \"version\": \"" << json_escape_ops(snapshot_.version) << "\",\n"
      << "  \"state\": \"" << bridge_state_name(snapshot_.state) << "\",\n"
      << "  \"account\": \"" << json_escape_ops(snapshot_.account) << "\",\n"
      << "  \"accepting\": " << (snapshot_.accepting ? "true" : "false") << ",\n"
      << "  \"active_game_id\": \"" << json_escape_ops(snapshot_.active_game_id) << "\",\n"
      << "  \"variant\": \"" << json_escape_ops(snapshot_.variant) << "\",\n"
      << "  \"brain_route\": \"" << json_escape_ops(snapshot_.brain_route) << "\",\n"
      << "  \"network_sha256\": \"" << json_escape_ops(snapshot_.network_sha256) << "\",\n"
      << "  \"latest_move\": \"" << json_escape_ops(snapshot_.latest_move) << "\",\n"
      << "  \"depth\": " << snapshot_.depth << ",\n"
      << "  \"score_cp\": " << snapshot_.score_cp << ",\n"
      << "  \"nodes\": " << snapshot_.nodes << ",\n"
      << "  \"elapsed_ms\": " << snapshot_.elapsed_ms << ",\n"
      << "  \"last_http_status\": " << snapshot_.last_http_status << ",\n"
      << "  \"reconnect_attempts\": " << snapshot_.reconnect_attempts << ",\n"
      << "  \"accepted_challenges\": " << snapshot_.accepted << ",\n"
      << "  \"declined_challenges\": " << snapshot_.declined << ",\n"
      << "  \"completed_wins\": " << snapshot_.completed_wins << ",\n"
      << "  \"completed_draws\": " << snapshot_.completed_draws << ",\n"
      << "  \"completed_losses\": " << snapshot_.completed_losses << ",\n"
      << "  \"protocol_incidents\": " << snapshot_.protocol_incidents << ",\n"
      << "  \"last_error\": \"" << json_escape_ops(snapshot_.last_error) << "\"\n}\n";
  out.close();
  MoveFileExW(std::filesystem::path(temporary).c_str(), status_path_.c_str(),
              MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

void BridgeController::publish(BridgeEvent event) {
  std::scoped_lock lock(mutex_);
  event.message = redact_bridge_text(event.message);
  snapshot_.events.push_back(event);
  if (snapshot_.events.size() > 300) snapshot_.events.erase(snapshot_.events.begin());
  if (event.error) snapshot_.last_error = event.message;
  persist_event_locked(event);
  write_snapshot_locked();
  std::cout << event.message << '\n';
}

void BridgeController::transition(BridgeState state, std::string message,
                                  bool error) {
  {
    std::scoped_lock lock(mutex_);
    snapshot_.state = state;
    if (error) snapshot_.last_error = redact_bridge_text(message);
  }
  if (!message.empty()) publish({std::chrono::system_clock::now(), state,
                                 std::move(message), error});
}

#define ELOI_OPS_LOCK std::scoped_lock lock(mutex_)
void BridgeController::set_account(std::string value) { ELOI_OPS_LOCK; snapshot_.account=std::move(value); write_snapshot_locked(); }
void BridgeController::set_configuration(std::string value) { ELOI_OPS_LOCK; snapshot_.enabled_variants=std::move(value); write_snapshot_locked(); }
void BridgeController::set_http_status(int value) { ELOI_OPS_LOCK; snapshot_.last_http_status=value; write_snapshot_locked(); }
void BridgeController::set_retry(int a,int s) { ELOI_OPS_LOCK; snapshot_.reconnect_attempts=a; snapshot_.next_retry_seconds=s; write_snapshot_locked(); }
void BridgeController::begin_game(std::string id,std::string variant,std::string opponent,std::string color) { ELOI_OPS_LOCK; snapshot_.active_game=true; snapshot_.active_game_id=std::move(id); snapshot_.variant=std::move(variant); snapshot_.opponent=std::move(opponent); snapshot_.color=std::move(color); snapshot_.state=BridgeState::playing; write_snapshot_locked(); }
void BridgeController::update_game_clock(int p,std::int64_t w,std::int64_t b) { ELOI_OPS_LOCK; snapshot_.ply=p; snapshot_.white_time_ms=w; snapshot_.black_time_ms=b; }
void BridgeController::record_search(std::string route,std::string network,std::string move,int depth,int score,std::uint64_t nodes,std::int64_t elapsed,std::string pv,std::string reason) { ELOI_OPS_LOCK; snapshot_.brain_route=std::move(route); snapshot_.network_sha256=std::move(network); snapshot_.latest_move=std::move(move); snapshot_.depth=depth; snapshot_.score_cp=score; snapshot_.nodes=nodes; snapshot_.elapsed_ms=elapsed; snapshot_.pv=std::move(pv); snapshot_.stop_reason=std::move(reason); write_snapshot_locked(); }
void BridgeController::end_game(std::string result) { ELOI_OPS_LOCK; if(result=="win")++snapshot_.completed_wins; else if(result=="draw")++snapshot_.completed_draws; else if(result=="loss")++snapshot_.completed_losses; snapshot_.last_result=std::move(result); snapshot_.active_game=false; snapshot_.active_game_id.clear(); snapshot_.state=BridgeState::connected; write_snapshot_locked(); }
void BridgeController::record_challenge(bool accepted) { ELOI_OPS_LOCK; if (accepted) ++snapshot_.accepted; else ++snapshot_.declined; }
void BridgeController::record_caissa_failure(bool fallback,bool emergency) { ELOI_OPS_LOCK; if (fallback) { ++snapshot_.caissa_failures; ++snapshot_.eloi_fallbacks; } if(emergency)++snapshot_.emergency_moves; }
void BridgeController::protocol_incident(std::string message) { { ELOI_OPS_LOCK; ++snapshot_.protocol_incidents; } publish({std::chrono::system_clock::now(),snapshot().state,std::move(message),true}); }
#undef ELOI_OPS_LOCK

BridgeSnapshot BridgeController::snapshot() const { std::scoped_lock lock(mutex_); return snapshot_; }
bool BridgeController::accepting() const { std::scoped_lock lock(mutex_); return snapshot_.accepting; }
void BridgeController::toggle_accepting() { { std::scoped_lock lock(mutex_); snapshot_.accepting=!snapshot_.accepting; write_snapshot_locked(); } condition_.notify_all(); }
bool BridgeController::stop_requested() const { std::scoped_lock lock(mutex_); return snapshot_.stop_requested; }
bool BridgeController::reconnect_requested() const { std::scoped_lock lock(mutex_); return reconnect_requested_; }
void BridgeController::clear_reconnect() { std::scoped_lock lock(mutex_); reconnect_requested_=false; }
void BridgeController::request_reconnect() { std::function<void()> cancel; { std::scoped_lock lock(mutex_); reconnect_requested_=true; cancel=cancel_callback_; } if(cancel)cancel(); condition_.notify_all(); }
void BridgeController::request_stop() { std::function<void()> cancel; { std::scoped_lock lock(mutex_); snapshot_.stop_requested=true; snapshot_.state=BridgeState::stopping; cancel=cancel_callback_; } if(cancel)cancel(); condition_.notify_all(); }
void BridgeController::set_cancel_callback(std::function<void()> cb) { std::scoped_lock lock(mutex_); cancel_callback_=std::move(cb); }
bool BridgeController::wait_backoff(int seconds) { std::unique_lock lock(mutex_); return !condition_.wait_for(lock,std::chrono::seconds(seconds),[&]{return snapshot_.stop_requested||reconnect_requested_;}); }

int run_lichess_operations_center(int argc, char** argv) {
  HANDLE mutex = CreateMutexW(nullptr, FALSE, L"Local\\EloiLichessOperationsCenter-v1");
  if (!mutex) return 2;
  if (GetLastError() == ERROR_ALREADY_EXISTS) {
    if (HWND existing = FindWindowW(operations_class, nullptr))
      PostMessageW(existing, show_existing_message, 0, 0);
    CloseHandle(mutex);
    return 0;
  }
  std::wstring executable_text(32768, L'\0');
  const DWORD length = GetModuleFileNameW(nullptr, executable_text.data(),
                                          static_cast<DWORD>(executable_text.size()));
  executable_text.resize(length);
  const std::filesystem::path executable(executable_text);
  Dashboard ui;
  ui.executable = executable;
  ui.config = argument_config(argc, argv);
  BridgeController controller(executable, ui.config);
  ui.controller = &controller;

  WNDCLASSEXW wc{}; wc.cbSize=sizeof(wc); wc.lpfnWndProc=dashboard_proc;
  wc.hInstance=GetModuleHandleW(nullptr);
  wc.hCursor=LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
  wc.hbrBackground=reinterpret_cast<HBRUSH>(COLOR_WINDOW+1); wc.lpszClassName=operations_class;
  RegisterClassExW(&wc);
  ui.font=CreateFontW(-17,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,
      OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Segoe UI");
  ui.window=CreateWindowExW(0,operations_class,L"Eloi Lichess Operations Center",
      WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,980,780,nullptr,nullptr,
      GetModuleHandleW(nullptr),&ui);
  ui.state=add(ui.window,L"STATIC",L"State: starting",SS_LEFT,20,18,920,28,0,ui.font);
  ui.details=add(ui.window,L"EDIT",L"",ES_MULTILINE|ES_READONLY|WS_VSCROLL,
      20,54,920,190,0,ui.font);
  ui.counters=add(ui.window,L"STATIC",L"",SS_LEFT,20,254,920,44,0,ui.font);
  ui.events=add(ui.window,L"LISTBOX",L"",LBS_NOINTEGRALHEIGHT|WS_VSCROLL,
      20,302,920,340,0,ui.font);
  ui.toggle=add(ui.window,L"BUTTON",L"Stop accepting",BS_PUSHBUTTON,20,664,140,34,toggle_button,ui.font);
  add(ui.window,L"BUTTON",L"Reconnect now",BS_PUSHBUTTON,172,664,130,34,reconnect_button,ui.font);
  add(ui.window,L"BUTTON",L"Configure",BS_PUSHBUTTON,314,664,110,34,configure_button,ui.font);
  add(ui.window,L"BUTTON",L"Copy diagnostics",BS_PUSHBUTTON,436,664,140,34,copy_button,ui.font);
  add(ui.window,L"BUTTON",L"Open logs",BS_PUSHBUTTON,588,664,110,34,logs_button,ui.font);
  add(ui.window,L"BUTTON",L"Exit",BS_PUSHBUTTON,830,664,110,34,exit_button,ui.font);
  SetTimer(ui.window,refresh_timer,500,nullptr);
  ShowWindow(ui.window,SW_SHOW); UpdateWindow(ui.window);

  std::thread worker([&] { run_lichess(argc, argv, &controller); });
  MSG message{};
  while(GetMessageW(&message,nullptr,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}
  controller.request_stop();
  if(worker.joinable())worker.join();
  if(ui.font)DeleteObject(ui.font);
  CloseHandle(mutex);
  return 0;
}

}  // namespace eloi

#else
namespace eloi {
std::string_view bridge_state_name(BridgeState){return "unsupported";}
int bridge_backoff_seconds(int retry){return retry<1?2:60;}
bool bridge_http_retryable(int status){return status==0||status==408||status==429||status>=500;}
bool bridge_http_fatal(int status){return status==401||status==403;}
std::string redact_bridge_text(std::string_view value){return std::string(value);}
int run_lichess_operations_center(int,char**){return 2;}
}
#endif
