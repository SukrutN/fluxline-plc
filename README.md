# FLUXLINE — Line 01 · PLC Program

[![CI](https://github.com/SukrutN/fluxline-plc/actions/workflows/ci.yml/badge.svg)](https://github.com/SukrutN/fluxline-plc/actions/workflows/ci.yml)

The machine itself. IEC 61131-3 Structured Text for the
[OpenPLC runtime](https://github.com/thiagoralves/OpenPLC_v3): a 3-way
conveyor sorting line with four sensors, three diverter gates, a reject
chute, a jam watchdog, an E-stop state machine and continuous OEE
accounting.

Companion to [SukrutN/fluxline](https://github.com/SukrutN/fluxline) — the
same line as an editorial web simulation (phase 1). This repo is the phase 2
program that actually runs the line. Same geometry, same verdict law, same
OEE math; one of them is a brochure, this one would be in a panel.

## The verdict law

Fixed order, decided at the load cell, identical to the web line:

```
height >= 165 mm             ->  L03  OVERSIZE
else metal detected          ->  L02  STEEL LOOP
else weight outside 2..12 kg ->  RJ   REJECT
else                         ->  L01  APPROVED
```

## Belt geometry

```
 0     500    1200    1900    2600    2900   3100   3300   3500  3600 mm
 PE ────●──────HS──────ID──────LC──────RJ─────L01────L02────L03─┤ end
 register height    metal   weight  push  divert divert divert
```

## What's here

```
program/fluxline.st      the program - upload to the OpenPLC runtime
docs/01-io-map.md        every sensor, solenoid, lamp and terminal
docs/02-register-map.md  Modbus registers: state, alarms, OEE, config
docs/03-commissioning.md install → upload → closed loop → calibrate → go-live
docs/04-safety.md        what the software E-stop is, and is not
docs/05-architecture.md  state machine, drift immunity, scaling to more lanes
sim/twin.py              digital twin - Modbus slave with belt physics
sim/scenarios.py         scripted runs (mixed batch, jam, E-stop)
sim/test_scenarios.py    offline: the law itself
sim/test_line.py         live: the runtime against the twin
```

## Quickstart

```bash
git clone https://github.com/SukrutN/fluxline-plc.git
cd fluxline-plc
pip install -r sim/requirements.txt
pytest sim/test_scenarios.py        # offline, passes without a PLC
```

Then the closed loop, no hardware:

1. Install the [OpenPLC runtime](https://github.com/thiagoralves/OpenPLC_v3)
   and upload `program/fluxline.st` (web UI on :8080).
2. Configure its **Modbus master** to poll the twin at `127.0.0.1:1502`
   — exact requests in `docs/03-commissioning.md` §5.
3. `python sim/twin.py` — pieces start flowing.
4. `pytest sim/test_line.py` — the runtime's actual verdicts, asserted.

## Design choices that matter

- **Single POU, sectioned.** The OpenPLC runtime uploads one `.st`, and the
  program deliberately sticks to the syntax surface every matiec build
  accepts — no derived types or user function blocks between the program and
  its I/O. Body is organized as banner-commented sections 0-8 so review is
  still practical.
- **No wall clock in the PLC.** All timing derives from the configured scan
  period — slow scans slow the sim, never cause spurious watchdog trips.
- **Sensor re-sync beats dead reckoning.** Piece positions re-sync at every
  physical crossing; drift from belt slip cannot accumulate into a missed
  divert silently — misses are counted and alarmed.
- **Config over Modbus, clamped.** Thresholds, watchdog and belt speed are
  writable at runtime (`%QW20..27`) with sane clamps; a HMI cannot corrupt
  the law, and a zero-config boot runs on compiled defaults.
- **Fail-safe polarity.** The E-stop chain reads TRUE when healthy; a broken
  wire is an E-stop, not a nice surprise.
- **Honest OEE.** Availability counts only JAM/ESTOP as downtime (deliberate
  IDLE is not downtime), performance is rolling pieces/min against ideal,
  quality is routed/detected — misses poison quality, as they should.

## CI

Every push compiles `fluxline.st` with [matiec](https://github.com/beremiz/matiec)
— the exact compiler the runtime uses — and runs the offline twin tests.
A program that doesn't compile doesn't merge. The live suite runs wherever an
OpenPLC runtime is available; it skips (never fails) without one.

## Status

- v1.0.1 — the program, docs, twin, offline tests, CI compile gate.
- Phase 3 (planned): the FLUXLINE web line reads this runtime's registers
  over Modbus and becomes its live operator dashboard.

## ST compiler notes (the gotchas CI caught)

Every push compiles the program with matiec — the exact compiler the runtime
uses. These are the syntax landmines it caught during bring-up, kept here so
the next author doesn't re-learn them:

1. **Single POU.** A user `FUNCTION_BLOCK` or `TYPE` declaration before the
   program poisons located-variable parsing (`pe AT %IX0.0 : BOOL`) in
   beremiz/matiec. The library's own FBs are fine — they parse in a separate
   session. Keep everything in one `PROGRAM`, use the library FBs (TON, CTU…)
   directly.
2. **One VAR block, one kind.** The first declaration decides how the whole
   `VAR…END_VAR` section is parsed. Put all located variables (`AT %IX…`/`%QW…`)
   in their own block, plain variables and library FB instances in another.
3. **IEC identifiers are case-insensitive.** `tOn : TON` names an instance
   with the *keyword* `TON` — the compiler reads it as a type, not a name.
4. **Typed literals in expressions.** `alarm_w OR 1` fails: `OR` is defined
   for `ANY_BIT` (BOOL and bitstrings), not INT. Declare status words as
   `WORD` and write `WORD#1`.
5. **No BOM.** A UTF-8 BOM at the top of the file makes matiec *silently*
   compile an empty program — no error, all-zero output. Save as plain UTF-8.

## Runtime bring-up notes (verified against live OpenPLC v3)

Two things bit us on the first live run against a real runtime. Kept here so
they never bite again:

1. **The file must end in a CONFIGURATION/RESOURCE wrapper.** The runtime
   compiles the uploaded `.st` standalone (`iec2c -f -l -p -r -R -a`); only a
   file that carries its own `CONFIGURATION … RESOURCE … PROGRAM … WITH … :
   <name>` task binding yields the `Config0.c`/`Res0.c` the core links
   against. `fluxline.st` ships this wrapper at the bottom — leave it there.
2. **Modbus-master locators are wire address + 100.** The runtime stages a
   master device's registers in its buffer region starting at index 100
   (`updateBuffersIn_MB`/`updateBuffersOut_MB` in
   `webserver/core/modbus_master.cpp`), so inside the ST program every
   located variable carries the register's wire address plus 100 —
   `%IX100.0` for DI 0, `%IW100/102/104` for IR 0/2/4, `%QX100.0…` for
   coils, `%QW101` for HR 1. Everything else (device config in the web UI,
   `docs/*.md`, the twin, the HMI) speaks plain wire addresses. Locators
   written 0-based compile fine and run forever — with the master then
   writing nothing but zeros to the device. Ask us how we know.
3. **A rig-line starts in ESTOP.** The runtime's very first scans run while
   no master is connected, so on a simulated chain every DI reads open and
   the chain fault latches — correct fail-safe behavior, wrong-looking
   quiet red lamp. The first start press clears the latch, the second
   starts the belt. `scenarios.start_line()` encodes the press-until-RUN
   dance so tests and the CLI cannot diverge.

Building the runtime itself on a modern toolchain (Ubuntu 26.04, CMake ≥ 4,
GCC 15) takes two deviations from its installer: run the `disable_opendnp3`
path before installing the libraries, and pass
`-DCMAKE_POLICY_VERSION_MINIMUM=3.5` to every `cmake` call (matiec,
libmodbus, snap7, webserver). After that the master polls the twin happily.

## License

MIT — see [LICENSE](LICENSE).
