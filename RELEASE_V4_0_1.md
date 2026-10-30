# Eloi v4.0.1 — Two Months, Four Seats

Celebrating two months since Eloi v1.0.0: **Watch Eloi Think** makes the
handcrafted four-player Teams brain's completed search work visible.

- Live completed depth, team-relative evaluation, nodes and elapsed time.
- A seat-labelled principal variation captured during the existing search,
  not invented or produced through a second search. The panel shows at most
  six plies; the engine retains up to sixteen.
- A **Show suggestion** toggle overlays the current legal root move without
  playing it or changing selection.
- Clear Preparing search, Thinking, Move chosen, Cancelled and Emergency legal
  move states. Final metrics are explicitly previous-search information.
- Bounded latest-only telemetry with stale generation/root rejection. Search
  does not wait for painting, and final results retain their reliable channel.
- Two-way in-window navigation between two-player chess and Teams, preserving
  both local boards. Teams pauses while hidden; no hidden search or clock
  continues. Operations Center/Lichess remains separate and unchanged.

Retains Segoe UI and the charcoal/purple Teams styling. No rule changes,
training, donor upgrades or strength claims. Search remains three lanes with
unchanged budgets, ordering, pruning and evaluation. Standard UCI/Lichess
continues using the same pinned Caissa 2.0 worker. EloiBot's existing live
process/configuration is not upgraded or interrupted by publishing this patch.

Extract either complete Windows x64 ZIP and start `Open-Teams.cmd`:

- `Eloi-v4.0.1-windows-x64-standalone.zip`
- `Eloi-v4.0.1-windows-x64-exoskeleton.zip`

The anniversary publication target is October 29, 2026, 10:00 PM UTC−7
(October 30, 05:00 UTC). Publication is blocked unless all validation and
downloaded golden-asset checks pass beforehand; network/GitHub latency can
delay public visibility. No release is backdated.
