"""FLUXLINE OEE commissioning check - runtime counters vs the twin's ledger.

Runs a controlled 6-piece batch (one tall, one standard, one metal, one
tall, one light, one heavy) through a freshly started runtime and then
compares the published telemetry (HR4..HR14) with what the twin recorded.

Expected on a healthy line:
    ledger  6/6 pieces ok, 0 missed (twin's own record)
    HR11/12 detected/routed = 6/6 (runtime's own counters)
    HR7..10 lane counts = L01 1, L02 1, L03 2, RJ 2
    HR6  quality = 1000 (per-mille), HR13 ppm = 6, HR5 = ppm/ideal(34)
    HR4  availability = run/(run+down) - the probe re-derives it from the
         state timeline (heartbeat-register anchored)

Run it from the repo root with the OpenPLC core already up:
    python sim/oee_check.py
Exit code 0 = counters agree with reality.

Usage notes:
    - use a freshly booted runtime (its counters start at 0; this check
      does not reset them)
    - closed-loop: twin on 127.0.0.1:1502, master polling it throughout
    - STALL (alarm bit 3) may be on at the end: the probe runs the belt
      with no feed for ~20 s after the last piece - that is the alarm
      working as designed, not a fault
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from twin import Twin                                        # noqa: E402
import scenarios                                             # noqa: E402

POLL = 0.25


def hr(t, i):
    return t.store.getValues(3, i, 1)[0]


def main():
    t = Twin(seed=2026)
    t.start()
    t.set_feed(False)

    deadline = time.time() + 10
    while time.time() < deadline and t.store.getValues(2, 4, 1)[0] != 1:
        time.sleep(0.1)
    hb0 = hr(t, 1)          # scan-seconds elapsed = pre-connect ESTOP time
    scenarios.start_line(t)
    print(f"RUN reached (hb0={hb0}s of pre-connect downtime)")

    kinds = ["tall", "standard", "metal", "tall", "light", "heavy"]
    spawn_at = [time.time() + i * 2.5 for i in range(len(kinds))]
    spawned = 0
    run_s = down_s = 0.0
    t0 = time.time()
    while time.time() - t0 < 150:
        state = hr(t, 2)
        if state == 2:
            run_s += POLL
        elif state in (3, 4):
            down_s += POLL
        while spawned < len(kinds) and time.time() >= spawn_at[spawned]:
            t.spawn(kinds[spawned])
            spawned += 1
        if spawned >= len(kinds) and len(t.snapshot()["pieces"]) >= len(kinds):
            break
        time.sleep(POLL)
    else:
        raise SystemExit("OEE_CHECK_FAILED: batch not fully routed in 150 s")

    # the runtime's route credits land one master-cycle after the twin's
    # confirm pulses start - settle on the published counter first
    deadline = time.time() + 6
    while time.time() < deadline and hr(t, 12) < len(kinds):
        time.sleep(0.1)

    regs = t.store.getValues(3, 4, 11)      # HR4..HR14
    snap = t.snapshot()
    counts = snap["counts"]
    a10, p10, q10 = regs[0], regs[1], regs[2]
    lanes = (regs[3], regs[4], regs[5], regs[6])
    det, rout, ppm, spd = regs[7], regs[8], regs[9], regs[10]
    alarm = hr(t, 3)

    exp_avail = run_s / (run_s + hb0 + down_s)
    print(f"ledger pieces={len(snap['pieces'])} all_ok="
          f"{all(p['ok'] for p in snap['pieces'])} counts={counts} "
          f"missed={snap['missed']}")
    print(f"HR3 alarm={alarm}  a10={a10} (expected ~{exp_avail*1000:.0f})  "
          f"p10={p10} q10={q10}  lanes={lanes}  det={det} rout={rout}  "
          f"ppm={ppm} spd={spd}")

    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(("PASS " if cond else "FAIL ") + name
              + (f" - {detail}" if detail and not cond else ""))

    n = len(kinds)
    chk(f"ledger {n} pieces all ok",
        len(snap["pieces"]) == n and all(p["ok"] for p in snap["pieces"]))
    chk("missed == 0", snap["missed"] == 0)
    chk(f"HR11 detect == {n}", det == n, str(det))
    chk(f"HR12 routed == {n}", rout == n, str(rout))
    chk("lane counters L01/L02/L03/RJ = 1/1/2/2",
        lanes == (1, 1, 2, 2), str(lanes))
    chk("HR6 quality == 1000", q10 == 1000, str(q10))
    chk("HR4 availability within 4% of probe accounting",
        abs(a10 - exp_avail * 1000) <= 40, f"a10={a10} exp={exp_avail*1000:.0f}")
    chk(f"HR13 ppm == {n}",
        n - 1 <= ppm <= n, f"ppm={ppm}")
    chk("HR5 perf == ppm/ideal(34)",
        abs(p10 - round(ppm / 34 * 1000)) <= 2, f"p10={p10}")
    chk("HR14 speed echo == 120 while RUN", spd == 120, str(spd))
    chk("alarm has no JAM/ESTOP/CHAIN/FULL bits", alarm & 0b10111 == 0,
        f"alarm={alarm}")

    t.close()
    print("OEE_CHECK_OK" if ok else "OEE_CHECK_FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
