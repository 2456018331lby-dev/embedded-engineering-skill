---
name: embedded-engineering
description: Embedded hardware engineering skill. Triggers on: hardware design, schematic, KiCad, PCB, component selection, RF, antenna, impedance matching, power tree, BOM, embedded system, wireless sensor, 2.4G/5G/433M/LoRa/Wi-Fi module antenna, U.FL/SMA, chip antenna, new hardware project from scratch.
---

# Embedded Engineering Skill

All scripts are under `scripts/` from this skill's root directory.
Python executable: `C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8`

---

## 1. Quick Start

Given a question about specs or theory -> answer directly (no scripts).
Given a single calculation (impedance, antenna size, matching) -> run the relevant `scripts/rf/` script.
Given a full hardware project requirement -> run the EDA pipeline (Section 4.6).

---

## 2. Mode Selection

| Mode | When | Action |
|------|------|--------|
| simple | Quick Q&A, single datasheet lookup, theory | Direct answer, no scripts |
| tool | Single calculation or code generation | Run one script, return result |
| engineering | Multi-subsystem project needing RF + firmware + BOM | Orchestrate subagents (Section 3) |
| full | From-scratch board design to EDA artifacts | validate_spec -> gen_kicad -> erc_check -> gen_jlc -> validate_eda |

---

## 3. Subagent Orchestration (engineering mode)

Pipeline order:
```
system-architect  -> requirement decomposition, task assignment
    |
    +-- rf-designer        -> RF calc chain (5 scripts)    [skip if no antenna/RF]
    +-- firmware-engineer  -> MCU selection + firmware      [skip if hardware-only]
    |
schematic-designer -> KiCad project + netlist + ERC
pcb-designer       -> layout constraints (needs rf-designer output)
bom-sourcer        -> BOM + stock check
test-engineer      -> test plan
doc_output_mcp     -> Word/Markdown reports
```

Subagent role files: `subagents/subagent_<role>.md`

---

## 4. Script CLI Reference

PYTHON = `C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8`

### 4.1 RF Scripts (scripts/rf/)

Microstrip impedance:
```
%PYTHON% scripts\rf\calc_microstrip.py --er 4.4 --h-mm 1.6 --target-z0 50 --freq-ghz 2.4
```

CPWG impedance:
```
%PYTHON% scripts\rf\calc_cpwg.py --er 4.4 --h-mm 1.6 --width-mm 4.0 --gap-mm 0.5 --freq-ghz 2.4
```

Antenna sizing (types: patch, pifa, dipole, monopole):
```
%PYTHON% scripts\rf\calc_antenna.py --type patch --freq-ghz 2.4 --er 4.4 --h-mm 1.6
```

Matching network (types: l_network, pi, t, double_t):
```
%PYTHON% scripts\rf\calc_matching.py --type l_network --rs 307 --rl 50 --freq-ghz 2.4
```

RF PCB rules check (18 rules):
```
%PYTHON% scripts\rf\check_rf_rules.py --microstrip ms.json --cpwg cpwg.json --antenna ant.json --matching match.json --solid-ground-plane --num-layers 2 --substrate FR4
```

Standard RF 5-step flow: antenna -> microstrip -> cpwg -> matching -> check_rf_rules.
FR4 1.6mm quick ref: 50 Ohm microstrip = 3.08mm wide; CPWG 50 Ohm: w=4.0mm gap=0.5mm.

### 4.2 Digital Hardware Scripts (scripts/digital/)

MCU selection:
```
%PYTHON% scripts\digital\gen_mcu_selection_report.py --needs-wifi --needs-ble --low-power --rtos --application iot_sensor --prefer esp32
```

Power tree (input: rails.json with rail definitions):
```
%PYTHON% scripts\digital\gen_power_tree.py --rails-json rails.json --input-voltage 5.0
```

Power design rules: voltage drop >40% use DC-DC; RF supply needs dedicated ldo_rf rail; thermal >500mW upgrade package.

### 4.3 Protocol & Firmware Scripts (scripts/protocol/)

Firmware skeleton:
```
%PYTHON% scripts\protocol\gen_firmware_skeleton.py --platform stm32 --series G4 --peripherals uart,spi,i2c --rtos freertos --project MySensor
```

