#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_rf_rules.py

Systematic RF PCB design rule checker for embedded RF workflows.

This script acts as the integration layer for the RF script suite. It consumes
the JSON outputs of calc_microstrip, calc_cpwg, calc_antenna, and calc_matching
(any combination, all optional) together with a small set of raw design
parameters, and runs each design against a registry of engineering rules.

Each rule returns one of three statuses:
  PASS  — within acceptable engineering limits
  WARN  — marginal; review recommended before committing to layout
  FAIL  — outside acceptable limits; must be resolved before fabrication

Features
- 20 rules across five categories: feedline, antenna, matching, layout, substrate
- Accepts upstream script outputs as plain dicts (JSON-compatible)
- Produces a ranked summary ordered by severity
- Unified dict/JSON output contract (matches all four upstream scripts)

Usage modes
- Programmatic: call check_rf_rules(...) with dicts from upstream scripts
- CLI: pass JSON files produced by upstream scripts via --microstrip / --cpwg /
  --antenna / --matching flags, plus raw design params as needed

Notes
- Rules are engineering heuristics derived from IPC-2141, IPC-2249, and standard
  RF PCB practice. They are not a substitute for EM simulation or DRC in EDA.
- A PASS result means the parameter is within typical engineering guidelines,
  not that the design is guaranteed to work. Always verify with a VNA.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Status definitions
# ---------------------------------------------------------------------------

class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"

# Severity order for sorting (FAIL first)
_SEVERITY = {Status.FAIL: 0, Status.WARN: 1, Status.PASS: 2}


@dataclass
class RuleResult:
    rule_id:        str
    category:       str
    status:         str          # "PASS" | "WARN" | "FAIL"
    description:    str          # one-line rule name
    detail:         str          # what was measured / checked
    recommendation: str          # what to do if WARN or FAIL


# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------

def _rule(
    rule_id: str,
    category: str,
    description: str,
    status: Status,
    detail: str,
    recommendation: str,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        category=category,
        status=status.value,
        description=description,
        detail=detail,
        recommendation=recommendation,
    )


def _pass(rule_id, category, description, detail) -> RuleResult:
    return _rule(rule_id, category, description, Status.PASS, detail, "No action required.")


def _warn(rule_id, category, description, detail, rec) -> RuleResult:
    return _rule(rule_id, category, description, Status.WARN, detail, rec)


def _fail(rule_id, category, description, detail, rec) -> RuleResult:
    return _rule(rule_id, category, description, Status.FAIL, detail, rec)


def _skip(rule_id, category, description) -> RuleResult:
    return _rule(
        rule_id, category, description, Status.PASS,
        "Rule skipped — required upstream data not provided.",
        "Run the corresponding calc_* script and pass its output to obtain a real result.",
    )


# ---------------------------------------------------------------------------
# Category A — Feedline rules (microstrip)
# ---------------------------------------------------------------------------

def _rule_ms_impedance(ms: Dict) -> RuleResult:
    rid, cat = "MS-01", "feedline"
    desc = "Microstrip characteristic impedance within 50 Ω ± 10 %"
    z0 = ms.get("results", {}).get("z0_ohm")
    if z0 is None:
        return _skip(rid, cat, desc)
    lo, hi = 45.0, 55.0
    if lo <= z0 <= hi:
        return _pass(rid, cat, desc, f"Z0 = {z0:.2f} Ω (target 50 Ω ± 10 %)")
    if 40.0 <= z0 <= 60.0:
        return _warn(rid, cat, desc,
                     f"Z0 = {z0:.2f} Ω — outside ±10 % but within ±20 %.",
                     "Adjust trace width or substrate stackup to bring Z0 within 45–55 Ω.")
    return _fail(rid, cat, desc,
                 f"Z0 = {z0:.2f} Ω — outside ±20 % of 50 Ω.",
                 "Recalculate trace width with calc_microstrip; verify stackup parameters.")


