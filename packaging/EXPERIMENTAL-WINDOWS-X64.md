# Eloi experimental Windows x64 split-runtime package

This ZIP is an experimental companion to Eloi v1.0.0-rc.2. It does not replace
the canonical standalone `Eloi.exe` and `config.yml` release assets.

Keep the entire extracted directory together. Its components are deliberately
split to test antivirus classification of the monolithic standalone build:

- `Eloi.exe` contains the GUI, UCI engine, perft, and benchmark modes. It has
  no native Lichess implementation and does not import WinHTTP.
- `EloiLichess.exe` is the separate native Lichess bridge. It is the only Eloi
  executable in this package that imports WinHTTP.
- `libgcc_s_seh-1.dll`, `libstdc++-6.dll`, and `libwinpthread-1.dll` are the
  exact hash-pinned MSYS2 UCRT64 runtime libraries required by both programs.
- `assets/chess_maestro_bw` contains the twelve external PNG chess pieces and
  their CC BY 4.0 attribution.
- `config.yml` contains an intentionally blank token. Add your Bot API token
  only to your private extracted copy.
- `licenses` contains Eloi and redistributed dependency license notices.
- `SOURCE_COMMIT.txt` records the exact post-tag source revision used for this
  experimental variant, while `SHA256SUMS.txt` covers every packaged file.

Double-click `Eloi.exe` for the GUI, or run UCI mode with:

```powershell
.\Eloi.exe --uci
```

For native Lichess operation, double-click `EloiLichess.exe`. Its native
configuration window edits `config.yml` without opening Notepad or a development
editor. Choose **Save & Start Bot** when ready. For unattended startup after the
file has been configured, run:

```powershell
.\EloiLichess.exe --run
```

Running `Eloi.exe --lichess` intentionally refuses and points to the separate
bridge. The Python lichess-bot workflow may still use `Eloi.exe --uci`.

This package is unsigned and experimental. Do not disable antivirus protection
or bypass a warning. Report which individual file is detected; separating the
network client is intended to make that result diagnostically useful.
