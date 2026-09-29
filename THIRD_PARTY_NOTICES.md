# Third-party notices

Eloi is distributed under the MIT License. Substantial third-party portions
retain their original copyright and permission notices below and in their
vendored source directories.

## Morlock / original Eloi base

Copyright (c) 2021 Henning Rohde

The original work was provided under the MIT License. Its copyright and MIT
permission notice remain preserved in Eloi's history and this notice.

## Caissa 1.25

Copyright (c) 2021 Michał Witanowski

The currently preserved Caissa 1.25 source backend is provided under the MIT
License. Its complete license is retained alongside the vendored source under
`third_party/caissa125`.

## Viridithas 19.0.1 rewrite donor

Copyright (c) 2022-2025 Cosmo Bobak

Viridithas 19.0.1 is an MIT-licensed Rust chess engine selected as the proposed
Standard-search donor for the September rewrite. The exact source identity and
network licensing are recorded in `docs/SEPTEMBER_REWRITE.md`. No Viridithas
source or network is shipped in production until qualification is complete.
The Rust worker source is retained under `third_party/viridithas19` with its
complete MIT notice. Its matching `noumena` network is CC0, as explicitly
declared by <https://github.com/cosmobobak/viridithas-networks>. Benjamin Sago's
MIT notice is preserved in the donor's `src/term.rs`. Active dependencies retain
their MIT, Apache-2.0, Unlicense, and Unicode-3.0 notices. External C tablebases
are excluded and their build features are refused.
