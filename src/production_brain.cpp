#include "eloi/production_brain.hpp"

#include <algorithm>
#include <cstdlib>
#include <mutex>
#include <stdexcept>
#include <string_view>

namespace eloi {
namespace {

std::mutex runtime_mutex;
std::optional<std::filesystem::path> runtime_network_path;
std::filesystem::path runtime_executable_path;
bool runtime_configured = false;

std::optional<std::filesystem::path> resolve_network_path(
    int argc, char** argv) {
  for (int index = 1; index < argc; ++index) {
    if (std::string_view(argv[index]) != "--caissa-network")
      continue;
    if (index + 1 >= argc || std::string_view(argv[index + 1]).empty())
      throw std::invalid_argument(
          "--caissa-network requires a non-empty path");
    return std::filesystem::path(argv[index + 1]);
  }
  if (const char* environment =
          std::getenv("ELOI_CAISSA_NETWORK_PATH");
      environment && *environment) {
    return std::filesystem::path(environment);
  }
  return std::nullopt;
}

int bounded_hash(int hash_mb) {
  return std::clamp(hash_mb, 0, 16'384);
}

std::size_t megabytes(int value) {
  return static_cast<std::size_t>(std::max(0, value))
         * 1024u * 1024u;
}

}  // namespace

void configure_production_brain_runtime(int argc, char** argv) {
  auto resolved = resolve_network_path(argc, argv);
  std::scoped_lock lock(runtime_mutex);
  runtime_network_path = resolved
      ? std::optional{std::filesystem::absolute(*resolved)}
      : std::nullopt;
  if (argc > 0 && argv && argv[0] && *argv[0])
    runtime_executable_path = std::filesystem::absolute(argv[0]);
  runtime_configured = true;
}

std::optional<std::filesystem::path> production_caissa_network_path() {
  std::scoped_lock lock(runtime_mutex);
  if (!runtime_configured) {
    if (const char* environment =
            std::getenv("ELOI_CAISSA_NETWORK_PATH");
        environment && *environment) {
      runtime_network_path =
          std::filesystem::absolute(environment);
    }
    runtime_configured = true;
  }
  return runtime_network_path;
}

std::filesystem::path production_executable_path() {
  std::scoped_lock lock(runtime_mutex);
  return runtime_executable_path;
}

struct ProductionBrain::Impl {
  Impl(EngineConfig source, std::atomic_bool& stopped,
       std::filesystem::path executable, std::filesystem::path network,
       bool isolate_caissa)
      : configured_hash(bounded_hash(source.hash_mb)),
        caissa_hash(configured_hash >= 2 ? configured_hash / 2 : 0),
        eloi_hash(configured_hash - caissa_hash) {
    source.hash_mb = configured_hash;
    full_eloi = std::make_unique<EloiBrain>(source, stopped);

    EngineConfig shared = source;
    shared.hash_mb = eloi_hash;
    hybrid_eloi = std::make_unique<EloiBrain>(shared, stopped);
    if (isolate_caissa)
      caissa = std::make_unique<IsolatedCaissaBrain>(
          std::move(executable), std::move(network), stopped,
          megabytes(caissa_hash));
    else
      caissa = std::make_unique<CaissaBrain>(
          std::move(network), stopped, megabytes(caissa_hash));
    hybrid = std::make_unique<HybridBrain>(
        *hybrid_eloi, *caissa);
  }