def _rule_ms_width(ms: Dict) -> RuleResult:
    rid, cat = "MS-02", "feedline"
    desc = "Microstrip trace width above PCB fab minimum"
    r = ms.get("results", {})
    i = ms.get("inputs", {})
    w = r.get("width_mm")
    w_min = i.get("board_capability_min_width_mm", 0.10)
    if w is None:
        return _skip(rid, cat, desc)
    if w >= w_min * 1.5:
        return _pass(rid, cat, desc, f"Width = {w:.4f} mm, fab min = {w_min:.4f} mm (margin ≥ 50 %)")
    if w >= w_min:
        return _warn(rid, cat, desc,
                     f"Width = {w:.4f} mm, fab min = {w_min:.4f} mm (margin < 50 %).",
                     "Confirm with PCB vendor; consider a thinner substrate to widen the trace.")
    return _fail(rid, cat, desc,
                 f"Width = {w:.4f} mm below fab minimum {w_min:.4f} mm.",
                 "Select a thinner substrate or lower-er material to increase the required width.")


def _rule_ms_loss(ms: Dict) -> RuleResult:
    rid, cat = "MS-03", "feedline"
    desc = "Microstrip total insertion loss ≤ 0.5 dB/cm"
    loss = ms.get("results", {}).get("total_loss_db_cm")
    if loss is None:
        return _skip(rid, cat, desc)
    if loss <= 0.3:
        return _pass(rid, cat, desc, f"Estimated loss = {loss:.4f} dB/cm")
    if loss <= 0.5:
        return _warn(rid, cat, desc,
                     f"Estimated loss = {loss:.4f} dB/cm — approaching 0.5 dB/cm limit.",
                     "Keep RF traces short; consider low-loss laminate if trace length > 30 mm.")
    return _fail(rid, cat, desc,
                 f"Estimated loss = {loss:.4f} dB/cm — exceeds 0.5 dB/cm guideline.",
                 "Switch to low-loss substrate (Rogers / Taconic) or shorten the RF path significantly.")


def _rule_ms_fr4_freq(ms: Dict) -> RuleResult:
    rid, cat = "MS-04", "substrate"
    desc = "FR4 substrate suitability for operating frequency"
    sub = ms.get("inputs", {}).get("substrate", "")
    freq = ms.get("inputs", {}).get("freq_ghz")
    if freq is None or sub.upper() != "FR4":
        return _skip(rid, cat, desc)
    if freq <= 3.0:
        return _pass(rid, cat, desc, f"FR4 at {freq:.2f} GHz — within standard guideline (≤ 3 GHz)")
    if freq <= 6.0:
        return _warn(rid, cat, desc,
                     f"FR4 at {freq:.2f} GHz — dielectric loss and Er variation become significant.",
                     "Validate with actual stackup data; consider Rogers 4003C / RO4350B above 5 GHz.")
    return _fail(rid, cat, desc,
                 f"FR4 at {freq:.2f} GHz — not recommended; loss and Er spread will degrade performance.",
                 "Use a low-loss, tightly-specified laminate (Rogers, Taconic, Megtron) above 6 GHz.")


# ---------------------------------------------------------------------------
# Category B — CPWG rules
# ---------------------------------------------------------------------------

def _rule_cpwg_impedance(cpwg: Dict) -> RuleResult:
    rid, cat = "CW-01", "feedline"
    desc = "CPWG characteristic impedance within 50 Ω ± 10 %"
    z0 = cpwg.get("results", {}).get("z0_ohm")
    if z0 is None:
        return _skip(rid, cat, desc)
    lo, hi = 45.0, 55.0
    if lo <= z0 <= hi:
        return _pass(rid, cat, desc, f"CPWG Z0 = {z0:.2f} Ω")
    if 40.0 <= z0 <= 60.0:
        return _warn(rid, cat, desc,
                     f"CPWG Z0 = {z0:.2f} Ω — outside ±10 %.",
                     "Adjust width or gap; re-run calc_cpwg.")
    return _fail(rid, cat, desc,
                 f"CPWG Z0 = {z0:.2f} Ω — outside ±20 %.",
                 "Recalculate CPWG geometry with calc_cpwg; verify stackup parameters with vendor.")


def _rule_cpwg_gap(cpwg: Dict) -> RuleResult:
    rid, cat = "CW-02", "feedline"
    desc = "CPWG gap above PCB fab minimum"
    r = cpwg.get("results", {})
    i = cpwg.get("inputs", {})
    gap = i.get("gap_mm")
    gap_min = i.get("board_capability_min_gap_mm", 0.10)
    if gap is None:
        return _skip(rid, cat, desc)
    if gap >= gap_min * 1.5:
        return _pass(rid, cat, desc, f"Gap = {gap:.4f} mm, fab min = {gap_min:.4f} mm")
    if gap >= gap_min:
        return _warn(rid, cat, desc,
                     f"Gap = {gap:.4f} mm — close to fab minimum {gap_min:.4f} mm.",
                     "Confirm spacing tolerance with PCB vendor; tight gaps increase impedance sensitivity.")
    return _fail(rid, cat, desc,
                 f"Gap = {gap:.4f} mm below fab minimum {gap_min:.4f} mm.",
                 "Widen the gap; accept the Z0 deviation or adjust width to compensate.")


