#include "eloi/config.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace eloi {
namespace {

constexpr int save_button = 1001;
constexpr int start_button = 1002;
constexpr int cancel_button = 1003;
constexpr int show_token_box = 1004;

std::wstring wide(std::string_view text) {
  if (text.empty()) return {};
  const int count = MultiByteToWideChar(
      CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
  std::wstring result(count, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count);
  return result;
}

std::string narrow(std::wstring_view text) {
  if (text.empty()) return {};
  const int count = WideCharToMultiByte(
      CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0,
      nullptr, nullptr);
  std::string result(count, '\0');
  WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count, nullptr, nullptr);
  return result;
}

std::filesystem::path executable_config() {
  std::wstring path(32768, L'\0');
  const DWORD size = GetModuleFileNameW(
      nullptr, path.data(), static_cast<DWORD>(path.size()));
  path.resize(size);
  return std::filesystem::path(path).parent_path() / "config.yml";
}

struct ConfigWindow {
  RuntimeConfig config;
  std::filesystem::path path;
  HWND window{};
  HWND enabled{};
  HWND token{};
  HWND show_token{};
  HWND min_base{};
  HWND max_base{};
  HWND allow_bots{};
  HWND standard{};
  HWND chess960{};
  HWND horde{};
  HWND depth{};
  HWND hash{};
  HWND overhead{};
  HWND own_book{};
  HWND status{};
  HFONT font{};
  HBRUSH background{};
  int action{};
};

void set_font(HWND control, HFONT font) {
  SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
}

HWND add_control(ConfigWindow& ui, const wchar_t* type, const wchar_t* text,
                 DWORD style, int x, int y, int width, int height, int id = 0) {
  const bool is_edit = std::wstring_view(type) == L"EDIT";
  HWND control = CreateWindowExW(
      is_edit ? WS_EX_CLIENTEDGE : 0, type, text,
      WS_CHILD | WS_VISIBLE | style, x, y, width, height, ui.window,
      reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
      GetModuleHandleW(nullptr), nullptr);
  set_font(control, ui.font);
  return control;
}

std::wstring control_text(HWND control) {
  const int length = GetWindowTextLengthW(control);
  std::wstring text(static_cast<std::size_t>(length) + 1, L'\0');
  GetWindowTextW(control, text.data(), length + 1);
  text.resize(length);
  return text;
}

std::optional<int> control_integer(HWND control) {
  try {
    const std::wstring value = control_text(control);
    std::size_t used = 0;
    const int result = std::stoi(value, &used);
    if (used == value.size()) return result;
  } catch (...) {}
  return std::nullopt;
}

bool checked(HWND control) {
  return SendMessageW(control, BM_GETCHECK, 0, 0) == BST_CHECKED;
}

void set_checked(HWND control, bool value) {
  SendMessageW(control, BM_SETCHECK, value ? BST_CHECKED : BST_UNCHECKED, 0);
}

bool save_from_controls(ConfigWindow& ui) {
  const auto minimum = control_integer(ui.min_base);
  const auto maximum = control_integer(ui.max_base);
  const auto depth = control_integer(ui.depth);
  const auto hash = control_integer(ui.hash);
  const auto overhead = control_integer(ui.overhead);
  if (!minimum || !maximum || !depth || !hash || !overhead ||
      *minimum < 0 || *maximum < *minimum ||
      *depth < 0 || *depth > 17'697 || *hash < 0 || *overhead < 0 ||
      (!checked(ui.standard) && !checked(ui.chess960) && !checked(ui.horde))) {
    MessageBoxW(ui.window,
        L"Check the numeric ranges and select at least one variant.",
        L"Eloi configuration", MB_OK | MB_ICONWARNING);
    return false;
  }
  ui.config.lichess_enabled = checked(ui.enabled);
  ui.config.lichess_token = narrow(control_text(ui.token));
  ui.config.lichess_url = "https://lichess.org";
  ui.config.min_base_seconds = *minimum;
  ui.config.max_base_seconds = *maximum;
  ui.config.allow_bots = checked(ui.allow_bots);
  ui.config.variants.clear();
  if (checked(ui.standard)) ui.config.variants.emplace_back("standard");
  if (checked(ui.chess960)) ui.config.variants.emplace_back("chess960");
  if (checked(ui.horde)) ui.config.variants.emplace_back("horde");
  ui.config.depth = *depth;
  ui.config.hash_mb = *hash;
  ui.config.move_overhead_ms = *overhead;
  ui.config.own_book = checked(ui.own_book);
  std::string error;
  if (!save_runtime_config(ui.path, ui.config, &error)) {
    MessageBoxW(ui.window, wide(error).c_str(), L"Could not save config.yml",
                MB_OK | MB_ICONERROR);
    return false;
  }
  SetWindowTextW(ui.status, L"Saved config.yml beside EloiLichess.exe");
  return true;
}

LRESULT CALLBACK window_proc(HWND window, UINT message,
                             WPARAM wparam, LPARAM lparam) {
  auto* ui = reinterpret_cast<ConfigWindow*>(
      GetWindowLongPtrW(window, GWLP_USERDATA));
  if (message == WM_NCCREATE) {
    const auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
    ui = static_cast<ConfigWindow*>(create->lpCreateParams);
    SetWindowLongPtrW(window, GWLP_USERDATA,
                      reinterpret_cast<LONG_PTR>(ui));
  }
  if (!ui) return DefWindowProcW(window, message, wparam, lparam);
  if (message == WM_COMMAND) {
    const int id = LOWORD(wparam);
    if (id == show_token_box) {
      SendMessageW(ui->token, EM_SETPASSWORDCHAR,
                   checked(ui->show_token) ? 0 : 0x25cf, 0);
      InvalidateRect(ui->token, nullptr, TRUE);
      return 0;
    }
    if (id == save_button && save_from_controls(*ui)) return 0;
    if (id == start_button && save_from_controls(*ui)) {
      ui->action = 1;
      DestroyWindow(window);
      return 0;
    }
    if (id == cancel_button) {
      DestroyWindow(window);
      return 0;
    }
  } else if (message == WM_CLOSE) {
    DestroyWindow(window);
    return 0;
  } else if (message == WM_DESTROY) {
    PostQuitMessage(0);
    return 0;
  }
  return DefWindowProcW(window, message, wparam, lparam);
}

void create_controls(ConfigWindow& ui) {
  ui.font = CreateFontW(-17, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                       DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                       CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
  add_control(ui, L"STATIC", L"Eloi Lichess", SS_LEFT, 24, 18, 430, 34);
  add_control(ui, L"STATIC",
      L"Configure the separate native network client — no editor required.",
      SS_LEFT, 24, 52, 510, 24);
  ui.enabled = add_control(ui, L"BUTTON", L"Enable native Lichess mode",
      BS_AUTOCHECKBOX, 24, 86, 250, 26);
  add_control(ui, L"STATIC", L"Bot API token", SS_LEFT, 24, 124, 150, 22);
  ui.token = add_control(ui, L"EDIT", wide(ui.config.lichess_token).c_str(),
      ES_AUTOHSCROLL | ES_PASSWORD, 24, 148, 390, 28);
  SendMessageW(ui.token, EM_SETPASSWORDCHAR, 0x25cf, 0);
  ui.show_token = add_control(ui, L"BUTTON", L"Show", BS_AUTOCHECKBOX,
      430, 149, 90, 26, show_token_box);
  add_control(ui, L"STATIC", L"Endpoint: https://lichess.org (locked)",
      SS_LEFT, 24, 184, 360, 22);

  add_control(ui, L"STATIC", L"Minimum base seconds", SS_LEFT, 24, 220, 190, 22);
  ui.min_base = add_control(ui, L"EDIT",
      std::to_wstring(ui.config.min_base_seconds).c_str(), ES_NUMBER,
      220, 216, 110, 28);
  add_control(ui, L"STATIC", L"Maximum base seconds", SS_LEFT, 24, 256, 190, 22);
  ui.max_base = add_control(ui, L"EDIT",
      std::to_wstring(ui.config.max_base_seconds).c_str(), ES_NUMBER,
      220, 252, 110, 28);
  ui.allow_bots = add_control(ui, L"BUTTON", L"Accept challenges from bots",
      BS_AUTOCHECKBOX, 350, 218, 210, 26);
  ui.standard = add_control(ui, L"BUTTON", L"Standard",
      BS_AUTOCHECKBOX, 350, 250, 100, 26);
  ui.chess960 = add_control(ui, L"BUTTON", L"Chess960",
      BS_AUTOCHECKBOX, 456, 250, 100, 26);
  ui.horde = add_control(ui, L"BUTTON", L"Horde",
      BS_AUTOCHECKBOX, 350, 280, 100, 26);

  add_control(ui, L"STATIC", L"Search depth (0 = clock-managed)",
      SS_LEFT, 24, 332, 240, 22);
  ui.depth = add_control(ui, L"EDIT", std::to_wstring(ui.config.depth).c_str(),
      ES_NUMBER, 270, 328, 90, 28);
  add_control(ui, L"STATIC", L"Hash (MB)", SS_LEFT, 24, 368, 120, 22);
  ui.hash = add_control(ui, L"EDIT", std::to_wstring(ui.config.hash_mb).c_str(),
      ES_NUMBER, 144, 364, 90, 28);
  add_control(ui, L"STATIC", L"Move overhead (ms)", SS_LEFT, 270, 368, 170, 22);
  ui.overhead = add_control(ui, L"EDIT",
      std::to_wstring(ui.config.move_overhead_ms).c_str(), ES_NUMBER,
      450, 364, 90, 28);
  ui.own_book = add_control(ui, L"BUTTON", L"Use Eloi opening book",
      BS_AUTOCHECKBOX, 24, 408, 220, 26);

  add_control(ui, L"BUTTON", L"Save", BS_PUSHBUTTON,
      24, 460, 110, 34, save_button);
  add_control(ui, L"BUTTON", L"Save && Start Bot", BS_DEFPUSHBUTTON,
      146, 460, 180, 34, start_button);
  add_control(ui, L"BUTTON", L"Cancel", BS_PUSHBUTTON,
      338, 460, 110, 34, cancel_button);
  ui.status = add_control(ui, L"STATIC",
      L"Your token is stored only in the local config.yml.",
      SS_LEFT, 24, 512, 510, 36);

  set_checked(ui.enabled, ui.config.lichess_enabled);
  set_checked(ui.allow_bots, ui.config.allow_bots);
  set_checked(ui.standard,
      std::ranges::find(ui.config.variants, "standard") != ui.config.variants.end());
  set_checked(ui.chess960,
      std::ranges::find(ui.config.variants, "chess960") != ui.config.variants.end());
  set_checked(ui.horde,
      std::ranges::find(ui.config.variants, "horde") != ui.config.variants.end());
  set_checked(ui.own_book, ui.config.own_book);
}

}  // namespace

int run_lichess_configurator() {
  ConfigWindow ui;
  ui.path = executable_config();
  std::string error;
  if (auto loaded = load_runtime_config(ui.path, &error)) ui.config = *loaded;

  const wchar_t* class_name = L"EloiLichessConfigurator";
  WNDCLASSEXW window_class{};
  window_class.cbSize = sizeof(window_class);
  window_class.lpfnWndProc = window_proc;
  window_class.hInstance = GetModuleHandleW(nullptr);
  window_class.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
  ui.background = CreateSolidBrush(RGB(245, 247, 251));
  window_class.hbrBackground = ui.background;
  window_class.lpszClassName = class_name;
  window_class.hIcon = LoadIconW(nullptr, MAKEINTRESOURCEW(32512));
  if (!RegisterClassExW(&window_class) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
    return 2;

  ui.window = CreateWindowExW(
      0, class_name, L"Configure Eloi Lichess", WS_OVERLAPPED | WS_CAPTION |
      WS_SYSMENU | WS_MINIMIZEBOX, CW_USEDEFAULT, CW_USEDEFAULT, 590, 605,
      nullptr, nullptr, GetModuleHandleW(nullptr), &ui);
  if (!ui.window) return 2;
  create_controls(ui);
  ShowWindow(ui.window, SW_SHOW);
  UpdateWindow(ui.window);
  if (!error.empty())
    MessageBoxW(ui.window, wide(error).c_str(), L"Using safe defaults",
                MB_OK | MB_ICONWARNING);

  MSG message{};
  while (GetMessageW(&message, nullptr, 0, 0) > 0) {
    TranslateMessage(&message);
    DispatchMessageW(&message);
  }
  if (ui.font) DeleteObject(ui.font);
  if (ui.background) DeleteObject(ui.background);
  return ui.action;
}

}  // namespace eloi

#else

namespace eloi {
int run_lichess_configurator() { return 2; }
}  // namespace eloi

#endif
