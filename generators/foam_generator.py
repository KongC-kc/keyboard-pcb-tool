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


def _mirror_x(value: float, center: float) -> float:
    """Mirror X coordinate about center."""
    return 2 * center - value


def generate_foam_layer(
    pcb: PCBData,
    layout: LayoutConfig,
    layer_config: FoamLayerConfig,
    avoidance_polygons: list[AvoidancePolygon],
    output_path: str,
    universal_mode: bool = True,
    mirror_x: bool = False,
) -> None:
    """Generate a single foam layer DXF file.

    Args:
        universal_mode: If True, all switches get cutouts regardless of layout
                        selection, and dashed lines mark variant boundaries.
        mirror_x: If True, mirror X coordinates to flip horizontal direction.
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
        msp.add_lwpolyline(
            outline_points + [outline_points[0]],
            dxfattribs={"layer": "OUTLINE"},
        )

    # Draw screw holes
    for hole in pcb.screw_holes:
        hx = _mirror_x(hole.x, mirror_center) if mirror_x else hole.x
        msp.add_circle(
            (hx, hole.y), hole.diameter / 2,
            dxfattribs={"layer": "SCREW_HOLES"},
        )

    # Get switches - always use all switches (layout refs used for plate only)
    switches = pcb.get_switches()

    # Generate cutouts based on layer type
    cutout_type = layer_config.cutout_type
    size = layer_config.cutout_size

    if cutout_type == "rect":
        _generate_rect_cutouts(msp, switches, size, avoidance, mirror_x, mirror_center)
    elif cutout_type == "circle_small":
        _generate_circle_cutouts(msp, switches, size, avoidance, mirror_x, mirror_center)
    elif cutout_type == "solid":
        pass  # No switch cutouts for solid layers
    elif cutout_type == "circle_large":
        _generate_sparse_circles(msp, pcb, size, avoidance, mirror_x, mirror_center)
    elif cutout_type == "circle_dense":
        _generate_dense_circles(msp, pcb, size, avoidance, mirror_x, mirror_center)

    doc.saveas(output_path)


def _generate_rect_cutouts(msp, switches, size: float,
                           avoidance: Polygon | None,
                           mirror_x: bool = False, mirror_center: float = 0.0) -> None:
    """Generate rectangular cutouts at each switch position."""
    hw = size / 2
    for sw in switches:
        sx = _mirror_x(sw.x, mirror_center) if mirror_x else sw.x
        cutout = box(sx - hw, sw.y - hw, sx + hw, sw.y + hw)
        if avoidance is not None:
            cutout = subtract_avoidance(cutout, avoidance)
        _draw_polygon(msp, cutout, layer="CUTS")


def _generate_circle_cutouts(msp, switches, diameter: float,
                             avoidance: Polygon | None,
                             mirror_x: bool = False, mirror_center: float = 0.0) -> None:
    """Generate small circle cutouts at each switch center."""
    r = diameter / 2
    for sw in switches:
        sx = _mirror_x(sw.x, mirror_center) if mirror_x else sw.x
        if avoidance is not None:
            pt = Point(sw.x, sw.y)
            if not avoidance.contains(pt):
                msp.add_circle((sx, sw.y), r, dxfattribs={"layer": "CUTS"})
        else:
            msp.add_circle((sx, sw.y), r, dxfattribs={"layer": "CUTS"})


def _generate_sparse_circles(msp, pcb: PCBData, diameter: float,
                              avoidance: Polygon | None,
                              mirror_x: bool = False, mirror_center: float = 0.0) -> None:
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
                    ox = _mirror_x(x, mirror_center) if mirror_x else x
                    msp.add_circle((ox, y), r, dxfattribs={"layer": "CUTS"})
            y += spacing
        x += spacing


def _generate_dense_circles(msp, pcb: PCBData, diameter: float,
                             avoidance: Polygon | None,
                             mirror_x: bool = False, mirror_center: float = 0.0) -> None:
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
                    ox = _mirror_x(x, mirror_center) if mirror_x else x
                    msp.add_circle((ox, y), r, dxfattribs={"layer": "CUTS"})
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
