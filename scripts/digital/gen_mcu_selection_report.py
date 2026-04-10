#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_mcu_selection_report.py

Engineering-grade MCU selection report generator for embedded system designs.

Given a set of project requirements, this script:
- Scores a curated internal knowledge base of common MCUs against the requirements
- Produces a ranked shortlist with rationale for each candidate
- Flags disqualifying mismatches (e.g. insufficient flash, missing peripheral)
- Generates a structured comparison table and recommendation summary

Knowledge base covers the most common MCU families used in embedded/IoT work:
  STM32 (F0/F1/F4/G0/G4/H7), ESP32 (original/S3/C3), RP2040, nRF52840,
  ATmega328P (Arduino Uno), ATmega4809.

Scoring model
  Each requirement maps to one or more MCU attributes. A hard mismatch on any
  requirement disqualifies the MCU entirely. Soft mismatches reduce the score.
  Candidates are sorted by score descending.

Unified dict/JSON output contract (matches all scripts in this project).
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# MCU knowledge base
# ---------------------------------------------------------------------------

@dataclass
class MCUSpec:
    family:         str
    part:           str              # Representative part number
    core:           str
    freq_mhz:       int
    flash_kb:       int
    ram_kb:         int
    supply_v:       Tuple[float, float]   # (min, max)
    has_wifi:       bool
    has_ble:        bool
    has_lora:       bool             # True only for SiP with integrated LoRa
    has_usb:        bool
    has_can:        bool
    has_ethernet:   bool
    has_dac:        bool
    has_adc_bits:   int              # ADC resolution (bits), 0 = none
    has_fpu:        bool
    has_rtos_support: bool           # Mature RTOS port available
    gpio_count:     int
    uart_count:     int
    spi_count:      int
    i2c_count:      int
    price_usd:      float            # Approximate unit price (small qty)
    package_notes:  str
    ecosystem_notes: str
    low_power_ua:   int              # Typical deep sleep current (µA)
    temp_range_c:   Tuple[int, int]  # (min, max) operating temperature


