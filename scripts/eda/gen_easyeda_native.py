"""Generate a native EasyEDA JSON schematic from a project netlist.

Produces a JSON file that can be loaded into 嘉立创EDA via:
  api('applySource', {source: <json>, createNew: true})

Usage:
    python gen_easyeda_native.py --manifest <path>/project.netlist.json --out <output.json>
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

# EasyEDA uses pixel units. 1 grid = 10px. 1mm ≈ 10px at default scale.
GRID = 10
PIN_LEN = 20  # pin length in pixels
BODY_PAD = 10  # padding around pin text inside body


def gid(counter: list[int]) -> str:
    counter[0] += 1
    return f"gge{counter[0]}"


def build_pin_map(manifest: dict) -> dict[str, dict[str, str]]:
    """Build {ref: {pin: net_name}} from nets."""
    result: dict[str, dict[str, str]] = {}
    for net_name, connections in manifest.get("nets", {}).items():
        for conn in connections:
            if "." in conn:
                ref, pin = conn.split(".", 1)
                result.setdefault(ref, {})[pin] = net_name
    return result


def estimate_body_size(pins: list[str]) -> tuple[float, float]:
    """Estimate component body width and height from pin count/names."""
    max_name_len = max((len(p) for p in pins), default=4)
    n = len(pins)
    w = max(40, max_name_len * 8 + 20)
    h = max(30, n * GRID * 2 + 20)
    return w, h


def make_pin(gids: list[int], x: float, y: float, angle: float,
             pin_name: str, pin_num: str) -> dict:
    """Create an EasyEDA pin object."""
    g = gid(gids)
    # pin line extends from pinDot inward
    if angle == 0:  # pin on left, pointing right
        px = x - PIN_LEN
        path = f"M {px} {y} h {PIN_LEN}"
        name_x, name_y = x - 3, y + 3
        num_x, num_y = x - 12, y - 1
        name_anchor = "end"
    elif angle == 180:  # pin on right, pointing left
        px = x + PIN_LEN
        path = f"M {px} {y} h -{PIN_LEN}"
        name_x, name_y = x + 3, y + 3
        num_x, num_y = x + 12, y - 1
        name_anchor = "start"
    elif angle == 90:  # pin on top, pointing down
        py = y - PIN_LEN
        path = f"M {x} {py} v {PIN_LEN}"
        name_x, name_y = x + 3, y - 3
        num_x, num_y = x - 1, y - 12
        name_anchor = "start"
    else:  # pin on bottom, pointing up
        py = y + PIN_LEN
        path = f"M {x} {py} v -{PIN_LEN}"
        name_x, name_y = x + 3, y + 3
        num_x, num_y = x - 1, y + 12
        name_anchor = "start"

    return {
        "configure": {
            "display": "show",
            "electric": "0",
            "spicePin": pin_num,
            "x": str(x),
            "y": str(y),
            "rotation": str(angle),
            "gId": g
        },
        "pinDot": {"x": x, "y": y},
        "path": {"pathString": path, "pinColor": "#800000"},
        "name": {
            "visible": 1, "x": str(name_x), "y": str(name_y),
            "rotation": 0, "text": pin_name,
            "textAnchor": name_anchor,
            "fontFamily": "", "fontSize": ""
        },
        "num": {
            "visible": 0, "x": str(num_x), "y": str(num_y),
            "rotation": 0, "text": pin_num,
            "textAnchor": "start",
            "fontFamily": "", "fontSize": ""
        },
        "dot": {"visible": 0, "x": str(x - 3 if angle == 0 else x + 3 if angle == 180 else x),
                "y": str(y - 3 if angle == 90 else y + 3 if angle == 270 else y)},
        "clock": {}
    }


def make_component(gids: list[int], ref: str, value: str, pins: dict[str, str],
                    cx: float, cy: float) -> dict:
    """Create an EasyEDA schlib component with rectangular body and pins."""
    pin_names = list(pins.keys())
    body_w, body_h = estimate_body_size(pin_names)

    # Split pins: left side and right side
    half = math.ceil(len(pin_names) / 2)
    left_pins = pin_names[:half]
    right_pins = pin_names[half:]

    # Component center offset so pins align to grid
    x0 = cx - body_w / 2
    y0 = cy - body_h / 2

    schlib_id = gid(gids)
    item_order = []

    # Annotations (reference and value)
    ann_ref_id = gid(gids)
    ann_val_id = gid(gids)
    annotation = {
        ann_ref_id: {
            "gId": ann_ref_id, "mark": "N", "x": str(cx), "y": str(y0 - 15),
            "rotation": 0, "fillColor": "#000080", "fontFamily": "Arial",
            "fontSize": "", "fontWeight": "", "fontStyle": "",
            "dominantBaseline": "", "type": "comment", "string": ref,
            "visible": 1, "textAnchor": "middle"
        },
        ann_val_id: {
            "gId": ann_val_id, "mark": "P", "x": str(cx), "y": str(y0 + body_h + 10),
            "rotation": 0, "fillColor": "#000080", "fontFamily": "Arial",
            "fontSize": "", "fontWeight": "", "fontStyle": "",
            "dominantBaseline": "", "type": "comment", "string": value,
            "visible": 1, "textAnchor": "middle"
        }
    }
    item_order.extend([ann_ref_id, ann_val_id])

    # Body rectangle
    rect_id = gid(gids)
    rect = {
        rect_id: {
            "gId": rect_id, "strokeColor": "#800000", "strokeWidth": "1",
            "strokeStyle": 0, "fillColor": "#FFFFFF",
            "x": str(x0), "y": str(y0), "rx": "", "ry": "",
            "width": str(body_w), "height": str(body_h)
        }
    }
    item_order.append(rect_id)

    # Pins
    pin_dict: dict[str, Any] = {}
    pin_positions: dict[str, tuple[float, float]] = {}

    for i, pin_name in enumerate(left_pins):
        py = y0 + 15 + i * GRID * 2
        px = x0 - PIN_LEN
        pin_obj = make_pin(gids, x0, py, 0, pin_name, pin_name)
        pid = pin_obj["configure"]["gId"]
        pin_dict[pid] = pin_obj
        pin_positions[pin_name] = (px, py)
        item_order.append(pid)

    for i, pin_name in enumerate(right_pins):
        py = y0 + 15 + i * GRID * 2
        px = x0 + body_w + PIN_LEN
        pin_obj = make_pin(gids, x0 + body_w, py, 180, pin_name, pin_name)
        pid = pin_obj["configure"]["gId"]
        pin_dict[pid] = pin_obj
        pin_positions[pin_name] = (px, py)
        item_order.append(pid)

    # Package info in c_para
    c_para = f"package``catid``spicePre`U`"

    return {
        "schlib": {
            schlib_id: {
                "head": {
                    "gId": schlib_id,
                    "x": str(cx), "y": str(cy),
                    "c_para": c_para,
                    "importFlag": 0
                },
                "itemOrder": item_order,
                "annotation": annotation,
                "rect": rect,
                "pin": pin_dict
            }
        },
        "pin_positions": pin_positions  # for wire generation
    }


def make_wire(gids: list[int], points: list[tuple[float, float]]) -> dict:
    """Create a wire with given points."""
    g = gid(gids)
    return {
        g: {
            "gId": g, "strokeColor": "#008800", "strokeWidth": "1",
            "strokeStyle": 0, "fillColor": "none",
            "pointArr": [{"x": x, "y": y} for x, y in points]
        }
    }


def make_netlabel(gids: list[int], name: str, x: float, y: float) -> dict:
    """Create a net label."""
    g = gid(gids)
    return {
        g: {
            "gId": g, "pinDot": {"x": x, "y": y},
            "rotation": 0, "fillColor": "#000080",
            "name": name, "textAnchor": "start",
            "x": str(x + 2), "y": str(y),
            "fontFamily": "Times New Roman", "fontSize": "7pt"
        }
    }


def make_gnd_flag(gids: list[int], x: float, y: float) -> dict:
    """Create a GND power flag."""
    g = gid(gids)
    lines = [
        {"gId": gid(gids), "strokeColor": "#000000", "strokeWidth": "1",
         "strokeStyle": 0, "fillColor": "none",
         "pointArr": [{"x": x, "y": y}, {"x": x, "y": y + 10}]},
        {"gId": gid(gids), "strokeColor": "#000000", "strokeWidth": "1",
         "strokeStyle": 0, "fillColor": "none",
         "pointArr": [{"x": x - 10, "y": y + 10}, {"x": x + 10, "y": y + 10}]},
        {"gId": gid(gids), "strokeColor": "#000000", "strokeWidth": "1",
         "strokeStyle": 0, "fillColor": "none",
         "pointArr": [{"x": x - 6, "y": y + 12}, {"x": x + 6, "y": y + 12}]},
        {"gId": gid(gids), "strokeColor": "#000000", "strokeWidth": "1",
         "strokeStyle": 0, "fillColor": "none",
         "pointArr": [{"x": x - 2, "y": y + 14}, {"x": x + 2, "y": y + 14}]},
    ]
    shapes = {}
    for line in lines:
        shapes[line["gId"]] = line

    mark_g = gid(gids)
    return {
        g: {
            "configure": {
                "gId": g, "partId": "part_netLabel_gnD",
                "x": str(x), "y": str(y), "rotation": "0"
            },
            "pinDot": {"x": x, "y": y},
            "mark": {
                "netFlagString": "GND", "fillColor": "#000080",
                "x": str(x - 11), "y": str(y - 13), "rotation": 0,
                "textAnchor": "start", "visible": 0,
                "fontFamily": "Times New Roman", "fontSize": "9pt"
            },
            "shapes": {"polyline": shapes}
        }
    }


def make_vcc_flag(gids: list[int], name: str, x: float, y: float) -> dict:
    """Create a VCC/power flag (circle with arrow)."""
    g = gid(gids)
    mark_g = gid(gids)
    return {
        g: {
            "configure": {
                "gId": g, "partId": f"part_netLabel_{name}",
                "x": str(x), "y": str(y), "rotation": "0"
            },
            "pinDot": {"x": x, "y": y},
            "mark": {
                "netFlagString": name, "fillColor": "#000080",
                "x": str(x), "y": str(y - 15), "rotation": 0,
                "textAnchor": "middle", "visible": 1,
                "fontFamily": "Times New Roman", "fontSize": "7pt"
            },
            "shapes": {
                "polyline": {
                    mark_g: {
                        "gId": mark_g, "strokeColor": "#000000",
                        "strokeWidth": "1", "strokeStyle": 0,
                        "fillColor": "none",
                        "pointArr": [
                            {"x": x, "y": y}, {"x": x, "y": y - 10}
                        ]
                    }
                }
            }
        }
    }


def generate_easyeda_schematic(manifest: dict) -> dict:
    """Generate a complete EasyEDA schematic JSON from a project manifest."""
    gids = [0]  # mutable counter
    components = manifest.get("components", [])
    nets = manifest.get("nets", {})

    # Build pin map
    pin_map = build_pin_map(manifest)

    # Layout: arrange components in a grid
    cols = 5
    spacing_x = 250
    spacing_y = 200

    # Collect all EasyEDA objects
    all_schlib: dict = {}
    all_wire: dict = {}
    all_netlabel: dict = {}
    all_netflag: dict = {}
    all_junction: dict = {}
    item_order: list[str] = []

    # Pin positions: {ref.pin: (x, y)}
    comp_pin_positions: dict[str, tuple[float, float]] = {}
    comp_positions: dict[str, tuple[float, float]] = {}

    # Place components
    for i, comp in enumerate(components):
        ref = comp["ref"]
        col = i % cols
        row = i // cols
        cx = 200 + col * spacing_x
        cy = 200 + row * spacing_y
        comp_positions[ref] = (cx, cy)

        pins = pin_map.get(ref, {})
        result = make_component(gids, ref, comp["value"], pins, cx, cy)

        for sid, sdata in result["schlib"].items():
            all_schlib[sid] = sdata
            item_order.append(sid)

        for pin_name, (px, py) in result["pin_positions"].items():
            comp_pin_positions[f"{ref}.{pin_name}"] = (px, py)

    # Wire connections: group by net, connect pins in each net
    power_nets = {"GND", "+3V3", "+VBUS", "+5V"}
    signal_nets = {name: conns for name, conns in nets.items()
                   if name not in power_nets and len(conns) >= 2}

    # For each signal net, connect pins with wires
    for net_name, connections in signal_nets.items():
        # Get pin positions for this net
        pin_pos = []
        for conn in connections:
            if conn in comp_pin_positions:
                pin_pos.append((conn, comp_pin_positions[conn]))

        if len(pin_pos) < 2:
            continue

        # Simple approach: connect all pins to a common vertical bus
        # Find the leftmost and rightmost pins
        pin_pos.sort(key=lambda p: p[1][0])  # sort by x

        if len(pin_pos) == 2:
            # Direct wire between two pins
            (ref1, (x1, y1)), (ref2, (x2, y2)) = pin_pos
            if abs(x1 - x2) < 5:
                # Same x, vertical wire
                wire = make_wire(gids, [(x1, y1), (x2, y2)])
            else:
                # L-shaped wire
                mid_x = (x1 + x2) / 2
                wire = make_wire(gids, [(x1, y1), (mid_x, y1), (mid_x, y2), (x2, y2)])
            all_wire.update(wire)
        else:
            # Multiple pins: connect via horizontal bus
            bus_y = min(p[1][1] for p in pin_pos) - 20
            bus_x_min = min(p[1][0] for p in pin_pos)
            bus_x_max = max(p[1][0] for p in pin_pos)

            # Horizontal bus wire
            bus_wire = make_wire(gids, [(bus_x_min, bus_y), (bus_x_max, bus_y)])
            all_wire.update(bus_wire)

            # Connect each pin to the bus
            for ref_name, (px, py) in pin_pos:
                stub = make_wire(gids, [(px, py), (px, bus_y)])
                all_wire.update(stub)

            # Add net label at center of bus
            label_x = (bus_x_min + bus_x_max) / 2
            label = make_netlabel(gids, net_name, label_x, bus_y)
            all_netlabel.update(label)

    # Power nets: add power symbols
    for net_name, connections in nets.items():
        if net_name not in power_nets:
            continue
        for conn in connections:
            if conn not in comp_pin_positions:
                continue
            ref, pin = conn.split(".", 1)
            px, py = comp_pin_positions[conn]

            if net_name == "GND":
                flag = make_gnd_flag(gids, px, py + PIN_LEN)
                all_netflag.update(flag)
            elif net_name in ("+3V3", "+VBUS", "+5V"):
                flag = make_vcc_flag(gids, net_name, px, py - PIN_LEN)
                all_netflag.update(flag)

    # Build final JSON
    head = {
        "c_para": f"Prefix Start`1`",
        "c_spiceCmd": None
    }

    canvas = {
        "viewWidth": str(max(1200, 200 + cols * spacing_x + 200)),
        "viewHeight": str(max(1200, 200 + (len(components) // cols + 1) * spacing_y + 200)),
        "backGround": "#FFFFFF",
        "gridVisible": "yes",
        "gridColor": "#CCCCCC",
        "gridSize": "10",
        "canvasWidth": max(1200, 200 + cols * spacing_x + 200),
        "canvasHeight": max(1200, 200 + (len(components) // cols + 1) * spacing_y + 200),
        "gridStyle": "line",
        "snapSize": 10,
        "unit": "pixel",
        "altSnapSize": 5
    }

    # Collect all item IDs
    all_items = []
    for sid in all_schlib:
        all_items.append(sid)
    for wid in all_wire:
        all_items.append(wid)
    for nid in all_netlabel:
        all_items.append(nid)
    for fid in all_netflag:
        all_items.append(fid)

    bbox = {
        "x": 100, "y": 100,
        "width": max(1200, cols * spacing_x + 200),
        "height": max(1200, (len(components) // cols + 1) * spacing_y + 200)
    }

    return {
        "head": head,
        "canvas": canvas,
        "BBox": bbox,
        "itemOrder": all_items,
        "schlib": all_schlib,
        "wire": all_wire,
        "netlabel": all_netlabel,
        "netflag": all_netflag,
        "junction": all_junction
    }


def main():
    parser = argparse.ArgumentParser(description="Generate EasyEDA native schematic JSON")
    parser.add_argument("--manifest", required=True, help="Path to project.netlist.json")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = generate_easyeda_schematic(manifest)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Generated: {out_path}")
    print(f"Components: {len(result.get('schlib', {}))}")
    print(f"Wires: {len(result.get('wire', {}))}")
    print(f"Net labels: {len(result.get('netlabel', {}))}")
    print(f"Power flags: {len(result.get('netflag', {}))}")
    print(f"Total items: {len(result.get('itemOrder', []))}")


if __name__ == "__main__":
    main()
