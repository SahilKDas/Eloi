#include "Memory.hpp"

bool EnableLargePagesSupport() {
  return false;
}

void* Malloc(std::size_t size) {
  return AlignedMalloc(size, CACHELINE_SIZE);
}

void Free(void* pointer) {
  AlignedFree(pointer);
}
