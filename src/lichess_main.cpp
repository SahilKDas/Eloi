#include "eloi/config.hpp"

#include <string_view>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int main(int argc, char** argv) {
  bool configure = argc == 1;
  for (int i = 1; i < argc; ++i)
    if (std::string_view(argv[i]) == "--configure") configure = true;
  if (configure) {
    if (HWND console = GetConsoleWindow()) ShowWindow(console, SW_HIDE);
    const int action = eloi::run_lichess_configurator();
    if (action != 1) return action == 0 ? 0 : 2;
    if (HWND console = GetConsoleWindow()) ShowWindow(console, SW_SHOW);
  }
  return eloi::run_lichess(argc, argv);
}
