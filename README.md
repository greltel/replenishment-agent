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

Στα Windows υπάρχουν δύο ξεχωριστές ροές, που δεν επηρεάζουν η μία την άλλη:

| | Συνθετικά δεδομένα (samples) | Πραγματικά δεδομένα (pilot, `data/pilot/`) |
|---|---|---|
| Pipeline | `run_all.bat` (βήματα 4–7, ~10–12 λεπτά) | `run_all_pilot.bat` (ανωνυμοποίηση → agent → backtest, ~30–45 λεπτά στα ~50.000 ενεργά υλικά)· `run_all_pilot.bat --full` για όλες τις αξιολογήσεις (πολλές ώρες) |
| Βάση | `replenishment.db` | `replenishment_pilot.db` |
| Αναφορές | ρίζα του project | `reports/pilot/` |
| Dashboard | `start_dashboard.bat` → :8501 | `start_dashboard_pilot.bat` → :8502 |

Τα δύο dashboards μπορούν να τρέχουν ταυτόχρονα. Σε Linux/macOS:
`./run_all.sh` και `./run_all_pilot.sh [--full]`. Η επιλογή δεδομένων γίνεται
με τη μεταβλητή `DATA_SOURCE` (`samples` / `anonymized` / `auto`).

**Δεδομένα του pilot:** τα SAP exports της εταιρείας μελέτης περίπτωσης και οι
ρυθμίσεις τους (`data/pilot/`) δεν περιλαμβάνονται στο repository. Τα
`run_all_pilot.*`, `run_pilot_thesis.*` και `start_dashboard_pilot.bat` τρέχουν
μόνο όταν υπάρχουν exports και `dataset.env` στο `data/pilot/` (βλ. «Ρυθμίσεις
ανά dataset»).

**Φωτεινό / σκούρο θέμα:** μενού ⋮ πάνω δεξιά στο dashboard → System / Light /
Dark (η επιλογή αποθηκεύεται στον browser). Οι δύο παλέτες ορίζονται στο
`.streamlit/config.toml` (`[theme.light]`, `[theme.dark]`) και στο
`dashboard/theme.py`· τα γραφήματα και οι κάρτες αλλάζουν αμέσως.

## Δομή Project

