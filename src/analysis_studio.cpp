#include "eloi/analysis_studio.hpp"

#include <filesystem>
#include <fstream>
#include <algorithm>
#include <format>
#include <string>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>

namespace eloi {
namespace {
constexpr UINT_PTR poll_timer = 41;
constexpr int id_analyse = 101, id_refresh = 102, id_open = 103,
              id_cancel = 104, id_list = 105, id_status = 106;

struct Studio {
  HWND window{}, list{}, status{}, analyse{}, cancel{};
  HANDLE process{}, job{};
  std::filesystem::path executable, root, script, network, cancel_file;
};

std::wstring widen(const std::filesystem::path& path) { return path.wstring(); }

std::filesystem::path local_root() {
  wchar_t buffer[32768]{};
  const DWORD size = GetEnvironmentVariableW(L"LOCALAPPDATA", buffer,
                                               static_cast<DWORD>(std::size(buffer)));
  return (size ? std::filesystem::path(buffer) : std::filesystem::temp_directory_path()) /
         "Eloi" / "autopsy";
}

std::string field(std::string_view text, std::string_view name) {
  const std::string needle = "\"" + std::string(name) + "\"";
  auto at = text.find(needle);
  if (at == std::string_view::npos) return {};
  at = text.find(':', at + needle.size());
  if (at == std::string_view::npos) return {};
  at = text.find('"', at + 1);
  if (at == std::string_view::npos) return {};
  const auto end = text.find('"', at + 1);
  return end == std::string_view::npos ? std::string{} :
         std::string(text.substr(at + 1, end - at - 1));
}

std::wstring wide_utf8(std::string text) {
  if (text.empty()) return {};
  const int count = MultiByteToWideChar(CP_UTF8, 0, text.data(),
                                         static_cast<int>(text.size()), nullptr, 0);
  std::wstring result(count, L' ');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count);
  return result;
}

void set_status(Studio& studio, std::wstring text) {
  SetWindowTextW(studio.status, text.c_str());
}

void refresh(Studio& studio) {
  SendMessageW(studio.list, LB_RESETCONTENT, 0, 0);
  const auto reports = studio.root / "reports";
  std::error_code error;
  std::size_t count = 0;
  if (std::filesystem::exists(reports, error)) {
    std::vector<std::filesystem::path> files;
    for (const auto& entry : std::filesystem::directory_iterator(reports, error))
      if (entry.path().extension() == ".json" && entry.path().filename() != "index.json")
        files.push_back(entry.path());
    std::ranges::sort(files);
    for (const auto& path : files) {
      std::ifstream input(path, std::ios::binary);
      const std::string json((std::istreambuf_iterator<char>(input)), {});
      const std::wstring row = wide_utf8(field(json, "game_id") + "  ·  " +
          field(json, "analysis_status") + "  ·  Eloi " + field(json, "version"));
      SendMessageW(studio.list, LB_ADDSTRING, 0,
                   reinterpret_cast<LPARAM>(row.c_str()));
      ++count;
    }
  }
  std::size_t queued = 0;
  const auto queue = studio.root / "queue";
  if (std::filesystem::exists(queue, error))
    for (const auto& entry : std::filesystem::directory_iterator(queue, error))
      if (entry.path().extension() == ".json") ++queued;
  set_status(studio, std::format(L"{} report(s) · {} queued game(s) · manual analysis only",
                                 count, queued));
}

std::wstring quote(const std::filesystem::path& path) {
  return L"\"" + path.wstring() + L"\"";
}

bool start_analysis(Studio& studio) {
  if (studio.process) return false;
  if (!std::filesystem::exists(studio.script) ||
      !std::filesystem::exists(studio.network)) {
    set_status(studio, L"Analyzer requires this source checkout and its pinned Caissa network");
    return false;
  }
  std::error_code error;
  std::filesystem::remove(studio.cancel_file, error);
  std::wstring command = L"python " + quote(studio.script) + L" --root " +
      quote(studio.root) + L" --engine " + quote(studio.executable) +
      L" --network " + quote(studio.network) + L" --cancel-file " +
      quote(studio.cancel_file);
  STARTUPINFOW startup{sizeof(startup)};
  PROCESS_INFORMATION process{};
  if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE,
                      CREATE_NO_WINDOW | IDLE_PRIORITY_CLASS, nullptr, nullptr,
                      &startup, &process)) {
    set_status(studio, L"Could not start the bounded analyzer");
    return false;
  }
  CloseHandle(process.hThread);
  studio.job = CreateJobObjectW(nullptr, nullptr);
  if (studio.job) {
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    SetInformationJobObject(studio.job, JobObjectExtendedLimitInformation,
                            &limits, sizeof(limits));
    AssignProcessToJobObject(studio.job, process.hProcess);
  }
  studio.process = process.hProcess;
  EnableWindow(studio.analyse, FALSE);
  EnableWindow(studio.cancel, TRUE);
  set_status(studio, L"Analyzing queued Standard games · E4-10 then Caissa · Idle priority");
  return true;
}

void cancel_analysis(Studio& studio) {
  if (!studio.process) return;
  std::filesystem::create_directories(studio.cancel_file.parent_path());
  std::ofstream(studio.cancel_file) << "cancel\n";
  set_status(studio, L"Cancellation requested · finishing the current bounded search");
}

