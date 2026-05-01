#!/usr/bin/env python3
"""Generate all bundled EDA example projects and a clickable gallery index."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from gen_kicad_project import DEFAULT_LIBRARY, ROOT, generate_project


DEFAULT_TEMPLATES = ROOT / "circuits" / "templates"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def validation_counts(report_path: Path) -> tuple[int, int, int]:
    if not report_path.exists():
        return 0, 0, 1
    report = load_json(report_path)
    rows = report.get("results", [])
    passes = len([row for row in rows if row.get("status") == "PASS"])
    skips = len([row for row in rows if row.get("status") == "SKIP"])
    fails = len([row for row in rows if row.get("status") == "FAIL"])
    return passes, skips, fails


def write_index(outdir: Path, projects: list[dict[str, Any]]) -> Path:
    rows = []
    for project in projects:
        project_dir = Path(project["project_dir"])
        passes, skips, fails = validation_counts(project_dir / "eda_validation.json")
        svg_files = list((project_dir / "kicad_export_svg").glob("*.svg"))
        kicad_svg = svg_files[0] if svg_files else None
        kicad_svg_link = f"<a href='{rel(kicad_svg, outdir)}'>KiCad SVG</a>" if kicad_svg else "not exported"
        readiness = project_dir / "production_readiness.md"
        jlc_report = project_dir / "jlc_assembly_report.md"
        rows.append(
            "<tr>"
            f"<td>{html.escape(project['name'])}</td>"
            f"<td>{passes}</td>"
            f"<td>{skips}</td>"
            f"<td>{fails}</td>"
            f"<td><a href='{rel(project_dir / 'schematic_preview.html', outdir)}'>HTML preview</a></td>"
            f"<td><a href='{rel(project_dir / 'schematic_preview.svg', outdir)}'>SVG preview</a></td>"
            f"<td>{kicad_svg_link}</td>"
            f"<td><a href='{rel(project_dir / 'eda_validation.md', outdir)}'>validation</a></td>"
            f"<td><a href='{rel(readiness, outdir)}'>readiness</a></td>"
            f"<td><a href='{rel(jlc_report, outdir)}'>JLC report</a></td>"
            "</tr>"
        )
    body = "\n".join(rows)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Embedded Engineering EDA Gallery</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #cfd8dc; padding: 8px 10px; text-align: left; }}
    th {{ background: #eef3f6; }}
    a {{ color: #0b5cad; }}
  </style>
</head>
<body>
  <h1>Embedded Engineering EDA Gallery</h1>
  <p>Generated examples for Claude Code skill verification. Open the preview links directly in a browser.</p>
  <table>
    <thead>
      <tr>
        <th>Project</th><th>PASS</th><th>SKIP</th><th>FAIL</th>
        <th>HTML</th><th>SVG</th><th>KiCad SVG</th><th>Validation</th><th>Readiness</th><th>JLC Report</th>
      </tr>
    </thead>
    <tbody>
{body}
    </tbody>
  </table>
</body>
</html>
"""
    index = outdir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


def write_summary(outdir: Path, projects: list[dict[str, Any]], index: Path) -> Path:
    lines = [
        "# Embedded Engineering EDA Gallery",
        "",
        f"Index: `{index}`",
        "",
        "| Project | PASS | SKIP | FAIL | HTML Preview | Validation | Readiness | JLC Report |",
        "|---|---:|---:|---:|---|---|---|---|",
    ]
    for project in projects:
        project_dir = Path(project["project_dir"])
        passes, skips, fails = validation_counts(project_dir / "eda_validation.json")
        lines.append(
            f"| {project['name']} | {passes} | {skips} | {fails} | "
            f"`{project_dir / 'schematic_preview.html'}` | "
            f"`{project_dir / 'eda_validation.md'}` | "
            f"`{project_dir / 'production_readiness.md'}` | "
            f"`{project_dir / 'jlc_assembly_report.md'}` |"
        )
    path = outdir / "gallery_summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate every bundled EDA template and a gallery index.")
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES, help="Directory containing project spec JSON templates.")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY, help="Component library JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output gallery directory.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for spec_path in sorted(p for p in args.templates.glob("*.json") if "spec_validation" not in p.name):
        name = spec_path.stem
        project_dir = args.out / name
        result = generate_project(spec_path, args.library, project_dir, name)
        projects.append({"name": name, "project_dir": str(project_dir), "success": result["success"]})
    index = write_index(args.out, projects)
    summary = write_summary(args.out, projects, index)
    print(json.dumps({"success": True, "index": str(index), "summary": str(summary), "projects": projects}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
