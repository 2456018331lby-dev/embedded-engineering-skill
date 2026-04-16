#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_antenna.py

Engineering-grade first-pass antenna dimension estimator
for embedded RF workflows.

Supported antenna types
- dipole   : half-wave dipole (free-space, balanced)
- monopole : quarter-wave monopole above infinite ground plane
- patch    : rectangular microstrip patch (edge-fed)
- pifa     : planar inverted-F antenna (simplified path-length model)

Features
- Estimate physical dimensions from frequency and substrate parameters
- Report typical gain, bandwidth, and feed impedance characteristics
- Flag manufacturability and design constraints
- Unified dict/JSON output contract (matches calc_microstrip / calc_cpwg)

Notes
- All results are first-pass engineering estimates only.
- Patch and PIFA dimensions are sensitive to substrate er and h variations;
  always verify with EM simulation (HFSS / CST / OpenEMS) before layout.
- Dipole and monopole shortening factors are based on standard thin-wire
  approximations; physical realisation may require trimming.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import argparse
import json
import math

C0 = 299_792_458.0  # m/s

ANTENNA_TYPES = ("dipole", "monopole", "patch", "pifa")

# ---------------------------------------------------------------------------
# Core geometry calculators
# ---------------------------------------------------------------------------

def _free_space_wavelength_mm(freq_ghz: float) -> float:
    if freq_ghz <= 0:
        raise ValueError("freq_ghz must be > 0")
    return (C0 / (freq_ghz * 1e9)) * 1e3


def _calc_dipole(freq_ghz: float) -> Dict[str, Any]:
    """
    Half-wave dipole in free space.

    A shortening factor of 0.95 is applied to account for the finite
    conductor diameter end-effect (standard thin-wire engineering approximation).
    """
    lam0_mm = _free_space_wavelength_mm(freq_ghz)
    shortening = 0.95
    total_length_mm = shortening * lam0_mm / 2.0
    element_length_mm = total_length_mm / 2.0          # each arm

    return {
        "total_length_mm": round(total_length_mm, 3),
        "element_length_mm": round(element_length_mm, 3),
        "free_space_wavelength_mm": round(lam0_mm, 3),
        "shortening_factor": shortening,
        "resonant_feed_impedance_ohm": 73.0,            # classic thin-wire result
        "typical_gain_dbi": 2.15,
        "typical_bandwidth_vswr2_pct": 12.0,            # ~10–15 % for thin wire
        "polarisation": "linear",
        "radiation_pattern": "omnidirectional (broadside, donut-shaped)",
    }


def _calc_monopole(freq_ghz: float) -> Dict[str, Any]:
    """
    Quarter-wave monopole above an infinite perfect ground plane.

    A shortening factor of 0.95 is applied (same convention as dipole arm).
    Feed impedance is half that of a dipole in free space.
    """
    lam0_mm = _free_space_wavelength_mm(freq_ghz)
    shortening = 0.95
    element_length_mm = shortening * lam0_mm / 4.0
    ground_plane_min_radius_mm = lam0_mm / 4.0         # λ/4 minimum ground radius

    return {
        "element_length_mm": round(element_length_mm, 3),
        "free_space_wavelength_mm": round(lam0_mm, 3),
        "shortening_factor": shortening,
        "ground_plane_min_radius_mm": round(ground_plane_min_radius_mm, 3),
        "resonant_feed_impedance_ohm": 36.5,           # ~73/2 above perfect ground
        "typical_gain_dbi": 5.15,                      # 3 dB above dipole (image theory)
        "typical_bandwidth_vswr2_pct": 12.0,
        "polarisation": "linear (vertical above ground)",
        "radiation_pattern": "omnidirectional (hemispherical above ground)",
    }


def _patch_effective_er(er: float, h_mm: float, W_mm: float) -> float:
    """Effective dielectric constant for rectangular microstrip patch."""
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / W_mm) ** (-0.5)


