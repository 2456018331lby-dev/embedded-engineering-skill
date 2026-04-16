#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_matching.py

Engineering-grade first-pass matching network calculator
for embedded RF workflows.

Supported network types
- l_network   : two-element L-network (real Rs, RL only; fixed Q)
- pi_network  : three-element π-network (real Rs, RL; user-specified Q)
- t_network   : three-element T-network (real Rs, RL; user-specified Q)
- stub        : single shunt stub (complex load ZL = RL + jXL)

Features
- Outputs both low-pass and high-pass topologies where applicable
- Reports component values in nH / pF at the operating frequency
- Reports electrical and physical stub lengths
- Manufacturability guidance and component value sanity checks
- Unified dict/JSON output contract (matches calc_microstrip / calc_cpwg / calc_antenna)

Notes
- All lumped-element calculations assume ideal components and real source/load
  impedances. Parasitic effects (lead inductance, pad capacitance, Q of physical
  components) must be evaluated with your SPICE or EM solver.
- Stub calculations assume a lossless transmission line with user-supplied
  effective permittivity (er_eff). Run calc_microstrip or calc_cpwg first to
  obtain er_eff, then pass it here for accurate physical stub lengths.
- Final matching network must be validated with a VNA after fabrication.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

C0 = 299_792_458.0  # m/s

NETWORK_TYPES = ("l_network", "pi_network", "t_network", "stub")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _omega(freq_ghz: float) -> float:
    return 2.0 * math.pi * freq_ghz * 1e9


def _l_from_x(X_ohm: float, freq_ghz: float) -> float:
    """Inductance in nH from reactance magnitude and frequency."""
    return abs(X_ohm) / _omega(freq_ghz) * 1e9


def _c_from_x(X_ohm: float, freq_ghz: float) -> float:
    """Capacitance in pF from reactance magnitude and frequency."""
    return 1.0 / (_omega(freq_ghz) * abs(X_ohm)) * 1e12


def _guided_wavelength_mm(freq_ghz: float, er_eff: float) -> float:
    return (C0 / (freq_ghz * 1e9)) * 1e3 / math.sqrt(er_eff)


def _betad_to_mm(betad_rad: float, freq_ghz: float, er_eff: float) -> float:
    """Convert electrical length βd (rad) to physical length (mm)."""
    lam_g = _guided_wavelength_mm(freq_ghz, er_eff)
    return betad_rad / (2.0 * math.pi) * lam_g


def _betad_deg(betad_rad: float) -> float:
    return math.degrees(betad_rad)


def _lp_element(X_ohm: float, freq_ghz: float) -> Dict[str, float]:
    """Return an inductor description for a positive reactance."""
    return {"type": "inductor", "X_ohm": round(X_ohm, 3), "L_nH": round(_l_from_x(X_ohm, freq_ghz), 4)}


def _cp_element(X_ohm: float, freq_ghz: float) -> Dict[str, float]:
    """Return a capacitor description for a (positive) reactance magnitude."""
    return {"type": "capacitor", "X_ohm": round(X_ohm, 3), "C_pF": round(_c_from_x(X_ohm, freq_ghz), 4)}


# ---------------------------------------------------------------------------
# L-network
# ---------------------------------------------------------------------------

