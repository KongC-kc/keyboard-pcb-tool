from __future__ import annotations
import re
import json
from dataclasses import dataclass, field


@dataclass
class FootprintRule:
    pattern: str        # regex, e.g. "^SW\\d+$"
    label: str          # display name, e.g. "SW prefix"
    priority: int       # higher = checked first
    enabled: bool = True

    def matches(self, ref: str) -> bool:
        if not self.enabled:
            return False
        try:
            return bool(re.match(self.pattern, ref, re.IGNORECASE))
        except re.error:
            return False

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "label": self.label,
                "priority": self.priority, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d: dict) -> FootprintRule:
        return cls(**d)


# Default presets for keyboard PCBs
DEFAULT_RULES: list[FootprintRule] = [
    FootprintRule(pattern=r"^SW\d+$", label="SW prefix (SW1, SW2...)", priority=10),
    FootprintRule(pattern=r"^K\d+$", label="K prefix (K1, K2...)", priority=8),
    FootprintRule(pattern=r"^KEY\d+$", label="KEY prefix (KEY1...)", priority=6),
    FootprintRule(pattern=r"^MX\d+$", label="MX prefix (MX1...)", priority=4),
]


@dataclass
class FootprintRuleSet:
    rules: list[FootprintRule] = field(default_factory=lambda: list(DEFAULT_RULES))

    def _sorted_rules(self) -> list[FootprintRule]:
        return sorted(self.rules, key=lambda r: r.priority, reverse=True)

    def classify_components(self, components) -> None:
        """Classify components in-place. Sets classification to 'switch' if matched."""
        for rule in self._sorted_rules():
            if not rule.enabled:
                continue
            for comp in components:
                if comp.classification_source == "manual":
                    continue
                if comp.classification != "unclassified":
                    continue
                if rule.matches(comp.ref):
                    comp.classification = "switch"
                    comp.classification_source = "rule"

    def to_dict(self) -> dict:
        return {"rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_dict(cls, d: dict) -> FootprintRuleSet:
        rules = [FootprintRule.from_dict(r) for r in d.get("rules", [])]
        return cls(rules=rules)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, path: str) -> FootprintRuleSet:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
