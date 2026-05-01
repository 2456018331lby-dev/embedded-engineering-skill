"""Read standard KiCad .kicad_mod footprint files and embed them into PCB generation.

This module maps component footprint names from library.json to actual KiCad
library .kicad_mod files, reads them, and transforms them for embedding into
a .kicad_pcb file with correct reference, value, position, and layer.
"""

import re
from pathlib import Path
from typing import Optional

# Common KiCad install paths on Windows
KICAD_SEARCH_PATHS = [
    Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints"),
    Path(r"C:\Program Files\KiCad\9.0\share\kicad\footprints"),
    Path(r"C:\Program Files\KiCad\8.0\share\kicad\footprints"),
]

# Cache for loaded footprints
_footprint_cache: dict[str, str] = {}
_kicad_footprints_root: Optional[Path] = None


def find_kicad_footprints_root() -> Optional[Path]:
    """Find the KiCad footprints directory."""
    global _kicad_footprints_root
    if _kicad_footprints_root is not None:
        return _kicad_footprints_root
    for base in KICAD_SEARCH_PATHS:
        if base.is_dir():
            _kicad_footprints_root = base
            return base
    return None


def resolve_footprint_path(footprint_name: str) -> Optional[Path]:
    """Resolve a KiCad footprint name like 'Resistor_SMD:R_0402_1005Metric'
    to the actual .kicad_mod file path.

    Returns None if not found.
    """
    root = find_kicad_footprints_root()
    if root is None:
        return None

    # Format: "Library:Footprint" -> "Library.pretty/Footprint.kicad_mod"
    if ":" in footprint_name:
        lib, fp = footprint_name.split(":", 1)
    else:
        # Try to find it as-is
        lib, fp = "", footprint_name

    lib_dir = root / f"{lib}.pretty"
    fp_file = lib_dir / f"{fp}.kicad_mod"

    if fp_file.is_file():
        return fp_file

    # Try without the library prefix (search all)
    if not lib:
        for pretty_dir in root.glob("*.pretty"):
            candidate = pretty_dir / f"{fp}.kicad_mod"
            if candidate.is_file():
                return candidate

    return None


def read_footprint_file(footprint_name: str) -> Optional[str]:
    """Read a .kicad_mod file and return its raw content."""
    if footprint_name in _footprint_cache:
        return _footprint_cache[footprint_name]

    fp_path = resolve_footprint_path(footprint_name)
    if fp_path is None:
        return None

    try:
        content = fp_path.read_text(encoding="utf-8")
        _footprint_cache[footprint_name] = content
        return content
    except Exception:
        return None