def _solve_l_network(
    Rs: float, RL: float, freq_ghz: float
) -> Dict[str, Any]:
    """
    Two-element L-network. Works for real Rs ≠ RL only.

    Q is fully determined by the impedance ratio:
        Q = sqrt(R_high / R_low − 1)

    Two topologies are returned:
    - low_pass  (series inductor → shunt capacitor, or reversed)
    - high_pass (series capacitor → shunt inductor, or reversed)

    Convention: elements listed in order from source to load.
    """
    if abs(Rs - RL) < 1e-9:
        raise ValueError(
            f"Rs ({Rs} Ω) and RL ({RL} Ω) are equal; L-network provides "
            "no impedance transformation (Q = 0). Use a bypass or add a "
            "series/shunt element for DC blocking / bypassing only."
        )
    if Rs <= 0 or RL <= 0:
        raise ValueError("Rs and RL must be positive real values.")

    R_high = max(Rs, RL)
    R_low = min(Rs, RL)
    Q = math.sqrt(R_high / R_low - 1.0)

    # Reactance magnitudes
    if Rs < RL:
        # Source is low → series element on source side, shunt on load side
        Xs = Q * Rs    # series arm
        Xp = RL / Q    # shunt arm
        lp = {
            "description": "series-L (source) → shunt-C (load)",
            "element_1_series": _lp_element(Xs, freq_ghz),
            "element_2_shunt": _cp_element(Xp, freq_ghz),
        }
        hp = {
            "description": "series-C (source) → shunt-L (load)",
            "element_1_series": _cp_element(Xs, freq_ghz),
            "element_2_shunt": _lp_element(Xp, freq_ghz),
        }
    else:
        # Source is high → shunt element on source side, series on load side
        Xp = Rs / Q    # shunt arm (source side)
        Xs = Q * RL    # series arm (load side)
        lp = {
            "description": "shunt-C (source) → series-L (load)",
            "element_1_shunt": _cp_element(Xp, freq_ghz),
            "element_2_series": _lp_element(Xs, freq_ghz),
        }
        hp = {
            "description": "shunt-L (source) → series-C (load)",
            "element_1_shunt": _lp_element(Xp, freq_ghz),
            "element_2_series": _cp_element(Xs, freq_ghz),
        }

    return {
        "Q": round(Q, 4),
        "R_high_ohm": round(R_high, 3),
        "R_low_ohm": round(R_low, 3),
        "low_pass": lp,
        "high_pass": hp,
    }


# ---------------------------------------------------------------------------
# π-network
# ---------------------------------------------------------------------------

def _solve_pi_network(
    Rs: float, RL: float, freq_ghz: float, Q_target: float
) -> Dict[str, Any]:
    """
    Three-element π-network (shunt → series → shunt).

    A virtual intermediate resistance Rv < min(Rs, RL) is used, derived from
    the user-specified Q_target (which must exceed the minimum Q of an L-network
    for this impedance ratio).

    Topology (low-pass): shunt-C₁ → series-L → shunt-C₂
    Topology (high-pass): shunt-L₁ → series-C → shunt-L₂
    """
    if Rs <= 0 or RL <= 0:
        raise ValueError("Rs and RL must be positive real values.")
    if Q_target <= 0:
        raise ValueError("Q_target must be positive.")

    R_max = max(Rs, RL)
    R_min = min(Rs, RL)
    Q_l_min = math.sqrt(R_max / R_min - 1.0)

    if Q_target <= Q_l_min:
        raise ValueError(
            f"Q_target ({Q_target:.4f}) must be greater than the minimum achievable "
            f"Q for an L-network ({Q_l_min:.4f}). Lower Q_target is not possible "
            "with a π-network for this impedance ratio."
        )

    Rv = R_max / (Q_target**2 + 1.0)

    # Rv must be < R_min (guaranteed when Q_target > Q_l_min)
    Q1 = math.sqrt(Rs / Rv - 1.0)
    Q2 = math.sqrt(RL / Rv - 1.0)

    Xp1 = Rs / Q1        # shunt element at source
    Xs = (Q1 + Q2) * Rv  # combined series element
    Xp2 = RL / Q2        # shunt element at load

    lp = {
        "description": "shunt-C₁ (source) → series-L → shunt-C₂ (load)",
        "element_1_shunt_source": _cp_element(Xp1, freq_ghz),
        "element_2_series":       _lp_element(Xs, freq_ghz),
        "element_3_shunt_load":   _cp_element(Xp2, freq_ghz),
    }
    hp = {
        "description": "shunt-L₁ (source) → series-C → shunt-L₂ (load)",
        "element_1_shunt_source": _lp_element(Xp1, freq_ghz),
        "element_2_series":       _cp_element(Xs, freq_ghz),
        "element_3_shunt_load":   _lp_element(Xp2, freq_ghz),
    }

    return {
        "Q_target": round(Q_target, 4),
        "Q_min_l_network": round(Q_l_min, 4),
        "virtual_resistance_Rv_ohm": round(Rv, 4),
        "Q1_source_section": round(Q1, 4),
        "Q2_load_section": round(Q2, 4),
        "low_pass": lp,
        "high_pass": hp,
    }


