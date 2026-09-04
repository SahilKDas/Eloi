#include "eloi/brain.hpp"
#include "eloi/version.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace eloi {
namespace {

std::vector<std::string> words(std::string_view line) {
  std::istringstream input{std::string(line)};
  std::vector<std::string> result;
  for (std::string word; input >> word;)
    result.push_back(std::move(word));
  return result;
}

std::optional<int> integer(std::string_view text) {
  try {
    std::size_t used = 0;
    const int value = std::stoi(std::string(text), &used);
    if (used == text.size()) return value;
  } catch (...) {
  }
  return std::nullopt;
}

std::filesystem::path network_path(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string_view(argv[index]) == "--caissa-network")
      return argv[index + 1];
  }
  if (const char* environment = std::getenv("ELOI_CAISSA_NETWORK_PATH");
      environment && *environment) {
    return environment;
  }
  return std::filesystem::current_path() /
         ".deps/caissa/eval-82-383B.pnn";
}

enum class LabBrainMode { hybrid, caissa, eloi };

LabBrainMode brain_mode(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string_view(argv[index]) != "--brain") continue;
    const std::string_view value = argv[index + 1];
    if (value == "caissa") return LabBrainMode::caissa;
    if (value == "eloi") return LabBrainMode::eloi;
  }
  return LabBrainMode::hybrid;
}

std::string_view brain_mode_name(LabBrainMode mode) {
  switch (mode) {
    case LabBrainMode::caissa: return "caissa";
    case LabBrainMode::eloi: return "eloi";
    default: return "hybrid";
  }
}

void print_result(const BrainResponse& response, const Board& root,
                  bool chess960, std::mutex& output) {
  std::scoped_lock lock(output);
  std::cout << "info depth " << response.search.depth
            << " score ";
  if (response.search.mate)
    std::cout << "mate " << response.search.mate;
  else
    std::cout << "cp " << response.search.score_cp;
  std::cout << " nodes " << response.search.nodes
            << " time " << response.search.elapsed.count();
  if (!response.search.pv.empty()) {
    std::cout << " pv";
    Board position = root;
    for (const Move& move : response.search.pv) {
      std::cout << ' ' << uci_move(move, position.position, chess960);
      if (!position.push(move)) break;
    }
  }
  if (!response.detail.empty())
    std::cout << "\ninfo string " << response.detail;
  std::cout << std::endl;
  std::cout << "bestmove ";
  if (response.has_legal_move(root)) {
    std::cout << uci_move(response.search.pv.front(), root.position, chess960);
  } else {
    std::cout << "0000";
  }
  std::cout << std::endl;
}

}  // namespace

