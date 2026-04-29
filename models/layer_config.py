from __future__ import annotations
import json
from dataclasses import dataclass, field


@dataclass
class FoamLayerConfig:
    name: str
    name_cn: str          # Chinese name
    thickness: float      # mm
    cutout_type: str      # "rect" | "circle_small" | "solid" | "circle_large" | "circle_dense"
    cutout_size: float    # mm, diameter or side length
    default_avoidance_expansion: float  # mm, default expansion around avoidance polygons

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> FoamLayerConfig:
        return cls(**d)


# Default layer configs
DEFAULT_LAYERS: list[FoamLayerConfig] = [
    FoamLayerConfig("plate", "定位板", 1.5, "rect", 14.0, 0.5),
    FoamLayerConfig("sandwich_foam", "夹心棉", 3.0, "rect", 15.5, 1.0),
    FoamLayerConfig("switch_foam", "轴下垫", 0.5, "circle_small", 4.0, 0.8),
    FoamLayerConfig("ixpe_pad", "声优垫", 0.5, "solid", 0.0, 0.3),
    FoamLayerConfig("bottom_foam", "底棉", 5.0, "circle_large", 10.0, 2.0),
    FoamLayerConfig("back_membrane", "背膜", 1.0, "circle_dense", 3.0, 3.0),
]


@dataclass
class LayerConfigSet:
    layers: list[FoamLayerConfig] = field(default_factory=lambda: list(DEFAULT_LAYERS))

    def get(self, name: str) -> FoamLayerConfig | None:
        for l in self.layers:
            if l.name == name:
                return l
        return None

    def to_dict(self) -> dict:
        return {"layers": [l.to_dict() for l in self.layers]}

    @classmethod
    def from_dict(cls, d: dict) -> LayerConfigSet:
        layers = [FoamLayerConfig.from_dict(l) for l in d.get("layers", [])]
        return cls(layers=layers)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: str) -> LayerConfigSet:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
