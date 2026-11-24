"""
Rule policy configuration — the company-specific parameters of the seven
business rules, kept OUTSIDE the code so that a company can adapt its policy
without touching Python.

    config/rules.json            the active policy (defaults = thesis values)
    config/rules_changelog.csv   who changed what, when (written on save)

The rule *logic* stays in src/rules/policies.py; only thresholds, buffers
and on/off switches live here. Every parameter has a plain-language catalog
entry (Greek) that the dashboard uses to explain the rule to planners.
"""
from __future__ import annotations

import copy
import csv
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.config import config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "config" / "rules.json"
CHANGELOG_PATH = PROJECT_ROOT / "config" / "rules_changelog.csv"
ENV_VAR = "RULES_CONFIG"


# ============================================================
# Catalog: what each rule is, in words a planner understands
# ============================================================
@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str            # Greek label for the dashboard
    unit: str             # "%", "ημ.", ""
    min: float
    max: float
    step: float
    kind: str = "number"  # "number" | "bool"


@dataclass(frozen=True)
class RuleInfo:
    name: str
    priority: int
    title: str            # short Greek title
    when: str             # Πότε ενεργοποιείται
    what: str             # Τι κάνει
    why: str              # Γιατί υπάρχει
    kind: str             # "μετασχηματιστικός" | "ενημερωτικός" | "καταστολή"
    params: tuple[ParamSpec, ...] = ()
    defaults: dict = field(default_factory=dict)


RULE_CATALOG: dict[str, RuleInfo] = {
    "R-DEAD-STOCK": RuleInfo(
        name="R-DEAD-STOCK", priority=1, title="Νεκρό απόθεμα",
        when="Το υλικό δεν έχει καμία κίνηση για περισσότερες από {inactive_days} ημέρες (ή καθόλου ιστορικό).",
        what="Ακυρώνει κάθε πρόταση παραγγελίας για το υλικό.",
        why="Απαξιωμένοι κωδικοί (απόσυρση μοντέλου) δεν πρέπει να ξαναπαραγγέλνονται επειδή το SAP έχει παλιό safety stock.",
        kind="καταστολή",
        params=(ParamSpec("inactive_days", "Ημέρες χωρίς κίνηση", "ημ.", 30, 1095, 5),),
        defaults={"inactive_days": config.dead_stock_threshold_days},
    ),
    "R-EXPEDITE": RuleInfo(
        name="R-EXPEDITE", priority=10, title="Επείγουσα παραγγελία",
        when="Το απόθεμα είναι κάτω από το {stock_vs_safety_pct} % του safety stock και η παραγγελία εκδίδεται μέσα στο lead time.",
        what="Σημαίνει την πρόταση ως «επείγουσα» — δεν αλλάζει ποσότητα ή ημερομηνία.",
        why="Ο planner βλέπει πρώτα τα λίγα υλικά που κινδυνεύουν με έλλειψη.",
        kind="ενημερωτικός",
        params=(ParamSpec("stock_vs_safety_pct", "Όριο αποθέματος ως % του safety stock", "%", 10, 100, 5),),
        defaults={"stock_vs_safety_pct": 50},
    ),
    "R-SAFETY-BUFFER-A": RuleInfo(
        name="R-SAFETY-BUFFER-A", priority=20, title="Buffer A-items",
        when="Το υλικό ανήκει στην κλάση A (το 20 % των κωδικών με το 80 % της αξίας).",
        what="Αυξάνει την ποσότητα της παραγγελίας κατά {buffer_pct} %.",
        why="Μία έλλειψη σε A-item κοστίζει πολύ περισσότερο (χαμένη πώληση, πελάτης) από λίγο παραπάνω απόθεμα.",
        kind="μετασχηματιστικός",
        params=(ParamSpec("buffer_pct", "Επιπλέον ποσότητα", "%", 0, 50, 1),),
        defaults={"buffer_pct": 20},
    ),
    "R-LONG-LEAD-BUFFER": RuleInfo(
        name="R-LONG-LEAD-BUFFER", priority=25, title="Buffer μακρού lead time",
        when="Ο χρόνος παράδοσης του υλικού υπερβαίνει τις {threshold_days} ημέρες (προμηθευτές Ασίας, θαλάσσια μεταφορά).",
        what="Αυξάνει την ποσότητα της παραγγελίας κατά {buffer_pct} %.",
        why="Καθυστερήσεις εκτελωνισμού και ομαδοποίησης φορτίων δεν καλύπτονται από επείγουσα παραγγελία όταν το πλοίο αργεί.",
        kind="μετασχηματιστικός",
        params=(ParamSpec("threshold_days", "Όριο lead time", "ημ.", 7, 120, 1),
                ParamSpec("buffer_pct", "Επιπλέον ποσότητα", "%", 0, 50, 1)),
        defaults={"threshold_days": 30, "buffer_pct": 15},
    ),
    "R-MOQ-ENFORCE": RuleInfo(
        name="R-MOQ-ENFORCE", priority=30, title="MOQ και συσκευασία",
        when="Πάντα, μετά τα buffers.",
        what="Ανεβάζει την ποσότητα τουλάχιστον στο MOQ, τη στρογγυλοποιεί σε πολλαπλάσιο συσκευασίας και σε ακέραια τεμάχια.",
        why="Ο προμηθευτής δεν στέλνει 70,4 σετ· η πρόταση πρέπει να είναι εκτελέσιμη όπως είναι.",
        kind="μετασχηματιστικός",
        params=(ParamSpec("whole_units", "Στρογγυλοποίηση σε ακέραια τεμάχια (διακριτές μονάδες)", "", 0, 1, 1, kind="bool"),),
        defaults={"whole_units": True},
    ),
    "R-CALENDAR-SHIFT": RuleInfo(
        name="R-CALENDAR-SHIFT", priority=80, title="Εργάσιμη ημέρα",
        when="Η ημερομηνία έκδοσης πέφτει Σαββατοκύριακο ή αργία.",
        what="Μετακινεί την έκδοση στην επόμενη εργάσιμη ημέρα.",
        why="Παραγγελία με ημερομηνία Κυριακή δεν εκτελείται από κανέναν.",
        kind="μετασχηματιστικός",
    ),
    "R-COST-ESTIMATE": RuleInfo(
        name="R-COST-ESTIMATE", priority=90, title="Εκτίμηση κόστους",
        when="Πάντα, τελευταίος.",
        what="Υπολογίζει το εκτιμώμενο κόστος = ποσότητα × standard cost.",
        why="Ο planner και η διοίκηση βλέπουν την αξία κάθε πρότασης χωρίς να ανοίξουν το SAP.",
        kind="ενημερωτικός",
    ),
}

