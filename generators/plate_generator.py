"""Generate positioning plate DXF with switch cutouts, stab holes, and avoidance."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import ezdxf
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union

from models.pcb_data import PCBData, Component, ScrewHole
from models.layout_group import LayoutConfig
from models.layer_config import FoamLayerConfig
from models.avoidance import AvoidancePolygon
from avoidance.avoidance_engine import compute_avoidance_zone, subtract_avoidance


# Standard MX switch cutout dimensions (mm)
MX_CUTOUT_W = 14.0
MX_CUTOUT_H = 14.0
MX_CORNER_RADIUS = 0.5

# Stabilizer cutout dimensions (mm)
STAB_WIRE_RADIUS = 0.85       # Wire hole radius
STAB_INSERT_W = 3.0           # Insert cutout width
STAB_INSERT_H = 3.5           # Insert cutout height

# Stab spacing for common key sizes (mm from switch center)
STAB_SPACING = {
    "2u": 11.938,
    "2.25u": 15.875,
    "2.75u": 19.844,
    "6.25u": 50.0,
    "7u": 57.15,
}

# Standard key spacing
KEY_SPACING = 19.05  # 1U in mm

# Plate variant definitions
PLATE_VARIANT_ANSI = "ansi"
PLATE_VARIANT_7U_ENTER = "7u_enter"
PLATE_VARIANT_UNIVERSAL = "universal"


@dataclass
class StabilizerPosition:
    """A stabilizer position relative to a switch center."""
    switch_x: float
    switch_y: float
    key_size: str  # e.g., "2u", "6.25u"
    orientation: str = "horizontal"  # "horizontal" or "vertical"


def generate_plate(
    pcb: PCBData,
    layout: LayoutConfig,
    layer_config: FoamLayerConfig,
    avoidance_polygons: list[AvoidancePolygon],
    output_path: str,
    cutout_size: tuple[float, float] = (MX_CUTOUT_W, MX_CUTOUT_H),
    corner_radius: float = MX_CORNER_RADIUS,
    plate_type: str = PLATE_VARIANT_UNIVERSAL,
) -> None:
    """Generate a positioning plate DXF file.

    Args:
        plate_type: "ansi", "7u_enter", or "universal"
    """
    doc = ezdxf.new("R2010")

    # Create layers
    doc.layers.add("OUTLINE", color=7)       # white
    doc.layers.add("SCREW_HOLES", color=5)   # blue
    doc.layers.add("SWITCH_CUTS", color=1)   # red
    doc.layers.add("STAB_CUTS", color=3)     # green

    # Add dashed linetype for universal template
    if plate_type == PLATE_VARIANT_UNIVERSAL:
        doc.layers.add("DASHED_CUTS", color=8)  # gray
        if "DASHED" not in doc.linetypes:
            doc.linetypes.add("DASHED", pattern=[0.5, 0.25, -0.25])

    msp = doc.modelspace()

    # Get switches - use all if layout not configured
    if layout and layout.groups:
        active_refs = layout.get_active_switch_refs()
        switches = [c for c in pcb.get_switches() if c.ref in active_refs]
    else:
        switches = pcb.get_switches()

    # If no switches detected by rules, use all components as fallback
    if not switches:
        switches = list(pcb.components)

    # Compute avoidance zone
    avoidance = compute_avoidance_zone(avoidance_polygons, layer_config) if avoidance_polygons else None

    # Draw board outline
    if pcb.board_outline and pcb.board_outline.is_valid():
        outline_points = pcb.board_outline.vertices
        msp.add_lwpolyline(outline_points + [outline_points[0]], dxfattribs={"layer": "OUTLINE"})

    # Draw screw holes
    for hole in pcb.screw_holes:
        msp.add_circle(
            (hole.x, hole.y), hole.diameter / 2,
            dxfattribs={"layer": "SCREW_HOLES"},
        )

    # Detect stabilizers based on switch positions
    stab_positions = _detect_stabilizers(switches, plate_type)

    # Draw switch cutouts
    for sw in switches:
        cx, cy = sw.x, sw.y
        hw, hh = cutout_size[0] / 2, cutout_size[1] / 2

        cutout = box(cx - hw, cy - hh, cx + hw, cy + hh)
        if avoidance is not None:
            cutout = subtract_avoidance(cutout, avoidance)

        _draw_polygon(msp, cutout, layer="SWITCH_CUTS")

    # Draw stabilizer cutouts
    for stab in stab_positions:
        _draw_stabilizer(msp, stab, layer="STAB_CUTS")

    # Draw dashed template for universal variant
    if plate_type == PLATE_VARIANT_UNIVERSAL:
        _draw_universal_dashed_template(msp, switches, stab_positions)

    doc.saveas(output_path)


def _detect_stabilizers(
    switches: list[Component],
    plate_type: str,
) -> list[StabilizerPosition]:
    """Detect stabilizer positions by finding switch pairs at known stab spacings.

    For each pair of switches in the same row, check if their distance matches
    a standard stabilizer spacing (within tolerance). All matching pairs are
    returned as stabilizer positions.
    """
    if not switches:
        return []

    # Sort switches by row (Y) then column (X)
    sorted_sw = sorted(switches, key=lambda s: (round(s.y, 0), s.x))

    # Group into rows
    rows: list[list[Component]] = []
    current_row: list[Component] = []
    last_y = None
    row_tolerance = 3.0  # mm

    for sw in sorted_sw:
        if last_y is None or abs(sw.y - last_y) > row_tolerance:
            if current_row:
                rows.append(current_row)
            current_row = [sw]
            last_y = sw.y
        else:
            current_row.append(sw)
    if current_row:
        rows.append(current_row)

    tolerance = 1.0  # mm tolerance for matching stab spacing

    # Build spacing map, filtering by plate_type
    # Exclude 2.75u (19.844mm) - too close to 1U spacing (19.05mm) to detect reliably
    spacings_to_check = {k: v for k, v in STAB_SPACING.items() if k != "2.75u"}
    if plate_type == PLATE_VARIANT_7U_ENTER:
        spacings_to_check.pop("6.25u", None)
    elif plate_type == PLATE_VARIANT_ANSI:
        spacings_to_check.pop("7u", None)

    stabs: list[StabilizerPosition] = []
    used_centers: set[tuple[float, float]] = set()

    for row in rows:
        if len(row) < 2:
            continue
        row.sort(key=lambda s: s.x)

        # For each stab size, find the widest pair matching that distance.
        # A stabilizer pair should span the widest key of that size.
        for stab_name, stab_dist in spacings_to_check.items():
            best: tuple[int, int, float, float] | None = None  # (i, j, cx, error)
            best_span = 0

            for i in range(len(row)):
                for j in range(i + 1, len(row)):
                    dist = row[j].x - row[i].x
                    error = abs(dist - stab_dist)
                    if error < tolerance:
                        # Verify switches exist between i and j (confirms wide key)
                        if j - i >= 2:
                            span = j - i
                            if span > best_span or (span == best_span and best and error < best[3]):
                                cx = (row[i].x + row[j].x) / 2
                                best = (i, j, cx, error)
                                best_span = span

            if best:
                _, _, cx, error = best
                cy = row[0].y
                key = (round(cx, 1), round(cy, 1))
                if key not in used_centers:
                    used_centers.add(key)
                    stabs.append(StabilizerPosition(
                        switch_x=cx,
                        switch_y=cy,
                        key_size=stab_name,
                        orientation="horizontal",
                    ))

    return stabs


def _get_stab_size(key_units: float, plate_type: str) -> Optional[str]:
    """Determine stabilizer size for a key of given width."""
    if key_units >= 6.75:
        if plate_type == PLATE_VARIANT_7U_ENTER:
            return "7u"
        return "6.25u"
    elif key_units >= 2.5:
        return "2.75u"
    elif key_units >= 2.1:
        return "2.25u"
    elif key_units >= 1.8:
        return "2u"
    return None


def _draw_stabilizer(
    msp,
    stab: StabilizerPosition,
    layer: str = "STAB_CUTS",
) -> None:
    """Draw stabilizer cutouts (wire holes + insert rectangles)."""
    spacing = STAB_SPACING.get(stab.key_size, 0)
    if spacing == 0:
        return

    if stab.orientation == "horizontal":
        dx, dy = spacing, 0
    else:
        dx, dy = 0, spacing

    # Left/Top stab
    lx, ly = stab.switch_x - dx, stab.switch_y - dy
    # Right/Bottom stab
    rx, ry = stab.switch_x + dx, stab.switch_y + dy

    for sx, sy in [(lx, ly), (rx, ry)]:
        # Wire hole
        msp.add_circle((sx, sy), STAB_WIRE_RADIUS, dxfattribs={"layer": layer})
        # Insert cutout
        hw, hh = STAB_INSERT_W / 2, STAB_INSERT_H / 2
        msp.add_lwpolyline(
            [(sx - hw, sy - hh), (sx + hw, sy - hh), (sx + hw, sy + hh),
             (sx - hw, sy + hh), (sx - hw, sy - hh)],
            dxfattribs={"layer": layer},
        )


def _draw_universal_dashed_template(
    msp,
    switches: list[Component],
    stabs: list[StabilizerPosition],
) -> None:
    """Draw dashed lines for optional cut positions in universal template.

    Marks all possible stab positions and variant-specific switch positions
    with dashed lines so users can cut along them for their specific layout.
    """
    # Draw dashed circles at all stab wire positions
    for stab in stabs:
        spacing = STAB_SPACING.get(stab.key_size, 0)
        if spacing == 0:
            continue

        if stab.orientation == "horizontal":
            dx, dy = spacing, 0
        else:
            dx, dy = 0, spacing

        for sx, sy in [(stab.switch_x - dx, stab.switch_y - dy),
                       (stab.switch_x + dx, stab.switch_y + dy)]:
            msp.add_circle(
                (sx, sy), STAB_WIRE_RADIUS,
                dxfattribs={"layer": "DASHED_CUTS", "linetype": "DASHED"},
            )
            hw, hh = STAB_INSERT_W / 2, STAB_INSERT_H / 2
            msp.add_lwpolyline(
                [(sx - hw, sy - hh), (sx + hw, sy - hh), (sx + hw, sy + hh),
                 (sx - hw, sy + hh), (sx - hw, sy - hh)],
                dxfattribs={"layer": "DASHED_CUTS", "linetype": "DASHED"},
            )


def _draw_polygon(msp, poly: Polygon, layer: str = "0") -> None:
    """Draw a Shapely polygon as a polyline in DXF."""
    if poly.is_empty:
        return
    coords = list(poly.exterior.coords)
    if coords:
        msp.add_lwpolyline(coords, dxfattribs={"layer": layer})
    # Handle holes (interior rings from avoidance subtraction)
    for interior in poly.interiors:
        hole_coords = list(interior.coords)
        if hole_coords:
            msp.add_lwpolyline(hole_coords, dxfattribs={"layer": layer})
