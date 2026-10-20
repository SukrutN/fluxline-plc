# FLUXLINE — Line 01 · PLC Program

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

## License

MIT — see [LICENSE](LICENSE).
