#!/usr/bin/env python3
"""Generate a hardware + firmware starter bundle for an embedded system."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "protocol"))

from gen_kicad_project import DEFAULT_LIBRARY, DEFAULT_TEMPLATE, generate_project, load_json  # type: ignore  # noqa: E402
from gen_crc_frame import gen_crc_frame  # type: ignore  # noqa: E402
from gen_firmware_skeleton import gen_firmware_skeleton  # type: ignore  # noqa: E402
from gen_uart_protocol import gen_uart_protocol  # type: ignore  # noqa: E402


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def firmware_profile(spec: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    mcu = str(spec.get("mcu", "")).upper()
    peripherals: list[str] = []
    if spec.get("debug", {}).get("uart_header", True):
        peripherals.append("uart")
    if any(sensor.get("interface", "i2c") == "i2c" for sensor in spec.get("sensors", [])):
        peripherals.append("i2c")
    if spec.get("radio_modules"):
        peripherals.append("spi")

    platform = ""
    series = ""
    rtos = "freertos"
    warnings: list[str] = []
    if "ESP32" in mcu:
        platform = "esp32"
        peripherals.extend(["wifi", "ble"])
    elif "STM32" in mcu:
        platform = "stm32"
        series = "G4"
    else:
        warnings.append(f"MCU {spec.get('mcu', '')} is not yet mapped to firmware-skill auto-generation.")

    ordered_peripherals = []
    for item in peripherals:
        if item not in ordered_peripherals:
            ordered_peripherals.append(item)

    protocol_commands = [
        "READ_SENSORS:0x01:0:host_to_device:Request latest sampled sensor payload",
        "SET_REPORT_INTERVAL:0x02:2:host_to_device:Set reporting interval in seconds",
        "GET_STATUS:0x03:0:host_to_device:Request system status bits",
        "ACK:0x10:1:device_to_host:Positive acknowledgement",
        "SENSOR_REPORT:0x11:8:device_to_host:Periodic sensor report payload",
    ]
    if spec.get("radio_modules"):
        protocol_commands.append("RADIO_TX:0x20:8:host_to_device:Send radio payload bytes")
        protocol_commands.append("RADIO_RX:0x21:8:device_to_host:Receive radio payload bytes")

    return {
        "platform": platform,
        "series": series,
        "rtos": rtos,
        "peripherals": ordered_peripherals,
        "warnings": warnings,
        "protocol_name": f"{manifest['project_name']}_proto",
        "protocol_commands": ",".join(protocol_commands),
    }


def materialize_firmware(output_root: Path, skeleton: dict[str, Any]) -> list[str]:
    written: list[str] = []
    for rel_path, content in skeleton.get("results", {}).get("files", {}).items():
        target = output_root / rel_path
        write_text(target, content)
        written.append(str(target))
    return written


def write_protocol_artifacts(output_root: Path, protocol_name: str, proto: dict[str, Any]) -> dict[str, str]:
    proto_dir = output_root / "generated_protocol"
    header = proto_dir / f"{protocol_name}.h"
    source = proto_dir / f"{protocol_name}.c"
    host_py = proto_dir / f"{protocol_name}_host.py"
    summary = proto_dir / f"{protocol_name}_summary.json"
    write_text(header, proto["results"]["c_header"])
    write_text(source, proto["results"]["c_source"])
    write_text(host_py, proto["results"]["python_reference"])
    write_json(summary, proto)
    return {
        "protocol_header": str(header),
        "protocol_source": str(source),
        "protocol_host": str(host_py),
        "protocol_summary": str(summary),
    }


def write_crc_artifacts(output_root: Path, algo_name: str) -> dict[str, str]:
    result = gen_crc_frame(poly=algo_name, include_c_code=True)
    crc_dir = output_root / "generated_protocol"
    stem = algo_name.lower()
    source = crc_dir / f"{stem}.c"
    header = crc_dir / f"{stem}.h"
    summary = crc_dir / f"{stem}_summary.json"
    ctype = "uint8_t" if "8" in algo_name and "16" not in algo_name and "32" not in algo_name else ("uint16_t" if "16" in algo_name else "uint32_t")
    func_name = f"calc_{stem}"
    header_text = "\n".join([
        "#ifndef CRC_HELPER_H",
        "#define CRC_HELPER_H",
        "",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "",
        f"{ctype} {func_name}(const uint8_t *data, size_t len);",
        "",
        "#endif /* CRC_HELPER_H */",
        "",
    ])
    write_text(source, result["results"]["c_code"])
    write_text(header, header_text)
    write_json(summary, result)
    return {
        "crc_source": str(source),
        "crc_header": str(header),
        "crc_summary": str(summary),
    }


def write_system_contract(outdir: Path, spec: dict[str, Any], manifest: dict[str, Any], hw_outputs: dict[str, str], fw_profile: dict[str, Any]) -> Path:
    path = outdir / "system_contract.md"
    pin_rows = manifest.get("pinmap", [])
    lines = [
        f"# {manifest['project_name']} System Contract",
        "",
        "## Hardware to Firmware Scope",
        f"- MCU: {spec.get('mcu', '')}",
        f"- Firmware platform: {fw_profile.get('platform', 'unsupported')}",
        f"- RTOS: {fw_profile.get('rtos', 'none')}",
        f"- Peripherals: {', '.join(fw_profile.get('peripherals', [])) or 'none'}",
        "",
        "## Generated Hardware Artifacts",
        f"- Schematic: `{hw_outputs.get('kicad_schematic', '')}`",
        f"- PCB skeleton: `{hw_outputs.get('kicad_pcb', '')}`",
        f"- Pin map: `{hw_outputs.get('pinmap', '')}`",
        f"- PCB constraints: `{hw_outputs.get('pcb_constraints', '')}`",
        "",
        "## Pin Map",
        "",
        "| Interface | Signal | MCU Pin | Net |",
        "|---|---|---|---|",
    ]
    for row in pin_rows:
        lines.append(f"| {row.get('interface', '')} | {row.get('signal', '')} | {row.get('mcu_pin', '')} | {row.get('net', '')} |")
    lines.extend([
        "",
        "## Implementation Notes",
        "- Firmware should treat this bundle as a starting point, not a completed application.",
        "- Copy generated protocol files into the platform project and wire them into the UART or radio task.",
        "- Review `pcb_constraints.md` before assigning GPIOs to timing-sensitive or RF-adjacent functions.",
    ])
    if fw_profile.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in fw_profile["warnings"])
    write_text(path, "\n".join(lines) + "\n")
    return path


def write_bundle_readme(outdir: Path, bundle: dict[str, Any]) -> Path:
    path = outdir / "README_system_bundle.md"
    lines = [
        f"# {bundle['project_name']} Embedded System Bundle",
        "",
        "## Contents",
        "- `hardware/`: KiCad/EasyEDA/BOM/pinmap/EDA validation outputs, JLC package, footprint binding artifacts",
        "- `firmware/`: firmware-skill derived starter project",
        "- `system_contract.md`: hardware-firmware contract and pin mapping",
        "",
        "## What Was Generated",
        f"- Hardware output root: `{bundle['hardware_root']}`",
        f"- Firmware output root: `{bundle['firmware_root']}`",
        f"- Validation: `{bundle['hardware_outputs'].get('eda_validation', '')}`",
        "",
        "## Remaining Work",
        "- Complete firmware application logic in the generated project.",
        "- Replace placeholder protocol handlers with real sensor/radio behavior.",
        "- Review the auto-generated `jlc_cpl.csv` against the intended manual placement and rerun KiCad PCB DRC after layout edits.",
    ]
    write_text(path, "\n".join(lines) + "\n")
    return path


def generate_bundle(spec_path: Path, library_path: Path, outdir: Path, project_name: str | None = None) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    hardware_dir = outdir / "hardware"
    firmware_dir = outdir / "firmware"

    hw_result = generate_project(spec_path, library_path, hardware_dir, project_name)
    manifest = load_json(hardware_dir / "project.netlist.json")
    spec = load_json(spec_path)
    if project_name:
        spec["project_name"] = project_name

    fw_profile = firmware_profile(spec, manifest)
    firmware_outputs: dict[str, Any] = {"warnings": fw_profile["warnings"]}

    if fw_profile["platform"]:
        skeleton = gen_firmware_skeleton(
            platform=fw_profile["platform"],
            project_name=manifest["project_name"],
            series=fw_profile["series"] or "G4",
            peripherals=fw_profile["peripherals"],
            rtos=fw_profile["rtos"],
        )
        proto = gen_uart_protocol(
            name=fw_profile["protocol_name"],
            baud=115200,
            crc_type="CRC16_MODBUS",
            commands_str=fw_profile["protocol_commands"],
            max_payload_bytes=64,
        )
        written_files = materialize_firmware(firmware_dir, skeleton)
        protocol_outputs = write_protocol_artifacts(firmware_dir, fw_profile["protocol_name"], proto)
        crc_outputs = write_crc_artifacts(firmware_dir, "CRC16_MODBUS")
        firmware_outputs = {
            "skeleton_summary": skeleton,
            "protocol_summary": proto,
            "written_files": written_files,
            "protocol_outputs": protocol_outputs,
            "crc_outputs": crc_outputs,
            "warnings": fw_profile["warnings"] + skeleton.get("warnings", []) + proto.get("warnings", []),
        }
    contract = write_system_contract(outdir, spec, manifest, hw_result["outputs"], fw_profile)
    bundle = {
        "success": True,
        "project_name": manifest["project_name"],
        "hardware_root": str(hardware_dir),
        "firmware_root": str(firmware_dir),
        "hardware_outputs": hw_result["outputs"],
        "firmware_outputs": firmware_outputs,
        "system_contract": str(contract),
    }
    bundle["bundle_readme"] = str(write_bundle_readme(outdir, bundle))
    write_json(outdir / "embedded_system_bundle.json", bundle)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a complete embedded system starter bundle.")
    parser.add_argument("--spec", type=Path, help="Project spec JSON. Defaults to bundled ESP32-C3 template.")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY, help="Component library JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory.")
    parser.add_argument("--project-name", help="Override project name.")
    args = parser.parse_args()

    result = generate_bundle(args.spec or DEFAULT_TEMPLATE, args.library, args.out, args.project_name)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
