# Contributing

These rules read like ceremony. Each one earned its place — usually by a
failure that looked like something else.

## Workflow

1. Branch from `main`, named for the work: `feature/<area>-<thing>`,
   `fix/<thing>`, `docs/<thing>`, `chore/<thing>`.
2. One unit of work per pull request. A PR carrying two ideas gets
   split.
3. Titles follow Conventional Commit style: `fix(sim): …`,
   `feat(st): …`, `docs: …`.
4. The body answers three questions: what, why (for fixes: the root
   cause, not the symptom), and how it was verified.
5. Self-review the diff before the merge. Anything you would flag in a
   stranger's PR, fix here first.

## Verification — the three gates

```bash
pytest sim/test_scenarios.py   # offline: the verdict law, no PLC needed
tools/check.sh                 # matiec compile gate (builds matiec once)
pytest sim/test_line.py        # live: runtime + twin required
```

CI runs the first two on every push and PR. Red CI doesn't merge — no
exceptions. The live gate runs on the machine that has a runtime; see
`docs/03-commissioning.md` for bring-up.

Don't run a standalone twin (`python sim/twin.py`) while a live suite is
running: both bind localhost:1502, and the fixture boots its own twin.

## Commits

A commit completes one change; nothing parks. The message names the root
cause — a message readable a year from now, without the code in front of
you, is the bar.

## Merging

Merge commits preserve the unit of work as a named, discussed blob on
`main`. Branch protection requires the CI checks to pass on every PR
that touches the program or the simulator.