_MCU_DB: List[MCUSpec] = [
    MCUSpec(
        family="STM32F1", part="STM32F103C8T6", core="Cortex-M3",
        freq_mhz=72, flash_kb=64, ram_kb=20,
        supply_v=(2.0, 3.6), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=True, has_ethernet=False, has_dac=True,
        has_adc_bits=12, has_fpu=False, has_rtos_support=True,
        gpio_count=37, uart_count=3, spi_count=2, i2c_count=2,
        price_usd=0.8, package_notes="LQFP-48, easy to hand-solder",
        ecosystem_notes="Huge community (Blue Pill), STM32CubeIDE, HAL/LL, Keil, PlatformIO",
        low_power_ua=3, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="STM32F4", part="STM32F411CEU6", core="Cortex-M4F",
        freq_mhz=100, flash_kb=512, ram_kb=128,
        supply_v=(1.7, 3.6), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=12, has_fpu=True, has_rtos_support=True,
        gpio_count=36, uart_count=3, spi_count=5, i2c_count=3,
        price_usd=2.5, package_notes="UFQFPN-48, reflow required",
        ecosystem_notes="Strong DSP/float support, STM32CubeIDE",
        low_power_ua=2, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="STM32G0", part="STM32G071RBT6", core="Cortex-M0+",
        freq_mhz=64, flash_kb=128, ram_kb=36,
        supply_v=(1.7, 3.6), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=True,
        has_adc_bits=12, has_fpu=False, has_rtos_support=True,
        gpio_count=59, uart_count=6, spi_count=3, i2c_count=3,
        price_usd=1.2, package_notes="LQFP-64, 2× UCPD (USB-PD capable)",
        ecosystem_notes="Modern entry-level STM32, recommended for new designs",
        low_power_ua=1, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="STM32G4", part="STM32G474RET6", core="Cortex-M4F",
        freq_mhz=170, flash_kb=512, ram_kb=128,
        supply_v=(1.71, 3.6), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=True, has_ethernet=False, has_dac=True,
        has_adc_bits=16, has_fpu=True, has_rtos_support=True,
        gpio_count=83, uart_count=5, spi_count=4, i2c_count=4,
        price_usd=4.5, package_notes="LQFP-64",
        ecosystem_notes="High-res ADC, HRTIM for power converters, motor control",
        low_power_ua=2, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="STM32H7", part="STM32H743ZIT6", core="Cortex-M7",
        freq_mhz=480, flash_kb=2048, ram_kb=1024,
        supply_v=(1.62, 3.6), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=True, has_ethernet=True, has_dac=True,
        has_adc_bits=16, has_fpu=True, has_rtos_support=True,
        gpio_count=168, uart_count=8, spi_count=6, i2c_count=4,
        price_usd=12.0, package_notes="LQFP-144 / BGA",
        ecosystem_notes="Highest-end STM32, dual-core variant available",
        low_power_ua=3, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="ESP32", part="ESP32-WROOM-32E", core="Xtensa LX6 dual-core",
        freq_mhz=240, flash_kb=4096, ram_kb=520,
        supply_v=(3.0, 3.6), has_wifi=True, has_ble=True, has_lora=False,
        has_usb=False, has_can=True, has_ethernet=False, has_dac=True,
        has_adc_bits=12, has_fpu=True, has_rtos_support=True,
        gpio_count=34, uart_count=3, spi_count=4, i2c_count=2,
        price_usd=2.5, package_notes="Module format, antenna built-in",
        ecosystem_notes="Dominant Wi-Fi/BLE SoC for IoT; Arduino-ESP32 and ESP-IDF",
        low_power_ua=10, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="ESP32-S3", part="ESP32-S3-WROOM-1", core="Xtensa LX7 dual-core",
        freq_mhz=240, flash_kb=8192, ram_kb=512,
        supply_v=(3.0, 3.6), has_wifi=True, has_ble=True, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=12, has_fpu=True, has_rtos_support=True,
        gpio_count=45, uart_count=3, spi_count=4, i2c_count=2,
        price_usd=3.5, package_notes="Module format, USB-OTG support",
        ecosystem_notes="Recommended for new ESP32 designs; AI acceleration (vector instructions)",
        low_power_ua=7, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="ESP32-C3", part="ESP32-C3-MINI-1", core="RISC-V",
        freq_mhz=160, flash_kb=4096, ram_kb=400,
        supply_v=(3.0, 3.6), has_wifi=True, has_ble=True, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=12, has_fpu=False, has_rtos_support=True,
        gpio_count=22, uart_count=2, spi_count=3, i2c_count=1,
        price_usd=1.8, package_notes="Small module, RISC-V open ISA",
        ecosystem_notes="Cost-optimised Wi-Fi/BLE, good for simple IoT endpoints",
        low_power_ua=5, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="RP2040", part="RP2040", core="Cortex-M0+ dual-core",
        freq_mhz=133, flash_kb=0, ram_kb=264,   # Flash external (QSPI)
        supply_v=(1.8, 3.3), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=12, has_fpu=False, has_rtos_support=True,
        gpio_count=30, uart_count=2, spi_count=2, i2c_count=2,
        price_usd=1.0, package_notes="QFN-56, external QSPI flash required",
        ecosystem_notes="MicroPython, CircuitPython, C SDK; PIO for custom protocols",
        low_power_ua=100, temp_range_c=(-20, 85),
    ),
    MCUSpec(
        family="nRF52840", part="nRF52840-QIAA", core="Cortex-M4F",
        freq_mhz=64, flash_kb=1024, ram_kb=256,
        supply_v=(1.7, 5.5), has_wifi=False, has_ble=True, has_lora=False,
        has_usb=True, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=12, has_fpu=True, has_rtos_support=True,
        gpio_count=48, uart_count=2, spi_count=4, i2c_count=2,
        price_usd=5.5, package_notes="QDEC / NFC / Zigbee / Thread support",
        ecosystem_notes="Best-in-class BLE 5.3; Zephyr RTOS; widely used in wearables",
        low_power_ua=2, temp_range_c=(-40, 85),
    ),
    MCUSpec(
        family="ATmega328P", part="ATmega328P-AU", core="AVR 8-bit",
        freq_mhz=20, flash_kb=32, ram_kb=2,
        supply_v=(1.8, 5.5), has_wifi=False, has_ble=False, has_lora=False,
        has_usb=False, has_can=False, has_ethernet=False, has_dac=False,
        has_adc_bits=10, has_fpu=False, has_rtos_support=False,
        gpio_count=23, uart_count=1, spi_count=1, i2c_count=1,
        price_usd=0.9, package_notes="DIP-28 / TQFP-32; prototype-friendly",
        ecosystem_notes="Arduino UNO ecosystem; vast library support; not for new complex designs",
        low_power_ua=1, temp_range_c=(-40, 85),
    ),
]

