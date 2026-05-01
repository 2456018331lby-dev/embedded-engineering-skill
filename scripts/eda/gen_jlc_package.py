#!/usr/bin/env python3
"""Generate JLC/JLCPCB-oriented assembly review files from a manifest."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ref_sort_key(ref: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Za-z]+)(\d+)$", ref)
    if not match:
        return (ref, 0, ref)
    return (match.group(1), int(match.group(2)), ref)


def is_dnp(comp: dict[str, Any]) -> bool:
    text = " ".join([
        str(comp.get("value", "")),
        str(comp.get("fields", {}).get("purpose", "")),
    ]).upper()
    return "DNP" in text


def assembly_class(comp: dict[str, Any]) -> str:
    value = str(comp.get("jlc_assembly", "")).strip().lower()
    if value in {"basic", "extended", "manual", "not_applicable"}:
        return value
    return "manual"


def assembled_by_jlc(comp: dict[str, Any]) -> bool:
    return assembly_class(comp) in {"basic", "extended"} and not is_dnp(comp)


def bom_group_key(comp: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(comp.get("value", "")),
        str(comp.get("footprint", "")),
        str(comp.get("lcsc_part", "")),
        str(comp.get("part", "")),
        assembly_class(comp),
    )


def build_jlc_bom_rows(manifest: dict[str, Any]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for comp in manifest.get("components", []):
        if assembled_by_jlc(comp):
            grouped[bom_group_key(comp)].append(comp)

    rows: list[dict[str, str]] = []
    for key, comps in sorted(grouped.items(), key=lambda item: ref_sort_key(item[1][0]["ref"])):
        value, footprint, lcsc_part, part, jlc_class = key
        refs = sorted([comp["ref"] for comp in comps], key=ref_sort_key)
        rows.append({
            "Comment": value,
            "Designator": ",".join(refs),
            "Footprint": footprint,
            "LCSC Part #": lcsc_part,
            "Quantity": str(len(refs)),
            "Assembly Type": jlc_class,
            "Part": part,
            "Description": comps[0].get("description", ""),
        })
    return rows


def build_placeholder_cpl_rows(manifest: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    comps = [comp for comp in manifest.get("components", []) if assembled_by_jlc(comp)]
    for idx, comp in enumerate(sorted(comps, key=lambda item: ref_sort_key(item["ref"]))):
        col = idx % 8
        row = idx // 8
        rows.append({
            "Designator": comp["ref"],
            "Mid X": f"{10.0 + col * 7.5:.2f}mm",
            "Mid Y": f"{10.0 + row * 7.5:.2f}mm",
            "Layer": "Top",
            "Rotation": "0",
            "Comment": "PLACEHOLDER_COORDINATE_DO_NOT_UPLOAD",
        })
    return rows


def build_real_cpl_rows(
    manifest: dict[str, Any],
    placements: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    comps = [comp for comp in manifest.get("components", []) if assembled_by_jlc(comp) and comp["ref"] in placements]
    for comp in sorted(comps, key=lambda item: ref_sort_key(item["ref"])):
        placement = placements[comp["ref"]]
        rows.append({
            "Designator": comp["ref"],
            "Mid X": f"{float(placement.get('x', 0.0)):.2f}mm",
            "Mid Y": f"{float(placement.get('y', 0.0)):.2f}mm",
            "Layer": str(placement.get("layer", "Top")),
            "Rotation": f"{float(placement.get('rotation', 0.0)):.2f}",
        })
    return rows


def build_report(manifest: dict[str, Any], placement_mode: str) -> dict[str, Any]:
    components = manifest.get("components", [])
    dnp = [comp for comp in components if is_dnp(comp)]
    jlc_parts = [comp for comp in components if assembled_by_jlc(comp)]
    missing_lcsc = [comp for comp in jlc_parts if not comp.get("lcsc_part")]
    manual = [comp for comp in components if assembly_class(comp) == "manual" and not is_dnp(comp)]
    not_applicable = [comp for comp in components if assembly_class(comp) == "not_applicable"]
    classes = defaultdict(int)
    for comp in components:
        if is_dnp(comp):
            classes["dnp"] += 1
        else:
            classes[assembly_class(comp)] += 1

    blockers: list[str] = []
    warnings: list[str] = []
    if missing_lcsc:
        blockers.append("Some JLC basic/extended assembly parts lack LCSC part numbers.")
    if not jlc_parts:
        blockers.append("No JLC-assembled parts were detected.")
    if manual:
        warnings.append("Manual assembly parts are present and must be handled outside JLC SMT assembly or manually sourced.")
    if dnp:
        warnings.append("DNP parts are present and excluded from JLC assembly outputs.")
    if placement_mode == "real":
        warnings.append("CPL coordinates come from the auto-placed KiCad PCB skeleton and still require engineering review.")
    else:
        warnings.append("CPL coordinates are placeholders until a real PCB placement exists.")

    verdict = "JLC_REVIEW_READY"
    if blockers:
        verdict = "BLOCKED"
    elif warnings:
        verdict = "NEEDS_ENGINEERING_REVIEW"

    return {
        "project_name": manifest.get("project_name", "hardware_project"),
        "verdict": verdict,
        "counts": {
            "components_total": len(components),
            "jlc_assembled": len(jlc_parts),
            "manual": len(manual),
            "not_applicable": len(not_applicable),
            "dnp": len(dnp),
            "missing_lcsc": len(missing_lcsc),
            "classes": dict(sorted(classes.items())),
        },
        "placement_mode": placement_mode,
        "blockers": blockers,
        "warnings": warnings,
        "missing_lcsc": [{"ref": c["ref"], "value": c.get("value", ""), "part": c.get("part", "")} for c in missing_lcsc],
        "manual_parts": [{"ref": c["ref"], "value": c.get("value", ""), "part": c.get("part", "")} for c in manual],
        "dnp_parts": [{"ref": c["ref"], "value": c.get("value", ""), "part": c.get("part", "")} for c in dnp],
    }


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    placement_text = (
        "The BOM is JLC-oriented. The CPL uses auto-generated placement coordinates from the KiCad PCB skeleton and still requires engineering review before fabrication."
        if report.get("placement_mode") == "real"
        else "The BOM is JLC-oriented. The CPL is a placeholder planning file and must be replaced by real PCB placement coordinates before fabrication."
    )
    lines = [
        f"# {report['project_name']} JLC Assembly Report",
        "",
        f"Verdict: **{report['verdict']}**",
        "",
        placement_text,
        "",
        "## Counts",
        "",
    ]
    for key, value in report["counts"].items():
        if key == "classes":
            continue
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Assembly Classes", ""])
    for key, value in report["counts"]["classes"].items():
        lines.append(f"- {key}: {value}")
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in report["blockers"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in report["warnings"])
    if report["manual_parts"]:
        lines.extend(["", "## Manual Parts", ""])
        lines.extend(f"- {row['ref']} {row['value']} ({row['part']})" for row in report["manual_parts"])
    if report["dnp_parts"]:
        lines.extend(["", "## DNP Parts", ""])
        lines.extend(f"- {row['ref']} {row['value']} ({row['part']})" for row in report["dnp_parts"])
    if report["missing_lcsc"]:
        lines.extend(["", "## Missing LCSC", ""])
        lines.extend(f"- {row['ref']} {row['value']} ({row['part']})" for row in report["missing_lcsc"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_jlc_package(
    manifest: dict[str, Any],
    outdir: Path,
    placements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    bom_rows = build_jlc_bom_rows(manifest)
    has_real_placements = bool(placements)
    cpl_rows = build_real_cpl_rows(manifest, placements or {}) if has_real_placements else build_placeholder_cpl_rows(manifest)
    report = build_report(manifest, "real" if has_real_placements else "placeholder")

    bom_path = outdir / "jlc_bom.csv"
    cpl_path = outdir / ("jlc_cpl.csv" if has_real_placements else "jlc_cpl_placeholder.csv")
    report_json_path = outdir / "jlc_assembly_report.json"
    report_md_path = outdir / "jlc_assembly_report.md"

    write_csv(
        bom_path,
        bom_rows,
        ["Comment", "Designator", "Footprint", "LCSC Part #", "Quantity", "Assembly Type", "Part", "Description"],
    )
    write_csv(
        cpl_path,
        cpl_rows,
        ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"] if has_real_placements else ["Designator", "Mid X", "Mid Y", "Layer", "Rotation", "Comment"],
    )
    write_json(report_json_path, report)
    write_markdown(report_md_path, report)

    return {
        "success": not report["blockers"],
        "outputs": {
            "jlc_bom": str(bom_path),
            "jlc_cpl": str(cpl_path),
            "jlc_assembly_report_json": str(report_json_path),
            "jlc_assembly_report": str(report_md_path),
        },
        "report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate JLC/JLCPCB assembly review package from project.netlist.json.")
    parser.add_argument("--manifest", type=Path, required=True, help="project.netlist.json from gen_kicad_project.py")
    parser.add_argument("--out", type=Path, help="Output directory. Defaults to manifest directory.")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    result = generate_jlc_package(manifest, args.out or args.manifest.parent)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
