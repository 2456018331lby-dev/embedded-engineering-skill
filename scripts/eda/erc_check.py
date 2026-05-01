#!/usr/bin/env python3
"""Run static ERC checks against project.netlist.json.

This checker validates the machine-readable manifest emitted by
gen_kicad_project.py. It does not replace KiCad ERC; it catches common
hardware-generation omissions before the design reaches KiCad.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def endpoints_by_ref(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for net, endpoints in manifest.get("nets", {}).items():
        for endpoint in endpoints:
            if "." not in endpoint:
                continue
            ref, pin = endpoint.split(".", 1)
            out.setdefault(ref, {}).setdefault(net, []).append(pin)
    return out


def component(manifest: dict[str, Any], ref: str) -> dict[str, Any] | None:
    for comp in manifest.get("components", []):
        if comp.get("ref") == ref:
            return comp
    return None


def refs_with_purpose(manifest: dict[str, Any], contains: str) -> list[str]:
    needle = contains.lower()
    refs = []
    for comp in manifest.get("components", []):
        purpose = str(comp.get("fields", {}).get("purpose", "")).lower()
        if needle in purpose:
            refs.append(comp["ref"])
    return refs


def ref_connects(ref_nets: dict[str, list[str]], *nets: str) -> bool:
    return all(net in ref_nets for net in nets)


def add(results: list[dict[str, str]], severity: str, rule: str, message: str, fix: str = "") -> None:
    results.append({"severity": severity, "rule": rule, "message": message, "fix": fix})


def run_checks(manifest: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    nets = manifest.get("nets", {})
    by_ref = endpoints_by_ref(manifest)
    components = manifest.get("components", [])
    source_spec = manifest.get("source_spec", {})

    for required in ("GND", "+3V3"):
        if required not in nets:
            add(results, "FAIL", "PWR-01", f"Required net {required} is missing.", f"Create and connect {required}.")
        elif len(nets[required]) < 2:
            add(results, "FAIL", "PWR-02", f"Net {required} has fewer than two endpoints.", f"Connect all loads and sources to {required}.")

    for comp in components:
        if not comp.get("symbol"):
            add(results, "FAIL", "LIB-01", f"{comp['ref']} has no KiCad symbol.", "Add symbol mapping in components/library.json.")
        if not comp.get("footprint"):
            add(results, "FAIL", "LIB-02", f"{comp['ref']} has no KiCad footprint.", "Add footprint mapping in components/library.json.")
        if comp.get("jlc_assembly") in {"basic", "extended"} and not comp.get("lcsc_part"):
            add(results, "WARN", "JLC-01", f"{comp['ref']} {comp.get('value', '')} is marked {comp.get('jlc_assembly')} but has no LCSC part.", "Add lcsc_part or mark as manual/not_applicable.")

    single_endpoint = [net for net, eps in nets.items() if len(eps) == 1 and not net.startswith("EXTERNAL")]
    for net in single_endpoint:
        add(results, "WARN", "NET-01", f"Net {net} has only one endpoint: {nets[net][0]}.", "Confirm it is intentional or connect the missing endpoint.")

    rd_refs = refs_with_purpose(manifest, "usb-c rd")
    cc_ok = {"CC1": False, "CC2": False}
    for ref in rd_refs:
        ref_nets = by_ref.get(ref, {})
        for cc_net in cc_ok:
            if ref_connects(ref_nets, cc_net, "GND"):
                cc_ok[cc_net] = True
    for cc_net, ok in cc_ok.items():
        if cc_net in nets and not ok:
            add(results, "FAIL", "USB-01", f"USB-C {cc_net} does not have a detected 5.1k Rd to GND.", "Add 5.1k resistor from CC pin to GND for sink mode.")

    if "USB_D+" in nets or "USB_D-" in nets:
        has_usb_esd = any(c.get("kind") == "protection" and "USB" in c.get("value", "") for c in components)
        if not has_usb_esd:
            add(results, "WARN", "USB-02", "USB data nets exist without a detected USB ESD protection component.", "Add low-capacitance ESD protection near the USB-C connector.")

    for net in ("I2C_SCL", "I2C_SDA"):
        if net in nets:
            has_pullup = False
            for ref in refs_with_purpose(manifest, "i2c pullup"):
                if ref_connects(by_ref.get(ref, {}), net, "+3V3"):
                    has_pullup = True
            if not has_pullup:
                add(results, "FAIL", "I2C-01", f"{net} is present without a pullup to +3V3.", "Add 2.2k-10k pullup according to bus capacitance and speed.")

    for net, rule in (("EN", "BOOT-01"), ("BOOT", "BOOT-02")):
        if net in nets:
            has_pullup = False
            for ref in refs_with_purpose(manifest, "pullup"):
                if ref_connects(by_ref.get(ref, {}), net, "+3V3"):
                    has_pullup = True
            if not has_pullup:
                add(results, "FAIL", rule, f"{net} lacks a pullup to +3V3.", "Add a 10k pullup unless the MCU datasheet says otherwise.")

    for comp in components:
        if "decoupling" in str(comp.get("fields", {}).get("purpose", "")).lower():
            ref_nets = by_ref.get(comp["ref"], {})
            if "GND" not in ref_nets or "+3V3" not in ref_nets:
                add(results, "FAIL", "DEC-01", f"{comp['ref']} decoupling capacitor is not connected between +3V3 and GND.", "Connect local decoupling directly to the IC supply and GND.")

    if "RF_ANT" in nets:
        has_series = any("rf pi series" in str(c.get("fields", {}).get("purpose", "")).lower() for c in components)
        has_shunt = len([c for c in components if "rf pi shunt" in str(c.get("fields", {}).get("purpose", "")).lower()]) >= 2
        if not has_series or not has_shunt:
            add(results, "WARN", "RF-01", "RF_ANT exists but pi matching placeholders are incomplete.", "Add series and two shunt placeholders near the antenna feed.")
        has_rf_endpoint = any(c.get("kind") in {"antenna", "rf_connector", "radio_module"} for c in components)
        if not has_rf_endpoint:
            add(results, "FAIL", "RF-02", "RF_ANT exists but no RF endpoint component is present.", "Add antenna, RF connector, or radio module endpoint.")

    if any(c.get("kind") == "radio_module" for c in components):
        for net in ("SPI_SCK", "SPI_MOSI", "SPI_MISO", "SPI_CS"):
            if net not in nets or len(nets[net]) < 2:
                add(results, "FAIL", "RAD-01", f"Radio module requires {net}, but it is missing or under-connected.", "Connect radio SPI signals to MCU pins.")

    if source_spec.get("input_power", {}).get("battery") in {"lipo_1s", "liion_1s"}:
        has_charger = any(c.get("kind") == "charger" for c in components)
        if not has_charger:
            add(results, "FAIL", "BAT-01", "Battery-powered design has no charger component.", "Add charger or mark the battery as externally charged.")
        if "+BATT" not in nets:
            add(results, "FAIL", "BAT-02", "Battery-powered design has no +BATT net.", "Connect charger, battery connector, and regulator input to +BATT.")

    for rail in source_spec.get("power", {}).get("rails", []):
        if rail.get("source") and rail.get("current_ma"):
            reg = next((c for c in components if c.get("value") == rail["source"] or c.get("part") == rail["source"]), None)
            if reg:
                max_current = reg.get("ratings", {}).get("output_current_ma")
                if max_current and float(rail["current_ma"]) > float(max_current) * 0.8:
                    add(results, "WARN", "PWR-03", f"{rail['name']} requested {rail['current_ma']}mA, close to or above 80% of {reg['part']} rating.", "Use a higher-current regulator or reduce load budget.")

    used_mcu_pins: dict[str, list[str]] = {}
    for row in manifest.get("pinmap", []):
        used_mcu_pins.setdefault(row["mcu_pin"], []).append(row["signal"])
    for pin, signals in used_mcu_pins.items():
        unique_signals = sorted(set(signals))
        if len(unique_signals) > 1:
            add(results, "FAIL", "PIN-01", f"MCU pin {pin} is assigned to multiple signals: {', '.join(unique_signals)}.", "Choose a different GPIO for one signal.")

    mcu = next((c for c in components if c.get("kind") == "mcu_module"), None)
    reserved = set()
    if mcu:
        reserved = set(manifest.get("source_spec", {}).get("reserved_pins", []))
        # The generator copies library constraints into the manifest only via
        # endpoints, so keep common module strapping constraints explicit here.
        if mcu.get("part") == "ESP32-C3-MINI-1":
            reserved.update({"GPIO8", "GPIO9"})
        elif mcu.get("part") == "ESP32-S3-WROOM-1":
            reserved.update({"GPIO0"})
    for pin, signals in used_mcu_pins.items():
        if pin in reserved:
            add(results, "FAIL", "PIN-02", f"MCU pin {pin} is reserved/strapping-sensitive but assigned to {', '.join(sorted(set(signals)))}.", "Move the signal to a non-reserved GPIO.")

    if not any(r["severity"] == "FAIL" for r in results):
        add(results, "PASS", "SUMMARY", "Static ERC passed with no blocking failures.", "")
    return results


def write_markdown(path: Path, project_name: str, results: list[dict[str, str]]) -> None:
    lines = [
        f"# {project_name} Static ERC Report",
        "",
        "| Severity | Rule | Message | Fix |",
        "|---|---|---|---|",
    ]
    for item in results:
        lines.append(f"| {item['severity']} | {item['rule']} | {item['message']} | {item.get('fix', '')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Static ERC for embedded-engineering project manifests.")
    parser.add_argument("--manifest", type=Path, required=True, help="project.netlist.json from gen_kicad_project.py")
    parser.add_argument("--out", type=Path, help="Markdown report path. Defaults to static_erc.md beside manifest.")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    results = run_checks(manifest)
    out_path = args.out or (args.manifest.parent / "static_erc.md")
    write_markdown(out_path, manifest.get("project_name", "hardware_project"), results)
    print(json.dumps({"success": not any(r["severity"] == "FAIL" for r in results), "report": str(out_path), "results": results}, indent=2))
    return 1 if any(r["severity"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
