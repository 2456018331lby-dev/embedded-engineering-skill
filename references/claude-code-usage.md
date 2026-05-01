# Claude Code Usage Guide

This directory is a Claude Code skill, not a standalone EDA application.

Claude Code should use `SKILL.md` as the operating prompt and the scripts in this
skill as local tools. The intended workflow is:

1. Detect that the user is asking for embedded hardware design.
2. Read the relevant section of `SKILL.md`.
3. Convert the user's requirement into a project spec JSON, preferably by
   adapting one of `circuits/templates/*.json`.
4. Run `scripts/eda/validate_project_spec.py` on the spec first.
5. Run the EDA generator and validation scripts.
6. Return concise engineering decisions plus direct paths to generated outputs.

## How To Invoke It

In Claude Code, ask naturally. You do not need to mention every script.

Good prompts:

- `使用 embedded-engineering skill，从零设计一个 ESP32-C3 温湿度采集板，带 USB-C、锂电池、I2C 传感器，生成 KiCad 原理图和 BOM。`
- `用 embedded-engineering 帮我做一个 LoRa 低功耗传感器节点，目标是嘉立创打样，给我 KiCad 文件、BOM、pinmap、ERC 报告和可视化预览。`
- `使用 embedded-engineering，给我一个适合嘉立创打样的 review 工程，除了 KiCad 和 BOM 之外，再给我 JLC BOM、装配报告和生产风险说明。`
- `使用 embedded-engineering，给我一个可在 KiCad 里打开的原理图和 PCB 骨架，再带上布局约束、JLC BOM 和装配风险报告。`
- `检查这个硬件需求并生成能打开的测试项目，输出文件路径给我。`
- `给我一个完整嵌入式系统 starter bundle，包含硬件工程、固件骨架、协议代码和硬件-固件接口文档。`

If Claude Code does not auto-trigger the skill, explicitly say:

`请使用 C:\Users\24560\.claude\skills\embedded-engineering 这个 skill。`

## What The Skill Can Produce Now

- KiCad project file: `.kicad_pro`
- KiCad pin-level review schematic: `.kicad_sch`
- KiCad PCB skeleton: `.kicad_pcb`
- KiCad CLI ERC result when `kicad-cli` is available
- KiCad PCB DRC result when `kicad-cli` is available
- KiCad exported SVG when `kicad-cli` is available
- KiCad PCB SVG when `kicad-cli` is available
- EasyEDA/JLCEDA review JSON: `.easyeda.json`
- Browser previews: `schematic_preview.html`, `schematic_preview.svg`
- Project spec validation reports: `spec_validation.json`, `spec_validation.md`
- Machine-readable netlist: `project.netlist.json`
- BOM: `bom.csv`
- JLC assembly review BOM: `jlc_bom.csv`
- JLC placement file: `jlc_cpl.csv`
- JLC assembly review report: `jlc_assembly_report.md`, `jlc_assembly_report.json`
- MCU pin map: `pinmap.csv`
- Static ERC: `static_erc.md`
- EDA validation report: `eda_validation.md`
- Manufacturing readiness gate: `production_readiness.md`
- PCB placement/routing guide: `pcb_constraints.md`
- Symbol/package binding report: `symbol_footprint_binding.md`
- Footprint assignment CSV: `footprint_assignment.csv`
- Complete system bundle entry: `README_system_bundle.md`
- Hardware/firmware contract: `system_contract.md`

## One-Command Visual Test

From the skill directory:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json
```

## One-Command Visual Test

From the skill directory:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery
```

Open:

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery\index.html
```

## One-Command System Bundle

From the skill directory:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\system\gen_embedded_system_bundle.py --spec circuits\templates\esp32-c3-sensor-node.json --out C:\Users\24560\.codex\.tmp\embedded-system-demo
```

## Current Boundary

The generated KiCad schematic is a strong review and automation artifact. It is
not yet a finished production schematic in the same sense as a human-curated
library-backed release.

Before fabrication, the assistant should still:

- bind critical ICs to approved manufacturer symbols and footprints when needed;
- complete PCB layout and KiCad PCB DRC;
- export Gerbers/drills;
- generate JLC BOM/CPL;
- review the generated `jlc_cpl.csv` because it comes from auto-placement, not a human-finished layout;
- import into JLCEDA when the target flow requires official JLCEDA verification.

## Best Claude Code Output Contract

For complete hardware project requests, Claude Code should return:

- project summary and major decisions;
- files generated and absolute paths;
- static ERC and KiCad validation result;
- PCB skeleton and placement/routing constraints;
- JLC assembly review result and whether manual/DNP parts remain;
- production readiness verdict;
- remaining blockers before manufacturing.
