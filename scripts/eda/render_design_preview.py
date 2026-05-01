#!/usr/bin/env python3
"""Render project.netlist.json as an HTML/SVG schematic preview."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


GROUP_ORDER = [
    ("Input", {"connector", "switch"}),
    ("Power", {"ldo"}),
    ("Controller", {"mcu_module"}),
    ("Sensors", {"sensor"}),
    ("Radio", {"rf_connector", "antenna", "radio_module"}),
    ("Passives", {"passive", "indicator"}),
]


COLORS = {
    "mcu_module": "#dbeafe",
    "sensor": "#dcfce7",
    "ldo": "#fef3c7",
    "connector": "#f3e8ff",
    "rf_connector": "#ffe4e6",
    "antenna": "#ffe4e6",
    "radio_module": "#ffe4e6",
    "passive": "#f8fafc",
    "indicator": "#e0f2fe",
    "switch": "#f1f5f9",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def component_nets(manifest: dict[str, Any]) -> dict[str, set[str]]:
    by_ref: dict[str, set[str]] = {}
    for net, endpoints in manifest.get("nets", {}).items():
        for endpoint in endpoints:
            if "." not in endpoint or endpoint.startswith("EXTERNAL."):
                continue
            ref, _ = endpoint.split(".", 1)
            by_ref.setdefault(ref, set()).add(net)
    return by_ref


def layout_components(manifest: dict[str, Any]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in GROUP_ORDER}
    grouped["Other"] = []
    for comp in manifest.get("components", []):
        placed = False
        for name, kinds in GROUP_ORDER:
            if comp.get("kind") in kinds:
                grouped[name].append(comp)
                placed = True
                break
        if not placed:
            grouped["Other"].append(comp)

    positions: dict[str, dict[str, float]] = {}
    x = 40.0
    for name, comps in grouped.items():
        if not comps:
            continue
        y = 90.0
        for comp in comps:
            positions[comp["ref"]] = {"x": x, "y": y, "w": 190.0, "h": 62.0, "group": name}
            y += 82.0
        x += 230.0
    return positions


def edge_points(a: dict[str, float], b: dict[str, float]) -> tuple[float, float, float, float]:
    ax = a["x"] + (a["w"] if a["x"] < b["x"] else 0)
    ay = a["y"] + a["h"] / 2
    bx = b["x"] + (0 if a["x"] < b["x"] else b["w"])
    by = b["y"] + b["h"] / 2
    return ax, ay, bx, by


def svg_for_manifest(manifest: dict[str, Any]) -> str:
    positions = layout_components(manifest)
    comp_by_ref = {c["ref"]: c for c in manifest.get("components", [])}
    width = max((p["x"] + p["w"] + 40 for p in positions.values()), default=900)
    height = max((p["y"] + p["h"] + 80 for p in positions.values()), default=600)
    nets_by_ref = component_nets(manifest)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">',
        "<defs>",
        '<marker id="dot" markerWidth="6" markerHeight="6" refX="3" refY="3"><circle cx="3" cy="3" r="2.5" fill="#475569"/></marker>',
        "</defs>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="40" y="38" font-size="22" font-family="Segoe UI, Arial" font-weight="700" fill="#0f172a">{html.escape(manifest.get("project_name", "hardware_project"))}</text>',
        '<text x="40" y="62" font-size="12" font-family="Segoe UI, Arial" fill="#64748b">Generated from project.netlist.json. Wires show logical net connectivity for review.</text>',
    ]

    drawn_pairs: set[tuple[str, str, str]] = set()
    for net, endpoints in manifest.get("nets", {}).items():
        refs = []
        for endpoint in endpoints:
            if "." not in endpoint or endpoint.startswith("EXTERNAL."):
                continue
            ref, _ = endpoint.split(".", 1)
            if ref in positions and ref not in refs:
                refs.append(ref)
        if len(refs) < 2:
            continue
        hub = refs[0]
        for other in refs[1:]:
            pair = tuple(sorted([hub, other]) + [net])
            if pair in drawn_pairs:
                continue
            drawn_pairs.add(pair)
            ax, ay, bx, by = edge_points(positions[hub], positions[other])
            mx = (ax + bx) / 2
            color = "#2563eb" if net.startswith("+") else "#64748b"
            if net in {"GND", "RF_ANT", "RF_FEED"}:
                color = "#dc2626" if net.startswith("RF") else "#334155"
            lines.append(f'<path d="M {ax:.1f} {ay:.1f} C {mx:.1f} {ay:.1f}, {mx:.1f} {by:.1f}, {bx:.1f} {by:.1f}" fill="none" stroke="{color}" stroke-width="1.6" marker-start="url(#dot)" marker-end="url(#dot)" opacity="0.78"/>')
            lines.append(f'<text x="{mx:.1f}" y="{((ay + by) / 2) - 5:.1f}" font-size="10" font-family="Segoe UI, Arial" fill="{color}" text-anchor="middle">{html.escape(net)}</text>')

    for ref, pos in positions.items():
        comp = comp_by_ref[ref]
        fill = COLORS.get(comp.get("kind", ""), "#f8fafc")
        lines.append(f'<rect x="{pos["x"]:.1f}" y="{pos["y"]:.1f}" width="{pos["w"]:.1f}" height="{pos["h"]:.1f}" rx="6" fill="{fill}" stroke="#334155" stroke-width="1.2"/>')
        lines.append(f'<text x="{pos["x"] + 10:.1f}" y="{pos["y"] + 20:.1f}" font-size="13" font-family="Segoe UI, Arial" font-weight="700" fill="#0f172a">{html.escape(ref)} {html.escape(comp.get("value", ""))}</text>')
        lines.append(f'<text x="{pos["x"] + 10:.1f}" y="{pos["y"] + 38:.1f}" font-size="10" font-family="Segoe UI, Arial" fill="#475569">{html.escape(comp.get("kind", ""))} | {html.escape(comp.get("footprint", ""))[:35]}</text>')
        nets = ", ".join(sorted(nets_by_ref.get(ref, set()))[:5])
        lines.append(f'<text x="{pos["x"] + 10:.1f}" y="{pos["y"] + 54:.1f}" font-size="9" font-family="Consolas, monospace" fill="#64748b">{html.escape(nets)}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def write_html(path: Path, manifest: dict[str, Any], svg: str) -> None:
    rows = []
    for comp in manifest.get("components", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(comp.get('ref', ''))}</td>"
            f"<td>{html.escape(comp.get('value', ''))}</td>"
            f"<td>{html.escape(comp.get('kind', ''))}</td>"
            f"<td>{html.escape(comp.get('footprint', ''))}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{html.escape(manifest.get("project_name", "hardware_project"))} schematic preview</title>
<style>
body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; color: #0f172a; background: #f8fafc; }}
main {{ padding: 24px; }}
.sheet {{ background: #fff; border: 1px solid #cbd5e1; overflow: auto; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin-top: 18px; }}
th, td {{ border: 1px solid #cbd5e1; padding: 7px 9px; font-size: 12px; text-align: left; }}
th {{ background: #e2e8f0; }}
</style>
<main>
  <div class="sheet">{svg}</div>
  <table>
    <thead><tr><th>Ref</th><th>Value</th><th>Kind</th><th>Footprint</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</main>
</html>
"""
    path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render project.netlist.json to SVG and HTML preview files.")
    parser.add_argument("--manifest", type=Path, required=True, help="project.netlist.json")
    parser.add_argument("--out-dir", type=Path, help="Output directory. Defaults beside manifest.")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    out_dir = args.out_dir or args.manifest.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = svg_for_manifest(manifest)
    svg_path = out_dir / "schematic_preview.svg"
    html_path = out_dir / "schematic_preview.html"
    svg_path.write_text(svg + "\n", encoding="utf-8")
    write_html(html_path, manifest, svg)
    print(json.dumps({"success": True, "svg": str(svg_path), "html": str(html_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
