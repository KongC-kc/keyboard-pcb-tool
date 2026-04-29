"""Auto-detect suspected IC/component positions for avoidance."""
from __future__ import annotations

import re
from models.pcb_data import Component
from models.avoidance import AvoidancePolygon

# Ref designator patterns for ICs
_IC_PATTERNS = [
    re.compile(r"^U\d+$", re.IGNORECASE),
    re.compile(r"^IC\d+$", re.IGNORECASE),
    re.compile(r"^MCU\d*$", re.IGNORECASE),
    re.compile(r"^USB\d*$", re.IGNORECASE),
    re.compile(r"^REG\d*$", re.IGNORECASE),
]

# Ref designator patterns for large passive components (may need avoidance)
_LARGE_PASSIVE_PATTERNS = [
    re.compile(r"^C\d+$", re.IGNORECASE),  # capacitors (check size)
    re.compile(r"^R\d+$", re.IGNORECASE),  # resistors (usually small)
    re.compile(r"^L\d+$", re.IGNORECASE),  # inductors (often large)
    re.compile(r"^D\d+$", re.IGNORECASE),  # diodes
]

# Minimum pad span to consider a component "large" enough for avoidance
_MIN_SPAN_MM = 3.0


def detect_suspected_avoidance(
    components: list[Component],
) -> list[AvoidancePolygon]:
    """Detect suspected IC/component positions that may need avoidance zones.

    Returns a list of AvoidancePolygon with confidence="suspected".
    User should confirm/adjust in GUI.
    """
    results = []

    for comp in components:
        if comp.classification == "switch":
            continue

        is_ic = any(p.match(comp.ref) for p in _IC_PATTERNS)
        is_large_passive = any(p.match(comp.ref) for p in _LARGE_PASSIVE_PATTERNS)

        if not is_ic and not is_large_passive:
            continue

        # Compute bounding polygon from pads
        bbox = comp.bounding_box()
        x1, y1, x2, y2 = bbox
        span_x = x2 - x1
        span_y = y2 - y1

        if not is_ic and max(span_x, span_y) < _MIN_SPAN_MM:
            continue

        # Build rectangle vertices (considering rotation)
        vertices = _rotated_rect(comp.x, comp.y, span_x, span_y, comp.rotation)

        label = comp.ref
        if is_ic:
            label += " (IC)"
        else:
            label += f" ({max(span_x, span_y):.1f}mm)"

        results.append(AvoidancePolygon(
            vertices=vertices,
            confidence="suspected",
            source="auto",
            label=label,
        ))

    return results


def _rotated_rect(cx: float, cy: float, w: float, h: float,
                  angle_deg: float) -> list[tuple[float, float]]:
    """Return 4 corners of a rotated rectangle centered at (cx, cy)."""
    import math
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    hw, hh = w / 2, h / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [(cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a)
            for x, y in corners]