_MCU_MAP: Dict[str, MCUSpec] = {m.part: m for m in _MCU_DB}

# ---------------------------------------------------------------------------
# Requirements model
# ---------------------------------------------------------------------------

@dataclass
class Requirements:
    freq_mhz_min:       int   = 0       # Minimum clock frequency
    flash_kb_min:       int   = 0       # Minimum flash (KB)
    ram_kb_min:         int   = 0       # Minimum RAM (KB)
    needs_wifi:         bool  = False
    needs_ble:          bool  = False
    needs_usb:          bool  = False
    needs_can:          bool  = False
    needs_ethernet:     bool  = False
    needs_dac:          bool  = False
    needs_fpu:          bool  = False
    adc_bits_min:       int   = 0       # 0 = don't care
    gpio_min:           int   = 0
    uart_min:           int   = 0
    spi_min:            int   = 0
    i2c_min:            int   = 0
    supply_v:           float = 3.3     # Target supply voltage
    low_power:          bool  = False   # True if deep sleep < 10 µA needed
    price_usd_max:      float = 999.0
    rtos:               bool  = False
    protocol:           str   = ""      # "wifi" | "ble" | "zigbee" | "lora" | ""
    temp_min_c:         int   = -40
    temp_max_c:         int   = 85
    prefer_ecosystem:   str   = ""      # "stm32" | "esp32" | "arduino" | ""
    application:        str   = ""      # Free-text hint: "motor_control" | "iot_sensor" | "audio" etc.

# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _score_mcu(mcu: MCUSpec, req: Requirements) -> Tuple[float, List[str], List[str]]:
    """
    Score a single MCU against requirements.

    Returns (score, hard_fails, soft_notes).
    score = 0 means disqualified (hard fail).
    """
    score = 100.0
    hard_fails: List[str] = []
    soft_notes: List[str] = []

    # --- Hard disqualifiers ---
    if mcu.freq_mhz < req.freq_mhz_min:
        hard_fails.append(f"Clock {mcu.freq_mhz} MHz < required {req.freq_mhz_min} MHz")
    if mcu.flash_kb < req.flash_kb_min and mcu.family != "RP2040":
        hard_fails.append(f"Flash {mcu.flash_kb} KB < required {req.flash_kb_min} KB")
    if mcu.ram_kb < req.ram_kb_min:
        hard_fails.append(f"RAM {mcu.ram_kb} KB < required {req.ram_kb_min} KB")
    if req.needs_wifi and not mcu.has_wifi:
        hard_fails.append("No Wi-Fi")
    if req.needs_ble and not mcu.has_ble:
        hard_fails.append("No BLE")
    if req.needs_usb and not mcu.has_usb:
        hard_fails.append("No USB")
    if req.needs_can and not mcu.has_can:
        hard_fails.append("No CAN")
    if req.needs_ethernet and not mcu.has_ethernet:
        hard_fails.append("No Ethernet")
    if req.needs_fpu and not mcu.has_fpu:
        hard_fails.append("No FPU")
    if req.adc_bits_min > 0 and mcu.has_adc_bits < req.adc_bits_min:
        hard_fails.append(f"ADC {mcu.has_adc_bits}-bit < required {req.adc_bits_min}-bit")
    if mcu.gpio_count < req.gpio_min:
        hard_fails.append(f"GPIO {mcu.gpio_count} < required {req.gpio_min}")
    if mcu.uart_count < req.uart_min:
        hard_fails.append(f"UART {mcu.uart_count} < required {req.uart_min}")
    if mcu.spi_count < req.spi_min:
        hard_fails.append(f"SPI {mcu.spi_count} < required {req.spi_min}")
    if mcu.i2c_count < req.i2c_min:
        hard_fails.append(f"I2C {mcu.i2c_count} < required {req.i2c_min}")
    if mcu.price_usd > req.price_usd_max:
        hard_fails.append(f"Price ${mcu.price_usd:.2f} > budget ${req.price_usd_max:.2f}")
    if req.rtos and not mcu.has_rtos_support:
        hard_fails.append("No mature RTOS port")
    if req.supply_v < mcu.supply_v[0] or req.supply_v > mcu.supply_v[1]:
        hard_fails.append(
            f"Supply {req.supply_v:.1f} V outside MCU range "
            f"{mcu.supply_v[0]:.1f}–{mcu.supply_v[1]:.1f} V"
        )
    if req.temp_min_c < mcu.temp_range_c[0] or req.temp_max_c > mcu.temp_range_c[1]:
        hard_fails.append(
            f"Temperature range {req.temp_min_c}–{req.temp_max_c} °C exceeds MCU spec "
            f"{mcu.temp_range_c[0]}–{mcu.temp_range_c[1]} °C"
        )

    if hard_fails:
        return 0.0, hard_fails, []

    # --- Soft scoring (penalties and bonuses) ---

    # Performance headroom bonus
    freq_ratio = mcu.freq_mhz / max(req.freq_mhz_min, 1)
    if freq_ratio >= 2.0:
        score += 5
    elif freq_ratio < 1.3:
        score -= 5
        soft_notes.append("Clock frequency is close to requirement — limited headroom for future features.")

    flash_ratio = mcu.flash_kb / max(req.flash_kb_min, 1)
    if flash_ratio >= 4.0:
        score += 5
    elif flash_ratio < 1.5:
        score -= 8
        soft_notes.append("Flash is tight; consider OTA update overhead or bootloader space.")

    ram_ratio = mcu.ram_kb / max(req.ram_kb_min, 1)
    if ram_ratio >= 4.0:
        score += 5
    elif ram_ratio < 1.5:
        score -= 10
        soft_notes.append("RAM is tight; RTOS stack, buffers, and heap may be constrained.")

    # Low power
    if req.low_power:
        if mcu.low_power_ua <= 5:
            score += 10
        elif mcu.low_power_ua <= 20:
            score += 3
        else:
            score -= 10
            soft_notes.append(f"Deep sleep current {mcu.low_power_ua} µA may not meet low-power requirement.")

    # Ecosystem preference
    eco = req.prefer_ecosystem.lower()
    if eco and eco in mcu.family.lower():
        score += 8

    # Application-specific hints
    app = req.application.lower()
    if "motor" in app and mcu.family in ("STM32G4", "STM32F4"):
        score += 10
        soft_notes.append("This MCU has hardware timers and advanced PWM suitable for motor control.")
    if "audio" in app and mcu.has_fpu and mcu.freq_mhz >= 100:
        score += 8
    if "iot" in app and mcu.has_wifi:
        score += 8
    if "sensor" in app and mcu.has_adc_bits >= 12:
        score += 5

    # Price efficiency
    if mcu.price_usd <= req.price_usd_max * 0.5:
        score += 5

    return max(0.0, score), [], soft_notes


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_comparison_table(
    candidates: List[Tuple[float, MCUSpec, List[str]]],
) -> List[Dict[str, Any]]:
    rows = []
    for score, mcu, notes in candidates:
        rows.append({
            "part":          mcu.part,
            "family":        mcu.family,
            "core":          mcu.core,
            "freq_mhz":      mcu.freq_mhz,
            "flash_kb":      mcu.flash_kb,
            "ram_kb":        mcu.ram_kb,
            "wifi":          mcu.has_wifi,
            "ble":           mcu.has_ble,
            "usb":           mcu.has_usb,
            "can":           mcu.has_can,
            "fpu":           mcu.has_fpu,
            "adc_bits":      mcu.has_adc_bits,
            "price_usd":     mcu.price_usd,
            "deep_sleep_ua": mcu.low_power_ua,
            "score":         round(score, 1),
            "soft_notes":    notes,
            "package":       mcu.package_notes,
            "ecosystem":     mcu.ecosystem_notes,
        })
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class MCUReportOutput:
    success:            bool
    inputs:             Dict[str, Any]
    results:            Dict[str, Any]
    warnings:           List[str]
    recommendations:    List[str]
    next_actions:       List[str]
    error:              Optional[Dict[str, str]] = None


