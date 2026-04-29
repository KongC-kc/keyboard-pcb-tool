from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class Pad:
    x: float  # mm, absolute
    y: float
    width: float
    height: float
    shape: str = "rect"  # "rect" | "circle"
    hole_diameter: float = 0.0  # >0 if this is a thru-hole pad

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width,
                "height": self.height, "shape": self.shape,
                "hole_diameter": self.hole_diameter}

    @classmethod
    def from_dict(cls, d: dict) -> Pad:
        return cls(**d)


@dataclass
class Component:
    ref: str  # e.g. "SW1", "U1", "H1"
    footprint_name: str
    x: float  # mm
    y: float
    rotation: float  # degrees
    pads: list[Pad] = field(default_factory=list)
    classification: str = "unclassified"  # "switch" | "ic" | "mechanical" | "unclassified"
    classification_source: str = "none"  # "rule" | "manual" | "none"

    def bounding_box(self) -> tuple[float, float, float, float]:
        if not self.pads:
            return (self.x, self.y, self.x, self.y)
        xs = [p.x for p in self.pads]
        ys = [p.y for p in self.pads]
        hw = max(p.width / 2 for p in self.pads) if self.pads else 0
        hh = max(p.height / 2 for p in self.pads) if self.pads else 0
        return (min(xs) - hw, min(ys) - hh, max(xs) + hw, max(ys) + hh)

    def to_dict(self) -> dict:
        return {"ref": self.ref, "footprint_name": self.footprint_name,
                "x": self.x, "y": self.y, "rotation": self.rotation,
                "pads": [p.to_dict() for p in self.pads],
                "classification": self.classification,
                "classification_source": self.classification_source}

    @classmethod
    def from_dict(cls, d: dict) -> Component:
        pads = [Pad.from_dict(p) for p in d.get("pads", [])]
        return cls(ref=d["ref"], footprint_name=d["footprint_name"],
                   x=d["x"], y=d["y"], rotation=d["rotation"],
                   pads=pads, classification=d.get("classification", "unclassified"),
                   classification_source=d.get("classification_source", "none"))


@dataclass
class TrackSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = ""
    width: float = 0.0

    def to_dict(self) -> dict:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
                "layer": self.layer, "width": self.width}

    @classmethod
    def from_dict(cls, d: dict) -> TrackSegment:
        return cls(**d)


@dataclass
class ArcSegment:
    cx: float
    cy: float
    radius: float
    start_angle: float
    end_angle: float
    layer: str = ""

    def to_dict(self) -> dict:
        return {"cx": self.cx, "cy": self.cy, "radius": self.radius,
                "start_angle": self.start_angle, "end_angle": self.end_angle,
                "layer": self.layer}

    @classmethod
    def from_dict(cls, d: dict) -> ArcSegment:
        return cls(**d)


@dataclass
class ScrewHole:
    x: float
    y: float
    diameter: float
    source: str = "auto"  # "auto" | "manual"

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "diameter": self.diameter,
                "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> ScrewHole:
        return cls(**d)


@dataclass
class BoardOutline:
    # Vertices forming a closed polygon
    vertices: list[tuple[float, float]] = field(default_factory=list)
    source: str = "none"  # "auto" | "manual" | "dxf_import" | "none"

    def to_dict(self) -> dict:
        return {"vertices": list(self.vertices), "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> BoardOutline:
        return cls(vertices=[tuple(v) for v in d.get("vertices", [])],
                   source=d.get("source", "none"))

    def is_valid(self) -> bool:
        return len(self.vertices) >= 3


@dataclass
class PCBData:
    components: list[Component] = field(default_factory=list)
    raw_tracks: list[TrackSegment] = field(default_factory=list)
    raw_arcs: list[ArcSegment] = field(default_factory=list)
    board_outline: Optional[BoardOutline] = None
    screw_holes: list[ScrewHole] = field(default_factory=list)
    source_file: str = ""

    def get_switches(self) -> list[Component]:
        return [c for c in self.components if c.classification == "switch"]

    def get_ics(self) -> list[Component]:
        return [c for c in self.components if c.classification == "ic"]

    def to_dict(self) -> dict:
        return {
            "components": [c.to_dict() for c in self.components],
            "raw_tracks": [t.to_dict() for t in self.raw_tracks],
            "raw_arcs": [a.to_dict() for a in self.raw_arcs],
            "board_outline": self.board_outline.to_dict() if self.board_outline else None,
            "screw_holes": [h.to_dict() for h in self.screw_holes],
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PCBData:
        return cls(
            components=[Component.from_dict(c) for c in d.get("components", [])],
            raw_tracks=[TrackSegment.from_dict(t) for t in d.get("raw_tracks", [])],
            raw_arcs=[ArcSegment.from_dict(a) for a in d.get("raw_arcs", [])],
            board_outline=BoardOutline.from_dict(d["board_outline"]) if d.get("board_outline") else None,
            screw_holes=[ScrewHole.from_dict(h) for h in d.get("screw_holes", [])],
            source_file=d.get("source_file", ""),
        )

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: str) -> PCBData:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
