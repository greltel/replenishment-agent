# Replenishment Agent

> Intelligent agent for inventory replenishment with SAP integration
> Athens MBA — Διπλωματική Εργασία (Γεώργιος Δράκος, επιβλέπων: Σωτήρης Γκαγιαλής)

Πλήρως λειτουργικό prototype ενός ευφυούς πράκτορα που εκτελεί δυναμικό MRP
και παράγει αυτοματοποιημένες προτάσεις αναπλήρωσης (**πότε** και **πόσο** για
κάθε υλικό). Βασίζεται σε αρχιτεκτονική BDI (Belief-Desire-Intention) και
διασυνδέεται με δεδομένα από SAP ERP (read-only ABAP extractor).

## Quick Start (5 λεπτά)

```bash
# 1. Clone & enter
git clone https://github.com/greltel/replenishment-agent.git
cd replenishment-agent

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate sample data (συνθετικά SAP exports — 150 κωδικοί ανταλλακτικών
#    αυτοκινήτων, 12 μήνες ιστορικό, βαθμονομημένα στο προφίλ εισαγωγέα)
python scripts/generate_sample_data.py

# 5. Load data into SQLite
python scripts/run_etl.py

# 6. Run the agent (perceive → deliberate → act)
python scripts/run_agent.py

# 7. Evaluation (As-Is vs To-Be, σενάρια, ευαισθησία, bootstrap, ablation)
python scripts/run_validation.py
python scripts/run_validation.py --all-scenarios
python scripts/run_validation.py --sensitivity
python scripts/run_bootstrap.py
python scripts/run_rule_ablation.py --stress-test
python scripts/run_forecast_eval.py

# 8. Launch dashboard
streamlit run dashboard/app.py
# → http://localhost:8501
```

Στα Windows μπορείτε απλώς να τρέξετε `run_all.bat` (κάνει τα βήματα 4–7,
~10–12 λεπτά) και μετά `start_dashboard.bat`. Σε Linux/macOS: `./run_all.sh`.

## Δομή Project

```
replenishment-agent/
├── src/                    # Main package
│   ├── config.py           # Central configuration (.env)
│   ├── data_layer/         # SQLAlchemy models, ETL, anonymization, repository
│   ├── agent/              # BDI agent (beliefs / desires / intentions)
│   ├── mrp/                # MRP engine + lot sizing (LFL, FOQ, EOQ, POQ, Wagner-Whitin)
│   ├── rules/              # Business rules engine (7 rules, priority order)
│   ├── copilot/            # AI Copilot (local LLM via Ollama, read-only tools)
│   └── utils/              # KPIs, cost model, bootstrap, forecasting, calendar, logger
├── dashboard/              # Streamlit dashboard (6 tabs)
├── tests/                  # pytest test suite (203 tests)
├── scripts/                # Entry points (CLI)
├── abap/                   # SAP ABAP extractor program (ZMRP_AGENT_EXPORT)
├── data/
│   ├── raw/                # SAP exports (git-ignored)
│   ├── anonymized/         # Anonymized datasets (git-ignored)
│   └── samples/            # Generated mock data (git-ignored, reproducible με seed 42)
└── docs/                   # Documentation (Παραρτήματα ΔΕ, οδηγοί)
```

## Πώς αποφασίζει ο πράκτορας (σύνοψη — αναλυτικά στη ΔΕ, Κεφ. 4)

1. **Perceive**: απόθεμα, ανοιχτές παραγγελίες, ιστορικό κινήσεων
   (καταναλώσεις = εξαγωγές προς πελάτες 601/251 + αναλώσεις 261/201/281) και
   master data ανά υλικό, ως την ημερομηνία αναφοράς.
2. **MRP engine** (time-phased, ορίζοντας 60 ημερών): πρόβλεψη ζήτησης
   (default κινητός μέσος), προβολή αποθέματος, καθαρές απαιτήσεις κάτω από
   το απόθεμα ασφαλείας, lot sizing με την πολιτική του υλικού (LFL / FOQ /
   EOQ / POQ / Wagner-Whitin — αυτόματη επιλογή ABC × CV αν λείπει το
   MARC-DISLS), offset κατά lead time και **ενοποίηση εκδόσεων ανά 7 ημέρες**
   (ένα planned order αντί πολλών ημερήσιων).
