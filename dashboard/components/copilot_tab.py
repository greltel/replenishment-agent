"""
Streamlit dashboard tab for the AI Copilot.

Provides a chat interface where planners can ask questions in natural
language. The copilot uses the BDI agent's data to answer.
"""
from __future__ import annotations

import streamlit as st

from src.copilot.llm_client import OllamaClient
from src.copilot.orchestrator import Copilot
from src.data_layer.repository import Repository


def render(repo: Repository) -> None:
    st.subheader("💬 AI Copilot")
    st.caption(
        "Ρωτήστε στα Ελληνικά ή Αγγλικά για τις προτάσεις του agent, "
        "συγκεκριμένα υλικά ή την κατάσταση του συστήματος."
    )

    # ─── Sidebar settings (within the tab) ───
    with st.expander("⚙️ Ρυθμίσεις Copilot", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            base_url = st.text_input(
                "Ollama URL",
                value=st.session_state.get("ollama_url", "http://localhost:11434"),
                help="Default Ollama API endpoint",
            )
        with col2:
            model = st.text_input(
                "Model",
                value=st.session_state.get("ollama_model", "llama3.1:8b"),
                help=("Recommended: llama3.1:8b (general), qwen2.5:7b "
                      "(better for non-English), mistral:7b"),
            )

        st.session_state["ollama_url"] = base_url
        st.session_state["ollama_model"] = model

    # ─── Init or reset copilot ───
    cop = _get_or_create_copilot(repo, base_url, model)

    # ─── Health check banner ───
    health = cop.health_check()
    if not health.get("ok"):
        st.warning(
            f"**Ollama δεν είναι έτοιμο:** {health.get('error')}\n\n"
            f"💡 {health.get('hint')}"
        )
        with st.expander("Πώς να εγκαταστήσω Ollama;"):
            st.markdown(
                """
                1. Κατεβάστε από [ollama.com](https://ollama.com) (Windows / macOS / Linux)
                2. Εκτελέστε ή ανοίξτε την εφαρμογή
                3. Από terminal:
                   ```bash
                   ollama pull llama3.1:8b
                   ```
                4. Κάντε refresh αυτή τη σελίδα

                Το Ollama τρέχει τοπικά — **τα δεδομένα δεν φεύγουν από το laptop σας**.
                """
            )
        return

    # ─── Chat history ───
    if "copilot_messages" not in st.session_state:
        st.session_state["copilot_messages"] = []

    # Quick-action buttons
    st.markdown("**Γρήγορες ερωτήσεις:**")
    qa_cols = st.columns(3)
    quick_questions = [
        "Δώσε μου μια σύνοψη",
        "Ποια υλικά είναι κρίσιμα τώρα;",
        "Ποια είναι τα top 5 σε κατανάλωση;",
    ]
    for col, q in zip(qa_cols, quick_questions):
        with col:
            if st.button(q, use_container_width=True, key=f"qa_{q}"):
                _ask_and_render(cop, q)

    if st.button("🗑️ Καθάρισε συνομιλία", type="secondary"):
        cop.reset()
        st.session_state["copilot_messages"] = []
        st.rerun()

    st.divider()

    # Render existing messages
    for msg in st.session_state["copilot_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools_used"):
                with st.expander(
                    f"🔧 Εργαλεία που χρησιμοποιήθηκαν ({len(msg['tools_used'])})"
                ):
                    for t in msg["tools_used"]:
                        st.code(f"{t['name']}({t['args']})", language="python")

    # Chat input
    user_input = st.chat_input("Ρωτήστε κάτι σχετικό με τις προτάσεις...")
    if user_input:
        _ask_and_render(cop, user_input)


# ============================================================
# Helpers
# ============================================================
def _get_or_create_copilot(
    repo: Repository, base_url: str, model: str
) -> Copilot:
    """Cache the Copilot instance in session_state, recreate if settings changed."""
    cache_key = f"{base_url}|{model}"
    if (st.session_state.get("copilot_cache_key") != cache_key
            or "copilot" not in st.session_state):
        client = OllamaClient(base_url=base_url, model=model)
        st.session_state["copilot"] = Copilot(repo=repo, client=client)
        st.session_state["copilot_cache_key"] = cache_key
    return st.session_state["copilot"]


def _ask_and_render(cop: Copilot, user_message: str) -> None:
    """Send a user message, render assistant reply, persist to session state."""
    st.session_state["copilot_messages"].append({
        "role": "user",
        "content": user_message,
    })
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Σκέφτομαι..."):
            resp = cop.ask(user_message)
        st.markdown(resp.text)
        if resp.tool_calls_made:
            with st.expander(
                f"🔧 Εργαλεία που χρησιμοποιήθηκαν ({len(resp.tool_calls_made)})"
            ):
                for t in resp.tool_calls_made:
                    st.code(f"{t['name']}({t['args']})", language="python")

    st.session_state["copilot_messages"].append({
        "role": "assistant",
        "content": resp.text,
        "tools_used": resp.tool_calls_made,
    })
