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

Οι εκδόσεις των βιβλιοθηκών ορίζονται στο `requirements.txt` (κάτω όρια).
Δοκιμασμένος συνδυασμός (Σεπτέμβριος 2026):

```
Python 3.11.x
pandas 3.0 · numpy 2.4 · scipy 1.16
sqlalchemy 2.0 · streamlit 1.64 · plotly 7.1
pytest 9 · loguru 0.7 · requests 2.32 · reportlab 4
```

Παλαιότερες εκδόσεις (pandas 2.x, streamlit ≥ 1.36, plotly 5.x) λειτουργούν
επίσης — το dashboard προσαρμόζεται αυτόματα στο API της εγκατεστημένης
έκδοσης Streamlit.

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

**Αναμενόμενο αποτέλεσμα**: `203 passed in ~20s`

---

## 3. Αναπαραγωγή Συγκεκριμένων Αποτελεσμάτων

Όλα τα τυχαία στοιχεία χρησιμοποιούν **σταθερά seeds** και η ημερομηνία
αναφοράς του συνθετικού dataset είναι **σταθερή** (snapshot 21.09.2026), ώστε
τα αποτελέσματα να είναι ίδια όποια μέρα κι αν τρέξει ο κώδικας. Οι τιμές
που ακολουθούν είναι τιμές αναφοράς για τα **συνθετικά** δεδομένα (seed 42)
— με πραγματικά (ανωνυμοποιημένα) δεδομένα SAP οι αριθμοί διαφέρουν.

Συντόμευση: `run_all.bat` (Windows) ή `./run_all.sh` (macOS/Linux) εκτελεί
όλα τα βήματα 3.1–3.6 και την αξιολόγηση πρόβλεψης (3.6α) με τη σειρά
(~10–12 λεπτά).

### 3.1 Synthetic Data Generation

```bash
python scripts/generate_sample_data.py            # seed 42, snapshot 2026-09-21
python scripts/generate_sample_data.py --snapshot-date today   # «ζωντανή» ημερομηνία
```

**Reproducible parameters**: seed 42 · 150 κωδικοί ανταλλακτικών αυτοκινήτων
(οικογένειες service / μηχανικά / ηλεκτρικά / φανοποιίας, τύπος HAWA, ABC
41/39/70) · 365 ημέρες ιστορικό · lead times 5–55 ημ. (Ευρώπη / Ασία) ·
προσομοιωμένος «ανθρώπινος planner» για το As-Is (εβδομαδιαίες
αναθεωρήσεις με παραλείψεις 10–35 %, καθυστερήσεις 0–7 ημ., μεγάλες
παρτίδες 15–30 % πάνω από το ROP) · 8 % αδρανή υλικά · 5 % νέα υλικά ·
εποχικότητα ανά οικογένεια (χειμερινά / θερινά είδη). Το master data (SS, ROP,
lot sizing) παράγεται από το ιστορικό με τους ίδιους κανόνες που εφαρμόζει
το `master_data_enrichment.py` στα πραγματικά δεδομένα.

**Output**: `data/samples/*.csv` (materials, stock, purchase_orders, movements)

**Verification**: `materials.csv` → 150 γραμμές· `movements.csv` → 18.622
γραμμές (18.047 × 601, 575 × 101)· `purchase_orders.csv` → 37 ανοιχτές
παραγγελίες· αξία αποθέματος snapshot ≈ €911 χιλ.· το snapshot αποθέματος
ισούται με άνοιγμα + παραλαβές − εξαγωγές (εσωτερικά συνεπές dataset).

### 3.2 ETL Pipeline

```bash
python scripts/run_etl.py
```

**Output**: `replenishment.db` (SQLite)

**Verification**:
```sql
SELECT COUNT(*) FROM materials;  -- 150
SELECT COUNT(*) FROM movements;  -- 18,622
SELECT MAX(snapshot_date) FROM stock;  -- 2026-09-21 (= ημερομηνία αναφοράς)
```

