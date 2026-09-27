# Eloi v3.5.0 — Lichess Operations Center

The native chess window and Lichess Operations Center now share Eloi's
Skia-rendered visual language, including responsive cards, subtle ambient
lighting, and smooth hover lift/zoom animations. These presentation changes do
not alter search, timing, routing, or move selection.

Status: development; not yet published.

Eloi v3.5.0 replaces the fragile launch-and-watch bridge workflow with a
supervised native Windows Operations Center. The dashboard and console are
visible by default, only one dashboard can connect per Windows user, and the
bridge reports connection state, active-game details, actual brain routing,
search telemetry, failures, fallbacks, incidents, and session results without
exposing the Lichess token.

Controls pause or resume challenge acceptance, request an immediate reconnect,
open configuration, copy redacted diagnostics, open the log directory, and
exit. Closing during a game requires explicit confirmation and performs a
controlled stop rather than leaving a hidden bridge behind.

Automatic recovery is deliberately narrow. DNS/socket failures, disconnected
streams, HTTP 408, 429, and 5xx responses retry using `Retry-After` or the
bounded 2/4/8/15/30/60-second schedule. Invalid configuration, malformed
account responses, HTTP 401/403, unsupported invariants, and repeated protocol
corruption stop in a visible fatal state.

The release adds `--headless` for console-only operation, rotating token-free
logs under `%LOCALAPPDATA%\Eloi\logs\lichess`, and an atomic status snapshot at
`%LOCALAPPDATA%\Eloi\status\lichess.json`.

This is an operations and observability release. It does not change move
selection, time allocation, variant rules, brain routing, or Eloi's fixed
three-thread contract. Standard remains on crash-contained Caissa 1.25, KOTH
uses E4-KOTH, and other variants and fallback use E4-10.

Publication requires all correctness, offline bridge, live-smoke,
behavior-comparison, reproducibility, clean-extraction, and Defender gates.
