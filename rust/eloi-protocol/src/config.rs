//! Native runtime configuration subset, with credential-safe diagnostics.

use eloi_core::Variant;

/// Lichess secret without Debug/Display exposure. Only transport construction
/// should request the plaintext; it never belongs in snapshots or packages.
pub struct Token(String);

impl Token {
    /// Explicit credential access for authenticated transport setup.
    #[must_use]
    pub fn expose_for_transport(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Debug for Token {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("[REDACTED]")
    }
}

/// Public native settings, matching the tracked release template.
#[derive(Debug)]
pub struct RuntimeConfig {
    /// Whether native Lichess operation is enabled.
    pub enabled: bool,
    /// Credential excluded from debug output.
    pub token: Token,
    /// Pinned HTTPS API origin, never an arbitrary token destination.
    pub url: String,
    /// Minimum accepted base time in seconds.
    pub min_base_seconds: u32,
    /// Maximum accepted base time in seconds.
    pub max_base_seconds: u32,
    /// Whether bot opponents are accepted.
    pub allow_bots: bool,
    /// Enabled, production-supported variants only.
    pub variants: Vec<Variant>,
    /// Configured depth; zero denotes clock-managed search.
    pub depth: u32,
    /// Configured transposition memory budget.
    pub hash_mb: u32,
    /// Protocol/network reserve configuration.
    pub move_overhead_ms: u32,
    /// Standard opening-book preference.
    pub own_book: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            token: Token(String::new()),
            url: "https://lichess.org".into(),
            min_base_seconds: 0,
            max_base_seconds: 10800,
            allow_bots: true,
            variants: vec![
                Variant::Standard,
                Variant::Chess960,
                Variant::Horde,
                Variant::KingOfTheHill,
                Variant::Atomic,
                Variant::Antichess,
                Variant::Crazyhouse,
            ],
            depth: 0,
            hash_mb: 32,
            move_overhead_ms: 100,
            own_book: true,
        }
    }
}

fn content(line: &str) -> Result<&str, &'static str> {
    let mut quote = None;
    for (index, character) in line.char_indices() {
        match character {
            '\'' | '"' if quote == Some(character) => quote = None,
            '\'' | '"' if quote.is_none() => quote = Some(character),
            '#' if quote.is_none() => return Ok(line[..index].trim_end()),
            '\\' if quote == Some('"') => return Err("escape syntax is unsupported"),
            _ => {}
        }
    }
    if quote.is_some() {
        Err("unterminated quoted scalar")
    } else {
        Ok(line.trim_end())
    }
}

fn scalar(value: &str) -> &str {
    let value = value.trim();
    if value.len() >= 2
        && ((value.starts_with('"') && value.ends_with('"'))
            || (value.starts_with('\'') && value.ends_with('\'')))
    {
        &value[1..value.len() - 1]
    } else {
        value
    }
}

/// Parse the native YAML subset without loading objects or interpolating variables.
/// Errors never include scalar values, so tokens cannot leak through failures.
///
/// # Errors
/// Rejects malformed syntax, unsupported variants, duplicates and invalid ranges.
pub fn parse(text: &str) -> Result<RuntimeConfig, String> {
    if text.len() > 65_536 {
        return Err("configuration exceeds 64 KiB".into());
    }
    let mut config = RuntimeConfig::default();
    config.variants.clear();
    let mut section = "";
    let mut variant_list = false;
    let mut keys = std::collections::BTreeSet::new();
    for (index, raw) in text.trim_start_matches('\u{feff}').lines().enumerate() {
        let fail = |reason: &str| format!("config line {}: {reason}", index + 1);
        let line = content(raw).map_err(fail)?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if !line.starts_with(char::is_whitespace) && trimmed.ends_with(':') {
            section = &trimmed[..trimmed.len() - 1];
            if !matches!(section, "lichess" | "challenge" | "engine") {
                return Err(fail("unsupported section"));
            }
            variant_list = false;
            continue;
        }
        if let Some(item) = trimmed.strip_prefix("- ") {
            if section != "challenge" || !variant_list {
                return Err(fail("list outside challenge.variants"));
            }
            let variant = super::variant_from_lichess(scalar(item))
                .filter(|variant| *variant != Variant::FourPlayer)
                .ok_or_else(|| fail("unsupported runtime variant"))?;
            if config.variants.contains(&variant) {
                return Err(fail("duplicate variant"));
            }
            config.variants.push(variant);
            continue;
        }
        let (key, value) = trimmed
            .split_once(':')
            .ok_or_else(|| fail("expected key: value"))?;
        let key = key.trim();
        let value = scalar(value);
        if !keys.insert((section, key)) {
            return Err(fail("duplicate setting"));
        }
        variant_list = section == "challenge" && key == "variants";
        let number = || {
            value
                .parse::<u32>()
                .map_err(|_| fail("invalid numeric setting"))
        };
        let boolean = || match value {
            "true" => Ok(true),
            "false" => Ok(false),
            _ => Err(fail("invalid boolean setting")),
        };
        match (section, key) {
            ("lichess", "enabled") => config.enabled = boolean()?,
            ("lichess", "token") => config.token = Token(value.into()),
            ("lichess", "url") => config.url = value.into(),
            ("challenge", "min_base_seconds") => config.min_base_seconds = number()?,
            ("challenge", "max_base_seconds") => config.max_base_seconds = number()?,
            ("challenge", "allow_bots") => config.allow_bots = boolean()?,
            ("challenge", "variants") if value.is_empty() => {}
            ("engine", "depth") => config.depth = number()?,
            ("engine", "hash_mb") => config.hash_mb = number()?,
            ("engine", "move_overhead_ms") => config.move_overhead_ms = number()?,
            ("engine", "own_book") => config.own_book = boolean()?,
            _ => return Err(fail("unsupported setting")),
        }
    }
    if config.variants.is_empty() {
        config.variants.push(Variant::Standard);
    }
    if config.url != "https://lichess.org" {
        return Err("lichess.url must be exactly https://lichess.org".into());
    }
    if config.max_base_seconds < config.min_base_seconds || config.depth > 17697 {
        return Err("configuration range is invalid".into());
    }
    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::parse;

    #[test]
    fn release_template_and_secrets_are_safe() {
        let config = parse(include_str!("../../../config.example.yml")).unwrap();
        assert_eq!(config.variants.len(), 7);
        assert!(config.token.expose_for_transport().is_empty());
        let config = parse("lichess:\n  token: 'lip_secret#hash' # comment\n").unwrap();
        assert_eq!(config.token.expose_for_transport(), "lip_secret#hash");
        assert!(!format!("{config:?}").contains("secret"));
    }

    #[test]
    fn malformed_or_unsupported_config_fails_without_values() {
        for text in [
            "lichess:\n  url: https://evil.example\n",
            "engine:\n  depth: -1\n",
            "challenge:\n  variants:\n    - fourPlayer\n",
            "challenge:\n  allow_bots: true\n  - standard\n",
            "lichess:\n  token: lip_secret\n  token: duplicate\n",
            "lichess:\n  token: 'lip_secret\n",
        ] {
            let error = parse(text).unwrap_err();
            assert!(!error.contains("secret"));
        }
    }
}
