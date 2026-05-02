"""Generate foam layer DXF files with per-layer cutout patterns."""
from __future__ import annotations

import math
import ezdxf
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union

from models.pcb_data import PCBData
from models.layout_group import LayoutConfig
from models.layer_config import FoamLayerConfig
from models.avoidance import AvoidancePolygon
from avoidance.avoidance_engine import compute_avoidance_zone, subtract_avoidance


def generate_foam_layer(
    pcb: PCBData,
    layout: LayoutConfig,
    layer_config: FoamLayerConfig,
    avoidance_polygons: list[AvoidancePolygon],
    output_path: str,
    universal_mode: bool = True,
) -> None:
    """Generate a single foam layer DXF file.

    Args:
        universal_mode: If True, all switches get cutouts regardless of layout
                        selection, and dashed lines mark variant boundaries.
    """
    doc = ezdxf.new("R2010")

    # Create layers
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("SCREW_HOLES", color=5)
    doc.layers.add("CUTS", color=1)

    # Add dashed linetype for universal template
    doc.layers.add("DASHED_CUTS", color=8)
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern=[0.5, 0.25, -0.25])

    msp = doc.modelspace()

    # Compute avoidance zone for this layer
    avoidance = compute_avoidance_zone(avoidance_polygons, layer_config) if avoidance_polygons else None

    # Draw board outline
    if pcb.board_outline and pcb.board_outline.is_valid():
        outline_points = pcb.board_outline.vertices
        msp.add_lwpolyline(
            outline_points + [outline_points[0]],
            dxfattribs={"layer": "OUTLINE"},
        )

    # Draw screw holes
    for hole in pcb.screw_holes:
        msp.add_circle(
            (hole.x, hole.y), hole.diameter / 2,
            dxfattribs={"layer": "SCREW_HOLES"},
        )

    # Get switches - use all in universal mode
    if universal_mode:
        switches = pcb.get_switches()
        if not switches:
            switches = list(pcb.components)
    else:
        active_refs = layout.get_active_switch_refs() if layout and layout.groups else set()
        switches = [c for c in pcb.get_switches() if c.ref in active_refs] if active_refs else pcb.get_switches()

    # Generate cutouts based on layer type
    cutout_type = layer_config.cutout_type
    size = layer_config.cutout_size

    if cutout_type == "rect":
        _generate_rect_cutouts(msp, switches, size, avoidance)
    elif cutout_type == "circle_small":
        _generate_circle_cutouts(msp, switches, size, avoidance)
    elif cutout_type == "solid":
        pass  # No switch cutouts for solid layers
    elif cutout_type == "circle_large":
        _generate_sparse_circles(msp, pcb, size, avoidance)
    elif cutout_type == "circle_dense":
        _generate_dense_circles(msp, pcb, size, avoidance)

    doc.saveas(output_path)


def _generate_rect_cutouts(msp, switches, size: float,
                           avoidance: Polygon | None) -> None:
    """Generate rectangular cutouts at each switch position."""
    hw = size / 2
    for sw in switches:
        cutout = box(sw.x - hw, sw.y - hw, sw.x + hw, sw.y + hw)
        if avoidance is not None:
            cutout = subtract_avoidance(cutout, avoidance)
        _draw_polygon(msp, cutout, layer="CUTS")


def _generate_circle_cutouts(msp, switches, diameter: float,
                             avoidance: Polygon | None) -> None:
    """Generate small circle cutouts at each switch center."""
    r = diameter / 2
    for sw in switches:
        if avoidance is not None:
            pt = Point(sw.x, sw.y)
            if not avoidance.contains(pt):
                msp.add_circle((sw.x, sw.y), r, dxfattribs={"layer": "CUTS"})
        else:
            msp.add_circle((sw.x, sw.y), r, dxfattribs={"layer": "CUTS"})


def _generate_sparse_circles(msp, pcb: PCBData, diameter: float,
                              avoidance: Polygon | None) -> None:
    """Generate large sparse circles in a grid pattern within the board outline."""
    if not pcb.board_outline or not pcb.board_outline.is_valid():
        return

    outline_poly = Polygon(pcb.board_outline.vertices)
    if not outline_poly.is_valid:
        outline_poly = outline_poly.buffer(0)

    r = diameter / 2
    spacing = diameter * 3  # sparse spacing

    min_x, min_y, max_x, max_y = outline_poly.bounds
    x = min_x + spacing
    while x < max_x:
        y = min_y + spacing
        while y < max_y:
            pt = Point(x, y)
            if outline_poly.contains(pt):
                if avoidance is None or not avoidance.contains(pt):
                    msp.add_circle((x, y), r, dxfattribs={"layer": "CUTS"})
            y += spacing
        x += spacing


def _generate_dense_circles(msp, pcb: PCBData, diameter: float,
                             avoidance: Polygon | None) -> None:
    """Generate dense small circles covering the board area."""
    if not pcb.board_outline or not pcb.board_outline.is_valid():
        return

    outline_poly = Polygon(pcb.board_outline.vertices)
    if not outline_poly.is_valid:
        outline_poly = outline_poly.buffer(0)

    r = diameter / 2
    spacing = diameter * 1.5  # dense spacing

    min_x, min_y, max_x, max_y = outline_poly.bounds
    x = min_x + spacing
    while x < max_x:
        y = min_y + spacing
        while y < max_y:
            pt = Point(x, y)
            if outline_poly.contains(pt):
                if avoidance is None or not avoidance.contains(pt):
                    msp.add_circle((x, y), r, dxfattribs={"layer": "CUTS"})
            y += spacing
        x += spacing


def _draw_polygon(msp, poly: Polygon, layer: str = "0") -> None:
    """Draw a Shapely polygon as a polyline in DXF."""
    if poly.is_empty:
        return
    coords = list(poly.exterior.coords)
    if coords:
        msp.add_lwpolyline(coords, dxfattribs={"layer": layer})
    for interior in poly.interiors:
        hole_coords = list(interior.coords)
        if hole_coords:
            msp.add_lwpolyline(hole_coords, dxfattribs={"layer": layer})
