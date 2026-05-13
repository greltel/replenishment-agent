# Reproducibility Guide

> Πλήρης τεκμηρίωση για την αναπαραγωγή των αποτελεσμάτων της Διπλωματικής
> Εργασίας. Με βάση τις προδιαγραφές που αναφέρονται εδώ, ένας τρίτος
> ερευνητής (π.χ. μέλος εξεταστικής επιτροπής) μπορεί να αναπαραγάγει
> κάθε αριθμητικό αποτέλεσμα της εργασίας.

---

## 1. Σύστημα Ανάπτυξης & Δοκιμών

### 1.1 Hardware

Το σύστημα δοκιμάστηκε σε:

| Στοιχείο | Specification |
|---|---|
| **CPU** | Intel Core i7 (8 cores) ή ισοδύναμο AMD |
| **RAM** | 16 GB |
| **Storage** | SSD, ~2 GB free για το project |
| **OS** | Windows 10/11, macOS 13+, ή Linux (Ubuntu 22.04+) |

**Σημείωση**: Δεν απαιτείται GPU. Όλοι οι αλγόριθμοι τρέχουν σε CPU.

### 1.2 Software

| Component | Version | Σχόλιο |
|---|---|---|
| **Python** | 3.11.x | Δοκιμασμένο σε 3.10-3.12 |
| **pip** | Latest | Για package management |
| **Git** | 2.40+ | Προαιρετικό (για κλωνοποίηση από GitHub) |
| **Ollama** | Latest | Μόνο εάν θέλετε AI Copilot |

### 1.3 Python Dependencies

Το αρχείο `requirements.txt` έχει pinned versions των key dependencies:

```
streamlit==1.36.x
pandas==2.2.x
numpy==1.26.x
sqlalchemy==2.0.x
plotly==5.22.x
reportlab==4.2.x
pytest==8.2.x
pypdf==4.2.x
ollama==0.3.x
faker==25.x
loguru==0.7.x
```

**Άλλες versions ενδέχεται να δουλεύουν** αλλά τα παραπάνω είναι τα
δοκιμασμένα.

---

## 2. Εγκατάσταση από το Μηδέν

### Βήμα 1: Κατέβασμα του Κώδικα

**Επιλογή A — Git clone (συνιστάται)**:

```bash
git clone https://github.com/greltel/replenishment-agent.git
cd replenishment-agent
```

**Επιλογή B — Direct download από zip**:

```bash
# Unzip το παραδοτέο zip
unzip replenishment-agent.zip
cd replenishment-agent
```

### Βήμα 2: Εικονικό Περιβάλλον Python

**Windows (PowerShell)**:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (CMD)**:
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Βήμα 3: Εγκατάσταση Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Διάρκεια: 2-5 λεπτά ανάλογα με τη σύνδεση internet.

### Βήμα 4: Επαλήθευση Εγκατάστασης

```bash
pytest tests/ -q
```

**Αναμενόμενο αποτέλεσμα**: `183 passed in ~17s`

---

## 3. Αναπαραγωγή Συγκεκριμένων Αποτελεσμάτων

Για να εξασφαλιστεί η reproducibility, όλα τα random elements του κώδικα
χρησιμοποιούν **fixed seeds**.

### 3.1 Synthetic Data Generation

```bash
python scripts/generate_sample_data.py
```

**Reproducible parameters**:
- Random seed: 42 (hardcoded στο `generate_sample_data.py`)
- 150 materials με συγκεκριμένη κατανομή ABC class
- 365 ημέρες ιστορικών movements
- ABC distribution: ~17% A, ~26% B, ~57% C (deterministic από seed)

**Output**: `data/samples/*.csv` (6 αρχεία)

**Verification**: Η πρώτη γραμμή των materials θα είναι πάντα
`MAT00001,PVC ring 2mm,ROH,KG,C,...`

### 3.2 ETL Pipeline

```bash
python scripts/run_etl.py
```

**Output**: `replenishment.db` (SQLite)

**Verification**:
```sql
SELECT COUNT(*) FROM materials;  -- 150
SELECT COUNT(*) FROM movements;  -- ~15,000-20,000
```

### 3.3 Agent Run

```bash
python scripts/run_agent.py
```

**Output**:
- Console: "Total proposals: 586" (deterministic)
- DB: `proposals` table populated

### 3.4 Backtest Single Scenario

```bash
python scripts/run_validation.py --window-days 60 --scenario realistic
```

**Reproducible KPIs** (με synthetic data):
- Service level: 100.00% (κάλη tied)
- Holding cost As-Is: €586,722
- Holding cost To-Be: €403,837
- Δ holding: −31.17%

### 3.5 Bootstrap Confidence Intervals

```bash
python scripts/run_bootstrap.py --n-samples 30 --seed 42
```

**Reproducible output** (με seed=42):
- Mean savings: +€64,568
- 95% CI: [+€45,665, +€85,506]
- p-value: 0.0000
- Decision: SIGNIFICANT

**Σημαντικό**: Διαφορετικά seeds θα δώσουν διαφορετικά intervals (φυσικά).
Το seed=42 είναι standard στην έρευνα machine learning.

### 3.6 Rule Ablation Study

```bash
python scripts/run_rule_ablation.py --window-days 60 --stress-test
```

**Reproducible output**: Σχετικές διαφορές κάθε rule έναντι baseline. Με
τα ίδια synthetic data, οι αριθμοί θα είναι deterministic.

### 3.7 Forecast Dashboard

```bash
streamlit run dashboard/app.py
```