3. **Rule engine** (7 κανόνες με σειρά προτεραιότητας): R-DEAD-STOCK,
   R-EXPEDITE, R-SAFETY-BUFFER-A (+20 % στα A), R-LONG-LEAD-BUFFER (+15 % αν
   LT > 30 ημ.), R-MOQ-ENFORCE (≥ MOQ, πολλαπλάσιο συσκευασίας, ακέραιες
   μονάδες για διακριτές UoM), R-CALENDAR-SHIFT, R-COST-ESTIMATE.
4. **Act**: εγγραφή προτάσεων (πότε / πόσο / γιατί) στη βάση → dashboard /
   AI Copilot.

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
με `,` ή `;` separators), διορθώνει το πρόσημο των κινήσεων βάσει BWART και
αντιστοιχίζει τα SAP lot-sizing procedures (MARC-DISLS: EX, FX, WB, MB, PK,
WI, BE, SP …) στις εσωτερικές πολιτικές LFL/FOQ/POQ/WW.

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
| Lot sizing | MARC.DISLS | ABC × CV (Πίν. 4.3 ΔΕ): A→WW/POQ/LFL, B→EOQ, C→FOQ |
| Fixed lot (FOQ) | MARC.BSTFE | 4 εβδομάδες ζήτησης, πολλαπλάσιο MOQ |
| ABC | — | Pareto on `cost × annual_demand` |

### Ημερομηνία αναφοράς (as-of date)

Ο πράκτορας χρειάζεται μια έννοια «σήμερα» δεμένη με τα δεδομένα. Με την
προεπιλογή `AS_OF_DATE=auto` (στο `.env`) χρησιμοποιείται η **πιο πρόσφατη**
από τις ημερομηνίες: τελευταίο stock snapshot (MARD) και τελευταία κίνηση
(MB51). Εναλλακτικά `AS_OF_DATE=YYYY-MM-DD` για συγκεκριμένη ημερομηνία.
Όλα τα scripts αξιολόγησης χρησιμοποιούν την ίδια ημερομηνία ως τέλος του
παραθύρου (override με `--end`).

## 📊 Backtest & Validation

Ο agent αξιολογείται μέσω συγκριτικού backtest As-Is vs To-Be πάνω στα
ιστορικά δεδομένα:

- **As-Is**: αναπαραγωγή των πραγματικών κινήσεων (κατανάλωση + παραλαβές 101)
- **To-Be**: ο agent αποφασίζει κάθε 7 ημέρες βλέποντας μόνο κινήσεις ≤ t
  (χωρίς look-ahead)· οι παραγγελίες του φτάνουν μετά το lead time·
  σε κάθε κύκλο εκδίδονται μόνο οι προτάσεις με ημερομηνία έκδοσης πριν τον
  επόμενο κύκλο (opening period), οι υπόλοιπες επανυπολογίζονται
- Και τα δύο σενάρια ξεκινούν από το **ίδιο** αρχικό απόθεμα (ανακατασκευή
  από το snapshot και τις κινήσεις) και από την **ίδια** pipeline παραγγελιών
  σε εξέλιξη (παραλαβές μέσα στο lead time από την έναρξη του παραθύρου)

Τρία cost scenarios υποστηρίζονται:

| Scenario | Holding rate | Description |
|---|---|---|
| `conservative` | ~12% | Stable industry, cheap capital, low margins |
| `realistic` | ~20% | Typical European manufacturer (default) |
| `aggressive` | ~28% | Tech / fashion / fast obsolescence |

**Βασικές εντολές:**

```bash
# Κύριο backtest (default: 60 ημέρες, realistic) → validation_report.csv + _abc.csv
python scripts/run_validation.py
python scripts/run_validation.py --window-days 90 --scenario aggressive

# Όλα τα σενάρια ταυτόχρονα → validation_report_all_scenarios.csv
python scripts/run_validation.py --all-scenarios

# Sensitivity analysis (±20% σε LT, ±10% demand, ±20% holding) → _sensitivity.csv
python scripts/run_validation.py --sensitivity
```

### Βάση κόστους (διαβάστε πριν αναφέρετε οποιοδήποτε €)

Όλα τα κόστη εκφράζονται **για τη διάρκεια του παραθύρου** προσομοίωσης:

```
holding_cost  = μέση αξία αποθέματος × ετήσιο holding rate × (ημέρες / 365)
stockout_cost = χαμένες πωλήσεις + premium επείγουσας προμήθειας (μέσα στο παράθυρο)
ordering_cost = πλήθος παραγγελιών × €50
TCO           = holding + stockout + ordering
```

