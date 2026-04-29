"""Detect candidate split zones where multiple switches occupy the same key grid position."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from models.pcb_data import Component


# Standard key spacing: 19.05mm (0.75in) = 1U
KEY_SPACING = 19.05
# Tolerance for grid alignment
GRID_TOLERANCE = 3.0  # mm


@dataclass
class CandidateZone:
    """A zone where multiple switches may be alternatives (split positions)."""
    grid_col: int
    grid_row: int
    switches: list[Component] = field(default_factory=list)
    center_x: float = 0.0
    center_y: float = 0.0

    @property
    def description(self) -> str:
        return f"Grid({self.grid_col},{self.grid_row}): {len(self.switches)} switches"


def find_candidate_split_zones(
    switches: list[Component],
) -> list[CandidateZone]:
    """Find grid cells containing multiple switches (candidate split zones).

    Assigns each switch to a grid cell based on 19.05mm spacing.
    Cells with 2+ switches are returned as candidates.
    """
    if not switches:
        return []

    # Find grid origin (top-left switch position)
    min_x = min(s.x for s in switches)
    min_y = min(s.y for s in switches)

    # Assign switches to grid cells
    grid: dict[tuple[int, int], list[Component]] = {}
    for sw in switches:
        col = round((sw.x - min_x) / KEY_SPACING)
        row = round((sw.y - min_y) / KEY_SPACING)
        # Verify the switch is actually close to this grid cell center
        expected_x = min_x + col * KEY_SPACING
        expected_y = min_y + row * KEY_SPACING
        dist = math.hypot(sw.x - expected_x, sw.y - expected_y)
        if dist < GRID_TOLERANCE:
            key = (col, row)
            if key not in grid:
                grid[key] = []
            grid[key].append(sw)

    # Return cells with multiple switches
    candidates = []
    for (col, row), sw_list in grid.items():
        if len(sw_list) >= 2:
            cx = sum(s.x for s in sw_list) / len(sw_list)
            cy = sum(s.y for s in sw_list) / len(sw_list)
            candidates.append(CandidateZone(
                grid_col=col, grid_row=row,
                switches=sw_list, center_x=cx, center_y=cy,
            ))

    return sorted(candidates, key=lambda z: (z.grid_row, z.grid_col))
