# Faloi — Fairy Eloi

Faloi is Eloi's experimental fairy-chess branch. It is intentionally isolated
from released Eloi v3.2.2 while variant rules and strength are qualified.

## First playable variant: King of the Hill

The first implemented slice is King of the Hill (KOTH):

- Standard chess legality still applies.
- A player wins immediately when their king reaches `d4`, `e4`, `d5`, or `e5`.
- The win condition is enforced inside board terminal detection, quiescence,
  negamax, root search, the hybrid dispatcher, and the native GUI.
- KOTH bypasses Standard-only Caissa 1.25 and uses Eloi E4-10 with exactly
  three RootSplit lanes.
- Opening-book use is disabled and search state is discarded when switching
  variants, preventing Standard/Horde/Chess960 transposition leakage.

## Interfaces

- Native GUI: choose **KOTH** in the clocked-game setup dialog.
- UCI: `setoption name UCI_Variant value kingofthehill`.
- The alias `king_of_the_hill` is accepted when setting the UCI option.

## Current boundary

This is a laboratory implementation, not a Faloi release. Native Lichess
challenge/configuration support is not enabled yet. KOTH uses the Standard-only
E4-10 evaluator plus a correct terminal search condition; it has not been
trained or strength-qualified specifically for KOTH. Caissa remains unavailable
for this variant.

## Validation

- Core engine suite, including immediate hill wins and orthodox isolation.
- Caissa/hybrid suite, including mandatory Eloi-only KOTH routing.
- GUI suite, including KOTH selection and Caissa rejection.
- Production-dispatcher UCI smoke: KOTH advertised, E4-10 route reported, and
  an immediate legal hill-winning move returned.

## Next safe slices

1. Add KOTH-specific positional evaluation and a deterministic tactical suite.
2. Add native Lichess KOTH parsing/configuration without widening accepted
   variants until the bridge tests pass.
3. Run mirrored KOTH matches against a fixed external reference.
4. Only then consider a separately branded Faloi executable/package.
