"""Detect candidate split zones and layout templates from switch positions."""
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
        return f"网格({self.grid_col},{self.grid_row}): {len(self.switches)} 个轴体"


@dataclass
class SplitOption:
    """A split option for a specific key area."""
    key: str          # "enter", "lshift", "rshift", "backspace", "spacebar"
    label: str        # Display name
    options: list[str]  # Available variants
    recommended: int = 0  # Recommended variant index


@dataclass
class LayoutTemplate:
    """A detected layout template with applicable split options."""
    name: str              # e.g. "ANSI", "ISO", "七回"
    description: str       # Human-readable description
    split_options: list[SplitOption] = field(default_factory=list)
    recommended: bool = False  # Is this the recommended template?


def _try_grid_origin(
    switches: list[Component], origin_x: float, origin_y: float,
) -> dict[tuple[int, int], list[Component]]:
    """Try assigning switches to a grid with the given origin."""
    grid: dict[tuple[int, int], list[Component]] = {}
    for sw in switches:
        col = round((sw.x - origin_x) / KEY_SPACING)
        row = round((sw.y - origin_y) / KEY_SPACING)
        expected_x = origin_x + col * KEY_SPACING
        expected_y = origin_y + row * KEY_SPACING
        dist = math.hypot(sw.x - expected_x, sw.y - expected_y)
        if dist < GRID_TOLERANCE:
            key = (col, row)
            if key not in grid:
                grid[key] = []
            grid[key].append(sw)
    return grid


def _assign_to_grid(switches: list[Component]) -> dict[tuple[int, int], list[Component]]:
    """Assign switches to grid cells based on 19.05mm spacing.

    Tries multiple grid origins to handle PCBs where the first switch
    doesn't align to the grid origin (e.g. ZS60HE with ~7mm offset).
    """
    grid, _ = _assign_to_grid_with_origin(switches)
    return grid


def _assign_to_grid_with_origin(
    switches: list[Component],
) -> tuple[dict[tuple[int, int], list[Component]], tuple[float, float]]:
    """Assign switches to grid, returning both the grid and the origin used.

    Returns (grid, (origin_x, origin_y)).
    """
    if not switches:
        return {}, (0.0, 0.0)

    min_x = min(s.x for s in switches)
    min_y = min(s.y for s in switches)

    best_grid: dict[tuple[int, int], list[Component]] = {}
    best_count = 0
    best_origin = (min_x, min_y)

    step = KEY_SPACING / 4
    for dx in range(4):
        for dy in range(4):
            ox = min_x + dx * step
            oy = min_y + dy * step
            grid = _try_grid_origin(switches, ox, oy)
            count = sum(len(v) for v in grid.values())
            if count > best_count:
                best_count = count
                best_grid = grid
                best_origin = (ox, oy)

    return best_grid, best_origin


def find_candidate_split_zones(
    switches: list[Component],
) -> list[CandidateZone]:
    """Find grid cells containing multiple switches (candidate split zones)."""
    grid = _assign_to_grid(switches)

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


def detect_layout_templates(switches: list[Component]) -> list[LayoutTemplate]:
    """Detect applicable layout templates from switch positions.

    Analyzes the grid layout to determine:
    - Keyboard size (60%, 75%, TKL, etc.)
    - Which split options are physically possible
    - Recommended template based on switch count and positions
    """
    if not switches or len(switches) < 40:
        return []

    grid = _assign_to_grid(switches)
    if not grid:
        return []

    # Analyze grid dimensions
    all_cols = set(c for c, r in grid.keys())
    all_rows = set(r for c, r in grid.keys())
    num_rows = len(all_rows)
    max_col = max(all_cols)
    total_switches = len(switches)

    # Count switches per row
    row_counts: dict[int, int] = {}
    for (col, row), sw_list in grid.items():
        row_counts[row] = row_counts.get(row, 0) + len(sw_list)

    # Detect split zones (grid cells with 2+ switches)
    split_zones = {(c, r): sw for (c, r), sw in grid.items() if len(sw) >= 2}

    # ── Build templates ─────────────────────────────────────────────
    templates: list[LayoutTemplate] = []

    # Always offer ANSI (standard)
    ansi_splits = _detect_ansi_splits(grid, num_rows, max_col, split_zones)
    templates.append(LayoutTemplate(
        name="ANSI",
        description=f"标准 ANSI 配列 ({total_switches} 个轴体, {num_rows} 行)",
        split_options=ansi_splits,
        recommended=True,
    ))

    # Offer 7U enter if bottom row has enough space
    if num_rows >= 5:
        seven_u_splits = _detect_7u_splits(grid, num_rows, max_col, split_zones)
        templates.append(LayoutTemplate(
            name="七回 (7U Enter)",
            description=f"七字回车配列 ({total_switches} 个轴体)",
            split_options=seven_u_splits,
            recommended=False,
        ))

    # Offer ISO if row 2 (QWERTY row) has enough keys for ISO enter
    if num_rows >= 5 and row_counts.get(2, 0) >= 14:
        iso_splits = _detect_iso_splits(grid, num_rows, max_col, split_zones)
        templates.append(LayoutTemplate(
            name="ISO",
            description=f"ISO 配列 ({total_switches} 个轴体)",
            split_options=iso_splits,
            recommended=False,
        ))

    return templates


