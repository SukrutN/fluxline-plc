"""Offline tests: the scenario expectations and the twin's own law.

These need no PLC and no network - they catch harness typos and band-edge
mistakes before anything reaches hardware. The LIVE tests (test_line.py)
then check that the real ST program agrees.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from twin import Twin, expected_lane, profiles   # noqa: E402


def test_every_profile_has_a_lawful_verdict():
    for kind, prof in profiles().items():
        if kind == "jam":
            continue
        lane = expected_lane(prof)
        if kind == "standard":
            assert lane == 1, f"{kind} should go L01, got {lane}"
        elif kind == "metal":
            assert lane == 2, f"{kind} should go L02, got {lane}"
        elif kind == "tall":
            assert lane == 3, f"{kind} should go L03, got {lane}"
        else:  # light / heavy
            assert lane == 4, f"{kind} should be rejected, got {lane}"


def test_band_edges_are_lawful():
    # exactly at the tall threshold -> oversize (>=)
    assert expected_lane({"height": 165.0, "metal": False, "weight": 5000.0}) == 3
    # one tenth under -> weight decides
    assert expected_lane({"height": 164.9, "metal": False, "weight": 5000.0}) == 1
    # metal beats weight band, loses to tall
    assert expected_lane({"height": 164.9, "metal": True, "weight": 5000.0}) == 2
    assert expected_lane({"height": 165.0, "metal": True, "weight": 500.0}) == 3
    # weight band edges are exclusive
    assert expected_lane({"height": 100.0, "metal": False, "weight": 2000.0}) == 1
    assert expected_lane({"height": 100.0, "metal": False, "weight": 1999.9}) == 4
    assert expected_lane({"height": 100.0, "metal": False, "weight": 12000.0}) == 1
    assert expected_lane({"height": 100.0, "metal": False, "weight": 12000.1}) == 4


def test_twin_spawns_lawful_pieces():
    t = Twin(seed=7)
    for _ in range(200):
        t.spawn("mix")
    kinds = [p["kind"] for p in t.pieces]
    assert set(kinds) <= {"standard", "metal", "tall", "light", "heavy"}
    assert len(t.pieces) == 200
    for p in t.pieces:
        assert expected_lane(p) == {"standard": 1, "metal": 2, "tall": 3, "light": 4, "heavy": 4}[p["kind"]]


def test_twin_ledger_shape():
    t = Twin(seed=1)
    t.spawn("metal")
    snap = t.snapshot()
    assert snap["counts"] == {"L01": 0, "L02": 0, "L03": 0, "RJ": 0}
    assert snap["missed"] == 0
