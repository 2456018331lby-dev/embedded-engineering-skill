"""Read standard KiCad .kicad_sym symbol library files and extract symbol definitions.

Maps component names from library.json to actual KiCad library symbols,
reads the symbol definition, and transforms it for embedding in .kicad_sch files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# KiCad symbol library paths
KICAD_SYMBOL_SEARCH_PATHS = [
    Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols"),
    Path(r"C:\Program Files\KiCad\9.0\share\kicad\symbols"),
    Path(r"C:\Program Files\KiCad\8.0\share\kicad\symbols"),
]

_symbol_cache: dict[str, str] = {}
_kicad_symbols_root: Optional[Path] = None
_symbol_defs_cache: dict[str, dict[str, str]] = {}  # lib_id -> {name, body}


def find_kicad_symbols_root() -> Optional[Path]:
    """Find the KiCad symbols directory."""
    global _kicad_symbols_root
    if _kicad_symbols_root is not None:
        return _kicad_symbols_root
    for base in KICAD_SYMBOL_SEARCH_PATHS:
        if base.is_dir():
            _kicad_symbols_root = base
            return base
    return None


def _parse_symbols_from_file(filepath: Path) -> dict[str, str]:
    """Parse all symbol definitions from a .kicad_sym file.

    Returns {symbol_name: full_symbol_text} for each (symbol ...) block
    at the top level (not sub-symbols like _0_1, _1_1).
    """
    if str(filepath) in _symbol_cache:
        return _symbol_defs_cache.get(str(filepath), {})

    content = filepath.read_text(encoding="utf-8", errors="replace")
    _symbol_cache[str(filepath)] = content

    symbols: dict[str, str] = {}
    # Find all top-level (symbol "Name" ...) blocks
    # Top-level means depth 2 inside (kicad_lib (lib_symbols (symbol ...)))
    depth = 0
    symbol_start = None
    symbol_name = None

    lines = content.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("(symbol "):
            depth += 1
            if depth == 2:  # Top-level symbol inside (lib_symbols ...)
                # Extract symbol name
                m = re.match(r'\(symbol\s+"([^"]*)"', stripped)
                if m:
                    symbol_name = m.group(1)
                    symbol_start = i
        elif stripped == ")":
            if depth == 2 and symbol_start is not None and symbol_name:
                # End of top-level symbol block
                symbol_text = "\n".join(lines[symbol_start:i + 1])
                symbols[symbol_name] = symbol_text
                symbol_start = None
                symbol_name = None
            depth -= 1
        else:
            depth += stripped.count("(") - stripped.count(")")
            if depth < 1:
                depth = 1  # Safety

    _symbol_defs_cache[str(filepath)] = symbols
    return symbols


def resolve_symbol_path(symbol_name: str) -> Optional[Path]:
    """Resolve a KiCad symbol name like 'Device:R' to the .kicad_sym file.
    The library part before : is the filename.
    """
    root = find_kicad_symbols_root()
    if root is None:
        return None

    if ":" in symbol_name:
        lib, _ = symbol_name.split(":", 1)
    else:
        lib = "Device"  # Default library

    sym_file = root / f"{lib}.kicad_sym"
    if sym_file.is_file():
        return sym_file
    return None


def get_symbol_definition(lib_id: str) -> Optional[str]:
    """Get the full symbol definition text for a given library ID.

    Args:
        lib_id: e.g. "Device:R", "RF_Module:ESP32-C3-WROOM-02"

    Returns:
        Full (symbol ...) text block, or None if not found.
    """
    sym_path = resolve_symbol_path(lib_id)
    if sym_path is None:
        return None

    symbols = _parse_symbols_from_file(sym_path)

    # Try exact match first
    if lib_id in symbols:
        return symbols[lib_id]

    # Try without library prefix (just the symbol name)
    _, sym_name = lib_id.split(":", 1) if ":" in lib_id else ("", lib_id)
    if sym_name in symbols:
        return symbols[sym_name]

    # Try partial match
    for name, text in symbols.items():
        if name == sym_name or name.endswith(f":{sym_name}"):
            return text

    return None


def transform_symbol_for_schematic(
    symbol_text: str,
    lib_id: str,
    ref: str,
    value: str,
    footprint: str,
    x: float,
    y: float,
) -> list[str]:
    """Transform a raw symbol definition for embedding in a .kicad_sch file.

    The lib_symbols section needs the raw symbol definition.
    The symbol instance section needs ref, value, footprint, position.

    Returns lines for the symbol instance (not the lib_symbol definition).
    """
    # Build the symbol instance block
    lines = [
        f'    (symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} 0) (unit 1)',
        '      (exclude_from_sim no)',
        '      (in_bom yes) (on_board yes)',
        '      (dnp no)',
        f'      (uuid "{__import__("uuid").uuid4()}")',
        f'      (property "Reference" "{ref}" (at {x:.2f} {y - 2.54:.2f} 0)',
        '        (effects (font (size 1.27 1.27)))',
        '      )',
        f'      (property "Value" "{value}" (at {x:.2f} {y + 2.54:.2f} 0)',
        '        (effects (font (size 1.27 1.27)))',
        '      )',
        f'      (property "Footprint" "{footprint}" (at {x:.2f} {y + 5.08:.2f} 0)',
        '        (effects (font (size 1.27 1.27)) hide)',
        '      )',
        f'      (property "Datasheet" "" (at {x:.2f} {y:.2f} 0)',
        '        (effects (font (size 1.27 1.27)) hide)',
        '      )',
        '    )',
    ]
    return lines


def is_symbol_available(lib_id: str) -> bool:
    """Check if a symbol is available in the local KiCad library."""
    return get_symbol_definition(lib_id) is not None


# Mapping from library.json symbol field to actual KiCad standard library symbol IDs
# These are verified to exist in KiCad 10.0 standard library
SYMBOL_MAP = {
    # Passives
    "Device:R": "Device:R",
    "Device:C": "Device:C",
    "Device:L": "Device:L",
    "Device:LED": "Device:LED",
    "Device:Antenna": "Device:Antenna",
    # Connectors
    "Connector:USB_C_Receptacle_USB2.0": "Connector:USB_C_Receptacle_USB2.0_16P",
    "Connector:Conn_Coaxial": "Connector:Conn_Coaxial",
    "Connector_Generic:Conn_01x04": "Connector_Generic:Conn_01x04",
    "Connector_Generic:Conn_01x02": "Connector_Generic:Conn_01x02",
    # Switches
    "Switch:SW_Push": "Switch:SW_Push",
    # ICs - exact matches from KiCad 10.0
    "Regulator_Linear:TLV75533PDBVR": "Regulator_Linear:TLV75533PDBV",
    "Power_Protection:USBLC6-2SC6": "Power_Protection:USBLC6-2SC6",
    # Sensors
    "Sensor:SHT31-DIS": "Sensor_Humidity:SHT31-DIS",
    # RF modules
    "RF_Module:ESP32-C3-MINI-1": "RF_Module:ESP32-C3-WROOM-02",
    "RF_Module:SX1262_Module_Generic": "RF:SX1262IMLTRT",
    # Battery management
    "Battery_Management:MCP73831-2-OT": "Battery_Management:MCP73831",
}


def get_lib_id_for_component(symbol_field: str) -> str:
    """Get the correct KiCad library ID for a component's symbol field.

    Args:
        symbol_field: The symbol field from library.json, e.g. "Device:R"

    Returns:
        Correct KiCad lib_id, e.g. "Device:R"
    """
    return SYMBOL_MAP.get(symbol_field, symbol_field)