# ---------------------------------------------------------------------------
# T-network
# ---------------------------------------------------------------------------

def _solve_t_network(
    Rs: float, RL: float, freq_ghz: float, Q_target: float
) -> Dict[str, Any]:
    """
    Three-element T-network (series → shunt → series).

    A virtual intermediate resistance Rv > max(Rs, RL) is used.
    Rv is anchored to max(Rs, RL):
        Rv = max(Rs, RL) × (Q_target² + 1)

    Q_target must be > sqrt(R_max/R_min − 1) (same constraint as π-network).

    Topology (low-pass): series-L₁ → shunt-C → series-L₂
    Topology (high-pass): series-C₁ → shunt-L → series-C₂
    """
    if Rs <= 0 or RL <= 0:
        raise ValueError("Rs and RL must be positive real values.")
    if Q_target <= 0:
        raise ValueError("Q_target must be positive.")

    R_max = max(Rs, RL)
    R_min = min(Rs, RL)
    Q_l_min = math.sqrt(R_max / R_min - 1.0) if R_max != R_min else 0.0

    if R_max != R_min and Q_target <= Q_l_min:
        raise ValueError(
            f"Q_target ({Q_target:.4f}) must be greater than {Q_l_min:.4f} "
            "for this impedance ratio."
        )

    # Virtual resistance for T-network (greater than both terminal Rs, RL)
    Rv = R_max * (Q_target**2 + 1.0)

    Q1 = math.sqrt(Rv / Rs - 1.0)   # left L-section
    Q2 = math.sqrt(Rv / RL - 1.0)   # right L-section

    Xs1 = Q1 * Rs                   # series element (source side)
    Xs2 = Q2 * RL                   # series element (load side)
    Xp  = Rv / (Q1 + Q2)            # shared shunt element

    lp = {
        "description": "series-L₁ (source) → shunt-C → series-L₂ (load)",
        "element_1_series_source": _lp_element(Xs1, freq_ghz),
        "element_2_shunt":         _cp_element(Xp,  freq_ghz),
        "element_3_series_load":   _lp_element(Xs2, freq_ghz),
    }
    hp = {
        "description": "series-C₁ (source) → shunt-L → series-C₂ (load)",
        "element_1_series_source": _cp_element(Xs1, freq_ghz),
        "element_2_shunt":         _lp_element(Xp,  freq_ghz),
        "element_3_series_load":   _cp_element(Xs2, freq_ghz),
    }

    return {
        "Q_target": round(Q_target, 4),
        "Q_min_l_network": round(Q_l_min, 4),
        "virtual_resistance_Rv_ohm": round(Rv, 4),
        "Q1_source_section": round(Q1, 4),
        "Q2_load_section": round(Q2, 4),
        "low_pass": lp,
        "high_pass": hp,
    }


# ---------------------------------------------------------------------------
# Single shunt stub
# ---------------------------------------------------------------------------

