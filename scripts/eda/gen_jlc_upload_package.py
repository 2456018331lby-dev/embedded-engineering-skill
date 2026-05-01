"""Generate a JLCPCB-ready ZIP package from a generated hardware project.

Creates a ZIP file containing:
- Gerber files (RS-274X format)
- Drill files (Excellon format)
- BOM in JLCPCB format
- CPL/position file in JLCPCB format

Usage:
    python gen_jlc_upload_package.py --project-dir <path> [--output <zip_path>]
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path


def find_project_name(project_dir: Path) -> str:
    """Find the project name from .kicad_pro or .netlist.json files."""
    for f in project_dir.glob("*.kicad_pro"):
        return f.stem
    for f in project_dir.glob("project.netlist.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("project_name", "project")
    return "project"


def collect_gerber_files(project_dir: Path) -> list[Path]:
    """Collect all Gerber and drill files from the project."""
    files = []
    gerber_dir = project_dir / "gerbers"
    drill_dir = project_dir / "drill"

    if gerber_dir.is_dir():
        files.extend(sorted(gerber_dir.glob("*")))
    if drill_dir.is_dir():
        files.extend(sorted(drill_dir.glob("*")))

    return files


def collect_kicad_project_files(project_dir: Path) -> list[Path]:
    """Collect KiCad project files for 嘉立创EDA import."""
    files = []
    for ext in [".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_prl"]:
        files.extend(sorted(project_dir.glob(f"*{ext}")))
    return files


def normalize_jlc_bom(project_dir: Path) -> Path | None:
    """Find the JLC BOM file."""
    jlc_bom = project_dir / "jlc_bom.csv"
    if jlc_bom.is_file():
        return jlc_bom
    bom = project_dir / "bom.csv"
    if bom.is_file():
        return bom
    return None


def normalize_jlc_cpl(project_dir: Path) -> Path | None:
    """Find the JLC CPL/position file."""
    jlc_cpl = project_dir / "jlc_cpl.csv"
    if jlc_cpl.is_file():
        return jlc_cpl
    pos = project_dir / "kicad_position.csv"
    if pos.is_file():
        return pos
    return None


def generate_jlc_upload_zip(project_dir: Path, output_path: Path) -> dict:
    """Generate a JLCPCB-ready ZIP package.

    Returns a dict with status info.
    """
    project_dir = Path(project_dir)
    project_name = find_project_name(project_dir)

    gerber_files = collect_gerber_files(project_dir)
    kicad_files = collect_kicad_project_files(project_dir)
    jlc_bom = normalize_jlc_bom(project_dir)
    jlc_cpl = normalize_jlc_cpl(project_dir)

    result = {
        "project_name": project_name,
        "output_path": str(output_path),
        "gerber_count": len(gerber_files),
        "kicad_file_count": len(kicad_files),
        "has_bom": jlc_bom is not None,
        "has_cpl": jlc_cpl is not None,
        "files_in_zip": [],
    }

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add Gerber files in a gerber/ subfolder
        for f in gerber_files:
            arcname = f"gerber/{f.name}"
            zf.write(f, arcname)
            result["files_in_zip"].append(arcname)

        # Add KiCad project files (for 嘉立创EDA import)
        for f in kicad_files:
            arcname = f.name
            zf.write(f, arcname)
            result["files_in_zip"].append(arcname)

        # Add BOM
        if jlc_bom:
            zf.write(jlc_bom, "bom.csv")
            result["files_in_zip"].append("bom.csv")

        # Add CPL
        if jlc_cpl:
            zf.write(jlc_cpl, "cpl.csv")
            result["files_in_zip"].append("cpl.csv")

    result["success"] = True
    result["zip_size_kb"] = output_path.stat().st_size / 1024
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate JLCPCB upload package")
    parser.add_argument("--project-dir", required=True, help="Path to generated project")
    parser.add_argument("--output", help="Output ZIP path (default: <project>_jlcpcb.zip)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"Error: {project_dir} is not a directory")
        return

    project_name = find_project_name(project_dir)
    output_path = Path(args.output) if args.output else project_dir / f"{project_name}_jlcpcb.zip"

    result = generate_jlc_upload_zip(project_dir, output_path)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