def _patch_delta_L(er_eff: float, h_mm: float, W_mm: float) -> float:
    """Fringing field extension at each radiating edge (Hammerstad formula)."""
    return (
        0.412 * h_mm
        * (er_eff + 0.3) * (W_mm / h_mm + 0.264)
        / ((er_eff - 0.258) * (W_mm / h_mm + 0.8))
    )


def _calc_patch(freq_ghz: float, er: float, h_mm: float) -> Dict[str, Any]:
    """
    Rectangular microstrip patch — edge-fed, TM010 mode.

    Width W is chosen for good radiation efficiency.
    Length L is corrected for fringing fields using the Hammerstad extension.
    """
    lam0_mm = _free_space_wavelength_mm(freq_ghz)
    f_hz = freq_ghz * 1e9

    # Width: optimised for radiation efficiency (avoids surface wave excitation)
    W_mm = (C0 / (2.0 * f_hz)) * math.sqrt(2.0 / (er + 1.0)) * 1e3

    er_eff = _patch_effective_er(er, h_mm, W_mm)
    dL_mm = _patch_delta_L(er_eff, h_mm, W_mm)

    # Physical length (fringing-corrected)
    L_mm = (C0 / (2.0 * f_hz * math.sqrt(er_eff))) * 1e3 - 2.0 * dL_mm

    # Feed point inset for 50 Ω match (approximate formula from Bahl & Trivedi)
    # R_edge ≈ 90 * er^2 / (er-1) * (L/W)^2   — simplified
    R_edge_ohm = 90.0 * er**2 / (er - 1.0) * (L_mm / W_mm) ** 2
    inset_mm = (L_mm / math.pi) * math.acos(math.sqrt(50.0 / R_edge_ohm)) if R_edge_ohm > 50 else None

    return {
        "patch_width_mm": round(W_mm, 3),
        "patch_length_mm": round(L_mm, 3),
        "fringing_extension_dL_mm": round(dL_mm, 3),
        "effective_er": round(er_eff, 4),
        "free_space_wavelength_mm": round(lam0_mm, 3),
        "edge_feed_impedance_ohm": round(R_edge_ohm, 1),
        "inset_feed_depth_50ohm_mm": round(inset_mm, 3) if inset_mm is not None else None,
        "typical_gain_dbi": 6.5,                        # 5–8 dBi typical range
        "typical_bandwidth_vswr2_pct": 3.5,             # ~2–5 % for thin substrate
        "polarisation": "linear (broadside)",
        "radiation_pattern": "broadside, ~65° half-power beamwidth",
    }


def _calc_pifa(freq_ghz: float, er: float = 1.0, h_antenna_mm: float = 6.0) -> Dict[str, Any]:
    """
    Planar inverted-F antenna — simplified path-length model.

    The PIFA resonates when the total electrical path from open end to short
    (L + W - Ws) ≈ λ/4.  This function assumes a fixed aspect ratio
    (W = 0.6 * L_total, Ws = 2 mm shorting strip) and solves for L.

    Because PIFA geometry is highly interactive, these numbers serve only as a
    PCB layout starting point; EM optimisation is mandatory.

    Parameters
    ----------
    h_antenna_mm : float
        Height of PIFA element above ground plane (mm).  Typical: 4–10 mm.
    """
    lam0_mm = _free_space_wavelength_mm(freq_ghz)
    # For a PIFA above ground, the resonant path ≈ λ/4 in free space
    # (the ground plane provides the image; er of the surrounding medium is ~1)
    target_path_mm = lam0_mm / 4.0

    # Shorting strip width (fixed heuristic)
    Ws_mm = 2.0

    # Solve L from: L + 0.6*L - Ws = target_path  →  1.6*L = target_path + Ws
    L_mm = (target_path_mm + Ws_mm) / 1.6
    W_mm = 0.6 * L_mm
    total_path_mm = L_mm + W_mm - Ws_mm

    # Matching: PIFA feed impedance tunable via shorting and feed positions
    return {
        "element_length_mm": round(L_mm, 3),
        "element_width_mm": round(W_mm, 3),
        "height_above_ground_mm": round(h_antenna_mm, 3),
        "shorting_strip_width_mm": Ws_mm,
        "resonant_path_mm": round(total_path_mm, 3),
        "free_space_wavelength_mm": round(lam0_mm, 3),
        "target_quarter_wave_mm": round(target_path_mm, 3),
        "typical_feed_impedance_ohm": 50.0,             # tunable by feed/short position
        "typical_gain_dbi": 2.0,                        # 1–3 dBi depending on ground plane
        "typical_bandwidth_vswr2_pct": 10.0,            # 5–15 % depending on h and ground
        "polarisation": "linear (complex, depends on ground shape)",
        "radiation_pattern": "quasi-omnidirectional (tilted, influenced by ground plane)",
    }


