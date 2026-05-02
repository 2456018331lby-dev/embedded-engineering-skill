#!/usr/bin/env python3
"""Generate a KiCad-ready hardware project from a project spec.

The generated manifest remains the source of truth for static ERC, BOM, pinmap,
and secondary EDA exports. The KiCad schematic is generated as a pin-level
review schematic using embedded custom symbols, short wire stubs, and net labels
so it can be opened and checked by KiCad CLI without depending on local symbol
library coverage for every selected part.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from erc_check import run_checks as run_static_erc
from erc_check import write_markdown as write_static_erc_markdown
from footprint_reader import get_footprint_for_component, is_footprint_available
from symbol_reader import get_symbol_definition, get_lib_id_for_component, is_symbol_available
from gen_easyeda_std import build_easyeda_document
from gen_jlc_package import generate_jlc_package
from render_design_preview import svg_for_manifest, write_html
from validate_project_spec import validate_spec, write_markdown as write_spec_markdown
from validate_eda_outputs import validate_project, write_markdown


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = ROOT / "components" / "library.json"
DEFAULT_TEMPLATE = ROOT / "circuits" / "templates" / "esp32-c3-sensor-node.json"


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_+-]+", "_", value.strip())
    return value.strip("_") or "hardware_project"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass
class RefAlloc:
    counters: dict[str, int] = field(default_factory=dict)

    def next(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}{self.counters[prefix]}"


class DesignBuilder:
    def __init__(self, spec: dict[str, Any], library: dict[str, Any]) -> None:
        self.spec = spec
        self.library = library["components"]
        self.refs = RefAlloc()
        self.components: list[dict[str, Any]] = []
        self.nets: dict[str, list[str]] = {}
        self.pinmap: list[dict[str, str]] = []
        self.decisions: list[str] = []
        self.warnings: list[str] = []

    def lib(self, part: str) -> dict[str, Any]:
        if part not in self.library:
            raise SystemExit(f"Unknown library part: {part}")
        return self.library[part]

    def add_net(self, net: str, endpoint: str) -> None:
        self.nets.setdefault(net, [])
        if endpoint not in self.nets[net]:
            self.nets[net].append(endpoint)

    def add_component(
        self,
        part: str,
        ref: str | None = None,
        value: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        info = self.lib(part)
        if ref is None:
            ref = self.refs.next(self.prefix_for(info["kind"], part))
        else:
            match = re.match(r"([A-Za-z]+)(\d+)$", ref)
            if match:
                prefix, number = match.group(1), int(match.group(2))
                self.refs.counters[prefix] = max(self.refs.counters.get(prefix, 0), number)
        comp = {
            "ref": ref,
            "part": part,
            "value": value or part,
            "kind": info.get("kind", "unknown"),
            "symbol": info.get("symbol", ""),
            "footprint": info.get("footprint", ""),
            "description": info.get("description", ""),
            "lcsc_part": info.get("lcsc_part", ""),
            "supplier": info.get("supplier", ""),
            "package": info.get("package", ""),
            "jlc_assembly": info.get("jlc_assembly", ""),
            "alternatives": info.get("alternatives", []),
            "ratings": {
                key: info[key]
                for key in ("input_voltage_max", "output_voltage", "output_current_ma")
                if key in info
            },
            "fields": fields or {},
        }
        self.components.append(comp)
        return comp

    @staticmethod
    def prefix_for(kind: str, part: str) -> str:
        if kind in {"mcu_module", "sensor", "ldo"}:
            return "U"
        if kind in {"charger", "protection", "radio_module"}:
            return "U"
        if kind in {"connector", "rf_connector"}:
            return "J"
        if kind == "antenna":
            return "AE"
        if kind == "indicator":
            return "D"
        if part.startswith("R_"):
            return "R"
        if part.startswith("C_"):
            return "C"
        if part.startswith("L_"):
            return "L"
        if "SW" in part:
            return "SW"
        return "X"

    def add_passive(self, part: str, value: str, net_a: str, net_b: str, purpose: str) -> dict[str, Any]:
        comp = self.add_component(part, value=value, fields={"purpose": purpose})
        self.add_net(net_a, f"{comp['ref']}.1")
        self.add_net(net_b, f"{comp['ref']}.2")
        return comp

    def build(self) -> dict[str, Any]:
        project_name = slug(self.spec.get("project_name", "hardware_project"))
        self._add_power_input()
        self._add_battery_charger()
        self._add_regulator()
        mcu_ref = self._add_mcu()
        self._add_sensors(mcu_ref)
        self._add_radio_modules(mcu_ref)
        self._add_debug_headers(mcu_ref)
        self._add_rf_path()
        self._add_indicators(mcu_ref)
        return {
            "schema_version": 1,
            "project_name": project_name,
            "source_spec": self.spec,
            "components": self.components,
            "nets": dict(sorted(self.nets.items())),
            "pinmap": self.pinmap,
            "decisions": self.decisions,
            "warnings": self.warnings,
        }

    def _add_power_input(self) -> None:
        power = self.spec.get("input_power", {})
        if power.get("source") == "usb_c":
            usb = self.add_component("USB-C-16P", ref="J1")
            self.add_net("+VBUS", f"{usb['ref']}.VBUS")
            self.add_net("GND", f"{usb['ref']}.GND")
            self.add_net("CC1", f"{usb['ref']}.CC1")
            self.add_net("CC2", f"{usb['ref']}.CC2")
            self.add_passive("R_0402", "5.1k", "CC1", "GND", "USB-C Rd")
            self.add_passive("R_0402", "5.1k", "CC2", "GND", "USB-C Rd")
            self.decisions.append("USB-C sink input uses 5.1k Rd resistors on CC1/CC2.")
            if power.get("esd_protection", True):
                esd = self.add_component("USBLC6-2SC6", ref="U4")
                self.add_net("USB_D+", f"{usb['ref']}.D+")
                self.add_net("USB_D-", f"{usb['ref']}.D-")
                self.add_net("USB_D+", f"{esd['ref']}.IO1")
                self.add_net("USB_D-", f"{esd['ref']}.IO2")
                self.add_net("GND", f"{esd['ref']}.GND")
                self.decisions.append("USB data lines include ESD protection placeholder.")
        else:
            self.warnings.append("No supported input_power.source found; generated +VBUS as an external net.")
            self.add_net("+VBUS", "EXTERNAL.+VBUS")
            self.add_net("GND", "EXTERNAL.GND")

    def _add_battery_charger(self) -> None:
        power = self.spec.get("input_power", {})
        if power.get("battery") not in {"lipo_1s", "liion_1s"}:
            return
        batt = self.add_component("JST-PH-2", ref="J4", value="BATTERY")
        self.add_net("+BATT", f"{batt['ref']}.1")
        self.add_net("GND", f"{batt['ref']}.2")
        charger_part = power.get("charger", "MCP73831")
        charger = self.add_component(charger_part, ref="U5")
        self.add_net("+VBUS", f"{charger['ref']}.VIN")
        self.add_net("+BATT", f"{charger['ref']}.VBAT")
        self.add_net("GND", f"{charger['ref']}.GND")
        self.add_net(f"{charger['ref']}_PROG", f"{charger['ref']}.PROG")
        self.add_passive("R_0402", power.get("charge_prog_resistor", "10k"), f"{charger['ref']}_PROG", "GND", "LiPo charge current program")
        for cap in self.lib(charger_part).get("required_caps", []):
            self.add_passive("C_0402", cap["value"], cap["net"], "GND", f"{charger_part} {cap['purpose']}")
        self.decisions.append("Single-cell LiPo charger and battery connector included.")

    def _add_regulator(self) -> None:
        reg_part = self.spec.get("power", {}).get("main_regulator", "TLV75533PDBVR")
        input_net = self.spec.get("power", {}).get(
            "regulator_input_net",
            "+BATT" if self.spec.get("input_power", {}).get("battery") in {"lipo_1s", "liion_1s"} else "+VBUS",
        )
        reg = self.add_component(reg_part, ref="U2")
        self.add_net(input_net, f"{reg['ref']}.IN")
        self.add_net("+3V3", f"{reg['ref']}.OUT")
        self.add_net("GND", f"{reg['ref']}.GND")
        for cap in self.lib(reg_part).get("required_caps", []):
            other = "GND"
            cap_net = input_net if cap["net"] == "+VBUS" and input_net != "+VBUS" else cap["net"]
            self.add_passive("C_0402", cap["value"], cap_net, other, f"LDO {cap['purpose']} capacitor")

    def _add_mcu(self) -> str:
        mcu_part = self.spec.get("mcu", "ESP32-C3-MINI-1")
        mcu = self.add_component(mcu_part, ref="U1")
        info = self.lib(mcu_part)
        for net in info.get("supply_nets", ["+3V3"]):
            self.add_net(net, f"{mcu['ref']}.3V3")
        self.add_net("GND", f"{mcu['ref']}.GND")
        for cap in info.get("decoupling", []):
            for _ in range(int(cap.get("qty", 1))):
                self.add_passive("C_0402", cap["value"], cap["net"], "GND", f"{mcu_part} decoupling")
        for pin, rule in info.get("control_pins", {}).items():
            net = rule["default_net"]
            self.add_net(net, f"{mcu['ref']}.{pin}")
            if rule.get("requires") == "pullup":
                self.add_passive("R_0402", rule.get("resistance", "10k"), net, "+3V3", f"{pin} pullup")
        return mcu["ref"]

    def _add_sensors(self, mcu_ref: str) -> None:
        mcu_info = self.lib(self.spec.get("mcu", "ESP32-C3-MINI-1"))
        i2c_pinset = mcu_info["interfaces"]["i2c"][0]
        i2c_used = False
        for sensor_spec in self.spec.get("sensors", []):
            part = sensor_spec["part"]
            ref = sensor_spec.get("ref")
            sensor = self.add_component(part, ref=ref)
            iface = sensor_spec.get("interface", "i2c")
            self.add_net("+3V3", f"{sensor['ref']}.VDD")
            self.add_net("GND", f"{sensor['ref']}.GND")
            for cap in self.lib(part).get("decoupling", []):
                for _ in range(int(cap.get("qty", 1))):
                    self.add_passive("C_0402", cap["value"], cap["net"], "GND", f"{part} decoupling")
            if iface == "i2c":
                self.add_net("I2C_SCL", f"{sensor['ref']}.SCL")
                self.add_net("I2C_SDA", f"{sensor['ref']}.SDA")
                self.add_net("I2C_SCL", f"{mcu_ref}.{i2c_pinset['scl']}")
                self.add_net("I2C_SDA", f"{mcu_ref}.{i2c_pinset['sda']}")
                self.pinmap.extend([
                    {"interface": "i2c", "signal": "I2C_SCL", "mcu_pin": i2c_pinset["scl"], "net": "I2C_SCL"},
                    {"interface": "i2c", "signal": "I2C_SDA", "mcu_pin": i2c_pinset["sda"], "net": "I2C_SDA"},
                ])
                i2c_used = True
        if i2c_used:
            self.add_passive("R_0402", "4.7k", "I2C_SCL", "+3V3", "I2C pullup")
            self.add_passive("R_0402", "4.7k", "I2C_SDA", "+3V3", "I2C pullup")

    def _add_radio_modules(self, mcu_ref: str) -> None:
        mcu_info = self.lib(self.spec.get("mcu", "ESP32-C3-MINI-1"))
        spi_pinset = mcu_info["interfaces"]["spi"][0]
        for radio_spec in self.spec.get("radio_modules", []):
            part = radio_spec["part"]
            radio = self.add_component(part, ref=radio_spec.get("ref"))
            self.add_net("+3V3", f"{radio['ref']}.VCC")
            self.add_net("GND", f"{radio['ref']}.GND")
            for cap in self.lib(part).get("decoupling", []):
                for _ in range(int(cap.get("qty", 1))):
                    self.add_passive("C_0402", cap["value"], cap["net"], "GND", f"{part} decoupling")
            mapping = {
                "SPI_SCK": ("sck", "SCK"),
                "SPI_MOSI": ("mosi", "MOSI"),
                "SPI_MISO": ("miso", "MISO"),
                "SPI_CS": ("cs", "NSS"),
            }
            for net, (mcu_pin_key, radio_pin) in mapping.items():
                self.add_net(net, f"{mcu_ref}.{spi_pinset[mcu_pin_key] if mcu_pin_key in spi_pinset else spi_pinset[mcu_pin_key.lower()]}")
                self.add_net(net, f"{radio['ref']}.{radio_pin}")
                self.pinmap.append({"interface": "spi", "signal": net, "mcu_pin": spi_pinset.get(mcu_pin_key, spi_pinset.get(mcu_pin_key.lower(), "")), "net": net})
            gpio_map = radio_spec.get("gpio", {"dio1": "GPIO3", "busy": "GPIO1", "reset": "GPIO0"})
            for signal, pin in gpio_map.items():
                net = f"LORA_{signal.upper()}"
                self.add_net(net, f"{mcu_ref}.{pin}")
                self.add_net(net, f"{radio['ref']}.{signal.upper()}")
                self.pinmap.append({"interface": "gpio", "signal": net, "mcu_pin": pin, "net": net})
            if radio_spec.get("rf_net", "RF_FEED"):
                self.add_net(radio_spec.get("rf_net", "RF_FEED"), f"{radio['ref']}.RF")

    def _add_debug_headers(self, mcu_ref: str) -> None:
        debug = self.spec.get("debug", {})
        mcu_part = self.spec.get("mcu", "ESP32-C3-MINI-1")
        mcu_info = self.lib(mcu_part)
        uart = mcu_info["interfaces"]["uart"][0]
        if debug.get("uart_header", True):
            hdr = self.add_component("HEADER_1X04", ref="J2", value="UART_DBG")
            self.add_net("+3V3", f"{hdr['ref']}.1")
            self.add_net("UART_TX", f"{hdr['ref']}.2")
            self.add_net("UART_RX", f"{hdr['ref']}.3")
            self.add_net("GND", f"{hdr['ref']}.4")
            self.add_net("UART_TX", f"{mcu_ref}.{uart['tx']}")
            self.add_net("UART_RX", f"{mcu_ref}.{uart['rx']}")
            self.pinmap.extend([
                {"interface": "uart", "signal": "UART_TX", "mcu_pin": uart["tx"], "net": "UART_TX"},
                {"interface": "uart", "signal": "UART_RX", "mcu_pin": uart["rx"], "net": "UART_RX"},
            ])
        if debug.get("reset_button", True):
            sw = self.add_component("SW_PUSH", value="RESET")
            reset_net = "RESET" if "NRF" in mcu_part.upper() else "EN"
            self.add_net(reset_net, f"{mcu_ref}.{reset_net}")
            self.add_net(reset_net, f"{sw['ref']}.1")
            self.add_net("GND", f"{sw['ref']}.2")
        if debug.get("boot_button", True):
            sw = self.add_component("SW_PUSH", value="BOOT")
            self.add_net("BOOT", f"{sw['ref']}.1")
            self.add_net("GND", f"{sw['ref']}.2")

    def _add_rf_path(self) -> None:
        rf = self.spec.get("rf", {})
        if not rf.get("enabled"):
            return
        self.add_component(rf.get("antenna", "PCB_ANT_2G4"), ref="AE1", value="2.4GHz_ANT")
        self.add_net("RF_ANT", "AE1.FEED")
        if rf.get("matching", "pi_placeholder") == "pi_placeholder":
            self.add_passive("C_0402", "DNP", "RF_FEED", "GND", "RF pi shunt placeholder C1")
            self.add_passive("L_0402", "0R/DNP", "RF_FEED", "RF_ANT", "RF pi series placeholder")
            self.add_passive("C_0402", "DNP", "RF_ANT", "GND", "RF pi shunt placeholder C2")
            self.decisions.append("RF antenna path includes pi matching placeholders; tune with VNA after PCB fabrication.")
        if rf.get("test_connector"):
            conn = self.add_component(rf["test_connector"], ref="J3")
            self.add_net("RF_ANT", f"{conn['ref']}.SIG")
            self.add_net("GND", f"{conn['ref']}.SHIELD")

    def _add_indicators(self, mcu_ref: str) -> None:
        for item in self.spec.get("indicators", []):
            led = self.add_component("LED_0603", value=f"LED_{item.get('name', 'STATUS')}")
            res = self.add_passive("R_0402", "1k", "+3V3", f"LED_{item.get('name', 'STATUS')}", "LED current limit")
            self.add_net(f"LED_{item.get('name', 'STATUS')}", f"{led['ref']}.A")
            self.add_net(f"LED_{item.get('name', 'STATUS')}_GPIO", f"{led['ref']}.K")
            self.add_net(f"LED_{item.get('name', 'STATUS')}_GPIO", f"{mcu_ref}.{item.get('gpio', 'GPIO8')}")
            self.pinmap.append({
                "interface": "gpio",
                "signal": item.get("name", "STATUS"),
                "mcu_pin": item.get("gpio", "GPIO8"),
                "net": f"LED_{item.get('name', 'STATUS')}_GPIO",
            })
            res["fields"]["paired_led"] = led["ref"]


def kicad_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def kicad_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:+.-]+", "_", value.strip()) or "unnamed"


def pin_sort_key(pin: str) -> tuple[int, str]:
    upper = pin.upper()
    priority = {
        "GND": 0,
        "VSS": 0,
        "SHIELD": 0,
        "3V3": 1,
        "VDD": 1,
        "VCC": 1,
        "VBUS": 1,
        "VIN": 1,
        "IN": 1,
        "OUT": 2,
        "VBAT": 2,
    }
    if upper in priority:
        return (priority[upper], upper)
    if pin.isdigit():
        return (3, f"{int(pin):04d}")
    match = re.match(r"([A-Za-z]+)(\d+)$", pin)
    if match:
        return (4, f"{match.group(1).upper()}{int(match.group(2)):04d}")
    return (5, upper)


def endpoints_by_component(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    pins: dict[str, dict[str, str]] = {}
    for net, endpoints in manifest.get("nets", {}).items():
        for endpoint in endpoints:
            if "." not in endpoint:
                continue
            ref, pin = endpoint.split(".", 1)
            if ref == "EXTERNAL":
                continue
            pins.setdefault(ref, {})
            pins[ref].setdefault(pin, net)
    return pins


def symbol_ref_prefix(ref: str) -> str:
    match = re.match(r"([A-Za-z]+)", ref)
    return match.group(1) if match else "U"


def pin_electrical_type(pin: str, net: str, comp: dict[str, Any]) -> str:
    # Keep generated review schematics ERC-friendly. Static ERC enforces the
    # domain-specific rules; KiCad ERC is used here to verify parse/open/export.
    return "passive"


def split_symbol_pins(pins: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    left_priority = []
    right_priority = []
    for pin, net in pins:
        token = f"{pin} {net}".upper()
        if any(word in token for word in ("GND", "VSS", "SHIELD", "VBUS", "VIN", "VCC", "VDD", "3V3", "BATT")):
            left_priority.append((pin, net))
        else:
            right_priority.append((pin, net))
    if not right_priority:
        midpoint = (len(left_priority) + 1) // 2
        return left_priority[:midpoint], left_priority[midpoint:]
    return left_priority, right_priority


def symbol_geometry(pin_count: int) -> tuple[float, float]:
    body_w = 30.48
    body_h = max(17.78, ((pin_count + 1) // 2) * 3.81 + 7.62)
    return body_w, body_h


def write_custom_lib_symbol(lines: list[str], comp: dict[str, Any], pins: list[tuple[str, str]]) -> dict[str, Any]:
    ref = comp["ref"]
    # Try to use standard KiCad library symbol
    symbol_field = comp.get("symbol", "")
    std_lib_id = get_lib_id_for_component(symbol_field) if symbol_field else ""
    std_symbol = get_symbol_definition(std_lib_id) if std_lib_id else None

    if std_symbol:
        # Use real KiCad library symbol - embed the definition directly
        # First remove the (kicad_lib ...) wrapper and just get the (symbol ...) block
        lib_id = std_lib_id
        # Add the symbol definition as-is to the lib_symbols section
        lines.append(std_symbol)
        # Extract pin locations from the real symbol for net label placement
        left, right = split_symbol_pins(pins)
        body_w, body_h = 20.0, max(len(left), len(right)) * 2.54 + 5.08  # estimate
        pin_pitch = 2.54
        top_y = body_h / 2 - 2.54
        left_x = -body_w / 2 - 2.54
        right_x = body_w / 2 + 2.54
        pin_locations: dict[str, dict[str, Any]] = {}
        for side, side_pins, x, angle in (("left", left, left_x, 0), ("right", right, right_x, 180)):
            for idx, (pin, net) in enumerate(side_pins):
                y = top_y - idx * pin_pitch
                pin_locations[pin] = {"side": side, "x": x, "y": y, "net": net}
        return {"lib_id": lib_id, "pin_locations": pin_locations, "body_w": body_w, "body_h": body_h}

    # Fallback: generate custom embedded symbol
    lib_id = f"embedded:{kicad_id(ref)}"
    left, right = split_symbol_pins(pins)
    body_w, body_h = symbol_geometry(max(len(left), len(right)) * 2)
    top_y = body_h / 2 - 3.81
    pin_pitch = 3.81
    left_x = -body_w / 2 - 2.54
    right_x = body_w / 2 + 2.54

    lines.extend([
        f'    (symbol "{kicad_string(lib_id)}"',
        '      (pin_names (offset 1.016))',
        '      (exclude_from_sim no)',
        '      (in_bom yes)',
        '      (on_board yes)',
        '      (in_pos_files yes)',
        '      (duplicate_pin_numbers_are_jumpers no)',
        f'      (property "Reference" "{kicad_string(symbol_ref_prefix(ref))}" (at 0 {body_h / 2 + 3.81:.2f} 0)',
        '        (effects (font (size 1.27 1.27)))',
        '      )',
        f'      (property "Value" "{kicad_string(comp["value"])}" (at 0 {-body_h / 2 - 3.81:.2f} 0)',
        '        (effects (font (size 1.27 1.27)))',
        '      )',
        f'      (property "Footprint" "{kicad_string(comp.get("footprint", ""))}" (at 0 0 0)',
        '        (effects (font (size 1.27 1.27)) hide)',
        '      )',
        '      (property "Datasheet" "" (at 0 0 0)',
        '        (effects (font (size 1.27 1.27)) hide)',
        '      )',
        f'      (property "Description" "{kicad_string(comp.get("description", ""))}" (at 0 0 0)',
        '        (effects (font (size 1.27 1.27)) hide)',
        '      )',
        f'      (symbol "{kicad_string(kicad_id(ref))}_0_1"',
        f'        (rectangle (start {-body_w / 2:.2f} {body_h / 2:.2f}) (end {body_w / 2:.2f} {-body_h / 2:.2f})',
        '          (stroke (width 0.254) (type default))',
        '          (fill (type background))',
        '        )',
        '      )',
        f'      (symbol "{kicad_string(kicad_id(ref))}_1_1"',
    ])

    pin_locations: dict[str, dict[str, Any]] = {}
    for side, side_pins, x, angle in (("left", left, left_x, 0), ("right", right, right_x, 180)):
        for idx, (pin, net) in enumerate(side_pins):
            y = top_y - idx * pin_pitch
            pin_locations[pin] = {"side": side, "x": x, "y": y, "net": net}
            lines.extend([
                f'        (pin {pin_electrical_type(pin, net, comp)} line',
                f'          (at {x:.2f} {y:.2f} {angle})',
                '          (length 2.54)',
                f'          (name "{kicad_string(pin)}"',
                '            (effects (font (size 1.0 1.0)))',
                '          )',
                f'          (number "{kicad_string(pin)}"',
                '            (effects (font (size 1.0 1.0)))',
                '          )',
                '        )',
            ])
    lines.extend([
        '      )',
        '      (embedded_fonts no)',
        '    )',
    ])
    return {"lib_id": lib_id, "pin_locations": pin_locations, "body_w": body_w, "body_h": body_h}


def add_wire(lines: list[str], x1: float, y1: float, x2: float, y2: float) -> None:
    lines.extend([
        '  (wire',
        '    (pts',
        f'      (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})',
        '    )',
        '    (stroke (width 0) (type default))',
        f'    (uuid "{uuid.uuid4()}")',
        '  )',
    ])


def add_label(lines: list[str], text: str, x: float, y: float, side: str) -> None:
    angle = 180 if side == "left" else 0
    justify = "right bottom" if side == "left" else "left bottom"
    lines.extend([
        f'  (label "{kicad_string(text)}"',
        f'    (at {x:.2f} {y:.2f} {angle})',
        '    (effects',
        '      (font (size 1.0 1.0))',
        f'      (justify {justify})',
        '    )',
        f'    (uuid "{uuid.uuid4()}")',
        '  )',
    ])


def write_kicad_project(outdir: Path, manifest: dict[str, Any]) -> Path:
    name = manifest["project_name"]
    pro_path = outdir / f"{name}.kicad_pro"
    project = {
        "board": {"design_settings": {"defaults": {}}},
        "meta": {"filename": f"{name}.kicad_pro", "version": 1},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.25}]},
        "schematic": {"legacy_lib_dir": "", "drawing": {"intersheets_ref_own_page": False}},
    }
    write_json(pro_path, project)
    return pro_path


def board_geometry(manifest: dict[str, Any]) -> dict[str, float]:
    spec = manifest.get("source_spec", {})
    width = 70.0
    height = 45.0
    if spec.get("input_power", {}).get("battery") in {"lipo_1s", "liion_1s"}:
        height += 8.0
    if spec.get("rf", {}).get("enabled"):
        width += 14.0
    if len(spec.get("sensors", [])) > 1:
        width += 8.0
    if spec.get("radio_modules"):
        width += 10.0
    width = max(width, 72.0)
    height = max(height, 48.0)
    return {
        "width": width,
        "height": height,
        "margin": 4.0,
        "rf_keepout_w": 18.0 if spec.get("rf", {}).get("enabled") else 0.0,
        "power_zone_w": 18.0,
        "sensor_zone_w": 22.0 if spec.get("sensors") else 0.0,
    }


def add_gr_rect(lines: list[str], x1: float, y1: float, x2: float, y2: float, layer: str, width: float = 0.1) -> None:
    lines.extend([
        f'  (gr_rect (start {x1:.2f} {y1:.2f}) (end {x2:.2f} {y2:.2f})',
        f'    (stroke (width {width:.2f}) (type default))',
        '    (fill no)',
        f'    (layer "{layer}")',
        f'    (uuid "{uuid.uuid4()}")',
        '  )',
    ])


def add_gr_text(lines: list[str], text: str, x: float, y: float, layer: str = "Dwgs.User", size: float = 1.5) -> None:
    lines.extend([
        f'  (gr_text "{kicad_string(text)}" (at {x:.2f} {y:.2f} 0)',
        f'    (layer "{layer}")',
        f'    (uuid "{uuid.uuid4()}")',
        '    (effects',
        f'      (font (size {size:.2f} {size:.2f}) (thickness 0.20))',
        '    )',
        '  )',
    ])


def placement_plan(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    geo = board_geometry(manifest)
    width = geo["width"]
    height = geo["height"]
    margin = geo["margin"]
    placements: dict[str, dict[str, Any]] = {}
    pending: dict[str, list[dict[str, Any]]] = {
        "power": [],
        "mcu": [],
        "sensor": [],
        "radio": [],
        "debug": [],
        "rf": [],
        "led": [],
        "passive": [],
    }
    for comp in manifest["components"]:
        ref = comp["ref"]
        kind = comp.get("kind", "")
        part = comp.get("part", "")
        purpose = str(comp.get("fields", {}).get("purpose", "")).lower()
        if kind == "antenna" and comp.get("package") == "PCB":
            continue
        if ref == "J1" and "USB-C" in part:
            placements[ref] = {"x": width / 2, "y": height - 4.0, "rotation": 0.0, "layer": "Top"}
        elif ref == "J4" or "battery" in str(comp.get("value", "")).lower():
            placements[ref] = {"x": 7.5, "y": height / 2, "rotation": 90.0, "layer": "Top"}
        elif kind == "mcu_module":
            placements[ref] = {"x": width / 2 - 2.0, "y": height / 2, "rotation": 0.0, "layer": "Top"}
        elif kind == "radio_module":
            placements[ref] = {"x": width - margin - max(geo["rf_keepout_w"], 18.0) - 10.0, "y": height / 2 + 2.0, "rotation": 0.0, "layer": "Top"}
        elif ref == "J3" or kind == "rf_connector":
            placements[ref] = {"x": width - 5.0, "y": height / 2, "rotation": 90.0, "layer": "Top"}
        elif kind in {"ldo", "charger", "protection"} or ref == "U2" or ref == "U4" or ref == "U5":
            pending["power"].append(comp)
        elif kind == "sensor":
            pending["sensor"].append(comp)
        elif kind == "connector" or kind == "switch":
            pending["debug"].append(comp)
        elif kind == "indicator":
            pending["led"].append(comp)
        elif "rf" in purpose:
            pending["rf"].append(comp)
        else:
            pending["passive"].append(comp)

    def assign_grid(items: list[dict[str, Any]], x0: float, y0: float, dx: float, dy: float, cols: int, rotation: float = 0.0) -> None:
        for idx, comp in enumerate(items):
            col = idx % cols
            row = idx // cols
            placements[comp["ref"]] = {
                "x": x0 + col * dx,
                "y": y0 + row * dy,
                "rotation": rotation,
                "layer": "Top",
            }

    sensor_zone_x = width - margin - max(geo["rf_keepout_w"], 18.0) - 18.0
    assign_grid(pending["power"], 14.0, 12.0, 8.0, 8.0, 2)
    assign_grid(pending["sensor"], sensor_zone_x, 12.0, 10.0, 10.0, 2)
    assign_grid([c for c in pending["debug"] if c["ref"].startswith("J")], 10.0, 8.0, 0.0, 10.0, 1, 90.0)
    assign_grid([c for c in pending["debug"] if c["ref"].startswith("SW")], 16.0, height - 8.0, 10.0, 0.0, 2)
    assign_grid(pending["led"], width / 2 + 10.0, height - 8.0, 6.0, 0.0, 2)
    assign_grid(pending["rf"], width - margin - max(geo["rf_keepout_w"], 18.0) - 10.0, height / 2 - 12.0, 7.0, 7.0, 2, 90.0)
    assign_grid(pending["passive"], width / 2 - 18.0, 10.0, 6.5, 5.0, 5)
    return placements


def fp_effects_lines(layer: str, size: float = 1.0, hide: bool = False) -> list[str]:
    suffix = " hide" if hide else ""
    return [
        "      (effects",
        f"        (font (size {size:.2f} {size:.2f}) (thickness 0.15)){suffix}",
        "      )",
    ]


def footprint_lines(comp: dict[str, Any], placement: dict[str, Any], pins_by_ref: dict[str, dict[str, str]]) -> list[str]:
    ref = comp["ref"]
    value = comp["value"]
    layer = "F.Cu" if placement.get("layer", "Top") == "Top" else "B.Cu"
    x = float(placement["x"])
    y = float(placement["y"])
    rotation = float(placement.get("rotation", 0.0))

    # Try standard KiCad library footprint first
    fp_name = comp.get("footprint", "")
    if fp_name and ":" in fp_name:
        lib_fp = get_footprint_for_component(
            fp_name, ref=ref, value=value, x=x, y=y, rotation=rotation, layer=layer
        )
        if lib_fp is not None:
            return lib_fp.split("\n")

    # Fallback: generate footprint from scratch (original logic)
    silk = "F.SilkS" if layer == "F.Cu" else "B.SilkS"
    fab = "F.Fab" if layer == "F.Cu" else "B.Fab"
    mask_layers = '"F.Cu" "F.Paste" "F.Mask"' if layer == "F.Cu" else '"B.Cu" "B.Paste" "B.Mask"'
    lines = [
        f'  (footprint "gen_only:{kicad_string(comp.get("footprint", comp.get("part", ref)))}" (layer "{layer}")',
        f'    (uuid "{uuid.uuid4()}")',
        f'    (at {x:.2f} {y:.2f} {rotation:.2f})',
    ]
    attr = "through_hole" if "header" in comp.get("package", "").lower() else "smd"
    lines.append(f'    (attr {attr})')
    lines.extend([
        f'    (property "Reference" "{kicad_string(ref)}"',
        '      (at 0 -2.00 0)',
        f'      (layer "{silk}")',
        *fp_effects_lines(silk, 1.0),
        '    )',
        f'    (property "Value" "{kicad_string(value)}"',
        '      (at 0 2.20 0)',
        f'      (layer "{fab}")',
        *fp_effects_lines(fab, 1.0),
        '    )',
        f'    (property "Footprint" "{kicad_string(comp.get("footprint", ""))}"',
        '      (at 0 0 0)',
        f'      (layer "{fab}")',
        *fp_effects_lines(fab, 1.0, hide=True),
        '    )',
    ])
    package = str(comp.get("package", "")).lower()
    kind = str(comp.get("kind", "")).lower()
    pins = sorted(pins_by_ref.get(ref, {}).keys(), key=pin_sort_key)

    def add_rect(w: float, h: float) -> None:
        lines.extend([
            f'    (fp_rect (start {-w/2:.2f} {-h/2:.2f}) (end {w/2:.2f} {h/2:.2f})',
            f'      (stroke (width 0.12) (type default)) (fill no) (layer "{fab}")',
            f'      (uuid "{uuid.uuid4()}")',
            '    )',
        ])

    def add_pad(number: str, x: float, y: float, sx: float, sy: float, shape: str = "roundrect", th: bool = False) -> None:
        if th:
            lines.extend([
                f'    (pad "{kicad_string(number)}" thru_hole circle (at {x:.2f} {y:.2f}) (size {sx:.2f} {sx:.2f}) (drill {sy:.2f}) (layers "*.Cu" "*.Mask"))',
            ])
        else:
            rr = ' (roundrect_rratio 0.25)' if shape == "roundrect" else ""
            lines.extend([
                f'    (pad "{kicad_string(number)}" smd {shape} (at {x:.2f} {y:.2f}) (size {sx:.2f} {sy:.2f}) (layers {mask_layers}){rr})',
            ])

    if package == "0402":
        add_rect(1.0, 0.6)
        add_pad(pins[0] if pins else "1", -0.55, 0.0, 0.60, 0.70)
        add_pad(pins[1] if len(pins) > 1 else "2", 0.55, 0.0, 0.60, 0.70)
    elif package == "0603":
        add_rect(1.6, 0.8)
        add_pad(pins[0] if pins else "1", -0.80, 0.0, 0.90, 1.00)
        add_pad(pins[1] if len(pins) > 1 else "2", 0.80, 0.0, 0.90, 1.00)
    elif "sot-23-5" in package:
        add_rect(1.7, 2.9)
        left = pins[:3] or ["1", "2", "3"]
        right = pins[3:5] or ["4", "5"]
        for idx, pin in enumerate(left):
            add_pad(pin, -1.20, -0.95 + idx * 0.95, 0.60, 1.20)
        for idx, pin in enumerate(right):
            add_pad(pin, 1.20, -0.48 + idx * 0.95, 0.60, 1.20)
    elif "sot-23-6" in package:
        add_rect(1.7, 2.9)
        left = pins[:3] or ["1", "2", "3"]
        right = pins[3:6] or ["4", "5", "6"]
        for idx, pin in enumerate(left):
            add_pad(pin, -1.20, -0.95 + idx * 0.95, 0.60, 1.20)
        for idx, pin in enumerate(right):
            add_pad(pin, 1.20, -0.95 + idx * 0.95, 0.60, 1.20)
    elif "dfn-8" in package or "lga-8" in package:
        add_rect(2.5, 2.5)
        left = pins[:4] or ["1", "2", "3", "4"]
        right = pins[4:8] or ["5", "6", "7", "8"]
        for idx, pin in enumerate(left):
            add_pad(pin, -1.45, -0.98 + idx * 0.65, 0.45, 0.30, "rect")
        for idx, pin in enumerate(right):
            add_pad(pin, 1.45, -0.98 + idx * 0.65, 0.45, 0.30, "rect")
    elif "usb-c-smd" in package:
        add_rect(9.0, 7.0)
        use_pins = pins or ["VBUS", "GND", "CC1", "CC2", "D+", "D-"]
        top = use_pins[:8]
        bottom = use_pins[8:16]
        for idx, pin in enumerate(top):
            add_pad(pin, -3.5 + idx * 1.0, -3.1, 0.40, 1.50, "rect")
        for idx, pin in enumerate(bottom):
            add_pad(pin, -3.5 + idx * 1.0, 3.1, 0.40, 1.50, "rect")
    elif "u.fl" in package:
        add_rect(3.0, 3.0)
        use_pins = pins or ["SIG", "SHIELD1", "SHIELD2"]
        add_pad(use_pins[0], 0.0, 0.0, 1.10, 1.50, "rect")
        if len(use_pins) > 1:
            add_pad(use_pins[1], -1.4, 0.0, 0.90, 1.50, "rect")
        if len(use_pins) > 2:
            add_pad(use_pins[2], 1.4, 0.0, 0.90, 1.50, "rect")
    elif "2.54mm header" in package:
        count = len(pins) if pins else (4 if "1x04" in comp.get("part", "").lower() else 6)
        add_rect(2.0, max(2.0, count * 2.54))
        for idx in range(count):
            pin = pins[idx] if idx < len(pins) else str(idx + 1)
            add_pad(pin, 0.0, idx * 2.54 - (count - 1) * 1.27, 1.70, 1.00, th=True)
    elif "jst-ph-2" in package:
        add_rect(5.0, 4.0)
        add_pad(pins[0] if pins else "1", -1.00, 0.0, 1.70, 1.00, th=True)
        add_pad(pins[1] if len(pins) > 1 else "2", 1.00, 0.0, 1.70, 1.00, th=True)
    elif "smd switch" in package:
        add_rect(4.0, 3.0)
        add_pad(pins[0] if pins else "1", -1.5, -0.9, 0.90, 1.20, "rect")
        add_pad(pins[1] if len(pins) > 1 else "2", -1.5, 0.9, 0.90, 1.20, "rect")
        add_pad(pins[2] if len(pins) > 2 else "3", 1.5, -0.9, 0.90, 1.20, "rect")
        add_pad(pins[3] if len(pins) > 3 else "4", 1.5, 0.9, 0.90, 1.20, "rect")
    elif "smd module" in package or kind in {"mcu_module", "radio_module"}:
        left, right = split_symbol_pins([(pin, "") for pin in pins or ["1", "2", "3", "4"]])
        body_h = max(8.0, max(len(left), len(right)) * 1.0 + 2.0)
        body_w = 18.0 if kind == "mcu_module" else 14.0
        add_rect(body_w, body_h)
        for idx, (pin, _net) in enumerate(left):
            add_pad(pin, -body_w / 2 - 0.6, -body_h / 2 + 1.0 + idx * 1.0, 1.20, 0.50, "rect")
        for idx, (pin, _net) in enumerate(right):
            add_pad(pin, body_w / 2 + 0.6, -body_h / 2 + 1.0 + idx * 1.0, 1.20, 0.50, "rect")
    else:
        count = max(2, len(pins))
        add_rect(4.0, 2.0 + count * 0.3)
        for idx, pin in enumerate(pins[:count]):
            add_pad(pin, -1.2 + idx * 0.6, 0.0, 0.50, 1.00, "rect")

    lines.append('  )')
    return lines


def write_pcb(outdir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    name = manifest["project_name"]
    pcb_path = outdir / f"{name}.kicad_pcb"
    geo = board_geometry(manifest)
    width = geo["width"]
    height = geo["height"]
    margin = geo["margin"]
    spec = manifest.get("source_spec", {})
    nets = sorted(manifest.get("nets", {}).keys())
    pins_by_ref = endpoints_by_component(manifest)
    placements = placement_plan(manifest)

    lines = [
        '(kicad_pcb (version 20250114) (generator "embedded-engineering-skill")',
        '  (general',
        '    (thickness 1.6)',
        '    (legacy_teardrops no)',
        '  )',
        '  (paper "A4")',
        '  (title_block',
        f'    (title "{kicad_string(name)}")',
        '    (comment 1 "Generated PCB skeleton for placement/routing review.")',
        '  )',
        '  (layers',
        '    (0 "F.Cu" signal)',
        '    (31 "B.Cu" signal)',
        '    (32 "B.Adhes" user "B.Adhesive")',
        '    (33 "F.Adhes" user "F.Adhesive")',
        '    (34 "B.Paste" user)',
        '    (35 "F.Paste" user)',
        '    (36 "B.SilkS" user "B.Silkscreen")',
        '    (37 "F.SilkS" user "F.Silkscreen")',
        '    (38 "B.Mask" user)',
        '    (39 "F.Mask" user)',
        '    (40 "Dwgs.User" user "User.Drawings")',
        '    (41 "Cmts.User" user "User.Comments")',
        '    (42 "Eco1.User" user "User.Eco1")',
        '    (43 "Eco2.User" user "User.Eco2")',
        '    (44 "Edge.Cuts" user)',
        '    (45 "Margin" user)',
        '    (46 "B.CrtYd" user "B.Courtyard")',
        '    (47 "F.CrtYd" user "F.Courtyard")',
        '    (48 "B.Fab" user)',
        '    (49 "F.Fab" user)',
        '  )',
        '  (setup',
        '    (pad_to_mask_clearance 0.10)',
        '    (allow_soldermask_bridges_in_footprints no)',
        '    (tenting front back)',
        '    (pcbplotparams',
        '      (layerselection 0x00000000_00000000)',
        '      (plot_on_all_layers_selection 0x00000000_00000000)',
        '      (disableapertmacros no)',
        '      (usegerberextensions no)',
        '      (usegerberattributes yes)',
        '      (usegerberadvancedattributes yes)',
        '      (creategerberjobfile yes)',
        '      (dashed_line_dash_ratio 12.000000)',
        '      (dashed_line_gap_ratio 3.000000)',
        '      (svgprecision 4)',
        '      (plotframeref no)',
        '      (mode 1)',
        '      (useauxorigin no)',
        '      (hpglpennumber 1)',
        '      (hpglpenspeed 20)',
        '      (hpglpendiameter 15.000000)',
        '      (pdf_front_fp_property_popups yes)',
        '      (pdf_back_fp_property_popups yes)',
        '      (pdf_metadata yes)',
        '      (pdf_single_document no)',
        '      (dxfpolygonmode yes)',
        '      (dxfimperialunits yes)',
        '      (dxfusepcbnewfont yes)',
        '      (psnegative no)',
        '      (psa4output no)',
        '      (plotreference yes)',
        '      (plotvalue yes)',
        '      (plotfptext yes)',
        '      (plotinvisibletext no)',
        '      (sketchpadsonfab no)',
        '      (plotpadnumbers no)',
        '      (hidednponfab no)',
        '      (sketchdnponfab yes)',
        '      (crossoutdnponfab yes)',
        '      (subtractmaskfromsilk no)',
        '      (outputformat 1)',
        '      (mirror no)',
        '      (drillshape 1)',
        '      (scaleselection 1)',
        '      (outputdirectory "")',
        '    )',
        '  )',
        '  (net 0 "")',
    ]
    for idx, net in enumerate(nets, start=1):
        lines.append(f'  (net {idx} "{kicad_string(net)}")')

    add_gr_rect(lines, 0.0, 0.0, width, height, "Edge.Cuts")
    # Also add a proper board outline rectangle on Edge.Cuts for KiCad to recognize
    lines.extend([
        f'  (gr_rect (start 0.00 0.00) (end {width:.2f} {height:.2f})',
        '    (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts")',
        f'    (uuid "{uuid.uuid4()}")',
        '  )',
    ])

    # Add GND copper zone on F.Cu covering the entire board
    lines.extend([
        '  (zone',
        '    (net 1)',
        '    (net_name "GND")',
        '    (layer "F.Cu")',
        '    (uuid "{}")'.format(uuid.uuid4()),
        '    (hatch edge 0.500)',
        '    (connect_pads',
        '      (clearance 0.500)',
        '    )',
        '    (min_thickness 0.250)',
        '    (fill yes',
        '      (thermal_gap 0.500)',
        '      (thermal_bridge_width 0.500)',
        '    )',
        f'    (polygon (pts (xy 0.00 0.00) (xy {width:.2f} 0.00) (xy {width:.2f} {height:.2f}) (xy 0.00 {height:.2f})))',
        '  )',
        '  (zone',
        '    (net 1)',
        '    (net_name "GND")',
        '    (layer "B.Cu")',
        '    (uuid "{}")'.format(uuid.uuid4()),
        '    (hatch edge 0.500)',
        '    (connect_pads',
        '      (clearance 0.500)',
        '    )',
        '    (min_thickness 0.250)',
        '    (fill yes',
        '      (thermal_gap 0.500)',
        '      (thermal_bridge_width 0.500)',
        '    )',
        f'    (polygon (pts (xy 0.00 0.00) (xy {width:.2f} 0.00) (xy {width:.2f} {height:.2f}) (xy 0.00 {height:.2f})))',
        '  )',
    ])
    add_gr_text(lines, f"{name} PCB SKELETON", width / 2, height / 2, "Dwgs.User", 2.0)

    power_x2 = min(width - margin, geo["power_zone_w"] + margin)
    add_gr_rect(lines, margin, margin, power_x2, height - margin, "Dwgs.User")
    add_gr_text(lines, "POWER", (margin + power_x2) / 2, margin + 4.0)

    mcu_x1 = power_x2 + 2.0
    mcu_x2 = width - margin - max(geo["rf_keepout_w"], geo["sensor_zone_w"])
    if mcu_x2 > mcu_x1 + 10.0:
        add_gr_rect(lines, mcu_x1, margin, mcu_x2, height - margin, "Dwgs.User")
        add_gr_text(lines, "MCU / DIGITAL", (mcu_x1 + mcu_x2) / 2, margin + 4.0)

    if geo["sensor_zone_w"] > 0:
        sensor_x1 = max(mcu_x1 + 12.0, width - margin - geo["sensor_zone_w"] - geo["rf_keepout_w"])
        sensor_x2 = width - margin - geo["rf_keepout_w"]
        if sensor_x2 > sensor_x1 + 5.0:
            add_gr_rect(lines, sensor_x1, margin, sensor_x2, height / 2 - 2.0, "Dwgs.User")
            add_gr_text(lines, "SENSORS", (sensor_x1 + sensor_x2) / 2, margin + 4.0)

    if geo["rf_keepout_w"] > 0:
        rf_x1 = width - margin - geo["rf_keepout_w"]
        add_gr_rect(lines, rf_x1, margin, width - margin, height - margin, "Dwgs.User")
        add_gr_text(lines, "RF / ANTENNA KEEPOUT", rf_x1 + geo["rf_keepout_w"] / 2, margin + 4.0)

    if spec.get("input_power", {}).get("source") == "usb_c":
        add_gr_text(lines, "USB EDGE", width / 2, height - 3.0, "Cmts.User", 1.2)
    if spec.get("input_power", {}).get("battery") in {"lipo_1s", "liion_1s"}:
        add_gr_text(lines, "BATTERY CONNECTOR EDGE", 10.0, height / 2, "Cmts.User", 1.2)
    if spec.get("rf", {}).get("enabled"):
        add_gr_text(lines, "KEEP ANTENNA EDGE CLEAR OF COPPER", width - 12.0, height - 3.0, "Cmts.User", 1.0)

    for comp in manifest["components"]:
        if comp["ref"] in placements:
            lines.extend(footprint_lines(comp, placements[comp["ref"]], pins_by_ref))

    lines.append(')')
    pcb_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": pcb_path, "placements": placements}


def write_pcb_constraints(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "pcb_constraints.md"
    spec = manifest.get("source_spec", {})
    geo = board_geometry(manifest)
    lines = [
        f"# {manifest['project_name']} PCB Constraints",
        "",
        "## Board Skeleton",
        f"- Suggested board outline: {geo['width']:.0f}mm x {geo['height']:.0f}mm",
        "- The generated `.kicad_pcb` is a placement/routing skeleton, not a finished layout.",
        "",
        "## Placement Priorities",
        "- Keep power entry, charger, regulator, and bulk decoupling grouped near the power edge.",
        "- Keep decoupling capacitors tight to the MCU/module supply pins.",
        "- Keep debug header accessible from a board edge where practical.",
    ]
    if spec.get("input_power", {}).get("source") == "usb_c":
        lines.append("- Place the USB-C receptacle directly on the board edge and keep ESD protection close to the connector.")
    if spec.get("input_power", {}).get("battery") in {"lipo_1s", "liion_1s"}:
        lines.append("- Place the battery connector on an edge with strain relief and keep charger components nearby.")
    if spec.get("sensors"):
        lines.append("- Place sensors away from switch nodes, antenna keepouts, and board edges exposed to handling noise.")
    if spec.get("rf", {}).get("enabled"):
        lines.extend([
            "- Keep the antenna edge and RF keepout clear of copper pours, fast digital lines, and tall metal parts.",
            "- Place pi-matching placeholders immediately between the radio RF pin and the antenna feed.",
            "- Route the RF feed as a controlled-impedance trace and preserve a continuous ground return.",
        ])
    if spec.get("radio_modules"):
        lines.append("- Keep SPI and radio control lines short, referenced to solid ground, and separated from the antenna section.")
    lines.extend([
        "",
        "## Routing Priorities",
        "- Route power rails first with short return paths and local decoupling.",
        "- Keep I2C pullups near the bus source or central branch point.",
        "- Keep reset/boot strapping traces quiet and away from noisy switching nodes.",
        "",
        "## Manufacturing Notes",
        "- Review `jlc_cpl.csv` if present; current coordinates come from auto-placement and still need engineering confirmation before fabrication.",
        "- Complete KiCad PCB DRC, Gerber/drill export, and final footprint review before fabrication.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_schematic(outdir: Path, manifest: dict[str, Any]) -> Path:
    name = manifest["project_name"]
    sch_path = outdir / f"{name}.kicad_sch"
    pins_by_ref = endpoints_by_component(manifest)
    symbol_defs: list[str] = ['  (lib_symbols']
    symbol_meta: dict[str, dict[str, Any]] = {}
    for comp in manifest["components"]:
        pins = sorted(pins_by_ref.get(comp["ref"], {}).items(), key=lambda item: pin_sort_key(item[0]))
        if not pins:
            pins = [("NC", "NC")]
        symbol_meta[comp["ref"]] = write_custom_lib_symbol(symbol_defs, comp, pins)
    symbol_defs.append('  )')

    lines = [
        '(kicad_sch (version 20230121) (generator "embedded-engineering-skill")',
        f'  (uuid "{uuid.uuid4()}")',
        '  (paper "A3")',
        '  (title_block',
        f'    (title "{kicad_string(name)}")',
        '    (comment 1 "Generated pin-level review schematic. project.netlist.json is the source of truth for static ERC.")',
        '  )',
    ]
    lines.extend(symbol_defs)

    columns = [38.0, 118.0, 198.0, 278.0]
    col_width = 80.0
    row_gap = 22.0
    y = 35.0
    row_height = 0.0
    placed: list[dict[str, Any]] = []
    for idx, comp in enumerate(manifest["components"]):
        col = idx % len(columns)
        if col == 0 and idx:
            y += row_height + row_gap
            row_height = 0.0
        meta = symbol_meta[comp["ref"]]
        cx = columns[col]
        cy = y
        row_height = max(row_height, float(meta["body_h"]))
        placed.append({"comp": comp, "x": cx, "y": cy, "meta": meta})

    for item in placed:
        comp = item["comp"]
        cx = item["x"]
        cy = item["y"]
        meta = item["meta"]
        pins = sorted(pins_by_ref.get(comp["ref"], {}).items(), key=lambda row: pin_sort_key(row[0]))
        lines.extend([
            f'  (symbol (lib_id "{kicad_string(meta["lib_id"])}") (at {cx:.2f} {cy:.2f} 0) (unit 1)',
            '    (exclude_from_sim no)',
            '    (in_bom yes) (on_board yes)',
            '    (dnp no)',
            f'    (uuid "{uuid.uuid4()}")',
            f'    (property "Reference" "{kicad_string(comp["ref"])}" (at {cx:.2f} {cy - 3.0:.2f} 0)',
            '      (effects (font (size 1.27 1.27)))',
            '    )',
            f'    (property "Value" "{kicad_string(comp["value"])}" (at {cx:.2f} {cy + 3.0:.2f} 0)',
            '      (effects (font (size 1.27 1.27)))',
            '    )',
            f'    (property "Footprint" "{kicad_string(comp["footprint"])}" (at {cx:.2f} {cy + 6.0:.2f} 0)',
            '      (effects (font (size 1.0 1.0)) hide)',
            '    )',
        ])
        for pin, _net in pins:
            lines.extend([
                f'    (pin "{kicad_string(pin)}"',
                f'      (uuid "{uuid.uuid4()}")',
                '    )',
            ])
        lines.extend([
            '    (instances',
            f'      (project "{kicad_string(name)}"',
            f'        (path "/{uuid.uuid4()}"',
            f'          (reference "{kicad_string(comp["ref"])}")',
            '          (unit 1)',
            '        )',
            '      )',
            '    )',
            '  )',
        ])

        for pin, net in pins:
            pin_info = meta["pin_locations"].get(pin)
            if not pin_info or net == "NC":
                continue
            pin_x = cx + float(pin_info["x"])
            pin_y = cy + float(pin_info["y"])
            if pin_info["side"] == "left":
                label_x = pin_x - 7.62
            else:
                label_x = pin_x + 7.62
            add_wire(lines, pin_x, pin_y, label_x, pin_y)
            add_label(lines, net, label_x, pin_y, str(pin_info["side"]))

    net_lines = [f"{net}: {', '.join(endpoints)}" for net, endpoints in manifest["nets"].items()]
    note = "\\n".join(net_lines[:24])
    note_y = max((item["y"] + float(item["meta"]["body_h"]) / 2 for item in placed), default=80.0) + 15.0
    lines.extend([
        f'  (text "{kicad_string(note)}" (at 15.00 {note_y:.2f} 0)',
        '    (effects (font (size 1.0 1.0)) (justify left bottom))',
        '  )',
        '  (sheet_instances',
        '    (path "/" (page "1"))',
        '  )',
        ')',
    ])
    sch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sch_path


def write_bom(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "bom.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ref",
                "value",
                "part",
                "kind",
                "symbol",
                "footprint",
                "lcsc_part",
                "supplier",
                "package",
                "jlc_assembly",
                "description",
            ],
        )
        writer.writeheader()
        for comp in manifest["components"]:
            writer.writerow({k: comp.get(k, "") for k in writer.fieldnames or []})
    return path


def write_pinmap(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "pinmap.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["interface", "signal", "mcu_pin", "net"])
        writer.writeheader()
        for row in manifest["pinmap"]:
            writer.writerow(row)
    return path


def write_review(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "design_review.md"
    lines = [
        f"# {manifest['project_name']} Design Review",
        "",
        "## Decisions",
        *(f"- {d}" for d in manifest["decisions"]),
        "",
        "## Warnings",
        *(f"- {w}" for w in manifest["warnings"] or ["None"]),
        "",
        "## Required Next Checks",
        "- Review `static_erc.md`; clear every FAIL before PCB layout.",
        "- Open the generated `.kicad_sch` in KiCad and inspect the pin-level labelled schematic.",
        "- Open the generated `.kicad_pcb` and use `pcb_constraints.md` as the placement/routing starting point.",
        "- Review `symbol_footprint_binding.md` and `footprint_assignment.csv` before handing the design to layout or manufacturing.",
        "- Replace embedded review symbols with exact manufacturer/library symbols before final production release if needed.",
        "- Run KiCad ERC after any manual schematic edits.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def binding_status(comp: dict[str, Any]) -> str:
    if not comp.get("symbol") or not comp.get("footprint"):
        return "missing_binding"
    if comp.get("jlc_assembly") in {"manual", "not_applicable"}:
        return "manual_review"
    if comp.get("jlc_assembly") in {"basic", "extended"} and not comp.get("lcsc_part"):
        return "missing_lcsc"
    return "review_ready"


def binding_source(comp: dict[str, Any]) -> str:
    if not comp.get("symbol") or not comp.get("footprint"):
        return "missing"
    if comp.get("jlc_assembly") in {"basic", "extended"} and comp.get("lcsc_part"):
        return "library+lcsc"
    if comp.get("jlc_assembly") in {"manual", "not_applicable"}:
        return "manual_or_non_smt"
    return "review_generated"


def write_symbol_footprint_binding(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "symbol_footprint_binding.md"
    lines = [
        f"# {manifest['project_name']} Symbol and Footprint Binding",
        "",
        "| Ref | Part | Symbol | Footprint | Package | LCSC | JLC | Binding Source | Binding Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for comp in manifest.get("components", []):
        status = binding_status(comp)
        lines.append(
            f"| {comp.get('ref', '')} | {comp.get('part', '')} | {comp.get('symbol', '')} | "
            f"{comp.get('footprint', '')} | {comp.get('package', '')} | {comp.get('lcsc_part', '')} | "
            f"{comp.get('jlc_assembly', '')} | {binding_source(comp)} | {status} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_footprint_assignment(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / "footprint_assignment.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ref",
                "part",
                "value",
                "kind",
                "symbol",
                "footprint",
                "package",
                "lcsc_part",
                "jlc_assembly",
                "binding_source",
                "binding_status",
            ],
        )
        writer.writeheader()
        for comp in manifest.get("components", []):
            writer.writerow({
                "ref": comp.get("ref", ""),
                "part": comp.get("part", ""),
                "value": comp.get("value", ""),
                "kind": comp.get("kind", ""),
                "symbol": comp.get("symbol", ""),
                "footprint": comp.get("footprint", ""),
                "package": comp.get("package", ""),
                "lcsc_part": comp.get("lcsc_part", ""),
                "jlc_assembly": comp.get("jlc_assembly", ""),
                "binding_source": binding_source(comp),
                "binding_status": binding_status(comp),
            })
    return path


def write_production_readiness(
    outdir: Path,
    manifest: dict[str, Any],
    static_erc: list[dict[str, str]],
    validation: dict[str, Any],
    jlc_report: dict[str, Any] | None = None,
) -> Path:
    path = outdir / "production_readiness.md"
    static_fails = [row for row in static_erc if row.get("severity") == "FAIL"]
    static_warns = [row for row in static_erc if row.get("severity") == "WARN"]
    validation_fails = [row for row in validation.get("results", []) if row.get("status") == "FAIL"]
    missing_lcsc = [
        comp for comp in manifest["components"]
        if comp.get("jlc_assembly") in {"basic", "extended"} and not comp.get("lcsc_part")
    ]
    missing_footprint = [comp for comp in manifest["components"] if not comp.get("footprint")]
    manual_parts = [
        comp for comp in manifest["components"]
        if comp.get("jlc_assembly") in {"manual", "not_applicable", ""}
    ]
    jlc_blockers = list((jlc_report or {}).get("blockers", []))
    jlc_warnings = list((jlc_report or {}).get("warnings", []))
    placement_mode = str((jlc_report or {}).get("placement_mode", "placeholder"))
    verdict = "REVIEW_READY"
    if static_fails or validation_fails or missing_footprint or jlc_blockers:
        verdict = "BLOCKED"
    elif static_warns or missing_lcsc or jlc_warnings:
        verdict = "NEEDS_ENGINEERING_REVIEW"

    lines = [
        f"# {manifest['project_name']} Production Readiness",
        "",
        f"Verdict: **{verdict}**",
        "",
        "This report is a manufacturing readiness gate for the generated review schematic. It does not replace final KiCad/JLCEDA checks.",
        "",
        "## Gate Summary",
        "",
        f"- Static ERC failures: {len(static_fails)}",
        f"- Static ERC warnings: {len(static_warns)}",
        f"- EDA validation failures: {len(validation_fails)}",
        f"- Missing footprints: {len(missing_footprint)}",
        f"- JLC basic/extended parts missing LCSC IDs: {len(missing_lcsc)}",
        f"- Manual/not-applicable assembly parts: {len(manual_parts)}",
        f"- JLC package blockers: {len(jlc_blockers)}",
        f"- JLC package warnings: {len(jlc_warnings)}",
        "",
        "## Required Before Fabrication",
        "",
        "- Clear every `FAIL` in `static_erc.md` and `eda_validation.md`.",
        "- Bind critical ICs to team-approved manufacturer symbols and footprints if the embedded review symbols are not sufficient.",
        "- Import the EasyEDA/JLCEDA artifact into JLCEDA and run its official checks before claiming JLCEDA verification.",
        (
            "- Review `jlc_cpl.csv`; coordinates come from the auto-placed KiCad PCB skeleton and still require engineering review."
            if placement_mode == "real"
            else "- Replace `jlc_cpl_placeholder.csv` with real PCB placement coordinates before uploading assembly files."
        ),
        "- Complete PCB layout, KiCad PCB DRC, Gerber/drill export, BOM/CPL review, and fab-side checks.",
    ]
    if missing_lcsc:
        lines.extend(["", "## Missing LCSC IDs", ""])
        lines.extend(f"- {comp['ref']} {comp.get('value', '')} ({comp.get('jlc_assembly', '')})" for comp in missing_lcsc)
    if missing_footprint:
        lines.extend(["", "## Missing Footprints", ""])
        lines.extend(f"- {comp['ref']} {comp.get('value', '')}" for comp in missing_footprint)
    if validation_fails:
        lines.extend(["", "## EDA Validation Failures", ""])
        lines.extend(f"- {row.get('check')}: {row.get('message')}" for row in validation_fails)
    if jlc_blockers:
        lines.extend(["", "## JLC Package Blockers", ""])
        lines.extend(f"- {item}" for item in jlc_blockers)
    if jlc_warnings:
        lines.extend(["", "## JLC Package Warnings", ""])
        lines.extend(f"- {item}" for item in jlc_warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_preview(outdir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    svg = svg_for_manifest(manifest)
    svg_path = outdir / "schematic_preview.svg"
    html_path = outdir / "schematic_preview.html"
    svg_path.write_text(svg + "\n", encoding="utf-8")
    write_html(html_path, manifest, svg)
    return {"schematic_preview_svg": svg_path, "schematic_preview_html": html_path}


def write_easyeda(outdir: Path, manifest: dict[str, Any]) -> Path:
    path = outdir / f"{manifest['project_name']}.easyeda.json"
    document = build_easyeda_document(manifest)
    write_json(path, document)
    return path


def generate_project(
    spec_path: Path,
    library_path: Path,
    outdir: Path,
    project_name: str | None = None,
) -> dict[str, Any]:
    spec = load_json(spec_path)
    if project_name:
        spec["project_name"] = project_name
    library = load_json(library_path)
    outdir.mkdir(parents=True, exist_ok=True)
    spec_validation = validate_spec(spec, library)
    spec_validation_path = outdir / "spec_validation.json"
    write_json(spec_validation_path, spec_validation)
    write_spec_markdown(outdir / "spec_validation.md", spec_validation)
    if not spec_validation["success"]:
        failures = "; ".join(row["message"] for row in spec_validation["results"] if row["status"] == "FAIL")
        raise SystemExit(f"Project spec validation failed: {failures}")

    manifest = DesignBuilder(spec, library).build()
    manifest_path = outdir / "project.netlist.json"
    write_json(manifest_path, manifest)
    static_erc = run_static_erc(manifest)
    static_erc_path = outdir / "static_erc.md"
    write_static_erc_markdown(static_erc_path, manifest["project_name"], static_erc)
    pcb_result = write_pcb(outdir, manifest)
    outputs = {
        "spec_validation": str(spec_validation_path),
        "manifest": str(manifest_path),
        "kicad_project": str(write_kicad_project(outdir, manifest)),
        "kicad_schematic": str(write_schematic(outdir, manifest)),
        "kicad_pcb": str(pcb_result["path"]),
        "easyeda_standard": str(write_easyeda(outdir, manifest)),
        "bom": str(write_bom(outdir, manifest)),
        "pinmap": str(write_pinmap(outdir, manifest)),
        "static_erc": str(static_erc_path),
        "design_review": str(write_review(outdir, manifest)),
        "pcb_constraints": str(write_pcb_constraints(outdir, manifest)),
        "symbol_footprint_binding": str(write_symbol_footprint_binding(outdir, manifest)),
        "footprint_assignment": str(write_footprint_assignment(outdir, manifest)),
    }
    outputs.update({key: str(path) for key, path in write_preview(outdir, manifest).items()})
    jlc_result = generate_jlc_package(manifest, outdir, pcb_result["placements"])
    outputs.update(jlc_result["outputs"])
    preliminary_validation = {"results": []}
    outputs["production_readiness"] = str(write_production_readiness(outdir, manifest, static_erc, preliminary_validation, jlc_result["report"]))
    validation = validate_project(outdir)
    write_production_readiness(outdir, manifest, static_erc, validation, jlc_result["report"])
    validation_path = outdir / "eda_validation.json"
    validation_path.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(outdir / "eda_validation.md", validation)
    outputs["eda_validation"] = str(validation_path)
    outputs["kicad_position"] = str(outdir / "kicad_position.csv")
    outputs["gerbers"] = str(outdir / "gerbers")
    outputs["drill"] = str(outdir / "drill")
    return {"success": True, "outputs": outputs, "warnings": manifest["warnings"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate KiCad project skeleton from embedded hardware spec.")
    parser.add_argument("--spec", type=Path, help="Project spec JSON. Defaults to ESP32-C3 sensor node template.")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY, help="Component library JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory.")
    parser.add_argument("--project-name", help="Override project name.")
    args = parser.parse_args()

    spec_path = args.spec or DEFAULT_TEMPLATE
    result = generate_project(spec_path, args.library, args.out, args.project_name)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