def gen_mcu_selection_report(
    freq_mhz_min:       int   = 0,
    flash_kb_min:       int   = 0,
    ram_kb_min:         int   = 0,
    needs_wifi:         bool  = False,
    needs_ble:          bool  = False,
    needs_usb:          bool  = False,
    needs_can:          bool  = False,
    needs_ethernet:     bool  = False,
    needs_dac:          bool  = False,
    needs_fpu:          bool  = False,
    adc_bits_min:       int   = 0,
    gpio_min:           int   = 0,
    uart_min:           int   = 0,
    spi_min:            int   = 0,
    i2c_min:            int   = 0,
    supply_v:           float = 3.3,
    low_power:          bool  = False,
    price_usd_max:      float = 999.0,
    rtos:               bool  = False,
    temp_min_c:         int   = -40,
    temp_max_c:         int   = 85,
    prefer_ecosystem:   str   = "",
    application:        str   = "",
    top_n:              int   = 3,
) -> Dict[str, Any]:
    """
    Generate an MCU selection report based on project requirements.

    All parameters are optional and default to "don't care" / minimum constraints.
    Returns the top_n qualifying candidates ranked by score, plus a disqualified list.
    """
    inputs: Dict[str, Any] = {k: v for k, v in locals().items() if k != "inputs"}

    try:
        req = Requirements(
            freq_mhz_min=freq_mhz_min, flash_kb_min=flash_kb_min,
            ram_kb_min=ram_kb_min, needs_wifi=needs_wifi, needs_ble=needs_ble,
            needs_usb=needs_usb, needs_can=needs_can, needs_ethernet=needs_ethernet,
            needs_dac=needs_dac, needs_fpu=needs_fpu, adc_bits_min=adc_bits_min,
            gpio_min=gpio_min, uart_min=uart_min, spi_min=spi_min, i2c_min=i2c_min,
            supply_v=supply_v, low_power=low_power, price_usd_max=price_usd_max,
            rtos=rtos, temp_min_c=temp_min_c, temp_max_c=temp_max_c,
            prefer_ecosystem=prefer_ecosystem, application=application,
        )

        qualified:    List[Tuple[float, MCUSpec, List[str]]] = []
        disqualified: List[Dict[str, Any]] = []

        for mcu in _MCU_DB:
            score, hard_fails, soft_notes = _score_mcu(mcu, req)
            if hard_fails:
                disqualified.append({
                    "part":   mcu.part,
                    "family": mcu.family,
                    "reasons": hard_fails,
                })
            else:
                qualified.append((score, mcu, soft_notes))

        qualified.sort(key=lambda x: x[0], reverse=True)
        top = qualified[:top_n]

        if not top:
            warnings = ["No MCU in the knowledge base satisfies all hard requirements. "
                        "Relax one or more constraints, or consider a custom SoC."]
            return asdict(MCUReportOutput(
                success=True, inputs=inputs,
                results={"top_candidates": [], "disqualified": disqualified,
                         "comparison_table": []},
                warnings=warnings, recommendations=[], next_actions=[],
            ))

        # Build top candidate entries
        top_candidates = []
        for rank, (score, mcu, notes) in enumerate(top, start=1):
            top_candidates.append({
                "rank":       rank,
                "part":       mcu.part,
                "family":     mcu.family,
                "score":      round(score, 1),
                "rationale":  (
                    f"{mcu.core} @ {mcu.freq_mhz} MHz, {mcu.flash_kb} KB flash, "
                    f"{mcu.ram_kb} KB RAM, ${mcu.price_usd:.2f}. {mcu.ecosystem_notes}."
                ),
                "soft_notes": notes,
                "package":    mcu.package_notes,
            })

        comparison_table = _build_comparison_table(top)

        # Global recommendations
        recs: List[str] = []
        top_mcu = top[0][1]
        recs.append(
            f"Primary recommendation: {top_mcu.part} ({top_mcu.family}). "
            f"Verify peripheral pin mapping against your schematic before committing to PCB layout."
        )
        if len(top) > 1:
            recs.append(
                f"Second choice: {top[1][1].part} — consider if {top[0][1].part} is out of stock "
                "or if its ecosystem does not suit your toolchain."
            )
        if low_power:
            recs.append(
                "For ultra-low-power designs, verify the actual deep-sleep current in your "
                "application firmware — peripheral clock gating and wake-up sources significantly "
                "affect real-world consumption."
            )
        recs.append(
            "Cross-check peripheral availability against your exact package and pin count. "
            "Some peripherals share pins and cannot be used simultaneously."
        )
        recs.append(
            "Confirm chip availability and lead time before finalising the BOM. "
            "Identify at least one pin-compatible alternative (second source)."
        )

        warnings: List[str] = []
        if len(qualified) < top_n:
            warnings.append(
                f"Only {len(qualified)} MCU(s) passed all requirements; "
                "shortlist is smaller than requested."
            )
        if top[0][0] < 80:
            warnings.append(
                "Top candidate score is below 80 — no MCU in the database is a strong fit. "
                "Consider relaxing constraints or expanding the search to other families."
            )

        next_actions = [
            "gen_power_tree",        # Verify supply rails match MCU requirements
            "gen_firmware_skeleton", # Generate firmware project scaffold
            "check_rf_rules",        # If wireless MCU, run RF design checks
        ]

        return asdict(MCUReportOutput(
            success=True,
            inputs=inputs,
            results={
                "top_candidates":   top_candidates,
                "comparison_table": comparison_table,
                "disqualified":     disqualified,
                "total_evaluated":  len(_MCU_DB),
                "total_qualified":  len(qualified),
                "total_disqualified": len(disqualified),
            },
            warnings=warnings,
            recommendations=recs,
            next_actions=next_actions,
        ))

    except Exception as exc:
        return asdict(MCUReportOutput(
            success=False, inputs=inputs, results={},
            warnings=[], recommendations=[], next_actions=[],
            error={"code": exc.__class__.__name__.upper(), "message": str(exc)},
        ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="MCU selection report generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--freq-mhz-min",   type=int,   default=0)
    p.add_argument("--flash-kb-min",   type=int,   default=0)
    p.add_argument("--ram-kb-min",     type=int,   default=0)
    p.add_argument("--needs-wifi",     action="store_true")
    p.add_argument("--needs-ble",      action="store_true")
    p.add_argument("--needs-usb",      action="store_true")
    p.add_argument("--needs-can",      action="store_true")
    p.add_argument("--needs-ethernet", action="store_true")
    p.add_argument("--needs-dac",      action="store_true")
    p.add_argument("--needs-fpu",      action="store_true")
    p.add_argument("--adc-bits-min",   type=int,   default=0)
    p.add_argument("--gpio-min",       type=int,   default=0)
    p.add_argument("--uart-min",       type=int,   default=0)
    p.add_argument("--spi-min",        type=int,   default=0)
    p.add_argument("--i2c-min",        type=int,   default=0)
    p.add_argument("--supply-v",       type=float, default=3.3)
    p.add_argument("--low-power",      action="store_true")
    p.add_argument("--price-max",      type=float, default=999.0, dest="price_usd_max")
    p.add_argument("--rtos",           action="store_true")
    p.add_argument("--temp-min-c",     type=int,   default=-40)
    p.add_argument("--temp-max-c",     type=int,   default=85)
    p.add_argument("--prefer",         type=str,   default="", dest="prefer_ecosystem",
                   help="Preferred ecosystem: stm32 | esp32 | arduino")
    p.add_argument("--application",    type=str,   default="",
                   help="Application hint: iot_sensor | motor_control | audio | etc.")
    p.add_argument("--top",            type=int,   default=3, dest="top_n")
    args = p.parse_args()

    result = gen_mcu_selection_report(
        freq_mhz_min=args.freq_mhz_min, flash_kb_min=args.flash_kb_min,
        ram_kb_min=args.ram_kb_min, needs_wifi=args.needs_wifi,
        needs_ble=args.needs_ble, needs_usb=args.needs_usb,
        needs_can=args.needs_can, needs_ethernet=args.needs_ethernet,
        needs_dac=args.needs_dac, needs_fpu=args.needs_fpu,
        adc_bits_min=args.adc_bits_min, gpio_min=args.gpio_min,
        uart_min=args.uart_min, spi_min=args.spi_min, i2c_min=args.i2c_min,
        supply_v=args.supply_v, low_power=args.low_power,
        price_usd_max=args.price_usd_max, rtos=args.rtos,
        temp_min_c=args.temp_min_c, temp_max_c=args.temp_max_c,
        prefer_ecosystem=args.prefer_ecosystem, application=args.application,
        top_n=args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