def _rule_cpwg_via_fence(
    cpwg: Dict, via_fence_actual_pitch_mm: Optional[float]
) -> RuleResult:
    rid, cat = "CW-03", "layout"
    desc = "CPWG via fence pitch ≤ λg/20"
    rec_pitch = cpwg.get("results", {}).get("via_fence_pitch_mm")
    if rec_pitch is None:
        return _skip(rid, cat, desc)
    if via_fence_actual_pitch_mm is None:
        return _warn(rid, cat, desc,
                     f"Recommended via fence pitch ≤ {rec_pitch:.3f} mm; actual pitch not provided.",
                     f"Place via fence along CPWG with pitch ≤ {rec_pitch:.3f} mm (λg/20).")
    if via_fence_actual_pitch_mm <= rec_pitch:
        return _pass(rid, cat, desc,
                     f"Actual pitch {via_fence_actual_pitch_mm:.3f} mm ≤ limit {rec_pitch:.3f} mm")
    return _fail(rid, cat, desc,
                 f"Actual pitch {via_fence_actual_pitch_mm:.3f} mm exceeds limit {rec_pitch:.3f} mm.",
                 f"Increase via density to achieve pitch ≤ {rec_pitch:.3f} mm along the CPWG.")


# ---------------------------------------------------------------------------
# Category C — Antenna rules
# ---------------------------------------------------------------------------

def _rule_ant_clearance(
    ant: Dict, clearance_actual_mm: Optional[float]
) -> RuleResult:
    rid, cat = "AN-01", "antenna"
    desc = "Antenna keep-out clearance ≥ λ0/10"
    freq = ant.get("inputs", {}).get("freq_ghz")
    if freq is None:
        return _skip(rid, cat, desc)
    lam0_mm = (299_792_458.0 / (freq * 1e9)) * 1e3
    required_mm = lam0_mm / 10.0
    if clearance_actual_mm is None:
        return _warn(rid, cat, desc,
                     f"Required keep-out ≥ {required_mm:.1f} mm (λ0/10 at {freq:.2f} GHz); "
                     f"actual clearance not provided.",
                     f"Ensure no metal, components, or traces within {required_mm:.1f} mm of the "
                     f"antenna radiating element.")
    if clearance_actual_mm >= required_mm:
        return _pass(rid, cat, desc,
                     f"Clearance {clearance_actual_mm:.1f} mm ≥ required {required_mm:.1f} mm")
    return _fail(rid, cat, desc,
                 f"Clearance {clearance_actual_mm:.1f} mm < required {required_mm:.1f} mm.",
                 f"Increase antenna keep-out zone to at least {required_mm:.1f} mm.")


def _rule_ant_patch_bandwidth(ant: Dict) -> RuleResult:
    rid, cat = "AN-02", "antenna"
    desc = "Patch antenna bandwidth adequate for application (> 2 %)"
    atype = ant.get("inputs", {}).get("antenna_type", "")
    bw = ant.get("results", {}).get("typical_bandwidth_vswr2_pct")
    if atype.lower() != "patch" or bw is None:
        return _skip(rid, cat, desc)
    if bw >= 5.0:
        return _pass(rid, cat, desc, f"Estimated bandwidth ≈ {bw:.1f} % (VSWR ≤ 2)")
    if bw >= 2.0:
        return _warn(rid, cat, desc,
                     f"Estimated bandwidth ≈ {bw:.1f} % — tight for wide-channel protocols (e.g. 802.11).",
                     "Consider aperture-coupled feed, stacked patch, or slots to broaden bandwidth.")
    return _fail(rid, cat, desc,
                 f"Estimated bandwidth ≈ {bw:.1f} % — likely insufficient.",
                 "Use a thicker substrate, lower-er material, or a different antenna type.")


