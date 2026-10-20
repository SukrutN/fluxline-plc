# 03 · Commissioning Guide — Line 01

From a clean machine to a closed-loop line with zero hardware attached.
Times are realistic: ~30 min for the software path, a shift for the physical one.

## 1 · Install the runtime

Linux (reference):

```bash
git clone https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3
./install.sh linux
```

Start it: `sudo systemctl start openplc` (or `./openplc_runtime` from the
install dir). Web UI: **http://localhost:8080** — default login
`openplc / openplc`. Change it before anything touches a network.

## 2 · Upload the program

1. Web UI → **Programs** → choose `program/fluxline.st` → Upload.
2. The runtime compiles the file with matiec and restarts the scan.
3. **Compiler output must be clean.** Any error here means the program does
   not match your runtime's matiec version — check `version_w` is reachable
   first via the debug table before touching real hardware.

## 3 · Select the board profile

Web UI → **Hardware** → pick the profile that matches your I/O:

- `Blank` — generic Linux I/O, simulation-friendly
- `RaspberryPi` / `UniPi` / `MicroBox` / your DIN-rail PLC's profile

The program addresses I/O by `%IX`/`%QX` logical numbers; the board profile
decides which physical terminal each number lands on. Fill in your terminal
map against `docs/01-io-map.md`.

## 4 · Prove the Modbus map

Before wiring anything: read `%QW19` (version register) with any Modbus
client — `mbpoll`, a Python one-liner, or the harness twin's probe:

```bash
python -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('localhost',502); c.connect(); print(c.read_holding_registers(19,1).registers)"
```

Expected: `[101]`. If your runtime serves a different offset convention,
align the register map in `docs/02-register-map.md` to what you measure and
note the delta in your commissioning record.

## 5 · Closed loop with the digital twin (no hardware)

The twin is a Modbus **slave** that simulates the sensors, belt and pieces;
the OpenPLC runtime is configured as Modbus **master** polling it. The loop:

```
   ┌────────────────────┐   Modbus TCP :1502   ┌──────────────────────┐
   │  FLUXLINE runtime   │ ───────────────────▶ │  twin.py (slave)     │
   │  fluxline.st        │ ◀─────────────────── │  belt + piece physics │
   └────────────────────┘   reads DI/IR,      └──────────────────────┘
                             writes CO/HR
```

Runtime side — Web UI → **Settings → Modbus Master** (or `ModbusEdit`):

1. Add slave: `127.0.0.1:1502`, protocol TCP, node ID 1.
2. Add four requests:
   - **Read Discrete Inputs**, offset 0, count 16 → binds to `%IX0.0..`
   - **Read Input Registers**, offset 0, count 8 → binds to `%IW0..`
   - **Write Coils**, offset 0, count 16, source `%QX0.0..`
   - **Write Holding Registers**, offset 0, count 32, source `%QW0..`
3. Save and restart the runtime.

Harness side:

```bash
pip install -r sim/requirements.txt
python sim/twin.py                  # serves :1502, feeds pieces
```

Then start the line: pulse start (`sim/scenarios.py` does this, or write coil
5). Watch `%QW2` go 0→1→2. Pieces flow; lane coils fire per the verdict law.

## 6 · Scenario tests

```bash
pytest sim/test_scenarios.py -v     # offline: validates expectations against the law
pytest sim/test_line.py -v          # live: needs runtime + twin running
```

`test_line.py` skips with a clear reason when the runtime isn't up — CI and
fresh clones never fail on a missing PLC.

## 7 · Calibration (physical line)

1. **Belt speed** — command 120 mm/s, measure actual travel with a tape over
   10 s, adjust `cfg_belt_mms` and the VFD scaling until measured = commanded
   within ±2 %. Position tracking re-syncs at every sensor, so small drift is
   absorbed; large drift causes missed diverts (alarm bit 0 of `%QW3`... see
   the missed counter `%QW12` vs detected).
2. **Height** — pass pieces of known height (100 / 165 / 200 mm shims) over
   HS. Adjust `height_max` scaling in the program or the transmitter span so
   the latch reads within ±2 mm.
3. **Weight** — place certified 2 kg and 12 kg masses on the cell at rest,
   tune the transmitter span for `%IW2`. Band edges have 100 g resolution.
4. **Jam watchdog** — stop a piece over the photo-eye manually; the line must
   trip to JAM after `cfg_jam_s` (8 s). Verify the horn and red lamp, then
   reset with the start button.
5. **E-stop chain** — press a real E-stop button. Belt must drop immediately
   (same scan), state 4, chain-open alarm bit. Restore chain, press start to
   clear the latch.

## 8 · Go-live checklist

- [ ] `version_w` reads 101 from Modbus
- [ ] All E-stop devices open the chain (test each one)
- [ ] Watchdog trips within 8 s of a real jam
- [ ] Each lane receives a piece of its verdict class (10 pieces each)
- [ ] Reject chute catches 10 consecutive off-band pieces
- [ ] `heartbeat` advances while the HMI supervises
- [ ] Downtime accounting checked after a deliberate stop/restart cycle
- [ ] Guard doors interlocked into the E-stop chain (physical, not software)
