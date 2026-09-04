#include "eloi/brain.hpp"

#include <atomic>
#include <iostream>
#include <random>
#include <ranges>
#include <stdexcept>
#include <vector>

using namespace eloi;

namespace {
int failures = 0;

void expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

std::vector<std::string> eloi_legal_moves(const Board& board) {
  std::vector<std::string> moves;
  for (const auto& move : board.legal_moves())
    moves.push_back(move.uci());
  std::ranges::sort(moves);
  return moves;
}

bool caissa_matches(const Board& board) {
  const auto probe = probe_caissa_position(board);
  return probe.parsed && probe.fen_round_trip &&
         probe.legal_moves == eloi_legal_moves(board);
}
}  // namespace

int main() {
  expect(production_search_threads() == 3,
         "every production brain process owns exactly three search threads");
  expect(HybridBudget{}.valid(), "default hybrid budget totals 100 percent");
  expect(!HybridBudget{70, 20, 9}.valid(),
         "invalid hybrid budget is rejected");

  std::atomic_bool stopped{false};
  auto config = default_config();
  config.own_book = false;
  config.hash_mb = 4;
  EloiBrain eloi(config, stopped);
  CaissaBrain caissa{".deps/caissa/missing-test-network.pnn", stopped};
  HybridBrain hybrid(eloi, caissa);

  expect(eloi.available(), "E2 adapter is available");
  expect(!caissa.available(), "Caissa fails closed before backend audit");
  expect(caissa.network_path() == ".deps/caissa/missing-test-network.pnn",
         "local network path is retained without loading it");

  auto standard = parse_fen(initial_fen);
  expect(standard.has_value(), "standard test position parses");
  if (standard) {
    const auto probe = probe_caissa_position(*standard);
    expect(probe.parsed && probe.fen_round_trip,
           "Caissa reconstructs the authoritative initial FEN exactly");
    expect(probe.legal_moves == eloi_legal_moves(*standard),
           "Caissa and Eloi initial legal move sets match exactly");

    SearchLimits limits;
    limits.depth = 1;
    auto response = hybrid.search(*standard, limits);
    expect(response.requested == BrainIdentity::hybrid &&
               response.selected == BrainIdentity::eloi_e2 &&
               response.used_fallback,
           "standard hybrid records E2 fallback while Caissa is unavailable");
    expect(response.status == BrainStatus::complete &&
               response.has_legal_move(*standard),
           "standard fallback produces an Eloi-verified legal move");
  }

  for (const auto* fen : {
           "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
           "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2",
           "4k3/P7/8/8/8/8/7p/4K3 w - - 0 1"}) {
    const auto board = parse_fen(fen);
    expect(board.has_value() && caissa_matches(*board),
           "Caissa matches Eloi on castling, en-passant, and promotion seams");
  }

  {
    auto board = *parse_fen(initial_fen);
    std::mt19937 random{0xCA155A};
    bool all_match = true;
    for (int sample = 0; sample < 256; ++sample) {
      if (!caissa_matches(board)) {
        all_match = false;
        break;
      }
      const auto moves = board.legal_moves();
      if (moves.empty()) {
        board = *parse_fen(initial_fen);
        continue;
      }
      const auto index = static_cast<std::size_t>(random()) % moves.size();
      if (!board.push(moves[index])) {
        all_match = false;
        break;
      }
    }
    expect(all_match,
           "Caissa matches Eloi across 256 seeded legal Standard positions");
  }

  auto chess960 = chess960_start(518);
  expect(chess960.has_value(), "Chess960 test position parses");
  if (chess960) {
    SearchLimits limits;
    limits.depth = 1;
    auto response = hybrid.search(*chess960, limits);
    expect(response.selected == BrainIdentity::eloi_e2 &&
               response.used_fallback && response.has_legal_move(*chess960),
           "Chess960 bypasses Caissa and remains legal");
  }

  auto horde = parse_fen(horde_initial_fen);
  expect(horde.has_value(), "Horde test position parses");
  if (horde) {
    horde->horde = true;
    SearchLimits limits;
    limits.depth = 1;
    auto response = hybrid.search(*horde, limits);
    expect(response.selected == BrainIdentity::eloi_e2 &&
               response.used_fallback && response.has_legal_move(*horde),
           "Horde bypasses Caissa and remains legal");
  }

  bool rejected_budget = false;
  try {
    HybridBrain invalid(eloi, caissa, {70, 20, 9});
  } catch (const std::invalid_argument&) {
    rejected_budget = true;
  }
  expect(rejected_budget, "constructor rejects an invalid shared budget");

  const std::filesystem::path local_network =
      std::filesystem::path(ELOI_TEST_PROJECT_DIR) /
      ".deps/caissa/eval-82-383B.pnn";
  if (std::filesystem::exists(local_network)) {
    CaissaBrain local_caissa{local_network, stopped, 4u * 1024u * 1024u};
    expect(local_caissa.available(),
           "the local Caissa network passes frozen size and SHA-256 checks");
    if (local_caissa.available()) {
      SearchLimits limits;
      limits.nodes = 1'000;
      auto board = *parse_fen(initial_fen);
      const auto response = local_caissa.search(board, limits);
      expect(response.status == BrainStatus::complete &&
                 response.has_legal_move(board),
             "three-thread local Caissa search returns an Eloi-legal move");

      HybridBrain live_hybrid{eloi, local_caissa};
      SearchLimits hybrid_limits;
      hybrid_limits.nodes = 4'000;
      const auto hybrid_response = live_hybrid.search(board, hybrid_limits);
      expect(hybrid_response.status == BrainStatus::complete &&
                 hybrid_response.selected == BrainIdentity::hybrid &&
                 hybrid_response.has_legal_move(board),
             "bounded two-brain arbitration returns an Eloi-legal move");
    }
  }

  if (failures) {
    std::cerr << failures << " hybrid test(s) failed\n";
    return 1;
  }
  std::cout << "hybrid adapter tests passed\n";
  return 0;
}
