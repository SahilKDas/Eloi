#include "eloi/brain.hpp"
#include "eloi/policy_value.hpp"
#include "eloi/version.hpp"

#include <algorithm>
#include <array>
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
const auto adjacent = std::filesystem::absolute(argv[0]).parent_path() /
                        "eval-71-v1.25.pnn";
  std::error_code error;
  if (std::filesystem::is_regular_file(adjacent, error)) return adjacent;
  return std::filesystem::current_path() /
         ".deps/caissa/eval-71-v1.25.pnn";
}

enum class LabBrainMode { production, hybrid, caissa, eloi, eloi_single, eloi_policy };

LabBrainMode brain_mode(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string_view(argv[index]) != "--brain") continue;
    const std::string_view value = argv[index + 1];
    if (value == "hybrid") return LabBrainMode::hybrid;
    if (value == "caissa") return LabBrainMode::caissa;
    if (value == "eloi") return LabBrainMode::eloi;
    if (value == "eloi-single") return LabBrainMode::eloi_single;
    if (value == "eloi-policy") return LabBrainMode::eloi_policy;
  }
  return LabBrainMode::production;
}

std::string_view brain_mode_name(LabBrainMode mode) {
  switch (mode) {
    case LabBrainMode::production: return "production";
    case LabBrainMode::caissa: return "caissa";
    case LabBrainMode::eloi: return "eloi";
    case LabBrainMode::eloi_single: return "eloi-single";
    case LabBrainMode::eloi_policy: return "eloi-policy";
    default: return "hybrid";
  }
}

std::filesystem::path policy_value_path(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index)
    if (std::string_view(argv[index]) == "--policy-value")
      return argv[index + 1];
  return {};
}
std::uint32_t selectivity_mask(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string_view(argv[index]) != "--selectivity") continue;
    const std::string value = argv[index + 1];
    if (value == "none") return 0;
    if (value == "all") return static_cast<std::uint32_t>(Selectivity::all);
    const std::array choices{
        std::pair{"reverse-futility", Selectivity::reverse_futility},
        std::pair{"razoring", Selectivity::razoring},
        std::pair{"internal-reduction", Selectivity::internal_reduction},
        std::pair{"null-move", Selectivity::null_move},
        std::pair{"probcut", Selectivity::probcut},
        std::pair{"futility", Selectivity::futility},
        std::pair{"lmp", Selectivity::late_move_pruning},
        std::pair{"lmr", Selectivity::late_move_reduction}};
    std::uint32_t result = 0;
    std::istringstream names(value);
    for (std::string name; std::getline(names, name, ',');) {
      const auto found = std::ranges::find_if(
          choices, [&](const auto& choice) { return choice.first == name; });
      if (found == choices.end())
        return static_cast<std::uint32_t>(Selectivity::all);
      result |= static_cast<std::uint32_t>(found->second);
    }
    return result;
  }
  return static_cast<std::uint32_t>(Selectivity::all);
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
  auto policy_value = std::make_shared<PolicyValueNetwork>();
  std::string policy_error;
  const auto policy_path = policy_value_path(argc, argv);
  const bool policy_loaded = !policy_path.empty() &&
      policy_value->load(policy_path, &policy_error);
  Searcher::MovePrior move_prior;
  if (policy_loaded) {
    move_prior = [policy_value](const Board& position, const MoveList& moves) {
      const auto prediction = policy_value->predict(position, moves);
      std::vector<float> result;
      result.reserve(prediction.policy.size());
      for (const auto& [move, probability] : prediction.policy) {
        (void)move;
        result.push_back(probability);
      }
      return result;
    };
  }
  EloiBrain eloi_single(config, stopped, SearchConcurrency::single_thread_lab,
                        move_prior);
  EloiBrain eloi_policy(config, stopped,
                        SearchConcurrency::production_three_threads, move_prior);
  IsolatedCaissaBrain caissa(std::filesystem::absolute(argv[0]),
                             network_path(argc, argv), stopped,
                             16u * 1024u * 1024u);
  HybridBrain hybrid(eloi, caissa);
  const LabBrainMode mode = brain_mode(argc, argv);
  const std::uint32_t lab_selectivity = selectivity_mask(argc, argv);
  Brain* active_brain = nullptr;
  if (mode == LabBrainMode::caissa) active_brain = &caissa;
  else if (mode == LabBrainMode::eloi) active_brain = &eloi;
  else if (mode == LabBrainMode::eloi_single) active_brain = &eloi_single;
  else if (mode == LabBrainMode::eloi_policy) active_brain = &eloi_policy;
  else if (mode == LabBrainMode::hybrid) active_brain = &hybrid;

  std::string first;
  if (!std::getline(std::cin, first) || first != "uci") return 2;
