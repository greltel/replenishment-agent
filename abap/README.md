# ABAP Z-Program — SAP Data Extraction

Custom ABAP report που εξάγει όλα τα δεδομένα που χρειάζεται το
Replenishment Agent project σε CSV format.

## Τι κάνει

Το `ZMRP_AGENT_EXPORT.abap` παράγει 7 CSV αρχεία:

| Αρχείο | Πίνακας | Περιεχόμενο |
|---|---|---|
| `MARA_export.csv` | MARA | Material master (γενικά πεδία) |
| `MARC_export.csv` | MARC + MBEW | Material per plant (MRP fields) + τιμή αποτίμησης (VPRSV, STPRS, VERPR, PEINH) |
| `MARD_export.csv` | MARD | Stock per storage location, όλα τα είδη αποθέματος (ελεύθερο, σε μεταφορά, ποιοτικός έλεγχος, περιορισμένο, δεσμευμένο, δεσμευμένες επιστροφές) |
| `EKKO_export.csv` | EKKO | PO headers της περιόδου ιστορικού |
| `EKPO_export.csv` | EKPO + EKKO + EKET | Όλες οι γραμμές PO αποθέματος της περιόδου (ανοιχτές και ολοκληρωμένες) + ημερομηνία PO, ημερομηνίες παράδοσης, παραληφθείσα ποσότητα |
| `MB51_export.csv` | MSEG + MKPF | Κινήσεις υλικών όλων των ειδών κίνησης (`SHKZG`, `SOBKZ`) |
| `T156T_export.csv` | T156T | Κείμενα των ειδών κίνησης (για τα δικά της είδη κίνησης της εταιρείας, π.χ. 9xx) |

Τα MARC, MARD, EKPO και MB51 περιορίζονται στα υλικά του `s_mtart` με join
στο MARA, μέσα στη βάση.

Όλα τα ονόματα στηλών είναι ευθυγραμμισμένα με αυτά που περιμένει το
`src/data_layer/anonymization.py`.

**Τιμές (v1.2):** η τιμή κάθε υλικού διαβάζεται από το MBEW, στην περιοχή
αποτίμησης του plant (`T001W-BWKEY`), εγγραφή χωρίς valuation type
(`BWTAR` κενό). Το Python χρησιμοποιεί `STPRS` όταν `VPRSV = S` και `VERPR`
όταν `VPRSV = V`, ανά `PEINH` μονάδες. Υλικά χωρίς εγγραφή MBEW παίρνουν
εκτιμώμενο κόστος (`src/utils/cost_estimator.py`). Οι εκδόσεις πριν τη v1.2
άφηναν τα `STPRS`/`PEINH` κενά — αν το πρόγραμμα είναι ήδη εγκατεστημένο,
χρειάζεται νέο transport με την τρέχουσα έκδοση πριν από την εξαγωγή.

**Αλλαγές v1.8:**
- **MARD:** νέες στήλες `UMLME` (σε μεταφορά), `SPEME` (δεσμευμένο) και
  `RETME` (δεσμευμένες επιστροφές), μετά το `ERSDA`. Οι κινήσεις του MB51
  περιλαμβάνουν και τις καταχωρίσεις σε αυτά τα αποθέματα· μια εταιρεία που
  παραλαμβάνει σε δεσμευμένο απόθεμα έχει στην αποθήκη εμπορεύματα που το
  `LABST` μόνο του δεν δείχνει. Το Python τα αθροίζει όταν οριστεί
  `STOCK_COLUMNS` (βλ. `data/pilot/dataset.env`).
- **T156T:** νέο αρχείο με τα κείμενα των ειδών κίνησης (γλώσσα `p_lang`,
  αλλιώς αγγλικά). Το Python τα γράφει στο log δίπλα σε κάθε είδος κίνησης.
  Checkbox «T156T», default επιλεγμένο.