int run_hybrid_lab(int argc, char** argv) {
  auto initial = parse_fen(initial_fen);
  if (!initial) return 2;
  Board board = *initial;
  bool uci_chess960 = false;
  std::string uci_variant{"chess"};
  int move_overhead_ms = 25;

  std::atomic_bool stopped{false};
  EngineConfig config = default_config();
  config.name = "Eloi Hybrid Lab";
  config.own_book = false;
  config.hash_mb = 16;
  EloiBrain eloi(config, stopped);
  CaissaBrain caissa(network_path(argc, argv), stopped,
                     16u * 1024u * 1024u);
  HybridBrain hybrid(eloi, caissa);
  const LabBrainMode mode = brain_mode(argc, argv);
  Brain* active_brain = &hybrid;
  if (mode == LabBrainMode::caissa) active_brain = &caissa;
  else if (mode == LabBrainMode::eloi) active_brain = &eloi;

  std::string first;
  if (!std::getline(std::cin, first) || first != "uci") return 2;
  std::cout << "id name Eloi Hybrid Lab " << version << "\n"
            << "id author Sahil Das; Caissa backend by Michal Witanowski\n"
            << "option name Threads type spin default 3 min 3 max 3\n"
            << "option name Hash type spin default 32 min 32 max 32\n"
            << "option name Move Overhead type spin default 25 min 0 max 5000\n"
            << "option name UCI_Chess960 type check default false\n"
            << "option name UCI_Variant type combo default chess var chess var horde\n"
            << "info string Caissa backend "
            << (caissa.available() ? "hash-verified and available"
                                   : "unavailable; E2 fallback active")
            << "\ninfo string Lab brain mode " << brain_mode_name(mode)
            << "\nuciok" << std::endl;

  std::thread worker;
  std::mutex output;
  auto stop_worker = [&] {
    stopped = true;
    if (worker.joinable()) worker.join();
    stopped = false;
  };
  auto launch = [&](SearchLimits limits) {
    stop_worker();
    Board snapshot = board;
    snapshot.horde = uci_variant == "horde";
    snapshot.chess960 = !snapshot.horde &&
                        (snapshot.chess960 || uci_chess960);
    worker = std::thread([&, snapshot = std::move(snapshot), limits]() mutable {
      const BrainResponse response = active_brain->search(snapshot, limits);
      print_result(response, snapshot, snapshot.chess960, output);
    });
  };

  for (std::string line; std::getline(std::cin, line);) {
    auto args = words(line);
    if (args.empty()) continue;
    std::string command = args.front();
    std::ranges::transform(command, command.begin(),
                           [](unsigned char c) { return std::tolower(c); });
    if (command == "quit") {
      stop_worker();
      break;
    }
    if (command == "stop") {
      stop_worker();
      continue;
    }
    if (command == "isready") {
      std::scoped_lock lock(output);
      std::cout << "readyok" << std::endl;
      continue;
    }
    if (command == "ucinewgame") {
      stop_worker();
      board = *initial;
      continue;
    }
    if (command == "setoption") {
      const auto name = std::ranges::find(args, "name");
      const auto value = std::ranges::find(args, "value");
      if (name == args.end() || value == args.end() || name + 1 == args.end() ||
          value + 1 == args.end()) {
        continue;
      }
      std::string key;
      for (auto cursor = name + 1; cursor != value; ++cursor) {
        if (!key.empty()) key += ' ';
        key += *cursor;
      }
      const std::string setting = *(value + 1);
      if (key == "UCI_Chess960") {
        uci_chess960 = setting == "true" || setting == "1";
      } else if (key == "UCI_Variant") {
        if (setting == "horde" || setting == "chess" ||
            setting == "standard") {
          uci_variant = setting == "horde" ? "horde" : "chess";
        }
      } else if (key == "Move Overhead") {
        move_overhead_ms = std::clamp(integer(setting).value_or(25), 0, 5000);
      }
      continue;
    }
    if (command == "position") {
      stop_worker();
      std::size_t index = 1;
      if (index < args.size() && args[index] == "startpos") {
        board = *initial;
        ++index;
      } else if (index < args.size() && args[index] == "fen" &&
                 index + 6 < args.size()) {
        std::string fen;
        for (int field = 0; field < 6; ++field) {
          if (field) fen += ' ';
          fen += args[index + 1 + field];
        }
        if (auto parsed = parse_fen(fen)) board = *parsed;
        else {
          std::scoped_lock lock(output);
          std::cout << "info string invalid FEN" << std::endl;
          continue;
        }
        index += 7;
      }
      if (index < args.size() && args[index] == "moves") ++index;
      for (; index < args.size(); ++index) {
        if (!board.push_uci(args[index])) {
          std::scoped_lock lock(output);
          std::cout << "info string invalid move " << args[index] << std::endl;
          break;
        }
      }
      continue;
    }
    if (command == "go") {
      SearchLimits limits;
      int move_time = 0;
      int white_time = 0, black_time = 0;
      int white_increment = 0, black_increment = 0;
      for (std::size_t index = 1; index < args.size(); ++index) {
        auto take = [&] {
          if (index + 1 < args.size())
            return integer(args[++index]).value_or(0);
          return 0;
        };
        if (args[index] == "depth") limits.depth = std::max(1, take());
        else if (args[index] == "nodes")
          limits.nodes = static_cast<std::uint64_t>(std::max(1, take()));
        else if (args[index] == "movetime") move_time = take();
        else if (args[index] == "wtime") white_time = take();
        else if (args[index] == "btime") black_time = take();
        else if (args[index] == "winc") white_increment = take();
        else if (args[index] == "binc") black_increment = take();
        else if (args[index] == "movestogo") limits.moves_to_go = take();
      }
      if (move_time > 0) {
        limits.deadline = std::chrono::steady_clock::now() +
            std::chrono::milliseconds(
                std::max(1, move_time - move_overhead_ms));
      } else if (white_time > 0 || black_time > 0) {
        limits.remaining_ms = board.turn == Color::white
                                  ? white_time : black_time;
        limits.increment_ms = board.turn == Color::white
                                  ? white_increment : black_increment;
        limits.move_overhead_ms = move_overhead_ms;
      } else if (limits.nodes == 0 && limits.depth == 0) {
        limits.nodes = 10'000;
      }
      launch(limits);
    }
  }
  stop_worker();
  return 0;
}

}  // namespace eloi

int main(int argc, char** argv) {
  return eloi::run_hybrid_lab(argc, argv);
}