RULE_ORDER = [n for n, _ in sorted(RULE_CATALOG.items(), key=lambda kv: kv[1].priority)]


def default_rules_dict() -> dict:
    return {
        name: {"enabled": True, "params": copy.deepcopy(info.defaults)}
        for name, info in RULE_CATALOG.items()
    }


# ============================================================
# Config object
# ============================================================
@dataclass
class RulesConfig:
    rules: dict = field(default_factory=default_rules_dict)
    source: Optional[Path] = None

    # ---- queries -------------------------------------------------
    def is_enabled(self, name: str) -> bool:
        return bool(self.rules.get(name, {}).get("enabled", True))

    def param(self, name: str, key: str, default: Any = None) -> Any:
        entry = self.rules.get(name, {})
        if key in entry.get("params", {}):
            return entry["params"][key]
        info = RULE_CATALOG.get(name)
        if info and key in info.defaults:
            return info.defaults[key]
        return default

    def describe(self, name: str) -> dict:
        """Catalog texts with the current parameter values filled in."""
        info = RULE_CATALOG[name]
        values = {p.key: self.param(name, p.key) for p in info.params}
        fmt = {k: (int(v) if isinstance(v, float) and float(v).is_integer() else v) for k, v in values.items()}
        return {
            "name": name, "priority": info.priority, "title": info.title, "kind": info.kind,
            "enabled": self.is_enabled(name),
            "when": info.when.format(**fmt), "what": info.what.format(**fmt), "why": info.why,
            "params": values,
        }

    def summary_label(self, name: str) -> str:
        """One-line Greek label with the live values (for the sidebar)."""
        v = {p.key: self.param(name, p.key) for p in RULE_CATALOG[name].params}
        labels = {
            "R-DEAD-STOCK":       f"Καταστολή αν > {int(v.get('inactive_days', 365))} ημ. χωρίς κίνηση",
            "R-EXPEDITE":         f"Επείγον αν απόθεμα < {int(v.get('stock_vs_safety_pct', 50))}% του SS",
            "R-SAFETY-BUFFER-A":  f"+{v.get('buffer_pct', 20):g}% στα A-items",
            "R-LONG-LEAD-BUFFER": f"+{v.get('buffer_pct', 15):g}% αν LT > {int(v.get('threshold_days', 30))} ημ.",
            "R-MOQ-ENFORCE":      "MOQ / συσκευασία" + (" / ακέραιες μονάδες" if v.get("whole_units", True) else ""),
            "R-CALENDAR-SHIFT":   "Μετάθεση σε εργάσιμη ημέρα",
            "R-COST-ESTIMATE":    "qty × standard cost",
        }
        return labels.get(name, name)

    # ---- mutation ------------------------------------------------
    def set_enabled(self, name: str, enabled: bool) -> None:
        self.rules.setdefault(name, {"enabled": True, "params": {}})["enabled"] = bool(enabled)

    def set_param(self, name: str, key: str, value: Any) -> None:
        self.rules.setdefault(name, {"enabled": True, "params": {}}).setdefault("params", {})[key] = value

    def diff(self, other: "RulesConfig") -> list[str]:
        """Human-readable list of differences (self vs other)."""
        out = []
        for name in RULE_ORDER:
            if self.is_enabled(name) != other.is_enabled(name):
                out.append(f"{name}: {'ενεργός' if self.is_enabled(name) else 'ανενεργός'}")
            for p in RULE_CATALOG[name].params:
                a, b = self.param(name, p.key), other.param(name, p.key)
                if a != b:
                    out.append(f"{name}.{p.key}: {b} → {a}")
        return out

    # ---- (de)serialisation --------------------------------------
    def to_dict(self) -> dict:
        return {"version": 1, "rules": copy.deepcopy(self.rules)}

    @classmethod
    def from_dict(cls, data: dict, source: Optional[Path] = None) -> "RulesConfig":
        rules = default_rules_dict()
        for name, entry in (data or {}).get("rules", {}).items():
            if name not in rules:
                continue  # unknown rule: ignore
            rules[name]["enabled"] = bool(entry.get("enabled", True))
            rules[name]["params"].update(entry.get("params", {}) or {})
        return cls(rules=rules, source=source)

    @classmethod
    def load(cls, path: Optional[os.PathLike | str] = None) -> "RulesConfig":
        """Load from `path`, else $RULES_CONFIG, else config/rules.json.
        A missing file means "defaults" — never an error."""
        p = Path(path or os.getenv(ENV_VAR) or DEFAULT_PATH)
        if not p.exists():
            return cls(source=p)
        with open(p, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh), source=p)

    def save(self, path: Optional[os.PathLike | str] = None, changed_by: str = "",
             note: str = "", previous: Optional["RulesConfig"] = None) -> Path:
        """Persist as the company policy and append a line to the changelog."""
        p = Path(path or self.source or DEFAULT_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        self.source = p
        changes = self.diff(previous) if previous is not None else ["(αρχική αποθήκευση)"]
        log_path = p.with_name("rules_changelog.csv")
        new_file = not log_path.exists()
        with open(log_path, "a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["timestamp", "changed_by", "changes", "note"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), changed_by,
                        "; ".join(changes) or "(καμία διαφορά)", note])
        return p


# ============================================================
# Active config (what the rules in policies.py read)
# ============================================================
_ACTIVE: Optional[RulesConfig] = None


def get_active() -> RulesConfig:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = RulesConfig.load()
    return _ACTIVE


def set_active(cfg: Optional[RulesConfig]) -> RulesConfig:
    """Install `cfg` as the policy the rules read (None = reload from disk)."""
    global _ACTIVE
    _ACTIVE = cfg if cfg is not None else RulesConfig.load()
    return _ACTIVE