Παράλληλα αναφέρεται το **ετήσιο ισοδύναμο** (`*_annualized`, = τιμή
παραθύρου × 365 / ημέρες). Χρησιμοποιήστε την τιμή παραθύρου όταν
περιγράφετε το backtest και το ετήσιο ισοδύναμο για το business case — ποτέ
μην πολλαπλασιάσετε ξανά το ετήσιο ισοδύναμο με 365/ημέρες.

**Cost methodology** (Silver-Pyke-Peterson 1998, Vollmann et al. 2005):
- Holding cost decomposed: capital + warehouse + obsolescence + insurance + shrinkage
- Stockout cost decomposed: lost sales (margin foregone) + expedite premium
- Per ABC class breakdown (`validation_report_abc.csv`)
- Cost imputation όταν λείπει `standard_cost` (από material_type + ABC class)

**Output**: CSV reports + dashboard tab «⚖️ As-Is vs To-Be»

### 🔬 Rule Ablation Study

Για να ποσοτικοποιηθεί η συνεισφορά **κάθε rule** στην απόδοση του agent,
το backtest τρέχει πολλές φορές, κάθε φορά απενεργοποιώντας έναν
διαφορετικό κανόνα (**leave-one-out**, Hooker 1995· Lipton 2018). Η
προσομοίωση είναι η ίδια με του κύριου backtest (`simulate_tobe`), άρα το
baseline του ablation ταυτίζεται εξ ορισμού με το To-Be.

```bash
# Default (ιστορικό αρχικό απόθεμα)
python scripts/run_rule_ablation.py

# Stress test (χαμηλό αρχικό απόθεμα = 50% SS — αναδεικνύει τη συμβολή κάθε rule)
python scripts/run_rule_ablation.py --stress-test
```

**Output**: `ablation_report.csv` με στήλες `disabled_rule`, `n_proposals`,
`Δ_proposals`, `service_level_pct`, `Δ_service_pp`, `holding_cost_eur`,
`Δ_holding`, `stockout_cost_eur`, `Δ_stockout_cost`, `Δ_stockout_days`,
`tco_eur`, `Δ_tco`, και ερμηνεία στην κονσόλα. Κανόνες χωρίς μετρήσιμη
επίδραση στα KPI είναι είτε **ενημερωτικοί** (σήμανση επείγοντος, εκτίμηση
κόστους — δεν αλλάζουν ποσότητες) είτε **δίχτυα ασφαλείας** που δεν
ενεργοποιήθηκαν στο συγκεκριμένο παράθυρο.

## 📈 Demand Forecast (Dashboard Tab)

- **Ιστορικό κατανάλωσης** ανά υλικό (90/180/365/730 ημέρες)
- **Πρόβλεψη** για τις επόμενες 14-90 ημέρες με 3 μεθόδους ταυτόχρονα
  (simple average, moving average 30d, exponential smoothing α=0.3)
- **Ακρίβεια** μέσω walk-forward validation (5 folds, rolling-origin)
- **Metrics**: MAE, RMSE, WMAPE, Bias (εβδομαδιαίο επίπεδο — το MAPE δεν
  ορίζεται σε διακοπτόμενη ζήτηση με μηδενικές εβδομάδες)
- **`python scripts/run_forecast_eval.py`** → `forecast_report.csv` (WMAPE ανά
  υλικό/μέθοδο) και `forecast_report_summary.csv` (Πίν. 4.12–4.13 ΔΕ)
- Μέθοδος `auto` (walk-forward επιλογή ανά υλικό) υπάρχει ως επιλογή
  (`run_agent.py --method auto`, `run_validation.py --forecast-method auto`)·
  **default παραμένει ο κινητός μέσος** — βλ. ΔΕ §4.9.2 γιατί

**Methodology reference**: Bergmeir & Benítez (2012).

## 📊 Τυχαία παράθυρα + Bootstrap Confidence Intervals

Δύο στάδια (ΔΕ §3.6.3):

1. **N τυχαία παράθυρα** (default 30 × 60 ημέρες, seed 42) → εξοικονόμηση
   sᵢ = TCO(As-Is) − TCO(To-Be) ανά παράθυρο
2. **Bootstrap του μέσου** (B = 2.000 επαναδειγματοληψίες) → 95% percentile
   CI του μέσου + bootstrap p-value· συμπληρωματικά t-CI (df = N−1),
   μονόπλευρος t-test και ακριβής έλεγχος προσήμου

