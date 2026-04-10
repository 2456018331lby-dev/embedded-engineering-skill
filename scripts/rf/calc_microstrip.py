#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_microstrip.py

Microstrip transmission line calculator for embedded/RF engineering workflows.

Features
- Solve line width for a target characteristic impedance
- Solve characteristic impedance for a given line width
- Estimate guided wavelength / quarter-wave / half-wave lengths
- Provide basic manufacturability and RF guidance warnings
- Return a unified dict output for direct skill / MCP integration

Notes
- Uses common closed-form approximations for microstrip lines
- Best used as a first-pass engineering calculator
- For final RF boards, verify with your PCB stackup calculator and EM simulation
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import argparse
import json
import math
import sys


C0 = 299_792_458.0  # m/s


def _effective_er(er: float, h_mm: float, w_mm: float) -> float:
    """Compute effective dielectric constant using a standard approximation."""
    if er <= 1:
        raise ValueError("er must be > 1")
    if h_mm <= 0 or w_mm <= 0:
        raise ValueError("h_mm and w_mm must be > 0")

    wh = w_mm / h_mm
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 / wh) ** (-0.5)


def _z0_from_w(er: float, h_mm: float, w_mm: float) -> float:
    """Characteristic impedance from geometry using a standard closed-form approximation."""
    eeff = _effective_er(er, h_mm, w_mm)
    wh = w_mm / h_mm

    if wh <= 1.0:
        return (60.0 / math.sqrt(eeff)) * math.log(8.0 / wh + wh / 4.0)
    return (120.0 * math.pi / math.sqrt(eeff)) / (
        wh + 1.393 + 0.667 * math.log(wh + 1.444)
    )


def _solve_w_for_z0(er: float, h_mm: float, target_z0: float) -> float:
    """Numerically solve width for target impedance."""
    if target_z0 <= 0:
        raise ValueError("target_z0 must be > 0")

    # Search bounds: extremely narrow to very wide.
    lo = max(0.001, h_mm * 0.01)
    hi = max(h_mm * 50.0, 100.0)

    # Ensure bracket; impedance decreases with width.
    z_lo = _z0_from_w(er, h_mm, lo)
    z_hi = _z0_from_w(er, h_mm, hi)

    if not (z_lo >= target_z0 >= z_hi):
        # Try to widen the bracket a bit more.
        for factor in [100.0, 200.0, 500.0]:
            hi2 = max(h_mm * factor, hi)
            z_hi = _z0_from_w(er, h_mm, hi2)
            if z_lo >= target_z0 >= z_hi:
                hi = hi2
                break
        else:
            raise RuntimeError(
                f"Unable to bracket target impedance {target_z0:.3f} Ω "
                f"(z at low={z_lo:.2f}, z at high={z_hi:.2f})"
            )

    # Binary search.
    for _ in range(120):
        mid = (lo + hi) / 2.0
        z_mid = _z0_from_w(er, h_mm, mid)
        if z_mid > target_z0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _conductor_loss_hint(freq_ghz: float, width_mm: float, copper_oz: float) -> float:
    """
    Very rough conductor-loss hint in dB/cm.

    This is only a first-pass heuristic, not a substitute for a proper EM solver.
    """
    if freq_ghz <= 0:
        raise ValueError("freq_ghz must be > 0")
    if width_mm <= 0 or copper_oz <= 0:
        raise ValueError("width_mm and copper_oz must be > 0")

    # Heuristic: higher frequency -> more loss, wider trace -> lower loss, thicker copper -> lower loss
    return 0.02 * math.sqrt(freq_ghz) * math.sqrt(1.0 / width_mm) / math.sqrt(copper_oz)


def _dielectric_loss_hint(freq_ghz: float, er: float, loss_tangent: float) -> float:
    """
    Very rough dielectric-loss hint in dB/cm.
    """
    if freq_ghz <= 0:
        raise ValueError("freq_ghz must be > 0")
    if er <= 1:
        raise ValueError("er must be > 1")
    if loss_tangent < 0:
        raise ValueError("loss_tangent must be >= 0")

    return 0.15 * freq_ghz * loss_tangent * math.sqrt((er - 1.0) / er)


