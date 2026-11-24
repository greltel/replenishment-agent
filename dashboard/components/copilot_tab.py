"""
Streamlit dashboard tab for the AI Copilot.

Provides a chat interface where planners can ask questions in natural
language. The copilot uses the BDI agent's data (read-only tools) to answer,
through a LOCAL LLM served by Ollama — no data leaves the machine.
"""
from __future__ import annotations

import streamlit as st

from src.copilot.llm_client import OllamaClient
from src.copilot.orchestrator import Copilot
from src.data_layer.repository import Repository
from dashboard import theme
from dashboard.theme import section


def render(repo: Repository) -> None:
    section("AI Copilot — συνομιλία με τον πράκτορα",
            "Ερωτήσεις σε φυσική γλώσσα (ελληνικά ή αγγλικά) πάνω στις προτάσεις, "
            "τα υλικά και την κατάσταση του συστήματος. Τοπικό LLM (Ollama): τα "
            "εταιρικά δεδομένα δεν φεύγουν από τον υπολογιστή. Ο Copilot εξηγεί — "
            "δεν αποφασίζει.")

    # ─── Settings ───
    with st.expander("⚙️ Ρυθμίσεις Copilot", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            base_url = st.text_input(
                "Ollama URL",
                value=st.session_state.get("ollama_url", "http://localhost:11434"),
                help="Προεπιλεγμένο endpoint του Ollama",
            )
        with col2:
            model = st.text_input(
                "Μοντέλο",
                value=st.session_state.get("ollama_model", "llama3.1:8b"),
                help="Προτεινόμενα: llama3.1:8b (γενικό), qwen2.5:7b (καλύτερο "
                     "σε μη αγγλικά), mistral:7b",
            )
        st.session_state["ollama_url"] = base_url
        st.session_state["ollama_model"] = model

    cop = _get_or_create_copilot(repo, base_url, model)

    # ─── Health check ───
    health = cop.health_check()
    if not health.get("ok"):
        st.warning(f"**Το Ollama δεν είναι διαθέσιμο:** {health.get('error')}")
        with st.expander("Πώς ενεργοποιώ τον Copilot;"):
            st.markdown(
                """
                1. Εγκατάσταση από [ollama.com](https://ollama.com) (Windows / macOS / Linux)
                2. Άνοιγμα της εφαρμογής Ollama (ή `ollama serve` σε terminal)
                3. Λήψη μοντέλου: `ollama pull llama3.1:8b` (~4,7 GB, μία φορά)
                4. Ανανέωση αυτής της σελίδας

                Ο Copilot απαντά **μόνο** με δεδομένα που διαβάζει από τη βάση μέσω 7
                read-only εργαλείων (get_summary, list_critical_proposals,
                get_material_details, explain_proposal, search_proposals,
                get_top_materials_by_demand, get_abc_distribution).
                """
            )
        return

    # ─── Chat history ───
    if "copilot_messages" not in st.session_state:
        st.session_state["copilot_messages"] = []

    st.markdown("**Γρήγορες ερωτήσεις:**")
    qa_cols = st.columns(4)
    quick_questions = [
        "Δώσε μου μια σύνοψη της κατάστασης",
        "Ποια υλικά είναι κρίσιμα τώρα;",
        "Ποια είναι τα top 5 σε κατανάλωση;",
        "Πόσα υλικά έχουμε ανά κλάση ABC;",
    ]
    for col, q in zip(qa_cols, quick_questions):
        with col:
            if st.button(q, key=f"qa_{q}", **theme.wide_kwargs(st.button)):
                _ask_and_render(cop, q)

    if st.button("🗑️ Καθαρισμός συνομιλίας", type="secondary"):
        cop.reset()
        st.session_state["copilot_messages"] = []
        st.rerun()

    st.divider()

    for msg in st.session_state["copilot_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools_used"):
                with st.expander(f"🔧 Εργαλεία που χρησιμοποιήθηκαν ({len(msg['tools_used'])})"):
                    for t in msg["tools_used"]:
                        st.code(f"{t['name']}({t['args']})", language="python")

    user_input = st.chat_input("Ρωτήστε κάτι για τις προτάσεις… π.χ. «Γιατί προτείνεις 500 τμχ για το MAT00012;»")
    if user_input:
        _ask_and_render(cop, user_input)


# ============================================================
# Helpers
# ============================================================
def _get_or_create_copilot(repo: Repository, base_url: str, model: str) -> Copilot:
    """Cache the Copilot in session_state; always point it at the live repo."""
    cache_key = f"{base_url}|{model}"
    if (st.session_state.get("copilot_cache_key") != cache_key
            or "copilot" not in st.session_state):
        client = OllamaClient(base_url=base_url, model=model)
        st.session_state["copilot"] = Copilot(repo=repo, client=client)
        st.session_state["copilot_cache_key"] = cache_key
    cop: Copilot = st.session_state["copilot"]
    cop.repo = repo   # the app opens a fresh repository on every rerun
    return cop


def _ask_and_render(cop: Copilot, user_message: str) -> None:
    """Send a user message, render assistant reply, persist to session state."""
    st.session_state["copilot_messages"].append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Σκέφτομαι…"):
            resp = cop.ask(user_message)
        st.markdown(resp.text)
        if resp.tool_calls_made:
            with st.expander(f"🔧 Εργαλεία που χρησιμοποιήθηκαν ({len(resp.tool_calls_made)})"):
                for t in resp.tool_calls_made:
                    st.code(f"{t['name']}({t['args']})", language="python")

    st.session_state["copilot_messages"].append({
        "role": "assistant", "content": resp.text, "tools_used": resp.tool_calls_made,
    })
