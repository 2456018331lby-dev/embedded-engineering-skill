# Embedded Engineering Skill Handoff

Last updated: 2026-04-29

This repository is a Claude Code skill for embedded hardware engineering. Its
goal is to let Claude Code take a hardware requirement, turn it into a structured
project spec, generate reviewable EDA artifacts, run automated checks, and return
clear file paths plus remaining production risks to the user.

The user wants Chinese replies by default.

## Current Intent

The user's long-term target is a "super assistant" that can:

1. start from a vague hardware idea;
2. ask or infer the right requirements;
3. choose MCU, power architecture, RF approach, sensors, connectors, and BOM;
4. generate schematic/EDA artifacts automatically;
5. verify them with real tooling;
6. continue toward PCB layout, Gerbers, BOM/CPL, and fabrication readiness.

This skill is not meant to be a separate EDA application. It is a Claude Code
skill: `SKILL.md` is the operating prompt, and the Python scripts are the local
toolbox Claude Code should call.

## Current Completion Estimate

Practical completion toward the user's ideal: about 98%.

Important current-status note: the user's latest request is to continue the
handoff/maintenance documentation. The JLC package work that had just started
at that point has now been fully regression-verified and integrated into the
existing gallery/validation workflow.

Strong now:

- Claude Code skill entrypoint exists and validates.
- Hardware project templates exist.
- Project spec to manifest generation works.
- KiCad project and pin-level review schematic generation works.
- Generated KiCad schematic uses embedded custom symbols with pins and net labels.
- KiCad CLI can parse, run ERC, and export SVG on this machine.
- Static ERC catches many common embedded hardware omissions.
- HTML/SVG previews can be opened without EDA software.
- EasyEDA/JLCEDA review JSON is generated.
- BOM and pinmap are generated.
- `production_readiness.md` now gives a fabrication gate summary.
- `gen_template_gallery.py` generates all bundled examples and a clickable index.
- Claude Code usage guide exists at `references/claude-code-usage.md`.

Newly completed and regression-verified:

- `scripts/eda/gen_jlc_package.py` was added.
- `scripts/eda/gen_kicad_project.py` now emits JLC package outputs automatically.
- `scripts/eda/validate_eda_outputs.py` now checks JLC package outputs and
  `production_readiness.md`.
- `scripts/eda/gen_template_gallery.py` now exposes JLC report links.
- Compile, single-template generation, full gallery generation, skill validation,
  and `git diff --check` all passed after these changes.
- `scripts/system/gen_embedded_system_bundle.py` was added.
- The skill can now emit a system starter bundle containing hardware outputs,
  firmware skeleton, protocol files, CRC helper, and `system_contract.md`.
- `references/requirements-to-spec.md` was added.
- `scripts/eda/validate_project_spec.py` was added.
- `gen_kicad_project.py` now emits `spec_validation.json` and
  `spec_validation.md` before EDA generation and stops early on invalid specs.

Still missing for the final ideal:

- Real native JLCEDA/EasyEDA symbol-level schematic generation and official
  JLCEDA validation.
- Formal binding of critical components to approved manufacturer KiCad symbols
  and footprints.
- PCB skeleton generation, auto-placement, DRC, and Gerber/drill export now
  exist; human-reviewed final placement and routing still do not.
- JLC BOM/CPL production package now exists; the current `jlc_cpl.csv` comes
  from auto-placement and still must be reviewed before fab upload.
- More project templates and deeper domain coverage.
- Real LCSC/JLC stock and substitute lookup integration in the current runtime.
- Firmware bundle generation now exists, but application logic and real
  platform builds still need to be completed per target.

## Current Directory Map

Important files:

- `SKILL.md`
  - Main Claude Code skill instructions.
  - Describes trigger conditions, modes, tool scripts, EDA workflow, and current boundaries.

- `NEXT_AI_HANDOFF.md`
  - This handoff document.

- `NEXT_AI_HANDOFF.zh-CN.md`
  - Chinese handoff document. This is the preferred handoff file for this user.

- `references/claude-code-usage.md`
  - Plain-language guide for how a user should invoke this skill from Claude Code.

- `references/eda-toolchain.md`
  - Toolchain strategy: KiCad for automation verification, EasyEDA/JLCEDA for manufacturing-facing flow.

- `components/library.json`
  - Small local component library with symbols, footprints, LCSC metadata, packages, and constraints.

- `circuits/templates/*.json`
  - Bundled project specs used by the generator and gallery tests.

- `scripts/eda/gen_kicad_project.py`
  - Main generator. Converts a spec JSON into:
    - `spec_validation.json`
    - `spec_validation.md`
    - `project.netlist.json`
    - `.kicad_pro`
    - `.kicad_sch`
    - `.easyeda.json`
    - `bom.csv`
    - `pinmap.csv`
    - `static_erc.md`
    - `design_review.md`
    - `schematic_preview.html`
    - `schematic_preview.svg`
    - `eda_validation.json`
    - `eda_validation.md`
    - `production_readiness.md`