```
replenishment-agent/
├── src/                    # Main package
│   ├── config.py           # Central configuration (.env)
│   ├── data_layer/         # SQLAlchemy models, ETL, anonymization, repository
│   ├── agent/              # BDI agent (beliefs / desires / intentions)
│   ├── mrp/                # MRP engine, lot sizing (LFL, FOQ, EOQ, POQ, WW), μοτίβα ζήτησης, επίπεδο εξυπηρέτησης ανά ABC
│   ├── rules/              # Business rules engine (7 rules, priority order) + policy config
│   ├── copilot/            # AI Copilot (local LLM via Ollama, read-only tools)
│   └── utils/              # KPIs, cost model, bootstrap, forecasting, calendar, logger
├── dashboard/              # Streamlit dashboard (6 tabs)
├── tests/                  # pytest test suite (328 tests)
├── scripts/                # Entry points (CLI)
├── abap/                   # SAP ABAP extractor program (ZMRP_AGENT_EXPORT)
├── config/                 # rules.json — πολιτική κανόνων της εταιρείας (+ changelog)
└── data/
    ├── raw/                # SAP exports (git-ignored)
    ├── pilot/              # SAP exports και dataset.env του pilot (δεν περιλαμβάνονται στο repository)
    ├── anonymized/         # Anonymized datasets (git-ignored)
    └── samples/            # Generated mock data (git-ignored, reproducible με seed 42)
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

## Πολιτική κανόνων ανά εταιρεία (`config/rules.json`)

Η **λογική** των 7 κανόνων είναι στο `src/rules/policies.py`· οι **παράμετροι**
της εταιρείας (όρια, buffers, on/off) είναι στο `config/rules.json` και
αλλάζουν χωρίς κώδικα. Οι προεπιλογές είναι οι τιμές της ΔΕ (Πίν. 4.4):

| Κανόνας | Παράμετροι | Προεπιλογή |
|---|---|---|
| R-DEAD-STOCK | `inactive_days` | 365 |
| R-EXPEDITE | `stock_vs_safety_pct` | 50 |
| R-SAFETY-BUFFER-A | `buffer_pct` | 20 |
| R-LONG-LEAD-BUFFER | `threshold_days`, `buffer_pct` | 30, 15 |
| R-MOQ-ENFORCE | `whole_units` | true |
| R-CALENDAR-SHIFT, R-COST-ESTIMATE | — (μόνο `enabled`) | true |

Τρεις τρόποι αλλαγής:

1. **Αρχείο**: επεξεργασία του `config/rules.json` (ή άλλο αρχείο με
   `python scripts/run_agent.py --rules-config path.json` / μεταβλητή `RULES_CONFIG`).
2. **Dashboard → πλευρική μπάρα → «Πολιτική κανόνων (what-if)»**: διακόπτες και
   αριθμητικά πεδία ανά κανόνα· «Εκτέλεση πράκτορα» τρέχει με τη what-if
   (μόνο για τη συνεδρία)· «Αποθήκευση ως πολιτική εταιρείας» γράφει το
   `rules.json` και καταγράφει ποιος/πότε/τι στο `config/rules_changelog.csv`.
3. **Νέος κανόνας**: μία συνάρτηση με `@rule("R-NAME", priority=N)` στο
   `policies.py` + μία εγγραφή στο `RULE_CATALOG` του `rules_config.py`
   (ελληνική περιγραφή: πότε / τι κάνει / γιατί) — εμφανίζεται αυτόματα στο
   dashboard, στο ablation και στο what-if.

Η καρτέλα «Ανάλυση υλικού» δείχνει τα **βήματα των κανόνων** για την πρόταση
του υλικού (π.χ. 51 → +20 % → 61,2 → +15 % → 70,4 → ακέραια → 71), με
επισήμανση αν τρέχει what-if. Οι τιμές που βλέπει ο planner στην πλευρική
μπάρα είναι πάντα οι τρέχουσες της πολιτικής.

## Πώς να χρησιμοποιήσετε με ΠΡΑΓΜΑΤΙΚΑ SAP δεδομένα

Έχετε δύο επιλογές για την εξαγωγή:

**Επιλογή Α — ABAP Z-Program (συνιστάται):**
1. Δείτε τον φάκελο `abap/` για το πρόγραμμα `ZMRP_AGENT_EXPORT` και οδηγίες εγκατάστασης
2. Τρέξτε το πρόγραμμα στο SAP — παράγει 7 CSV αρχεία με ένα κλικ
3. Αντιγράψτε τα στον φάκελο `data/raw/`
4. `python -m src.data_layer.anonymization`
5. Συνεχίστε από το βήμα 5 του Quick Start

(Για exports που βρίσκονται στο `data/pilot/`, αρκεί το
`run_all_pilot.bat` — δείτε τον πίνακα του Quick Start.)

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

Όταν η ημερομηνία είναι **πριν** από το στιγμιότυπο αποθέματος (π.χ.
αντίγραφο παραγωγής που εξάχθηκε μήνες αργότερα), το απόθεμα της ημερομηνίας
αναφοράς ανακατασκευάζεται από το στιγμιότυπο αφαιρώντας τις κινήσεις που
ακολούθησαν, και οι παραγγελίες που δημιουργήθηκαν αργότερα δεν μετρούν ως
ανοιχτές.

### Ρυθμίσεις ανά dataset (`data/pilot/dataset.env`)

Τα pilot scripts διαβάζουν τις ρυθμίσεις των πραγματικών δεδομένων από το
`data/pilot/dataset.env` (τα scripts των samples κρατούν τις προεπιλογές):

| Ρύθμιση | Προεπιλογή | Τι ορίζει |
|---|---|---|
| `AS_OF_DATE` | `auto` | Η «σημερινή» ημερομηνία του agent |
| `GR_MOVEMENT_TYPES` | `101` | Είδη κίνησης που είναι παραλαβές παραγγελιών (backtest) |
| `DEMAND_MOVEMENT_TYPES` | `601,251,261,201,281` | Είδη κίνησης που είναι ζήτηση |
| `STOCK_COLUMNS` | `LABST` | Είδη αποθέματος του MARD που αθροίζονται (π.χ. και `SPEME` όταν οι παραλαβές περνούν από δεσμευμένο απόθεμα) |
| `MATERIAL_SCOPE` | `all` | `active`: μόνο υλικά με κίνηση, απόθεμα ή ανοιχτή παραγγελία (μεγάλοι κατάλογοι) |
| `EXCLUDE_MATERIAL_GROUPS`, `EXCLUDE_MATERIALS` | κενά | Υλικά που μένουν έξω από το dataset (π.χ. υλικά άλλης δραστηριότητας με τον ίδιο τύπο υλικού): ομάδες υλικών (MARA-MATKL) και κωδικοί (MATNR), χωρισμένα με κόμμα |
| `DEMAND_POLICY` | `legacy` | `pattern`: πρόβλεψη, απόθεμα ασφαλείας και επίσπευση ανά μοτίβο ζήτησης (βλ. παρακάτω) |
| `SERVICE_LEVEL_BY_ABC` | κενό / `uniform` | Επίπεδο εξυπηρέτησης ανά κλάση ABC, π.χ. `A=0.98,B=0.95,C=0.90` (βλ. παρακάτω)· κενό ή `uniform` = 98 % για όλα |

### Πολιτική ανά μοτίβο ζήτησης (`DEMAND_POLICY=pattern`)

Η ζήτηση ανταλλακτικών είναι κυρίως διακοπτόμενη: στα δεδομένα της εταιρείας
μελέτης περίπτωσης (50.138 ενεργά υλικά, 52 εβδομάδες ως τις 06.02.2026) μόνο
710 υλικά πωλούνται τις περισσότερες εβδομάδες. Η προεπιλεγμένη πολιτική
(`legacy`) αντιμετωπίζει κάθε υλικό ως συνεχή ζήτηση (κινητός μέσος,
SS = z·σ·√LT, με μέσο και σ μόνο από την πρώτη ως την τελευταία πώληση): ένα
τεμάχιο τον χρόνο γίνεται «ένα τεμάχιο την ημέρα». Με `pattern`, για κάθε
υλικό και κάθε ημερομηνία αναφοράς t (`src/mrp/demand_pattern.py`):

1. **Παράθυρο ζήτησης:** οι 364 ημέρες t−363…t (είδη κίνησης ζήτησης), ως
   ημερήσιες ποσότητες και ως 52 εβδομάδες που λήγουν στο t· οι μέρες και οι
   εβδομάδες χωρίς ζήτηση μετρούν.
2. **Ταξινόμηση** (Syntetos, Boylan & Croston 2005) στις εβδομάδες:
   ADI = 52 / εβδομάδες με ζήτηση, CV² = (s / x̄)² των μη μηδενικών εβδομάδων.

| Μοτίβο | Κριτήριο | Πρόβλεψη | Απόθεμα ασφαλείας | Επίσπευση |
|---|---|---|---|---|
| Σταθερή (SMOOTH) | ADI < 1,32, CV² < 0,49 | κινητός μέσος | z·σ_d·√LT | όπως πριν |
| Ακανόνιστη (ERRATIC) | ADI < 1,32, CV² ≥ 0,49 | κινητός μέσος | z·σ_d·√LT | όπως πριν |
| Διακοπτόμενη (INTERMITTENT) | ADI ≥ 1,32, CV² < 0,49 | SBA | compound Poisson | αν P(ζήτηση στο LT) ≥ 50 % |
| Διακοπτόμενη-ακανόνιστη (LUMPY) | ADI ≥ 1,32, CV² ≥ 0,49 | SBA | compound Poisson | αν P(ζήτηση στο LT) ≥ 50 % |
| Σπάνια (RARE) | ζήτηση σε 1–2 εβδομάδες | — | 0 (κατά παραγγελία) | ποτέ |
| Χωρίς ζήτηση (NONE) | καμία εβδομάδα | — | 0 (κατά παραγγελία) | ποτέ |

- **σ_d**: τυπική απόκλιση των 364 ημερήσιων ποσοτήτων (με τις μηδενικές).
- **SBA** (Syntetos & Boylan 2005): Croston (1972) με α = 0,1 — ποσότητα z
  και διάστημα x εξομαλύνονται μόνο στις εβδομάδες με ζήτηση, πρόβλεψη
  (1 − α/2)·z/x ανά εβδομάδα, μοιρασμένη στις ημέρες.
- **Compound Poisson** (Feeney & Sherbrooke 1966): ο αριθμός εβδομάδων με
  ζήτηση μέσα στο lead time είναι Poisson με λ = p·LT/7 (p = εβδομάδες με
  ζήτηση / 52) και κάθε μία φέρνει μια ποσότητα από τις παρατηρημένες. Το
  σημείο αναπαραγγελίας s* είναι το μικρότερο s με P(LTD ≤ s) ≥ 98 % και
  SS = s* − λ·x̄. Ο κανονικός τύπος θα υπέθετε ζήτηση που τις περισσότερες
  μέρες δεν υπάρχει.
- **Κατά παραγγελία:** για σπάνια υλικά ο agent δεν κρατά απόθεμα· όταν
  ζητηθούν, αγοράζονται για τον πελάτη (η εταιρεία το κάνει ήδη στο 37 %
  των πωλήσεών τους: παραλαβή 1–4 ημέρες πριν την πώληση).
- Απόθεμα ασφαλείας του SAP (MARC-EISBE) υπερισχύει πάντα.
- Το enrichment υπολογίζει με το ίδιο παράθυρο τη μέση ζήτηση (άρα και την
  κλάση ABC) και γράφει τη στήλη `demand_pattern`· ο agent ξαναϋπολογίζει
  μοτίβο και απόθεμα ασφαλείας σε κάθε αναθεώρηση από το ιστορικό ως την
  ημερομηνία του (χωρίς look-ahead στο backtest). Το dashboard (ανάλυση
  υλικού) δείχνει μοτίβο, μέθοδο και απόθεμα ασφαλείας του agent.

**Αξιολόγηση.** Με `pattern` (ή `run_validation.py --by-pattern`, για να
μετρηθεί και η `legacy` με τον ίδιο τρόπο) το backtest ταξινομεί κάθε υλικό
από τις 52 εβδομάδες πριν το παράθυρο, ίδια για As-Is και To-Be:
- η ζήτηση σπάνιων υλικών που δεν καλύπτει το απόθεμα είναι **εκκρεμής
  παραγγελία πελάτη** (backorder), όχι χαμένη πώληση· στο To-Be ο agent
  αγοράζει την ποσότητα αμέσως και φτάνει στον πελάτη μετά το lead time·
- τα σπάνια υλικά δεν μετρούν στους δείκτες διαθεσιμότητας (cycle service
  level, stockout days και η «πίεση» του expedite premium): το μηδενικό
  απόθεμά τους είναι επιλογή, όχι έλλειψη·
- επιπλέον αναφορά ανά μοτίβο: `validation_report_pattern.csv`· το
  `run_forecast_eval.py` συγκρίνει και Croston / SBA / TSB (Teunter,
  Syntetos & Babai 2011) ανά μοτίβο (`forecast_report_summary.csv`).

Τα samples τρέχουν με `legacy` (τα αποτελέσματα του κειμένου δεν αλλάζουν)·
το pilot με `pattern` και επίπεδο εξυπηρέτησης ανά κλάση ABC
(`data/pilot/dataset.env`).

Βιβλιογραφία: Croston (1972) *ORQ* 23(3); Feeney & Sherbrooke (1966)
*Management Science* 12(5); Syntetos & Boylan (2005) *IJF* 21(2); Syntetos,
Boylan & Croston (2005) *JORS* 56(5); Boylan, Syntetos & Karakostas (2008)
*JORS* 59(4); Teunter, Syntetos & Babai (2011) *EJOR* 214(3).

### Επίπεδο εξυπηρέτησης ανά κλάση ABC (`SERVICE_LEVEL_BY_ABC`)

Με ένα επίπεδο για όλα τα υλικά (98 %), το απόθεμα ασφαλείας των πολλών
φθηνών υλικών βαραίνει στην απόφαση όσο και των λίγων που κάνουν την αξία
των πωλήσεων. Η συνήθης πρακτική είναι το ίδιο επίπεδο για όλα τα υλικά μιας
κλάσης ABC (Teunter, Babai & Syntetos 2010, *POMS* 19(3), 343–352, οι οποίοι
δείχνουν επίσης ότι σταθερά επίπεδα ανά κλάση πάνω στην αξία ζήτησης απέχουν
από το βέλτιστο κόστος). Η ρύθμιση υλοποιεί την πρακτική αυτή ώστε να
μετρηθεί (`src/mrp/service_level.py`):

- `SERVICE_LEVEL_BY_ABC=A=0.98,B=0.95,C=0.90`: ζεύγη ΚΛΑΣΗ=επίπεδο (κλάσμα
  ή ποσοστό)· κλάση που δεν αναφέρεται κρατά το 98 % (desire του agent).
  Κενό ή `uniform` (προεπιλογή, και καρφωμένο στα `run_all.*`) = 98 % για
  όλα — τα αποτελέσματα των samples δεν αλλάζουν.
- **Agent (`DEMAND_POLICY=pattern`):** το απόθεμα ασφαλείας κάθε αναθεώρησης
  υπολογίζεται για το επίπεδο της κλάσης. Η κλάση υπολογίζεται **ξανά σε κάθε
  αναθεώρηση** από τη ζήτηση των 52 εβδομάδων ως την ημερομηνία της (Pareto
  80/95 % στην αξία ζήτησης, ο κανόνας του enrichment): στην ημερομηνία
  αναφοράς ταυτίζεται με την κλάση του master data, ενώ στο backtest μια
  αναθεώρηση δεν χρησιμοποιεί κλάση που περιέχει τις πωλήσεις του ίδιου του
  παραθύρου (στο pilot 1.085 από τα 50.138 υλικά αλλάζουν κλάση μέσα στις 60
  ημέρες).
- **Enrichment (και οι δύο πολιτικές):** το απόθεμα ασφαλείας του
  `materials.csv` υπολογίζεται για το επίπεδο της κλάσης· η στήλη
  `ss_source` γράφει το επίπεδο (`SL=90%`). Με `legacy` ο agent παίρνει το
  απόθεμα ασφαλείας από εκεί.
- **Σύγκριση επιπέδων:** `scripts/run_service_level_grid.py` τρέχει το
  backtest του To-Be για 4 σύνολα επιπέδων (98 % για όλα, A 98 / B 95 / C 90,
  95 % και 90 % για όλα) απέναντι στο ίδιο As-Is → `service_level_grid.csv`
  (σύνολο, ανά κλάση ABC, ανά μοτίβο, και αξία αποθέματος ασφαλείας στο
  τέλος του παραθύρου). ~15 λεπτά ανά σύνολο στο pilot (`--jobs 2`: δύο
  παράλληλα· κάθε backtest του pilot χρειάζεται ~3,5 GB μνήμης, άρα
  `--jobs 2` θέλει ~7 GB ελεύθερα).

### Όλα τα αποτελέσματα του pilot για τη ΔΕ: `run_pilot_thesis.bat`

Μία εντολή (~4 ώρες σε 2 πυρήνες, ~8 GB μνήμης) ξαναβγάζει ό,τι αναφέρει
η ΔΕ για το pilot — χρήσιμο όταν έρθει νέα εξαγωγή:

| Βήμα | Αρχεία |
|---|---|
| Πολιτική του `dataset.env`: agent στην ημερομηνία αναφοράς (και με 98 % για όλα) | `reports/pilot/agent_summary.csv`, `agent_summary_uniform.csv` |
| Backtest 60 ημερών (σύνολο, ABC, μοτίβο) | `reports/pilot/validation_report*.csv` |
| Ακρίβεια προβλέψεων ανά μοτίβο | `reports/pilot/forecast_report*.csv` |
| Επίπεδα εξυπηρέτησης ανά ABC | `reports/pilot/service_level_grid.csv` |
| Το ίδιο backtest σε κάθε παράθυρο 60 ημερών του ιστορικού (`scripts/run_pilot_windows.py`) | `reports/pilot/pilot_windows.csv`, `pilot_windows_summary.csv` |
| Πολιτική `legacy` (της ΔΕ) στα ίδια δεδομένα, ίδια αξιολόγηση | `reports/pilot/legacy/…` (δική της βάση `replenishment_pilot_legacy.db`) |

## 📊 Backtest & Validation

Ο agent αξιολογείται μέσω συγκριτικού backtest As-Is vs To-Be πάνω στα
ιστορικά δεδομένα:

- **As-Is**: αναπαραγωγή των πραγματικών κινήσεων (κατανάλωση + παραλαβές 101)
- **To-Be**: ο agent αποφασίζει κάθε 8 ημέρες βλέποντας μόνο κινήσεις ≤ t
  (χωρίς look-ahead)· οι παραγγελίες του φτάνουν μετά το lead time·
  σε κάθε κύκλο εκδίδονται μόνο οι προτάσεις με ημερομηνία έκδοσης πριν τον
  επόμενο κύκλο (opening period), οι υπόλοιπες επανυπολογίζονται
- Και τα δύο σενάρια ξεκινούν από το **ίδιο** αρχικό απόθεμα (ανακατασκευή
  από το snapshot και τις κινήσεις) και από την **ίδια** pipeline παραγγελιών
  σε εξέλιξη (παραλαβές μέσα στο lead time από την έναρξη του παραθύρου)

Τρία cost scenarios υποστηρίζονται:

| Scenario | Holding rate | Description |
|---|---|---|
| `conservative` | 14% | Stable industry, cheap capital, low margins |
| `realistic` | ~20% | Typical European manufacturer (default) |
| `aggressive` | 28,5% | Tech / fashion / fast obsolescence |

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
διαφορετικό κανόνα (**leave-one-out**, Lipton & Steinhardt 2019). Η
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

**Methodology reference**: Tashman (2000)· Bergmeir, Hyndman & Koo (2018).

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

## 💬 AI Copilot (προαιρετικό)

Το dashboard περιλαμβάνει AI Copilot — chatbot που απαντά σε ερωτήσεις
στα Ελληνικά ή Αγγλικά για τις προτάσεις του agent. Χρησιμοποιεί **τοπικό
LLM** μέσω Ollama, οπότε **εταιρικά δεδομένα δεν φεύγουν από το laptop**.

```bash
ollama pull llama3.1:8b        # μία φορά (~4,7 GB)
streamlit run dashboard/app.py # το copilot tab το ανιχνεύει αυτόματα
```

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

Λεπτομέρειες στη ΔΕ, Κεφάλαια 3 και 4.

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
