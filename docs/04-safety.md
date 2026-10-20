# 04 · Safety — what this program does and does not do

Read this before wiring anything to real power.

## What the software E-stop is

The program's state machine latches an E-stop condition from two sources:

1. **The E-stop chain input** (`%IX0.4`, NC, fail-safe polarity) — opens on
   any button or guard contact. Belt and all solenoids drop the same scan.
2. **The jam watchdog** — a piece blocking the photo-eye past the configured
   limit latches a JAM condition with identical output behavior.

Both are **supervisory actions**. They stop the *process*.

## What it is not

- **It is not a safety system.** No software running on the OpenPLC runtime is
  safety-rated. A stuck scan, a crashed runtime, or a power cut can leave
  outputs in the last written state.
- **It does not remove stored energy.** Belt coasting, air pressure in the
  diverter lines, and hot surfaces are not addressed by the program.
- **It does not make the E-stop chain safe.** The chain must be wired NC,
  monitored, and rated for the task. The program merely *observes* it.

## The certified stop path

Real stopping authority lives in hardware, outside this program:

```
E-stop buttons + guard switches  ──▶  safety relay (cat. 3, dual-channel)
                                          │
                                          ├─▶  VFD safe-torque-off / main contactor
                                          ├─▶  diverter valve bank isolation
                                          └─▶  stack light + horn feed
```

The program's `%IX0.4` reads the same chain *after* the safety relay — it is a
report channel, not the stop mechanism. Belt and solenoid outputs must also
pass through contacts opened by the safety relay, so the wiring alone drops
power even if the program is wrong.

## Non-negotiables before production

- [ ] Risk assessment per ISO 12100 for the cell, signed by a competent person
- [ ] Safety functions per ISO 13849-1 with the required Performance Level
- [ ] E-stop buttons per ISO 13850 (red on yellow, latching, within reach)
- [ ] Guards per ISO 14120, interlocked into the safety chain
- [ ] Mains isolation and lockout/tagout procedure documented at the panel
- [ ] The program's watchdog behavior validated on the real line (section 7
      of the commissioning guide), not assumed from simulation

## Simulation honesty

The digital twin (`sim/`) exercises the logic, not the physics of a jammed
crate or a person's hand. Test the watchdog and E-stop on the real line with
real pieces before trusting it.
