## What

<!-- one paragraph: what this changes -->

## Why

<!-- the problem or decision behind it; for fixes, the root cause,
     not the symptom -->

## How verified

- [ ] `pytest sim/test_scenarios.py` — offline green
- [ ] matiec compile gate (`tools/check.sh` / CI) — clean
- [ ] `pytest sim/test_line.py` — live green (runtime + twin)
