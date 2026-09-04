#include "eloi/brain.hpp"
#include "eloi/version_match.hpp"

#include "Evaluate.hpp"
#include "Game.hpp"
#include "Search.hpp"
#include "TranspositionTable.hpp"

#include <algorithm>
#include <chrono>
#include <mutex>
#include <thread>
#include <vector>

namespace eloi {

namespace {

std::optional<Move> translate_move(const Board& board,
                                   const ::Move& caissa_move) {
  const std::string text = caissa_move.ToString();
  const auto legal = board.legal_moves();
  const auto found = std::ranges::find_if(legal, [&](const Move& move) {
    return move.uci() == text;
  });
  if (found == legal.end()) return std::nullopt;
  return *found;
}

bool rebuild_game(Board board, ::Game& game, std::string& error) {
  std::vector<Move> history;
  history.reserve(board.history.size());
  while (!board.history.empty()) {
    const auto move = board.last_move();
    if (!move || !board.pop()) {
      error = "Eloi could not rewind its authoritative game history";
      return false;
    }
    history.push_back(*move);
  }
  std::ranges::reverse(history);

  ::Position position;
  if (!position.FromFEN(to_fen(board))) {
    error = "Caissa rejected Eloi's root FEN";
    return false;
  }
  game.Reset(position);
  for (const Move& eloi_move : history) {
    const ::Move move = game.GetPosition().MoveFromString(
        eloi_move.uci(), MoveNotation::LAN);
    if (!move.IsValid() || !game.DoMove(move)) {
      error = "Caissa rejected an Eloi history move: " + eloi_move.uci();
      return false;
    }
  }
  return true;
}

std::vector<Move> translate_pv(Board board,
                               const std::vector<::Move>& caissa_pv) {
  std::vector<Move> pv;
  pv.reserve(caissa_pv.size());
  for (const ::Move& donor_move : caissa_pv) {
    const auto move = translate_move(board, donor_move);
    if (!move || !board.push(*move)) return {};
    pv.push_back(*move);
  }
  return pv;
}

}  // namespace

struct CaissaBrain::Impl {
  Impl(std::atomic_bool& stop_flag, std::size_t hash_bytes)
      : stopped(stop_flag), table(hash_bytes) {}

