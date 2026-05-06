"""Read standard KiCad .kicad_sym symbol library files.

Parses symbol definitions, pin positions (by_number + by_name),
handles extends inheritance, and finds sub-symbols at any depth.
"""
from __future__ import annotations
import re, json
from pathlib import Path
from typing import Optional

KICAD_SYMBOL_SEARCH_PATHS = [
    Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols"),
    Path(r"C:\Program Files\KiCad\9.0\share\kicad\symbols"),
]

_kicad_symbols_root: Optional[Path] = None
_file_cache: dict[str, str] = {}
_symbols_cache: dict[str, dict[str, str]] = {}
_extends_cache: dict[str, dict[str, str]] = {}
_pin_cache: dict[str, dict] = {}


def find_kicad_symbols_root() -> Optional[Path]:
    global _kicad_symbols_root
    if _kicad_symbols_root:
        return _kicad_symbols_root
    for base in KICAD_SYMBOL_SEARCH_PATHS:
        if base.is_dir():
            _kicad_symbols_root = base
            return base
    return None


def _parse_file(filepath: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Parse all (symbol ...) blocks from .kicad_sym at any nesting depth.
    Returns (symbols_dict, extends_map).
    """
    key = str(filepath)
    if key in _symbols_cache:
        return _symbols_cache[key], _extends_cache.get(key, {})

    if key not in _file_cache:
        _file_cache[key] = filepath.read_text(encoding="utf-8", errors="replace")
    content = _file_cache[key]
    lines = content.split("\n")

    symbols: dict[str, str] = {}
    extends: dict[str, str] = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        m = re.match(r'\(symbol\s+"([^"]*)"', stripped)
        if m:
            sym_name = m.group(1)
            d = 0
            start = i
            for j in range(i, len(lines)):
                for ch in lines[j]:
                    if ch == '(': d += 1
                    elif ch == ')': d -= 1
                if d == 0:
                    block = "\n".join(lines[start:j+1])
                    # Only store if not already stored (first definition wins)
                    if sym_name not in symbols:
                        symbols[sym_name] = block
                    # Check for extends on lines after opening
                    for k in range(start+1, min(start+3, j+1)):
                        ext_m = re.search(r'\(extends\s+"([^"]+)"', lines[k])
                        if ext_m:
                            extends[sym_name] = ext_m.group(1)
                            break
                    i = j
                    break
            else:
                i += 1
        else:
            i += 1

    _symbols_cache[key] = symbols
    _extends_cache[key] = extends
    return symbols, extends


def resolve_symbol_path(symbol_name: str) -> Optional[Path]:
    root = find_kicad_symbols_root()
    if not root:
        return None
    lib = symbol_name.split(":", 1)[0] if ":" in symbol_name else "Device"
    p = root / f"{lib}.kicad_sym"
    return p if p.is_file() else None


def _rename_symbol(text: str, old: str, new: str) -> str:
    """Rename symbol and sub-symbols: R -> Device:R, R_1_1 -> Device:R_1_1"""
    def repl(m):
        name = m.group(1)
        if name == old or name.startswith(old + "_"):
            return f'(symbol "{new}{name[len(old):]}"'
        return m.group(0)
    return re.sub(r'\(symbol "([^"]*)"', repl, text)


def get_symbol_definition(lib_id: str) -> Optional[str]:
    """Get full symbol definition text with names using full lib_id."""
    sym_path = resolve_symbol_path(lib_id)
    if not sym_path:
        return None
    symbols, extends = _parse_file(sym_path)

    if lib_id in symbols:
        return symbols[lib_id]

    _, sym_name = lib_id.split(":", 1) if ":" in lib_id else ("", lib_id)
    if sym_name in symbols:
        return _rename_symbol(symbols[sym_name], sym_name, lib_id)

    for name, text in symbols.items():
        if name == sym_name or name.endswith(f":{sym_name}"):
            return _rename_symbol(text, name, lib_id)
    return None


def _extract_pins_from_block(block: str) -> dict[str, dict]:
    """Extract pin positions from a symbol block.
    Returns {pin_number: {"x","y","angle","length","name"}}
    """
    pins = {}
    pin_blocks = re.split(r'(?=\(pin\s+\w+\s+line)', block)
    for pb in pin_blocks:
        at_m = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\)', pb)
        len_m = re.search(r'\(length\s+([\d.-]+)\)', pb)
        num_m = re.search(r'\(number\s+"([^"]+)"', pb)
        name_m = re.search(r'\(name\s+"([^"]*)"', pb)
        if not at_m or not num_m:
            continue
        pin_num = num_m.group(1)
        pin_name = name_m.group(1) if name_m else ""
        pins[pin_num] = {
            "x": float(at_m.group(1)),
            "y": float(at_m.group(2)),
            "angle": int(at_m.group(3)),
            "length": float(len_m.group(1)) if len_m else 2.54,
            "name": pin_name,
        }
    return pins


def get_pin_positions(lib_id: str) -> dict[str, dict]:
    """Parse real pin positions. Returns {"by_number": {...}, "by_name": {...}}.
    by_number: pin_number -> coords
    by_name: pin_name (from symbol) -> coords
    """
    if lib_id in _pin_cache:
        return _pin_cache[lib_id]

    sym_path = resolve_symbol_path(lib_id)
    if not sym_path:
        _pin_cache[lib_id] = {"by_number": {}, "by_name": {}}
        return _pin_cache[lib_id]

    symbols, extends = _parse_file(sym_path)
    _, sym_name = lib_id.split(":", 1) if ":" in lib_id else ("", lib_id)

    # Find the main symbol block
    main_block = symbols.get(sym_name, "")
    if not main_block:
        for name, text in symbols.items():
            if name == sym_name or name.endswith(f":{sym_name}"):
                main_block = text
                sym_name = name
                break

    # If this symbol extends another, get parent's block too
    parent_name = extends.get(sym_name, "")
    parent_block = symbols.get(parent_name, "") if parent_name else ""

    # Find _1_1 draw sub-symbol (may be nested inside main block)
    draw_block = ""
    for suffix in ["_1_1", "_0_1"]:
        target = f"{sym_name}{suffix}"
        # Search in main block first
        pat = re.compile(rf'\(symbol\s+"{re.escape(target)}"')
        m = pat.search(main_block)
        if m:
            draw_block = main_block[m.start():]
            break
        # Search in parent block
        if parent_block:
            m = pat.search(parent_block)
            if m:
                draw_block = parent_block[m.start():]
                break

    # If no sub-symbol found, use main block itself
    if not draw_block:
        draw_block = main_block

    # Also try parent block directly if nothing found yet
    if not draw_block and parent_block:
        draw_block = parent_block

    by_number = _extract_pins_from_block(draw_block)

    # Build by_name map
    by_name: dict[str, dict] = {}
    for num, info in by_number.items():
        if info.get("name"):
            by_name[info["name"]] = info

    # If parent has pins we don't have, merge them
    if parent_block and parent_name:
        parent_draw = ""
        for suffix in ["_1_1", "_0_1"]:
            pat = re.compile(rf'\(symbol\s+"{re.escape(parent_name)}{suffix}"')
            m = pat.search(parent_block)
            if m:
                parent_draw = parent_block[m.start():]
                break
        if not parent_draw:
            parent_draw = parent_block
        parent_pins = _extract_pins_from_block(parent_draw)
        for num, info in parent_pins.items():
            if num not in by_number:
                by_number[num] = info
                if info.get("name"):
                    by_name[info["name"]] = info

    result = {"by_number": by_number, "by_name": by_name}
    _pin_cache[lib_id] = result
    return result


def is_symbol_available(lib_id: str) -> bool:
    return get_symbol_definition(lib_id) is not None


# Symbol mapping: library.json field -> actual KiCad library symbol
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

# Netlist pin name -> symbol pin name fuzzy matching
PIN_NAME_ALIASES = {
    # ESP32 GPIO aliases
    "GPIO0": "IO0", "GPIO1": "IO1", "GPIO2": "IO2", "GPIO3": "IO3",
    "GPIO4": "IO4", "GPIO5": "IO5", "GPIO6": "IO6", "GPIO7": "IO7",
    "GPIO8": "IO8", "GPIO9": "IO9", "GPIO10": "IO10",
    "GPIO18": "IO18", "GPIO19": "IO19",
    "GPIO20": "IO20/RXD", "GPIO21": "IO21/TXD",
    "3V3": "3V3",
    # Power pin aliases (many ICs use VSS/VDD instead of GND/VCC)
    "GND": "VSS",
    "VBUS": "VCC",
    "VIN": "VDD",
}


def get_lib_id_for_component(symbol_field: str) -> str:
    return SYMBOL_MAP.get(symbol_field, symbol_field)


def resolve_pin_name(pin_name: str, lib_id: str) -> str:
    """Try to resolve a netlist pin name to a symbol pin name.
    Returns the resolved name or the original if no match.
    """
    # Direct match
    pins = get_pin_positions(lib_id)
    by_name = pins.get("by_name", {})
    by_number = pins.get("by_number", {})
    if pin_name in by_name or pin_name in by_number:
        return pin_name

    # Check aliases
    aliased = PIN_NAME_ALIASES.get(pin_name)
    if aliased and (aliased in by_name or aliased in by_number):
        return aliased

    # Case-insensitive match
    upper_map = {n.upper(): n for n in by_name}
    if pin_name.upper() in upper_map:
        return upper_map[pin_name.upper()]

    # Substring match (e.g. "IO20/RXD" contains "IO20")
    for sym_pin in list(by_name.keys()) + list(by_number.keys()):
        if pin_name in sym_pin or sym_pin in pin_name:
            return sym_pin

    return pin_name
