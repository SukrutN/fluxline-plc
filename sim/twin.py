"""FLUXLINE digital twin - Modbus slave standing in for the physical line.

The OpenPLC runtime (configured as Modbus master) polls this server:

    reads   discrete inputs   %IX0.0..1.0   PE, ID, E-stop chain, PBs, confirms
            input registers   %IW0/2/4     height, weight, belt speed raw
    writes  coils             %QX0.0..1.0   belt run, diverters, lamps, horn
            holding regs      %QW0..27      setpoint, telemetry, config

Belt physics run at 30 Hz in a background thread. Pieces are spawned on a
timer or scripted by the scenario API. Every divert the runtime performs is
recorded, so pytest can assert that the PLC's verdicts match the law.

Run standalone:  python twin.py          (serves :1502, feeds pieces)
Use in tests:    from twin import Twin; t = Twin(); t.start()
"""

import asyncio
import json
import os
import random
import threading
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
try:
    from pymodbus.server.async_io import ModbusTcpServer   # pymodbus >= 3.0
    SERVER_ASYNC = True
except ImportError:                                      # pragma: no cover
    try:
        from pymodbus.server.sync import ModbusTcpServer  # pymodbus 2.x
        SERVER_ASYNC = False
    except ImportError:
        ModbusTcpServer = None                            # no backend
        SERVER_ASYNC = None

# ---------------------------------------------------------------- geometry

PE_POS = 0.0        # mm, registration photo-eye
HS_POS = 1200.0     # height curtain
ID_POS = 1900.0     # inductive probe
LC_POS = 2600.0     # load cell
G_RJ, G_L1, G_L2, G_L3 = 2900.0, 3100.0, 3300.0, 3500.0
BELT_LEN = 3600.0

RAW_MAX = 27648
HEIGHT_MAX = 400.0
WEIGHT_MAX = 30000.0
SPEED_MAX = 600.0

LANE_NAMES = {1: "L01", 2: "L02", 3: "L03", 4: "RJ"}


def expected_lane(piece):
    """The verdict law, stated once, so the harness cannot drift from docs."""
    if piece["height"] >= 165.0:
        return 3
    if piece["metal"]:
        return 2
    if piece["weight"] < 2000.0 or piece["weight"] > 12000.0:
        return 4
    return 1


def profiles():
    """Piece factories. Ranges sit clear of the band edges (that is a
    calibration question, not a logic question - see scenarios.py)."""
    return {
        "standard": dict(height=random.uniform(90, 160), weight=random.uniform(3000, 9000), metal=False),
        "metal":    dict(height=random.uniform(90, 160), weight=random.uniform(4000, 10000), metal=True),
        "tall":     dict(height=random.uniform(170, 260), weight=random.uniform(4000, 7600), metal=False),
        "light":    dict(height=random.uniform(90, 160), weight=random.uniform(800, 1400), metal=False),
        "heavy":    dict(height=random.uniform(90, 160), weight=random.uniform(14000, 26000), metal=False),
        "jam":      dict(height=120.0, weight=5000.0, metal=False, jam=True),
    }


