#include "eloi/brain.hpp"

#include <atomic>
#include <chrono>
#include <iostream>
#include <random>
#include <ranges>
#include <stdexcept>
#include <thread>
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

BrainResponse fake_response(BrainIdentity identity, const Board& board,
                            std::string_view move_text, int score_cp,
                            int mate = 0) {
  BrainResponse response;
  response.requested = response.selected = identity;
  response.status = BrainStatus::complete;
  const auto legal = board.legal_moves();
  const auto move = std::ranges::find_if(
      legal, [&](const Move& candidate) {
        return candidate.uci() == move_text;
      });
  if (move == legal.end()) {
    response.status = BrainStatus::invalid_move;
    return response;
  }
  response.search.pv.push_back(*move);
  response.search.score_cp = score_cp;
  response.search.mate = mate;
  response.search.depth = 4;
  response.lines.push_back({response.search.pv, score_cp, mate});
  return response;
}

class FakeBrain final : public Brain {
 public:
  using Handler =
      std::function<BrainResponse(const Board&, const SearchLimits&, int)>;

  FakeBrain(BrainIdentity identity, Handler handler)
      : identity_(identity), handler_(std::move(handler)) {}

  BrainIdentity identity() const noexcept override { return identity_; }
  bool available() const noexcept override { return true; }
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& = {}) override {
    return handler_(board, limits, calls_++);
  }
  int calls() const noexcept { return calls_; }

 private:
  BrainIdentity identity_;
  Handler handler_;
  int calls_{0};
};
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

  CaissaBrain wrong_network{
      std::filesystem::path(ELOI_TEST_PROJECT_DIR) / "CMakeLists.txt",
      stopped};
  expect(!wrong_network.available(),
         "a regular file with the wrong network identity fails closed");

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
           "4k3/P7/8/8/8/8/7p/4K3 w - - 0 1",
           "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 47 83"}) {
    const auto board = parse_fen(fen);
    expect(board.has_value() && caissa_matches(*board),
           "Caissa matches castling, en-passant, promotion, and clock seams");
  }

  {
    auto repetition = *parse_fen(initial_fen);
    bool replayed = true;
    for (const auto* move : {
             "g1f3", "g8f6", "f3g1", "f6g8",
             "g1f3", "g8f6", "f3g1", "f6g8"}) {
      replayed = replayed && repetition.push_uci(move);
    }
    const auto probe = probe_caissa_position(repetition);
    expect(replayed && probe.history_replayed && probe.history_size == 8,
           "Caissa replays Eloi's complete reversible move history");
    expect(probe.repetition_count == 3 && probe.drawn,
           "Caissa preserves a threefold repetition through replay");
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

  {
    const auto mate = parse_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1");
    expect(mate.has_value(), "terminal mate position parses");
    if (mate) {
      const auto response = hybrid.search(*mate, {});
      expect(response.status == BrainStatus::complete &&
                 response.search.pv.empty() &&
                 response.detail.find("checkmate") != std::string::npos,
             "terminal checkmate completes without inventing a move");
    }
  }

  {
    auto board = *parse_fen(initial_fen);
    FakeBrain fake_eloi{
        BrainIdentity::eloi_e2,
        [](const Board& position, const SearchLimits&, int) {
          return fake_response(BrainIdentity::eloi_e2, position, "e2e4", 12);
        }};
    FakeBrain fake_caissa{
        BrainIdentity::caissa_1_26,
        [](const Board& position, const SearchLimits&, int) {
          return fake_response(
              BrainIdentity::caissa_1_26, position, "e2e4", 18);
        }};
    HybridBrain agreement{fake_eloi, fake_caissa};
    SearchLimits limits;
    limits.nodes = 1'000;
    const auto response = agreement.search(board, limits);
    expect(response.has_legal_move(board) &&
               response.search.pv.front().uci() == "e2e4" &&
               fake_eloi.calls() == 1 && fake_caissa.calls() == 1,
           "agreement accepts the shared legal move without verification");
  }

  {
    auto board = *parse_fen(initial_fen);
    FakeBrain fake_eloi{
        BrainIdentity::eloi_e2,
        [](const Board& position, const SearchLimits&, int) {
          if (position.history.empty())
            return fake_response(
                BrainIdentity::eloi_e2, position, "d2d4", 40);
          return fake_response(
              BrainIdentity::eloi_e2, position, "e7e5", -20);
        }};
    FakeBrain fake_caissa{
        BrainIdentity::caissa_1_26,
        [](const Board& position, const SearchLimits&, int) {
          if (position.history.empty())
            return fake_response(
                BrainIdentity::caissa_1_26, position, "e2e4", 60);
          return fake_response(
              BrainIdentity::caissa_1_26, position, "d7d5", 200);
        }};
    HybridBrain disagreement{fake_eloi, fake_caissa};
    SearchLimits limits;
    limits.nodes = 1'000;
    const auto response = disagreement.search(board, limits);
    expect(response.has_legal_move(board) &&
               response.search.pv.front().uci() == "e2e4" &&
               response.search.score_cp == 20 &&
               response.lines.size() == 2 &&
               response.lines.front().pv.front().uci() == "e2e4" &&
               fake_eloi.calls() == 2 && fake_caissa.calls() == 2 &&
               response.detail.find("cross-verification") != std::string::npos,
           "disagreement reports normalized selected and alternative lines");
  }

  {
    auto board = *parse_fen(initial_fen);
    FakeBrain fake_eloi{
        BrainIdentity::eloi_e2,
        [](const Board& position, const SearchLimits&, int) {
          return fake_response(BrainIdentity::eloi_e2, position, "d2d4", 10);
        }};
    FakeBrain invalid_caissa{
        BrainIdentity::caissa_1_26,
        [](const Board&, const SearchLimits&, int) {
          BrainResponse response;
          response.requested = response.selected =
              BrainIdentity::caissa_1_26;
          response.status = BrainStatus::invalid_move;
          return response;
        }};
    HybridBrain fallback{fake_eloi, invalid_caissa};
    SearchLimits limits;
    limits.nodes = 1'000;
    const auto response = fallback.search(board, limits);
    expect(response.requested == BrainIdentity::hybrid &&
               response.selected == BrainIdentity::eloi_e2 &&
               response.used_fallback && response.has_legal_move(board),
           "an invalid Caissa response falls back to a legal E2 move");
  }

  {
    auto board = *parse_fen(initial_fen);
    const auto failing = [](BrainIdentity identity) {
      return FakeBrain{
          identity,
          [identity](const Board&, const SearchLimits&, int) {
            BrainResponse response;
            response.requested = response.selected = identity;
            response.status = BrainStatus::failed;
            return response;
          }};
    };
    auto failed_eloi = failing(BrainIdentity::eloi_e2);
    auto failed_caissa = failing(BrainIdentity::caissa_1_26);
    HybridBrain no_brain{failed_eloi, failed_caissa};
    SearchLimits limits;
    limits.nodes = 1'000;
    const auto response = no_brain.search(board, limits);
    expect(response.status == BrainStatus::failed &&
               response.selected == BrainIdentity::hybrid &&
               response.search.pv.empty(),
           "two failed brains produce an explicit hybrid failure");
  }

  {
    auto board = *parse_fen(initial_fen);
    FakeBrain fake_eloi{
        BrainIdentity::eloi_e2,
        [](const Board& position, const SearchLimits&, int) {
          auto response = fake_response(
              BrainIdentity::eloi_e2, position, "d2d4", 10);
          const auto legal = position.legal_moves();
          const auto e4 = std::ranges::find_if(
              legal, [](const Move& move) { return move.uci() == "e2e4"; });
          if (e4 != legal.end())
            response.lines.push_back({{*e4}, 0, -2});
          return response;
        }};
    FakeBrain fake_caissa{
        BrainIdentity::caissa_1_26,
        [](const Board& position, const SearchLimits&, int) {
          if (position.history.empty())
            return fake_response(
                BrainIdentity::caissa_1_26, position, "e2e4", 0);
          BrainResponse failed;
          failed.requested = failed.selected = BrainIdentity::caissa_1_26;
          failed.status = BrainStatus::failed;
          return failed;
        }};
    HybridBrain mate_veto{fake_eloi, fake_caissa};
    SearchLimits limits;
    limits.nodes = 1'000;
    const auto response = mate_veto.search(board, limits);
    expect(response.has_legal_move(board) &&
               response.search.pv.front().uci() == "e2e4" &&
               response.search.mate == -2,
           "one brain's forced-loss report survives an ordinary peer score");
  }

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

      SearchLimits stop_limits;
      stop_limits.depth = 99;
      const auto stop_started = std::chrono::steady_clock::now();
      std::jthread stop_trigger([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
        stopped = true;
      });
      const auto stopped_response = local_caissa.search(board, stop_limits);
      stop_trigger.join();
      const auto stop_elapsed =
          std::chrono::steady_clock::now() - stop_started;
      expect(stopped_response.status == BrainStatus::stopped,
             "Caissa observes Eloi's shared external stop flag");
      expect(stop_elapsed < std::chrono::milliseconds(500),
             "Caissa external stop returns within 500 milliseconds");
      expect(stopped_response.search.pv.empty() ||
                 stopped_response.has_legal_move(board),
             "a stopped Caissa search exposes no illegal partial move");
      stopped = false;

      SearchLimits deadline_limits;
      deadline_limits.deadline = std::chrono::steady_clock::now() +
                                 std::chrono::milliseconds(50);
      const auto deadline_started = std::chrono::steady_clock::now();
      const auto deadline_response =
          local_caissa.search(board, deadline_limits);
      const auto deadline_elapsed =
          std::chrono::steady_clock::now() - deadline_started;
      expect(deadline_response.status == BrainStatus::complete &&
                 deadline_response.has_legal_move(board),
             "a bounded Caissa deadline retains a legal completed move");
      expect(deadline_elapsed < std::chrono::milliseconds(500),
             "Caissa's 50 millisecond deadline returns within 500 milliseconds");

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