def _rule_ant_pifa_sim(ant: Dict) -> RuleResult:
    rid, cat = "AN-03", "antenna"
    desc = "PIFA design validated by EM simulation (mandatory)"
    atype = ant.get("inputs", {}).get("antenna_type", "")
    if atype.lower() != "pifa":
        return _skip(rid, cat, desc)
    # PIFA always requires simulation — this rule is always a reminder
    return _warn(rid, cat, desc,
                 "PIFA geometry is highly sensitive to ground plane and nearby components.",
                 "Run full EM simulation (HFSS / CST / OpenEMS) before committing to layout. "
                 "calc_antenna provides a starting point only.")


def _rule_ant_monopole_ground(ant: Dict) -> RuleResult:
    rid, cat = "AN-04", "antenna"
    desc = "Monopole ground plane radius ≥ λ/4"
    atype = ant.get("inputs", {}).get("antenna_type", "")
    gp_required = ant.get("results", {}).get("ground_plane_min_radius_mm")
    if atype.lower() != "monopole" or gp_required is None:
        return _skip(rid, cat, desc)
    # We can only warn; actual ground plane size is a layout parameter
    return _warn(rid, cat, desc,
                 f"Required minimum ground plane radius: {gp_required:.1f} mm. "
                 f"Actual size depends on your PCB layout.",
                 f"Verify PCB ground plane extends at least {gp_required:.1f} mm from the monopole base, "
                 f"or add at least four radials of the same length.")


# ---------------------------------------------------------------------------
# Category D — Matching network rules
# ---------------------------------------------------------------------------

def _rule_match_q(matching: Dict) -> RuleResult:
    rid, cat = "MN-01", "matching"
    desc = "Matching network Q ≤ 10 (component tolerance manageable)"
    r = matching.get("results", {})
    Q = r.get("Q") or r.get("Q_target")
    ntype = matching.get("inputs", {}).get("network_type", "")
    if Q is None or ntype == "stub":
        return _skip(rid, cat, desc)
    if Q <= 5.0:
        return _pass(rid, cat, desc, f"Network Q = {Q:.2f}")
    if Q <= 10.0:
        return _warn(rid, cat, desc,
                     f"Network Q = {Q:.2f} — component tolerances will noticeably shift centre frequency.",
                     "Use 1 % tolerance components; model parasitics in SPICE before layout.")
    return _fail(rid, cat, desc,
                 f"Network Q = {Q:.2f} — very high; component tolerance and parasitics are critical.",
                 "Split Q across a π or T network; reduce Q_target; or use a distributed (stub) solution.")


def _rule_match_component_values(matching: Dict) -> RuleResult:
    rid, cat = "MN-02", "matching"
    desc = "Matching network component values within standard sourcing range"
    r = matching.get("results", {})
    ntype = matching.get("inputs", {}).get("network_type", "")
    if ntype == "stub":
        return _skip(rid, cat, desc)

    issues = []
    def _check_element(elem: Dict, label: str) -> None:
        if elem.get("type") == "inductor":
            L = elem.get("L_nH", 0)
            if L < 0.3:
                issues.append(f"{label}: L = {L:.4f} nH — below typical 0402 minimum (~0.3 nH).")
            elif L > 100.0:
                issues.append(f"{label}: L = {L:.2f} nH — very large; check self-resonance frequency.")
        elif elem.get("type") == "capacitor":
            C = elem.get("C_pF", 0)
            if C < 0.1:
                issues.append(f"{label}: C = {C:.4f} pF — below typical 0402 minimum (~0.1 pF).")
            elif C > 1000.0:
                issues.append(f"{label}: C = {C:.2f} pF — unusually large for RF matching.")

    # Walk all topology dicts (low_pass / high_pass) and their elements
    for topo_key in ("low_pass", "high_pass"):
        topo = r.get(topo_key, {})
        for k, v in topo.items():
            if isinstance(v, dict) and "type" in v:
                _check_element(v, f"{topo_key}/{k}")

    if not issues:
        return _pass(rid, cat, desc, "All lumped component values within standard sourcing range.")
    if len(issues) <= 1:
        return _warn(rid, cat, desc,
                     " | ".join(issues),
                     "Verify component availability and self-resonance; consider a distributed alternative.")
    return _fail(rid, cat, desc,
                 " | ".join(issues),
                 "Multiple component values are out of sourcing range. "
                 "Reconsider network topology or frequency; use stub matching for distributed solution.")


# ---------------------------------------------------------------------------
# Category E — Layout and isolation rules (raw parameters)
# ---------------------------------------------------------------------------