def _solve_stub(
    RL: float,
    XL: float,
    Z0: float,
    freq_ghz: float,
    er_eff: float,
) -> Dict[str, Any]:
    """
    Single shunt stub matching for a complex load ZL = RL + jXL.

    Returns two solutions (solution_A, solution_B), each providing
    both short-circuit and open-circuit stub options.

    Algorithm
    ---------
    Normalise: yL = Z0 / ZL = gL + jbL
    Solve for tan(βd) such that g(d) = 1 (unit normalised conductance at
    the stub attachment point):
        (gL² + bL² − gL)·t² − 2·bL·t + (1 − gL) = 0   [t = tan(βd)]
    Then size the stub to cancel the residual susceptance b(d).

    Physical lengths are computed using the guided wavelength at er_eff.
    Run calc_microstrip or calc_cpwg first to obtain er_eff for your feedline.
    """
    if RL <= 0:
        raise ValueError("RL must be > 0 for stub matching.")
    if Z0 <= 0:
        raise ValueError("Z0 must be > 0.")
    if er_eff < 1.0:
        raise ValueError("er_eff must be ≥ 1.0.")

    yL = Z0 / complex(RL, XL)
    gL = yL.real
    bL = yL.imag

    if abs(RL - Z0) < 1e-9 and abs(XL) < 1e-9:
        raise ValueError(
            "Load is already matched (ZL = Z0); no stub network required."
        )

    lam_g = _guided_wavelength_mm(freq_ghz, er_eff)

    # Coefficients of the quadratic in t = tan(βd)
    A = gL**2 + bL**2 - gL
    B = -2.0 * bL
    C = 1.0 - gL

    # Discriminant: always ≥ 0 for gL > 0
    disc = math.sqrt(max(0.0, gL * (bL**2 + (gL - 1.0)**2)))

    if abs(A) < 1e-12:
        # Degenerate case (gL = 1 or |yL|² = gL): one solution from linear eq.
        if abs(B) < 1e-12:
            raise ValueError("Cannot determine t; load may be at a degenerate point.")
        t_vals = [-C / B]
    else:
        t_vals = [(-B + 2.0 * disc) / (2.0 * A),
                  (-B - 2.0 * disc) / (2.0 * A)]

    def _betad(t: float) -> float:
        """Map t = tan(βd) to βd ∈ (0, π)."""
        raw = math.atan(t)
        return raw if raw > 0 else raw + math.pi

    def _b_in(t: float) -> float:
        """Normalised susceptance at distance d (given t = tan(βd))."""
        num = bL + t * (1.0 - bL**2 - gL**2) - bL * t**2
        den = (1.0 - bL * t)**2 + (gL * t)**2
        return num / den

    def _stub_lengths(b_in_val: float) -> Dict[str, Any]:
        """
        Compute short and open stub lengths (βl) to cancel b_in_val.
        Short-circuit stub: Y_sc = −jY0·cot(βl) → cot(βl) = b_in
        Open-circuit stub:  Y_oc = +jY0·tan(βl) → tan(βl) = −b_in
        """
        # Short-circuit stub
        if abs(b_in_val) < 1e-12:
            sc_betl = math.pi / 2.0   # quarter-wave
        else:
            sc_betl = math.atan(1.0 / b_in_val)
            if sc_betl <= 0:
                sc_betl += math.pi

        # Open-circuit stub
        oc_arg = -b_in_val
        if abs(oc_arg) < 1e-12:
            oc_betl = math.pi / 2.0
        else:
            oc_betl = math.atan(oc_arg)
            if oc_betl <= 0:
                oc_betl += math.pi

        return {
            "short_circuit_stub": {
                "electrical_length_deg": round(_betad_deg(sc_betl), 3),
                "physical_length_mm": round(_betad_to_mm(sc_betl, freq_ghz, er_eff), 3),
            },
            "open_circuit_stub": {
                "electrical_length_deg": round(_betad_deg(oc_betl), 3),
                "physical_length_mm": round(_betad_to_mm(oc_betl, freq_ghz, er_eff), 3),
            },
        }

    solutions = []
    for idx, t in enumerate(t_vals):
        bd = _betad(t)
        bi = _b_in(t)
        stubs = _stub_lengths(bi)
        solutions.append({
            "solution": ["A", "B"][idx],
            "distance_from_load": {
                "electrical_length_deg": round(_betad_deg(bd), 3),
                "physical_length_mm":    round(_betad_to_mm(bd, freq_ghz, er_eff), 3),
            },
            "residual_normalised_susceptance_b_in": round(bi, 6),
            "stub_options": stubs,
        })

    return {
        "load_ZL_ohm": {"RL": RL, "XL": XL},
        "Z0_ohm": Z0,
        "normalised_yL": {"gL": round(gL, 6), "bL": round(bL, 6)},
        "er_eff_feedline": er_eff,
        "guided_wavelength_mm": round(lam_g, 3),
        "solutions": solutions,
        "note": (
            "Physical lengths assume er_eff of the feedline TL. "
            "Use calc_microstrip or calc_cpwg to obtain er_eff. "
            "Solution A is generally preferred for shorter d; choose B if A "
            "leads to an impractical stub length."
        ),
    }


# ---------------------------------------------------------------------------
# Warnings and recommendations
# ---------------------------------------------------------------------------