### 3.3 Agent Run

```bash
python scripts/run_agent.py
```

**Output** (συνθετικά δεδομένα): «Total proposals: 67 · Materials covered: 47
· Expedite alerts: 1 · Total value: €284,854» και ο πίνακας `proposals` στη βάση.

### 3.4 Backtest

```bash
python scripts/run_validation.py                      # 60 ημέρες, realistic
python scripts/run_validation.py --all-scenarios
python scripts/run_validation.py --sensitivity
```

**Τιμές αναφοράς** (συνθετικά δεδομένα, realistic, παράθυρο 60 ημερών
24.07–21.09.2026, κόστη για το παράθυρο): TCO As-Is €37.398 → To-Be €32.587
(−12,9 %, −€4.811)· holding −9,5 %· κόστος ελλείψεων −72 %· κόστος
παραγγελιών −1 % (102 → 101 παραγγελίες)· cycle service level 99,0 % →
99,7 %· fill rate 100 % → 99,95 %· ημέρες έλλειψης 90 → 27· μέση αξία
αποθέματος €900 χιλ. → €815 χιλ. Σενάρια: conservative −10,0 %, realistic
−12,9 %, aggressive −16,0 %. Ευαισθησία: −6,6 % έως −19,3 % (όλες θετικές).
ABC: A −18,1 %, B −8,7 %, C −6,7 %.

**Output**: `validation_report.csv`, `validation_report_abc.csv`,
`validation_report_all_scenarios.csv`, `validation_report_sensitivity.csv`

### 3.5 Τυχαία παράθυρα + Bootstrap

```bash
python scripts/run_bootstrap.py --n-samples 30 --window-size 60 --seed 42   # ~5 λεπτά
```

**Τιμές αναφοράς** (συνθετικά δεδομένα): μέση εξοικονόμηση €3.724 ανά
παράθυρο 60 ημερών (διάμεσος €3.432, SD €972)· 95 % CI του μέσου (bootstrap,
B = 2.000) [€3.382, €4.077]· t-CI [€3.361, €4.086]· 30/30 παράθυρα θετικά·
t = 20,99· p < 0,001 (bootstrap), p < 0,0001 (t-test, sign test) →
στατιστικά σημαντικό. Το παράθυρο είναι 60 ημέρες (όχι 21) ώστε να περιέχει
και τις παραδόσεις των παραγγελιών του πράκτορα (μέγιστο lead time 55 ημ.).

**Output**: `bootstrap_report.csv` (ανά παράθυρο), `bootstrap_report_summary.csv`

### 3.6 Rule Ablation Study

```bash
python scripts/run_rule_ablation.py --window-days 60 --stress-test
```

**Output**: `ablation_report.csv` — μεταβολή κάθε KPI όταν αφαιρείται ένας
κανόνας. Με τα ίδια δεδομένα οι αριθμοί είναι ντετερμινιστικοί.

**Τιμές αναφοράς** (stress test, baseline TCO €169.575, service 83,2 %):
αφαίρεση R-SAFETY-BUFFER-A → TCO −€3.629· R-LONG-LEAD-BUFFER → −€1.085·
R-DEAD-STOCK → −€908· R-MOQ-ENFORCE → −€365· R-CALENDAR-SHIFT → −€29·
R-EXPEDITE / R-COST-ESTIMATE → 0 (ενημερωτικοί). Οι buffer κανόνες κοστίζουν
στη ντετερμινιστική προσομοίωση — βλ. ΔΕ §4.7.2.

### 3.6α Αξιολόγηση Πρόβλεψης (walk-forward)

```bash
python scripts/run_forecast_eval.py
```

