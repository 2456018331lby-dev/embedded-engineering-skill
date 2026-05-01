#!/usr/bin/env python3
"""Validate embedded hardware project spec JSON before EDA generation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = ROOT / "components" / "library.json"

ALLOWED_POWER_SOURCES = {"usb_c"}
ALLOWED_BATTERIES = {"lipo_1s", "liion_1s"}
SUPPORTED_SENSOR_INTERFACES = {"i2c"}
SUPPORTED_RADIO_INTERFACES = {"spi"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def add(results: list[dict[str, str]], status: str, check: str, message: str) -> None:
    results.append({"status": status, "check": check, "message": message})


def slug_ok(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_+-]+", value))


def normalize_pin_set(entries: Any) -> set[str]:
    pins: set[str] = set()
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return pins
    for entry in entries:
        if isinstance(entry, str):
            pins.add(entry)
        elif isinstance(entry, dict):
            for value in entry.values():
                if isinstance(value, str):
                    pins.add(value)
    return pins


def pin_pattern_for_mcu(part: str) -> re.Pattern[str] | None:
    upper = part.upper()
    if "ESP32" in upper or "RP2040" in upper:
        return re.compile(r"GPIO\d+")
    if "NRF" in upper:
        return re.compile(r"P\d+\.\d+")
    if "STM32" in upper:
        return re.compile(r"P[A-Z]\d+")
    return None


def validate_spec(spec: dict[str, Any], library: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    components = library.get("components", {})

    schema_version = spec.get("schema_version")
    if schema_version == 1:
        add(results, "PASS", "schema-version", "schema_version is 1.")
    else:
        add(results, "WARN", "schema-version", f"schema_version is {schema_version!r}; current templates use 1.")

    project_name = spec.get("project_name")
    if isinstance(project_name, str) and project_name.strip():
        if slug_ok(project_name):
            add(results, "PASS", "project-name", "project_name is present and slug-safe.")
        else:
            add(results, "WARN", "project-name", "project_name contains characters that will be normalized by the generator.")
    else:
        add(results, "FAIL", "project-name", "project_name is required and must be a non-empty string.")

    description = spec.get("description")
    if isinstance(description, str) and description.strip():
        add(results, "PASS", "description", "description is present.")
    else:
        add(results, "WARN", "description", "description is missing or empty.")

    input_power = spec.get("input_power")
    if not isinstance(input_power, dict):
        add(results, "FAIL", "input-power", "input_power must be an object.")
        input_power = {}
    power_source = input_power.get("source")
    if power_source in ALLOWED_POWER_SOURCES:
        add(results, "PASS", "input-power-source", f"input_power.source={power_source} is supported.")
    elif power_source:
        add(results, "FAIL", "input-power-source", f"Unsupported input_power.source={power_source!r}. Supported: {sorted(ALLOWED_POWER_SOURCES)}.")
    else:
        add(results, "FAIL", "input-power-source", "input_power.source is required.")

    voltage = input_power.get("voltage")
    if isinstance(voltage, (int, float)) and voltage > 0:
        add(results, "PASS", "input-power-voltage", f"input_power.voltage={voltage}V is valid.")
    else:
        add(results, "FAIL", "input-power-voltage", "input_power.voltage must be a positive number.")

    battery = input_power.get("battery")
    if battery is None:
        add(results, "PASS", "battery-mode", "No battery path requested.")
    elif battery in ALLOWED_BATTERIES:
        add(results, "PASS", "battery-mode", f"Battery mode {battery} is supported.")
    else:
        add(results, "FAIL", "battery-mode", f"Unsupported battery type {battery!r}. Supported: {sorted(ALLOWED_BATTERIES)}.")

    power = spec.get("power")
    if not isinstance(power, dict):
        add(results, "FAIL", "power", "power must be an object.")
        power = {}

    regulator_part = str(power.get("main_regulator", "")).strip()
    regulator_info = components.get(regulator_part)
    if regulator_part and regulator_info and regulator_info.get("kind") == "ldo":
        add(results, "PASS", "main-regulator", f"main_regulator {regulator_part} exists in the library.")
    elif regulator_part:
        add(results, "FAIL", "main-regulator", f"power.main_regulator={regulator_part!r} is missing or not tagged as an LDO.")
    else:
        add(results, "FAIL", "main-regulator", "power.main_regulator is required.")

    rails = power.get("rails")
    total_3v3_current = 0.0
    if isinstance(rails, list) and rails:
        add(results, "PASS", "power-rails", f"{len(rails)} power rail(s) declared.")
        for index, rail in enumerate(rails, start=1):
            if not isinstance(rail, dict):
                add(results, "FAIL", "power-rails", f"power.rails[{index}] must be an object.")
                continue
            name = rail.get("name")
            rail_voltage = rail.get("voltage")
            rail_current = rail.get("current_ma")
            if not isinstance(name, str) or not name:
                add(results, "FAIL", "power-rails", f"power.rails[{index}].name is required.")
            if not isinstance(rail_voltage, (int, float)) or rail_voltage <= 0:
                add(results, "FAIL", "power-rails", f"power.rails[{index}].voltage must be positive.")
            if not isinstance(rail_current, (int, float)) or rail_current <= 0:
                add(results, "FAIL", "power-rails", f"power.rails[{index}].current_ma must be positive.")
            elif name == "+3V3":
                total_3v3_current += float(rail_current)
    else:
        add(results, "FAIL", "power-rails", "power.rails must contain at least one rail.")

    if regulator_info and total_3v3_current:
        limit = regulator_info.get("output_current_ma")
        if isinstance(limit, (int, float)) and total_3v3_current <= float(limit):
            add(results, "PASS", "power-budget", f"+3V3 current budget {total_3v3_current:.0f}mA fits within {regulator_part} {float(limit):.0f}mA.")
        elif isinstance(limit, (int, float)):
            add(results, "FAIL", "power-budget", f"+3V3 current budget {total_3v3_current:.0f}mA exceeds {regulator_part} {float(limit):.0f}mA.")

    mcu_part = str(spec.get("mcu", "")).strip()
    mcu_info = components.get(mcu_part)
    if mcu_part and mcu_info and mcu_info.get("kind") == "mcu_module":
        add(results, "PASS", "mcu", f"MCU {mcu_part} exists in the library.")
    elif mcu_part:
        add(results, "FAIL", "mcu", f"mcu={mcu_part!r} is missing or not tagged as an MCU module.")
        mcu_info = {}
    else:
        add(results, "FAIL", "mcu", "mcu is required.")
        mcu_info = {}

    mcu_i2c_pins = normalize_pin_set(mcu_info.get("interfaces", {}).get("i2c"))
    mcu_uart_pins = normalize_pin_set(mcu_info.get("interfaces", {}).get("uart"))
    mcu_spi_pins = normalize_pin_set(mcu_info.get("interfaces", {}).get("spi"))
    reserved_pins = {str(pin) for pin in mcu_info.get("reserved_pins", [])}
    control_pins = {str(pin) for pin in mcu_info.get("control_pins", {}).keys()}
    pin_pattern = pin_pattern_for_mcu(mcu_part)

    def validate_pin_format(pin: str, check: str, context: str) -> None:
        if not pin_pattern:
            add(results, "WARN", check, f"{context}: no pin naming rule is defined for MCU {mcu_part}.")
            return
        if pin_pattern.fullmatch(pin):
            add(results, "PASS", check, f"{context}: pin {pin} matches MCU naming.")
        else:
            add(results, "FAIL", check, f"{context}: pin {pin} does not match MCU naming for {mcu_part}.")

    exclusive_pin_usage: dict[str, str] = {}

    def claim_pin(pin: str, owner: str, check: str) -> None:
        if pin in reserved_pins:
            add(results, "FAIL", check, f"{owner} uses reserved MCU pin {pin}.")
            return
        previous = exclusive_pin_usage.get(pin)
        if previous and previous != owner:
            add(results, "FAIL", check, f"{owner} reuses MCU pin {pin}, already claimed by {previous}.")
            return
        exclusive_pin_usage[pin] = owner
        add(results, "PASS", check, f"{owner} uses MCU pin {pin}.")

    sensors = spec.get("sensors", [])
    if isinstance(sensors, list):
        add(results, "PASS", "sensors", f"{len(sensors)} sensor entry(ies) declared.")
        seen_sensor_refs: set[str] = set()
        for index, sensor in enumerate(sensors, start=1):
            if not isinstance(sensor, dict):
                add(results, "FAIL", "sensor-entry", f"sensors[{index}] must be an object.")
                continue
            part = str(sensor.get("part", "")).strip()
            ref = str(sensor.get("ref", "")).strip()
            iface = str(sensor.get("interface", "i2c")).strip()
            info = components.get(part)
            if not info:
                add(results, "FAIL", "sensor-part", f"sensors[{index}].part={part!r} is not in the component library.")
                continue
            if info.get("kind") != "sensor":
                add(results, "FAIL", "sensor-part", f"sensors[{index}].part={part} is not tagged as a sensor.")
            else:
                add(results, "PASS", "sensor-part", f"Sensor part {part} exists in the library.")
            if iface not in SUPPORTED_SENSOR_INTERFACES:
                add(results, "FAIL", "sensor-interface", f"sensors[{index}].interface={iface!r} is unsupported by the generator.")
            elif iface not in info.get("interfaces", {}):
                add(results, "FAIL", "sensor-interface", f"Sensor {part} does not expose {iface} in the library.")
            elif iface == "i2c" and not mcu_i2c_pins:
                add(results, "FAIL", "sensor-interface", f"MCU {mcu_part} has no I2C pinset for sensor {part}.")
            else:
                add(results, "PASS", "sensor-interface", f"Sensor {part} uses supported {iface} interface.")
            if ref:
                if ref in seen_sensor_refs:
                    add(results, "FAIL", "sensor-ref", f"Duplicate sensor ref {ref}.")
                else:
                    seen_sensor_refs.add(ref)
                    add(results, "PASS", "sensor-ref", f"Sensor ref {ref} is unique.")
    else:
        add(results, "FAIL", "sensors", "sensors must be a list.")

    radio_modules = spec.get("radio_modules", [])
    if isinstance(radio_modules, list):
        if len(radio_modules) > 1:
            add(results, "FAIL", "radio-count", "More than one radio module is not yet supported by the current generator pin allocation.")
        else:
            add(results, "PASS", "radio-count", f"{len(radio_modules)} radio module entry(ies) declared.")
        seen_radio_refs: set[str] = set()
        for index, radio in enumerate(radio_modules, start=1):
            if not isinstance(radio, dict):
                add(results, "FAIL", "radio-entry", f"radio_modules[{index}] must be an object.")
                continue
            part = str(radio.get("part", "")).strip()
            ref = str(radio.get("ref", "")).strip()
            iface = str(radio.get("interface", "spi")).strip()
            info = components.get(part)
            if not info:
                add(results, "FAIL", "radio-part", f"radio_modules[{index}].part={part!r} is not in the component library.")
                continue
            if info.get("kind") != "radio_module":
                add(results, "FAIL", "radio-part", f"radio_modules[{index}].part={part} is not tagged as a radio module.")
            else:
                add(results, "PASS", "radio-part", f"Radio part {part} exists in the library.")
            if iface not in SUPPORTED_RADIO_INTERFACES:
                add(results, "FAIL", "radio-interface", f"radio_modules[{index}].interface={iface!r} is unsupported by the generator.")
            elif iface not in info.get("interfaces", {}):
                add(results, "FAIL", "radio-interface", f"Radio {part} does not expose {iface} in the library.")
            elif iface == "spi" and not mcu_spi_pins:
                add(results, "FAIL", "radio-interface", f"MCU {mcu_part} has no SPI pinset for radio {part}.")
            else:
                add(results, "PASS", "radio-interface", f"Radio {part} uses supported {iface} interface.")
            if ref:
                if ref in seen_radio_refs:
                    add(results, "FAIL", "radio-ref", f"Duplicate radio ref {ref}.")
                else:
                    seen_radio_refs.add(ref)
                    add(results, "PASS", "radio-ref", f"Radio ref {ref} is unique.")
            gpio_map = radio.get("gpio", {})
            if not isinstance(gpio_map, dict):
                add(results, "FAIL", "radio-gpio", f"radio_modules[{index}].gpio must be an object.")
                continue
            for signal, pin in gpio_map.items():
                pin_str = str(pin)
                validate_pin_format(pin_str, "radio-gpio-format", f"radio_modules[{index}].gpio.{signal}")
                claim_pin(pin_str, f"radio_modules[{index}].gpio.{signal}", "radio-gpio-claim")
    else:
        add(results, "FAIL", "radio-modules", "radio_modules must be a list when present.")

    debug = spec.get("debug", {})
    if isinstance(debug, dict):
        for field in ("uart_header", "boot_button", "reset_button"):
            value = debug.get(field)
            if isinstance(value, bool):
                add(results, "PASS", "debug", f"debug.{field} is boolean.")
            elif value is None:
                add(results, "PASS", "debug", f"debug.{field} omitted; generator default applies.")
            else:
                add(results, "FAIL", "debug", f"debug.{field} must be boolean when present.")
        if debug.get("uart_header", True):
            if mcu_uart_pins:
                add(results, "PASS", "debug-uart", f"MCU {mcu_part} exposes UART pins for debug header.")
            else:
                add(results, "FAIL", "debug-uart", f"MCU {mcu_part} does not expose a UART pinset for debug header generation.")
        if debug.get("boot_button", True):
            if control_pins:
                boot_pin = next((pin for pin in control_pins if "GPIO" in pin or pin.startswith("P")), "")
                if boot_pin:
                    claim_pin(boot_pin, "debug.boot_button", "debug-boot")
            else:
                add(results, "WARN", "debug-boot", f"MCU {mcu_part} has no control_pins metadata for boot button validation.")
    else:
        add(results, "FAIL", "debug", "debug must be an object when present.")

    rf = spec.get("rf", {})
    if isinstance(rf, dict):
        enabled = bool(rf.get("enabled"))
        add(results, "PASS", "rf-enabled", f"rf.enabled={enabled}.")
        if enabled:
            antenna = str(rf.get("antenna", "")).strip()
            antenna_info = components.get(antenna)
            if antenna and antenna_info and antenna_info.get("kind") == "antenna":
                add(results, "PASS", "rf-antenna", f"RF antenna {antenna} exists in the library.")
            else:
                add(results, "FAIL", "rf-antenna", "rf.enabled is true, but rf.antenna is missing or invalid.")
            connector = str(rf.get("test_connector", "")).strip()
            if connector:
                connector_info = components.get(connector)
                if connector_info and connector_info.get("kind") == "rf_connector":
                    add(results, "PASS", "rf-connector", f"RF test connector {connector} exists in the library.")
                else:
                    add(results, "FAIL", "rf-connector", f"rf.test_connector={connector!r} is not a known RF connector.")
    else:
        add(results, "FAIL", "rf", "rf must be an object when present.")

    indicators = spec.get("indicators", [])
    if isinstance(indicators, list):
        seen_indicator_names: set[str] = set()
        for index, indicator in enumerate(indicators, start=1):
            if not isinstance(indicator, dict):
                add(results, "FAIL", "indicator-entry", f"indicators[{index}] must be an object.")
                continue
            name = str(indicator.get("name", "")).strip()
            gpio = str(indicator.get("gpio", "")).strip()
            if not name:
                add(results, "FAIL", "indicator-name", f"indicators[{index}].name is required.")
            elif name in seen_indicator_names:
                add(results, "FAIL", "indicator-name", f"Duplicate indicator name {name}.")
            else:
                seen_indicator_names.add(name)
                add(results, "PASS", "indicator-name", f"Indicator {name} is unique.")
            if not gpio:
                add(results, "FAIL", "indicator-gpio", f"indicators[{index}].gpio is required.")
            else:
                validate_pin_format(gpio, "indicator-gpio-format", f"indicators[{index}].gpio")
                claim_pin(gpio, f"indicators[{index}].gpio", "indicator-gpio-claim")
    else:
        add(results, "FAIL", "indicators", "indicators must be a list.")

    reserved_spec = spec.get("reserved_pins")
    if reserved_spec is None:
        add(results, "PASS", "reserved-pins", "No additional reserved_pins override provided.")
    elif isinstance(reserved_spec, list) and all(isinstance(pin, str) for pin in reserved_spec):
        add(results, "PASS", "reserved-pins", f"{len(reserved_spec)} additional reserved pin(s) declared.")
    else:
        add(results, "FAIL", "reserved-pins", "reserved_pins must be a list of strings when present.")

    failures = [row for row in results if row["status"] == "FAIL"]
    warnings = [row for row in results if row["status"] == "WARN"]
    return {
        "success": not failures,
        "summary": {
            "pass": len([row for row in results if row["status"] == "PASS"]),
            "warn": len(warnings),
            "fail": len(failures),
        },
        "results": results,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Project Spec Validation",
        "",
        f"Verdict: `{'PASS' if report['success'] else 'FAIL'}`",
        "",
        "| Status | Check | Message |",
        "|---|---|---|",
    ]
    for row in report["results"]:
        lines.append(f"| {row['status']} | {row['check']} | {row['message']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate project spec JSON before EDA generation.")
    parser.add_argument("--spec", type=Path, required=True, help="Project spec JSON.")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY, help="Component library JSON.")
    parser.add_argument("--out", type=Path, help="Validation report JSON path.")
    args = parser.parse_args()

    spec = load_json(args.spec)
    library = load_json(args.library)
    report = validate_spec(spec, library)
    out = args.out or args.spec.with_suffix(".spec_validation.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(out.with_suffix(".md"), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