**Αλλαγές v1.3:**
- **MB51:** όλα τα είδη κίνησης (νέο πεδίο `s_bwart`, κενό = όλα). Η σταθερή
  λίστα των προηγούμενων εκδόσεων έχανε τις παραλαβές εταιρειών που δεν
  τις καταχωρούν με 101. Νέες στήλες `SHKZG` (χρέωση/πίστωση) και `SOBKZ`
  (ειδικό απόθεμα). Το `MENGE` μένει προσημασμένο όπως πριν.
- **EKKO/EKPO:** περίοδος = `p_months` (το EKKO ήταν σταθερά 12 μήνες). Το
  EKPO εξάγει όλες τις γραμμές της περιόδου, όχι μόνο τις ανοιχτές, με νέες
  στήλες `BEDAT` (ημερομηνία PO), `WEMNG` (ποσότητα που έχει παραληφθεί,
  άθροισμα των schedule lines) και `EINDT_OPEN` (ημερομηνία της πρώτης
  schedule line που δεν έχει παραληφθεί πλήρως — για τμηματικές παραδόσεις).
  Από αυτά το Python βγάζει την ανοιχτή ποσότητα (`MENGE − WEMNG`), πότε
  αναμένεται, και τον προγραμματισμένο χρόνο παράδοσης (`EINDT − BEDAT`,
  με `EINDT` την πρώτη schedule line). Εξάγονται μόνο γραμμές που
  αναπληρώνουν δικό μας απόθεμα: χωρίς λογαριασμό (`KNTTP`), όχι επιστροφές
  (`RETPO`), όχι consignment (`PSTYP` 2).
- **Απόδοση:** τα MARC/MARD φιλτράρονται με join στη βάση αντί για αναζήτηση
  γραμμή-γραμμή (που με πολλά υλικά μπορούσε να καταλήξει σε TIME_OUT).
- **Application server:** με ξετσεκαρισμένο το «Local download» τα αρχεία
  γράφονται στον server (`OPEN DATASET`), ώστε το πρόγραμμα να τρέχει και ως
  background job. Το `p_path` κρατά πλέον τα πεζά γράμματα· για τον server
  πρέπει να είναι απόλυτη διαδρομή χωρίς `..`. Σε background, αν κάποιο
  αρχείο δεν γραφτεί, το job τελειώνει ως *cancelled* με το μήνυμα στο job log.
- `p_months` από 1 έως 99.
- Οι νέες στήλες μπαίνουν πάντα στο τέλος· τα αρχεία παλαιότερων εκδόσεων
  διαβάζονται όπως πριν.

## Προαπαιτούμενα στο SAP

### 1. Authorization Objects (ζητήστε από SAP Basis)

Το πρόγραμμα χρειάζεται **read-only** access στους εξής πίνακες:

