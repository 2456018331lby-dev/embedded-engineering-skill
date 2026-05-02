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
_symbol_defs_cache: dict[str, dict[str, str]] = {}


def find_kicad_symbols_root() -> Optional[Path]:
    global _kicad_symbols_root
    if _kicad_symbols_root is not None:
        return _kicad_symbols_root
    for base in KICAD_SYMBOL_SEARCH_PATHS:
        if base.is_dir():
            _kicad_symbols_root = base
            return base
    return None


def _parse_symbols_from_file(filepath: Path) -> dict[str, str]:
    if str(filepath) in _symbol_cache:
        return _symbol_defs_cache.get(str(filepath), {})

    content = filepath.read_text(encoding="utf-8", errors="replace")
    _symbol_cache[str(filepath)] = content

    symbols: dict[str, str] = {}
    depth = 0
    symbol_start = None
    symbol_name = None

    lines = content.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("(symbol "):
            depth += 1
            if depth == 2:
                m = re.match(r'\(symbol\s+"([^"]*)"', stripped)
                if m:
                    symbol_name = m.group(1)
                    symbol_start = i
        elif stripped == ")":
            if depth == 2 and symbol_start is not None and symbol_name:
                symbol_text = "\n".join(lines[symbol_start:i + 1])
                symbols[symbol_name] = symbol_text
                symbol_start = None
                symbol_name = None
            depth -= 1
        else:
            depth += stripped.count("(") - stripped.count(")")
            if depth < 1:
                depth = 1

    _symbol_defs_cache[str(filepath)] = symbols
    return symbols


def resolve_symbol_path(symbol_name: str) -> Optional[Path]:
    root = find_kicad_symbols_root()
    if root is None:
        return None
    if ":" in symbol_name:
        lib, _ = symbol_name.split(":", 1)
    else:
        lib = "Device"
    sym_file = root / f"{lib}.kicad_sym"
    if sym_file.is_file():
        return sym_file
    return None


def _rename_symbol_to_full_id(text: str, old_name: str, new_name: str) -> str:
    """Rename symbol and all its sub-symbols to use full lib_id.
    e.g. "R" -> "Device:R", "R_0_1" -> "Device:R_0_1"
    """
    def replace_name(m):
        name = m.group(1)
        if name == old_name or name.startswith(old_name + "_"):
            new = new_name + name[len(old_name):]
            return f'(symbol "{new}"'
        return m.group(0)
    return re.sub(r'\(symbol "([^"]*)"', replace_name, text)


def get_symbol_definition(lib_id: str) -> Optional[str]:
    """Get the full symbol definition text for a given library ID.
    Returns text with symbol names renamed to full lib_id (e.g. "Device:R").
    """
    sym_path = resolve_symbol_path(lib_id)
    if sym_path is None:
        return None

    symbols = _parse_symbols_from_file(sym_path)

    # Try exact match first
    if lib_id in symbols:
        return symbols[lib_id]

    # Try without library prefix
    _, sym_name = lib_id.split(":", 1) if ":" in lib_id else ("", lib_id)
    if sym_name in symbols:
        return _rename_symbol_to_full_id(symbols[sym_name], sym_name, lib_id)

    # Try partial match
    for name, text in symbols.items():
        if name == sym_name or name.endswith(f":{sym_name}"):
            return _rename_symbol_to_full_id(text, name, lib_id)

    return None


def is_symbol_available(lib_id: str) -> bool:
    return get_symbol_definition(lib_id) is not None


# Mapping from library.json symbol field to actual KiCad standard library symbol IDs
SYMBOL_MAP = {
    "Device:R": "Device:R",
    "Device:C": "Device:C",
    "Device:L": "Device:L",
    "Device:LED": "Device:LED",
    "Device:Antenna": "Device:Antenna",
    "Connector:USB_C_Receptacle_USB2.0": "Connector:USB_C_Receptacle_USB2.0_16P",
    "Connector:Conn_Coaxial": "Connector:Conn_Coaxial",
    "Connector_Generic:Conn_01x04": "Connector_Generic:Conn_01x04",
    "Connector_Generic:Conn_01x02": "Connector_Generic:Conn_01x02",
    "Switch:SW_Push": "Switch:SW_Push",
    "Regulator_Linear:TLV75533PDBVR": "Regulator_Linear:TLV75533PDBV",
    "Power_Protection:USBLC6-2SC6": "Power_Protection:USBLC6-2SC6",
    "Sensor:SHT31-DIS": "Sensor_Humidity:SHT31-DIS",
    "RF_Module:ESP32-C3-MINI-1": "RF_Module:ESP32-C3-WROOM-02",
    "RF_Module:SX1262_Module_Generic": "RF:SX1262IMLTRT",
    "Battery_Management:MCP73831-2-OT": "Battery_Management:MCP73831",
}


def get_lib_id_for_component(symbol_field: str) -> str:
    return SYMBOL_MAP.get(symbol_field, symbol_field)