UART protocol definition:
```
%PYTHON% scripts\protocol\gen_uart_protocol.py --name SensorProto --baud 115200 --crc CRC16_MODBUS --commands "READ:0x01:4,ACK:0x10:0"
```

CRC calculation + frame builder:
```
%PYTHON% scripts\protocol\gen_crc_frame.py --poly CRC16_MODBUS --data "AA 55 04 01 DE AD BE EF" --build-frame
```

### 4.4 EDA Scripts (scripts/eda/)

Validate spec before generation:
```
%PYTHON% scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json
```

Generate KiCad project (schematic, PCB skeleton, netlist, BOM, pinmap, ERC):
```
%PYTHON% scripts\eda\gen_kicad_project.py --spec circuits\templates\esp32-c3-sensor-node.json --out out\my_project --project-name my_project
```

Static ERC check:
```
%PYTHON% scripts\eda\erc_check.py --manifest out\my_project\project.netlist.json
```

Generate EasyEDA Standard JSON preview:
```
%PYTHON% scripts\eda\gen_easyeda_std.py --manifest out\my_project\project.netlist.json --out out\my_project
```

Generate HTML/SVG visual preview:
```
%PYTHON% scripts\eda\render_design_preview.py --manifest out\my_project\project.netlist.json --out out\my_project
```

JLC assembly package (BOM + CPL + risk report):
```
%PYTHON% scripts\eda\gen_jlc_package.py --manifest out\my_project\project.netlist.json
```

Validate all EDA outputs (+ KiCad CLI if available):
```
%PYTHON% scripts\eda\validate_eda_outputs.py --out out\my_project
```

Batch generate all templates + HTML gallery:
```
%PYTHON% scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery
```

### 4.5 System Bundle (scripts/system/)

Full embedded system bundle (hardware + firmware + protocol + system contract):
```
%PYTHON% scripts\system\gen_embedded_system_bundle.py --spec circuits\templates\esp32-c3-sensor-node.json --out out\esp32_c3_system
```

### 4.6 Full EDA Pipeline (from-scratch project)

```
# Step 1: Write or select a project spec JSON (see templates/ for examples)
# Step 2: Validate spec
%PYTHON% scripts\eda\validate_project_spec.py --spec my_spec.json
# Step 3: Generate KiCad project
%PYTHON% scripts\eda\gen_kicad_project.py --spec my_spec.json --out out\my_project --project-name my_project
# Step 4: Static ERC
%PYTHON% scripts\eda\erc_check.py --manifest out\my_project\project.netlist.json
# Step 5: JLC package
%PYTHON% scripts\eda\gen_jlc_package.py --manifest out\my_project\project.netlist.json
# Step 6: Validate all outputs
%PYTHON% scripts\eda\validate_eda_outputs.py --out out\my_project
```

---

## 5. Templates (circuits/templates/)

| Template | Description |
|----------|-------------|
| `esp32-c3-sensor-node.json` | ESP32-C3 Wi-Fi/BLE sensor node, USB-C power, I2C sensor, PCB antenna |
| `esp32-s3-multisensor-node.json` | ESP32-S3 multi-sensor node with USB, more GPIOs and ADC channels |
| `nrf52-ble-low-power-node.json` | nRF52840 BLE low-power sensor node, battery-optimized |
| `lora-sx1262-sensor-node.json` | LoRa SX1262 long-range sensor node, SPI radio interface |
| `usb-lipo-esp32-node.json` | ESP32 node with USB-C + LiPo charging, MCP73831 charger IC |

---

## 6. Component Library

File: `components/library.json` (schema v2)

Contains pre-defined components with symbol, footprint, LCSC part, package, JLC assembly tier, alternatives, interfaces, decoupling, and required passives.

Categories: mcu_module, radio_module, sensor, connector, ldo, charger, protection, rf_connector, antenna, passive, indicator.

Key components: ESP32-C3-MINI-1, ESP32-S3-WROOM-1, NRF52840-MODULE, SX1262_MODULE, SHT31-DIS, BME280, USB-C-16P, TLV75533PDBVR, MCP73831, USBLC6-2SC6, U.FL, PCB_ANT_2G4, R_0402, C_0402, L_0402, LED_0603.

