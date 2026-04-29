from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LayoutOption:
    id: str
    name: str  # e.g., "Split Backspace", "6.25U Spacebar"
    switch_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "switch_refs": self.switch_refs}

    @classmethod
    def from_dict(cls, d: dict) -> LayoutOption:
        return cls(**d)


@dataclass
class LayoutGroup:
    id: str
    name: str  # e.g., "Backspace", "Spacebar"
    description: str = ""
    options: list[LayoutOption] = field(default_factory=list)
    selected_option_id: Optional[str] = None

    def selected_option(self) -> Optional[LayoutOption]:
        for opt in self.options:
            if opt.id == self.selected_option_id:
                return opt
        return None

    def selected_switch_refs(self) -> list[str]:
        opt = self.selected_option()
        return opt.switch_refs if opt else []

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "options": [o.to_dict() for o in self.options],
            "selected_option_id": self.selected_option_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LayoutGroup:
        return cls(
            id=d["id"], name=d["name"], description=d.get("description", ""),
            options=[LayoutOption.from_dict(o) for o in d.get("options", [])],
            selected_option_id=d.get("selected_option_id"),
        )


@dataclass
class LayoutConfig:
    groups: list[LayoutGroup] = field(default_factory=list)

    def get_active_switch_refs(self) -> set[str]:
        """All switch refs from selected options across all groups."""
        refs = set()
        for g in self.groups:
            refs.update(g.selected_switch_refs())
        return refs

    def to_dict(self) -> dict:
        return {"groups": [g.to_dict() for g in self.groups]}

    @classmethod
    def from_dict(cls, d: dict) -> LayoutConfig:
        return cls(groups=[LayoutGroup.from_dict(g) for g in d.get("groups", [])])

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: str) -> LayoutConfig:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
