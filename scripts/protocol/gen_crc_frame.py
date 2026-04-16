#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_crc_frame.py

CRC calculator and protocol frame generator for embedded communication workflows.

Supported algorithms
  CRC8          poly=0x07, init=0x00, no reflect
  CRC8_MAXIM    poly=0x31, init=0x00, reflect — Dallas/Maxim 1-Wire
  CRC16_MODBUS  poly=0x8005, init=0xFFFF, reflect
  CRC16_CCITT   poly=0x1021, init=0xFFFF, no reflect — X.25/HDLC
  CRC16_IBM     poly=0x8005, init=0x0000, reflect
  CRC32         poly=0x04C11DB7, init=0xFFFFFFFF, reflect — Ethernet/ZIP

Features
- Compute CRC for arbitrary hex data
- Build complete protocol frame: [header][LEN][CMD][data][CRC]
- Verify a received frame
- Generate C lookup-table function ready to paste into firmware
- Unified dict/JSON output contract
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# CRC algorithm descriptors
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CRCAlgo:
    name:    str
    width:   int
    poly:    int
    init:    int
    ref_in:  bool
    ref_out: bool
    xor_out: int
    check:   int   # CRC of b"123456789"


ALGOS: Dict[str, CRCAlgo] = {
    "CRC8":         CRCAlgo("CRC8",         8,  0x07,       0x00,     False, False, 0x00,       0xF4),
    "CRC8_MAXIM":   CRCAlgo("CRC8_MAXIM",   8,  0x31,       0x00,     True,  True,  0x00,       0xA1),
    "CRC16_MODBUS": CRCAlgo("CRC16_MODBUS", 16, 0x8005,     0xFFFF,   True,  True,  0x0000,     0x4B37),
    "CRC16_CCITT":  CRCAlgo("CRC16_CCITT",  16, 0x1021,     0xFFFF,   False, False, 0x0000,     0x29B1),
    "CRC16_IBM":    CRCAlgo("CRC16_IBM",    16, 0x8005,     0x0000,   True,  True,  0x0000,     0xBB3D),
    "CRC32":        CRCAlgo("CRC32",        32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF, 0xCBF43926),
}


# ---------------------------------------------------------------------------
# CRC engine
# ---------------------------------------------------------------------------

def _reflect(value: int, bits: int) -> int:
    result = 0
    for _ in range(bits):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def _build_table(algo: CRCAlgo) -> List[int]:
    mask = (1 << algo.width) - 1
    msb  = 1 << (algo.width - 1)
    table: List[int] = []
    for i in range(256):
        crc = _reflect(i, 8) << (algo.width - 8) if algo.ref_in else i << (algo.width - 8)
        for _ in range(8):
            crc = ((crc << 1) ^ algo.poly) & mask if crc & msb else (crc << 1) & mask
        table.append(_reflect(crc, algo.width) if algo.ref_out else crc)
    return table


def _compute_crc(data: bytes, algo: CRCAlgo) -> int:
    table = _build_table(algo)
    mask  = (1 << algo.width) - 1
    crc   = algo.init
    if algo.ref_in:
        crc = _reflect(crc, algo.width)
        for b in data:
            crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]
    else:
        for b in data:
            idx = ((crc >> (algo.width - 8)) ^ b) & 0xFF
            crc = ((crc << 8) ^ table[idx]) & mask
        if algo.ref_out:
            crc = _reflect(crc, algo.width)
    return (crc ^ algo.xor_out) & mask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hex(s: str) -> bytes:
    tokens = s.replace(",", " ").split()
    out = []
    for t in tokens:
        t = t.strip().lstrip("0xX").lstrip("0x")
        if t:
            # handle 0x prefix properly
            raw = s.replace(",", " ").split()
    # redo cleanly
    result = []
    for tok in s.replace(",", " ").split():
        tok = tok.strip()
        if not tok:
            continue
        result.append(int(tok, 16) if tok.startswith(("0x", "0X")) else int(tok, 16))
    return bytes(result)