  int configured_hash;
  int caissa_hash;
  int eloi_hash;
  std::unique_ptr<EloiBrain> full_eloi;
  std::unique_ptr<EloiBrain> hybrid_eloi;
  std::unique_ptr<Brain> caissa;
  std::unique_ptr<HybridBrain> hybrid;
  std::string detail;
};

ProductionBrain::ProductionBrain(
    EngineConfig config, std::atomic_bool& stopped)
    : impl_(std::make_unique<Impl>(
          std::move(config), stopped, production_executable_path(),
          production_caissa_network_path().value_or(
              std::filesystem::path{}), true)) {}

ProductionBrain::ProductionBrain(
    EngineConfig config, std::atomic_bool& stopped,
    std::filesystem::path network_path)
    : impl_(std::make_unique<Impl>(
          std::move(config), stopped, std::filesystem::path{},
          std::move(network_path), false)) {}

ProductionBrain::~ProductionBrain() = default;

ProductionRoute ProductionBrain::route_for(
    const Board& board) const noexcept {
  if (board.horde || board.chess960)
    return ProductionRoute::eloi_variant;
  return impl_->caissa->available()
      ? ProductionRoute::hybrid_standard
      : ProductionRoute::eloi_fallback;
}

SearchResult ProductionBrain::iterative(
    Board board, SearchLimits limits,
    const std::function<void(const SearchResult&)>& info) {
  const Board root = board;
  BrainResponse response;
  const ProductionRoute route = route_for(root);
  switch (route) {
    case ProductionRoute::eloi_variant:
      if (auto* direct = dynamic_cast<CaissaBrain*>(impl_->caissa.get()))
        direct->release_hash();
      if (auto* isolated =
              dynamic_cast<IsolatedCaissaBrain*>(impl_->caissa.get()))
        isolated->release_hash();
      response = impl_->full_eloi->search(
          std::move(board), limits,
          [&](const BrainResponse& update) {
            if (info) info(update.search);
          });
      response.detail =
          "Chess960/Horde routed to Eloi E2";
      break;
    case ProductionRoute::eloi_fallback:
      if (auto* direct = dynamic_cast<CaissaBrain*>(impl_->caissa.get()))
        direct->release_hash();
      if (auto* isolated =
              dynamic_cast<IsolatedCaissaBrain*>(impl_->caissa.get()))
        isolated->release_hash();
      response = impl_->full_eloi->search(
          std::move(board), limits,
          [&](const BrainResponse& update) {
            if (info) info(update.search);
          });
      response.requested = BrainIdentity::hybrid;
      response.used_fallback = true;
      response.detail =
          "Standard hybrid unavailable; full-budget Eloi E2 fallback";
      break;
    case ProductionRoute::hybrid_standard:
      try {
        response = impl_->hybrid->search(
            std::move(board), limits,
            [&](const BrainResponse& update) {
              if (info) info(update.search);
            });
      } catch (const std::exception& error) {
        response.status = BrainStatus::failed;
        response.detail =
            "Caissa/hybrid exception: " +
            std::string(error.what());
      } catch (...) {
        response.status = BrainStatus::failed;
        response.detail = "Caissa/hybrid unknown exception";
      }
      break;
  }
  if (route == ProductionRoute::hybrid_standard &&
      response.status != BrainStatus::stopped &&
      !response.has_legal_move(root) &&
      !root.legal_moves().empty() &&
      (!limits.deadline ||
       std::chrono::steady_clock::now() < *limits.deadline)) {
    const std::string failure = response.detail;
    if (auto* direct = dynamic_cast<CaissaBrain*>(impl_->caissa.get()))
      direct->release_hash();
    if (auto* isolated =
            dynamic_cast<IsolatedCaissaBrain*>(impl_->caissa.get()))
      isolated->release_hash();
    response = impl_->full_eloi->search(
        root, limits,
        [&](const BrainResponse& update) {
          if (info) info(update.search);
        });
    response.requested = BrainIdentity::hybrid;
    response.used_fallback = true;
    response.detail =
        "hybrid failed; full-budget Eloi E2 fallback";
    if (!failure.empty())
      response.detail += " (" + failure + ")";
  }
  impl_->detail = response.detail;
  if (!response.search.pv.empty()
      && !response.has_legal_move(root)) {
    impl_->detail =
        "production controller rejected a non-Eloi-legal move";
    return {};
  }
  return response.search;
}

bool ProductionBrain::caissa_available() const noexcept {
  return impl_->caissa->available();
}

int ProductionBrain::eloi_hash_mb() const noexcept {
  return impl_->eloi_hash;
}

int ProductionBrain::caissa_hash_mb() const noexcept {
  return impl_->caissa_hash;
}

int ProductionBrain::configured_hash_mb() const noexcept {
  return impl_->configured_hash;
}

const std::string& ProductionBrain::last_detail() const noexcept {
  return impl_->detail;
}

}  // namespace eloi
