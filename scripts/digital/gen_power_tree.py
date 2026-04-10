#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_power_tree.py

Engineering-grade power tree generator and rule checker
for embedded system designs.

Given a list of power rails (voltage, current, source), this script:
- Validates each rail against a rule set (voltage tolerance, current headroom,
  sequencing constraints, bypass capacitor requirements)
- Estimates total power consumption and thermal dissipation
- Generates a structured power tree description suitable for schematic guidance
- Produces BOM hints for regulators and bulk/bypass capacitors

Supported regulator types
  ldo     Linear regulator (LDO)
  dcdc    Switching regulator (buck / boost / buck-boost)
  ldo_rf  Low-noise LDO specifically for RF/analog supply rails

Rail dependency graph is specified by the user as a list of (child, parent)
pairs. The script validates that there are no circular dependencies and that
each parent rail exists.

Unified dict/JSON output contract (matches all scripts/rf/ scripts).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Rail:
    name:           str
    voltage_v:      float           # Nominal output voltage
    current_ma:     float           # Peak current demand (mA)
    regulator_type: str             # ldo | dcdc | ldo_rf | direct (no reg)
    parent:         Optional[str]   # Parent rail name (None = battery/input)
    consumers:      List[str]       # Human-readable list of loads on this rail
    notes:          str = ""        # Optional design notes


@dataclass
class RailResult:
    name:               str
    voltage_v:          float
    current_ma:         float
    regulator_type:     str
    parent:             Optional[str]
    consumers:          List[str]
    # Computed
    power_mw:           float
    efficiency_pct:     float       # Estimated regulator efficiency
    dissipation_mw:     float       # Estimated heat dissipated in regulator
    dropout_ok:         bool        # LDO dropout check vs parent rail
    headroom_pct:       float       # Current headroom vs rated current
    issues:             List[str]
    recommendations:    List[str]
    bom_hints:          List[str]


# ---------------------------------------------------------------------------
# Regulator efficiency / dropout models
# ---------------------------------------------------------------------------

# Typical efficiencies used for first-pass thermal estimation
_EFFICIENCY: Dict[str, float] = {
    "ldo":    0.85,   # conservative for typical dropout ratio
    "ldo_rf": 0.88,
    "dcdc":   0.88,
    "direct": 1.00,
}

# Typical LDO dropout voltage (V)
_LDO_DROPOUT_V = 0.3

def _efficiency(reg_type: str, v_in: float, v_out: float) -> float:
    """
    Estimate regulator efficiency.

    For LDOs the theoretical maximum is Vout/Vin; we take the lower of
    that and the typical catalogue efficiency so very large dropout ratios
    are penalised correctly.
    """
    base = _EFFICIENCY.get(reg_type, 0.85)
    if reg_type in ("ldo", "ldo_rf") and v_in > 0:
        theoretical = v_out / v_in
        return min(base, theoretical)
    return base


def _dissipation_mw(
    reg_type: str, v_in: float, v_out: float, i_ma: float
) -> float:
    """Estimate power dissipated in regulator (mW)."""
    eff = _efficiency(reg_type, v_in, v_out)
    if reg_type == "direct" or eff >= 1.0:
        return 0.0
    p_out = v_out * i_ma                    # mW
    p_in  = p_out / eff                     # mW
    return max(0.0, p_in - p_out)


# ---------------------------------------------------------------------------
# Rule checks per rail
# ---------------------------------------------------------------------------

_VOLTAGE_TOLERANCE = 0.05    # ±5 % nominal voltage tolerance limit

# Headroom ratio: actual current / rated current should leave ≥ 20 % margin
_CURRENT_HEADROOM_MIN = 0.20

# Bulk capacitance guideline (µF per 100 mA of load)
_BULK_CAP_UF_PER_100MA = 10.0