---

## 7. Output Files Manifest

All paths relative to `--out` directory:

| File | Description |
|------|-------------|
| `*.kicad_pro` | KiCad project file |
| `*.kicad_sch` | KiCad pin-level schematic (embedded custom symbols, net labels) |
| `*.kicad_pcb` | KiCad PCB skeleton (board outline, zones, RF keepout) |
| `*.easyeda.json` | EasyEDA Standard JSON schematic preview for JLC/LCSC |
| `project.netlist.json` | Machine-readable netlist (source of truth for ERC) |
| `bom.csv` | Generic BOM |
| `jlc_bom.csv` | JLC assembly-oriented BOM |
| `jlc_cpl.csv` | JLC component placement (auto-generated, needs manual review) |
| `jlc_assembly_report.md` | JLC assembly risk report (markdown) |
| `jlc_assembly_report.json` | JLC assembly risk report (JSON) |
| `pinmap.csv` | MCU pin assignment |
| `static_erc.md` | Static ERC report (FAIL must be zero) |
| `schematic_preview.html` | Interactive HTML schematic preview |
| `schematic_preview.svg` | SVG schematic preview |
| `spec_validation.json` | Pre-generation spec validation (JSON) |
| `spec_validation.md` | Pre-generation spec validation (markdown) |
| `eda_validation.md` | EDA output validation report |
| `production_readiness.md` | Production readiness gate report |
| `pcb_constraints.md` | PCB layout and routing constraints |
| `symbol_footprint_binding.md` | Symbol/footprint/assembly binding audit |
| `footprint_assignment.csv` | Footprint assignment for layout |

System bundle adds: `hardware/`, `firmware/`, `firmware/generated_protocol/`, `system_contract.md`, `README_system_bundle.md`.

---

## 8. MCP Tools

| Server | Tool | Purpose |
|--------|------|---------|
| parts_db_mcp | parts_search | Search components by keyword |
| parts_db_mcp | parts_get_detail | Full specs and pricing |
| parts_db_mcp | parts_find_alternatives | Find alternative parts |
| parts_db_mcp | parts_check_stock | Real-time stock and pricing |
| doc_output_mcp | doc_rf_design_report | RF design report (Word) |
| doc_output_mcp | doc_power_tree_report | Power architecture report (Word) |
| doc_output_mcp | doc_project_summary | Full project summary (Word) |
| doc_output_mcp | doc_export_markdown | Markdown to Word export |

---

## 9. Platform Quick Reference

| Platform | Notes |
|----------|-------|
| STM32 | HAL > LL > register; G0 (low-end), G4 (motor/power), H7 (high-end) |
| ESP32 | ESP-IDF preferred; NimBLE for lightweight BLE; external ADC for precision |
| nRF52 | Zephyr or nRF SDK; ultra-low-power BLE |
| Substrate | FR4 er=4.4, <=3GHz; Rogers 4003C er=3.55, <=20GHz |

---

## 10. Boundaries & Limitations

CAN DO:
- RF calculations (impedance, antenna sizing, matching, PCB rules)
- MCU selection reports with scoring
- Power tree generation and validation
- Protocol frame definitions and CRC
- KiCad project generation with pin-level schematics and PCB skeleton
- Static ERC (no FAIL allowed before proceeding)
- JLC assembly package (BOM, CPL, risk report)
- EasyEDA Standard JSON preview for JLC import
- HTML/SVG preview without EDA software
- Full system bundle (hardware + firmware + contract)
- Batch template gallery generation

CANNOT DO:
- Auto-route PCB traces (PCB skeleton only, not production-ready)
- Replace manual symbol/footprint library verification before production
- Guarantee EasyEDA native ERC pass (must import and verify in EasyEDA GUI)
- Replace VNA/SNA RF measurements (calculations are initial estimates only)
- Generate production Gerber/drill without kicad-cli on machine
- Replace firmware compilation and hardware debugging

BEFORE PRODUCTION:
- Replace generated symbols with vendor-verified libraries
- Run KiCad ERC + DRC with kicad-cli if available
- Verify JLC CPL coordinates manually
- Tune RF matching on real hardware (VNA required)
- Confirm all ERC FAIL=0 and WARN explained
