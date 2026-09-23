# Περιορισμοί & Μελλοντική Εργασία

> Σύμφωνα με τις προδιαγραφές του Αναλυτικού Οδηγού Athens MBA (§5.9), η ΔΕ
> πρέπει να αναφέρει περιορισμούς (limitations) και προτάσεις για μελλοντική
> εργασία. Αυτό το έγγραφο τεκμηριώνει και τα δύο σημεία και χρησιμεύει ως
> πηγή για το Κεφάλαιο 5 της κύριας εργασίας.

---

## 1. Περιορισμοί της Παρούσας ΔΕ

Παρότι η εργασία πέτυχε τους στόχους της, η ορθή ερευνητική πρακτική
απαιτεί τη ρητή αναγνώριση των περιορισμών. Αυτοί ταξινομούνται σε
τέσσερις κατηγορίες: μεθοδολογικοί, δεδομένων, υλοποίησης, και
γενίκευσης αποτελεσμάτων.

### 1.1 Μεθοδολογικοί Περιορισμοί

**1.1.1 Single Case Study Design**

Η εργασία ακολουθεί τη μεθοδολογία της μελέτης περίπτωσης (Κατηγορία Β.2
του Οδηγού). Αυτό σημαίνει ότι τα ευρήματα προέρχονται από **μία**
επιχείρηση και ένα συγκεκριμένο επιχειρησιακό περιβάλλον.

*Επίδραση*: Ο βαθμός γενίκευσης σε άλλους κλάδους (π.χ. τρόφιμα, φαρμακευτικά,
λιανικό εμπόριο) απαιτεί επιπλέον επικύρωση.

*Μετριασμός*: Η αρχιτεκτονική σχεδιάστηκε domain-agnostic. Τα core components
(BDI agent, MRP engine, rules) δεν περιέχουν industry-specific λογική.

**1.1.2 Backtest με Counterfactual Simulation**

Το As-Is vs To-Be backtest βασίζεται σε προσομοίωση του τι "θα είχε γίνει"
αν ο agent αποφάσιζε αντί για ανθρώπινους planners. Αυτό προϋποθέτει
ότι:
- Η ζήτηση θα παρέμενε ίδια ανεξάρτητα από τις αποφάσεις του agent
- Οι suppliers θα ανταποκρίνονταν με το ίδιο lead time
- Δεν θα υπήρχαν δευτερογενείς επιπτώσεις (π.χ. αλλαγή σχέσεων με
  προμηθευτές)

*Επίδραση*: Τα τελικά οφέλη ενδέχεται να υπερεκτιμώνται ή υποεκτιμώνται
σε live production.

*Μετριασμός*: Sensitivity analysis ±20% σε key παραμέτρους (lead time,
demand, holding rate) δείχνει robustness του core finding.

**1.1.3 Bootstrap Validation με Περιορισμένα Παράθυρα**

Το bootstrap analysis (30-100 samples) προσφέρει στατιστική σημαντικότητα,
αλλά τα παράθυρα προέρχονται από μια **περίοδο 365 ημερών**. Δεν καλύπτονται:
- Πολυετείς τάσεις (year-over-year seasonality)
- Σπάνια γεγονότα (supply chain disruptions, COVID-style shocks)
- Νέοι κωδικοί υλικών εκτός του dataset

*Μετριασμός*: Walk-forward validation αντί random k-fold για διατήρηση
της χρονικής ακολουθίας (Bergmeir & Benítez 2012).

### 1.2 Περιορισμοί Δεδομένων

**1.2.1 Synthetic Data στις Δημόσιες Επαναλήψεις**

Το repository (GitHub) και τα tests χρησιμοποιούν synthetic data για
λόγους privacy. Τα πραγματικά εταιρικά δεδομένα παρέμειναν τοπικά για
λόγους εμπιστευτικότητας.

*Επίδραση*: Όποιος αναπαράγει το project από το GitHub θα δει KPIs που
δεν αντιστοιχούν 1:1 στα reported αποτελέσματα της ΔΕ.

*Μετριασμός*: Πλήρης τεκμηρίωση του synthetic data generator (ώστε να
γνωρίζει κανείς ότι τα reported numbers στη ΔΕ αναφέρονται στα πραγματικά
data).

**1.2.2 Missing Master Data στο SAP**

Το πραγματικό SAP environment είχε κενά κρίσιμα MRP fields (~30% των
materials με EISBE=0 ή PLIFZ=0). Αντιμετωπίστηκε με smart defaults
(Silver-Pyke-Peterson formulas).

