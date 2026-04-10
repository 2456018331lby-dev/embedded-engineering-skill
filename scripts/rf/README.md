# calc_microstrip.py

First delivered script for the embedded-engineering skill.

## What it does
- Computes microstrip width for a target impedance
- Computes impedance for a given width
- Estimates guided wavelength and quarter-wave length
- Produces first-pass loss and manufacturability guidance
- Returns a unified dict / JSON structure suitable for Skill or MCP integration

## Example
```bash
python calc_microstrip.py --er 4.4 --h-mm 1.6 --target-z0 50 --freq-ghz 2.4
```

## Notes
This is a first-pass engineering calculator. For production RF boards, verify with vendor stackup tools and EM simulation.