def _rule_rf_digital_isolation(
    rf_digital_clearance_mm: Optional[float],
    freq_ghz: Optional[float],
) -> RuleResult:
    rid, cat = "LO-01", "layout"
    desc = "RF-to-digital signal isolation clearance ≥ 3 × substrate height (h)"
    if rf_digital_clearance_mm is None:
        return _warn(rid, cat, desc,
                     "RF-to-digital clearance not provided.",
                     "Keep digital traces and clocks at least 3× substrate height (typically ≥ 5 mm) "
                     "from any RF signal trace; use a ground guard trace between domains.")
    # Rough benchmark: at least 5 mm for most FR4 boards
    limit = 5.0
    if rf_digital_clearance_mm >= limit:
        return _pass(rid, cat, desc,
                     f"Clearance = {rf_digital_clearance_mm:.1f} mm ≥ {limit:.0f} mm guideline.")
    return _warn(rid, cat, desc,
                 f"Clearance = {rf_digital_clearance_mm:.1f} mm < {limit:.0f} mm guideline.",
                 "Increase separation or add a solid ground guard between RF and digital domains.")


def _rule_return_path(has_solid_ground_plane: Optional[bool]) -> RuleResult:
    rid, cat = "LO-02", "layout"
    desc = "Continuous ground reference plane beneath all RF traces"
    if has_solid_ground_plane is None:
        return _warn(rid, cat, desc,
                     "Ground plane continuity not confirmed.",
                     "Ensure a continuous copper pour with no slots or splits beneath all RF traces. "
                     "Any discontinuity in the reference plane will affect impedance and radiation.")
    if has_solid_ground_plane:
        return _pass(rid, cat, desc, "Solid ground plane confirmed.")
    return _fail(rid, cat, desc,
                 "Ground plane has splits or slots beneath RF traces.",
                 "Remove all splits and slots under RF signal paths; re-route any crossing traces "
                 "to a different layer without disturbing the ground plane.")


def _rule_connector_transition(
    uses_rf_connector: Optional[bool],
    connector_type: Optional[str],
) -> RuleResult:
    rid, cat = "LO-03", "layout"
    desc = "RF connector transition properly managed"
    if uses_rf_connector is None:
        return _skip(rid, cat, desc)
    if not uses_rf_connector:
        return _pass(rid, cat, desc, "No RF connector used in this design.")
    ctype = (connector_type or "").upper()
    if ctype in ("SMA", "U.FL", "MMCX", "SMP"):
        return _warn(rid, cat, desc,
                     f"RF connector type: {connector_type}. Transition geometry must be verified.",
                     f"Use a CPWG-to-{connector_type} footprint with matched via geometry; "
                     f"verify S11 of the transition with EM simulation or TDR measurement.")
    return _warn(rid, cat, desc,
                 f"RF connector type '{connector_type}' specified — verify it is rated for this frequency.",
                 "Confirm connector bandwidth specification; use manufacturer's recommended PCB footprint.")


def _rule_layer_stackup(
    freq_ghz: Optional[float],
    num_layers: Optional[int],
    substrate: Optional[str],
) -> RuleResult:
    rid, cat = "LO-04", "layout"
    desc = "PCB layer stackup appropriate for operating frequency"
    if freq_ghz is None or num_layers is None:
        return _skip(rid, cat, desc)
    sub = (substrate or "FR4").upper()
    if num_layers < 2:
        return _fail(rid, cat, desc,
                     "Single-layer PCB detected — no dedicated ground plane.",
                     "Use at least a 2-layer PCB with layer 2 as a solid ground plane for any RF design.")
    if freq_ghz > 6.0 and sub == "FR4":
        return _fail(rid, cat, desc,
                     f"{num_layers}-layer FR4 at {freq_ghz:.2f} GHz — substrate loss is unacceptable.",
                     "Switch to a low-loss laminate (Rogers, Taconic, Megtron) for >6 GHz designs.")
    if freq_ghz > 3.0 and sub == "FR4" and num_layers < 4:
        return _warn(rid, cat, desc,
                     f"{num_layers}-layer FR4 at {freq_ghz:.2f} GHz.",
                     "A 4-layer stackup (signal / GND / PWR / signal) provides better isolation "
                     "and a tighter reference plane; consider it for production designs above 3 GHz.")
    return _pass(rid, cat, desc,
                 f"{num_layers}-layer {sub} at {freq_ghz:.2f} GHz — within acceptable guidelines.")


