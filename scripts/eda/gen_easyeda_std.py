#!/usr/bin/env python3
"""Export project.netlist.json as an EasyEDA/JLCEDA Standard JSON schematic.

The output remains a generated review schematic, but it now uses grouped
functional sections, richer symbol metadata, package/footprint visibility,
pin-level net stubs, and summary panels so the imported result reads more like
an engineering review schematic instead of a bare block diagram.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from render_design_preview import COLORS, GROUP_ORDER


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def easy_text(value: str) -> str:
    return str(value).replace("~", " ").replace("\n", " ")


def truncate(text: str, limit: int) -> str:
    text = easy_text(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def endpoints_by_component(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    pins: dict[str, dict[str, str]] = {}
    for net, endpoints in manifest.get("nets", {}).items():
        for endpoint in endpoints:
            if "." not in endpoint or endpoint.startswith("EXTERNAL."):
                continue
            ref, pin = endpoint.split(".", 1)
            pins.setdefault(ref, {})
            pins[ref].setdefault(pin, net)
    return pins


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


def ref_sort_key(ref: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Za-z]+)(\d+)$", ref)
    if not match:
        return (ref, 0, ref)
    return (match.group(1), int(match.group(2)), ref)


def split_symbol_pins(pins: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    left: list[tuple[str, str]] = []
    right: list[tuple[str, str]] = []
    for pin, net in pins:
        token = f"{pin} {net}".upper()
        if any(word in token for word in ("GND", "VSS", "SHIELD", "VBUS", "VIN", "VCC", "VDD", "3V3", "BATT")):
            left.append((pin, net))
        else:
            right.append((pin, net))
    if not right:
        midpoint = (len(left) + 1) // 2
        return left[:midpoint], left[midpoint:]
    return left, right


def binding_status(comp: dict[str, Any]) -> tuple[str, str]:
    symbol = str(comp.get("symbol", "")).strip()
    footprint = str(comp.get("footprint", "")).strip()
    jlc = str(comp.get("jlc_assembly", "")).strip().lower()
    lcsc = str(comp.get("lcsc_part", "")).strip()
    if not symbol or not footprint:
        return "missing_binding", "#dc2626"
    if jlc in {"manual", "not_applicable"}:
        return "manual_review", "#d97706"
    if jlc in {"basic", "extended"} and not lcsc:
        return "missing_lcsc", "#dc2626"
    return "review_ready", "#15803d"


def component_box_geometry(comp: dict[str, Any], pin_count: int) -> tuple[float, float]:
    longest = max(
        len(str(comp.get("part", ""))),
        len(str(comp.get("footprint", ""))),
        len(str(comp.get("package", ""))),
        len(str(comp.get("value", ""))),
        18,
    )
    width = 280.0
    if longest > 38:
        width = 320.0
    if longest > 52:
        width = 350.0
    metadata_h = 88.0
    pin_rows = max(1, (pin_count + 1) // 2)
    height = max(128.0, metadata_h + pin_rows * 18.0 + 20.0)
    return width, height


def net_color(net: str) -> str:
    upper = net.upper()
    if upper.startswith("RF"):
        return "#cc0000"
    if upper.startswith("+") or upper in {"VBAT", "VBUS", "3V3", "VCC", "VDD"}:
        return "#0066cc"
    if upper == "GND":
        return "#334155"
    if upper.startswith(("UART", "SPI", "I2C", "USB", "LORA", "BOOT", "EN")):
        return "#7c3aed"
    return "#008800"


def shape_rect(x: float, y: float, w: float, h: float, stroke: str, fill: str) -> str:
    return f"RECT~{x:.0f}~{y:.0f}~{w:.0f}~{h:.0f}~{stroke}~1~0~{fill}~gge{uuid.uuid4().hex[:8]}"


def shape_text(x: float, y: float, text: str, size: int = 12, color: str = "#000000") -> str:
    return f"TEXT~L~{x:.0f}~{y:.0f}~{size}~0~0~0~{color}~{easy_text(text)}~gge{uuid.uuid4().hex[:8]}"


def shape_line(x1: float, y1: float, x2: float, y2: float, color: str = "#334155") -> str:
    return f"WIRE~{x1:.0f} {y1:.0f} {x2:.0f} {y2:.0f}~{color}~1~0~none~gge{uuid.uuid4().hex[:8]}"


def group_name_for_kind(kind: str) -> str:
    for name, kinds in GROUP_ORDER:
        if kind in kinds:
            return name
    return "Other"


def group_components(manifest: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in GROUP_ORDER}
    grouped["Other"] = []
    for comp in manifest.get("components", []):
        grouped[group_name_for_kind(str(comp.get("kind", "")))].append(comp)
    ordered: list[tuple[str, list[dict[str, Any]]]] = []
    for name in list(grouped.keys()):
        comps = sorted(grouped[name], key=lambda item: ref_sort_key(str(item.get("ref", ""))))
        if comps:
            ordered.append((name, comps))
    return ordered


def summarize_nets(manifest: dict[str, Any]) -> dict[str, list[str]]:
    nets = list(manifest.get("nets", {}).keys())
    power = [net for net in nets if net.startswith("+") or net in {"GND", "VBAT", "VDD", "VCC", "VBUS"}]
    rf = [net for net in nets if net.startswith("RF") or net.startswith("LORA")]
    signals = [
        net for net in nets
        if net.startswith(("UART", "SPI", "I2C", "USB", "BOOT", "EN")) and net not in power and net not in rf
    ]
    return {
        "power": power[:8],
        "rf": rf[:8],
        "signals": signals[:10],
    }


def assembly_summary(manifest: dict[str, Any]) -> list[str]:
    counts: dict[str, int] = {}
    for comp in manifest.get("components", []):
        key = str(comp.get("jlc_assembly", "manual") or "manual")
        counts[key] = counts.get(key, 0) + 1
    return [f"{key}:{counts[key]}" for key in sorted(counts)]


def build_easyeda_document(manifest: dict[str, Any]) -> dict[str, Any]:
    comp_by_ref = {c["ref"]: c for c in manifest.get("components", [])}
    pins_by_ref = endpoints_by_component(manifest)
    grouped = group_components(manifest)
    shapes: list[str] = []

    shapes.append(shape_text(40, 34, manifest.get("project_name", "hardware_project"), 20, "#1f2937"))
    shapes.append(shape_text(40, 58, "Generated pin-level review schematic for EasyEDA/JLCEDA import", 10, "#64748b"))
    shapes.append(shape_text(40, 76, "Includes symbol/package/footprint/JLC metadata. project.netlist.json remains the ERC source of truth.", 9, "#64748b"))

    sections: list[dict[str, Any]] = []
    placements: list[dict[str, Any]] = []
    cursor_x = 40.0
    overall_bottom = 110.0

    for group_name, comps in grouped:
        cursor_y = 122.0
        section_width = 0.0
        section_items: list[dict[str, Any]] = []
        for comp in comps:
            ref = str(comp.get("ref", ""))
            pins = sorted(pins_by_ref.get(ref, {}).items(), key=lambda item: pin_sort_key(item[0]))
            if not pins:
                pins = [("NC", "NC")]
            left_pins, right_pins = split_symbol_pins(pins)
            box_w, box_h = component_box_geometry(comp, len(pins))
            entry = {
                "ref": ref,
                "comp": comp,
                "x": cursor_x + 82.0,
                "y": cursor_y,
                "w": box_w,
                "h": box_h,
                "pins": pins,
                "left_pins": left_pins,
                "right_pins": right_pins,
            }
            section_items.append(entry)
            placements.append(entry)
            section_width = max(section_width, box_w + 188.0)
            cursor_y += box_h + 28.0
        section_h = max(110.0, cursor_y - 96.0)
        sections.append({
            "name": group_name,
            "x": cursor_x,
            "y": 92.0,
            "w": max(290.0, section_width),
            "h": section_h,
            "count": len(comps),
        })
        cursor_x += max(290.0, section_width) + 28.0
        overall_bottom = max(overall_bottom, 92.0 + section_h)

    for section in sections:
        shapes.append(shape_rect(section["x"], section["y"], section["w"], section["h"], "#cbd5e1", "#f8fafc"))
        shapes.append(shape_text(section["x"] + 10, section["y"] + 18, f"{section['name']} ({section['count']})", 11, "#0f172a"))
        shapes.append(shape_line(section["x"] + 8, section["y"] + 26, section["x"] + section["w"] - 8, section["y"] + 26, "#cbd5e1"))

    for entry in placements:
        comp = comp_by_ref[entry["ref"]]
        x = entry["x"]
        y = entry["y"]
        w = entry["w"]
        h = entry["h"]
        fill = COLORS.get(comp.get("kind", ""), "#ffffff")
        status, status_color = binding_status(comp)
        shapes.append(shape_rect(x, y, w, h, "#334155", fill))
        shapes.append(shape_text(x + 8, y + 18, f"{entry['ref']}  {truncate(str(comp.get('value', '')), 28)}", 11, "#0f172a"))
        shapes.append(shape_text(x + 8, y + 34, truncate(str(comp.get("part", "")), 42), 8, "#475569"))
        shapes.append(shape_text(x + 8, y + 48, f"FP: {truncate(str(comp.get('footprint', '')), 35)}", 8, "#334155"))
        shapes.append(shape_text(x + 8, y + 62, f"PKG: {truncate(str(comp.get('package', '')), 20)}  LCSC: {truncate(str(comp.get('lcsc_part', 'N/A')), 16)}", 8, "#334155"))
        shapes.append(shape_text(x + 8, y + 76, f"JLC: {truncate(str(comp.get('jlc_assembly', 'manual')), 14)}  Bind: {status}", 8, status_color))
        shapes.append(shape_line(x + 6, y + 84, x + w - 6, y + 84, "#94a3b8"))

        top_y = y + 98.0
        pitch = 18.0
        for idx, (pin, net) in enumerate(entry["left_pins"]):
            pin_y = top_y + idx * pitch
            x1 = x - 24.0
            x2 = x
            color = net_color(net)
            shapes.append(shape_line(x1, pin_y, x2, pin_y, color))
            shapes.append(shape_text(x - 74.0, pin_y + 4.0, truncate(net, 18), 8, color))
            shapes.append(shape_text(x - 16.0, pin_y + 4.0, truncate(pin, 10), 8, "#334155"))
        for idx, (pin, net) in enumerate(entry["right_pins"]):
            pin_y = top_y + idx * pitch
            x1 = x + w
            x2 = x1 + 24.0
            color = net_color(net)
            shapes.append(shape_line(x1, pin_y, x2, pin_y, color))
            shapes.append(shape_text(x2 + 6.0, pin_y + 4.0, truncate(net, 18), 8, color))
            shapes.append(shape_text(x1 + 2.0, pin_y + 4.0, truncate(pin, 10), 8, "#334155"))

    net_summary = summarize_nets(manifest)
    summary_y = overall_bottom + 28.0
    card_x = 40.0
    card_w = 320.0
    card_gap = 24.0
    summary_cards = [
        ("Power Nets", net_summary["power"] or ["None"], "#eff6ff"),
        ("RF / Radio Nets", net_summary["rf"] or ["None"], "#fef2f2"),
        ("Interface / Assembly", (net_summary["signals"][:5] + assembly_summary(manifest)) or ["None"], "#f8fafc"),
    ]
    for title, lines_data, fill in summary_cards:
        card_h = 56.0 + 16.0 * len(lines_data)
        shapes.append(shape_rect(card_x, summary_y, card_w, card_h, "#cbd5e1", fill))
        shapes.append(shape_text(card_x + 10, summary_y + 18, title, 10, "#0f172a"))
        for idx, line in enumerate(lines_data):
            shapes.append(shape_text(card_x + 10, summary_y + 38 + idx * 16.0, truncate(line, 42), 8, "#475569"))
        card_x += card_w + card_gap
        overall_bottom = max(overall_bottom, summary_y + card_h)

    width = max(1000.0, card_x - card_gap + 40.0, *(section["x"] + section["w"] + 40.0 for section in sections))
    height = max(720.0, overall_bottom + 40.0)
    return {
        "docType": "1",
        "editorVersion": "6.5.0",
        "title": manifest.get("project_name", "hardware_project"),
        "description": "Generated by embedded-engineering skill. project.netlist.json is authoritative for ERC.",
        "head": {
            "docType": "1",
            "editorVersion": "6.5.0",
            "newgId": True,
            "c_para": {},
            "uuid": uuid.uuid4().hex,
            "time": int(time.time()),
        },
        "canvas": f"CA~1000~1000~#FFFFFF~yes~#CCCCCC~10~1000~{width:.0f}~{height:.0f}~line~5~pixel~5~0~0",
        "shape": shapes,
        "BOM": [
            {
                "ref": c.get("ref", ""),
                "value": c.get("value", ""),
                "part": c.get("part", ""),
                "footprint": c.get("footprint", ""),
                "package": c.get("package", ""),
                "lcsc_part": c.get("lcsc_part", ""),
                "jlc_assembly": c.get("jlc_assembly", ""),
                "symbol": c.get("symbol", ""),
            }
            for c in manifest.get("components", [])
        ],
        "netlist": manifest.get("nets", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export manifest to EasyEDA/JLCEDA Standard JSON.")
    parser.add_argument("--manifest", type=Path, required=True, help="project.netlist.json")
    parser.add_argument("--out", type=Path, help="Output .json path. Defaults beside manifest.")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    out = args.out or (args.manifest.parent / f"{re.sub(r'[^A-Za-z0-9_+-]+', '_', manifest.get('project_name', 'hardware_project'))}.easyeda.json")
    document = build_easyeda_document(manifest)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "easyeda_standard": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