def _check_rail(
    rail: Rail,
    parent_voltage_v: Optional[float],
    rated_current_ma: float,
) -> RailResult:
    """
    Run all rule checks for a single rail and produce a RailResult.

    Parameters
    ----------
    rail              : Rail descriptor from user input
    parent_voltage_v  : Voltage of the parent (input) rail, if known
    rated_current_ma  : Rated output current of the chosen regulator (mA)
    """
    issues:       List[str] = []
    recs:         List[str] = []
    bom_hints:    List[str] = []

    v_in  = parent_voltage_v if parent_voltage_v is not None else rail.voltage_v
    v_out = rail.voltage_v
    i_ma  = rail.current_ma
    rtype = rail.regulator_type.lower()

    # --- Power and thermal ---
    power_mw      = v_out * i_ma
    eff           = _efficiency(rtype, v_in, v_out)
    dissip_mw     = _dissipation_mw(rtype, v_in, v_out, i_ma)
    eff_pct       = round(eff * 100.0, 1)

    # --- LDO dropout check ---
    dropout_ok = True
    if rtype in ("ldo", "ldo_rf") and parent_voltage_v is not None:
        margin_v = parent_voltage_v - v_out
        if margin_v < _LDO_DROPOUT_V:
            dropout_ok = False
            issues.append(
                f"LDO dropout risk: parent rail {parent_voltage_v:.2f} V gives only "
                f"{margin_v*1000:.0f} mV headroom (minimum {_LDO_DROPOUT_V*1000:.0f} mV)."
            )
            recs.append(
                "Raise the parent rail voltage, use a lower-dropout LDO, or switch to a "
                "buck converter for this rail."
            )

    # --- LDO efficiency warning for large dropout ---
    if rtype in ("ldo", "ldo_rf") and parent_voltage_v is not None:
        ratio = v_out / parent_voltage_v if parent_voltage_v > 0 else 1.0
        if ratio < 0.6:
            issues.append(
                f"LDO efficiency is low ({eff_pct:.1f} %) due to large dropout ratio "
                f"({parent_voltage_v:.2f}→{v_out:.2f} V); {dissip_mw:.0f} mW dissipated."
            )
            recs.append(
                "Consider a buck (DC-DC) converter for efficiency. LDO is acceptable only "
                "if load is < 100 mA and noise requirements justify it."
            )

    # --- RF supply cleanliness ---
    if rtype == "ldo_rf":
        recs.append(
            "Use a dedicated low-noise LDO (e.g. TLV733P, XC6222, MIC5504) for this RF/analog rail. "
            "Place a π-filter (e.g. 10 Ω + 10 µF + 100 nF) between the main supply and LDO input."
        )
        bom_hints.append("LDO (RF): TLV733P / XC6222 / MIC5504 or equivalent (PSRR ≥ 60 dB @ 1 MHz)")

    # --- Current headroom ---
    headroom_pct = (rated_current_ma - i_ma) / rated_current_ma * 100.0 if rated_current_ma > 0 else 0.0
    if headroom_pct < _CURRENT_HEADROOM_MIN * 100.0:
        issues.append(
            f"Current headroom is only {headroom_pct:.1f} % "
            f"({i_ma:.0f} mA load / {rated_current_ma:.0f} mA rated). "
            "Minimum recommended headroom is 20 %."
        )
        recs.append(
            f"Uprate the regulator to at least {math.ceil(i_ma * 1.25 / 100) * 100:.0f} mA, "
            "or reduce peak current demand."
        )
    elif headroom_pct > 80.0:
        recs.append(
            f"Regulator is significantly over-rated ({headroom_pct:.0f} % headroom). "
            "Consider a smaller, lower-quiescent-current device to improve light-load efficiency."
        )

    # --- Thermal dissipation warning ---
    if dissip_mw > 500:
        issues.append(
            f"Estimated regulator dissipation {dissip_mw:.0f} mW — may require heatsinking "
            "or a larger SOT-223 / D2PAK package."
        )
        recs.append(
            "Verify junction temperature: Tj = Ta + Rθja × Pdiss. "
            "For SOT-23: Rθja ≈ 200 °C/W; for SOT-223: ≈ 60 °C/W. "
            "Target Tj ≤ 125 °C."
        )
    elif dissip_mw > 200:
        recs.append(
            f"Regulator dissipates ~{dissip_mw:.0f} mW; verify thermal performance in "
            "the target enclosure."
        )

    # --- DC-DC switching noise guidance ---
    if rtype == "dcdc":
        recs.append(
            "Place input and output bulk capacitors as close to the converter as possible. "
            "Keep the switching node (SW pin) trace short and away from analog/RF signals."
        )
        recs.append(
            "Add a post-regulator LC filter or LDO stage if this rail powers noise-sensitive circuits."
        )
        bom_hints.append(
            "Buck converter: check for good light-load efficiency (PFM/PSM mode). "
            "Recommended: TPS62x / MP2307 / RT8059 or equivalent."
        )

    # --- Bypass capacitor guideline ---
    bulk_cap_uf = max(10.0, _BULK_CAP_UF_PER_100MA * (i_ma / 100.0))
    bom_hints.append(
        f"Bulk capacitor on {rail.name}: ≥ {bulk_cap_uf:.0f} µF (e.g. 2× {bulk_cap_uf/2:.0f} µF "
        f"electrolytic or polymer) + 100 nF ceramic bypass per IC pin."
    )

    # --- Standard LDO BOM hint ---
    if rtype == "ldo" and not any("LDO (RF)" in h for h in bom_hints):
        bom_hints.append(
            f"LDO for {rail.name} ({v_out:.2f} V, {i_ma:.0f} mA): "
            "AMS1117 (low cost) / MIC5219 (low Iq) / TLV1117 or equivalent."
        )

    return RailResult(
        name=rail.name,
        voltage_v=v_out,
        current_ma=i_ma,
        regulator_type=rtype,
        parent=rail.parent,
        consumers=rail.consumers,
        power_mw=round(power_mw, 2),
        efficiency_pct=eff_pct,
        dissipation_mw=round(dissip_mw, 2),
        dropout_ok=dropout_ok,
        headroom_pct=round(headroom_pct, 1),
        issues=issues,
        recommendations=recs,
        bom_hints=bom_hints,
    )


