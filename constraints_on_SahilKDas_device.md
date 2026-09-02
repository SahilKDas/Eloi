# Constraints on SahilKDas's Device

This file is the binding local resource contract for developing, training,
testing, packaging, and running Eloi on SahilKDas's laptop. Its purpose is to
protect the machine's storage, responsiveness, and active Lichess sessions.
These limits apply even when a larger workload would improve Eloi. Only
SahilKDas may explicitly relax them.

## Hardware snapshot

Snapshot taken on 2026-09-01. Free disk space and driver versions are
point-in-time values.

| Component | Verified specification |
| --- | --- |
| Laptop | HP Pavilion Laptop 15-eg2xxx |
| CPU | 12th Gen Intel Core i7-1255U; 10 physical cores, 12 logical processors |
| Memory | 16,831,832,064 bytes installed (about 15.68 GiB visible to Windows) |
| Discrete GPU | NVIDIA GeForce MX550; 2 GiB reported VRAM |
| Integrated GPU | Intel Iris Xe Graphics |
| Operating system | Microsoft Windows 11 Home, 64-bit; version 10.0.26200, build 26200 |
| System drive at snapshot | 510,770,802,688 bytes total; 31,862,267,904 bytes free |

The integrated GPU memory reported by Windows is shared system memory, so it
must not be treated as an additional dedicated 2 GiB training budget.

## Hard limits

| Resource or activity | Limit |
| --- | --- |
| Eloi engine search | Exactly 3 search threads per engine process |
| All temporary project data combined | At most 10,000,000,000 bytes (10 GB) at any instant |
| Temporary NNUE training data and artifacts | At most 8,000,000,000 bytes (8 GB) at any instant, included inside the 10 GB total cap |
| Concurrent Lichess bridge processes | At most 2 |
| Concurrent Eloi GUI processes | At most 2 |
| Raspberry Pi emulation or heavy Linux/ARM environments | Do not create or run them on this laptop without new explicit permission |

The 8 GB training allowance is a subset of the 10 GB total temporary-data
allowance, not an additional allowance. For example, 8 GB of training data
leaves at most 2 GB for every other temporary Eloi file combined. Existing
stricter limits remain valid: the NNUE trainer currently caps itself at 7 GiB,
and a task must obey whichever applicable limit is lower.

## What counts as temporary data

The 10 GB total includes all disposable data created or downloaded for an Eloi
task, regardless of which directory or drive contains it:

- compiler, linker, LTO, CMake, and build-tree scratch data;
- downloaded archives, extracted dependency copies, and temporary toolchains;
- training inputs, sampled positions, intermediate tensors, candidate networks,
  checkpoints, caches, and training logs;
- match PGNs, generated suites, benchmark output, screenshots, crash dumps, and
  other generated validation evidence that is not intended to be retained;
- package staging directories, extracted ZIP copies, and duplicate release
  candidates.

Checked-in source files and deliberately retained, hash-pinned dependencies are
not temporary merely because they support a build. A new task must still count
any disposable copies it creates from them. When classification is unclear,
count the data toward the cap.

Before a storage-heavy task begins, estimate its peak usage and measure current
temporary usage. During the task, enforce a hard quota before writes whenever
practical. Stop before either cap would be exceeded; do not rely on cleanup
after an overrun. Delete disposable staging and temporary data when the task is
complete, while preserving tracked source, reproducibility records, and test
evidence that the repository intentionally keeps.

## CPU and process rules

- Eloi's production search contract is fixed at exactly three threads. Do not
  silently raise the UCI thread count, helper count, or parallel-search lane
  count.
- Do not run multiple CPU-heavy gauntlets or training jobs concurrently unless
  SahilKDas explicitly authorizes that specific run.
- Keep long background matches and benchmarks bounded. When foreground use or a
  Lichess bridge is active, use Windows Idle priority for background gauntlets
  where supported.
- Very deep fixed-depth searches can take hours on this device. Depth ladders
  and matches must have declared time, game-count, and storage bounds rather
  than running indefinitely.
- Never exceed two bridge processes or two GUI processes. The limits are per
  category, not a shared total: two bridges plus two GUIs is permitted, while
  three bridges or three GUIs is not.

## Protect active Lichess play

Do not interrupt a running Lichess bridge merely to build, test, install, or
replace Eloi. For a bridge upgrade:

1. Leave the active bridge untouched.
2. Start at most one replacement, staying within the two-bridge limit.
3. Confirm that the replacement starts correctly and reaches Lichess.
4. Only then close the old bridge.

Avoid builds, installs, cleanup commands, or process-wide termination that can
overwrite an executable used by the active bridge, kill its process tree, or
remove its configuration. Never expose, copy into a release, or commit the
private token stored in the ignored local `config.yml`.

## GUI visibility

When SahilKDas asks to watch engine games or GUI tests, launch the GUI visibly
and do not hide it in the background. Headless correctness tests are still
allowed when no visible GUI was requested. A visible test does not override the
two-GUI limit.

## Local build and release storage

- Treat `dist/current` as a rolling release-candidate directory, not an archive.
- Keep only the newest required Windows candidate packages there: the
  standalone ZIP and the split-runtime **Exoskeleton ZIP**.
- Remove obsolete local candidate folders, extracted package duplicates, and
  superseded build scratch after they are no longer needed.
- Do not delete tracked validation evidence, reproducibility manifests, the
  active configuration, or a binary currently used by a bridge.

## Preflight and completion checklist

Before a resource-heavy task:

1. Confirm the projected peak stays within both the 10 GB total cap and, when
   applicable, the nested 8 GB training cap.
2. Confirm no conflicting training or gauntlet is already running.
3. Count active bridge and GUI processes.
4. Protect the live bridge and keep the laptop usable for foreground work.
5. State bounds for game count, time, and generated storage.

After the task:

1. Verify correctness before retaining a candidate.
2. Remove disposable temporary data and obsolete local build duplicates.
3. Re-measure temporary storage when the task was storage-heavy.
4. Leave only current required candidate packages under `dist/current`.

This document is intentionally tracked by Git and must not be added to
`.gitignore`.
