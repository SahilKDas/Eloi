//! Audited SIMD kernels behind safe, fixed-size interfaces.
//!
//! All runtime crates forbid unsafe code. This leaf crate contains the only
//! architecture intrinsics and denies unsafe code globally except on the one
//! AVX2 kernel whose preconditions are established by safe dispatch.

/// Scalar reference for a clipped 64-lane signed dot product.
#[must_use]
pub fn clipped_dot_scalar(values: &[i32; 64], weights: &[i16; 64]) -> i64 {
    values
        .iter()
        .zip(weights)
        .map(|(value, weight)| i64::from((*value).clamp(0, 127)) * i64::from(*weight))
        .sum()
}

/// Runtime-dispatched AVX2 dot product with an exact scalar fallback.
#[must_use]
pub fn clipped_dot(values: &[i32; 64], weights: &[i16; 64]) -> i64 {
    #[cfg(target_arch = "x86_64")]
    if std::arch::is_x86_feature_detected!("avx2") {
        // SAFETY: runtime detection proves AVX2; both references point to
        // exactly 64 initialized elements and the kernel uses unaligned loads.
        #[allow(unsafe_code)]
        return unsafe { clipped_dot_avx2(values, weights) };
    }
    clipped_dot_scalar(values, weights)
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
#[allow(unsafe_code)]
#[allow(clippy::cast_ptr_alignment)] // Intrinsics are explicitly unaligned loads/stores.
unsafe fn clipped_dot_avx2(values: &[i32; 64], weights: &[i16; 64]) -> i64 {
    use std::arch::x86_64::{
        __m128i, __m256i, _mm_loadu_si128, _mm256_cvtepi16_epi32, _mm256_loadu_si256,
        _mm256_max_epi32, _mm256_min_epi32, _mm256_mullo_epi32, _mm256_set1_epi32,
        _mm256_setzero_si256, _mm256_storeu_si256,
    };

    let zero = _mm256_setzero_si256();
    let ceiling = _mm256_set1_epi32(127);
    let mut sum = 0_i64;
    for index in (0..64).step_by(8) {
        // SAFETY: index advances 0..56 by eight; every load/store spans exactly
        // eight in-bounds values and accepts unaligned pointers.
        let value = unsafe { _mm256_loadu_si256(values.as_ptr().add(index).cast::<__m256i>()) };
        let value = _mm256_min_epi32(_mm256_max_epi32(value, zero), ceiling);
        let weight = unsafe { _mm_loadu_si128(weights.as_ptr().add(index).cast::<__m128i>()) };
        let products = _mm256_mullo_epi32(value, _mm256_cvtepi16_epi32(weight));
        let mut lanes = [0_i32; 8];
        unsafe { _mm256_storeu_si256(lanes.as_mut_ptr().cast::<__m256i>(), products) };
        sum += lanes.into_iter().map(i64::from).sum::<i64>();
    }
    sum
}

#[cfg(test)]
mod tests {
    use super::{clipped_dot, clipped_dot_scalar};

    #[test]
    fn dispatched_and_scalar_are_bit_exact() {
        let mut seed = 0x9E37_79B9_u32;
        for _ in 0..4096 {
            let mut values = [0_i32; 64];
            let mut weights = [0_i16; 64];
            for (value, weight) in values.iter_mut().zip(weights.iter_mut()) {
                seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                *value = i32::from((seed >> 16) as i16);
                seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                *weight = (seed >> 16) as i16;
            }
            assert_eq!(
                clipped_dot(&values, &weights),
                clipped_dot_scalar(&values, &weights)
            );
        }
    }
}