*Επίδραση*: Τα derived values είναι statistical εκτιμήσεις, όχι "ground
truth". Σε A-class items που έχουν master data, ο agent είναι ακριβέστερος.

*Μετριασμός*: Το script `master_data_enrichment.py` καταγράφει ποιες
τιμές είναι imputed vs original, ώστε ο χρήστης να γνωρίζει το confidence
επιπέδων.

**1.2.3 Demand History Length**

Για πολλά υλικά (ιδίως νέα ή slow-moving), διαθέσιμα ιστορικά κατανάλωσης
ήταν λιγότερα από 90 ημέρες. Τα statistical forecasts σε αυτές τις
περιπτώσεις είναι αναξιόπιστα.

*Επίδραση*: εβδομαδιαίο WMAPE ~55–70% (διάμεσος/μέσος) σε διακοπτόμενη ζήτηση ανταλλακτικών· η αυτόματη επιλογή μεθόδου ανά υλικό (auto) δεν βελτιώνει το backtest (§4.9 ΔΕ).

*Μετριασμός*: Το dashboard και το run_forecast_eval.py δείχνουν honestly το WMAPE
("Χαμηλή ακρίβεια — εξετάστε διαφορετική μέθοδο"). Δεν κρύβεται.

### 1.3 Περιορισμοί Υλοποίησης

**1.3.1 Offline Integration (ETL-based)**

Ο agent δουλεύει σε offline mode μέσω CSV exports από το SAP. Δεν υπάρχει
real-time σύνδεση (BAPI/RFC).

*Επίδραση*: Decision lag = frequency του ETL run (συνήθως daily).

*Λόγος επιλογής*: Production safety (καμία modification στο SAP), security
(audit-friendly), και reproducibility.

*Μετριασμός*: Η αρχιτεκτονική επιτρέπει μελλοντική αναβάθμιση σε
event-driven model (κεφάλαιο 2.2 αυτού του document).

**1.3.2 Single-Plant Scope**

Η τρέχουσα υλοποίηση χειρίζεται **ένα plant**. Multi-plant scenarios
(inter-plant transfers, distributed inventory) δεν καλύπτονται.

*Επίδραση*: Δεν εφαρμόζεται σε εταιρείες με πολλές αποθήκες ή multi-echelon
δίκτυα.

*Μετριασμός*: Το data model (SQLAlchemy) ήδη περιλαμβάνει `plant_id`
column. Η επέκταση απαιτεί business logic, όχι data restructuring.

**1.3.3 Static Cost Parameters**

Τα τρία cost scenarios (conservative/realistic/aggressive) χρησιμοποιούν
**static** holding rates και stockout costs. Δεν διαφοροποιούνται:
- Ανά κατηγορία υλικού (έτσι π.χ. FERT vs ROH)
- Ανά εποχή
- Ανά supplier criticality

*Επίδραση*: Πιο πραγματικά cost modeling θα απαιτούσε per-SKU παραμέτρους.

*Μετριασμός*: Η decomposition σε 5 components δίνει ευελιξία για
μελλοντικό customization.

**1.3.4 LLM Latency για AI Copilot**

Το llama3.1:8b τρέχει σε CPU με latency 2-15 δευτερόλεπτα ανά query.
Όχι αρκετά γρήγορο για high-volume production use.

*Μετριασμός*: Το Copilot σχεδιάστηκε ως **decision support tool** για
planners, όχι real-time API. Το latency είναι αποδεκτό για ad-hoc queries.

### 1.4 Περιορισμοί Γενίκευσης

**1.4.1 Παραδοχές για το Demand Pattern**

Τα forecasting methods (simple_average, moving_average, exponential_smoothing)
υποθέτουν **stationary** ή **slowly-changing** demand. Δεν χειρίζονται:
- Promotion-driven spikes
- New product introductions
- Discontinued items
- Hard seasonal patterns (π.χ. ηλεκτρικά είδη Χριστουγέννων)

**1.4.2 Δεν Καλύπτονται Strategic Decisions**

Ο agent χειρίζεται **operational replenishment** (πότε & πόσο). ΔΕΝ:
- Συναλλάσσεται με προμηθευτές
- Αξιολογεί supplier alternatives
- Αποφασίζει για make-vs-buy
- Σχεδιάζει production schedules

**1.4.3 Δεν Λαμβάνει Υπόψη Capacity Constraints**