def _rule_decoupling_proximity(
    rf_ic_decoupling_distance_mm: Optional[float],
) -> RuleResult:
    rid, cat = "LO-05", "layout"
    desc = "RF IC decoupling capacitors placed within 0.5 mm of supply pins"
    if rf_ic_decoupling_distance_mm is None:
        return _warn(rid, cat, desc,
                     "Decoupling capacitor placement distance not provided.",
                     "Place all RF IC supply decoupling capacitors within 0.5 mm of the supply pin; "
                     "use 100 nF + 10 pF in parallel; connect to ground via a short, wide trace.")
    if rf_ic_decoupling_distance_mm <= 0.5:
        return _pass(rid, cat, desc,
                     f"Decoupling distance = {rf_ic_decoupling_distance_mm:.2f} mm ≤ 0.5 mm.")
    if rf_ic_decoupling_distance_mm <= 1.5:
        return _warn(rid, cat, desc,
                     f"Decoupling distance = {rf_ic_decoupling_distance_mm:.2f} mm — slightly large.",
                     "Move decoupling capacitors closer to the supply pin; parasitic inductance "
                     "of the trace reduces their effectiveness at RF frequencies.")
    return _fail(rid, cat, desc,
                 f"Decoupling distance = {rf_ic_decoupling_distance_mm:.2f} mm — too far from pin.",
                 "Relocate decoupling capacitors to within 0.5 mm of the supply pin.")


# ---------------------------------------------------------------------------
# Main rule runner
# ---------------------------------------------------------------------------

def _run_all_rules(
    microstrip_result:          Optional[Dict],
    cpwg_result:                Optional[Dict],
    antenna_result:             Optional[Dict],
    matching_result:            Optional[Dict],
    via_fence_actual_pitch_mm:  Optional[float],
    antenna_clearance_mm:       Optional[float],
    rf_digital_clearance_mm:    Optional[float],
    has_solid_ground_plane:     Optional[bool],
    uses_rf_connector:          Optional[bool],
    connector_type:             Optional[str],
    freq_ghz:                   Optional[float],
    num_layers:                 Optional[int],
    substrate:                  Optional[str],
    rf_ic_decoupling_distance_mm: Optional[float],
) -> List[RuleResult]:
    ms   = microstrip_result or {}
    cpwg = cpwg_result       or {}
    ant  = antenna_result    or {}
    mat  = matching_result   or {}

    # Resolve freq_ghz: prefer explicit param, fall back to upstream inputs
    if freq_ghz is None:
        for src in (ms, cpwg, ant, mat):
            freq_ghz = src.get("inputs", {}).get("freq_ghz")
            if freq_ghz:
                break
    if substrate is None:
        for src in (ms, cpwg):
            substrate = src.get("inputs", {}).get("substrate")
            if substrate:
                break

    rules: List[RuleResult] = [
        # Microstrip feedline
        _rule_ms_impedance(ms),
        _rule_ms_width(ms),
        _rule_ms_loss(ms),
        _rule_ms_fr4_freq(ms),
        # CPWG
        _rule_cpwg_impedance(cpwg),
        _rule_cpwg_gap(cpwg),
        _rule_cpwg_via_fence(cpwg, via_fence_actual_pitch_mm),
        # Antenna
        _rule_ant_clearance(ant, antenna_clearance_mm),
        _rule_ant_patch_bandwidth(ant),
        _rule_ant_pifa_sim(ant),
        _rule_ant_monopole_ground(ant),
        # Matching
        _rule_match_q(mat),
        _rule_match_component_values(mat),
        # Layout
        _rule_rf_digital_isolation(rf_digital_clearance_mm, freq_ghz),
        _rule_return_path(has_solid_ground_plane),
        _rule_connector_transition(uses_rf_connector, connector_type),
        _rule_layer_stackup(freq_ghz, num_layers, substrate),
        _rule_decoupling_proximity(rf_ic_decoupling_distance_mm),
    ]

    # Sort: FAIL → WARN → PASS
    rules.sort(key=lambda r: _SEVERITY[Status(r.status)])
    return rules


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(rules: List[RuleResult]) -> Dict[str, Any]:
    counts = {s.value: 0 for s in Status}
    for r in rules:
        counts[r.status] += 1

    if counts["FAIL"] > 0:
        overall = "FAIL"
    elif counts["WARN"] > 0:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "overall_status": overall,
        "total_rules": len(rules),
        "pass_count":  counts["PASS"],
        "warn_count":  counts["WARN"],
        "fail_count":  counts["FAIL"],
    }


