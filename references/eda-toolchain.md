# EDA Toolchain Strategy

## Recommendation

Use a dual-track pipeline:

1. **KiCad as the automation verifier** when `kicad-cli` is available.
   - Public CLI supports schematic ERC and schematic export.
   - File formats are documented and text-based.
   - Good fit for repeatable machine validation.
   - Current generator emits pin-level review schematics with embedded custom symbols, net-label stubs, and BOM/footprint properties.

2. **EasyEDA/JLCEDA Standard as the manufacturing-facing export**.
   - Standard documents are JSON-based and can be generated.
   - Fits JLC/LCSC/JLCPCB downstream workflows.
   - Current exporter generates a review schematic; official JLCEDA checks still require importing into the editor.

Keep `project.netlist.json` as the source of truth. Generate KiCad, EasyEDA, BOM, pinmap, and previews from it.

## Practical Completion Levels

- **Static-ready**: `project.netlist.json`, BOM, pinmap, HTML/SVG preview, EasyEDA JSON, and static ERC all pass.
- **KiCad-verified**: `validate_eda_outputs.py` finds `kicad-cli` and runs official KiCad ERC/export against the generated pin-level `.kicad_sch`.
- **JLCEDA-verified**: generated EasyEDA/JLCEDA file is imported into JLCEDA and passes its official checks.

## Current Boundary

Do not claim official KiCad or JLCEDA ERC unless the corresponding tool has run. Static ERC is useful but not a substitute for official EDA checks.

KiCad automation is now stronger than the EasyEDA exporter: it can generate a pin-level labelled schematic, run KiCad CLI ERC, and export KiCad-rendered SVG. The EasyEDA/JLCEDA export remains a review/import artifact until native symbol-level EasyEDA generation and official JLCEDA validation are added.

For production release, replace or bind the embedded review symbols to team-approved manufacturer symbols/footprints where required, then rerun KiCad ERC, footprint assignment checks, PCB DRC, and the target fab's official checks.

## References

- EasyEDA Document Format: https://docs.easyeda.com/en/DocumentFormat/EasyEDA-Document-Format/index.html
- EasyEDA Schematic File Format: https://docs.easyeda.com/en/DocumentFormat/2-EasyEDA-Schematic-File-Format/index.html
- KiCad EasyEDA import format notes: https://dev-docs.kicad.org/en/import-formats/easyeda/index.html
- KiCad CLI documentation: https://docs.kicad.org/8.0/en/cli/cli.html
