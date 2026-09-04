#pragma once

#include "Common.hpp"

#include <algorithm>
#include <cstdlib>
#include <limits>
#include <new>

#if defined(PLATFORM_WINDOWS)
#include <malloc.h>
#endif

// Eloi-owned bounded allocator boundary. The embedded backend deliberately
// does not request OS large pages or change process privileges.
inline void* AlignedMalloc(std::size_t size, std::size_t alignment) {
  alignment = std::max(alignment, alignof(void*));
#if defined(PLATFORM_WINDOWS)
  return _aligned_malloc(size, alignment);
#else
  void* pointer = nullptr;
  return posix_memalign(&pointer, alignment, size) == 0 ? pointer : nullptr;
#endif
}

inline void AlignedFree(void* pointer) {
#if defined(PLATFORM_WINDOWS)
  _aligned_free(pointer);
#else
  std::free(pointer);
#endif
}

bool EnableLargePagesSupport();
[[nodiscard]] void* Malloc(std::size_t size);
void Free(void* pointer);

template <typename T, std::size_t Alignment = 16>
class AlignmentAllocator {
 public:
  using value_type = T;
  using size_type = std::size_t;
  using difference_type = std::ptrdiff_t;

  AlignmentAllocator() noexcept = default;
  template <typename U>
  AlignmentAllocator(const AlignmentAllocator<U, Alignment>&) noexcept {}

  [[nodiscard]] T* allocate(std::size_t count) {
    if (count > std::numeric_limits<std::size_t>::max() / sizeof(T))
      throw std::bad_array_new_length();
    if (void* memory = AlignedMalloc(count * sizeof(T), Alignment))
      return static_cast<T*>(memory);
    throw std::bad_alloc();
  }

  void deallocate(T* pointer, std::size_t) noexcept {
    AlignedFree(pointer);
  }

  template <typename U>
  struct rebind {
    using other = AlignmentAllocator<U, Alignment>;
  };

  template <typename U>
  bool operator==(const AlignmentAllocator<U, Alignment>&) const noexcept {
    return true;
  }
};

template <typename T>
class Allocator {
 public:
  using value_type = T;

  Allocator() noexcept = default;
  template <typename U>
  Allocator(const Allocator<U>&) noexcept {}

  [[nodiscard]] T* allocate(std::size_t count) {
    if (count > std::numeric_limits<std::size_t>::max() / sizeof(T))
      throw std::bad_array_new_length();
    if (void* memory = Malloc(count * sizeof(T)))
      return static_cast<T*>(memory);
    throw std::bad_alloc();
  }

  void deallocate(T* pointer, std::size_t) noexcept {
    Free(pointer);
  }
};