# ---------------------------------------------------------------------------
# Recommendations and next actions
# ---------------------------------------------------------------------------

def _build_recommendations(rules: List[RuleResult], overall: str) -> List[str]:
    recs = []
    if overall == "FAIL":
        recs.append("Resolve all FAIL items before committing to PCB layout or ordering fabrication.")
    if any(r.status == "WARN" for r in rules):
        recs.append("Review all WARN items; most require a layout decision rather than a recalculation.")
    recs.append(
        "After resolving flagged items, re-run check_rf_rules with the updated upstream script outputs."
    )
    recs.append(
        "Use a VNA to measure S11 / S21 on the fabricated board and compare against simulation."
    )
    recs.append(
        "For production designs, commission a PCB vendor impedance coupon test on the same panel."
    )
    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class RFRulesResult:
    success:         bool
    inputs:          Dict[str, Any]
    summary:         Dict[str, Any]
    rules:           List[Dict[str, Any]]
    warnings:        List[str]
    recommendations: List[str]
    next_actions:    List[str]
    error:           Optional[Dict[str, str]] = None


def check_rf_rules(
    microstrip_result:              Optional[Dict] = None,
    cpwg_result:                    Optional[Dict] = None,
    antenna_result:                 Optional[Dict] = None,
    matching_result:                Optional[Dict] = None,
    via_fence_actual_pitch_mm:      Optional[float] = None,
    antenna_clearance_mm:           Optional[float] = None,
    rf_digital_clearance_mm:        Optional[float] = None,
    has_solid_ground_plane:         Optional[bool]  = None,
    uses_rf_connector:              Optional[bool]  = None,
    connector_type:                 Optional[str]   = None,
    freq_ghz:                       Optional[float] = None,
    num_layers:                     Optional[int]   = None,
    substrate:                      Optional[str]   = None,
    rf_ic_decoupling_distance_mm:   Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run the full RF PCB rule check.

    All parameters are optional. Pass whichever upstream script outputs and
    layout parameters are available; rules requiring missing data are skipped
    and reported as informational PASS entries with a note.

    Parameters
    ----------
    microstrip_result / cpwg_result / antenna_result / matching_result : dict
        Direct output dicts from the corresponding calc_* scripts.
    via_fence_actual_pitch_mm : float
        Actual via fence pitch used in the layout (mm).
    antenna_clearance_mm : float
        Physical clearance from antenna radiating element to nearest obstacle (mm).
    rf_digital_clearance_mm : float
        Minimum clearance between RF signal traces and digital/clock traces (mm).
    has_solid_ground_plane : bool
        True if the reference layer under RF traces is a continuous copper pour.
    uses_rf_connector : bool
        True if the design includes an RF connector (SMA, U.FL, etc.).
    connector_type : str
        Label for the RF connector type (e.g. "SMA", "U.FL").
    freq_ghz : float
        Operating frequency (GHz). Inferred from upstream results if not provided.
    num_layers : int
        Total number of PCB copper layers.
    substrate : str
        Substrate label (e.g. "FR4"). Inferred from upstream results if not provided.
    rf_ic_decoupling_distance_mm : float
        Distance from RF IC supply pins to nearest decoupling capacitor (mm).

    Returns
    -------
    dict
        Unified result dict with summary, per-rule results, and recommendations.
    """
    inputs: Dict[str, Any] = {
        "has_microstrip_result": microstrip_result is not None,
        "has_cpwg_result":       cpwg_result       is not None,
        "has_antenna_result":    antenna_result     is not None,
        "has_matching_result":   matching_result    is not None,
        "via_fence_actual_pitch_mm":    via_fence_actual_pitch_mm,
        "antenna_clearance_mm":         antenna_clearance_mm,
        "rf_digital_clearance_mm":      rf_digital_clearance_mm,
        "has_solid_ground_plane":       has_solid_ground_plane,
        "uses_rf_connector":            uses_rf_connector,
        "connector_type":               connector_type,
        "freq_ghz":                     freq_ghz,
        "num_layers":                   num_layers,
        "substrate":                    substrate,
        "rf_ic_decoupling_distance_mm": rf_ic_decoupling_distance_mm,
    }

    try:
        rules = _run_all_rules(
            microstrip_result, cpwg_result, antenna_result, matching_result,
            via_fence_actual_pitch_mm, antenna_clearance_mm,
            rf_digital_clearance_mm, has_solid_ground_plane,
            uses_rf_connector, connector_type,
            freq_ghz, num_layers, substrate,
            rf_ic_decoupling_distance_mm,
        )

        summary = _build_summary(rules)
        overall = summary["overall_status"]
        recommendations = _build_recommendations(rules, overall)

        # warnings: collect FAIL and WARN detail strings for the top-level field
        # (mirrors the style of upstream scripts)
        top_warnings = [
            f"[{r.rule_id}] {r.description}: {r.detail}"
            for r in rules if r.status in ("FAIL", "WARN")
        ]

        next_actions: List[str] = []
        if overall in ("FAIL", "WARN"):
            next_actions += ["re-run calc_* scripts with corrected parameters",
                             "update PCB layout to resolve flagged items",
                             "re-run check_rf_rules after corrections"]
        next_actions += ["sim_rf", "gen_kicad_netlist"]

        return asdict(RFRulesResult(
            success=True,
            inputs=inputs,
            summary=summary,
            rules=[asdict(r) for r in rules],
            warnings=top_warnings,
            recommendations=recommendations,
            next_actions=next_actions,
        ))

    except Exception as exc:
        return asdict(RFRulesResult(
            success=False,
            inputs=inputs,
            summary={},
            rules=[],
            warnings=[],
            recommendations=[],
            next_actions=[],
            error={"code": exc.__class__.__name__.upper(), "message": str(exc)},
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="RF PCB design rule checker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--microstrip", metavar="FILE",
                   help="JSON output file from calc_microstrip")
    p.add_argument("--cpwg",       metavar="FILE",
                   help="JSON output file from calc_cpwg")
    p.add_argument("--antenna",    metavar="FILE",
                   help="JSON output file from calc_antenna")
    p.add_argument("--matching",   metavar="FILE",
                   help="JSON output file from calc_matching")
    p.add_argument("--via-fence-pitch-mm",      type=float, default=None,
                   help="Actual via fence pitch used in layout (mm)")
    p.add_argument("--antenna-clearance-mm",    type=float, default=None,
                   help="Antenna keep-out clearance in layout (mm)")
    p.add_argument("--rf-digital-clearance-mm", type=float, default=None,
                   help="RF-to-digital trace clearance (mm)")
    p.add_argument("--solid-ground-plane",      action="store_true", default=None,
                   help="Confirm continuous ground plane under RF traces")
    p.add_argument("--no-solid-ground-plane",   dest="solid_ground_plane",
                   action="store_false",
                   help="Indicate ground plane has splits or slots")
    p.add_argument("--uses-rf-connector",       action="store_true",  default=None)
    p.add_argument("--connector-type",          type=str, default=None,
                   help="RF connector label, e.g. SMA, U.FL")
    p.add_argument("--freq-ghz",                type=float, default=None,
                   help="Operating frequency (GHz); inferred from upstream if omitted")
    p.add_argument("--num-layers",              type=int,   default=None,
                   help="Number of PCB copper layers")
    p.add_argument("--substrate",               type=str,   default=None,
                   help="Substrate label (e.g. FR4)")
    p.add_argument("--decoupling-distance-mm",  type=float, default=None,
                   dest="rf_ic_decoupling_distance_mm",
                   help="RF IC decoupling cap distance from supply pin (mm)")

    args = p.parse_args()

    def _load(path: Optional[str]) -> Optional[Dict]:
        if path is None:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    result = check_rf_rules(
        microstrip_result=_load(args.microstrip),
        cpwg_result=_load(args.cpwg),
        antenna_result=_load(args.antenna),
        matching_result=_load(args.matching),
        via_fence_actual_pitch_mm=args.via_fence_pitch_mm,
        antenna_clearance_mm=args.antenna_clearance_mm,
        rf_digital_clearance_mm=args.rf_digital_clearance_mm,
        has_solid_ground_plane=args.solid_ground_plane,
        uses_rf_connector=args.uses_rf_connector,
        connector_type=args.connector_type,
        freq_ghz=args.freq_ghz,
        num_layers=args.num_layers,
        substrate=args.substrate,
        rf_ic_decoupling_distance_mm=args.rf_ic_decoupling_distance_mm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