Ανοίγει στο `http://localhost:8501`. Το tab "Forecast" χρησιμοποιεί
walk-forward validation με fixed splits, οπότε αναπαράξιμο.

---

## 4. Αναπαραγωγή Tests

```bash
# Όλα τα tests
pytest tests/ -v

# Συγκεκριμένη κατηγορία
pytest tests/test_bootstrap.py -v
pytest tests/test_rule_ablation.py -v
pytest tests/test_forecasting.py -v

# Με coverage report
pytest --cov=src --cov-report=html
# Open: htmlcov/index.html
```

**Αναμενόμενο**: 183 passed, 0 failed, 0 errors.

---

## 5. AI Copilot Reproducibility

Το AI Copilot tab απαιτεί επιπλέον setup:

### 5.1 Εγκατάσταση Ollama

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Κατεβάστε από: https://ollama.com/download/windows
```

### 5.2 Pull του Μοντέλου

```bash
ollama pull llama3.1:8b
```

**Μέγεθος**: ~4.7 GB

### 5.3 Πιστοποίηση Λειτουργίας

```bash
ollama run llama3.1:8b "Hello"
```

Πρέπει να απαντήσει εντός 2-15 δευτερολέπτων (CPU dependent).

**Σημαντικό για reproducibility**: Επειδή το LLM είναι probabilistic,
οι απαντήσεις του Copilot ΔΕΝ είναι deterministic. Όμως οι **κλήσεις των
tools** είναι αναπαράξιμες (επιστρέφουν πάντα το ίδιο αποτέλεσμα από τη DB).

---

## 6. Random Seeds — Πλήρης Λίστα

Για πλήρη reproducibility, τα ακόλουθα seeds είναι hardcoded:

| Component | File | Seed | Σκοπός |
|---|---|---|---|
| Sample data generator | `scripts/generate_sample_data.py` | `42` | Synthetic data deterministic |
| Bootstrap analysis | `scripts/run_bootstrap.py` | `42` (CLI default) | Same random windows |
| Anonymization | `src/data_layer/anonymization.py` | MD5-based | Same input → same pseudonym |

Για διαφορετικό seed στο bootstrap:

```bash
python scripts/run_bootstrap.py --seed 123
```

---

## 7. Διάρκεια Εκτέλεσης (Reference Benchmarks)

Σε Intel i7 με 16GB RAM, χωρίς GPU:

| Λειτουργία | Διάρκεια |
|---|---|
| Sample data generation | ~5 sec |
| ETL pipeline | ~3 sec |
| Agent run | ~10 sec |
| Backtest single scenario | ~30-60 sec |
| Backtest all scenarios (×3) | ~2-3 min |
| Sensitivity analysis (×9) | ~5-10 min |
| Bootstrap (30 samples) | ~10-15 min |
| Rule ablation (×8 backtests) | ~3-5 min |
| Test suite | ~17 sec |
| Streamlit dashboard load | ~3 sec |

---

## 8. Αναμενόμενα Output Files

Μετά από πλήρη εκτέλεση:

```
replenishment-agent/
├── replenishment.db                    # SQLite database
├── data/
│   ├── samples/                        # 6 generated CSVs
│   └── anonymized/                     # (εάν τρέξατε anonymization)
├── validation_report.csv               # Single-scenario backtest
├── validation_report_all_scenarios.csv # Cross-scenario
├── bootstrap_report.csv                # Per-sample bootstrap data
├── bootstrap_report_summary.csv        # Aggregate stats
├── ablation_report.csv                 # Rule ablation results
└── docs/parartima_d_technical_guide.pdf
```

---

## 9. Troubleshooting

### Πρόβλημα: `ModuleNotFoundError: No module named 'src'`

**Αιτία**: Δεν τρέχετε από το project root.

**Λύση**: 
```bash
cd path/to/replenishment-agent
python scripts/run_validation.py
```

### Πρόβλημα: `sqlite3.OperationalError: no such table: materials`

**Αιτία**: Δεν έχει τρέξει το ETL.

**Λύση**:
```bash
python scripts/generate_sample_data.py
python scripts/run_etl.py
```

### Πρόβλημα: Streamlit error στο Forecast tab

**Αιτία**: Plotly/pandas conflict με Timestamps (fixed στην τελευταία έκδοση).

**Λύση**: Verify ότι έχετε `dashboard/components/forecast_tab.py` με το
patch (χρήση `add_shape` αντί `add_vline`).

### Πρόβλημα: AI Copilot δεν απαντά

**Αιτία**: Ollama δεν τρέχει.

**Λύση**:
```bash
# Verify
ollama list

# Restart
ollama serve  # σε ξεχωριστό terminal
```

---

## 10. Επικοινωνία για Reproducibility Issues

Σε περίπτωση που η αναπαραγωγή αποτυχάνει:

1. Ελέγξτε ότι όλα τα requirements είναι installed (`pip list`)
2. Ελέγξτε ότι τρέχει το test suite (`pytest`)
3. Ελέγξτε το hardware/OS match
4. Επικοινωνήστε με τον συγγραφέα μέσω GitHub Issues

**Repository**: https://github.com/greltel/replenishment-agent

---

*Αναπαραγωγιμότητα είναι θεμελιώδης αρχή της επιστημονικής έρευνας. Όλα τα
αποτελέσματα της παρούσας ΔΕ είναι ντετερμινιστικά (deterministic) όταν
χρησιμοποιούνται τα προβλεπόμενα seeds και τα synthetic δεδομένα του
project.*

*Παρόν document: Παράρτημα ΣΤ της Διπλωματικής Εργασίας*
