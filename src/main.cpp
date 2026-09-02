#include "eloi/chess.hpp"
#include "eloi/config.hpp"
#include "eloi/version_match.hpp"
#include "eloi/version.hpp"

#include <cstring>
#include <filesystem>
#include <iostream>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

int main(int argc, char** argv) {
  using namespace eloi;
  auto config = default_config();

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--version") == 0 ||
        std::strcmp(argv[i], "-v") == 0) {
      std::cout << "Eloi " << version << '\n';
      return 0;
    }
    if (std::strcmp(argv[i], "--version-match-smoke") == 0 && i + 1 < argc)
      return run_version_match_smoke(
          std::filesystem::absolute(argv[0]),
          std::filesystem::absolute(argv[i + 1]));
    if (std::strcmp(argv[i], "--version-match") == 0)
      return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--gui") == 0) return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--screenshot") == 0) return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--screenshot-setup") == 0)
      return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--screenshot-engine-lab") == 0)
      return run_gui(argc, argv);
    if (std::strcmp(argv[i], "--uci") == 0) return run_engine(config, argc, argv);
    if (std::strcmp(argv[i], "--lichess") == 0) {
#ifdef ELOI_SEPARATE_LICHESS_EXE
      std::cerr << "This Exoskeleton package isolates native Lichess networking.\n"
                   "Run EloiLichess.exe instead.\n";
      return 2;
#else
      return run_lichess(argc, argv);
#endif
    }
    if (std::strcmp(argv[i], "--perft") == 0) return run_perft(argc - i, argv + i);
    if (std::strcmp(argv[i], "--bench") == 0) return run_benchmark(argc - i, argv + i);
    if (std::strcmp(argv[i], "--diagnose-search") == 0)
      return run_search_diagnostic(argc - i, argv + i);
    if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
      std::cout << "Eloi " << version << "\n"
                   "  Eloi.exe             launch the Skia chess GUI\n"
                   "  Eloi.exe --version   print the exact build version\n"
                   "  Eloi.exe --gui       force GUI mode\n"
                   "  Eloi.exe --uci       force UCI/Lichess mode\n"
                   "  Eloi.exe --lichess   native Lichess bot using config.yml\n"
                   "  Eloi.exe --perft ... run move-generation validation\n"
                   "  Eloi.exe --bench [--depth N]  run deterministic search benchmark\n"
                   "  Eloi.exe --diagnose-search --fen FEN --depth N --profile production|full-width --json PATH\n"
                   "  Eloi.exe --screenshot FILE.bmp  render a GUI test frame\n"
                   "  Eloi.exe --screenshot-setup FILE.bmp  render clock setup\n"
                   "  Eloi.exe --screenshot-engine-lab FILE.bmp PREVIOUS.exe  render Engine Lab\n"
                   "  Eloi.exe --version-match  launch the current-vs-previous arena\n"
                   "  Eloi.exe --version-match-smoke PREVIOUS.exe  test the UCI version arena\n"
                   "Depths above 40 plies are experimental and may take hours or days.\n"
                   "GUI maximum: 200 plies; engine/UCI maximum: 17697 plies.\n";
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