def transform_footprint_for_pcb(
    fp_content: str,
    ref: str,
    value: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    layer: str = "F.Cu",
    uuid_str: str = "",
) -> str:
    """Transform a raw .kicad_mod footprint for embedding in a .kicad_pcb file.

    Changes:
    - Replace REF** with actual reference
    - Replace value property with actual value
    - Set position (at x y rotation)
    - Set layer
    - Add uuid
    - Remove 3D model references (not needed for PCB-only)
    """
    import uuid as uuid_mod

    if not uuid_str:
        uuid_str = str(uuid_mod.uuid4())

    lines = fp_content.split("\n")
    result = []
    skip_block = False
    skip_depth = 0
    prev_was_attr = False  # Track if previous line was (attr ...)

    for line in lines:
        stripped = line.strip()

        # If we're inside a skipped block, track depth and skip
        if skip_block:
            skip_depth += stripped.count("(") - stripped.count(")")
            if skip_depth <= 0:
                skip_block = False
            continue

        # Skip 3D model blocks
        if stripped.startswith("(model"):
            skip_block = True
            skip_depth = stripped.count("(") - stripped.count(")")
            continue

        # Skip footprint-level metadata that conflicts with PCB header
        if stripped.startswith("(version "):
            continue
        if stripped.startswith("(generator ") or stripped.startswith("(generator_version "):
            continue
        if stripped.startswith("(descr "):
            continue
        if stripped.startswith("(tags "):
            continue
        if stripped.startswith("(duplicate_pad_numbers_are_jumpers"):
            continue
        if stripped.startswith("(embedded_fonts"):
            continue
        if stripped.startswith("(attr "):
            continue
        # Skip standalone layer declaration at footprint level (one tab indent)
        # Layer declarations inside property blocks (two+ tabs) must be kept
        if re.match(r'^\(layer\s+"[^"]+"\)$', stripped) and line.startswith('\t') and not line.startswith('\t\t'):
            continue

        # Skip multi-line property blocks (Datasheet, Description, KiLib_Generator)
        if '(property "Datasheet"' in stripped or '(property "Description"' in stripped or '(property "KiLib_Generator"' in stripped:
            # Always enter skip mode - these blocks have content after the first line
            skip_block = True
            skip_depth = stripped.count("(") - stripped.count(")")
            # If the first line is balanced (like empty value ""), we still need
            # to skip until the block's closing )
            if skip_depth <= 0:
                skip_depth = 1  # Expect one more closing paren
            continue

        # Transform footprint header
        if stripped.startswith("(footprint"):
            m = re.match(r'\(footprint\s+"([^"]*)"', stripped)
            fp_name = m.group(1) if m else "unknown"
            result.append(f'  (footprint "{fp_name}" (layer "{layer}")')
            result.append(f'    (uuid "{uuid_str}")')
            result.append(f'    (at {x:.2f} {y:.2f} {rotation:.2f})')
            result.append(f'    (attr smd)')
            continue

        # Replace Reference property - just change the name, keep structure
        if '(property "Reference"' in stripped:
            # Replace REF** with actual reference
            new_line = re.sub(r'"REF?\*?\*?"', f'"{ref}"', line, count=1)
            result.append(new_line)
            continue

        # Replace Value property - just change the value, keep structure
        if '(property "Value"' in stripped:
            # Replace the value string (second quoted string)
            new_line = re.sub(r'("Value"\s+)"[^"]*"', f'\\1"{value}"', line, count=1)
            result.append(new_line)
            continue

        # Skip single-line pad properties
        if '(property pad_prop' in stripped:
            continue

        # Replace layer references if on back
        if layer == "B.Cu":
            line = line.replace('"F.Cu"', '"B.Cu"')
            line = line.replace('"F.Mask"', '"B.Mask"')
            line = line.replace('"F.Paste"', '"B.Paste"')
            line = line.replace('"F.SilkS"', '"B.SilkS"')
            line = line.replace('"F.Fab"', '"B.Fab"')
            line = line.replace('"F.CrtYd"', '"B.CrtYd"')
            line = line.replace('"F.Adhes"', '"B.Adhes"')

        result.append(line)

    # Safety net: fix unbalanced parentheses
    # Complex footprints (e.g. ESP32-C3-WROOM-02) can have multi-line property
    # blocks where the first line appears balanced but subsequent lines add more
    # opens. Count total opens/closes across the entire result and close any gap.
    joined = "\n".join(result)
    opens = joined.count("(")
    closes = joined.count(")")
    if opens > closes:
        diff = opens - closes
        result.append(")" * diff)

    return "\n".join(result)


def get_footprint_for_component(
    footprint_name: str,
    ref: str,
    value: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    layer: str = "F.Cu",
) -> Optional[str]:
    """High-level function: read a KiCad library footprint and transform it
    for embedding in a PCB file.

    Returns the transformed footprint text, or None if the footprint file
    cannot be found (caller should fall back to generated footprint).
    """
    raw = read_footprint_file(footprint_name)
    if raw is None:
        return None

    return transform_footprint_for_pcb(
        raw, ref=ref, value=value, x=x, y=y, rotation=rotation, layer=layer
    )


# --- Footprint name mapping from library.json footprint fields ---
# library.json uses names like "Resistor_SMD:R_0402_1005Metric"
# which directly map to KiCad library paths.

def is_footprint_available(footprint_name: str) -> bool:
    """Check if a footprint is available in the local KiCad library."""
    return resolve_footprint_path(footprint_name) is not None


def list_available_footprints(component_footprints: list[str]) -> dict[str, bool]:
    """Check availability of multiple footprint names."""
    return {fp: is_footprint_available(fp) for fp in component_footprints}