  std::atomic_bool& stopped;
  ::TranspositionTable table;
  ::Search searcher;
  std::mutex mutex;
  bool ready{false};
  std::string failure;
};

CaissaBrain::CaissaBrain(std::filesystem::path network_path,
                         std::atomic_bool& stopped,
                         std::size_t hash_bytes)
    : network_path_(std::move(network_path)),
      impl_(std::make_unique<Impl>(stopped, hash_bytes)) {
  ::InitEngine();
  std::error_code error;
  if (!std::filesystem::is_regular_file(network_path_, error)) {
    impl_->failure = "Caissa network file is absent";
    return;
  }
  if (std::filesystem::file_size(network_path_, error) !=
          caissa_1_26_network_size || error) {
    impl_->failure = "Caissa network size does not match the frozen identity";
    return;
  }
  if (sha256_file(network_path_) != caissa_1_26_network_sha256) {
    impl_->failure = "Caissa network SHA-256 does not match the frozen identity";
    return;
  }
  if (!::LoadMainNeuralNetwork(network_path_.string().c_str())) {
    impl_->failure = "Caissa rejected the hash-verified network";
    return;
  }
  impl_->ready = true;
}

CaissaBrain::~CaissaBrain() = default;

BrainIdentity CaissaBrain::identity() const noexcept {
  return BrainIdentity::caissa_1_26;
}

bool CaissaBrain::available() const noexcept {
  return impl_->ready;
}

BrainResponse CaissaBrain::search(Board board, SearchLimits limits,
                                  const BrainInfoCallback& info) {
  BrainResponse response;
  response.requested = BrainIdentity::caissa_1_26;
  response.selected = BrainIdentity::caissa_1_26;
  if (!impl_->ready) {
    response.status = BrainStatus::unavailable;
    response.detail = impl_->failure;
    if (info) info(response);
    return response;
  }
  if (board.horde || board.chess960) {
    response.status = BrainStatus::unavailable;
    response.detail = "Caissa search is Standard-only until variant parity";
    if (info) info(response);
    return response;
  }
  if (impl_->stopped) {
    response.status = BrainStatus::stopped;
    response.detail = "Caissa search was stopped before launch";
    if (info) info(response);
    return response;
  }

  std::scoped_lock lock(impl_->mutex);
  ::Game game;
  if (!rebuild_game(board, game, response.detail)) {
    response.status = BrainStatus::failed;
    if (info) info(response);
    return response;
  }

  ::SearchLimits donor_limits;
  donor_limits.startTimePoint = TimePoint::GetCurrent();
  if (limits.depth > 0)
    donor_limits.maxDepth = static_cast<std::uint16_t>(
        std::min(limits.depth, static_cast<int>(UINT16_MAX)));
  if (limits.nodes > 0) {
    donor_limits.maxNodes = limits.nodes;
    donor_limits.maxNodesSoft = limits.nodes;
  }
  if (limits.deadline) {
    const auto remaining = *limits.deadline - std::chrono::steady_clock::now();
    donor_limits.maxTime = TimePoint::FromSeconds(
        std::max(0.001f, std::chrono::duration<float>(remaining).count()));
    donor_limits.idealTimeBase = donor_limits.maxTime;
    donor_limits.idealTimeCurrent = donor_limits.maxTime;
  } else if (limits.remaining_ms > 0) {
    const TimeBudget budget = plan_time_budget(board, limits);
    donor_limits.maxTime = TimePoint::FromSeconds(
        std::max(1, budget.hard_ms) / 1000.0f);
    donor_limits.idealTimeBase = TimePoint::FromSeconds(
        std::max(1, budget.soft_ms) / 1000.0f);
    donor_limits.idealTimeCurrent = donor_limits.idealTimeBase;
  }

  ::SearchParam parameters{impl_->table};
  parameters.limits = donor_limits;
  parameters.numThreads = production_search_threads();
  parameters.numPvLines = 2;
  parameters.debugLog = false;
  parameters.useRootTablebase = false;
  parameters.evalRandomization = 0;
  parameters.stopSearch = false;

  ::SearchResult donor_result;
  ::SearchStats stats;
  const auto started = std::chrono::steady_clock::now();
  std::jthread stop_monitor([&](std::stop_token token) {
    while (!token.stop_requested() && !parameters.stopSearch) {
      if (impl_->stopped) {
        parameters.stopSearch = true;
        break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  });
  impl_->table.NextGeneration();
  impl_->searcher.DoSearch(game, parameters, donor_result, &stats);
  stop_monitor.request_stop();
  stop_monitor.join();
  response.search.elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - started);
  response.search.nodes = stats.nodes.load();
  response.search.qnodes = stats.quiescenceNodes.load();
  response.search.depth = static_cast<int>(stats.maxDepth.load());

  if (donor_result.empty() || donor_result.front().moves.empty()) {
    response.status = impl_->stopped ? BrainStatus::stopped : BrainStatus::failed;
    response.detail = "Caissa completed without a principal variation";
    if (info) info(response);
    return response;
  }

  response.search.pv = translate_pv(board, donor_result.front().moves);
  if (response.search.pv.empty()) {
    response.status = BrainStatus::invalid_move;
    response.detail = "Caissa PV failed Eloi's authoritative legal translation";
    if (info) info(response);
    return response;
  }
  const auto score = donor_result.front().score;
  response.search.score_cp = ::NormalizeEval(score);
  if (::IsMate(score)) {
    response.search.mate = score > 0
        ? (::CheckmateValue - score + 1) / 2
        : -(::CheckmateValue + score + 1) / 2;
  }
  for (const ::PvLine& donor_line : donor_result) {
    auto pv = translate_pv(board, donor_line.moves);
    if (pv.empty()) continue;
    BrainLine line;
    line.pv = std::move(pv);
    line.score_cp = ::NormalizeEval(donor_line.score);
    if (::IsMate(donor_line.score)) {
      line.mate = donor_line.score > 0
          ? (::CheckmateValue - donor_line.score + 1) / 2
          : -(::CheckmateValue + donor_line.score + 1) / 2;
    }
    response.lines.push_back(std::move(line));
  }
  response.status = impl_->stopped ? BrainStatus::stopped
                                   : BrainStatus::complete;
  if (info) info(response);
  return response;
}

const std::filesystem::path& CaissaBrain::network_path() const noexcept {
  return network_path_;
}

}  // namespace eloi
