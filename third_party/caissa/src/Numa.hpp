#pragma once

#include "Common.hpp"

#include <new>

// Eloi intentionally presents one ordinary allocation domain to the donor.
// It neither probes NUMA topology nor pins threads.
namespace numa {

void Init();
std::uint32_t GetNumNodes();
bool PinCurrentThreadToNumaNode(std::uint32_t node);
void* AllocateOnNode(std::size_t size, std::uint32_t node);
void FreeOnNode(void* pointer, std::size_t size);

template <typename T>
class PerNodeAllocation {
 public:
  PerNodeAllocation()
      : value_(new T()) {}

  PerNodeAllocation(const PerNodeAllocation&) = delete;
  PerNodeAllocation& operator=(const PerNodeAllocation&) = delete;

  ~PerNodeAllocation() {
    delete value_;
  }

  [[nodiscard]] T* Get(std::uint32_t node) const {
    ASSERT(node == 0);
    return value_;
  }

 private:
  T* value_;
};

}  // namespace numa