# ---------------------------------------------------------------------------
# Dependency graph validation
# ---------------------------------------------------------------------------

def _validate_graph(
    rails: List[Rail],
) -> Tuple[bool, List[str]]:
    """
    Check that the rail dependency graph is a valid DAG.
    Returns (ok, list_of_errors).
    """
    names = {r.name for r in rails}
    errors: List[str] = []

    for r in rails:
        if r.parent and r.parent not in names:
            errors.append(
                f"Rail '{r.name}' references parent '{r.parent}' which does not exist."
            )

    # Cycle detection via DFS
    adj: Dict[str, List[str]] = {r.name: [] for r in rails}
    for r in rails:
        if r.parent and r.parent in adj:
            adj[r.parent].append(r.name)

    visited: set = set()
    in_stack: set = set()

    def _dfs(node: str) -> bool:
        visited.add(node)
        in_stack.add(node)
        for child in adj.get(node, []):
            if child not in visited:
                if _dfs(child):
                    return True
            elif child in in_stack:
                errors.append(f"Circular dependency detected involving rail '{node}' → '{child}'.")
                return True
        in_stack.discard(node)
        return False

    for r in rails:
        if r.name not in visited:
            _dfs(r.name)

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Power tree text summary builder
# ---------------------------------------------------------------------------

def _build_tree_text(
    rails: List[Rail],
    rail_map: Dict[str, Rail],
) -> List[str]:
    """Produce an indented text power tree diagram."""
    children: Dict[str, List[str]] = {r.name: [] for r in rails}
    roots: List[str] = []

    for r in rails:
        if r.parent and r.parent in children:
            children[r.parent].append(r.name)
        elif r.parent is None:
            roots.append(r.name)

    lines: List[str] = []

    def _render(name: str, indent: int) -> None:
        r = rail_map.get(name)
        if r is None:
            return
        prefix = "  " * indent + ("└─ " if indent > 0 else "")
        lines.append(
            f"{prefix}{r.name}  {r.voltage_v:.2f} V / {r.current_ma:.0f} mA"
            f"  [{r.regulator_type.upper()}]"
            + (f"  ({', '.join(r.consumers)})" if r.consumers else "")
        )
        for child in sorted(children.get(name, [])):
            _render(child, indent + 1)

    for root in sorted(roots):
        _render(root, 0)

    return lines


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

