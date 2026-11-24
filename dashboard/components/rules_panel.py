"""
Sidebar panel for the business rules.

Three things, in plain Greek, for the end user:
  1. what each rule does right now (cards with the live parameter values)
  2. a "what-if" editor: switch rules on/off and change their parameters for
     the current session, then re-run the agent to see the effect
  3. "save as company policy": persist the what-if to config/rules.json with
     an entry in config/rules_changelog.csv (who / when / what changed)

The company policy is deliberately NOT changed by a mere click: a what-if
lives in the session until it is saved explicitly, so planners can explore
without silently rewriting the rules everyone else runs with.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from dashboard import theme
from src.rules.rules_config import RULE_CATALOG, RULE_ORDER, RulesConfig

SESSION_KEY = "rules_policy"          # RulesConfig with the session's what-if
SAVED_KEY = "rules_policy_saved"      # RulesConfig as last loaded from disk

KIND_COLORS = {
    "μετασχηματιστικός": theme.ACCENT,
    "ενημερωτικός": theme.NEUTRAL_DARK,
    "καταστολή": theme.ORANGE,
}


# ------------------------------------------------------------------
# state helpers
# ------------------------------------------------------------------
def get_session_policy() -> RulesConfig:
    """The policy the dashboard currently works with (saved + what-if)."""
    if SAVED_KEY not in st.session_state:
        st.session_state[SAVED_KEY] = RulesConfig.load()
    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = RulesConfig.from_dict(
            st.session_state[SAVED_KEY].to_dict(), source=st.session_state[SAVED_KEY].source)
    return st.session_state[SESSION_KEY]


def saved_policy() -> RulesConfig:
    get_session_policy()
    return st.session_state[SAVED_KEY]


def reload_from_disk() -> None:
    st.session_state[SAVED_KEY] = RulesConfig.load()
    st.session_state[SESSION_KEY] = RulesConfig.from_dict(
        st.session_state[SAVED_KEY].to_dict(), source=st.session_state[SAVED_KEY].source)


def whatif_changes() -> list[str]:
    """Differences between the session what-if and the saved company policy."""
    return get_session_policy().diff(saved_policy())


def write_session_policy_file() -> Path:
    """Dump the session policy to a temp JSON for `run_agent.py --rules-config`."""
    tmp = Path(tempfile.gettempdir()) / "replenishment_rules_whatif.json"
    tmp.write_text(json.dumps(get_session_policy().to_dict(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return tmp


# ------------------------------------------------------------------
# rendering
# ------------------------------------------------------------------
def _pill(text: str, color: str) -> str:
    return (f"<span style='display:inline-block;padding:0 .45rem;border-radius:.6rem;"
            f"font-size:.72rem;font-weight:600;color:#fff;background:{color}'>{text}</span>")


def render_rule_cards(policy: RulesConfig) -> None:
    """Plain-language cards: when / what / why, with live values."""
    for name in RULE_ORDER:
        d = policy.describe(name)
        status = _pill("ενεργός", theme.STATUS["good"]) if d["enabled"] else _pill("ανενεργός", theme.TEXT_MUTED)
        kind = _pill(d["kind"], KIND_COLORS.get(d["kind"], theme.TEXT_SECONDARY))
        st.markdown(
            f"<div style='border:1px solid {theme.BORDER};border-radius:8px;padding:.5rem .65rem;"
            f"margin-bottom:.45rem;background:{theme.SURFACE}'>"
            f"<div><b>{d['priority']:>2} · {d['title']}</b></div>"
            f"<div style='margin:.2rem 0 .1rem 0'>{kind} {status} "
            f"<span style='font-size:.74rem;color:{theme.TEXT_SECONDARY}'><code>{name}</code></span></div>"
            f"<div style='font-size:.82rem;margin-top:.3rem'><b>Πότε:</b> {d['when']}</div>"
            f"<div style='font-size:.82rem'><b>Τι κάνει:</b> {d['what']}</div>"
            f"<div style='font-size:.82rem;color:{theme.TEXT_SECONDARY}'><b>Γιατί:</b> {d['why']}</div>"
            f"</div>", unsafe_allow_html=True)


def render_policy_editor() -> None:
    """What-if editor + save as company policy."""
    policy = get_session_policy()
    saved = saved_policy()

    st.caption("Οι αλλαγές ισχύουν μόνο σε αυτή τη συνεδρία (what-if). Πάτησε «Εκτέλεση πράκτορα» για να "
               "δεις την επίδραση· «Αποθήκευση» για να γίνουν η πολιτική της εταιρείας.")

    for name in RULE_ORDER:
        info = RULE_CATALOG[name]
        enabled = st.toggle(f"{info.priority} · {info.title}", value=policy.is_enabled(name),
                            key=f"pol_en_{name}", help=name)
        policy.set_enabled(name, enabled)
        for p in info.params:
            cur = policy.param(name, p.key)
            if p.kind == "bool":
                val = st.checkbox(p.label, value=bool(cur), key=f"pol_{name}_{p.key}",
                                  disabled=not enabled)
            else:
                val = st.number_input(
                    f"{p.label} ({p.unit})" if p.unit else p.label,
                    min_value=float(p.min), max_value=float(p.max), step=float(p.step),
                    value=float(cur), key=f"pol_{name}_{p.key}", disabled=not enabled,
                    format="%g")
                val = int(val) if float(val).is_integer() else float(val)
            policy.set_param(name, p.key, val)

    changes = policy.diff(saved)
    if changes:
        st.warning("What-if ενεργό — διαφορές από την αποθηκευμένη πολιτική:\n\n- " + "\n- ".join(changes))
    else:
        st.caption("Ίδιο με την αποθηκευμένη πολιτική της εταιρείας.")

    if st.button("↩ Επαναφορά στην αποθηκευμένη πολιτική", **theme.wide_kwargs(st.button),
                 help="Επιστροφή στην αποθηκευμένη πολιτική (config/rules.json)."):
        for name in RULE_ORDER:
            st.session_state.pop(f"pol_en_{name}", None)
            for p in RULE_CATALOG[name].params:
                st.session_state.pop(f"pol_{name}_{p.key}", None)
        reload_from_disk()
        st.rerun()
    save_clicked = st.button("💾 Αποθήκευση ως πολιτική εταιρείας", **theme.wide_kwargs(st.button),
                             disabled=not changes, key="pol_save_btn",
                             help="Γράφει τη what-if ως πολιτική εταιρείας στο config/rules.json "
                                  "και καταγράφει την αλλαγή στο rules_changelog.csv.")
    if save_clicked:
        st.session_state["_policy_save_pending"] = True
    if st.session_state.get("_policy_save_pending"):
        who = st.text_input("Ποιος εγκρίνει την αλλαγή;", key="pol_who", placeholder="π.χ. Υπεύθυνος Σχεδιασμού")
        note = st.text_input("Αιτιολόγηση (προαιρετικά)", key="pol_note")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("Επιβεβαίωση", **theme.wide_kwargs(st.button), disabled=not who.strip()):
                path = policy.save(saved.source, changed_by=who.strip(), note=note.strip(), previous=saved)
                st.session_state["_policy_save_pending"] = False
                reload_from_disk()
                st.success(f"Αποθηκεύτηκε ως πολιτική εταιρείας ({path.name}).")
                st.rerun()
        with cc2:
            if st.button("Άκυρο", **theme.wide_kwargs(st.button)):
                st.session_state["_policy_save_pending"] = False
                st.rerun()

    src = saved.source
    st.caption(f"Αρχείο πολιτικής: `{src.name if src else 'config/rules.json'}` · "
               f"ιστορικό αλλαγών: `rules_changelog.csv`")


def render_sidebar_section() -> None:
    """Compact list + the two expanders. Call inside `with st.sidebar:`."""
    policy = get_session_policy()
    changes = whatif_changes()

    st.markdown("**Επιχειρησιακοί κανόνες**" + ("  ⚠️ what-if" if changes else ""))
    for name in RULE_ORDER:
        info = RULE_CATALOG[name]
        on = policy.is_enabled(name)
        color = theme.TEXT_MUTED if not on else theme.TEXT_PRIMARY
        strike = "text-decoration:line-through;" if not on else ""
        st.markdown(
            f"<div style='font-size:.82rem;line-height:1.25;margin:.1rem 0 .3rem 0;color:{color};{strike}'>"
            f"<code>{info.priority:>2}</code> <b>{info.title}</b><br>"
            f"<span style='color:{theme.TEXT_SECONDARY};font-size:.76rem'>{policy.summary_label(name)}</span></div>",
            unsafe_allow_html=True)

    with st.expander("ℹ️ Τι κάνει κάθε κανόνας", expanded=False):
        render_rule_cards(policy)
    with st.expander("⚙️ Πολιτική κανόνων (what-if)", expanded=bool(changes)):
        render_policy_editor()
