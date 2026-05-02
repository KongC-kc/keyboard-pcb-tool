"""
Footprint Rules — Component Classification System

Supports two matching strategies:
1. Exact footprint name matching (primary, for standardized libraries)
2. Regex pattern matching (legacy fallback)

Classification categories: "switch", "led", "ic", "mechanical", "unclassified"
"""
from __future__ import annotations
import re
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FootprintRule:
    pattern: str        # regex pattern (legacy)
    label: str          # display name
    priority: int       # higher = checked first
    enabled: bool = True
    match_type: str = "regex"  # "regex" | "exact"
    classification: str = "switch"  # target classification

    def matches(self, ref: str, footprint_name: str = "") -> bool:
        """Match against ref (regex) or footprint_name (exact/regex)."""
        if not self.enabled:
            return False
        if self.match_type == "exact":
            return footprint_name == self.pattern
        try:
            # Regex matches against ref by default
            return bool(re.match(self.pattern, ref, re.IGNORECASE))
        except re.error:
            return False

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "label": self.label,
            "priority": self.priority,
            "enabled": self.enabled,
            "match_type": self.match_type,
            "classification": self.classification,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FootprintRule:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Standard Library Exact-Match Rules ──────────────────────────────
# These rules match footprint_name exactly, based on the NINX standardized
# component library used across all keyboard PCBs (ZS60HE, EON64, etc.)

STANDARD_LIBRARY_RULES: list[FootprintRule] = [
    # Switches (Hall-effect sensors)
    FootprintRule("HALL-SOT-23-DL",  "霍尔开关 (DL)",       100, True, "exact", "switch"),
    FootprintRule("HALL-SOT-23-NS",  "霍尔开关 (NS)",       100, True, "exact", "switch"),
    FootprintRule("HALL-SOT-23-FLIP","霍尔开关 (Flip)",     100, True, "exact", "switch"),

    # LEDs
    FootprintRule("0402LED",         "0402 LED",             90, True, "exact", "led"),
    FootprintRule("RGB6028-2812",    "RGB 6028 灯珠",        90, True, "exact", "led"),
    FootprintRule("RGB3528-2812",    "RGB 3528 灯珠",        90, True, "exact", "led"),

    # Main ICs
    FootprintRule("LQFP64-7*7",     "主控 MCU (LQFP64)",    80, True, "exact", "ic"),
    FootprintRule("LQFP48-7*7",     "主控 MCU (LQFP48)",    80, True, "exact", "ic"),
    FootprintRule("DFN1210-6",      "IC (DFN1210-6)",       80, True, "exact", "ic"),
    FootprintRule("ADC-SOP20",      "ADC (SOP20)",          80, True, "exact", "ic"),
    FootprintRule("MUX-SOP16",      "MUX (SOP16)",          80, True, "exact", "ic"),
    FootprintRule("SOT-23-5 DBV",   "IC (SOT-23-5)",        80, True, "exact", "ic"),

    # Mechanical
    FootprintRule("STUD-M2",        "M2 铜柱",              70, True, "exact", "mechanical"),
    FootprintRule("USB TYPE-C-F-16P","USB-C 接口",           70, True, "exact", "mechanical"),
    FootprintRule("HEADER-4P",      "4P 排针",              70, True, "exact", "mechanical"),
    FootprintRule("KEY1",           "按键 (KEY1)",           70, True, "exact", "mechanical"),
    FootprintRule("MX1.25-B-3P",   "连接器 (MX1.25)",      70, True, "exact", "mechanical"),
    FootprintRule("SH1.0-4P",      "连接器 (SH1.0)",       70, True, "exact", "mechanical"),
    FootprintRule("CRYSTAL2520",    "晶振 2520",            70, True, "exact", "ic"),
    FootprintRule("CRYSTAL3225",    "晶振 3225",            70, True, "exact", "ic"),
]

# Legacy regex rules (fallback for non-standard footprints)
LEGACY_REGEX_RULES: list[FootprintRule] = [
    FootprintRule(r"^SW\d+$",  "SW 前缀 (SW1, SW2...)",   10, True, "regex", "switch"),
    FootprintRule(r"^K\d+$",   "K 前缀 (K1, K2...)",       8, True, "regex", "switch"),
    FootprintRule(r"^KEY\d+$", "KEY 前缀 (KEY1...)",        6, True, "regex", "switch"),
    FootprintRule(r"^MX\d+$",  "MX 前缀 (MX1...)",          4, True, "regex", "switch"),
    FootprintRule(r"^H\d+$",   "H 前缀 - 霍尔 (H1, H2...)", 5, True, "regex", "switch"),
]

DEFAULT_RULES: list[FootprintRule] = STANDARD_LIBRARY_RULES + LEGACY_REGEX_RULES


@dataclass
class FootprintRuleSet:
    rules: list[FootprintRule] = field(default_factory=lambda: list(DEFAULT_RULES))

    @classmethod
    def get_default_rules(cls) -> FootprintRuleSet:
        return cls(rules=list(DEFAULT_RULES))

    def _sorted_rules(self) -> list[FootprintRule]:
        return sorted(self.rules, key=lambda r: r.priority, reverse=True)

    def classify_components(self, components) -> None:
        """Classify components in-place using exact footprint matching first, then regex fallback."""
        for comp in components:
            if comp.classification_source == "manual":
                continue
            if comp.classification != "unclassified":
                continue
            for rule in self._sorted_rules():
                if not rule.enabled:
                    continue
                if rule.matches(comp.ref, comp.footprint_name):
                    comp.classification = rule.classification
                    comp.classification_source = "rule"
                    break

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