Το MRP engine είναι "infinite capacity". Δεν ελέγχει αν η αποθήκη χωράει
την προτεινόμενη παραγγελία ή αν ο supplier έχει διαθεσιμότητα.

*Μετριασμός*: Αυτά συνήθως ελέγχονται downstream (από human planner) πριν
τη μετατροπή Proposal → PO.

---

## 2. Προτάσεις για Μελλοντική Εργασία

Οι ακόλουθες κατευθύνσεις θα μπορούσαν να επεκτείνουν την παρούσα εργασία.
Κατατάσσονται σε τρεις βαθμίδες ωριμότητας: άμεσες (short-term),
ενδιάμεσες (mid-term), και μακροπρόθεσμες (long-term).

### 2.1 Άμεσες Επεκτάσεις (Short-Term)

**2.1.1 Multi-Echelon Inventory**

Επέκταση σε multi-warehouse settings:
- Inter-warehouse transfers αντί για external POs όπου συμφέρει
- Risk pooling effects (Eppen 1979)
- Centralized vs decentralized strategies

*Διάρκεια*: 2-3 μήνες
*Δυσκολία*: Μέτρια — απαιτεί επέκταση data model και νέα rules

**2.1.2 Promotion-Aware Forecasting**

Ενσωμάτωση promotion calendar:
- Boost demand forecasts κατά promo periods
- Self-cannibalization between similar products
- ML uplift modeling

*Διάρκεια*: 2-3 μήνες
*Δυσκολία*: Μέτρια προς υψηλή

**2.1.3 Supplier Performance Rules**

Νέα rules που λαμβάνουν υπόψη supplier history:
- R-SUPPLIER-RELIABILITY: αν supplier έχει lead time variance >30%, buffer
- R-SUPPLIER-CAPACITY: αν η ποσότητα υπερβαίνει historical max του supplier, split

*Διάρκεια*: 1 μήνας
*Δυσκολία*: Χαμηλή

**2.1.4 Real-Time SAP Integration via BAPI**

Αντικατάσταση CSV-based ETL με real-time BAPI calls:
- BAPI_MATERIAL_GETLIST για master data
- BAPI_GOODSMVT_GETITEMS για live stock
- Webhook-based triggers όταν stock < safety

*Διάρκεια*: 1-2 μήνες
*Δυσκολία*: Μέτρια (κυρίως SAP-side configuration)
*Σημείωση*: Απαιτεί έγκριση SAP admin και testing σε QA environment

### 2.2 Ενδιάμεσες Επεκτάσεις (Mid-Term)

**2.2.1 ML-Based Demand Forecasting**

Παράλληλη υποστήριξη ML methods:
- Prophet (Facebook/Meta) για seasonality
- LightGBM/XGBoost για multivariate
- LSTM για deep time-series
- **Auto-selection μεταξύ statistical και ML** με βάση το CV και history length

*Διάρκεια*: 3-4 μήνες
*Δυσκολία*: Υψηλή
*Risk*: Overfitting σε small datasets — απαιτεί προσεκτική evaluation

**2.2.2 Stochastic MRP**

Από deterministic σε stochastic formulation:
- Demand ως random variable (όχι point estimate)
- Service-level chance constraints
- Robust optimization (Bertsimas & Sim 2004)

*Διάρκεια*: 4-6 μήνες
*Δυσκολία*: Υψηλή (απαιτεί OR background)

**2.2.3 Multi-Agent Coordination**

Επέκταση σε multi-agent system:
- Ένας agent per plant
- Coordination via contract net protocol (Smith 1980)
- Auction-based inter-plant transfers

*Διάρκεια*: 6-9 μήνες
*Δυσκολία*: Υψηλή

**2.2.4 Sustainability Metrics**

Επιπλέον KPI dimension:
- Carbon footprint per order (transport emissions)
- Πολιτικές που λαμβάνουν υπόψη green criteria
- Multi-objective optimization (cost vs CO2)

*Διάρκεια*: 3-4 μήνες
*Δυσκολία*: Μέτρια
*Trend value*: Υψηλή (alignment με ESG reporting)

### 2.3 Μακροπρόθεσμες Επεκτάσεις (Long-Term)

**2.3.1 Reinforcement Learning Layer**

Αντικατάσταση hand-crafted rules με RL policy:
- Reward = TCO savings + service level
- State = (stock, history, open POs, ABC class, ...)
- Action = (order qty, order date)

