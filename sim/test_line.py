"""Live tests: the real OpenPLC runtime against the digital twin.

Prerequisites (see docs/03-commissioning.md section 5):
  1. OpenPLC runtime running with program/fluxline.st uploaded
  2. Runtime's Modbus master configured to poll 127.0.0.1:1502
     (read DI/IR, write CO/HR)
  3. This suite starts the twin itself.

Behavior: if the runtime is not polling the twin, tests SKIP with a clear
reason - a fresh clone or CI machine must not fail for missing hardware.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from twin import Twin                              # noqa: E402
import scenarios                                   # noqa: E402

RUNTIME_TIMEOUT = 20.0


@pytest.fixture()
def twin():
    t = Twin(seed=2026)
    t.start()
    # a runtime polls the twin; without one the heartbeat never moves and
    # nothing else in this file is meaningful
    hb0 = t.store.getValues(3, 1, 1)[0]
    got_heartbeat = True
    try:
        scenarios.wait_for(
            lambda: t.store.getValues(3, 1, 1)[0] != hb0,
            RUNTIME_TIMEOUT, poll=1.0, what="runtime heartbeat")
    except TimeoutError:
        got_heartbeat = False
    if not got_heartbeat:
        t.close()
        pytest.skip("OpenPLC runtime not polling the twin - start it and "
                    "configure the Modbus master (docs/03-commissioning.md)")
    t.pulse_start()                       # line starts at IDLE
    scenarios.wait_for(lambda: t.store.getValues(3, 2, 1)[0] == 2, 15,
                       what="line reaching RUN")
    yield t
    t.close()


def test_every_verdict_class_routes_correctly(twin):
    t = twin
    kinds = ["standard", "metal", "tall", "light", "heavy"] * 3   # 15 pieces
    for k in kinds:
        t.spawn(k)
        time.sleep(0.35)
    scenarios.wait_for(lambda: len(t.snapshot()["pieces"]) >= len(kinds), 90,
                       what="all pieces routed")
    snap = t.snapshot()
    for p in snap["pieces"]:
        assert p["ok"], (f"FLX piece {p['id']} ({p['kind']}): expected "
                         f"{p['expected']}, runtime sent it to {p['lane_got']}")
    assert snap["missed"] == 0, "pieces fell off the belt unrouted"
    # and every lane actually got traffic
    counts = snap["counts"]
    assert counts["L01"] >= 2 and counts["L02"] >= 2
    assert counts["L03"] >= 2 and counts["RJ"] >= 2


def test_jam_watchdog_trips_and_resets(twin):
    t = twin
    out = scenarios.jam_watchdog(t)
    assert out["belt_dropped"], "watchdog tripped but belt stayed on"


def test_estop_chain_drops_belt_same_scan(twin):
    t = twin
    scenarios.estop_chain(t)
    # the estop scenario returned after the latch cleared; belt must be off
    # or already restarted cleanly by the scenario's own reset flow
    assert t.store.getValues(3, 2, 1)[0] in (1, 2)


def test_heartbeat_and_counters_advancing(twin):
    t = twin
    hb = t.store.getValues(3, 1, 1)[0]
    scenarios.wait_for(lambda: t.store.getValues(3, 1, 1)[0] != hb, 5,
                       poll=0.5, what="heartbeat tick")
    assert t.store.getValues(3, 19, 1)[0] == 101, "version register"
