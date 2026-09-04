#include "eloi/brain.hpp"

namespace eloi {

CaissaBrain::CaissaBrain(std::filesystem::path network_path)
    : network_path_(std::move(network_path)) {}

BrainIdentity CaissaBrain::identity() const noexcept {
  return BrainIdentity::caissa_1_26;
}

bool CaissaBrain::available() const noexcept {
  return false;
}

BrainResponse CaissaBrain::search(Board, SearchLimits,
                                  const BrainInfoCallback& info) {
  BrainResponse response;
  response.requested = BrainIdentity::caissa_1_26;
  response.selected = BrainIdentity::caissa_1_26;
  response.status = BrainStatus::unavailable;
  response.detail =
      "Caissa backend disabled pending source-provenance audit and licensed "
      "network redistribution; no donor search was executed";
  if (info) info(response);
  return response;
}

const std::filesystem::path& CaissaBrain::network_path() const noexcept {
  return network_path_;
}

}  // namespace eloi
