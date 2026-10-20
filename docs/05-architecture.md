# 05 · Architecture — Line 01

## System layout

```
                      phase 3 (planned): web dashboard
                 reads %QW telemetry over Modbus TCP :502
                                 ▲
                                 │
┌─────────────────────────────────────────────────────────────────┐
│  FLUXLINE runtime — program/fluxline.st                          │
│                                                                  │
│  inputs → debounce → state machine → piece tracker → diverters    │
│                ▲              │            │            │        │
│                │              ▼            ▼            ▼        │
│           E-stop chain    watchdogs      OEE        Modbus out    │
│             (NC)          (jam/stall)   counters   (telemetry)    │
└─────────────────────────────────────────────────────────────────┘
          ▲ %IX/%IW                                   │ %QX/%QW
          │ Modbus master requests                    │
┌─────────┴───────────────────────────────────────────▼────────────┐
│  sim/twin.py — digital twin (Modbus slave :1502)                  │
│  belt physics · piece queue · sensor emulation · outcome ledger   │
└──────────────────────────────────────────────────────────────────┘
```

## The verdict pipeline

1. **Register** — every rising edge of the photo-eye claims a tracker slot and
   positions a piece at 0 mm. Slots are a fixed 16-entry array; a FOR-loop
   scan costs microseconds at 10 ms cycle.
2. **Measure** — as the piece moves, the height curtain window keeps the max
   reading; the inductive probe latches one bit at its position; the load cell
   window keeps the max grams. Windows are physical beam/cell widths, not
   guesses.
3. **Decide** — at the end of the load-cell window the verdict locks:

   ```
   height >= tall        → 3  (L03 oversize)
   else metal            → 2  (L02 steel loop)
   else weight outside   → 4  (reject)
   else                  → 1  (L01 approved)
   ```

   Order is the law. Tall beats metal; metal beats weight-band. Same order as
   the reference web simulation, deliberately.
4. **Divert** — the matching diverter arms `prearm` mm before its gate, holds
   until the confirm photo-eye (or a 300 mm timeout), then the piece is
   counted and its slot freed. A piece that reaches the belt end unrouted is
   a missed piece (counter, not silent).
5. **Account** — A/P/Q accumulate continuously; no batch boundaries, no
   secrets.

## Drift immunity

Piece position integrates `belt speed × scan time` every scan. Real belts
slip, encoders sag, cycles jitter. The program therefore **re-syncs** piece
positions at every sensor crossing: the photo-eye defines position 0, the
curtain/probe/cell windows only open within a band of the expected arrival,
and a piece whose window opens while it is still in transit keeps tracking
until a later sensor. Missed diverts are visible (missed counter, alarm) —
they are never swallowed.

## Timing model

The program has no wall clock. All time is `scan_s` (config register
`%QW26`), the assumed scan period set once during commissioning. Watchdogs,
downtime accounting and the heartbeat all scale from it. Set it to your
runtime's actual cycle (Settings → Startup → cycle time; default 10 ms).

Deliberate consequences:

- Suspended or slowed scan ⇒ slower simulated time, never a spurious trip.
- Watchdog granularity = one scan; at 10 ms the 8 s jam window has
  0.125 % resolution.
- The heartbeat increments per second of scan-time — an HMI sees a frozen
  runtime as a frozen heartbeat.

## Scaling the line

| Change | Touch |
|---|---|
| 4th lane (L04) | add gate position + `verdict 5` branch, duplicate diverter block |
| Faster belt | raise `cfg_belt_mms`; widen HS/LC windows so sampling keeps ≥10 scans per piece |
| Two belts in series | instantiate the program per belt; split via the tracker at the transfer photo-eye |
| Different thresholds | Modbus writes to `%QW20..27`, no recompile |

The tracker array is the only fixed-size structure; 16 slots cover a 3.6 m
belt at 600 mm/s with 209 mm pitch six times over. Raising it is a one-line
change plus a commissioning re-check.

## Relationship to the web line

`github.com/SukrutN/fluxline` (phase 1) is the same machine as an editorial
web simulation — same geometry, same law, same OEE math, in TypeScript for
demonstration. This repo is the machine itself. Phase 3 (planned): the web
line reads this runtime's registers live over Modbus and becomes the actual
operator dashboard for the PLC line.
