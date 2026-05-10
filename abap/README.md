# ABAP Z-Program — SAP Data Extraction

Custom ABAP report που εξάγει όλα τα δεδομένα που χρειάζεται το
Replenishment Agent project σε CSV format.

## Τι κάνει

Το `ZMRP_AGENT_EXPORT.abap` παράγει 6 CSV αρχεία:

| Αρχείο | Πίνακας | Περιεχόμενο |
|---|---|---|
| `MARA_export.csv` | MARA | Material master (γενικά πεδία) |
| `MARC_export.csv` | MARC | Material per plant (MRP fields) |
| `MARD_export.csv` | MARD | Stock per storage location |
| `EKKO_export.csv` | EKKO | PO headers |
| `EKPO_export.csv` | EKPO + EKET | PO line items + delivery dates |
| `MB51_export.csv` | MSEG + MKPF | Material movements (12-24 μήνες) |

Όλα τα ονόματα στηλών είναι ευθυγραμμισμένα με αυτά που περιμένει το
`src/data_layer/anonymization.py`.

## Προαπαιτούμενα στο SAP

### 1. Authorization Objects (ζητήστε από SAP Basis)

Το πρόγραμμα χρειάζεται **read-only** access στους εξής πίνακες:

```
S_TABU_DIS:  ACTVT=03 (display), DICBERCLS=*
             για: MARA, MARC, MARD, EKKO, EKPO, MSEG, MKPF, EKET
S_DEVELOP:   ACTVT=01,02 (create/change) για το package που θα φιλοξενήσει το Z-program
S_TCODE:     SE38, SE80 (για development)
```

Αν δεν έχετε developer authorization, μπορεί κάποιος Basis να σας δώσει
έτοιμο ZMRP_AGENT_EXPORT μέσω transport.

### 2. Package & Transport

- Package: ZMRP (ή υπάρχον custom package της εταιρείας)
- Transport request: ένα νέο workbench transport
- Σε production deployment: code review από SAP CoE

## Deployment Steps

### Α. Στο Development System

1. **SE38** → νέο πρόγραμμα `ZMRP_AGENT_EXPORT` → type "Executable program"
2. Επικόλληση του κώδικα από `ZMRP_AGENT_EXPORT.abap`
3. **Text symbols** (Goto → Text Elements → Text Symbols):
   ```
   001 = Output Settings
   002 = Selection Filters
   003 = Tables to Export
   ```
4. **Activate** (`Ctrl+F3`)
5. Δοκιμή: **F8** (execute) με μικρό filter (π.χ. ένα plant)

### Β. Transport σε QA → Production

Standard SAP workflow:
- Development: code, test, save to TR
- QA: import TR, UAT
- Production: import TR μετά από approval

## Πώς να το τρέξετε

### Selection Screen

Όταν κάνετε execute (F8) θα δείτε 3 blocks:

