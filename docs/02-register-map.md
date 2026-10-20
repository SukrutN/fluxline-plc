# 02 · Modbus Register Map — Line 01

The OpenPLC runtime serves a Modbus TCP server (default port **502**) and maps
the program's located variables onto it:

| Program area | Modbus area | Reference style | Master access |
|---|---|---|---|
| `%IX` | Discrete inputs | `0x` offsets, function code 02 | read-only |
| `%QX` | Coils | `0x` offsets, function code 01/05/15 | read/write |
| `%IW` | Input registers | `3xxxx` style, function code 04 | read-only |
| `%QW` | Holding registers | `4xxxx` style, function code 03/06/16 | read/write |

Both `0`-based protocol addresses and 1-based reference styles below refer to
the runtime's default (zero-mode) mapping. Verify against your runtime version
in commissioning step 4.

## Status word — `%QW2`

| Value | State | Meaning |
|---|---|---|
| 0 | INIT | power-on self-check |
| 1 | IDLE | ready, belt stopped |
| 2 | RUN | belt running, sorting |
| 3 | JAM | watchdog tripped, belt stopped, horn on |
| 4 | ESTOP | E-stop latched, everything off |

## Alarm word — `%QW3` (bit mask)

| Bit | Mask | Condition |
|---|---|---|
| 0 | 1 | JAM latched |
| 1 | 2 | E-stop latched |
| 2 | 4 | E-stop chain open right now |
| 3 | 8 | feed stall — no new piece for 20 s while RUN |
| 4 | 16 | piece tracker full |

## Telemetry — holding registers (read-write area, program-written)

| Register | Name | Unit / scale | Notes |
|---|---|---|---|
| `%QW0` | belt setpoint | raw 0..27648 = 0..600 mm/s | program-written |
| `%QW1` | heartbeat | increments 1/s, wraps 32000 | HMI supervision: any freeze is visible here |
| `%QW2` | state | 0..4 | see table above |
| `%QW3` | alarm | bit mask | see table above |
| `%QW4` | availability | per-mille 0..1000 | A = run/(run+down), 956 reads as 95.6% |
| `%QW5` | performance | per-mille 0..1000 | P = rolling pieces/min ÷ ideal, capped |
| `%QW6` | quality | per-mille 0..1000 | Q = routed/detected |
| `%QW7` | L01 count | pieces | signed 16-bit, wraps past 32767 |
| `%QW8` | L02 count | pieces | |
| `%QW9` | L03 count | pieces | |
| `%QW10` | reject count | pieces | |
| `%QW11` | detected | pieces | |
| `%QW12` | routed | pieces | |
| `%QW13` | pieces/min | rolling 60 s | |
| `%QW14` | belt speed | mm/s | derived from tacho, setpoint fallback |
| `%QW19` | version | 101 = 1.0.1 | handshake for HMI compatibility |

## Config — holding registers (write from HMI/HIL harness)

| Register | Name | Valid range | Default | Meaning |
|---|---|---|---|---|
| `%QW20` | tall threshold | 50..380 | 165 | mm, ≥ → L03 |
| `%QW21` | weight band min | 100..8000 | 2000 | g |
| `%QW22` | weight band max | 4000..29000 | 12000 | g, must exceed min |
| `%QW23` | jam watchdog | 1..60 | 8 | seconds of blocked photo-eye |
| `%QW24` | ideal rate | 1..200 | 34 | pieces/min, performance reference |
| `%QW25` | diverter pre-arm | 20..500 | 120 | mm before the gate |
| `%QW26` | scan period | 1..100 | 10 | ms — set to your runtime cycle |
| `%QW27` | belt speed | 20..590 | 120 | mm/s setpoint |

Out-of-range values are replaced by the compiled default each scan — a HMI
cannot put the line into an invalid law. Reset of the runtime restores zeros,
which resolve to defaults again.

## Physical I/O in the same server

Coils `%QX0.0..1.0` (offsets 0..8) mirror the physical outputs — read them to
watch the diverter pattern; discrete inputs `%IX0.0..1.0` (offsets 0..8) carry
the sensors. Input registers `%IW0/2/4` (protocol addresses 0, 2, 4) carry
height/weight/speed raw.

## Heartbeat discipline

An HMI or supervisor should read `%QW1` at ≥2 Hz and raise its own
"line silent" alarm if the value stops changing for 3 s. The program never
freezes this register while the scan is alive.
