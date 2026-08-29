#include "eloi/chess.hpp"

#include <cstring>
#include <iostream>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

int main(int argc, char** argv) {
  using namespace eloi;
  auto config = default_config(EngineKind::eloi);

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--gui") == 0) return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--screenshot") == 0) return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--uci") == 0) return run_engine(config, argc, argv);
    if (std::strcmp(argv[i], "--perft") == 0) return run_perft(argc - i, argv + i);
    if (std::strcmp(argv[i], "--bench") == 0) return run_benchmark(argc - i, argv + i);
    if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
      std::cout << "Eloi 1.0.0\n"
                   "  Eloi.exe             launch the Skia chess GUI\n"
                   "  Eloi.exe --gui       force GUI mode\n"
                   "  Eloi.exe --uci       force UCI/Lichess mode\n"
                   "  Eloi.exe --perft ... run move-generation validation\n"
                   "  Eloi.exe --bench [--depth N]  run deterministic search benchmark\n"
                   "  Eloi.exe --screenshot FILE.bmp  render a GUI test frame\n"
                   "Search depth is permanently limited to 40 plies.\n";
      return 0;
    }
  }

#ifdef _WIN32
  const DWORD input_type = GetFileType(GetStdHandle(STD_INPUT_HANDLE));
  if (input_type == FILE_TYPE_PIPE) return run_engine(config, argc, argv);
  return run_gui(argc, argv);
#else
  return run_engine(config, argc, argv);
#endif
}