**Block 1 — Output Settings:**
- `Path`: φάκελος εξόδου (π.χ. `C:\sap_exports\` για Windows ή `/tmp/sap_exports/` για Linux server)
- `Local download`: ✓ checked → αρχεία στον δικό σας PC | ☐ unchecked → στον application server

**Block 2 — Selection Filters:**
- `Plant (WERKS)`: ένα ή περισσότερα plants (π.χ. 1000)
- `Material type (MTART)`: ROH, HALB, FERT (συνήθως ROH+HALB+FERT)
- `MRP controller (DISPO)`: αν θέλετε συγκεκριμένο planner
- `Months of history`: default 24, για backtest αρκούν 12

**Block 3 — Tables to Export:**
- Επιλέξτε ποιους πίνακες θέλετε. Default: όλους.

### Παράδειγμα Run

```
Path:                C:\sap_exports\
Local download:      ☑

Plant:               1000
Material type:       ROH, HALB, FERT
Months of history:   24

[F8 Execute]
```

Output:
```
Replenishment Agent — Data Export
=====================================
Output folder: C:\sap_exports\
─────────────────────────────────────
Extracting MARA...
       1,247 records
  Saved: C:\sap_exports\MARA_export.csv
Extracting MARC...
         842 records
  Saved: C:\sap_exports\MARC_export.csv
Extracting MARD...
       1,156 records
  Saved: C:\sap_exports\MARD_export.csv
Extracting EKKO...
         324 records
  Saved: C:\sap_exports\EKKO_export.csv
Extracting EKPO...
         918 records
  Saved: C:\sap_exports\EKPO_export.csv
Extracting MB51 (MSEG+MKPF)...
  Cutoff date: 20240507
      45,237 records
  Saved: C:\sap_exports\MB51_export.csv
─────────────────────────────────────
Done. Copy files to data/raw/ in your project.
Then run: python -m src.data_layer.anonymization
```

## Background Execution (για μεγάλα datasets)

Αν το MB51 είναι >100k records, η dialog εκτέλεση μπορεί να κρασάρει με
runtime error (TIME_OUT). Λύση: τρέξτε στο background.

1. Αντί για F8, πατήστε **F9** (Execute in Background)
2. Variant: αποθηκεύστε τις παραμέτρους ως variant
3. Job: επιλέξτε output device (SAPLPD ή spool)
4. Start: Immediately ή scheduled
5. Παρακολούθηση: **SM37** (Job overview)

Το output αρχείο θα γραφτεί στον application server. Στη συνέχεια, το
κατεβάζετε με **AL11** (file browser) ή με transaction **CG3Y**.

## Επόμενα βήματα μετά την εξαγωγή

```bash
# 1. Αντιγραφή των 6 CSV στον φάκελο data/raw/ του project
cp ~/Downloads/*.csv replenishment-agent/data/raw/

# 2. Anonymization
cd replenishment-agent
python -m src.data_layer.anonymization

# 3. ETL — φόρτωση στη DB
python scripts/run_etl.py

# 4. Run agent
python scripts/run_agent.py

# 5. Validation backtest
python scripts/run_validation.py

# 6. Dashboard
streamlit run dashboard/app.py
```

## Performance Tips

- **MB51 είναι το βαρύ query**. Αν τρέχει >5 λεπτά, μειώστε το `p_months`
  ή προσθέστε plant filter.
- **Index hints**: σε ορισμένα systems μπορεί να βοηθήσει `%_HINTS ORACLE 'INDEX(...)'`
  μετά το WHERE. Συμβουλευτείτε τον SAP Basis.
- **Background mode** (F9 αντί F8) για production datasets με >1M records.

## Customization Points

Αν θέλετε να αλλάξετε τη συμπεριφορά:

| Τι θέλετε να αλλάξετε | Πού |
|---|---|
| Επιπλέον movement types | `FORM extract_mb51`, line με `s~bwart IN (...)` |
| Διαφορετικό purchase document type | `FORM extract_ekko`, `bstyp = 'F'` |
| Αλλαγή cutoff για EKKO POs | `FORM extract_ekko`, μεταβλητή `lv_cutoff` |
| Επιπλέον πεδία από MARA | Προσθήκη στο `ty_mara` και στο SELECT/WRITE |

## Troubleshooting

**Error "TIME_OUT"** στην dialog εκτέλεση:
→ Τρέξτε στο background (F9). Default dialog timeout είναι ~10 λεπτά.

**Error "DBSQL_DUPLICATE_KEY_ERROR"**:
→ Δεν θα συμβεί σε read-only πρόγραμμα. Αν το δείτε, καλέστε SAP Basis.

**File not found στο PC** (όταν p_local = X):
→ Βεβαιωθείτε ότι ο φάκελος `C:\sap_exports\` υπάρχει. Δημιουργήστε τον
   χειροκίνητα πριν τρέξετε το πρόγραμμα.

**Greek characters σε garbled encoding**:
→ Το πρόγραμμα γράφει UTF-8 (codepage 4110). Αν δείτε προβλήματα στο
   Excel, ανοίξτε με Notepad++ ή έντονη επιλογή UTF-8 στο Excel
   (Data → From Text → encoding 65001 UTF-8).

**"Authorization missing" σε runtime**:
→ Ζητήστε από Basis να ελέγξει τα authorization objects S_TABU_DIS και
   S_DEVELOP για τον user σας.

## AI Disclosure

Ο κώδικας ABAP δημιουργήθηκε με βοήθεια Generative AI (Claude) στο
πλαίσιο της διπλωματικής εργασίας. Η λογική και οι επιχειρησιακοί
κανόνες έχουν επικυρωθεί από τον συγγραφέα.

## License

Proprietary — for academic use only.
Επιβλέπων: Σωτήρης Γκαγιαλής (ΕΜΠ)
