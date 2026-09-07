#pragma once

#include <cstddef>
#include <span>

namespace eloi {

// Returns the build-time RCDATA payload only in an explicitly configured
// Windows embedding build. Ordinary and non-Windows builds return an empty
// view and retain no network bytes.
std::span<const std::byte> embedded_caissa_network_bytes() noexcept;

}  // namespace eloi