def _detect_ansi_splits(
    grid: dict, num_rows: int, max_col: int, split_zones: dict
) -> list[SplitOption]:
    """Detect ANSI-applicable split options."""
    options: list[SplitOption] = []

    # Enter: ANSI uses standard enter (no split needed)
    options.append(SplitOption("enter", "回车", ["标准回车"], 0))

    # Left Shift: check if row 3 has enough keys for split
    row3_count = sum(len(sw) for (c, r), sw in grid.items() if r == 3)
    if row3_count >= 14:
        options.append(SplitOption("lshift", "左Shift", ["标准 Shift (2.25U)", "分裂 Shift (1.25U + 1U)"], 0))
    else:
        options.append(SplitOption("lshift", "左Shift", ["标准 Shift (2.25U)"], 0))

    # Right Shift
    options.append(SplitOption("rshift", "右Shift", ["标准 Shift (2.75U)", "分裂 Shift (1.75U + 1U)"], 0))

    # Backspace
    options.append(SplitOption("backspace", "Backspace", ["标准 Backspace (2U)", "分裂 Backspace (1.5U + 1U)"], 0))

    # Spacebar: check bottom row
    row_last = num_rows - 1
    bottom_count = sum(len(sw) for (c, r), sw in grid.items() if r == row_last)
    has_split_zone_in_bottom = any(r == row_last for (c, r) in split_zones)

    if has_split_zone_in_bottom:
        options.append(SplitOption("spacebar", "空格", ["6.25U 空格", "7U 空格", "分裂空格"], 0))
    elif bottom_count >= 14:
        options.append(SplitOption("spacebar", "空格", ["6.25U 空格", "7U 空格"], 0))
    else:
        options.append(SplitOption("spacebar", "空格", ["6.25U 空格"], 0))

    return options


def _detect_7u_splits(
    grid: dict, num_rows: int, max_col: int, split_zones: dict
) -> list[SplitOption]:
    """Detect 7U enter split options."""
    options: list[SplitOption] = []
    options.append(SplitOption("enter", "回车", ["七字回车 (7U)"], 0))
    options.append(SplitOption("lshift", "左Shift", ["标准 Shift", "分裂 Shift"], 0))
    options.append(SplitOption("rshift", "右Shift", ["标准 Shift", "分裂 Shift"], 0))
    options.append(SplitOption("backspace", "Backspace", ["标准 Backspace", "分裂 Backspace"], 0))
    options.append(SplitOption("spacebar", "空格", ["7U 空格", "6.25U 空格"], 0))
    return options


def _detect_iso_splits(
    grid: dict, num_rows: int, max_col: int, split_zones: dict
) -> list[SplitOption]:
    """Detect ISO split options."""
    options: list[SplitOption] = []
    options.append(SplitOption("enter", "回车", ["ISO 大回车"], 0))
    options.append(SplitOption("lshift", "左Shift", ["ISO Shift (1.25U)"], 0))
    options.append(SplitOption("rshift", "右Shift", ["标准 Shift", "分裂 Shift"], 0))
    options.append(SplitOption("backspace", "Backspace", ["标准 Backspace", "分裂 Backspace"], 0))
    options.append(SplitOption("spacebar", "空格", ["6.25U 空格", "7U 空格"], 0))
    return options
