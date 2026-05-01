# Embedded Engineering Skill - AI Handoff

Last updated: 2026-04-29

This is a Claude Code skill for embedded hardware EDA automation.
Primary reference: `SKILL.md` — read it first, always.
User preference: reply in Chinese unless told otherwise.

## What Works

- Spec JSON -> KiCad project + review schematic generation (`gen_kicad_project.py`)
- KiCad CLI can parse, ERC, and export SVG on this machine
- Static ERC over `project.netlist.json` (custom, not official KiCad ERC)
- HTML/SVG preview generation (`render_design_preview.py`)
- EasyEDA/JLCEDA review JSON export (`gen_easyeda_std.py`)
- BOM, pinmap, production readiness report generation
- JLC assembly package: `jlc_bom.csv`, `jlc_cpl.csv`, assembly reports
- Spec validation before generation (`validate_project_spec.py`)
- System bundle: hardware + firmware skeleton + protocol + system_contract
- Gallery regression: all 5 templates pass (22 checks each, 0 FAIL)

## What Doesn't Work / Known Limits

- `jlc_cpl.csv` is from auto-placement — needs human review before fab upload
- EasyEDA output is review JSON, NOT native JLCEDA symbol-level schematic
- No real LCSC/JLC stock/price/substitute lookup integration
- Static ERC is custom, not a substitute for KiCad/JLCEDA official ERC
- No human-reviewed PCB layout/routing — PCB skeleton exists but is basic
- RF placeholder parts (0R/DNP) may have incomplete LCSC metadata
- `production_readiness.md` is a local gate, not fab approval

## How to Extend

### Add a new template
1. Create `circuits/templates/<name>.json` following existing format
2. Run `gen_kicad_project.py` on it — fix any spec validation errors
3. Add to gallery: run `gen_template_gallery.py`, confirm 0 FAIL
4. Run `py_compile` on all eda scripts

### Modify generator logic
1. Edit the relevant script in `scripts/eda/`
2. `py_compile` the changed file
3. Regenerate full gallery, confirm 0 FAIL
4. If KiCad CLI available, verify ERC/export still passes

### Add new EDA output type
1. Add generation logic in `gen_kicad_project.py`
2. Add validation check in `validate_eda_outputs.py`
3. Add gallery summary link in `gen_template_gallery.py`
4. Regenerate gallery, confirm 0 FAIL

## Key Paths

```
Skill root:    C:\Users\24560\.claude\skills\embedded-engineering
Python:        C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe
KiCad CLI:     C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
Gallery:       C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\
```

## Verification Commands

```powershell
# Compile check (from skill root)
python -m py_compile scripts\eda\gen_kicad_project.py scripts\eda\gen_template_gallery.py scripts\eda\gen_jlc_package.py scripts\eda\validate_eda_outputs.py scripts\eda\validate_project_spec.py scripts\eda\gen_easyeda_std.py scripts\eda\render_design_preview.py scripts\eda\erc_check.py

# Validate one spec
python -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json

# Skill structure validation
python -X utf8 C:\Users\24560\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\24560\.claude\skills\embedded-engineering

# Full gallery
python -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery

# Whitespace
git diff --check
```

## Next Steps (Priority Order)

1. Extend JLC package: better CPL from placement, LCSC completeness checks
2. PCB skeleton: `.kicad_pcb` generation with board outline, mounting holes, keepout
3. Symbol/footprint binding: distinguish review vs official vs manufacturer symbols
4. EasyEDA native path: symbol-level JLCEDA output with verified import
5. More templates: STM32, RP2040, motor control, RS-485/CAN industrial

## Maintenance Rules

- `project.netlist.json` is the source of truth — derive all outputs from it
- New outputs must be checked by `validate_eda_outputs.py` or gallery
- Every new template must pass: py_compile + gallery + static ERC (0 FAIL)
- Never overclaim: only state tool-verified results
