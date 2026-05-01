# EDA Toolchain Reference

## Dual-Track Pipeline

Source of truth: `project.netlist.json`. All other artifacts derive from it.

### Track A: KiCad (automation + verification)
- Generate `.kicad_sch` (pin-level review schematic) from netlist
- Run `kicad-cli` for ERC and SVG export when available
- Open `.kicad_sch` in KiCad → assign manufacturer symbols/footprints → design PCB → export Gerber/drills → upload to JLCPCB

### Track B: EasyEDA/JLCEDA (JLCPCB-native flow)
- Generate `.easyeda.json` from netlist (JSON-based, machine-generable)
- Import into 嘉立创EDA (JLCEDA Standard) → layout PCB → export Gerber → upload to JLCPCB

## Key Scripts

```
scripts/eda/validate_project_spec.py --spec <path>         # Validate project spec JSON
scripts/eda/gen_kicad_project.py --spec <path> --out <dir> # Generate KiCad project + schematic
scripts/eda/gen_easyeda_std.py --spec <path> --out <dir>   # Generate EasyEDA JSON
scripts/eda/validate_eda_outputs.py --project <dir>        # Run static ERC + KiCad CLI ERC if available
scripts/eda/render_design_preview.py --project <dir>       # Generate HTML/SVG previews
scripts/eda/gen_jlc_package.py --manifest <path>           # Generate JLC BOM, CPL, assembly report
```

## Completion Levels

| Level | Criteria |
|-------|----------|
| Static-ready | netlist + BOM + pinmap + preview + EasyEDA JSON + static ERC pass |
| KiCad-verified | `kicad-cli` ran official ERC on generated `.kicad_sch` |
| JLCEDA-verified | Generated EasyEDA file imported into JLCEDA and passed its checks |

## Workflow: Design → Manufacturing

1. User requirement → `project.netlist.json` (adapt from `circuits/templates/*.json`)
2. `validate_project_spec.py` → fix spec errors
3. `gen_kicad_project.py` → `.kicad_pro` + `.kicad_sch` + `.kicad_pcb` skeleton
4. `validate_eda_outputs.py` → static ERC + KiCad CLI ERC (if available)
5. `gen_jlc_package.py` → `jlc_bom.csv` + `jlc_cpl.csv` + assembly report
6. Open `.kicad_sch` in KiCad → complete PCB layout → DRC → export Gerber → JLCPCB

Or for EasyEDA flow:
1-2. Same as above
3. `gen_easyeda_std.py` → `.easyeda.json`
4. Import into 嘉立创EDA → layout → export Gerber → JLCPCB

## Output Files

```
<project>/
├── *.kicad_pro, *.kicad_sch, *.kicad_pcb   # KiCad project
├── *.easyeda.json                            # EasyEDA import file
├── project.netlist.json                      # Source of truth
├── bom.csv                                   # Generic BOM
├── pinmap.csv                                # MCU pin assignment
├── jlc_bom.csv, jlc_cpl.csv                 # JLCPCB assembly files
├── jlc_assembly_report.md/.json              # Assembly review
├── static_erc.md                             # Static ERC results
├── eda_validation.md                         # Validation summary
├── production_readiness.md                   # Manufacturing gate
├── pcb_constraints.md                        # Placement/routing guide
├── schematic_preview.html/.svg               # Browser-viewable preview
└── spec_validation.json/.md                  # Spec validation
```

## Boundaries

- Static ERC ≠ official KiCad/JLCEDA ERC. Only claim "verified" if the tool actually ran.
- Generated schematics are review artifacts. Before fabrication: bind ICs to manufacturer symbols, complete PCB layout, run DRC, export Gerbers.
- Review `jlc_cpl.csv` manually — it comes from auto-placement, not a finished layout.

## References

- EasyEDA format: https://docs.easyeda.com/en/DocumentFormat/EasyEDA-Document-Format/index.html
- EasyEDA schematic format: https://docs.easyeda.com/en/DocumentFormat/2-EasyEDA-Schematic-File-Format/index.html
- KiCad EasyEDA import: https://dev-docs.kicad.org/en/import-formats/easyeda/index.html
- KiCad CLI: https://docs.kicad.org/8.0/en/cli/cli.html
