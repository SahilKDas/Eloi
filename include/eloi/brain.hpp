#pragma once

#include "eloi/chess.hpp"

#include <atomic>
#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <string_view>

namespace eloi {

inline constexpr std::string_view caissa_1_26_commit =
    "008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06";
inline constexpr std::string_view caissa_1_26_network_sha256 =
    "22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116";
inline constexpr std::uintmax_t caissa_1_26_network_size = 50'367'040;

enum class BrainIdentity {
  eloi_e2,
  caissa_1_26,
  hybrid,
};

enum class BrainStatus {
  complete,
  stopped,
  timed_out,
  unavailable,
  invalid_move,
  failed,
};

struct BrainResponse {
  BrainIdentity requested{BrainIdentity::eloi_e2};
  BrainIdentity selected{BrainIdentity::eloi_e2};
  BrainStatus status{BrainStatus::failed};
  SearchResult search{};
  double confidence{0.0};
  bool used_fallback{false};
  std::string detail;

  bool has_legal_move(const Board& board) const;
};

using BrainInfoCallback = std::function<void(const BrainResponse&)>;

class Brain {
 public:
  virtual ~Brain() = default;
  virtual BrainIdentity identity() const noexcept = 0;
  virtual bool available() const noexcept = 0;
  virtual BrainResponse search(
      Board board, SearchLimits limits,
      const BrainInfoCallback& info = {}) = 0;
};

class EloiBrain final : public Brain {
 public:
  EloiBrain(EngineConfig config, std::atomic_bool& stopped);

  BrainIdentity identity() const noexcept override;
  bool available() const noexcept override;
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& info = {}) override;

 private:
  EngineConfig config_;
  std::atomic_bool& stopped_;
};

// This adapter intentionally fails closed until the remaining Caissa backend
// passes the source-provenance audit. Merely possessing the local network does
// not make the backend available.
class CaissaBrain final : public Brain {
 public:
  explicit CaissaBrain(std::filesystem::path network_path);

  BrainIdentity identity() const noexcept override;
  bool available() const noexcept override;
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& info = {}) override;
  const std::filesystem::path& network_path() const noexcept;

 private:
  std::filesystem::path network_path_;
};

struct HybridBudget {
  int caissa_percent{70};
  int eloi_percent{20};
  int verification_percent{10};

  bool valid() const noexcept;
};

// Standard chess will eventually use both backends sequentially. Until the
// audited Caissa adapter is available, this class records an explicit E2
// fallback. Chess960 and Horde always bypass Caissa at this stage.
class HybridBrain final : public Brain {
 public:
  HybridBrain(Brain& eloi, Brain& caissa,
              HybridBudget budget = {});

  BrainIdentity identity() const noexcept override;
  bool available() const noexcept override;
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& info = {}) override;
  const HybridBudget& budget() const noexcept;

 private:
  Brain& eloi_;
  Brain& caissa_;
  HybridBudget budget_;
};

constexpr int production_search_threads() noexcept {
  return search_thread_count;
}

}  // namespace eloi
