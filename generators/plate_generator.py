"""Generate positioning plate DXF with switch cutouts, stab holes, and avoidance."""
from __future__ import annotations

from dataclasses import dataclass
import ezdxf
from shapely.geometry import Polygon, box, Point

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


def _mirror_x(value: float, center: float) -> float:
    """Mirror X coordinate about center."""
    return 2 * center - value


def generate_plate(
    pcb: PCBData,
    layout: LayoutConfig,
    layer_config: FoamLayerConfig,
    avoidance_polygons: list[AvoidancePolygon],
    output_path: str,
    cutout_size: tuple[float, float] = (MX_CUTOUT_W, MX_CUTOUT_H),
    corner_radius: float = MX_CORNER_RADIUS,
    plate_type: str = PLATE_VARIANT_UNIVERSAL,
    mirror_x: bool = False,
) -> None:
    """Generate a positioning plate DXF file.

    Args:
        plate_type: "ansi", "7u_enter", or "universal"
        mirror_x: If True, mirror X coordinates to flip horizontal direction.
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

    # Get switches - use all switches if layout doesn't specify specific refs
    switches = pcb.get_switches()
    if layout and layout.groups:
        active_refs = layout.get_active_switch_refs()
        if active_refs:
            switches = [c for c in switches if c.ref in active_refs]

    # Compute avoidance zone
    avoidance = compute_avoidance_zone(avoidance_polygons, layer_config) if avoidance_polygons else None

    # Compute mirror center from board outline bounds
    mirror_center = 0.0
    if mirror_x and pcb.board_outline and pcb.board_outline.is_valid():
        xs = [v[0] for v in pcb.board_outline.vertices]
        mirror_center = (min(xs) + max(xs)) / 2

    # Draw board outline (directly from outline layer tracks and arcs)
    if pcb.outline_tracks or pcb.outline_arcs:
        for track in pcb.outline_tracks:
            x1 = _mirror_x(track.x1, mirror_center) if mirror_x else track.x1
            x2 = _mirror_x(track.x2, mirror_center) if mirror_x else track.x2
            msp.add_line((x1, track.y1), (x2, track.y2), dxfattribs={"layer": "OUTLINE"})
        for arc in pcb.outline_arcs:
            cx = _mirror_x(arc.cx, mirror_center) if mirror_x else arc.cx
            if mirror_x:
                sa, ea = 180 - arc.end_angle, 180 - arc.start_angle
            else:
                sa, ea = arc.start_angle, arc.end_angle
            msp.add_arc((cx, arc.cy), arc.radius, start_angle=sa, end_angle=ea,
                        dxfattribs={"layer": "OUTLINE"})
    elif pcb.board_outline and pcb.board_outline.is_valid():
        outline_points = pcb.board_outline.vertices
        if mirror_x:
            outline_points = [(_mirror_x(v[0], mirror_center), v[1]) for v in outline_points]
        msp.add_lwpolyline(outline_points + [outline_points[0]], dxfattribs={"layer": "OUTLINE"})

    # Draw screw holes
    for hole in pcb.screw_holes:
        hx = _mirror_x(hole.x, mirror_center) if mirror_x else hole.x
        msp.add_circle(
            (hx, hole.y), hole.diameter / 2,
            dxfattribs={"layer": "SCREW_HOLES"},
        )

    # Detect stabilizers based on switch positions
    stab_positions = _detect_stabilizers(switches, plate_type)

    # Draw switch cutouts
    for sw in switches:
        cx = _mirror_x(sw.x, mirror_center) if mirror_x else sw.x
        cy = sw.y
        hw, hh = cutout_size[0] / 2, cutout_size[1] / 2

        cutout = box(cx - hw, cy - hh, cx + hw, cy + hh)
        if avoidance is not None:
            cutout = subtract_avoidance(cutout, avoidance)

        _draw_polygon(msp, cutout, layer="SWITCH_CUTS")

    # Draw stabilizer cutouts
    for stab in stab_positions:
        if mirror_x:
            stab = StabilizerPosition(
                switch_x=_mirror_x(stab.switch_x, mirror_center),
                switch_y=stab.switch_y,
                key_size=stab.key_size,
                orientation=stab.orientation,
            )
        _draw_stabilizer(msp, stab, layer="STAB_CUTS")

    # Draw dashed template for universal variant
    if plate_type == PLATE_VARIANT_UNIVERSAL:
        _draw_universal_dashed_template(msp, switches, stab_positions, mirror_x, mirror_center)

    doc.saveas(output_path)


def _detect_stabilizers(
    switches: list[Component],
    plate_type: str,
) -> list[StabilizerPosition]:
    """Detect stabilizer positions from switch layout.

    Note: automatic stabilizer detection from switch positions alone is unreliable
    because stabilizer wire holes are placed INSIDE the key area (7-10mm from
    key edge), not at switch positions. For example, a 6.25u spacebar's stab
    holes at +-50mm from center don't align with any switch pair distance.

    Returns an empty list. Users should add stabilizer positions manually
    via the plate editor if needed.
    """
    return []


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
    mirror_x: bool = False,
    mirror_center: float = 0.0,
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

        stab_cx = _mirror_x(stab.switch_x, mirror_center) if mirror_x else stab.switch_x
        stab_cy = stab.switch_y

        if stab.orientation == "horizontal":
            dx, dy = spacing, 0
        else:
            dx, dy = 0, spacing

        for sx, sy in [(stab_cx - dx, stab_cy - dy),
                       (stab_cx + dx, stab_cy + dy)]:
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
