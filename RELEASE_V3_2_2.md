# Eloi v3.2.2

Eloi v3.2.2 adds an explicit Standard-chess brain choice to the native GUI
and promotes E4-10 as Eloi's native neural evaluator. Caissa 1.25 remains the
default Standard brain and the default for UCI and native Lichess play.

## Highlights

- Adds **Caissa 1.25** and **Eloi E4-10** choices to the native GUI's Standard
  game setup.
- Promotes the hash-verified E4-10 network for Eloi-native play, variants, and
  Caissa crash fallback.
- Keeps Chess960 and Horde on the Eloi-native route.
- Preserves Caissa 1.25 as the default Standard choice and does not change the
  production UCI or Lichess routing.

## Strength evidence

E4-10 was selected over E4-20 after 400 direct games. E4-10 scored
205.5/400 (51.375%) with 129 wins, 153 draws, and 118 losses. This establishes
the selected Eloi-native mode; it is not a claim that E4-10 is stronger than
the default Caissa 1.25 Standard brain.

## Network identity

The promoted E4-10 header SHA-256 is
`4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88`.
The selected checkpoint SHA-256 is
`D613B853FE534B6AD3604080E559DB26D9CCC55E124005FE60B9ABBCD508EE99`.

## Packages

The release consists of the reproducibly built Windows x64 standalone and
Exoskeleton ZIPs. Both retain the bundled Caissa attribution and network
identity. No runtime download is used.