**Τιμές αναφοράς** (128 υλικά με επαρκές ιστορικό, εβδομαδιαίο WMAPE):
μέσος WMAPE simple average 66,6 % · moving average 68,4 % · exponential
smoothing 67,0 % (διάμεσοι 57,2 / 57,5 / 54,5 %)· βέλτιστη μέθοδος ανά
υλικό: SA 67, MA 26, ES 35. Με `run_validation.py --forecast-method X`:
MA −12,9 %, SA −13,3 %, ES +1,6 %, auto −11,1 % (ΔΕ §4.9).

**Output**: `forecast_report.csv`, `forecast_report_summary.csv`

### 3.7 Dashboard

```bash
streamlit run dashboard/app.py
```

Ανοίγει στο `http://localhost:8501`. Το tab «As-Is vs To-Be» διαβάζει τα CSV
των βημάτων 3.4–3.6· το tab «Πρόβλεψη ζήτησης» χρησιμοποιεί walk-forward
validation με σταθερά splits, οπότε είναι αναπαράξιμο.

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

**Αναμενόμενο**: 203 passed, 0 failed, 0 errors (κάλυψη `src/` ≈ 65 %).

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

| Component | File | Seed | Σκοπός |
|---|---|---|---|
| Sample data generator | `scripts/generate_sample_data.py` | `42` + σταθερό snapshot 2026-09-21 | Ίδιο dataset κάθε φορά |
| Bootstrap — τυχαία παράθυρα | `scripts/run_bootstrap.py` | `42` (CLI `--seed`) | Ίδια παράθυρα |
| Bootstrap — επαναδειγματοληψία μέσου | `src/utils/bootstrap.py` | `42` (ίδιο seed) | Ίδιο CI, B = 2.000 |
| Anonymization | `src/data_layer/anonymization.py` | MD5-based | Same input → same pseudonym |

Για διαφορετικό seed: `python scripts/run_bootstrap.py --seed 123`.

---

## 7. Διάρκεια Εκτέλεσης (Reference Benchmarks)

Σε laptop Intel i7 / 16 GB RAM, χωρίς GPU, 150 υλικά:

| Λειτουργία | Διάρκεια |
|---|---|
| Sample data generation | ~1 sec |
| ETL pipeline | ~3 sec |
| Agent run | ~2 sec |
| Backtest single scenario (60 ημ.) | ~10 sec |
| Backtest all scenarios (×3) | ~30 sec |
| Sensitivity analysis (×9) | ~1,5 min |
| Bootstrap (30 × 60 ημ.) | ~5 min |
| Forecast evaluation (150 υλικά × 3 μέθοδοι) | ~1 min |
| Rule ablation (×8 backtests) | ~1 min |
| Test suite (203 tests) | ~20 sec |
| Streamlit dashboard load | ~3 sec |

Με 1.500+ υλικά οι χρόνοι κλιμακώνονται περίπου γραμμικά (×10).

---

## 8. Αναμενόμενα Output Files

Μετά από πλήρη εκτέλεση:

```
replenishment-agent/
├── replenishment.db                    # SQLite database
├── data/samples/                       # 4 generated CSVs
├── validation_report.csv               # Backtest (Πίν. 4.6)
├── validation_report_abc.csv           # Ανά κλάση ABC (Πίν. 4.8)
├── validation_report_all_scenarios.csv # Σενάρια κόστους (Πίν. 4.7)
├── validation_report_sensitivity.csv   # Ευαισθησία (Πίν. 4.11)
├── bootstrap_report.csv                # Ανά παράθυρο (Πίν. Γ.1, Σχ. 4.2)
├── bootstrap_report_summary.csv        # Συγκεντρωτικά (Πίν. 4.9)
├── ablation_report.csv                 # Rule ablation (Πίν. 4.10)
├── forecast_report.csv                 # WMAPE ανά υλικό/μέθοδο
├── forecast_report_summary.csv         # Πρόβλεψη (Πίν. 4.12–4.13)
└── logs/agent_YYYYMMDD.log             # Ημερολόγιο εκτέλεσης
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
