#pragma once

#include "eloi/chess.hpp"

#include <atomic>
#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <string_view>

namespace eloi {

inline constexpr std::string_view caissa_1_25_commit =
    "0c01e79ea36ae492585e88cca9d03abae9b7a3d5";
inline constexpr std::string_view caissa_1_25_network_sha256 =
    "615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B";
inline constexpr std::uintmax_t caissa_1_25_network_size = 50'367'040;

enum class BrainIdentity {
  eloi_e2,
  caissa_1_25,
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

struct BrainLine {
  std::vector<Move> pv;
  int score_cp{0};
  int mate{0};
};

struct BrainResponse {
  BrainIdentity requested{BrainIdentity::eloi_e2};
  BrainIdentity selected{BrainIdentity::eloi_e2};
  BrainStatus status{BrainStatus::failed};
  SearchResult search{};
  std::vector<BrainLine> lines;
  double confidence{0.0};
  bool used_fallback{false};
  std::string detail;

  bool has_legal_move(const Board& board) const;
};

struct CaissaPositionProbe {
  bool parsed{false};
  bool fen_round_trip{false};
  bool history_replayed{false};
  std::size_t history_size{0};
  std::uint32_t repetition_count{0};
  bool drawn{false};
  std::string reconstructed_fen;
  std::vector<std::string> legal_moves;
  std::string detail;
};

// Caissa 1.25 process-global initialization is not idempotent.
void initialize_caissa_backend();

// Standard-chess board adapter probe. It does not load a network or search.
CaissaPositionProbe probe_caissa_position(const Board& board);

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
  std::unique_ptr<Searcher> searcher_;
};

// This adapter intentionally fails closed until the remaining Caissa backend
// passes the source-provenance audit. Merely possessing the local network does
// not make the backend available.
class CaissaBrain final : public Brain {
 public:
  CaissaBrain(std::filesystem::path network_path,
              std::atomic_bool& stopped,
              std::size_t hash_bytes = 16u * 1024u * 1024u);
  ~CaissaBrain();

  CaissaBrain(const CaissaBrain&) = delete;
  CaissaBrain& operator=(const CaissaBrain&) = delete;

  BrainIdentity identity() const noexcept override;
  bool available() const noexcept override;
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& info = {}) override;
  const std::filesystem::path& network_path() const noexcept;

 private:
  struct Impl;
  std::filesystem::path network_path_;
  std::unique_ptr<Impl> impl_;
};

class IsolatedCaissaBrain final : public Brain {
 public:
  IsolatedCaissaBrain(std::filesystem::path executable_path,
                      std::filesystem::path network_path,
                      std::atomic_bool& stopped,
                      std::size_t hash_bytes = 16u * 1024u * 1024u);
  ~IsolatedCaissaBrain();
  IsolatedCaissaBrain(const IsolatedCaissaBrain&) = delete;
  IsolatedCaissaBrain& operator=(const IsolatedCaissaBrain&) = delete;
  BrainIdentity identity() const noexcept override;
  bool available() const noexcept override;
  BrainResponse search(Board board, SearchLimits limits,
                       const BrainInfoCallback& info = {}) override;
  void release_hash();

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

bool caissa_worker_requested(int argc, char** argv) noexcept;
int run_caissa_worker(int argc, char** argv);

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