*Διάρκεια*: 12+ μήνες
*Δυσκολία*: Πολύ υψηλή
*Risk*: Sample inefficiency, sim-to-real gap, explainability loss

**2.3.2 Federated Learning Across Companies**

Cross-company knowledge sharing **χωρίς** data sharing:
- Federated training of forecasting models
- Συμμετοχή πολλών εταιρειών στον ίδιο κλάδο
- Privacy-preserving aggregation

*Διάρκεια*: 18+ μήνες (πιθανώς PhD-level)
*Δυσκολία*: Πολύ υψηλή

**2.3.3 Integration με Procurement Marketplaces**

Σύνδεση του agent με B2B marketplaces:
- Auto-RFQ generation
- Multi-supplier price comparison
- Smart contract automation με blockchain

*Διάρκεια*: 12+ μήνες
*Δυσκολία*: Υψηλή
*Dependency*: Maturity της εκάστοτε marketplace platform

**2.3.4 Cognitive Procurement Assistant**

Επέκταση του AI Copilot σε proactive mode:
- Anomaly detection ("το lead time αυξήθηκε ασυνήθιστα")
- Recommendation engine για strategic decisions
- Πολυγλωσσική υποστήριξη (Ελληνικά + Αγγλικά + Γερμανικά)

*Διάρκεια*: 6-12 μήνες
*Δυσκολία*: Μέτρια προς υψηλή

---

## 3. Σύνοψη — Επόμενα Βήματα Πρακτικής Εφαρμογής

Από επιχειρησιακή σκοπιά (όχι μόνο ακαδημαϊκή), τα πιο **value-adding** επόμενα
βήματα είναι:

| Priority | Επέκταση | ROI Estimate | Effort |
|---|---|---|---|
| 1 | Real-time SAP integration (BAPI) | Υψηλό — εξαλείφει daily ETL lag | 1-2 μήνες |
| 2 | Supplier reliability rules | Υψηλό — μειώνει stockouts από κακούς προμηθευτές | 1 μήνας |
| 3 | Multi-plant support | Μέτριο — εάν η εταιρεία έχει >1 plant | 2-3 μήνες |
| 4 | Promotion-aware forecasting | Μέτριο — εάν τα promotions είναι σημαντικά | 2-3 μήνες |
| 5 | Sustainability metrics | Μέτριο — απαιτείται για ESG reporting | 3-4 μήνες |

---

## 4. Επιστημονική Συνεισφορά της ΔΕ

Παρά τους περιορισμούς, η εργασία προσφέρει συγκεκριμένες συνεισφορές στο
πεδίο:

1. **Πρακτική εφαρμογή BDI σε supply chain** — Λίγες υπάρχουσες δουλειές
   εφαρμόζουν BDI στο replenishment context. Η εργασία γεφυρώνει theory
   και πράξη.

2. **Validation methodology** — Η σύνδεση bootstrap CI + ablation study +
   sensitivity analysis είναι **standard στη ML research αλλά σπάνια στο
   operations management**. Η ΔΕ μεταφέρει αυτές τις πρακτικές.

3. **Production-safe AI integration** — Το offline ETL pattern με local LLM
   (Ollama) δείχνει πώς οι ελληνικές επιχειρήσεις μπορούν να υιοθετήσουν AI
   χωρίς GDPR concerns ή cloud costs.

4. **Open-source contribution** — Ο κώδικας θα διατεθεί public (μετά
   παράδοση) ως template για άλλους ερευνητές που εργάζονται με SAP +
   intelligent agents.

---

## 5. Συμπερασματικά

Καμία ερευνητική εργασία δεν είναι "complete" — οι περιορισμοί αναγνωρίζονται
ως ευκαιρίες για μελλοντική έρευνα. Η παρούσα ΔΕ απαντά σε ένα συγκεκριμένο
ερευνητικό ερώτημα (πώς ένας ευφυής πράκτορας μπορεί να αυτοματοποιήσει το
replenishment σε SAP-based environments) και ορίζει σαφή roadmap για
επεκτάσεις. Η μεθοδολογική αυστηρότητα — bootstrap validation,
ablation studies, sensitivity analysis — διασφαλίζει ότι τα συμπεράσματα
είναι defensible.

---

*Παρόν document: Πηγή για το Κεφάλαιο 5 (Συμπεράσματα) και Κεφάλαιο 6
(Μελλοντική Εργασία) της Διπλωματικής Εργασίας*

*Reference: Αναλυτικός Οδηγός Athens MBA 2026, §5.9*
