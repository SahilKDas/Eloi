//! UCI and online-service protocol boundaries for the Rust rewrite.

use eloi_core::Variant;

pub mod uci;

/// Parse an exact Lichess variant key.
#[must_use]
pub fn variant_from_lichess(key: &str) -> Option<Variant> {
    Some(match key {
        "standard" => Variant::Standard,
        "chess960" => Variant::Chess960,
        "horde" => Variant::Horde,
        "kingOfTheHill" => Variant::KingOfTheHill,
        "atomic" => Variant::Atomic,
        "antichess" => Variant::Antichess,
        "crazyhouse" => Variant::Crazyhouse,
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::variant_from_lichess;
    use eloi_core::Variant;

    #[test]
    fn unsupported_variants_fail_closed() {
        assert_eq!(
            variant_from_lichess("crazyhouse"),
            Some(Variant::Crazyhouse)
        );
        assert_eq!(variant_from_lichess("fourPlayer"), None);
        assert_eq!(variant_from_lichess("kingofthehill"), None);
        assert_eq!(
            variant_from_lichess("kingOfTheHill"),
            Some(Variant::KingOfTheHill)
        );
    }
}
