# Repository Guidelines

## Project Structure & Module Organization
This repository is a Claude Code skill for embedded hardware and EDA automation. `SKILL.md` is the main entrypoint. Reusable Python tooling lives under `scripts/` by domain: `rf/`, `digital/`, `protocol/`, `eda/`, and `system/`. Built-in design specs live in `circuits/templates/`, shared part data in `components/library.json`, reference docs in `references/`, and role prompts in `subagents/`. MCP helpers are in `mcp/`, and workflow examples live in `workflows/`.

## Build, Test, and Development Commands
Run commands from the repository root. On this machine, prefer Python 3.12 with UTF-8 output:
`C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 ...`

- `python -m py_compile scripts\eda\gen_kicad_project.py scripts\eda\gen_template_gallery.py scripts\eda\gen_jlc_package.py scripts\eda\validate_eda_outputs.py scripts\eda\gen_easyeda_std.py scripts\eda\render_design_preview.py scripts\eda\erc_check.py` checks core scripts for syntax errors.
- `python -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery` regenerates all bundled example outputs.
- `python -X utf8 scripts\eda\gen_jlc_package.py --manifest <path>\project.netlist.json` validates JLC package generation for one project.
- `git diff --check` catches whitespace issues before review.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, type hints where useful, small focused helpers, and concise module docstrings. Keep filenames snake_case, constants UPPER_SNAKE_CASE, and JSON templates lowercase with hyphenated names such as `esp32-c3-sensor-node.json`. Prefer ASCII in code unless engineering symbols or Chinese text are required, then run with `-X utf8`.

## Testing Guidelines
There is no formal pytest suite yet; verification is script-driven. For changes in `scripts/eda/`, run `py_compile` and regenerate the gallery. For template or manifest changes, rerun the affected generator and confirm `eda_validation.md`, `static_erc.md`, and preview outputs are produced. Document any manual KiCad CLI checks if `validate_eda_outputs.py` is involved.

## Commit & Pull Request Guidelines
Recent history uses short, imperative subjects such as `Publish the embedded engineering skill as a public-ready repository` and `Normalize line endings for cross-platform contributors`. Keep commit titles specific and under one line; use the body to explain why when the change is non-trivial. PRs should include scope, touched paths, verification commands run, and screenshots or output paths when UI, HTML/SVG previews, or generated EDA artifacts change.

## Security & Configuration Tips
Do not commit generated output directories, local machine paths beyond examples, or secrets in MCP configs. Treat `components/library.json` and template manifests as source-of-truth inputs; update them carefully and re-run downstream generators after edits.
