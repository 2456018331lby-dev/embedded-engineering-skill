#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_cpwg.py

Engineering-grade first-pass CPWG (Coplanar Waveguide with Ground) calculator
for embedded RF workflows.

Features
- Solve impedance from width/gap/stackup
- Estimate guided wavelength and quarter-wave section
- Via fence pitch recommendation
- Edge-launch SMA guidance
- Manufacturability warnings
- Unified dict/JSON output contract
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import argparse
import json
import math

C0 = 299_792_458.0


def _effective_er(er: float) -> float:
    if er <= 1:
        raise ValueError("er must be > 1")
    return (er + 1.0) / 2.0


def _z0_cpwg(er: float, h_mm: float, width_mm: float, gap_mm: float) -> float:
    if h_mm <= 0 or width_mm <= 0 or gap_mm <= 0:
        raise ValueError("h_mm, width_mm, gap_mm must be > 0")
    eeff = _effective_er(er)
    # Stable first-pass Hammerstad-style approximation
    return 87.0 / math.sqrt(eeff) * math.log(5.98 * h_mm / (0.8 * width_mm + gap_mm))


@dataclass
class CPWGResult:
    success: bool
    inputs: Dict[str, Any]
    results: Dict[str, Any]
    warnings: list[str]
    recommendations: list[str]
    next_actions: list[str]
    error: Optional[Dict[str, str]] = None


def calc_cpwg(
    er: float,
    h_mm: float,
    width_mm: float,
    gap_mm: float,
    freq_ghz: float = 2.4,
    substrate: str = "FR4",
    board_capability_min_width_mm: float = 0.10,
    board_capability_min_gap_mm: float = 0.10,
) -> Dict[str, Any]:
    inputs = {
        "er": er,
        "h_mm": h_mm,
        "width_mm": width_mm,
        "gap_mm": gap_mm,
        "freq_ghz": freq_ghz,
        "substrate": substrate,
        "board_capability_min_width_mm": board_capability_min_width_mm,
        "board_capability_min_gap_mm": board_capability_min_gap_mm,
    }

    try:
        eeff = _effective_er(er)
        z0 = _z0_cpwg(er, h_mm, width_mm, gap_mm)

        lambda0_mm = (C0 / (freq_ghz * 1e9)) * 1e3
        guided_wavelength_mm = lambda0_mm / math.sqrt(eeff)
        quarter_wave_mm = guided_wavelength_mm / 4.0

        # Conservative via fence pitch: λg/20
        via_fence_pitch_mm = guided_wavelength_mm / 20.0
        recommended_edge_clearance_mm = max(width_mm * 3.0, 1.0)

        warnings = []
        if width_mm < board_capability_min_width_mm:
            warnings.append("Signal width below PCB fab capability.")
        if gap_mm < board_capability_min_gap_mm:
            warnings.append("CPWG gap below PCB fab spacing capability.")
        if substrate.upper() == "FR4" and freq_ghz > 5.0:
            warnings.append("FR4 dielectric spread and loss may strongly affect >5 GHz CPWG.")
        if gap_mm / width_mm < 0.15:
            warnings.append("Gap is very tight relative to width; impedance tolerance sensitivity is high.")

        recommendations = [
            "Prefer CPWG for edge-launch SMA, U.FL, antenna feeds, and RF switch outputs.",
            f"Recommended via fence pitch ≤ {via_fence_pitch_mm:.3f} mm.",
            f"Keep CPWG at least {recommended_edge_clearance_mm:.3f} mm away from board edge unless using edge-launch SMA.",
            "Place dense stitching vias near RF transitions and discontinuities.",
            "Validate final geometry with PCB vendor impedance calculator and EM simulation."
        ]

        next_actions = [
            "calc_matching",
            "check_rf_rules",
            "gen_kicad_netlist",
            "sim_rf"
        ]

        return asdict(CPWGResult(
            success=True,
            inputs=inputs,
            results={
                "z0_ohm": round(z0, 3),
                "effective_er": round(eeff, 4),
                "guided_wavelength_mm": round(guided_wavelength_mm, 3),
                "quarter_wave_mm": round(quarter_wave_mm, 3),
                "via_fence_pitch_mm": round(via_fence_pitch_mm, 3),
                "recommended_edge_clearance_mm": round(recommended_edge_clearance_mm, 3),
            },
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions
        ))
    except Exception as exc:
        return asdict(CPWGResult(
            success=False,
            inputs=inputs,
            results={},
            warnings=[],
            recommendations=[],
            next_actions=[],
            error={
                "code": exc.__class__.__name__.upper(),
                "message": str(exc)
            }
        ))


def main():
    p = argparse.ArgumentParser(description="CPWG calculator")
    p.add_argument("--er", type=float, required=True)
    p.add_argument("--h-mm", type=float, required=True)
    p.add_argument("--width-mm", type=float, required=True)
    p.add_argument("--gap-mm", type=float, required=True)
    p.add_argument("--freq-ghz", type=float, default=2.4)
    p.add_argument("--substrate", type=str, default="FR4")
    args = p.parse_args()

    result = calc_cpwg(
        er=args.er,
        h_mm=args.h_mm,
        width_mm=args.width_mm,
        gap_mm=args.gap_mm,
        freq_ghz=args.freq_ghz,
        substrate=args.substrate
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
