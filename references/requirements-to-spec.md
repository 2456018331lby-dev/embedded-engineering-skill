# Requirements To Spec Guide

This guide defines how Claude Code should convert a natural-language embedded
hardware request into the JSON `project spec` consumed by
`scripts/eda/gen_kicad_project.py`.

## Goal

Keep the spec explicit enough that generation and validation are deterministic.
Do not leave board-critical assumptions hidden in prose.

## Minimal Required Fields

```json
{
  "schema_version": 1,
  "project_name": "example_board",
  "description": "Short engineering summary",
  "input_power": {
    "source": "usb_c",
    "voltage": 5.0,
    "net": "+VBUS",
    "esd_protection": true
  },
  "power": {
    "main_regulator": "TLV75533PDBVR",
    "rails": [
      {"name": "+3V3", "voltage": 3.3, "current_ma": 250, "source": "TLV75533PDBVR"}
    ]
  },
  "mcu": "ESP32-C3-MINI-1",
  "sensors": [],
  "debug": {
    "uart_header": true,
    "boot_button": true,
    "reset_button": true
  },
  "rf": {
    "enabled": false
  },
  "indicators": []
}
```

## Current Supported Top-Level Keys

- `schema_version`
- `project_name`
- `description`
- `input_power`
- `power`
- `mcu`
- `sensors`
- `radio_modules`
- `debug`
- `rf`
- `indicators`
- `reserved_pins`

## Field Rules

### `input_power`

- `source`: currently only `usb_c`
- `voltage`: positive number
- `net`: informational source net label; templates use `+VBUS`
- `esd_protection`: boolean
- `battery`: optional, currently `lipo_1s` or `liion_1s`
- `charger`: optional charger part when battery is present
- `charge_prog_resistor`: optional programming resistor value string

### `power`

- `main_regulator`: must exist in `components/library.json`
- `regulator_input_net`: optional; battery-backed boards should usually use `+BATT`
- `rails`: at least one rail
- `current_ma` should be a realistic budget, not a placeholder

### `mcu`

- Must map to a library part tagged as `mcu_module`
- Prefer existing template-compatible modules before inventing new part names

### `sensors`

Each entry is:

```json
{"part": "SHT31-DIS", "interface": "i2c", "ref": "U3"}
```

Rules:

- `part` must exist in the component library
- `interface` must be supported by both the generator and the part
- Current generator support is strongest for `i2c`
- `ref` should be unique

### `radio_modules`

Each entry is:

```json
{
  "part": "SX1262_MODULE",
  "ref": "U6",
  "interface": "spi",
  "rf_net": "RF_FEED",
  "gpio": {"dio1": "GPIO1", "busy": "GPIO0", "reset": "GPIO3"}
}
```

Rules:

- `part` must exist in the component library
- `interface` is currently expected to be `spi`
- `gpio` must avoid reserved or already claimed MCU pins
- Current generator path assumes one radio module unless pin allocation is extended

### `debug`

- `uart_header`: boolean
- `boot_button`: boolean
- `reset_button`: boolean

### `rf`

- `enabled`: boolean
- When `enabled` is true, provide at least `antenna`
- Optional `test_connector` should be a known RF connector such as `U.FL`

### `indicators`

Each entry is:

```json
{"name": "STATUS", "color": "green", "gpio": "GPIO3"}
```

Rules:

- `name` should be unique
- `gpio` must not collide with reserved or already-claimed MCU pins

## Conversion Workflow For Claude Code

1. Start from the closest template in `circuits/templates/`.
2. Change only the fields the user actually requested.
3. Keep component part names aligned with `components/library.json`.
4. Set realistic `current_ma` budgets before generation.
5. Run `scripts/eda/validate_project_spec.py` before `gen_kicad_project.py`.
6. If validation fails, fix the spec instead of pushing the problem into EDA generation.

## Validation Command

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json
```

## Current Boundary

- This spec format is the current generator contract, not a universal hardware schema.
- Passing spec validation does not mean KiCad ERC, PCB DRC, or JLCEDA checks have passed.
- If a requested part is missing from `components/library.json`, extend the library first or explicitly downgrade the result to a review-only partial spec.
