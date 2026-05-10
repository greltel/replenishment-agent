# AI Copilot — Setup Guide

The AI Copilot is an LLM-powered chat assistant that lets supply planners
query the replenishment system in natural language ("ποια υλικά είναι κρίσιμα
σήμερα;", "γιατί προτείνεις 500τμχ για το ΧΥΖ;"). It uses local inference
via [Ollama](https://ollama.com), so **εταιρικά δεδομένα δεν φεύγουν από το
laptop σας**.

## Architecture

```
User question                        Streamlit chat UI
       │                                    ▲
       ▼                                    │
┌─────────────────────────────────────────────────────┐
│  Copilot Orchestrator (src/copilot/orchestrator.py)│
│    1. Send prompt + tools schema to Ollama          │
│    2. If LLM asks for tool: execute & loop          │
│    3. Otherwise: return text                        │
└──────┬──────────────────────────────┬───────────────┘
       │                              │
       ▼                              ▼
┌────────────────┐         ┌──────────────────────────┐
│ Ollama (local) │         │ Tools (src/copilot/tools)│
│  llama3.1:8b   │         │  • get_summary           │
│                │         │  • list_critical_proposals│
└────────────────┘         │  • get_material_details  │
                            │  • explain_proposal      │
                            │  • search_proposals      │
                            │  • get_top_materials_… │
                            │  • get_abc_distribution  │
                            └──────┬───────────────────┘
                                   │
                                   ▼
                            SQLite DB (replenishment.db)
```

## Setup

### Step 1: Install Ollama

**Windows / macOS:** Download installer from [ollama.com](https://ollama.com).

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Step 2: Pull a model

```bash
# Recommended for general use (~5 GB):
ollama pull llama3.1:8b

# Better for non-English (~5 GB):
ollama pull qwen2.5:7b

# Smaller / faster (~4 GB):
ollama pull mistral:7b
```

### Step 3: Verify Ollama is running

```bash
ollama list                   # see installed models
curl http://localhost:11434   # should respond "Ollama is running"
```

### Step 4: Use the copilot

```bash
streamlit run dashboard/app.py
```

Στο dashboard, πηγαίνετε στο tab **💬 AI Copilot**.

## Usage Examples

The copilot understands questions in **Greek and English**. Examples:

| Question | Tools the copilot will likely call |
|---|---|
| "Δώσε μου μια σύνοψη" | `get_summary` |
| "Ποια υλικά χρειάζονται άμεση παραγγελία;" | `list_critical_proposals` |
| "Πες μου για το MAT4DA9F2C8" | `get_material_details` |
| "Γιατί προτείνεις 19000τμχ για αυτό το υλικό;" | `explain_proposal` |
| "Δείξε μου όλες τις προτάσεις A-class" | `search_proposals(abc_class="A")` |
| "What are our top 5 high-demand items?" | `get_top_materials_by_demand(n=5)` |
| "Πόσα υλικά είναι σε κάθε ABC κατηγορία;" | `get_abc_distribution` |

## Configuration

The copilot reads its settings from the dashboard UI (Ρυθμίσεις expander)
or from environment variables:

| Variable | Default | Description |
|---|---|---|
| (UI) Ollama URL | `http://localhost:11434` | Ollama API endpoint |
| (UI) Model | `llama3.1:8b` | Model name (must be pulled) |

## Adding new tools

To extend the copilot with a new capability:

1. **Implement** the function in `src/copilot/tools.py`:
   ```python
   def my_new_tool(repo: Repository, arg1: str) -> dict:
       ...
       return {"result": ...}
   ```
2. **Add the schema** to `TOOL_SCHEMAS`:
   ```python
   {
       "type": "function",
       "function": {
           "name": "my_new_tool",
           "description": "What it does and when to use it",
           "parameters": {
               "type": "object",
               "properties": {"arg1": {"type": "string", ...}},
               "required": ["arg1"],
           },
       },
   },
   ```
3. **Register** in `TOOL_FUNCTIONS`:
   ```python
   TOOL_FUNCTIONS["my_new_tool"] = my_new_tool
   ```
4. **Test** in `tests/test_copilot.py`

## Troubleshooting

**"Ollama δεν είναι έτοιμο"**
→ Make sure Ollama is running. From terminal: `ollama serve` (or just open the
  Ollama desktop app).

**"Model 'llama3.1:8b' is not pulled locally"**
→ Run: `ollama pull llama3.1:8b`

**The copilot makes up numbers / hallucinates**
→ This is a known weakness of smaller models. Try a bigger model
  (`llama3.1:70b` if you have ≥40GB RAM, or use Groq cloud for testing).
  The system prompt explicitly tells the model to use tools, but enforcement
  varies by model.

**Slow responses (>30 seconds)**
→ Inference on CPU is slow. Either:
  - Use a smaller model (mistral:7b or even phi3:mini)
  - Run on a machine with GPU (CUDA / Metal)
  - Increase Ollama's parallelism: `OLLAMA_NUM_PARALLEL=2 ollama serve`

**Greek responses come out broken**
→ Try `qwen2.5:7b` instead — it has better multilingual support than llama3.1.

## Why Ollama instead of OpenAI/Anthropic API?

| Aspect | Ollama (this project) | Cloud API (alternative) |
|---|---|---|
| **Data privacy** | ✅ Local, εταιρικά δεδομένα ασφαλή | ⚠️ Sends data to vendor |
| **Cost** | Free | ~$0.20/1M tokens |
| **Reproducibility** | ✅ Anyone can run the project | Requires API keys |
| **Quality** | Good (8B-70B models) | Excellent (GPT-4, Claude) |
| **Latency** | 2-15s on CPU, <2s on GPU | <1s |
| **Academic argument** | "Privacy-preserving AI" | Requires explanation |

For thesis purposes, **Ollama is the right choice** — defensible privacy
position, fully reproducible, no operational cost.