# ---------------------------------------------------------------------------
# Warnings and recommendations
# ---------------------------------------------------------------------------

def _build_warnings(
    antenna_type: str,
    freq_ghz: float,
    er: float,
    h_mm: float,
    substrate: str,
    results: Dict[str, Any],
) -> list[str]:
    warnings = []

    if antenna_type == "patch":
        if h_mm / (_free_space_wavelength_mm(freq_ghz)) > 0.05:
            warnings.append(
                "Substrate height is relatively thick (>5 % λ0); surface wave excitation "
                "may reduce radiation efficiency."
            )
        if substrate.upper() == "FR4" and freq_ghz > 3.0:
            warnings.append(
                "FR4 dielectric loss (tan δ ≈ 0.02) significantly degrades patch efficiency "
                "above 3 GHz; consider Rogers/Taconic."
            )
        inset = results.get("inset_feed_depth_50ohm_mm")
        if inset is None:
            warnings.append(
                "Edge feed impedance is below 50 Ω; inset feed depth cannot be computed. "
                "Use a matching network or transformer feed."
            )
        elif inset > results.get("patch_length_mm", 0) * 0.4:
            warnings.append(
                "Required inset depth exceeds 40 % of patch length; consider a coupled "
                "feed, probe feed, or matching network instead."
            )

    if antenna_type == "pifa":
        warnings.append(
            "PIFA dimensions are highly sensitive to ground plane size and nearby components. "
            "Always optimise with EM simulation."
        )
        if freq_ghz > 5.0:
            warnings.append(
                "PIFA height and footprint become impractically small above 5 GHz; "
                "consider a PCB patch or chip antenna instead."
            )

    if antenna_type == "monopole":
        if results.get("ground_plane_min_radius_mm", 0) > 50:
            warnings.append(
                "Required minimum ground plane radius exceeds 50 mm. "
                "A finite, asymmetric ground plane will affect pattern and feed impedance."
            )

    if freq_ghz < 0.1:
        warnings.append("Below 100 MHz: antenna dimensions will be very large; consider a loading coil or whip.")

    return warnings


def _build_recommendations(antenna_type: str, freq_ghz: float, results: Dict[str, Any]) -> list[str]:
    recs = []

    common = [
        "Verify final dimensions with EM simulation (HFSS, CST, OpenEMS, or QUCS-S).",
        "Use a VNA to measure S11 after fabrication and tune if needed.",
    ]

    if antenna_type == "dipole":
        recs += [
            "Use a balun (1:1) at the feed point to suppress common-mode currents on the feedline.",
            "For PCB integration consider a folded dipole to raise feed impedance toward 300 Ω and use a 6:1 balun.",
        ]
    elif antenna_type == "monopole":
        recs += [
            "Provide at least four ground radials each λ/4 long if a solid ground plane is not feasible.",
            "Use a coaxial feed or SMA edge connector; chassis ground must be low-impedance at RF.",
        ]
    elif antenna_type == "patch":
        inset = results.get("inset_feed_depth_50ohm_mm")
        if inset is not None:
            recs.append(f"Inset feed depth for 50 Ω edge match: {inset:.2f} mm (verify with simulation).")
        recs += [
            "Add a microstrip quarter-wave transformer if direct edge feed impedance is not 50 Ω.",
            "Keep the ground plane at least one patch width larger than the patch on all sides.",
            "Consider aperture-coupled or probe-fed designs for better bandwidth isolation.",
        ]
    elif antenna_type == "pifa":
        recs += [
            "Adjust the shorting strip width to tune feed impedance; narrower strip increases impedance.",
            "Move the feed point toward the shorting strip to raise impedance, away from it to lower.",
            "Ground plane dimensions directly affect PIFA resonant frequency; resimulate after any change.",
        ]

    recs += common
    return recs


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