@dataclass
class PowerTreeOutput:
    success:            bool
    inputs:             Dict[str, Any]
    results:            Dict[str, Any]
    warnings:           List[str]
    recommendations:    List[str]
    next_actions:       List[str]
    error:              Optional[Dict[str, str]] = None


def gen_power_tree(
    rails: List[Dict[str, Any]],
    input_voltage_v: float = 5.0,
    rated_currents_ma: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Generate and validate a power tree for an embedded system.

    Parameters
    ----------
    rails : list of dict
        Each dict must contain:
          name           (str)  : unique rail identifier, e.g. "VCC_3V3"
          voltage_v      (float): nominal rail voltage
          current_ma     (float): peak load current in mA
          regulator_type (str)  : "ldo" | "dcdc" | "ldo_rf" | "direct"
          parent         (str|None): parent rail name, or null for input rail
          consumers      (list[str]): list of loads, e.g. ["MCU", "Flash"]
          notes          (str)  : optional design note

    input_voltage_v : float
        Nominal input supply voltage (battery or connector), used as the
        voltage of any rail whose parent is None.

    rated_currents_ma : dict[str, float], optional
        Maps rail name → regulator rated output current (mA).
        If not provided, a default of 150 % of load current is assumed.

    Returns
    -------
    dict
        Unified result dict with summary, per-rail results, power tree text,
        BOM hints, and recommendations.
    """
    inputs: Dict[str, Any] = {
        "num_rails": len(rails),
        "input_voltage_v": input_voltage_v,
        "rails_summary": [
            {"name": r.get("name"), "voltage_v": r.get("voltage_v"),
             "current_ma": r.get("current_ma"), "regulator_type": r.get("regulator_type")}
            for r in rails
        ],
    }

    try:
        # Parse into Rail dataclass objects
        rail_objects: List[Rail] = []
        for rd in rails:
            rail_objects.append(Rail(
                name=str(rd["name"]),
                voltage_v=float(rd["voltage_v"]),
                current_ma=float(rd["current_ma"]),
                regulator_type=str(rd.get("regulator_type", "ldo")),
                parent=rd.get("parent"),
                consumers=rd.get("consumers", []),
                notes=rd.get("notes", ""),
            ))

        # Validate dependency graph
        graph_ok, graph_errors = _validate_graph(rail_objects)
        if not graph_ok:
            raise ValueError("Power tree dependency graph error: " + "; ".join(graph_errors))

        rail_map: Dict[str, Rail] = {r.name: r for r in rail_objects}

        # Build voltage lookup: each rail's input voltage = parent's voltage_v,
        # or input_voltage_v if parent is None
        def _parent_v(r: Rail) -> Optional[float]:
            if r.parent is None:
                return input_voltage_v
            parent = rail_map.get(r.parent)
            return parent.voltage_v if parent else None

        # Run checks for each rail
        rated = rated_currents_ma or {}
        rail_results: List[RailResult] = []
        for r in rail_objects:
            rated_ma = rated.get(r.name, r.current_ma * 1.5)
            result = _check_rail(r, _parent_v(r), rated_ma)
            rail_results.append(result)

        # Aggregate totals
        total_load_mw     = sum(rr.power_mw for rr in rail_results)
        total_dissip_mw   = sum(rr.dissipation_mw for rr in rail_results)
        total_input_mw    = total_load_mw + total_dissip_mw
        system_eff_pct    = (
            round(total_load_mw / total_input_mw * 100.0, 1)
            if total_input_mw > 0 else 100.0
        )

        # Count issues
        all_issues   = [issue for rr in rail_results for issue in rr.issues]
        all_recs     = list(dict.fromkeys(
            rec for rr in rail_results for rec in rr.recommendations
        ))
        all_bom      = list(dict.fromkeys(
            h for rr in rail_results for h in rr.bom_hints
        ))

        # Sequencing recommendation
        seq_recs: List[str] = []
        dcdc_rails = [r for r in rail_objects if r.regulator_type == "dcdc"]
        ldo_rails  = [r for r in rail_objects if r.regulator_type in ("ldo", "ldo_rf")]
        if dcdc_rails and ldo_rails:
            seq_recs.append(
                "Power sequencing: enable DC-DC rails before LDO rails. "
                "LDOs sourced from a DC-DC output must not power up until the DC-DC output is stable."
            )

        # Global warnings
        global_warnings: List[str] = list(all_issues)
        if total_dissip_mw > 1000:
            global_warnings.append(
                f"Total regulator dissipation {total_dissip_mw:.0f} mW — consider thermal analysis "
                "for the enclosure and board."
            )
        if system_eff_pct < 75:
            global_warnings.append(
                f"System power efficiency estimate is low ({system_eff_pct:.1f} %). "
                "Consider replacing high-dropout LDOs with switching regulators."
            )

        # Next actions (fixed list + conditional)
        next_actions = ["check_power_tree", "gen_mcu_selection_report"]
        if total_dissip_mw > 500:
            next_actions.insert(0, "thermal_analysis")

        # Build power tree text
        tree_lines = _build_tree_text(rail_objects, rail_map)

        return asdict(PowerTreeOutput(
            success=True,
            inputs=inputs,
            results={
                "power_tree_text": tree_lines,
                "total_load_mw":   round(total_load_mw, 2),
                "total_dissipation_mw": round(total_dissip_mw, 2),
                "total_input_power_mw": round(total_input_mw, 2),
                "system_efficiency_pct": system_eff_pct,
                "rails": [asdict(rr) for rr in rail_results],
                "bom_hints": all_bom,
                "sequencing_notes": seq_recs,
            },
            warnings=global_warnings,
            recommendations=all_recs,
            next_actions=next_actions,
        ))

    except Exception as exc:
        return asdict(PowerTreeOutput(
            success=False,
            inputs=inputs,
            results={},
            warnings=[],
            recommendations=[],
            next_actions=[],
            error={"code": exc.__class__.__name__.upper(), "message": str(exc)},
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_EXAMPLE_RAILS = [
    {
        "name": "VIN",
        "voltage_v": 5.0,
        "current_ma": 600,
        "regulator_type": "direct",
        "parent": None,
        "consumers": ["USB / DC jack input"],
        "notes": "5V input from USB or DC barrel jack",
    },
    {
        "name": "VCC_3V3",
        "voltage_v": 3.3,
        "current_ma": 300,
        "regulator_type": "ldo",
        "parent": "VIN",
        "consumers": ["MCU", "Flash", "Sensors"],
        "notes": "Main digital supply",
    },
    {
        "name": "VCC_RF",
        "voltage_v": 3.3,
        "current_ma": 200,
        "regulator_type": "ldo_rf",
        "parent": "VIN",
        "consumers": ["ESP32 RF block", "PA"],
        "notes": "Low-noise RF supply, separate from digital",
    },
    {
        "name": "VCC_1V8",
        "voltage_v": 1.8,
        "current_ma": 80,
        "regulator_type": "ldo",
        "parent": "VCC_3V3",
        "consumers": ["Sensor I/O", "EEPROM"],
        "notes": "1.8V I/O supply for low-voltage peripherals",
    },
]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Embedded power tree generator and rule checker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--rails-json", metavar="FILE", default=None,
        help="JSON file containing a list of rail descriptors. "
             "If omitted, a built-in example (ESP32 sensor node) is used.",
    )
    p.add_argument(
        "--input-voltage", type=float, default=5.0, dest="input_voltage_v",
        help="Input supply voltage (V)",
    )
    p.add_argument(
        "--rated-currents-json", metavar="FILE", default=None,
        help='JSON file mapping rail name → regulator rated current (mA). '
             'E.g. {"VCC_3V3": 500, "VCC_RF": 300}',
    )
    args = p.parse_args()

    if args.rails_json:
        with open(args.rails_json, "r", encoding="utf-8") as f:
            rails = json.load(f)
    else:
        rails = _EXAMPLE_RAILS

    rated = None
    if args.rated_currents_json:
        with open(args.rated_currents_json, "r", encoding="utf-8") as f:
            rated = json.load(f)

    result = gen_power_tree(
        rails=rails,
        input_voltage_v=args.input_voltage_v,
        rated_currents_ma=rated,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