```bash
python scripts/run_bootstrap.py                       # 30 × 60 ημέρες (~5 λεπτά)
python scripts/run_bootstrap.py --n-samples 100       # στενότερα CI
python scripts/run_bootstrap.py --scenario aggressive --window-size 90
```

**Output**:
- Console report με thesis-ready statement
- `bootstrap_report.csv` (ανά παράθυρο — Παράρτημα Γ, Πίνακας Γ.1)
- `bootstrap_report_summary.csv` (συγκεντρωτικά — Πίνακας 4.9)

**Methodology references**: Efron & Tibshirani (1993)· Politis & Romano
(1994)· Bergmeir, Hyndman & Koo (2018).

## Αντιστοίχιση αρχείων → πίνακες ΔΕ

| Αρχείο | Εντολή | Πίνακας/Σχήμα ΔΕ |
|---|---|---|
| `validation_report.csv` | `run_validation.py` | Πίν. 4.6 |
| `validation_report_abc.csv` | `run_validation.py` | Πίν. 4.8 |
| `validation_report_all_scenarios.csv` | `run_validation.py --all-scenarios` | Πίν. 4.7 |
| `validation_report_sensitivity.csv` | `run_validation.py --sensitivity` | Πίν. 4.11 |
| `bootstrap_report_summary.csv` | `run_bootstrap.py` | Πίν. 4.9 |
| `bootstrap_report.csv` | `run_bootstrap.py` | Πίν. Γ.1, Σχ. 4.2 |
| `ablation_report.csv` | `run_rule_ablation.py --stress-test` | Πίν. 4.10 |
| `forecast_report_summary.csv` | `run_forecast_eval.py` | Πίν. 4.12, 4.13 |

## 📖 Τεκμηρίωση

- **`docs/parartima_d_technical_guide.pdf`** — Τεχνικός Οδηγός Υλοποίησης
  (Παράρτημα Δ), παράγεται με `python scripts/generate_parartima_d.py`
- `docs/AI_DISCLOSURE.md` — Δήλωση χρήσης Generative AI (Παράρτημα Ε)
- `docs/DILOSI_EKPONISIS.md` — Υπεύθυνη δήλωση εκπόνησης (template)
- `docs/REPRODUCIBILITY.md` — Οδηγός αναπαραγωγής αποτελεσμάτων (Παράρτημα ΣΤ)
- `docs/LIMITATIONS_AND_FUTURE_WORK.md` — Περιορισμοί + μελλοντική εργασία
- `docs/copilot_setup.md` — Οδηγίες AI Copilot (Ollama)

## 💬 AI Copilot (προαιρετικό)

Το dashboard περιλαμβάνει AI Copilot — chatbot που απαντά σε ερωτήσεις
στα Ελληνικά ή Αγγλικά για τις προτάσεις του agent. Χρησιμοποιεί **τοπικό
LLM** μέσω Ollama, οπότε **εταιρικά δεδομένα δεν φεύγουν από το laptop**.

```bash
ollama pull llama3.1:8b        # μία φορά (~4,7 GB)
streamlit run dashboard/app.py # το copilot tab το ανιχνεύει αυτόματα
```

Πλήρεις οδηγίες: [`docs/copilot_setup.md`](docs/copilot_setup.md)

## Testing

```bash
pytest                              # Όλα τα tests (τρέχουν σε απομονωμένη βάση)
pytest --cov=src                    # Με coverage
pytest tests/test_mrp_engine.py -v  # Συγκεκριμένο file
```

## Architecture

Three-tier:

```
SAP / CSV exports  →  SQLite  →  BDI Agent  →  Dashboard
                                  (MRP + Rules)
```

Λεπτομέρειες στο `docs/parartima_d_technical_guide.pdf`.

## Tech Stack

- **Python 3.11+** — main language
- **SQLAlchemy 2.0** — ORM
- **pandas / numpy / scipy** — data manipulation, statistics
- **Streamlit + Plotly** — dashboard
- **pytest** — testing

## Επιβλέπων

Σωτήρης Γκαγιαλής (ΕΜΠ — Σχολή Μηχανολόγων Μηχανικών)

## AI Disclosure

Generative AI tools (Claude) χρησιμοποιήθηκαν για code scaffolding,
documentation και σχεδιασμό αρχιτεκτονικής. Όλοι οι αλγόριθμοι, οι
επιχειρησιακοί κανόνες και η ανάλυση έχουν επικυρωθεί από τον συγγραφέα.

## License

Proprietary — for academic use only.
