"""Generate positioning plate DXF with switch cutouts, stab holes, and avoidance."""
from __future__ import annotations

import ezdxf
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from models.pcb_data import PCBData, ScrewHole
from models.layout_group import LayoutConfig
from models.layer_config import FoamLayerConfig
from models.avoidance import AvoidancePolygon
from avoidance.avoidance_engine import compute_avoidance_zone, subtract_avoidance


# Standard MX switch cutout dimensions (mm)
MX_CUTOUT_W = 14.0
MX_CUTOUT_H = 14.0
MX_CORNER_RADIUS = 0.5

# Stabilizer cutout dimensions (mm)
STAB_WIRE_WIDTH = 3.0
STAB_INSERT_W = 7.0
STAB_INSERT_H = 4.5

# Stab spacing for common key sizes (mm from switch center)
STAB_SPACING = {
    "2u": 11.938,
    "2.25u": 15.875,
    "2.75u": 19.844,
    "6.25u": 50.0,
    "7u": 57.15,
}


def generate_plate(
    pcb: PCBData,
    layout: LayoutConfig,
    layer_config: FoamLayerConfig,
    avoidance_polygons: list[AvoidancePolygon],
    output_path: str,
    cutout_size: tuple[float, float] = (MX_CUTOUT_W, MX_CUTOUT_H),
    corner_radius: float = MX_CORNER_RADIUS,
) -> None:
    """Generate a positioning plate DXF file."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Get active switches from layout
    active_refs = layout.get_active_switch_refs()
    switches = [c for c in pcb.get_switches() if c.ref in active_refs]

    # Compute avoidance zone for this layer
    avoidance = compute_avoidance_zone(avoidance_polygons, layer_config)

    # Draw board outline
    if pcb.board_outline and pcb.board_outline.is_valid():
        outline_points = pcb.board_outline.vertices
        msp.add_lwpolyline(outline_points + [outline_points[0]], dxfattribs={"layer": "OUTLINE"})

    # Draw screw holes
    for hole in pcb.screw_holes:
        msp.add_circle(
            (hole.x, hole.y), hole.diameter / 2,
            dxfattribs={"layer": "SCREW_HOOLS"},
        )

    # Draw switch cutouts
    for sw in switches:
        cx, cy = sw.x, sw.y
        hw, hh = cutout_size[0] / 2, cutout_size[1] / 2

        # Create cutout polygon
        cutout = box(cx - hw, cy - hh, cx + hw, cy + hh)

        # Subtract avoidance if needed
        if avoidance is not None:
            cutout = subtract_avoidance(cutout, avoidance)

        _draw_polygon(msp, cutout, layer="SWITCH_CUTS")

    # TODO: Add stabilizer cutouts for keys >= 2U
    # This requires key size information from layout config

    doc.saveas(output_path)


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
