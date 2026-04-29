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
) -> None:
    """Generate a single foam layer DXF file."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Compute avoidance zone for this layer
    avoidance = compute_avoidance_zone(avoidance_polygons, layer_config)

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

    # Get active switches
    active_refs = layout.get_active_switch_refs()
    switches = [c for c in pcb.get_switches() if c.ref in active_refs]

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
