"""Altium Designer ASCII PCB file parser.

Supports only ASCII format .PcbDoc files. Binary files are rejected.

The Altium ASCII PCB format uses a pipe-delimited record structure:
    |RECORD=...|FIELD1=VALUE1|FIELD2=VALUE2|

Key record types:
    - Component: placed footprints (switches, ICs, etc.)
    - Pad: pads belonging to components
    - Track: line segments (board outline, traces)
    - Arc: arc segments
    - Via: vias (used for screw hole detection)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from models.pcb_data import (
    Component, Pad, TrackSegment, ArcSegment, ScrewHole, BoardOutline, PCBData,
)


def validate_ascii_pcb(file_path: str) -> tuple[bool, str]:
    """Check if file is a valid Altium ASCII PCB file.

    Returns (is_valid, error_message).
    """
    path = Path(file_path)
    if not path.exists():
        return False, f"文件不存在: {file_path}"
    if path.suffix.lower() not in (".pcbdoc", ".pcbdoc", ".pcb"):
        return False, "请选择 .PcbDoc 文件"

    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
    except OSError as e:
        return False, f"无法读取文件: {e}"

    # Binary detection: null bytes in first 4KB
    if b"\x00" in header:
        return False, "此文件为二进制格式，请在 Altium Designer 中另存为 ASCII 格式"

    # Check for ASCII PCB header markers
    text = header.decode("ascii", errors="replace")
    if "|PCB|" not in text and "|FILEVERSION|" not in text:
        return False, "无法识别 Altium ASCII PCB 格式，请确认文件格式"

    return True, ""


def _parse_record(line: str) -> dict[str, str]:
    """Parse a pipe-delimited Altium record into a dict."""
    fields = {}
    for segment in line.split("|"):
        if "=" in segment:
            key, _, value = segment.partition("=")
            key = key.strip()
            if key:
                fields[key] = value.strip()
    return fields


def _rotation_matrix(angle_deg: float) -> tuple[float, float, float, float]:
    """Return (cos, sin, -sin, cos) for rotation."""
    import math
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return c, s, -s, c


def _transform_point(px: float, py: float, ox: float, oy: float,
                     angle_deg: float) -> tuple[float, float]:
    """Rotate point (px, py) by angle around origin, then translate by (ox, oy)."""
    c, s, ns, c2 = _rotation_matrix(angle_deg)
    rx = px * c + py * ns
    ry = px * s + py * c2
    return rx + ox, ry + oy


class AltiumASCIIParser:
    """Parser for Altium Designer ASCII PCB files."""

    def __init__(self):
        self._components: dict[int, dict] = {}  # owner_index -> component data
        self._pads: list[dict] = []
        self._tracks: list[dict] = []
        self._arcs: list[dict] = []
        self._vias: list[dict] = []
        self._board_outline_tracks: list[dict] = []

    def parse(self, file_path: str) -> PCBData:
        """Parse an Altium ASCII PCB file into PCBData."""
        valid, err = validate_ascii_pcb(file_path)
        if not valid:
            raise ValueError(err)

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|"):
                    continue
                self._process_line(line)

        return self._build_pcb_data(file_path)

    def _process_line(self, line: str) -> None:
        rec = _parse_record(line)
        record_type = rec.get("RECORD", "")

        if record_type == "Component":
            self._handle_component(rec)
        elif record_type == "Pad":
            self._handle_pad(rec)
        elif record_type == "Track":
            self._handle_track(rec)
        elif record_type == "Arc":
            self._handle_arc(rec)
        elif record_type == "Via":
            self._handle_via(rec)

    def _handle_component(self, rec: dict) -> None:
        # In Altium ASCII, components have an index used as owner for child pads
        idx = int(rec.get("INDEX", 0))
        # Coordinates: altium uses 0.01mil units → convert to mm (1 mil = 0.0254mm)
        x = self._to_mm(rec.get("X", "0"))
        y = self._to_mm(rec.get("Y", "0"))
        rotation = float(rec.get("ROTATION", "0"))
        ref = rec.get("COMPONENTDESCRIPTION", "") or rec.get("TEXTINFO", "") or rec.get("NAME", "")
        footprint = rec.get("PATTERN", rec.get("FOOTPRINT", ""))
        layer = rec.get("LAYER", "")

        self._components[idx] = {
            "x": x, "y": y, "rotation": rotation,
            "ref": ref, "footprint": footprint, "layer": layer,
        }

    def _handle_pad(self, rec: dict) -> None:
        owner = int(rec.get("OWNER", -1))
        x = self._to_mm(rec.get("X", "0"))
        y = self._to_mm(rec.get("Y", "0"))
        xsize = self._to_mm(rec.get("XSIZE", "0"))
        ysize = self._to_mm(rec.get("YSIZE", "0"))
        shape = rec.get("SHAPE", "RECTANGLE")
        hole = self._to_mm(rec.get("HOLESIZE", "0"))

        pad = {"owner": owner, "x": x, "y": y, "xsize": xsize, "ysize": ysize,
               "shape": shape, "hole": hole}
        self._pads.append(pad)

    def _handle_track(self, rec: dict) -> None:
        x1 = self._to_mm(rec.get("X1", "0"))
        y1 = self._to_mm(rec.get("Y1", "0"))
        x2 = self._to_mm(rec.get("X2", "0"))
        y2 = self._to_mm(rec.get("Y2", "0"))
        layer = rec.get("LAYER", "")
        width = self._to_mm(rec.get("WIDTH", "0"))

        track = {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                 "layer": layer, "width": width}
        self._tracks.append(track)

    def _handle_arc(self, rec: dict) -> None:
        cx = self._to_mm(rec.get("X", "0"))
        cy = self._to_mm(rec.get("Y", "0"))
        radius = self._to_mm(rec.get("RADIUS", "0"))
        start = float(rec.get("STARTANGLE", "0"))
        end = float(rec.get("ENDANGLE", "360"))
        layer = rec.get("LAYER", "")

        self._arcs.append({"cx": cx, "cy": cy, "radius": radius,
                           "start_angle": start, "end_angle": end, "layer": layer})

    def _handle_via(self, rec: dict) -> None:
        x = self._to_mm(rec.get("X", "0"))
        y = self._to_mm(rec.get("Y", "0"))
        holesize = self._to_mm(rec.get("HOLESIZE", "0"))

        self._vias.append({"x": x, "y": y, "holesize": holesize})

    def _build_pcb_data(self, file_path: str) -> PCBData:
        # Build components with their pads
        components = []
        pad_by_owner: dict[int, list[dict]] = {}
        for p in self._pads:
            owner = p["owner"]
            if owner not in pad_by_owner:
                pad_by_owner[owner] = []
            pad_by_owner[owner].append(p)

        for idx, cdata in self._components.items():
            comp = Component(
                ref=cdata["ref"],
                footprint_name=cdata["footprint"],
                x=cdata["x"], y=cdata["y"],
                rotation=cdata["rotation"],
            )
            # Attach pads, transforming relative coords to absolute
            for pdata in pad_by_owner.get(idx, []):
                # Pad coordinates may be relative to component origin
                # If pad coords match component coords, they're absolute
                pad_x = pdata["x"]
                pad_y = pdata["y"]
                pad_w = pdata["xsize"]
                pad_h = pdata["ysize"]
                shape = "circle" if pdata["shape"] == "ROUND" else "rect"

                comp.pads.append(Pad(
                    x=pad_x, y=pad_y, width=pad_w, height=pad_h,
                    shape=shape, hole_diameter=pdata["hole"],
                ))
            components.append(comp)

        # Build tracks
        tracks = [
            TrackSegment(t["x1"], t["y1"], t["x2"], t["y2"], t["layer"], t["width"])
            for t in self._tracks
        ]

        # Build arcs
        arcs = [
            ArcSegment(a["cx"], a["cy"], a["radius"], a["start_angle"], a["end_angle"], a["layer"])
            for a in self._arcs
        ]

        # Detect board outline from outline/keepout layer tracks
        outline = self._extract_board_outline()

        # Detect screw holes: large vias or pads on mechanical layers
        screw_holes = self._extract_screw_holes()

        return PCBData(
            components=components,
            raw_tracks=tracks,
            raw_arcs=arcs,
            board_outline=outline,
            screw_holes=screw_holes,
            source_file=str(file_path),
        )

    def _extract_board_outline(self) -> Optional[BoardOutline]:
        """Try to extract board outline from tracks on outline/keepout layers."""
        outline_layers = {"outline", "keepout", "mechanical1", "mechanical 1",
                          "board outline"}
        outline_tracks = [
            t for t in self._tracks
            if t["layer"].lower() in outline_layers
        ]

        if len(outline_tracks) < 3:
            return None

        # Chain tracks into a polygon by connecting endpoints
        vertices = self._chain_tracks(outline_tracks)
        if vertices and len(vertices) >= 3:
            return BoardOutline(vertices=vertices, source="auto")
        return None

    def _extract_screw_holes(self) -> list[ScrewHole]:
        """Detect screw holes from large vias."""
        screw_holes = []
        for v in self._vias:
            hole = v["holesize"]
            # Typical M2 screw hole: ~2.2mm, M2.5: ~2.7mm
            if hole >= 1.5:
                screw_holes.append(ScrewHole(
                    x=v["x"], y=v["y"], diameter=hole, source="auto",
                ))
        return screw_holes

    @staticmethod
    def _chain_tracks(tracks: list[dict], tolerance: float = 0.01) -> list[tuple[float, float]]:
        """Chain track segments into a closed polygon by connecting endpoints."""
        if not tracks:
            return []

        remaining = list(tracks)
        vertices = [(remaining[0]["x1"], remaining[0]["y1"])]
        current_end = (remaining[0]["x2"], remaining[0]["y2"])
        remaining.pop(0)

        max_iter = len(tracks) + 1
        for _ in range(max_iter):
            if not remaining:
                break
            found = False
            for i, t in enumerate(remaining):
                # Try forward connection
                if (abs(t["x1"] - current_end[0]) < tolerance and
                        abs(t["y1"] - current_end[1]) < tolerance):
                    vertices.append(current_end)
                    current_end = (t["x2"], t["y2"])
                    remaining.pop(i)
                    found = True
                    break
                # Try reverse connection
                if (abs(t["x2"] - current_end[0]) < tolerance and
                        abs(t["y2"] - current_end[1]) < tolerance):
                    vertices.append(current_end)
                    current_end = (t["x1"], t["y1"])
                    remaining.pop(i)
                    found = True
                    break
            if not found:
                break

        vertices.append(current_end)
        return vertices

    @staticmethod
    def _to_mm(value: str) -> float:
        """Convert Altium coordinate units to millimeters.

        Altium ASCII uses 0.01mil (10^-5 inches) for coordinates.
        Some fields may already be in mm. We detect by magnitude.
        """
        try:
            v = float(value)
        except (ValueError, TypeError):
            return 0.0
        # Altium PCB ASCII coordinates are in 0.01mil units
        # 1 mil = 0.0254mm, so 0.01mil = 0.000254mm
        # Typical PCB is ~300mm, so in 0.01mil units that's ~1,181,100
        # If value is large (>10000), assume it's in 0.01mil units
        if abs(v) > 10000:
            return v * 0.000254
        # Otherwise assume mm already
        return v
