# Claude Code Usage — AI Agent Quick Reference

## Skill Path

`C:\Users\24560\.claude\skills\embedded-engineering`

Entry point: `SKILL.md`. Templates: `circuits/templates/*.json`. Scripts: `scripts/eda/`, `scripts/system/`.

## Invocation Pattern

1. User requests hardware design → read `SKILL.md`
2. Adapt a template from `circuits/templates/*.json` into a project spec
3. Validate spec → generate EDA outputs → report results

If skill doesn't auto-trigger: `请使用 C:\Users\24560\.claude\skills\embedded-engineering 这个 skill。`

## Workflow Chain (full pipeline)

```bash
# Set Python
PYTHON="C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe"

# 1. Validate spec
$PYTHON -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json

# 2. Generate KiCad project
$PYTHON -X utf8 scripts\eda\gen_kicad_project.py --spec <spec.json> --out <output_dir>

# 3. Generate EasyEDA JSON (alternative flow)
$PYTHON -X utf8 scripts\eda\gen_easyeda_std.py --spec <spec.json> --out <output_dir>

# 4. Run validation (static ERC + KiCad CLI if available)
$PYTHON -X utf8 scripts\eda\validate_eda_outputs.py --project <output_dir>

# 5. Generate JLC assembly package
$PYTHON -X utf8 scripts\eda\gen_jlc_package.py --manifest <output_dir>\project.netlist.json

# 6. Generate previews
$PYTHON -X utf8 scripts\eda\render_design_preview.py --project <output_dir>

# 7. Full system bundle (hardware + firmware + contracts)
$PYTHON -X utf8 scripts\system\gen_embedded_system_bundle.py --spec <spec.json> --out <output_dir>
```

## Quick Gallery Test

```bash
$PYTHON -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery
# Open: <out>\index.html
```

## Example Prompts

- `使用 embedded-engineering skill，从零设计一个 ESP32-C3 温湿度采集板，带 USB-C、锂电池、I2C 传感器，生成 KiCad 原理图和 BOM。`
- `用 embedded-engineering 帮我做一个 LoRa 低功耗传感器节点，目标是嘉立创打样，给我 KiCad 文件、BOM、pinmap、ERC 报告和可视化预览。`
- `使用 embedded-engineering，给我一个适合嘉立创打样的 review 工程，除了 KiCad 和 BOM 之外，再给我 JLC BOM、装配报告和生产风险说明。`
- `使用 embedded-engineering，给我一个可在 KiCad 里打开的原理图和 PCB 骨架，再带上布局约束、JLC BOM 和装配风险报告。`
- `给我一个完整嵌入式系统 starter bundle，包含硬件工程、固件骨架、协议代码和硬件-固件接口文档。`

## Output Contract (what to return to user)

For complete hardware requests, always return:
1. Project summary + major design decisions
2. Generated files with absolute paths
3. Static ERC / KiCad validation result
4. PCB skeleton + placement/routing constraints
5. JLC assembly review + remaining DNP/manual parts
6. Production readiness verdict
7. Remaining blockers before manufacturing

## Pre-Fabrication Checklist

Before claiming "ready for fab":
- [ ] Bind critical ICs to manufacturer symbols/footprints
- [ ] Complete PCB layout + run KiCad PCB DRC
- [ ] Export Gerber + drill files
- [ ] Generate JLC BOM/CPL
- [ ] Review `jlc_cpl.csv` (auto-placement, not human-finished)
- [ ] Import into JLCEDA if official JLCEDA verification required

## Output Files Reference

`*.kicad_sch` — KiCad schematic | `*.easyeda.json` — EasyEDA import
`project.netlist.json` — source of truth | `bom.csv` — BOM
`pinmap.csv` — MCU pins | `jlc_bom.csv`/`jlc_cpl.csv` — JLC assembly
`static_erc.md` — ERC | `production_readiness.md` — fab gate
`pcb_constraints.md` — layout guide | `schematic_preview.html` — visual preview
