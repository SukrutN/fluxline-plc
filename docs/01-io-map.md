# 01 · I/O Map — Line 01

All signals on 24 VDC, PNP sourcing (sensors), 24 V sink (outputs) unless noted.
`%I`/`%Q` addresses are the OpenPLC logical addresses the ST program uses.
Bind them to your board's physical terminals with the OpenPLC runtime board
profile (see `docs/03-commissioning.md`, step 3).

## Digital inputs

| Address | Signal | Device | Behavior | Notes |
|---|---|---|---|---|
| `%IX0.0` | PE · photo-eye | Through-beam IR across the belt, first station | TRUE while a piece interrupts the beam | Registration edge: every rising edge creates a tracked piece |
| `%IX0.2` | ID · inductive | Eddy-current / inductive probe under the belt | TRUE while a ferrous piece is over the probe | Sampled once, when a piece crosses the probe position |
| `%IX0.4` | E-stop chain | NC contacts in series, all E-stop buttons + guards | **TRUE = chain healthy. FALSE = tripped.** | Fail-safe polarity: broken wire reads FALSE. Never debounced |
| `%IX0.5` | PB start | Momentary green pushbutton | Pulse to start from IDLE | Debounced 50 ms in program |
| `%IX0.6` | PB stop | Momentary red pushbutton | Pulse to stop from RUN | Debounced 50 ms in program |
| `%IX0.7` | Gate confirm | Photo-eye just past the lane gates | TRUE while a diverted piece passes | Completes a divert; timeout is the fallback |
| `%IX1.0` | Chute PE | Photo-eye in the reject chute | TRUE while a rejected piece falls | Confirms reject pushes |

## Analog inputs

| Address | Signal | Device | Raw range | Engineering |
|---|---|---|---|---|
| `%IW0` | Height | Light curtain / laser rangefinder over the belt at HS | 0..27648 | 0..400 mm |
| `%IW2` | Weight | Load cell amplifier at LC | 0..27648 | 0..30000 g |
| `%IW4` | Belt speed | VFD tacho / encoder feedback | 0..27648 | 0..600 mm/s |

Raw full scale is Siemens-style 27648. If your hardware uses another span
(e.g. 65535), adjust the `raw_max` working value in the program or keep the
raw register convention and re-scale at the sensor amplifier.

## Digital outputs

| Address | Signal | Device | Notes |
|---|---|---|---|
| `%QX0.0` | Belt run | VFD enable contactor | Driven TRUE only in state RUN |
| `%QX0.1` | Div L01 | Diverter solenoid, lane 01 | Arms `cfg_prearm` mm before the piece |
| `%QX0.2` | Div L02 | Diverter solenoid, lane 02 | |
| `%QX0.3` | Div L03 | Diverter solenoid, lane 03 | |
| `%QX0.4` | Reject pusher | Air pusher at the reject gate | Confirms via chute PE |
| `%QX0.5` | Stack green | Stack light | RUN, no active alarm |
| `%QX0.6` | Stack amber | Stack light | INIT / IDLE |
| `%QX0.7` | Stack red | Stack light | JAM / ESTOP |
| `%QX1.0` | Horn | Alarm horn | Steady in JAM, 0.5 s blip on start |

## Analog outputs

| Address | Signal | Device | Raw range | Engineering |
|---|---|---|---|---|
| `%QW0` | Belt speed setpoint | VFD speed reference | 0..27648 | 0..600 mm/s |

Default setpoint: 120 mm/s (7.2 m/min), written every scan.

## Notes

- **Input polarity is part of the contract.** If you wire an E-stop channel
  N/O instead of N/C, the program reads a healthy chain as tripped — fix the
  wiring, not the program.
- Outputs are re-asserted every scan. A frozen runtime holds the last outputs
  for a moment; the hardware E-stop chain is the only certified stop path
  (`docs/04-safety.md`).
- Piece pitch on the reference line: ~209 mm at 120 mm/s → 34 pieces/min ideal.
