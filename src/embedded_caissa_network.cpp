#include "eloi/embedded_caissa_network.hpp"

#if defined(_WIN32) && defined(ELOI_EMBED_CAISSA_NETWORK)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

namespace eloi {

std::span<const std::byte> embedded_caissa_network_bytes() noexcept {
#if defined(_WIN32) && defined(ELOI_EMBED_CAISSA_NETWORK)
  const HMODULE module = GetModuleHandleW(nullptr);
  const HRSRC resource = FindResourceW(
      module, MAKEINTRESOURCEW(290), MAKEINTRESOURCEW(10));
  if (!resource) return {};
  const DWORD size = SizeofResource(module, resource);
  const HGLOBAL loaded = LoadResource(module, resource);
  const void* bytes = loaded ? LockResource(loaded) : nullptr;
  if (!bytes || size == 0) return {};
  return {static_cast<const std::byte*>(bytes),
          static_cast<std::size_t>(size)};
#else
  return {};
#endif
}

}  // namespace eloi