void finish_process(Studio& studio) {
  if (studio.process) CloseHandle(studio.process);
  if (studio.job) CloseHandle(studio.job);
  studio.process = studio.job = nullptr;
  EnableWindow(studio.analyse, TRUE);
  EnableWindow(studio.cancel, FALSE);
  refresh(studio);
}

LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  auto* studio = reinterpret_cast<Studio*>(GetWindowLongPtrW(window, GWLP_USERDATA));
  if (message == WM_NCCREATE) {
    studio = static_cast<Studio*>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
    SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(studio));
  }
  if (!studio) return DefWindowProcW(window, message, wparam, lparam);
  switch (message) {
    case WM_CREATE: {
      CreateWindowW(L"STATIC", L"LICHESS ANALYSIS STUDIO", WS_CHILD | WS_VISIBLE,
                    24, 18, 420, 30, window, nullptr, nullptr, nullptr);
      CreateWindowW(L"STATIC", L"Post-game evidence only · never runs during live play",
                    WS_CHILD | WS_VISIBLE, 24, 48, 600, 24, window, nullptr, nullptr, nullptr);
      studio->list = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", nullptr,
          WS_CHILD | WS_VISIBLE | WS_VSCROLL | LBS_NOINTEGRALHEIGHT,
          24, 82, 712, 330, window, reinterpret_cast<HMENU>(id_list), nullptr, nullptr);
      studio->analyse = CreateWindowW(L"BUTTON", L"Analyze queued games",
          WS_CHILD | WS_VISIBLE, 24, 430, 180, 38, window,
          reinterpret_cast<HMENU>(id_analyse), nullptr, nullptr);
      CreateWindowW(L"BUTTON", L"Refresh", WS_CHILD | WS_VISIBLE, 216, 430, 110, 38,
                    window, reinterpret_cast<HMENU>(id_refresh), nullptr, nullptr);
      CreateWindowW(L"BUTTON", L"Open reports", WS_CHILD | WS_VISIBLE, 338, 430, 130, 38,
                    window, reinterpret_cast<HMENU>(id_open), nullptr, nullptr);
      studio->cancel = CreateWindowW(L"BUTTON", L"Cancel analysis",
          WS_CHILD | WS_VISIBLE | WS_DISABLED, 480, 430, 150, 38, window,
          reinterpret_cast<HMENU>(id_cancel), nullptr, nullptr);
      studio->status = CreateWindowW(L"STATIC", nullptr, WS_CHILD | WS_VISIBLE,
          24, 486, 712, 42, window, reinterpret_cast<HMENU>(id_status), nullptr, nullptr);
      SetTimer(window, poll_timer, 300, nullptr);
      refresh(*studio);
      return 0;
    }
    case WM_COMMAND:
      if (LOWORD(wparam) == id_analyse) start_analysis(*studio);
      else if (LOWORD(wparam) == id_refresh) refresh(*studio);
      else if (LOWORD(wparam) == id_open) {
        std::filesystem::create_directories(studio->root / "reports");
        ShellExecuteW(window, L"open", widen(studio->root / "reports").c_str(),
                      nullptr, nullptr, SW_SHOWNORMAL);
      } else if (LOWORD(wparam) == id_cancel) cancel_analysis(*studio);
      return 0;
    case WM_TIMER:
      if (studio->process && WaitForSingleObject(studio->process, 0) == WAIT_OBJECT_0)
        finish_process(*studio);
      return 0;
    case WM_CLOSE:
      if (studio->process) {
        if (MessageBoxW(window, L"Cancel the active analysis and close?",
                        L"Eloi Analysis Studio", MB_YESNO | MB_ICONWARNING) != IDYES)
          return 0;
        cancel_analysis(*studio);
        if (WaitForSingleObject(studio->process, 5000) != WAIT_OBJECT_0 && studio->job)
          TerminateJobObject(studio->job, 2);
        finish_process(*studio);
      }
      DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      PostQuitMessage(0);
      return 0;
  }
  return DefWindowProcW(window, message, wparam, lparam);
}
}  // namespace

int run_analysis_studio(int, char** argv) {
  Studio studio;
  studio.executable = std::filesystem::absolute(argv[0]);
  studio.root = local_root();
  const auto repository = std::filesystem::current_path();
  studio.script = repository / "scripts" / "lichess_autopsy.py";
  studio.network = repository / ".deps" / "caissa" / "eval-71-v1.25.pnn";
  studio.cancel_file = studio.root / "analysis.cancel";
  const wchar_t* class_name = L"EloiAnalysisStudio";
  WNDCLASSW type{};
  type.lpfnWndProc = procedure;
  type.hInstance = GetModuleHandleW(nullptr);
  type.lpszClassName = class_name;
  type.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
  type.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
  RegisterClassW(&type);
  studio.window = CreateWindowExW(0, class_name, L"Eloi · Lichess Analysis Studio",
      WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
      CW_USEDEFAULT, CW_USEDEFAULT, 780, 580, nullptr, nullptr,
      type.hInstance, &studio);
  if (!studio.window) return 2;
  ShowWindow(studio.window, SW_SHOW);
  UpdateWindow(studio.window);
  MSG message{};
  while (GetMessageW(&message, nullptr, 0, 0) > 0) {
    TranslateMessage(&message);
    DispatchMessageW(&message);
  }
  return static_cast<int>(message.wParam);
}
}  // namespace eloi

#else
namespace eloi { int run_analysis_studio(int, char**) { return 2; } }
#endif