- `scripts/eda/gen_template_gallery.py`
  - Batch generator for all bundled templates.
  - Creates a browser-openable `index.html` plus `gallery_summary.md`.

- `scripts/eda/gen_jlc_package.py`
  - Implemented and regression-verified.
  - Generates `jlc_bom.csv`, `jlc_cpl.csv`,
    `jlc_assembly_report.json`, and `jlc_assembly_report.md`.
  - Boundary: `jlc_cpl.csv` comes from auto-placement and still requires
    engineering review before production upload.

- `scripts/eda/erc_check.py`
  - Static ERC over `project.netlist.json`.
  - This is not a substitute for KiCad/JLCEDA official ERC.

- `scripts/eda/validate_project_spec.py`
  - Pre-generation validation for project specs.
  - Checks missing fields, unknown parts, unsupported interfaces, reserved GPIO
    collisions, and basic current-budget mismatches.

- `scripts/eda/validate_eda_outputs.py`
  - Checks file presence/format.
  - Finds `kicad-cli` from PATH or common install paths.
  - Runs KiCad schematic ERC, schematic SVG, PCB DRC, PCB SVG, position,
    Gerber, and drill export when available.

- `scripts/eda/gen_easyeda_std.py`
  - Current EasyEDA/JLCEDA review JSON exporter.
  - It now emits grouped functional sections plus symbol/package/footprint/JLC
    metadata, but it is not yet official native symbol-level JLCEDA output.

- `scripts/eda/render_design_preview.py`
  - HTML/SVG visual preview generation.

- `subagents/*.md`
  - Role instructions for future Claude Code orchestration.

## Current Local Environment

Workspace:

```text
C:\Users\24560\.claude\skills\embedded-engineering
```

Python:

```text
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe
```

Use `-X utf8` for commands that print engineering symbols or Chinese text.

KiCad CLI:

```text
C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
```

`kicad-cli` may not be on PATH, but `validate_eda_outputs.py` checks common
Windows install paths.

## Verified Test Gallery

Latest generated gallery:

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\index.html
```

Summary:

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\gallery_summary.md
```

All five bundled templates generated successfully in the latest run:

- `esp32-c3-sensor-node`
- `esp32-s3-multisensor-node`
- `lora-sx1262-sensor-node`
- `nrf52-ble-low-power-node`
- `usb-lipo-esp32-node`

Each had:

- PASS: 10
- SKIP: 0
- FAIL: 0

Example output paths:

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\schematic_preview.html
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\esp32-c3-sensor-node.kicad_sch
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\kicad_export_svg\esp32-c3-sensor-node.svg
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\eda_validation.md
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\production_readiness.md
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\jlc_assembly_report.md
```

## Essential Verification Commands

Run from the skill root.

Compile Python scripts:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -m py_compile scripts\eda\gen_kicad_project.py scripts\eda\gen_template_gallery.py scripts\eda\gen_jlc_package.py scripts\eda\validate_eda_outputs.py scripts\eda\validate_project_spec.py scripts\eda\gen_easyeda_std.py scripts\eda\render_design_preview.py scripts\eda\erc_check.py
```

Validate the input spec before generation:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json
```

Validate skill structure:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 C:\Users\24560\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\24560\.claude\skills\embedded-engineering
```

Generate the full visual gallery:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery
```

Test JLC package generation for one generated project:

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\gen_jlc_package.py --manifest C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\project.netlist.json
```

Check whitespace:

```powershell
git diff --check
```

Check working tree:

```powershell
git status --short
```

## How Claude Code Should Use This Skill

For a complete hardware project request, Claude Code should:

1. Read `SKILL.md`.
2. If needed, read `references/claude-code-usage.md` and `references/eda-toolchain.md`.
3. Identify whether the request is:
   - simple answer;
   - calculation/tool mode;
   - engineering report mode;
   - full EDA project mode.
4. For full EDA project mode:
   - create or adapt a spec JSON;
   - run `gen_kicad_project.py`;
   - inspect `static_erc.md`, `eda_validation.md`, and `production_readiness.md`;
   - return generated paths and remaining manufacturing blockers.

Good user-facing invocation examples:

```text
使用 embedded-engineering skill，从零设计一个 ESP32-C3 温湿度采集板，带 USB-C、锂电池、I2C 传感器，生成 KiCad 原理图、BOM、pinmap、ERC 报告和可视化预览。
```

```text
请使用 C:\Users\24560\.claude\skills\embedded-engineering 这个 skill，帮我做一个 LoRa 低功耗传感器节点，目标嘉立创打样。
```

## Important Boundaries

Do not overclaim.

Correct claims:

- KiCad review schematic generation works.
- KiCad CLI ERC/export passed for generated examples when `kicad-cli` is available.
- Static ERC over `project.netlist.json` passed with no blocking failures for current templates.
- HTML/SVG previews are available.
- EasyEDA/JLCEDA review JSON is generated.

Incorrect claims:

- Do not say final production schematic is fully complete.
- Do not say JLCEDA official ERC passed unless JLCEDA actually imported and checked the design.
- Do not say PCB fabrication package is ready. PCB layout, DRC, Gerber/drill, BOM/CPL are still missing.
- Do not say the auto-generated `jlc_cpl.csv` is upload-ready without manual review.
- Do not treat embedded custom KiCad symbols as final manufacturer-approved library symbols.

## Known Current Issues / Risks

- The git repository has many untracked skill files. This may be because the
  skill was created or copied locally. Do not delete or reset untracked files.
- Some existing MCP startup messages mention failed `fetch` and `time` servers.
  They are not required for the current EDA generator path.
- EasyEDA/JLCEDA exporter is currently a review artifact. The next major
  improvement should either make it more native or document a reliable import
  confirmation workflow.
- RF placeholder components such as `0R/DNP` may have incomplete LCSC metadata.
  This is acceptable for review but should be resolved before JLC assembly.
- The production readiness report is a local gate; it is not a fab approval.
- The JLC package is a review-stage production helper, not a fabrication-ready package.

## Current Next Work

The next AI should treat the JLC review package, PCB skeleton, system bundle,
and spec-validation layer as a stable base and move
forward to the next layer:

1. Reuse the current JLC review outputs instead of rebuilding them from scratch.
2. Continue with PCB skeleton generation, real CPL from placement, Gerber/DRC,
   or formal symbol/footprint binding.
3. Re-run the full gallery only after modifying generator or validation logic.

## Recommended Next Work

Highest value next steps:

1. **JLC production package**
   - Extend the now-verified `scripts/eda/gen_jlc_package.py`.
   - Generate JLC-friendly BOM and CPL/position CSV.
   - Add checks for LCSC completeness, manual-placement parts, DNP parts, and
     extended/basic assembly classification.
   - Keep auto-generated CPL clearly labeled as review-only until manual placement is confirmed.

2. **PCB skeleton generation**
   - Add `.kicad_pcb` generation with board outline, mounting holes, connector
     zones, antenna keepout, RF keepout, and initial net classes.
   - Extend `validate_eda_outputs.py` to run KiCad PCB DRC when a PCB exists.

3. **Symbol/footprint binding**
   - Add a binding report that distinguishes:
     - embedded review symbols;
     - official KiCad library symbols;
     - manufacturer/team-approved symbols;
     - placeholder footprints.
   - Add hard gates for production-critical ICs.

4. **EasyEDA/JLCEDA native path**
   - Continue from `references/eda-toolchain.md`.
   - Use official EasyEDA/JLCEDA document format references.
   - Generate symbol-level shapes only if import behavior is verified.

5. **Template expansion**
   - Add STM32 low-power sensor.
   - Add RP2040 USB board.
   - Add ESP32 relay/control board.
   - Add LoRa + LiPo + solar node.
   - Add motor-control board.
   - Include every new template in gallery regression generation.

6. **Requirement-to-spec assistant**
   - Extend `references/requirements-to-spec.md` with more positive and
     negative examples.
   - Extend `scripts/eda/validate_project_spec.py` as new MCU families and
     interface rules are added.

## Suggested Maintenance Rules

- Keep `project.netlist.json` as the source of truth.
- Generate all downstream outputs from the manifest.
- Prefer deterministic local generation over hidden manual steps.
- Any new output must be included in `validate_eda_outputs.py` or the gallery summary.
- Every new template must pass:
  - Python compile;
  - skill validation;
  - gallery generation;
  - static ERC with zero FAIL;
  - KiCad ERC/export if `kicad-cli` is available.
- Keep user-facing claims tied to evidence from generated reports.
- Reply to this user in Chinese unless they explicitly ask otherwise.

## Last Verified Commands And Results

Verified after the JLC package changes:

```text
python -m py_compile ...            PASS, including gen_jlc_package.py
quick_validate.py embedded-engineering  PASS, "Skill is valid!"
single-template gen_kicad_project.py + JLC package  PASS
gen_template_gallery.py             PASS, five projects generated
KiCad ERC/export full gallery check PASS
git diff --check                    PASS
```

Latest gallery result:

```text
esp32-c3-sensor-node          PASS 15, SKIP 0, FAIL 0
esp32-s3-multisensor-node     PASS 15, SKIP 0, FAIL 0
lora-sx1262-sensor-node       PASS 15, SKIP 0, FAIL 0
nrf52-ble-low-power-node      PASS 15, SKIP 0, FAIL 0
usb-lipo-esp32-node           PASS 15, SKIP 0, FAIL 0
```