class Twin:
    """Digital twin: Modbus slave + belt physics + outcome ledger."""

    def __init__(self, port=1502, feed=True, pitch_s=1.75, seed=None):
        self.port = port
        self.auto_feed = feed
        self.pitch_s = pitch_s

        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.thread = None
        self.server_thread = None

        self.store = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * 32),
            co=ModbusSequentialDataBlock(0, [0] * 32),
            hr=ModbusSequentialDataBlock(0, [0] * 32),
            ir=ModbusSequentialDataBlock(0, [0] * 32),
            zero_mode=True,
        )
        self.context = ModbusServerContext(slaves=self.store, single=True)

        self.pieces = []           # live pieces on the belt
        self.results = []          # completed pieces (the ledger)
        self.missed = 0
        self.seq = 0
        self.last_spawn = time.time()

        self.pb_start_until = 0.0
        self.pb_stop_until = 0.0
        self.estop_ok = True
        self.feed_enabled = True
        self.confirm_until = 0.0
        self.chute_until = 0.0
        self.belt_run = False
        self.sp_mms = 120.0
        # server lifecycle state (start()/close() manage these) - note the
        # deliberate use of _srv_loop: _loop is this class's physics loop
        # method, and Thread(target=self._loop) binds it at start()
        self.server = None
        self._srv_loop = None
        self._ready = threading.Event()
        self._serve_error = None

    # ------------------------------------------------ lifecycle

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.server_thread = threading.Thread(target=self._serve, daemon=True)
        self.server_thread.start()
        self.thread.start()
        # pymodbus builds its asyncio server inside this thread (its base
        # class requires a running loop); wait until the port is bound or
        # the server thread gave up, so failures surface as exceptions here
        if not self._ready.wait(5.0):
            detail = "" if self._serve_error is None else f" - {self._serve_error!r}"
            raise RuntimeError(
                f"twin Modbus server did not bind 127.0.0.1:{self.port} "
                f"in 5 s{detail}")
        time.sleep(0.2)

    def _serve(self):
        """Run the Modbus server on an event loop this instance owns.

        Ownership matters: a bare ``StartTcpServer`` in a daemon thread can
        only be stopped by killing the whole process, so back-to-back twins
        (pytest fixtures) would all fail to rebind the port while the first
        twin's orphaned server kept serving a dead context."""
        try:
            if ModbusTcpServer is None:
                raise RuntimeError("no pymodbus server backend is importable")
            if SERVER_ASYNC:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._srv_loop = loop

                async def _run():
                    srv = ModbusTcpServer(
                        self.context, address=("127.0.0.1", self.port))
                    await srv.listen()        # the port is actually bound here
                    self.server = srv
                    self._ready.set()          # announce only once bind succeeded
                    await srv.serving          # returns when shutdown() completes

                loop.run_until_complete(_run())
            else:
                self.server = ModbusTcpServer(
                    context=self.context, address=("127.0.0.1", self.port))
                self._ready.set()
                self.server.serve_forever()
        except Exception as exc:                        # pragma: no cover
            self._serve_error = exc
            self._ready.set()
            print(f"[twin] server thread ended: {exc}")

    def close(self):
        self.stop_evt.set()
        time.sleep(0.1)
        server, loop = self.server, self._srv_loop
        self.server = None
        self._srv_loop = None
        if server is not None:
            try:
                if SERVER_ASYNC and loop is not None:
                    fut = asyncio.run_coroutine_threadsafe(
                        server.shutdown(), loop)
                    fut.result(timeout=3.0)
                else:
                    server.shutdown()
            except Exception as exc:                    # pragma: no cover
                print(f"[twin] server shutdown error: {exc}")
            finally:
                if self.server_thread is not None:
                    self.server_thread.join(timeout=3.0)

    # ------------------------------------------------ scenario API

    def spawn(self, kind="standard"):
        """Not locked on purpose: called from _step while the lock is held,
        and from tests where the physics thread is idle. List append is
        atomic in CPython."""
        if kind == "mix":
            kind = self.rng.choice(["standard", "standard", "metal", "tall", "light", "heavy"])
        prof = dict(profiles()[kind])
        prof["kind"] = kind
        prof["len"] = self.rng.uniform(100, 200)
        prof["pos"] = -30.0        # front edge just short of the PE beam
        prof["id"] = self.seq
        self.seq += 1
        self.pieces.append(prof)
        return prof["id"]

    def clear_jam(self):
        """Remove the wedged piece - the physical equivalent of pulling it out."""
        with self.lock:
            for p in [p for p in self.pieces if p.get("pinned")]:
                self.pieces.remove(p)

    def pulse_start(self, s=0.25):
        self.pb_start_until = time.time() + s

    def pulse_stop(self, s=0.25):
        self.pb_stop_until = time.time() + s

    def open_estop(self):
        self.estop_ok = False

    def close_estop(self):
        self.estop_ok = True

    def set_feed(self, on):
        self.feed_enabled = on

    # ------------------------------------------------ ledger

    def snapshot(self):
        with self.lock:
            return {
                "pieces": list(self.results),
                "missed": self.missed,
                "counts": {
                    LANE_NAMES[l]: sum(1 for p in self.results if p["lane_got"] == l)
                    for l in LANE_NAMES
                },
            }

    def flush(self, path=None):
        path = path or os.path.join(os.path.dirname(__file__), "results.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.snapshot(), f, indent=2)
        return path

    # ------------------------------------------------ physics

    def _co(self, addr):
        return bool(self.store.getValues(1, addr, 1)[0])

    def _hr(self, addr, n=1):
        return self.store.getValues(3, addr, n)

    def _set_di(self, addr, val):
        self.store.setValues(2, addr, [1 if val else 0])

    def _set_ir(self, addr, val):
        self.store.setValues(4, addr, [int(val) & 0xFFFF])

    def _loop(self):
        dt = 1.0 / 30.0
        while not self.stop_evt.is_set():
            t0 = time.time()
            try:
                self._step(dt)
            except Exception as exc:      # keep the twin alive through glitches
                print(f"[twin] step error: {exc}")
            elapsed = time.time() - t0
            self.stop_evt.wait(max(0.0, dt - elapsed))

    def _step(self, dt):
        now = time.time()
        with self.lock:
            self.belt_run = self._co(0)
            divs = {l: self._co(addr) for l, addr in
                    ((1, 1), (2, 2), (3, 3), (4, 4))}
            sp_raw = self._hr(0, 1)[0]
            self.sp_mms = max(20.0, min(590.0, sp_raw * SPEED_MAX / RAW_MAX)) if sp_raw else 120.0

            belt_v = self.sp_mms if self.belt_run else 0.0

            # spawn on the feed timer
            if self.auto_feed and self.feed_enabled and now - self.last_spawn >= self.pitch_s:
                self.last_spawn = now
                self.spawn("mix")

            # advance pieces
            for p in self.pieces:
                if p.get("pinned"):
                    continue
                p["pos"] += belt_v * dt
                if p["kind"] == "jam" and p["pos"] >= 30.0:
                    p["pinned"] = True       # wedged in front of the photo-eye

            # sensors
            # sensors - the PE is a through-beam at position 0, blocked while
            # a piece's body covers it. The rising edge is therefore the front
            # edge at 0.0, which is precisely the anchor the runtime's
            # dead-reckoned tracker slots assume (slot pos starts at 0).
            pe = any(0.0 <= p["pos"] <= p["len"] or p.get("pinned")
                     for p in self.pieces)
            self._set_di(0, pe)
            metal_here = any(p["metal"] and abs(p["pos"] - ID_POS) < 60 for p in self.pieces)
            self._set_di(2, metal_here)
            self._set_di(4, self.estop_ok)
            self._set_di(5, now < self.pb_start_until)
            self._set_di(6, now < self.pb_stop_until)

            # sensor exposures mirror the runtime's sampling windows
            # (hs_win 80 / lc_win 120 in the program), guarded by 20 mm so
            # every value the runtime max-tracks stays valid for its whole
            # window even with master-cycle latency
            height_p = next(
                (p for p in self.pieces
                 if HS_POS - 20 <= p["pos"] <= HS_POS + 100), None)
            self._set_ir(0, height_p["height"] / HEIGHT_MAX * RAW_MAX if height_p else 0)
            weight_p = next(
                (p for p in self.pieces
                 if LC_POS - 20 <= p["pos"] <= LC_POS + 140), None)
            self._set_ir(2, weight_p["weight"] / WEIGHT_MAX * RAW_MAX if weight_p else 0)
            self._set_ir(4, self.sp_mms / SPEED_MAX * RAW_MAX if belt_v > 0 else 0)

            # diverters: whichever coil fires while a piece is in its window
            # moves that piece off the belt - the twin does not know verdicts,
            # the runtime alone decides, which is the point of the exercise.
            confirm_now = False
            for lane, addr in ((1, 1), (2, 2), (3, 3), (4, 4)):
                if not divs[lane]:
                    continue
                gate = {1: G_L1, 2: G_L2, 3: G_L3, 4: G_RJ}[lane]
                # the grab is the FRONT crossing the gate point: the runtime
                # pre-arms the coil 120 mm before the front and holds it
                # until this piece's confirm, so at the crossing the arm is
                # always up. The window stays tight so ownership is unique -
                # wider spans once let a following piece's pre-arm record a
                # long piece still on the belt after the gate.
                p = next((p for p in self.pieces
                         if gate - 5 <= p["pos"] <= gate + 25), None)
                if p is not None:
                    p["lane_got"] = lane
                    p["expected"] = expected_lane(p)
                    p["ok"] = p["lane_got"] == p["expected"]
                    self.results.append(p)
                    self.pieces.remove(p)
                    if lane == 4:
                        self.chute_until = now + 0.3
                    else:
                        confirm_now = True
            self._set_di(7, confirm_now or now < self.confirm_until)
            self._set_di(8, now < self.chute_until)
            if confirm_now:
                self.confirm_until = now + 0.25

            # end of belt, unrouted
            for p in [p for p in self.pieces if p["pos"] > BELT_LEN + 100]:
                p["lane_got"] = 0
                p["expected"] = expected_lane(p)
                p["ok"] = False
                self.missed += 1
                self.results.append(p)
                self.pieces.remove(p)


if __name__ == "__main__":
    print("[twin] FLUXLINE digital twin serving Modbus TCP on 127.0.0.1:1502")
    t = Twin()
    t.start()
    try:
        while True:
            time.sleep(5)
            snap = t.snapshot()
            print(f"[twin] pieces done={len(snap['pieces'])} missed={snap['missed']} "
                  f"counts={snap['counts']}")
    except KeyboardInterrupt:
        t.flush()
        print("[twin] ledger written to sim/results.json")
