#include "eloi/config.hpp"
#include "eloi/lichess_operations.hpp"

#include <filesystem>
#include <string_view>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int main(int argc, char** argv) {
  bool configure = false;
  bool headless = false;
  bool check = false;
  std::filesystem::path config;
  for (int i = 1; i < argc; ++i) {
    const std::string_view argument(argv[i]);
    if (argument == "--configure") configure = true;
    else if (argument == "--headless") headless = true;
    else if (argument == "--check-config") check = true;
    else if (argument == "--config" && i + 1 < argc) config = argv[++i];
  }
  if (configure) {
    if (HWND console = GetConsoleWindow()) ShowWindow(console, SW_HIDE);
    const int action = eloi::run_lichess_configurator(config);
    return action == 0 ? 0 : 2;
  }
  if (headless || check) return eloi::run_lichess(argc, argv);
  return eloi::run_lichess_operations_center(argc, argv);
}