def _manufacturability_warnings(
    substrate: str,
    freq_ghz: float,
    width_mm: float,
    h_mm: float,
    board_capability_min_width_mm: float,
) -> list[str]:
    warnings: list[str] = []

    if width_mm < board_capability_min_width_mm:
        warnings.append(
            f"Calculated width {width_mm:.4f} mm is below board capability minimum "
            f"{board_capability_min_width_mm:.4f} mm."
        )

    if substrate.upper() == "FR4" and freq_ghz > 3.0:
        warnings.append(
            "FR4 is usually acceptable for low/mid RF, but above ~3 GHz losses and "
            "dielectric variability become increasingly significant."
        )

    if width_mm / h_mm < 0.15:
        warnings.append("Trace is very narrow relative to substrate height; fabrication tolerance risk is high.")

    if width_mm / h_mm > 10:
        warnings.append("Trace is very wide relative to substrate height; confirm solder mask, coupling, and ground clearance.")

    return warnings


@dataclass
class MicrostripResult:
    success: bool
    inputs: Dict[str, Any]
    results: Dict[str, Any]
    warnings: list[str]
    recommendations: list[str]
    next_actions: list[str]
    error: Optional[Dict[str, str]] = None


def calc_microstrip(
    er: float,
    h_mm: float,
    target_z0: float = 50.0,
    copper_oz: float = 1.0,
    freq_ghz: float = 2.4,
    substrate: str = "FR4",
    loss_tangent: float = 0.02,
    board_capability_min_width_mm: float = 0.10,
    mode: str = "solve_width",
    trace_width_mm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Unified microstrip calculator.

    Parameters
    ----------
    er : float
        Relative dielectric constant.
    h_mm : float
        Substrate height in mm.
    target_z0 : float
        Target characteristic impedance in ohms.
    copper_oz : float
        Copper thickness in ounces.
    freq_ghz : float
        Operating frequency in GHz.
    substrate : str
        Substrate label for guidance.
    loss_tangent : float
        Dielectric loss tangent.
    board_capability_min_width_mm : float
        Minimum manufacturable trace width.
    mode : str
        solve_width | solve_impedance | phase_length
    trace_width_mm : float, optional
        Required for solve_impedance mode.

    Returns
    -------
    dict
        Unified result dict with success / inputs / results / warnings / recommendations / next_actions.
    """
    inputs = {
        "er": er,
        "h_mm": h_mm,
        "target_z0": target_z0,
        "copper_oz": copper_oz,
        "freq_ghz": freq_ghz,
        "substrate": substrate,
        "loss_tangent": loss_tangent,
        "board_capability_min_width_mm": board_capability_min_width_mm,
        "mode": mode,
        "trace_width_mm": trace_width_mm,
    }

    try:
        if mode == "solve_width":
            width_mm = _solve_w_for_z0(er, h_mm, target_z0)
            eeff = _effective_er(er, h_mm, width_mm)
            z0 = _z0_from_w(er, h_mm, width_mm)
        elif mode == "solve_impedance":
            if trace_width_mm is None:
                raise ValueError("trace_width_mm is required in solve_impedance mode")
            width_mm = float(trace_width_mm)
            eeff = _effective_er(er, h_mm, width_mm)
            z0 = _z0_from_w(er, h_mm, width_mm)
        elif mode == "phase_length":
            # Use target_z0 width as a reference geometry
            width_mm = _solve_w_for_z0(er, h_mm, target_z0)
            eeff = _effective_er(er, h_mm, width_mm)
            z0 = _z0_from_w(er, h_mm, width_mm)
        else:
            raise ValueError("mode must be one of: solve_width, solve_impedance, phase_length")

        lambda0_mm = (C0 / (freq_ghz * 1e9)) * 1e3
        guided_wavelength_mm = lambda0_mm / math.sqrt(eeff)
        quarter_wave_mm = guided_wavelength_mm / 4.0
        half_wave_mm = guided_wavelength_mm / 2.0

        conductor_loss_db_cm = _conductor_loss_hint(freq_ghz, width_mm, copper_oz)
        dielectric_loss_db_cm = _dielectric_loss_hint(freq_ghz, er, loss_tangent)
        total_loss_db_cm = conductor_loss_db_cm + dielectric_loss_db_cm

        warnings = _manufacturability_warnings(
            substrate=substrate,
            freq_ghz=freq_ghz,
            width_mm=width_mm,
            h_mm=h_mm,
            board_capability_min_width_mm=board_capability_min_width_mm,
        )

        recommendations = []
        if substrate.upper() == "FR4" and freq_ghz > 3.0:
            recommendations.append("Consider low-loss laminate (Rogers/Taconic) for better repeatability above 3 GHz.")
        if total_loss_db_cm > 0.5:
            recommendations.append("Keep RF trace short and review stackup; loss is relatively high.")
        else:
            recommendations.append("Trace loss looks acceptable as a first-pass estimate.")
        recommendations.append("Verify final line width with the PCB vendor stackup calculator.")
        recommendations.append("Use EM simulation for the final design, especially for antennas and matching networks.")

        next_actions = ["calc_cpwg", "check_rf_rules"]

        result = MicrostripResult(
            success=True,
            inputs=inputs,
            results={
                "width_mm": round(width_mm, 4),
                "z0_ohm": round(z0, 3),
                "effective_er": round(eeff, 4),
                "lambda0_mm": round(lambda0_mm, 3),
                "guided_wavelength_mm": round(guided_wavelength_mm, 3),
                "quarter_wave_mm": round(quarter_wave_mm, 3),
                "half_wave_mm": round(half_wave_mm, 3),
                "conductor_loss_db_cm": round(conductor_loss_db_cm, 4),
                "dielectric_loss_db_cm": round(dielectric_loss_db_cm, 4),
                "total_loss_db_cm": round(total_loss_db_cm, 4),
            },
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions,
        )
        return asdict(result)

    except Exception as exc:
        return asdict(
            MicrostripResult(
                success=False,
                inputs=inputs,
                results={},
                warnings=[],
                recommendations=[],
                next_actions=[],
                error={
                    "code": exc.__class__.__name__.upper(),
                    "message": str(exc),
                },
            )
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Microstrip calculator")
    p.add_argument("--er", type=float, required=True, help="Relative dielectric constant")
    p.add_argument("--h-mm", type=float, required=True, help="Substrate height in mm")
    p.add_argument("--target-z0", type=float, default=50.0, help="Target impedance in ohms")
    p.add_argument("--copper-oz", type=float, default=1.0, help="Copper thickness in oz")
    p.add_argument("--freq-ghz", type=float, default=2.4, help="Operating frequency in GHz")
    p.add_argument("--substrate", type=str, default="FR4", help="Substrate label")
    p.add_argument("--loss-tangent", type=float, default=0.02, help="Loss tangent")
    p.add_argument(
        "--board-capability-min-width-mm",
        type=float,
        default=0.10,
        help="Board fab minimum trace width in mm",
    )
    p.add_argument(
        "--mode",
        type=str,
        default="solve_width",
        choices=["solve_width", "solve_impedance", "phase_length"],
        help="Calculation mode",
    )
    p.add_argument("--trace-width-mm", type=float, default=None, help="Trace width for solve_impedance")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    result = calc_microstrip(
        er=args.er,
        h_mm=args.h_mm,
        target_z0=args.target_z0,
        copper_oz=args.copper_oz,
        freq_ghz=args.freq_ghz,
        substrate=args.substrate,
        loss_tangent=args.loss_tangent,
        board_capability_min_width_mm=args.board_capability_min_width_mm,
        mode=args.mode,
        trace_width_mm=args.trace_width_mm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
