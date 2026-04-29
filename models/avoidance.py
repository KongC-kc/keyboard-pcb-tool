from __future__ import annotations
import json
from dataclasses import dataclass, field


@dataclass
class AvoidancePolygon:
    vertices: list[tuple[float, float]]  # polygon vertices in mm
    confidence: str = "suspected"  # "suspected" | "confirmed"
    source: str = "auto"           # "auto" | "manual"
    label: str = ""
    # Per-layer expansion in mm (overrides default if present)
    layer_expansions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "vertices": list(self.vertices),
            "confidence": self.confidence,
            "source": self.source,
            "label": self.label,
            "layer_expansions": self.layer_expansions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AvoidancePolygon:
        return cls(
            vertices=[tuple(v) for v in d.get("vertices", [])],
            confidence=d.get("confidence", "suspected"),
            source=d.get("source", "auto"),
            label=d.get("label", ""),
            layer_expansions=d.get("layer_expansions", {}),
        )
