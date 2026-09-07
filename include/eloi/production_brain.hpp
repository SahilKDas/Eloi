#pragma once

#include "eloi/brain.hpp"

#include <filesystem>
#include <memory>
#include <optional>

namespace eloi {

enum class ProductionRoute {
  hybrid_standard,
  eloi_variant,
  eloi_fallback,
};

// Resolve an explicit --caissa-network argument, then
// ELOI_CAISSA_NETWORK_PATH. No working-directory or executable-directory
// discovery occurs and no network is downloaded.
void configure_production_brain_runtime(int argc, char** argv);
std::optional<std::filesystem::path> production_caissa_network_path();

class ProductionBrain final {
 public:
  ProductionBrain(EngineConfig config, std::atomic_bool& stopped);
  ProductionBrain(EngineConfig config, std::atomic_bool& stopped,
                  std::filesystem::path network_path);
  ~ProductionBrain();

  ProductionBrain(const ProductionBrain&) = delete;
  ProductionBrain& operator=(const ProductionBrain&) = delete;

  SearchResult iterative(
      Board board, SearchLimits limits,
      const std::function<void(const SearchResult&)>& info = {});
  ProductionRoute route_for(const Board& board) const noexcept;
  bool caissa_available() const noexcept;
  int eloi_hash_mb() const noexcept;
  int caissa_hash_mb() const noexcept;
  int configured_hash_mb() const noexcept;
  const std::string& last_detail() const noexcept;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace eloi
