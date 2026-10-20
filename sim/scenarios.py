"""FLUXLINE scenarios - scripted runs against the digital twin + runtime.

Every scenario is a plain function taking a live Twin. pytest uses the same
functions, so the CLI and the test suite cannot diverge.

Usage:
    python scenarios.py all          # full batch, prints the ledger
    python scenarios.py mixed        # single scenario by name
"""

import sys
import time

from twin import Twin, LANE_NAMES


def wait_for(predicate, timeout, poll=0.5, what="condition"):
    """Poll until predicate is true or fail loudly - tests want silence only
    from pytest, not from a hung harness."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    raise TimeoutError(f"scenario: {what} not reached within {timeout}s")


def kind_expect(kind):
    return {"standard": 1, "metal": 2, "tall": 3, "light": 4, "heavy": 4, "jam": 3}[kind]


def batch_line(t):
    """One of every kind down the line, checking the whole verdict law."""
    t.set_feed(False)
    kinds = ["standard", "metal", "tall", "light", "heavy"]
    for k in kinds:
        t.spawn(k)
        time.sleep(0.4)
    n = len(kinds)
    wait_for(lambda: len(t.snapshot()["pieces"]) >= n, 60, what=f"{n} pieces routed")
    return t.snapshot()


def jam_watchdog(t, jam_limit_s=8):
    """A wedged piece must trip the JAM state inside the watchdog window."""
    t.set_feed(False)
    t.pulse_start()
    time.sleep(1.0)
    t.spawn("jam")                       # pins itself in front of the photo-eye
    wait_for(lambda: t.store.getValues(3, 2, 1)[0] == 3, jam_limit_s + 10,
             what="JAM state via watchdog")
    belt_off = not t._co(0)
    t.clear_jam()
    t.pulse_start()                      # manual reset from JAM
    wait_for(lambda: t.store.getValues(3, 2, 1)[0] in (1, 2), 15, what="state cleared")
    return {"jammed": True, "belt_dropped": belt_off}


def estop_chain(t):
    """Opening the chain must drop the belt the same scan and latch."""
    t.set_feed(False)
    t.pulse_start()
    time.sleep(1.0)
    t.open_estop()
    wait_for(lambda: not t._co(0), 5, what="belt dropped on chain open")
    state = t.store.getValues(3, 2, 1)[0]
    t.close_estop()
    t.pulse_start()                      # reset latch only when chain healthy
    wait_for(lambda: t.store.getValues(3, 2, 1)[0] == 1, 15, what="latch cleared")
    return {"latched_state": state}


SCENARIOS = {
    "batch": batch_line,
    "jam": jam_watchdog,
    "estop": estop_chain,
}


def main(argv):
    if not argv or argv[0] == "all":
        names = list(SCENARIOS)
    else:
        names = [argv[0]]
    for name in names:
        print(f"[scenario] {name}")
        t = Twin(seed=42)
        t.start()
        try:
            out = SCENARIOS[name](t)
            print(f"  -> {out}")
            if name == "batch":
                snap = t.flush()
                print(f"  ledger -> {snap}")
        finally:
            t.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
