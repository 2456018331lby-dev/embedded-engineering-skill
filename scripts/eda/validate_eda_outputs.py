#!/usr/bin/env python3
"""Validate generated EDA outputs and use KiCad CLI when available."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def balanced_parentheses(text: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def add(results: list[dict[str, str]], status: str, check: str, message: str) -> None:
    results.append({"status": status, "check": check, "message": message})


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return p.returncode, p.stdout, p.stderr


def find_kicad_cli() -> str | None:
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def validate_project(project_dir: Path) -> dict[str, Any]:
    results: list[dict[str, str]] = []
    spec_validation = project_dir / "spec_validation.json"
    spec_validation_md = project_dir / "spec_validation.md"
    if spec_validation.exists():
        report = load_json(spec_validation)
        if report.get("success"):
            add(results, "PASS", "spec-validation", "spec_validation.json exists and passed.")
        else:
            add(results, "FAIL", "spec-validation", "spec_validation.json exists but contains validation failures.")
    else:
        add(results, "FAIL", "spec-validation", "spec_validation.json is missing.")
    add(
        results,
        "PASS" if spec_validation_md.exists() else "FAIL",
        "spec-validation-md",
        f"spec_validation.md {'exists' if spec_validation_md.exists() else 'is missing'}.",
    )

    manifest = project_dir / "project.netlist.json"
    if manifest.exists():
        load_json(manifest)
        add(results, "PASS", "manifest", "project.netlist.json parses as JSON.")
    else:
        add(results, "FAIL", "manifest", "project.netlist.json is missing.")

    easyeda_files = list(project_dir.glob("*.easyeda.json"))
    if easyeda_files:
        for path in easyeda_files:
            doc = load_json(path)
            if "shape" in doc and isinstance(doc["shape"], list):
                add(results, "PASS", "easyeda-json", f"{path.name} parses and has a shape array.")
            else:
                add(results, "FAIL", "easyeda-json", f"{path.name} lacks EasyEDA shape array.")
    else:
        add(results, "FAIL", "easyeda-json", "No *.easyeda.json file found.")

    for required in (
        "schematic_preview.html",
        "schematic_preview.svg",
        "bom.csv",
        "pinmap.csv",
        "static_erc.md",
        "production_readiness.md",
        "pcb_constraints.md",
        "symbol_footprint_binding.md",
        "footprint_assignment.csv",
        "jlc_bom.csv",
        "jlc_assembly_report.md",
    ):
        path = project_dir / required
        add(results, "PASS" if path.exists() else "FAIL", required, f"{required} {'exists' if path.exists() else 'is missing'}.")

    cpl_real = project_dir / "jlc_cpl.csv"
    cpl_placeholder = project_dir / "jlc_cpl_placeholder.csv"
    if cpl_real.exists():
        add(results, "PASS", "jlc-cpl", "jlc_cpl.csv exists.")
    elif cpl_placeholder.exists():
        add(results, "PASS", "jlc-cpl", "jlc_cpl_placeholder.csv exists; replace it with real placement before fabrication.")
    else:
        add(results, "FAIL", "jlc-cpl", "No JLC CPL file found.")

    jlc_report = project_dir / "jlc_assembly_report.json"
    if jlc_report.exists():
        report = load_json(jlc_report)
        if report.get("blockers"):
            add(results, "FAIL", "jlc-package", f"JLC package has blockers: {'; '.join(report['blockers'])}")
        else:
            add(results, "PASS", "jlc-package", f"JLC package report parses with verdict {report.get('verdict', 'unknown')}.")
    else:
        add(results, "FAIL", "jlc-package", "jlc_assembly_report.json is missing.")

    sch_files = list(project_dir.glob("*.kicad_sch"))
    if sch_files:
        for path in sch_files:
            text = path.read_text(encoding="utf-8")
            if text.lstrip().startswith("(kicad_sch") and balanced_parentheses(text):
                add(results, "PASS", "kicad-syntax", f"{path.name} has balanced S-expression syntax.")
            else:
                add(results, "FAIL", "kicad-syntax", f"{path.name} does not look like a valid KiCad S-expression.")
    else:
        add(results, "FAIL", "kicad-syntax", "No *.kicad_sch file found.")

    pcb_files = list(project_dir.glob("*.kicad_pcb"))
    if pcb_files:
        for path in pcb_files:
            text = path.read_text(encoding="utf-8")
            if text.lstrip().startswith("(kicad_pcb") and balanced_parentheses(text):
                add(results, "PASS", "pcb-syntax", f"{path.name} has balanced S-expression syntax.")
            else:
                add(results, "FAIL", "pcb-syntax", f"{path.name} does not look like a valid KiCad PCB S-expression.")
    else:
        add(results, "FAIL", "pcb-syntax", "No *.kicad_pcb file found.")

    kicad_cli = find_kicad_cli()
    if not kicad_cli:
        add(results, "SKIP", "kicad-cli", "kicad-cli not found on PATH; official KiCad ERC/export was not run.")
    elif sch_files:
        erc_out = project_dir / "kicad_erc.json"
        code, stdout, stderr = run([kicad_cli, "sch", "erc", "--format", "json", "--output", str(erc_out), str(sch_files[0])], project_dir)
        if code == 0:
            add(results, "PASS", "kicad-erc", f"KiCad ERC completed: {erc_out}")
        else:
            add(results, "FAIL", "kicad-erc", f"KiCad ERC failed with exit {code}: {(stderr or stdout).strip()[:300]}")
        export_dir = project_dir / "kicad_export_svg"
        export_dir.mkdir(exist_ok=True)
        code, stdout, stderr = run([kicad_cli, "sch", "export", "svg", "--output", str(export_dir), str(sch_files[0])], project_dir)
        if code == 0:
            add(results, "PASS", "kicad-svg", f"KiCad SVG export completed: {export_dir}")
        else:
            add(results, "FAIL", "kicad-svg", f"KiCad SVG export failed with exit {code}: {(stderr or stdout).strip()[:300]}")
    if kicad_cli and pcb_files:
        pcb_drc_out = project_dir / "kicad_pcb_drc.json"
        code, stdout, stderr = run([kicad_cli, "pcb", "drc", "--format", "json", "--output", str(pcb_drc_out), str(pcb_files[0])], project_dir)
        if code == 0:
            add(results, "PASS", "pcb-drc", f"KiCad PCB DRC completed: {pcb_drc_out}")
        else:
            add(results, "FAIL", "pcb-drc", f"KiCad PCB DRC failed with exit {code}: {(stderr or stdout).strip()[:300]}")
        pcb_svg_dir = project_dir / "kicad_pcb_svg"
        pcb_svg_dir.mkdir(exist_ok=True)
        pcb_svg_out = pcb_svg_dir / f"{pcb_files[0].stem}.svg"
        code, stdout, stderr = run(
            [kicad_cli, "pcb", "export", "svg", "--layers", "Edge.Cuts,Dwgs.User", "--output", str(pcb_svg_out), "--mode-single", str(pcb_files[0])],
            project_dir,
        )
        if code == 0:
            add(results, "PASS", "pcb-svg", f"KiCad PCB SVG export completed: {pcb_svg_out}")
        else:
            add(results, "FAIL", "pcb-svg", f"KiCad PCB SVG export failed with exit {code}: {(stderr or stdout).strip()[:300]}")
        pos_out = project_dir / "kicad_position.csv"
        code, stdout, stderr = run(
            [kicad_cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "front", "--smd-only", "--exclude-dnp", "--output", str(pos_out), str(pcb_files[0])],
            project_dir,
        )
        if code == 0 and pos_out.exists():
            add(results, "PASS", "pcb-pos", f"KiCad position export completed: {pos_out}")
        else:
            add(results, "FAIL", "pcb-pos", f"KiCad position export failed with exit {code}: {(stderr or stdout).strip()[:300]}")
        gerber_dir = project_dir / "gerbers"
        gerber_dir.mkdir(exist_ok=True)
        code, stdout, stderr = run(
            [kicad_cli, "pcb", "export", "gerbers", "--output", str(gerber_dir), "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts", str(pcb_files[0])],
            project_dir,
        )
        if code == 0:
            add(results, "PASS", "pcb-gerbers", f"KiCad Gerber export completed: {gerber_dir}")
        else:
            add(results, "FAIL", "pcb-gerbers", f"KiCad Gerber export failed with exit {code}: {(stderr or stdout).strip()[:300]}")
        drill_dir = project_dir / "drill"
        drill_dir.mkdir(exist_ok=True)
        drill_report = drill_dir / "drill_report.txt"
        code, stdout, stderr = run(
            [kicad_cli, "pcb", "export", "drill", "--output", str(drill_dir), "--generate-report", "--report-path", str(drill_report), str(pcb_files[0])],
            project_dir,
        )
        if code == 0:
            add(results, "PASS", "pcb-drill", f"KiCad drill export completed: {drill_dir}")
        else:
            add(results, "FAIL", "pcb-drill", f"KiCad drill export failed with exit {code}: {(stderr or stdout).strip()[:300]}")

    return {"success": not any(r["status"] == "FAIL" for r in results), "project_dir": str(project_dir), "results": results}


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        f"# EDA Output Validation",
        "",
        f"Project: `{report['project_dir']}`",
        "",
        "| Status | Check | Message |",
        "|---|---|---|",
    ]
    for row in report["results"]:
        lines.append(f"| {row['status']} | {row['check']} | {row['message']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated EDA outputs; run KiCad CLI checks when available.")
    parser.add_argument("--project-dir", type=Path, required=True, help="Generated project output directory.")
    parser.add_argument("--out", type=Path, help="Validation report JSON path.")
    args = parser.parse_args()

    report = validate_project(args.project_dir)
    out = args.out or (args.project_dir / "eda_validation.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(args.project_dir / "eda_validation.md", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