```
S_TABU_DIS:  ACTVT=03 (display), DICBERCLS=*
             για: MARA, MAKT, MARC, MBEW, T001W, MARD, EKKO, EKPO, MSEG, MKPF, EKET, T156T
S_DATASET:   ACTVT=34 (write) για τη διαδρομή στον application server
             — μόνο αν τα αρχεία γράφονται στον server (background job)
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
2. Επικόλληση του κώδικα από `ZMRP_AGENT_EXPORT.abap`. Δεν χρειάζονται
   text elements ούτε selection texts: όλες οι ετικέτες του selection
   screen ορίζονται μέσα στον κώδικα (`INITIALIZATION`). Ο κώδικας είναι
   ASCII και τρέχει από ABAP 7.40 και μετά (ECC 6.0 EHP7+, S/4HANA).
3. **Activate** (`Ctrl+F3`)
4. Δοκιμή: **F8** (execute) με μικρό filter (π.χ. ένα plant). Η γραμμή
   κατάστασης δείχνει την πρόοδο ανά πίνακα (π.χ. `3/6 Reading MARD`, και
   ανά μήνα για το MB51 με το `MB51 month by month`). Η λίστα γράφει πόσα δευτερόλεπτα πήρε κάθε
   ανάγνωση και κάθε αρχείο (π.χ. `MB51 read in 42.3 s`).

### Β. Transport σε QA → Production

Standard SAP workflow:
- Development: code, test, save to TR
- QA: import TR, UAT
- Production: import TR μετά από approval

## Πώς να το τρέξετε

### Selection Screen

Όταν κάνετε execute (F8) θα δείτε 3 blocks:

**Block 1 — Output Settings:**
- `Output folder`: φάκελος εξόδου (π.χ. `C:\sap_exports\` για Windows ή
  `/tmp/sap_exports/` για Linux server). Με **F4** ανοίγει ο φάκελος
  επιλογής του PC· για τον application server γράψτε τη διαδρομή.
- `Download to the PC`: ✓ checked → αρχεία στον δικό σας PC | ☐ unchecked → στον application server

**Block 2 — Selection Filters:**
- `Plant (WERKS)`: ένα ή περισσότερα plants (π.χ. 1000)
- `Material type (MTART)`: το είδος υλικού των ανταλλακτικών που μελετάμε
  (ισχύει για όλους τους πίνακες)
- `MRP controller (DISPO)`: αν θέλετε συγκεκριμένο planner
- `Movement type (BWART)`: κενό = όλα τα είδη κίνησης (συνιστάται)
- `Months of history`: default 24 — ισχύει για MB51, EKKO και EKPO

**Block 3 — Tables to Export:**
- Επιλέξτε ποιους πίνακες θέλετε. Default: όλους.
- `MB51 month by month`: default ☐. Τσεκαρισμένο, το MB51 διαβάζεται ένα
  query ανά ημερολογιακό μήνα με πρόοδο ανά μήνα (ίδιες γραμμές). Βοηθά
  κόντρα στο TIME_OUT σε dialog, αλλά είναι γρηγορότερο μόνο αν η βάση
  διαβάζει το MKPF με την ημερομηνία καταχώρισης· συγκρίνετε το
  `MB51 read in … s` των δύο τρόπων (ή ST05) πριν το κρατήσετε.
- `T156T - movement type texts`: default ☑ (μικρό αρχείο, δευτερόλεπτα).

### Παράδειγμα Run

```
Path:                C:\sap_exports\
Local download:      ☑

Plant:               1000
Material type:       (το MTART των ανταλλακτικών)
Movement type:       (κενό = όλα)
Months of history:   24

[F8 Execute]
```

Output:
```
Replenishment Agent — Data Export
=====================================
Output folder (local PC): C:\sap_exports\
History from: 20241105
─────────────────────────────────────
Extracting MARA...
       1,247 records
  Saved: C:\sap_exports\MARA_export.csv
Extracting MARC...
  Prices from MBEW:        839 of        842 materials
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
  Cutoff date: 20241105
      45,237 records
  Saved: C:\sap_exports\MB51_export.csv
Extracting T156T...
         612 records
  Saved: C:\sap_exports\T156T_export.csv
