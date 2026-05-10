# Replenishment Agent

> Intelligent agent for inventory replenishment with SAP integration
> Athens MBA — Διπλωματική Εργασία

Πλήρως λειτουργικό prototype ενός ευφυούς πράκτορα που εκτελεί δυναμικό MRP
και παράγει αυτοματοποιημένες προτάσεις αναπλήρωσης. Βασίζεται σε αρχιτεκτονική
BDI (Belief-Desire-Intention) και διασυνδέεται με δεδομένα από SAP ERP.

## Quick Start (5 λεπτά)

```bash
# 1. Clone & enter
cd replenishment-agent

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate sample data (mock SAP exports — ~150 SKUs)
python scripts/generate_sample_data.py

# 5. Load data into SQLite
python scripts/run_etl.py

# 6. Run the agent
python scripts/run_agent.py

# 7. Run backtest validation (As-Is vs To-Be)
python scripts/run_validation.py

# 8. Launch dashboard
streamlit run dashboard/app.py
# → http://localhost:8501
```

## Δομή Project

```
replenishment-agent/
├── src/                    # Main package
│   ├── config.py           # Central configuration
│   ├── data_layer/         # SQLAlchemy models, ETL, repository
│   ├── agent/              # BDI agent implementation
│   ├── mrp/                # MRP engine + lot sizing policies
│   ├── rules/              # Business rules engine
│   ├── copilot/            # 🆕 AI Copilot (Ollama-based LLM assistant)
│   └── utils/              # KPIs, forecasting, calendar, logger
├── dashboard/              # Streamlit dashboard (5 tabs incl. Copilot)
├── tests/                  # pytest test suite (100 tests)
├── scripts/                # Entry points (CLI)
├── abap/                   # SAP ABAP extractor program
├── data/
│   ├── raw/                # SAP exports (git-ignored)
│   ├── anonymized/         # Anonymized datasets (git-ignored)
│   └── samples/            # Sample mock data (committed)
├── docs/                   # Documentation (incl. copilot_setup.md)
└── notebooks/              # Jupyter notebooks for analysis
```

## Πώς να χρησιμοποιήσετε με ΠΡΑΓΜΑΤΙΚΑ SAP δεδομένα

Έχετε δύο επιλογές για την εξαγωγή:

**Επιλογή Α — ABAP Z-Program (συνιστάται):**
1. Δείτε τον φάκελο `abap/` για το πρόγραμμα `ZMRP_AGENT_EXPORT` και οδηγίες εγκατάστασης
2. Τρέξτε το πρόγραμμα στο SAP — παράγει 6 CSV αρχεία με ένα κλικ
3. Αντιγράψτε τα στον φάκελο `data/raw/`
4. `python -m src.data_layer.anonymization`
5. Συνεχίστε από το βήμα 5 του Quick Start

**Επιλογή Β — Manual SE16N:**
1. Εξαγωγή πινάκων (MARA, MARC, MARD, EKKO, EKPO, MB51) ως Excel
2. Αρχεία στον φάκελο `data/raw/` με τα ονόματα: `MARA_export.xlsx` κ.λπ.
3. `python -m src.data_layer.anonymization`
4. Συνεχίστε από το βήμα 5 του Quick Start

Το `anonymization.py` αναγνωρίζει αυτόματα και τις δύο μορφές (xlsx & csv,
με `,` ή `;` separators).

### Smart defaults για ελλιπές master data

Σε πολλά SAP περιβάλλοντα (ιδίως sandbox / demo systems) τα MRP πεδία
(PLIFZ, EISBE, BSTMI κ.λπ.) είναι κενά ή μηδενικά. Το anonymization
εμπλουτίζει αυτόματα τα materials με smart defaults βάσει ιστορικών
δεδομένων:

| Πεδίο | Πηγή 1 (αν υπάρχει) | Πηγή 2 (derived) |
|---|---|---|
| Lead time | MARC.PLIFZ | PO history ή 14 days default |
| Safety stock | MARC.EISBE | `z × σ × √LT` (Silver-Pyke-Peterson) |
| Reorder point | MARC.MINBE | `avg_daily × LT + SS` |
| MOQ | MARC.BSTMI | Median PO qty ή 7 days demand |
| Lot sizing | MARC.DISLS | Από CV: WW/POQ/EOQ/FOQ |
| ABC | — | Pareto on `cost × annual_demand` |

### As-of date για ιστορικά datasets

Όταν τα δεδομένα σας δεν είναι "live", βάλτε στο `.env`:

```
AS_OF_DATE=auto      # ή 'YYYY-MM-DD' για συγκεκριμένη ημερομηνία
```

Αυτό κάνει τον agent να treat ως "σήμερα" την τελευταία ημερομηνία στα
data, αποτρέποντας false dead-stock alerts.

## 💬 AI Copilot (προαιρετικό)

Το dashboard περιλαμβάνει AI Copilot — chatbot που απαντά σε ερωτήσεις
στα Ελληνικά ή Αγγλικά για τις προτάσεις του agent. Χρησιμοποιεί **τοπικό
LLM** μέσω Ollama, οπότε **εταιρικά δεδομένα δεν φεύγουν από το laptop**.

**Setup:**
```bash
# 1. Install Ollama (ollama.com) και pull μοντέλο
ollama pull llama3.1:8b

# 2. Run dashboard — το copilot tab το ανιχνεύει αυτόματα
streamlit run dashboard/app.py
```

Πλήρεις οδηγίες: [`docs/copilot_setup.md`](docs/copilot_setup.md)

**Παραδείγματα ερωτήσεων:**
- *«Δώσε μου μια σύνοψη»*
- *«Ποια υλικά είναι κρίσιμα;»*
- *«Γιατί προτείνεις 500τμχ για το MAT123;»*
- *«Show me top 5 by demand»*

## Testing

```bash
pytest                              # Όλα τα tests
pytest --cov=src                    # Με coverage
pytest tests/test_mrp_engine.py -v  # Συγκεκριμένο file
```

## Architecture

Three-tier:

```
SAP / CSV exports  →  SQLite  →  BDI Agent  →  Dashboard
                                  (MRP + Rules)
```

Δείτε `docs/architecture.md` για λεπτομέρειες.

## Tech Stack

- **Python 3.11+** — main language
- **SQLAlchemy 2.0** — ORM
- **pandas / numpy** — data manipulation
- **scipy** — optimization (EOQ, Wagner-Whitin)
- **Streamlit + Plotly** — dashboard
- **pytest** — testing

## Επιβλέπων

Σωτήρης Γκαγιαλής (ΕΜΠ — Σχολή Μηχανολόγων Μηχανικών)

## AI Disclosure

Generative AI tools (Claude) χρησιμοποιήθηκαν για:
- Code scaffolding και documentation
- Σχεδιασμός αρχιτεκτονικής

Όλοι οι αλγόριθμοι, οι επιχειρησιακοί κανόνες και η ανάλυση είναι original και
έχουν επικυρωθεί από τον συγγραφέα.

## License

Proprietary — for academic use only.
