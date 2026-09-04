#include "eloi/brain.hpp"

#include <atomic>
#include <iostream>
#include <stdexcept>

using namespace eloi;

namespace {
int failures = 0;

void expect(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
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
  CaissaBrain caissa{".deps/caissa/eval-82-383B.pnn"};
  HybridBrain hybrid(eloi, caissa);

  expect(eloi.available(), "E2 adapter is available");
  expect(!caissa.available(), "Caissa fails closed before backend audit");
  expect(caissa.network_path() == ".deps/caissa/eval-82-383B.pnn",
         "local network path is retained without loading it");

  auto standard = parse_fen(initial_fen);
  expect(standard.has_value(), "standard test position parses");
  if (standard) {
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

  if (failures) {
    std::cerr << failures << " hybrid test(s) failed\n";
    return 1;
  }
  std::cout << "hybrid adapter tests passed\n";
  return 0;
}