─────────────────────────────────────
Done. Copy the files to data/pilot/ in the project
and run run_all_pilot.bat.
```

## Background Execution (για μεγάλα datasets)

Αν το MB51 είναι >100k records, η dialog εκτέλεση μπορεί να κρασάρει με
runtime error (TIME_OUT). Λύση: τρέξτε στο background.

1. Στο selection screen: **ξετσεκάρετε** το `Local download` και δώστε
   φάκελο του application server στο `Path` (π.χ. `/tmp/sap_exports/`).
   Με τσεκαρισμένο το `Local download` το background job σταματά με μήνυμα.
2. Αντί για F8, πατήστε **F9** (Execute in Background) — ή αποθηκεύστε τις
   παραμέτρους ως variant και ορίστε job στο SM36
3. Start: Immediately ή scheduled
4. Παρακολούθηση: **SM37** (Job overview) — το spool δείχνει τα records
   ανά πίνακα και τυχόν μηνύματα σφάλματος

Το output αρχείο θα γραφτεί στον application server. Στη συνέχεια, το
κατεβάζετε με **AL11** (file browser) ή με transaction **CG3Y**.

## Επόμενα βήματα μετά την εξαγωγή

1. Αντικαταστήστε τα CSV του φακέλου `data/pilot/` με τα νέα (ίδια ονόματα)
   και ενημερώστε το `data/pilot/dataset.env` (ημερομηνία αναφοράς, είδη
   κίνησης παραλαβής και ζήτησης, είδη αποθέματος, εύρος υλικών).
   Οι κινήσεις σε GR blocked stock (103/104/107/108/124/125) δεν αλλάζουν
   το απόθεμα της αποθήκης και αγνοούνται (αλλιώς μια παραλαβή 103 → 105
   θα μετρούσε διπλά). Οι γραμμές ειδικού αποθέματος (`SOBKZ`) κρατιούνται.
2. `run_all_pilot.bat` — ανωνυμοποίηση, ETL, agent και backtest
   (`--full` για όλες τις αξιολογήσεις).
3. `start_dashboard_pilot.bat` — dashboard στο http://localhost:8502

**Παραλαβές στο backtest:** η ανωνυμοποίηση γράφει στο log τα είδη κίνησης
που υπάρχουν (`Movement types (lines, net qty): …`, με το κείμενο του T156T).
Αν η εταιρεία δεν παραλαμβάνει με 101 (π.χ. 103 → 105 ή δικό της είδος
κίνησης), ορίστε τα είδη παραλαβής στο `data/pilot/dataset.env`, π.χ.
`GR_MOVEMENT_TYPES=101,105`, ώστε το As-Is να τις μετρά ως παραγγελίες και
το To-Be να κληρονομεί τις παραγγελίες σε μεταφορά. Το ίδιο για τη ζήτηση
(`DEMAND_MOVEMENT_TYPES`). Οι ρυθμίσεις αφορούν μόνο τα pilot δεδομένα· το
`run_all.bat` (samples) κρατά τις προεπιλογές.

## Performance Tips

- **MB51 είναι το βαρύ query**. Αν τρέχει >5 λεπτά, μειώστε το `p_months`
  ή προσθέστε plant filter. Δοκιμάστε και το `MB51 month by month`
  (βλ. Block 3) και κρατήστε τον τρόπο με τα λιγότερα δευτερόλεπτα.
- **Index hints**: σε ορισμένα systems μπορεί να βοηθήσει `%_HINTS ORACLE 'INDEX(...)'`
  μετά το WHERE. Συμβουλευτείτε τον SAP Basis.
- **Background mode** (F9 αντί F8) για production datasets με >1M records.

## Customization Points

Αν θέλετε να αλλάξετε τη συμπεριφορά:

| Τι θέλετε να αλλάξετε | Πού |
|---|---|
| Περιορισμός σε συγκεκριμένα movement types | Selection screen, `s_bwart` |
| Διαφορετικό purchase document type | `FORM extract_ekko` και `FORM extract_ekpo`, `bstyp = 'F'` |
| Περίοδος ιστορικού (MB51, EKKO, EKPO) | Selection screen, `p_months` |
| Επιπλέον πεδία από MARA | Προσθήκη στο `ty_mara` και στο SELECT/WRITE |

## Troubleshooting

**Error "TIME_OUT"** στην dialog εκτέλεση:
→ Τρέξτε στο background (F9) με ξετσεκαρισμένο το `Local download`.
   Default dialog timeout είναι ~10 λεπτά.

**"Background job: uncheck Local download, give a server path"**:
→ Ένα background job δεν έχει SAP GUI για να κατεβάσει αρχεία στο PC.
   Ξετσεκάρετε το `Local download` και δώστε φάκελο του server.

**"Server path must be absolute"** / **"The path must not contain '..'"**:
→ Δώστε πλήρη διαδρομή του server, π.χ. `/tmp/sap_exports/` (ή
   `D:\sap_exports\` σε Windows server).

**"Could not open … on the application server"**:
→ Ο φάκελος δεν υπάρχει στον server ή λείπει το `S_DATASET`.

**ATC / Code Inspector:** το `OPEN DATASET` με διαδρομή από το selection
screen μπορεί να εμφανιστεί ως security finding. Ο έλεγχος για απόλυτη
διαδρομή χωρίς `..` το περιορίζει· αν η εταιρεία απαιτεί logical file path
(`FILE_VALIDATE_NAME`), χρειάζεται μια εγγραφή στο transaction FILE.

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
