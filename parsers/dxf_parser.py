"""DXF file parser for board outline and screw hole import."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import ezdxf

from models.pcb_data import BoardOutline, ScrewHole


def parse_board_outline_dxf(file_path: str) -> tuple[Optional[BoardOutline], list[ScrewHole]]:
    """Parse a DXF file to extract board outline and screw holes.

    Returns:
        (BoardOutline, list[ScrewHole]) - board outline may be None if not found.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"DXF file not found: {file_path}")
    if path.suffix.lower() != ".dxf":
        raise ValueError("Please select a .dxf file")

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()

    outline = _extract_board_outline(msp)
    screw_holes = _extract_screw_holes(msp)

    return outline, screw_holes


def _extract_board_outline(msp) -> Optional[BoardOutline]:
    """Extract the largest closed polyline as board outline."""
    best_polyline = None
    best_area = 0.0

    for entity in msp:
        if entity.dxftype() != "LWPOLYLINE":
            continue
        if not entity.closed:
            continue

        pts = list(entity.get_points())
        if len(pts) < 3:
            continue

        # Calculate bounding box area
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))

        if area > best_area:
            best_area = area
            best_polyline = entity

    if best_polyline is None:
        return None

    pts = list(best_polyline.get_points())
    vertices = [(p[0], p[1]) for p in pts]

    return BoardOutline(vertices=vertices, source="dxf_import")


def _extract_screw_holes(msp) -> list[ScrewHole]:
    """Extract circles as screw holes (r >= 1.0mm)."""
    holes = []

    for entity in msp:
        if entity.dxftype() != "CIRCLE":
            continue
        r = entity.dxf.radius
        if r >= 1.0:
            holes.append(ScrewHole(
                x=entity.dxf.center.x,
                y=entity.dxf.center.y,
                diameter=r * 2,
                source="dxf_import",
            ))

    return holes