def _build_warnings(
    network_type: str,
    Rs: float,
    RL: float,
    freq_ghz: float,
    result_data: Dict[str, Any],
) -> List[str]:
    warnings: List[str] = []

    if network_type in ("l_network", "pi_network", "t_network"):
        Q = result_data.get("Q") or result_data.get("Q_target", 0)
        if Q and Q > 10:
            warnings.append(
                f"Network Q ({Q:.2f}) is very high; component tolerances and parasitics "
                "will significantly narrow the usable bandwidth."
            )
        if Q and Q < 0.5:
            warnings.append(
                "Network Q is very low; impedance transformation ratio is small. "
                "Verify that a matching network is actually needed."
            )

    if network_type == "l_network":
        Q = result_data.get("Q", 0)
        if Q and Q > 5:
            warnings.append(
                "Consider using a π or T network to split the Q and improve bandwidth."
            )

    if network_type in ("pi_network", "t_network"):
        Rv = result_data.get("virtual_resistance_Rv_ohm", 0)
        if Rv and Rv < 1.0:
            warnings.append(
                f"Virtual resistance Rv = {Rv:.4f} Ω is very low; "
                "component values may become extreme and difficult to source."
            )

    if network_type == "stub":
        for sol in result_data.get("solutions", []):
            for stub_type, stub_data in sol.get("stub_options", {}).items():
                l_mm = stub_data.get("physical_length_mm", 0)
                if l_mm and l_mm > 60:
                    warnings.append(
                        f"Stub physical length ({l_mm:.1f} mm, {stub_type}) is large; "
                        "consider a lumped-element network instead."
                    )

    return warnings


def _build_recommendations(
    network_type: str, freq_ghz: float, Rs: float, RL: float
) -> List[str]:
    recs: List[str] = []

    if network_type == "l_network":
        recs.append(
            "L-network Q is fixed by impedance ratio. Use a π or T network "
            "if you need to control bandwidth independently."
        )
        recs.append(
            "Choose high-pass topology if DC blocking is required, or low-pass "
            "for harmonic suppression."
        )

    elif network_type == "pi_network":
        recs.append(
            "π-network is preferred for PA output matching and inter-stage coupling "
            "where harmonic filtering is beneficial (low-pass form)."
        )
        recs.append(
            "Higher Q_target → narrower bandwidth. Start at Q_min × 1.5 and iterate."
        )

    elif network_type == "t_network":
        recs.append(
            "T-network suits applications where both ports need a series DC-blocking "
            "element (high-pass form) or series filters."
        )
        recs.append(
            "Virtual Rv is larger than both terminal resistances; component values "
            "can be very small at high frequencies — verify against component datasheets."
        )

    elif network_type == "stub":
        recs.append(
            "Run calc_microstrip or calc_cpwg first to obtain er_eff of your feedline "
            "before interpreting physical stub lengths."
        )
        recs.append(
            "Short-circuit stubs are narrowband but avoid radiation from open ends; "
            "open stubs are easier to trim during tuning."
        )
        recs.append(
            "Add a second stub (double-stub) if single-stub solution gives impractical "
            "d or stub length for your layout."
        )

    recs.append(
        "Verify final component values with SPICE (LTspice/Qucs) before layout; "
        "account for component self-resonance and lead parasitics."
    )
    recs.append(
        "After board assembly, measure S11 / S21 with a VNA and tune if needed."
    )
    return recs


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

@dataclass
class MatchingResult:
    success: bool
    inputs: Dict[str, Any]
    results: Dict[str, Any]
    warnings: List[str]
    recommendations: List[str]
    next_actions: List[str]
    error: Optional[Dict[str, str]] = None


