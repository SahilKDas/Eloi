#include "Numa.hpp"

#include <new>

namespace numa {

void Init() {}

std::uint32_t GetNumNodes() {
  return 1;
}

bool PinCurrentThreadToNumaNode(std::uint32_t node) {
  return node == 0;
}

void* AllocateOnNode(std::size_t size, std::uint32_t node) {
  if (node != 0) return nullptr;
  return ::operator new(size, std::nothrow);
}

void FreeOnNode(void* pointer, std::size_t) {
  ::operator delete(pointer);
}

}  // namespace numa