@dataclass
class AntennaResult:
    success: bool
    inputs: Dict[str, Any]
    results: Dict[str, Any]
    warnings: list
    recommendations: list
    next_actions: list
    error: Optional[Dict[str, str]] = None


def calc_antenna(
    antenna_type: str,
    freq_ghz: float,
    er: float = 4.4,
    h_mm: float = 1.6,
    h_antenna_mm: float = 6.0,
    substrate: str = "FR4",
) -> Dict[str, Any]:
    """
    First-pass antenna dimension estimator.

    Parameters
    ----------
    antenna_type : str
        One of: dipole | monopole | patch | pifa
    freq_ghz : float
        Target resonant frequency in GHz.
    er : float
        Substrate relative permittivity (used for patch and pifa).
    h_mm : float
        Substrate thickness in mm (used for patch).
    h_antenna_mm : float
        PIFA element height above ground plane in mm (used for pifa only).
    substrate : str
        Substrate label for guidance messages.

    Returns
    -------
    dict
        Unified result dict (success / inputs / results / warnings / recommendations / next_actions).
    """
    inputs: Dict[str, Any] = {
        "antenna_type": antenna_type,
        "freq_ghz": freq_ghz,
        "er": er,
        "h_mm": h_mm,
        "h_antenna_mm": h_antenna_mm,
        "substrate": substrate,
    }

    try:
        atype = antenna_type.lower().strip()
        if atype not in ANTENNA_TYPES:
            raise ValueError(f"antenna_type must be one of {ANTENNA_TYPES}; got '{antenna_type}'")
        if freq_ghz <= 0:
            raise ValueError("freq_ghz must be > 0")
        if er <= 1.0:
            raise ValueError("er must be > 1.0")
        if h_mm <= 0:
            raise ValueError("h_mm must be > 0")
        if h_antenna_mm <= 0:
            raise ValueError("h_antenna_mm must be > 0")

        if atype == "dipole":
            results = _calc_dipole(freq_ghz)
        elif atype == "monopole":
            results = _calc_monopole(freq_ghz)
        elif atype == "patch":
            results = _calc_patch(freq_ghz, er, h_mm)
        else:  # pifa
            results = _calc_pifa(freq_ghz, er, h_antenna_mm)

        warnings = _build_warnings(atype, freq_ghz, er, h_mm, substrate, results)
        recommendations = _build_recommendations(atype, freq_ghz, results)

        next_actions = [
            "calc_matching",
            "calc_microstrip",   # feedline design
            "calc_cpwg",         # if edge-launch or coax transition needed
            "check_rf_rules",
            "sim_rf",
        ]

        return asdict(AntennaResult(
            success=True,
            inputs=inputs,
            results=results,
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions,
        ))

    except Exception as exc:
        return asdict(AntennaResult(
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
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="First-pass antenna dimension estimator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--type",
        dest="antenna_type",
        required=True,
        choices=ANTENNA_TYPES,
        help="Antenna type",
    )
    p.add_argument("--freq-ghz", type=float, required=True, help="Resonant frequency in GHz")
    p.add_argument("--er", type=float, default=4.4, help="Substrate relative permittivity")
    p.add_argument("--h-mm", type=float, default=1.6, help="Substrate thickness in mm (patch)")
    p.add_argument("--h-antenna-mm", type=float, default=6.0, help="PIFA height above ground in mm")
    p.add_argument("--substrate", type=str, default="FR4", help="Substrate label")
    args = p.parse_args()

    result = calc_antenna(
        antenna_type=args.antenna_type,
        freq_ghz=args.freq_ghz,
        er=args.er,
        h_mm=args.h_mm,
        h_antenna_mm=args.h_antenna_mm,
        substrate=args.substrate,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