def calc_matching(
    network_type: str,
    Rs: float = 50.0,
    RL: float = 50.0,
    XL: float = 0.0,
    Z0: float = 50.0,
    freq_ghz: float = 2.4,
    Q_target: Optional[float] = None,
    er_eff: float = 1.0,
) -> Dict[str, Any]:
    """
    First-pass matching network calculator.

    Parameters
    ----------
    network_type : str
        One of: l_network | pi_network | t_network | stub
    Rs : float
        Source impedance (real, Ω). Used for lumped networks.
    RL : float
        Load resistance (real part, Ω). Required for all types.
    XL : float
        Load reactance (Ω). Used for stub matching only; ignored for lumped networks.
    Z0 : float
        Feedline characteristic impedance (Ω). Used for stub matching.
    freq_ghz : float
        Operating frequency in GHz.
    Q_target : float, optional
        Desired network Q. Required for pi_network and t_network.
        Ignored for l_network (Q is fixed by impedance ratio).
        Ignored for stub.
    er_eff : float
        Effective dielectric constant of the feedline (for stub physical lengths).
        Default 1.0 (free space / air line). Use calc_microstrip or calc_cpwg output.

    Returns
    -------
    dict
        Unified result dict (success / inputs / results / warnings / recommendations / next_actions).
    """
    inputs: Dict[str, Any] = {
        "network_type": network_type,
        "Rs_ohm": Rs,
        "RL_ohm": RL,
        "XL_ohm": XL,
        "Z0_ohm": Z0,
        "freq_ghz": freq_ghz,
        "Q_target": Q_target,
        "er_eff": er_eff,
    }

    try:
        ntype = network_type.lower().strip()
        if ntype not in NETWORK_TYPES:
            raise ValueError(
                f"network_type must be one of {NETWORK_TYPES}; got '{network_type}'"
            )
        if freq_ghz <= 0:
            raise ValueError("freq_ghz must be > 0")
        if RL <= 0:
            raise ValueError("RL must be > 0")

        if ntype == "l_network":
            if Rs <= 0:
                raise ValueError("Rs must be > 0 for l_network")
            results = _solve_l_network(Rs, RL, freq_ghz)

        elif ntype == "pi_network":
            if Rs <= 0:
                raise ValueError("Rs must be > 0 for pi_network")
            if Q_target is None:
                raise ValueError("Q_target is required for pi_network")
            results = _solve_pi_network(Rs, RL, freq_ghz, Q_target)

        elif ntype == "t_network":
            if Rs <= 0:
                raise ValueError("Rs must be > 0 for t_network")
            if Q_target is None:
                raise ValueError("Q_target is required for t_network")
            results = _solve_t_network(Rs, RL, freq_ghz, Q_target)

        else:  # stub
            results = _solve_stub(RL, XL, Z0, freq_ghz, er_eff)

        warnings = _build_warnings(ntype, Rs, RL, freq_ghz, results)
        recommendations = _build_recommendations(ntype, freq_ghz, Rs, RL)

        next_actions = [
            "check_rf_rules",
            "sim_rf",
            "gen_kicad_netlist",
        ]

        return asdict(MatchingResult(
            success=True,
            inputs=inputs,
            results=results,
            warnings=warnings,
            recommendations=recommendations,
            next_actions=next_actions,
        ))

    except Exception as exc:
        return asdict(MatchingResult(
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
        description="Matching network calculator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--type",
        dest="network_type",
        required=True,
        choices=NETWORK_TYPES,
        help="Network topology",
    )
    p.add_argument("--rs",       type=float, default=50.0, help="Source resistance (Ω)")
    p.add_argument("--rl",       type=float, default=50.0, help="Load resistance (Ω)")
    p.add_argument("--xl",       type=float, default=0.0,  help="Load reactance (Ω, for stub)")
    p.add_argument("--z0",       type=float, default=50.0, help="Feedline Z0 (Ω, for stub)")
    p.add_argument("--freq-ghz", type=float, default=2.4,  help="Frequency (GHz)")
    p.add_argument("--q",        type=float, default=None, dest="Q_target",
                   help="Target Q (required for pi_network and t_network)")
    p.add_argument("--er-eff",   type=float, default=1.0,
                   help="Effective permittivity of feedline (for stub physical lengths)")
    args = p.parse_args()

    result = calc_matching(
        network_type=args.network_type,
        Rs=args.rs,
        RL=args.rl,
        XL=args.xl,
        Z0=args.z0,
        freq_ghz=args.freq_ghz,
        Q_target=args.Q_target,
        er_eff=args.er_eff,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