def _hex_str(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _crc_hex(val: int, width: int) -> str:
    return f"0x{val:0{width // 4}X}"


def _crc_to_bytes(val: int, width: int) -> bytes:
    return val.to_bytes(width // 8, "big")


# ---------------------------------------------------------------------------
# C code generator
# ---------------------------------------------------------------------------

def _gen_c_code(algo: CRCAlgo) -> str:
    table = _build_table(algo)
    w     = algo.width
    ctype = "uint8_t" if w == 8 else ("uint16_t" if w == 16 else "uint32_t")
    fname = f"calc_{algo.name.lower()}"
    cols  = 8

    rows = []
    for i in range(0, 256, cols):
        row = ", ".join(f"0x{v:0{w // 4}X}" for v in table[i:i + cols])
        rows.append(f"    {row},")

    if algo.ref_in and algo.ref_out:
        loop = f"        crc = ({ctype})(crc >> 8) ^ {fname}_table[(crc ^ *p++) & 0xFFU];"
    elif w == 8:
        loop = f"        crc = {fname}_table[crc ^ *p++];"
    else:
        loop = (f"        crc = ({ctype})(crc << 8) ^ "
                f"{fname}_table[((crc >> {w - 8}) ^ *p++) & 0xFFU];")

    xor_line = (f"    crc ^= 0x{algo.xor_out:0{w // 4}X}U;\n"
                if algo.xor_out else "")

    return (
        f"/* {algo.name} | poly=0x{algo.poly:X} | init=0x{algo.init:X}"
        f" | ref_in={str(algo.ref_in).lower()} | xor_out=0x{algo.xor_out:X} */\n"
        f"#include <stdint.h>\n#include <stddef.h>\n\n"
        f"static const {ctype} {fname}_table[256] = {{\n"
        + "\n".join(rows) +
        f"\n}};\n\n"
        f"{ctype} {fname}(const uint8_t *data, size_t len) {{\n"
        f"    {ctype} crc = 0x{algo.init:0{w // 4}X}U;\n"
        f"    const uint8_t *p = data;\n"
        f"    while (len--) {{\n"
        f"{loop}\n"
        f"    }}\n"
        f"{xor_line}"
        f"    return crc;\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Frame builder / verifier
# ---------------------------------------------------------------------------

def _build_frame(
    header: bytes, cmd: int, data: bytes, algo: CRCAlgo,
    len_includes_cmd: bool,
) -> bytes:
    length  = (len(data) + 1) if len_includes_cmd else len(data)
    payload = bytes([length, cmd]) + data
    crc_val = _compute_crc(payload, algo)
    return header + payload + _crc_to_bytes(crc_val, algo.width)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class CRCOutput:
    success:         bool
    inputs:          Dict[str, Any]
    results:         Dict[str, Any]
    warnings:        List[str]
    recommendations: List[str]
    next_actions:    List[str]
    error:           Optional[Dict[str, str]] = None


def gen_crc_frame(
    poly:              str,
    data_hex:          str  = "",
    frame_header_hex:  str  = "AA 55",
    cmd:               int  = 0x01,
    build_frame:       bool = False,
    verify_frame_hex:  str  = "",
    include_c_code:    bool = True,
    len_includes_cmd:  bool = True,
) -> Dict[str, Any]:
    """
    Compute CRC, optionally build a protocol frame, and generate C firmware code.

    Parameters
    ----------
    poly             : CRC algorithm (CRC8 / CRC8_MAXIM / CRC16_MODBUS /
                       CRC16_CCITT / CRC16_IBM / CRC32)
    data_hex         : Data bytes as hex string, e.g. "DE AD BE EF"
    frame_header_hex : Frame sync header bytes, e.g. "AA 55"
    cmd              : Command byte (0–255)
    build_frame      : Assemble [header][LEN][CMD][data][CRC]
    verify_frame_hex : Full received frame hex to verify CRC
    include_c_code   : Include C lookup-table function in output
    len_includes_cmd : LEN = len(data)+1 if True, else len(data)
    """
    inputs: Dict[str, Any] = {
        "poly": poly, "data_hex": data_hex,
        "frame_header_hex": frame_header_hex,
        "cmd": hex(cmd), "build_frame": build_frame,
        "verify_frame_hex": verify_frame_hex,
        "include_c_code": include_c_code,
    }

    try:
        key = poly.upper().strip()
        if key not in ALGOS:
            raise ValueError(f"Unknown algorithm '{poly}'. Supported: {', '.join(ALGOS)}")
        algo = ALGOS[key]

        results: Dict[str, Any] = {
            "algorithm":  algo.name,
            "width_bits": algo.width,
            "poly_hex":   f"0x{algo.poly:X}",
            "init_hex":   f"0x{algo.init:X}",
            "ref_in":     algo.ref_in,
            "ref_out":    algo.ref_out,
            "xor_out_hex": f"0x{algo.xor_out:X}",
            "check_value": _crc_hex(algo.check, algo.width),
        }
        warnings:  List[str] = []
        recs:      List[str] = []

        # CRC computation
        if data_hex.strip():
            data  = _parse_hex(data_hex)
            val   = _compute_crc(data, algo)
            results["input_data_hex"]     = _hex_str(data)
            results["input_length_bytes"] = len(data)
            results["crc_value_hex"]      = _crc_hex(val, algo.width)
            results["crc_bytes_hex"]      = _hex_str(_crc_to_bytes(val, algo.width))

        # Frame assembly
        if build_frame and data_hex.strip():
            header = _parse_hex(frame_header_hex)
            data   = _parse_hex(data_hex)
            frame  = _build_frame(header, cmd, data, algo, len_includes_cmd)
            length = (len(data) + 1) if len_includes_cmd else len(data)
            payload = bytes([length, cmd]) + data
            crc_val = _compute_crc(payload, algo)
            results["frame_hex"]    = _hex_str(frame)
            results["frame_length"] = len(frame)
            results["frame_breakdown"] = {
                "header":   _hex_str(header),
                "len_byte": f"{length:02X}",
                "cmd_byte": f"{cmd:02X}",
                "data":     _hex_str(data),
                "crc":      _hex_str(_crc_to_bytes(crc_val, algo.width)),
            }

        # Frame verification
        if verify_frame_hex.strip():
            frame_bytes = _parse_hex(verify_frame_hex)
            crc_size    = algo.width // 8
            if len(frame_bytes) <= crc_size:
                warnings.append("Frame too short to contain a CRC field.")
            else:
                rx_crc_bytes = frame_bytes[-crc_size:]
                rx_crc       = int.from_bytes(rx_crc_bytes, "big")
                payload      = frame_bytes[:-crc_size]
                computed     = _compute_crc(payload, algo)
                ok           = rx_crc == computed
                results["verify"] = {
                    "received_crc":  _crc_hex(rx_crc, algo.width),
                    "computed_crc":  _crc_hex(computed, algo.width),
                    "frame_valid":   ok,
                }
                if not ok:
                    warnings.append(
                        f"CRC MISMATCH — received {_crc_hex(rx_crc, algo.width)}, "
                        f"computed {_crc_hex(computed, algo.width)}."
                    )

        # C code
        if include_c_code:
            results["c_code"] = _gen_c_code(algo)

        # Recommendations
        recs.append(
            f"Ensure all nodes use identical {algo.name} parameters "
            "(poly, init, ref_in, xor_out). Mismatches cause silent data corruption."
        )
        if algo.width == 8:
            recs.append(
                "CRC8 has a ~0.4 % undetected-error rate for burst errors. "
                "Use CRC16 or CRC32 for safety-critical or OTA firmware data."
            )
        if algo.name == "CRC16_MODBUS":
            recs.append(
                "CRC16_MODBUS is transmitted low-byte first. "
                "Confirm byte order with your receiver implementation."
            )

        return asdict(CRCOutput(
            success=True, inputs=inputs, results=results,
            warnings=warnings, recommendations=recs,
            next_actions=["gen_uart_protocol", "gen_firmware_skeleton"],
        ))

    except Exception as exc:
        return asdict(CRCOutput(
            success=False, inputs=inputs, results={},
            warnings=[], recommendations=[], next_actions=[],
            error={"code": exc.__class__.__name__.upper(), "message": str(exc)},
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="CRC calculator and protocol frame generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--poly",    required=True, choices=list(ALGOS))
    p.add_argument("--data",    default="",    dest="data_hex",
                   help="Data bytes as hex, e.g. 'AA 55 01 02'")
    p.add_argument("--frame-header", default="AA 55", dest="frame_header_hex")
    p.add_argument("--cmd",     type=lambda x: int(x, 0), default=0x01)
    p.add_argument("--build-frame", action="store_true")
    p.add_argument("--verify",  default="", dest="verify_frame_hex",
                   help="Full received frame hex to verify")
    p.add_argument("--no-c-code", action="store_false", dest="include_c_code")
    p.add_argument("--len-excludes-cmd", action="store_false", dest="len_includes_cmd")
    args = p.parse_args()

    result = gen_crc_frame(
        poly=args.poly, data_hex=args.data_hex,
        frame_header_hex=args.frame_header_hex, cmd=args.cmd,
        build_frame=args.build_frame, verify_frame_hex=args.verify_frame_hex,
        include_c_code=args.include_c_code, len_includes_cmd=args.len_includes_cmd,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