#ifdef ELOI_HYBRID_EMBEDDED
  std::cout << "id name Eloi " << version << "\n";
#else
  std::cout << "id name Eloi Hybrid Lab " << version << "\n";
#endif
  std::cout            << "id author Sahil Das; Caissa backend by Michal Witanowski\n"
            << "option name Threads type spin default 3 min 3 max 3\n"
            << "option name Hash type spin default 32 min 32 max 32\n"
            << "option name Move Overhead type spin default 25 min 0 max 5000\n"
            << "option name UCI_Chess960 type check default false\n"
            << "option name UCI_Variant type combo default chess var chess var horde var kingofthehill var atomic var antichess\n"
            << "info string Caissa backend "
            << (caissa.available() ? "hash-verified and available"
                                   : "unavailable; E4-10 fallback active")
            << "\ninfo string Lab brain mode " << brain_mode_name(mode)
            << "\ninfo string Lab selectivity mask " << lab_selectivity
            << "\ninfo string Lab policy/value "
            << (policy_loaded ? "loaded as root-order prior" :
                (policy_path.empty() ? "disabled" : policy_error))
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
    limits.selectivity_mask = lab_selectivity;
    Board snapshot = board;
    snapshot.horde = uci_variant == "horde";
    snapshot.king_of_the_hill = uci_variant == "kingofthehill";
    snapshot.atomic = uci_variant == "atomic";
    snapshot.antichess = uci_variant == "antichess";
    snapshot.chess960 = !snapshot.horde && !snapshot.king_of_the_hill && !snapshot.atomic &&
                        !snapshot.antichess &&
                        (snapshot.chess960 || uci_chess960);
    worker = std::thread([&, snapshot = std::move(snapshot), limits]() mutable {
      Brain* selected_brain = active_brain;
      if (!selected_brain) {
        selected_brain = (!snapshot.horde && !snapshot.chess960 &&
                          !snapshot.king_of_the_hill && !snapshot.atomic &&
                          !snapshot.antichess && caissa.available())
                             ? static_cast<Brain*>(&caissa)
                             : static_cast<Brain*>(&eloi);
      }
      BrainResponse response = selected_brain->search(snapshot, limits);
      bool runtime_fallback = false;
      if (!active_brain && selected_brain == &caissa &&
          response.status != BrainStatus::stopped &&
          !response.has_legal_move(snapshot)) {
        const std::string donor_failure = response.detail;
        response = eloi.search(snapshot, limits);
        response.used_fallback = true;
        response.detail = "production routing: Caissa failed; used Eloi E4-10";
        if (!donor_failure.empty())
          response.detail += " (" + donor_failure + ")";
        runtime_fallback = true;
      }
      if (!active_brain && selected_brain == &eloi) {
        response.used_fallback = true;
        response.detail = snapshot.horde || snapshot.chess960 ||
                          snapshot.king_of_the_hill || snapshot.atomic ||
                          snapshot.antichess
            ? "production routing: variant uses Eloi E4-10"
            : "production routing: Caissa unavailable; used Eloi E4-10";
      } else if (!active_brain && !runtime_fallback) {
        response.detail = "production routing: Standard uses Caissa 1.25";
      }
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
      const auto name = std::ranges::find(args, std::string_view{"name"});
      const auto value = std::ranges::find(args, std::string_view{"value"});
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
            setting == "standard" || setting == "kingofthehill" ||
            setting == "king_of_the_hill" || setting == "atomic" ||
            setting == "antichess") {
          uci_variant = setting == "horde" ? "horde" :
                        (setting == "kingofthehill" ||
                         setting == "king_of_the_hill")
                            ? "kingofthehill" : setting == "atomic"
                                ? "atomic" : setting == "antichess"
                                    ? "antichess" : "chess";
          board.horde = uci_variant == "horde";
          board.king_of_the_hill = uci_variant == "kingofthehill";
          board.atomic = uci_variant == "atomic";
          board.antichess = uci_variant == "antichess";
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
        if (auto parsed = parse_fen(fen)) {
          board = *parsed;
          board.horde = uci_variant == "horde";
          board.king_of_the_hill = uci_variant == "kingofthehill";
          board.atomic = uci_variant == "atomic";
          board.antichess = uci_variant == "antichess";
        }
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

#ifndef ELOI_HYBRID_EMBEDDED
int main(int argc, char** argv) {
  if (eloi::caissa_worker_requested(argc, argv))
    return eloi::run_caissa_worker(argc, argv);
  return eloi::run_hybrid_lab(argc, argv);
}
#endif
