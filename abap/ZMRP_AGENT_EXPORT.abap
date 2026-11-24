*&---------------------------------------------------------------------*
*& Report  ZMRP_AGENT_EXPORT
*&---------------------------------------------------------------------*
*& Title       : Data extraction for Replenishment Agent (Athens MBA)
*& Description : Extracts MARA, MARC, MARD, EKKO, EKPO, MB51 (and the
*&               movement type texts T156T) to flat files (CSV format)
*&               ready for the Python ETL pipeline.
*&
*& Author      : George Drakos
*& Created     : 2026
*& Thesis      : Athens MBA - Intelligent Agent for Inventory
*&               Replenishment with SAP Integration
*& Supervisor  : Sotiris Gkagialis
*&
*& AUTHORIZATION: Read-only on tables MARA, MAKT, MARC, MBEW, T001W,
*&                MARD, EKKO, EKPO, EKET, MSEG, MKPF, T156T. No data
*&                modification.
*&                Writing to the application server (Local download
*&                unchecked) also needs S_DATASET (ACTVT 34) for the path.
*&
*& OUTPUT: Seven CSV files in the chosen folder, named:
*&           MARA_export.csv      -- general material master
*&           MARC_export.csv      -- material per plant (MRP fields)
*&                                   + valuation price (MBEW)
*&           MARD_export.csv      -- stock per storage location
*&           EKKO_export.csv      -- PO header
*&           EKPO_export.csv      -- PO line items
*&           MB51_export.csv      -- material movements (MSEG+MKPF join)
*&           T156T_export.csv     -- movement type texts
*&
*& RELEASE: ABAP 7.40 and later (ECC 6.0 EHP7+, S/4HANA). Plain ASCII.
*&          No text elements needed: copy, paste, activate.
*&
*& CHANGELOG:
*&   v1.8 - MARD: also the stock in transfer (UMLME), blocked stock
*&          (SPEME) and blocked returns (RETME), appended after ERSDA.
*&          The movements (MB51) post into and out of every stock type;
*&          a company that receives into blocked stock has goods in the
*&          warehouse that LABST alone does not show.
*&        - New file T156T_export.csv: the texts of the movement types
*&          (P_LANG, English if none), to tell the company's own types
*&          (9xx, Z..) apart. Checkbox "T156T", default on.
*&   v1.7 - ECC performance, same export content:
*&          - MAKT: English fallback description from a second LEFT
*&            OUTER JOIN (was FOR ALL ENTRIES + linear READ TABLE).
*&          - EKET: part of the EKPO join, folded per PO item in ABAP
*&            (was FOR ALL ENTRIES over one key per PO item).
*&          - MB51: optional "month by month" mode (P_MBMON, default
*&            off = the v1.6 statement): calendar-month slices of BUDAT,
*&            progress per month, same rows as the single statement.
*&          - Elapsed seconds of every read and every file in the output.
*&          Row order of EKPO/MB51 files may differ (no effect on Python).
*&   v1.6 - MBEW prices read with ONE statement filtered in the database
*&          (valuation areas of the plants + material type) instead of
*&          FOR ALL ENTRIES per material; T001W read once for the plants.
*&          FOR ALL ENTRIES is split into packages (on Oracle-based ECC
*&          typically 5 entries each: rsdb/max_blocking_factor), i.e.
*&          thousands of statements for ~10,000 materials; on S/4HANA
*&          each package also re-runs the compatibility view MBV_MBEW.
*&          Elapsed seconds of the MARC and MBEW reads in the output.
*&   v1.5 - Progress indicator in the status bar for every table (read /
*&          write). Each internal table is released (FREE) right after
*&          its file is written, so large selections need less memory.
*&   v1.4 - Selection-screen labels and frame titles set in the code
*&          (no text symbols / selection texts to maintain). F4 on the
*&          output folder opens the folder browser of the PC.
*&   v1.3 - MB51: every movement type by default (new select-option
*&          S_BWART, empty = all); the fixed list missed the company's
*&          goods receipts. New columns SHKZG, SOBKZ.
*&        - EKKO/EKPO: history period = P_MONTHS (EKKO was fixed to 12
*&          months). EKPO exports every item of the period, open or not,
*&          with the PO date (EKKO-BEDAT) and the quantity received so far
*&          (sum of EKET-WEMNG), so the open quantity and the planned lead
*&          time can be computed. EINDT = first schedule line (lead
*&          time), EINDT_OPEN = first schedule line not fully received
*&          (when the open quantity is due). Only items that replenish own
*&          stock (no KNTTP, RETPO, consignment).
*&        - MARC, MARD, EKPO, MB51 are restricted to the materials of
*&          S_MTART by a join with MARA in the database (MARC/MARD used a
*&          linear search per row, too slow for large selections).
*&        - Local download unchecked: the files are written to the
*&          application server (OPEN DATASET), so the report can run as a
*&          background job. P_PATH keeps lower case; a server path must be
*&          absolute and without '..'. P_MONTHS 1-99. In background a
*&          file that cannot be written ends the job as cancelled.
*&   v1.2 - MARC export carries the material price from MBEW (valuation
*&          area = T001W-BWKEY of the plant): price control VPRSV,
*&          standard price STPRS, moving average price VERPR, price
*&          unit PEINH. STPRS/PEINH were previously always empty.
*&   v1.1 - Fixed MB51 sign logic (was forcing negative for all movements,
*&          breaking goods receipts). Now uses the proper SHKZG-based sign.
*&   v1.0 - Initial version
*&---------------------------------------------------------------------*
REPORT zmrp_agent_export.

TABLES: mara, makt, marc, mard, ekko, ekpo, mseg, mkpf.

TYPES: BEGIN OF ty_mara,
         matnr TYPE mara-matnr,
         mtart TYPE mara-mtart,
         meins TYPE mara-meins,
         matkl TYPE mara-matkl,
         brgew TYPE mara-brgew,
         ntgew TYPE mara-ntgew,
         ersda TYPE mara-ersda,
         laeda TYPE mara-laeda,
         maktx TYPE makt-maktx,    " Material description (from MAKT)
         maktx_en TYPE makt-maktx, " English description: fallback, not exported
       END OF ty_mara.

TYPES: BEGIN OF ty_marc,
         matnr TYPE marc-matnr,
         werks TYPE marc-werks,
         dispo TYPE marc-dispo,
         dismm TYPE marc-dismm,
         disls TYPE marc-disls,
         beskz TYPE marc-beskz,
         plifz TYPE marc-plifz,
         eisbe TYPE marc-eisbe,
         minbe TYPE marc-minbe,
         bstmi TYPE marc-bstmi,
         bstma TYPE marc-bstma,
         bstrf TYPE marc-bstrf,
         " Valuation (MBEW), filled by READ_MBEW_PRICES
         stprs TYPE mbew-stprs,    " Standard price          (per PEINH)
         peinh TYPE mbew-peinh,    " Price unit
         vprsv TYPE mbew-vprsv,    " Price control: S = standard, V = moving avg
         verpr TYPE mbew-verpr,    " Moving average price    (per PEINH)
       END OF ty_marc.

TYPES: BEGIN OF ty_mard,
         matnr TYPE mard-matnr,
         werks TYPE mard-werks,
         lgort TYPE mard-lgort,
         labst TYPE mard-labst,
         insme TYPE mard-insme,
         einme TYPE mard-einme,
         umlme TYPE mard-umlme,    " Stock in transfer (v1.8)
         speme TYPE mard-speme,    " Blocked stock (v1.8)
         retme TYPE mard-retme,    " Blocked stock returns (v1.8)
       END OF ty_mard.

TYPES: BEGIN OF ty_ekko,
         ebeln TYPE ekko-ebeln,
         bsart TYPE ekko-bsart,
         lifnr TYPE ekko-lifnr,
         ekorg TYPE ekko-ekorg,
         bedat TYPE ekko-bedat,
         waers TYPE ekko-waers,
       END OF ty_ekko.

TYPES: BEGIN OF ty_ekpo,
         ebeln TYPE ekpo-ebeln,
         ebelp TYPE ekpo-ebelp,
         matnr TYPE ekpo-matnr,
         werks TYPE ekpo-werks,
         menge TYPE ekpo-menge,
         meins TYPE ekpo-meins,
         netpr TYPE ekpo-netpr,
         eindt TYPE eket-eindt,    " First schedule line (see EXTRACT_EKPO)
         elikz TYPE ekpo-elikz,
         loekz TYPE ekpo-loekz,
         bedat TYPE ekko-bedat,    " PO date (v1.3)
         wemng TYPE eket-wemng,    " Received so far, all schedule lines (v1.3)
         eindt_open TYPE eket-eindt, " First schedule line not fully received (v1.3)
       END OF ty_ekpo.

TYPES: BEGIN OF ty_mb51,
         mblnr TYPE mseg-mblnr,
         mjahr TYPE mseg-mjahr,
         zeile TYPE mseg-zeile,
         matnr TYPE mseg-matnr,
         werks TYPE mseg-werks,
         lgort TYPE mseg-lgort,
         bwart TYPE mseg-bwart,
         menge TYPE mseg-menge,
         meins TYPE mseg-meins,
         shkzg TYPE mseg-shkzg,
         budat TYPE mkpf-budat,
         sobkz TYPE mseg-sobkz,    " Special stock indicator (v1.3)
       END OF ty_mb51.

DATA: gt_mara TYPE STANDARD TABLE OF ty_mara,
      gt_marc TYPE STANDARD TABLE OF ty_marc,
      gt_mard TYPE STANDARD TABLE OF ty_mard,
      gt_ekko TYPE STANDARD TABLE OF ty_ekko,
      gt_ekpo TYPE STANDARD TABLE OF ty_ekpo,
      gt_mb51 TYPE STANDARD TABLE OF ty_mb51.

DATA: gv_filename TYPE string,
      gv_path     TYPE string,
      gv_csv_line TYPE string,
      gv_count    TYPE i,
      gv_cutoff   TYPE sy-datum,   " Start of the history period (P_MONTHS)
      gv_errors   TYPE i,          " Files that could not be written
      gv_steps    TYPE i,          " Progress indicator: tables to export
      gv_done     TYPE i.          " Progress indicator: tables written

*----------------------------------------------------------------------*
* Selection screen. Every label is a COMMENT / frame title filled in
* INITIALIZATION, so the report needs no text symbols and no selection
* texts: copy the source into SE38, activate, run. (A name in TITLE or
* COMMENT creates a global CHAR 83 field of that name implicitly.)
*----------------------------------------------------------------------*
SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE t_b1.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_path FOR FIELD p_path.
    " LOWER CASE: application-server paths are case-sensitive.
    " F4 opens the folder browser of the PC (AT SELECTION-SCREEN ON
    " VALUE-REQUEST below).
    PARAMETERS p_path TYPE string DEFAULT 'C:\sap_exports\' OBLIGATORY
                      LOWER CASE VISIBLE LENGTH 40.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_local AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(60) c_local FOR FIELD p_local.
  SELECTION-SCREEN END OF LINE.
SELECTION-SCREEN END OF BLOCK b1.

SELECTION-SCREEN BEGIN OF BLOCK b2 WITH FRAME TITLE t_b2.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_werks FOR FIELD s_werks.
    SELECT-OPTIONS s_werks FOR marc-werks.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_mtart FOR FIELD s_mtart.
    SELECT-OPTIONS s_mtart FOR mara-mtart.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_dispo FOR FIELD s_dispo.
    SELECT-OPTIONS s_dispo FOR marc-dispo.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_bwart FOR FIELD s_bwart.
    SELECT-OPTIONS s_bwart FOR mseg-bwart.   " Movement types (empty = all)
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_months FOR FIELD p_months.
    PARAMETERS p_months TYPE i DEFAULT 24.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    SELECTION-SCREEN COMMENT 1(31) c_lang FOR FIELD p_lang.
    PARAMETERS p_lang TYPE makt-spras DEFAULT 'E'.   " E=EN, D=DE, EL=GR
  SELECTION-SCREEN END OF LINE.
SELECTION-SCREEN END OF BLOCK b2.

SELECTION-SCREEN BEGIN OF BLOCK b3 WITH FRAME TITLE t_b3.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_mara AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_mara FOR FIELD p_mara.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_marc AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_marc FOR FIELD p_marc.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_mard AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_mard FOR FIELD p_mard.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_ekko AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_ekko FOR FIELD p_ekko.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_ekpo AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_ekpo FOR FIELD p_ekpo.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_mb51 AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_mb51 FOR FIELD p_mb51.
  SELECTION-SCREEN END OF LINE.
  " Off = one statement for the whole period (as v1.6). On = one
  " statement per month with progress per month: helps against dialog
  " TIME_OUTs, but is only faster if the database reads MKPF by posting
  " date - check the 'MB51 read in' seconds before using it routinely.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_mbmon AS CHECKBOX DEFAULT ' '.
    SELECTION-SCREEN COMMENT 3(60) c_mbmon FOR FIELD p_mbmon.
  SELECTION-SCREEN END OF LINE.
  SELECTION-SCREEN BEGIN OF LINE.
    PARAMETERS p_t156 AS CHECKBOX DEFAULT 'X'.
    SELECTION-SCREEN COMMENT 3(50) c_t156 FOR FIELD p_t156.
  SELECTION-SCREEN END OF LINE.
SELECTION-SCREEN END OF BLOCK b3.

INITIALIZATION.
  " Labels of the selection screen (no text elements needed)
  t_b1     = 'Output settings'.
  c_path   = 'Output folder (F4 = browse)'.
  c_local  = 'Download to the PC (unchecked: application server)'.
  t_b2     = 'Selection filters'.
  c_werks  = 'Plant'.
  c_mtart  = 'Material type'.
  c_dispo  = 'MRP controller'.
  c_bwart  = 'Movement type (empty = all)'.
  c_months = 'Months of history (1-99)'.
  c_lang   = 'Language of descriptions'.
  t_b3     = 'Tables to export'.
  c_mara   = 'MARA - material master (+ MAKT)'.
  c_marc   = 'MARC - plant data (+ MBEW price)'.
  c_mard   = 'MARD - stock per storage location'.
  c_ekko   = 'EKKO - purchase order headers'.
  c_ekpo   = 'EKPO - purchase order items (+ EKET)'.
  c_mb51   = 'MB51 - material movements (MSEG + MKPF)'.
  c_mbmon  = 'MB51 month by month (progress per month)'.
  c_t156   = 'T156T - movement type texts'.

AT SELECTION-SCREEN ON VALUE-REQUEST FOR p_path.
  PERFORM browse_folder.

AT SELECTION-SCREEN.
  PERFORM check_input.

START-OF-SELECTION.

  " Same checks again: a background job may start from a variant
  PERFORM check_input.
  PERFORM normalize_path.
  PERFORM calc_cutoff.

  WRITE: / 'Replenishment Agent - Data Export'.
  WRITE: / '====================================='.
  IF p_local = 'X'.
    WRITE: / 'Output folder (local PC):', p_path.
  ELSE.
    WRITE: / 'Output folder (application server):', p_path.
  ENDIF.
  WRITE: / 'History from:', gv_cutoff.
  ULINE.

  " Number of tables, for the progress indicator
  IF p_mara = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_marc = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_mard = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_ekko = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_ekpo = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_mb51 = 'X'. gv_steps = gv_steps + 1. ENDIF.
  IF p_t156 = 'X'. gv_steps = gv_steps + 1. ENDIF.

  IF p_mara = 'X'. PERFORM extract_mara. ENDIF.
  IF p_marc = 'X'. PERFORM extract_marc. ENDIF.
  IF p_mard = 'X'. PERFORM extract_mard. ENDIF.
  IF p_ekko = 'X'. PERFORM extract_ekko. ENDIF.
  IF p_ekpo = 'X'. PERFORM extract_ekpo. ENDIF.
  IF p_mb51 = 'X'. PERFORM extract_mb51. ENDIF.
  IF p_t156 = 'X'. PERFORM extract_t156t. ENDIF.

  ULINE.
  IF gv_errors > 0.
    WRITE: / gv_errors, 'file(s) could not be written - see the messages above.'.
    " Background: end the job as cancelled (SM37), details in the job log
    IF sy-batch = 'X'.
      MESSAGE 'Not all export files could be written - see the job log' TYPE 'E'.
    ENDIF.
  ELSE.
    WRITE: / 'Done. Copy the files to data/pilot/ in the project'.
    WRITE: / 'and run run_all_pilot.bat.'.
  ENDIF.

*&---------------------------------------------------------------------*
*& Form CHECK_INPUT - selection-screen checks (also for background jobs)
*&---------------------------------------------------------------------*
FORM check_input.
  " RP_CALC_DATE_IN_INTERVAL takes at most 99 months (NUMC 2)
  IF p_months < 1 OR p_months > 99.
    MESSAGE 'Months of history must be between 1 and 99' TYPE 'E'.
  ENDIF.

  IF p_local = 'X'.
    " A background job has no SAP GUI: files can only go to the server
    " (SJOB = "Execute in Background" pressed on the selection screen)
    IF sy-batch = 'X' OR sy-ucomm = 'SJOB'.
      MESSAGE 'Background job: uncheck Local download, give a server path' TYPE 'E'.
    ENDIF.
  ELSE.
    " Application server: absolute path without '..' (no directory
    " traversal); on Unix servers a Windows path such as the default
    " C:\sap_exports\ would only create odd file names in the work folder
    IF p_path CS '..'.
      MESSAGE 'The path must not contain ".."' TYPE 'E'.
    ENDIF.
    IF sy-opsys NS 'Windows' AND p_path NP '/*'.
      MESSAGE 'Server path must be absolute, e.g. /tmp/sap_exports/' TYPE 'E'.
    ENDIF.
    " Windows server: drive letter (D:\...) or UNC path (\\host\...)
    IF sy-opsys CS 'Windows' AND p_path NP '+:\*' AND p_path NP '\\*'.
      MESSAGE 'Server path must be absolute, e.g. D:\sap_exports\' TYPE 'E'.
    ENDIF.
  ENDIF.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form PROGRESS - status bar text "n/N ..." with the share of tables
*& already written. Each call is a round trip to SAP GUI, which on most
*& systems also restarts the dialog-step time limit (fewer TIME_OUTs).
*& No effect in background.
*&---------------------------------------------------------------------*
FORM progress USING p_text TYPE csequence.
  DATA: lv_text    TYPE c LENGTH 70,
        lv_percent TYPE i,
        lv_current TYPE i.

  IF gv_steps > 0.
    lv_percent = gv_done * 100 / gv_steps.
  ENDIF.
  lv_current = gv_done + 1.
  lv_text = |{ lv_current }/{ gv_steps } { p_text }|.

  CALL FUNCTION 'SAPGUI_PROGRESS_INDICATOR'
    EXPORTING
      percentage = lv_percent
      text       = lv_text.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form REPORT_ERROR - count a failed file; in background also log it
*&---------------------------------------------------------------------*
FORM report_error USING p_text TYPE string.
  gv_errors = gv_errors + 1.
  WRITE: / '  ERROR:', p_text.
  IF sy-batch = 'X'.
    MESSAGE p_text TYPE 'I'.   " job log entry; the job continues
  ENDIF.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form BROWSE_FOLDER - F4 on the output folder: folder browser of the
*& PC (SAP GUI). For the application server type the path by hand.
*&---------------------------------------------------------------------*
FORM browse_folder.
  DATA: lv_folder  TYPE string,
        lv_initial TYPE string.

  lv_initial = p_path.
  cl_gui_frontend_services=>directory_browse(
    EXPORTING
      window_title         = 'Folder for the export files'
      initial_folder       = lv_initial
    CHANGING
      selected_folder      = lv_folder
    EXCEPTIONS
      cntl_error           = 1
      error_no_gui         = 2
      not_supported_by_gui = 3
      OTHERS               = 4 ).
  IF sy-subrc = 0 AND lv_folder IS NOT INITIAL.   " empty = cancelled
    p_path = lv_folder.
    PERFORM normalize_path.                       " trailing '\'
  ENDIF.
ENDFORM.

FORM normalize_path.
  DATA: lv_last TYPE c LENGTH 1.
  IF p_path IS NOT INITIAL.
    DATA(lv_length) = strlen( p_path ) - 1.
    lv_last = p_path+lv_length(1).
    IF lv_last <> '\' AND lv_last <> '/'.
      " Unix-style path (application server) -> '/', Windows path -> '\'
      IF p_path CS '/'.
        CONCATENATE p_path '/' INTO p_path.
      ELSE.
        CONCATENATE p_path '\' INTO p_path.
      ENDIF.
    ENDIF.
  ENDIF.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form CALC_CUTOFF - start of the history period: today - P_MONTHS
*& (used by EKKO, EKPO and MB51)
*&---------------------------------------------------------------------*
FORM calc_cutoff.
  gv_cutoff = sy-datum.
  CALL FUNCTION 'RP_CALC_DATE_IN_INTERVAL'
    EXPORTING
      date      = gv_cutoff
      months    = CONV t5a4a-dlymo( p_months )
      signum    = '-'
      days      = 0
      years     = 0
    IMPORTING
      calc_date = gv_cutoff.
ENDFORM.

FORM extract_mara.
  DATA: lv_t0 TYPE timestampl.

  WRITE: / 'Extracting MARA + MAKT...'.
  PERFORM progress USING 'Reading MARA + MAKT'.
  GET TIME STAMP FIELD lv_t0.

  " Descriptions in P_LANG and in English in the same statement (two
  " LEFT OUTER JOINs on MAKT). Up to v1.6 the English fallback was read
  " FOR ALL ENTRIES and matched with a linear READ TABLE per material.
  SELECT m~matnr m~mtart m~meins m~matkl m~brgew m~ntgew m~ersda m~laeda
         t~maktx e~maktx AS maktx_en
    FROM mara AS m
    LEFT OUTER JOIN makt AS t
      ON  t~matnr = m~matnr
      AND t~spras = p_lang
    LEFT OUTER JOIN makt AS e
      ON  e~matnr = m~matnr
      AND e~spras = 'E'
    INTO TABLE gt_mara
    WHERE m~mtart IN s_mtart
      AND m~lvorm = ''.

  " No description in P_LANG -> English one (same rule as before)
  LOOP AT gt_mara ASSIGNING FIELD-SYMBOL(<fs_check>).
    IF <fs_check>-maktx IS INITIAL.
      <fs_check>-maktx = <fs_check>-maktx_en.
    ENDIF.
  ENDLOOP.
  PERFORM stopwatch USING lv_t0 'MARA + MAKT read in'.

  gv_count = lines( gt_mara ).
  WRITE: / '  ', gv_count, 'records (lang=', p_lang, ')'.
  CONCATENATE p_path 'MARA_export.csv' INTO gv_filename.
  PERFORM write_mara_csv USING gv_filename.
  FREE gt_mara.   " file written: release the memory
ENDFORM.

FORM extract_marc.
  DATA: lv_t0 TYPE timestampl.

  WRITE: / 'Extracting MARC...'.
  PERFORM progress USING 'Reading MARC'.
  GET TIME STAMP FIELD lv_t0.
  " Same material set as MARA (S_MTART, not flagged for deletion); the
  " join replaces the per-row READ TABLE on GT_MARA of v1.2.
  SELECT c~matnr c~werks c~dispo c~dismm c~disls c~beskz c~plifz
         c~eisbe c~minbe c~bstmi c~bstma c~bstrf
    FROM marc AS c
    INNER JOIN mara AS m
      ON m~matnr = c~matnr
    INTO TABLE gt_marc
    WHERE c~werks IN s_werks
      AND c~dispo IN s_dispo
      AND c~lvorm = ''
      AND m~mtart IN s_mtart
      AND m~lvorm = ''.
  PERFORM stopwatch USING lv_t0 'MARC read in'.

  PERFORM progress USING 'Reading MBEW prices'.
  PERFORM read_mbew_prices.

  gv_count = lines( gt_marc ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'MARC_export.csv' INTO gv_filename.
  PERFORM write_marc_csv USING gv_filename.
  FREE gt_marc.   " file written: release the memory
ENDFORM.

*&---------------------------------------------------------------------*
*& Form READ_MBEW_PRICES
*& Adds the valuation price of every GT_MARC row from MBEW.
*&   Valuation area: T001W-BWKEY of the plant (= the plant itself when
*&   valuation is at plant level, = the company code otherwise).
*&   BWTAR = space: the header record, which holds the total price also
*&   for materials with split valuation.
*& v1.6 performance: ONE statement for all prices, filtered in the
*& database (valuation areas of the selected plants + material type).
*& Up to v1.5 MBEW was read FOR ALL ENTRIES over one key per material.
*& The database interface splits that into packages - on Oracle-based
*& ECC usually 5 entries per statement (rsdb/max_blocking_factor), so
*& about 2,000 statements for 10,000 materials; on S/4HANA, where MBEW
*& is the compatibility view MBV_MBEW, every package also recomputes
*& the view. T001W was read FOR ALL ENTRIES over every material as well
*& (one entry per material) instead of once for the plants.
*& Materials without an MBEW record keep initial values; the Python
*& pipeline then estimates a cost (src/utils/cost_estimator.py).
*&---------------------------------------------------------------------*
FORM read_mbew_prices.
  TYPES: BEGIN OF ty_plant_bwkey,
           werks TYPE t001w-werks,
           bwkey TYPE t001w-bwkey,
         END OF ty_plant_bwkey,
         BEGIN OF ty_mbew_price,
           matnr TYPE mbew-matnr,
           bwkey TYPE mbew-bwkey,
           vprsv TYPE mbew-vprsv,
           stprs TYPE mbew-stprs,
           verpr TYPE mbew-verpr,
           peinh TYPE mbew-peinh,
         END OF ty_mbew_price.

  DATA: lt_plant_bwkey TYPE SORTED TABLE OF ty_plant_bwkey
                            WITH UNIQUE KEY werks,
        lr_bwkey       TYPE RANGE OF t001w-bwkey,
        lt_prices      TYPE SORTED TABLE OF ty_mbew_price
                            WITH NON-UNIQUE KEY matnr bwkey,
        ls_plant_bwkey TYPE ty_plant_bwkey,
        ls_price       TYPE ty_mbew_price,
        lv_found       TYPE i,
        lv_total       TYPE i,
        lv_t0          TYPE timestampl.

  FIELD-SYMBOLS: <ls_marc> TYPE ty_marc.

  CHECK gt_marc IS NOT INITIAL.

  " Valuation areas of the selected plants: one small read of T001W
  SELECT werks bwkey
    FROM t001w
    INTO TABLE lt_plant_bwkey
    WHERE werks IN s_werks.

  LOOP AT lt_plant_bwkey INTO ls_plant_bwkey.
    APPEND VALUE #( sign = 'I' option = 'EQ' low = ls_plant_bwkey-bwkey )
      TO lr_bwkey.
  ENDLOOP.
  SORT lr_bwkey BY low.
  DELETE ADJACENT DUPLICATES FROM lr_bwkey COMPARING low.

  " An empty range would select every valuation area
  IF lr_bwkey IS INITIAL.
    WRITE: / '  WARNING: no valuation area found for the selected plants'.
    RETURN.
  ENDIF.

  " All prices in one statement (see the header of this form)
  GET TIME STAMP FIELD lv_t0.
  SELECT b~matnr b~bwkey b~vprsv b~stprs b~verpr b~peinh
    FROM mbew AS b
    INNER JOIN mara AS m
      ON m~matnr = b~matnr
    INTO TABLE lt_prices
    WHERE b~bwkey IN lr_bwkey
      AND b~bwtar = space
      AND m~mtart IN s_mtart
      AND m~lvorm = ''.
  PERFORM stopwatch USING lv_t0 'MBEW prices read in'.

  LOOP AT gt_marc ASSIGNING <ls_marc>.
    READ TABLE lt_plant_bwkey INTO ls_plant_bwkey
         WITH TABLE KEY werks = <ls_marc>-werks.
    IF sy-subrc <> 0.
      CONTINUE.
    ENDIF.
    READ TABLE lt_prices INTO ls_price
         WITH TABLE KEY matnr = <ls_marc>-matnr
                        bwkey = ls_plant_bwkey-bwkey.
    IF sy-subrc = 0.
      <ls_marc>-vprsv = ls_price-vprsv.
      <ls_marc>-stprs = ls_price-stprs.
      <ls_marc>-verpr = ls_price-verpr.
      <ls_marc>-peinh = ls_price-peinh.
      lv_found = lv_found + 1.
    ENDIF.
  ENDLOOP.

  lv_total = lines( gt_marc ).
  WRITE: / '  Prices from MBEW:', lv_found, 'of', lv_total, 'materials'.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form STOPWATCH - writes the seconds elapsed since P_T0 to the list,
*& so slow steps can be seen in the output (and in the spool)
*&---------------------------------------------------------------------*
FORM stopwatch USING p_t0    TYPE timestampl
                     p_label TYPE csequence.
  DATA: lv_t1      TYPE timestampl,
        lv_seconds TYPE p LENGTH 10 DECIMALS 1.

  GET TIME STAMP FIELD lv_t1.
  lv_seconds = cl_abap_tstmp=>subtract( tstmp1 = lv_t1
                                        tstmp2 = p_t0 ).
  WRITE: / '  ', p_label, lv_seconds, 's'.
ENDFORM.

FORM extract_mard.
  DATA: lv_t0 TYPE timestampl.

  WRITE: / 'Extracting MARD...'.
  PERFORM progress USING 'Reading MARD'.
  GET TIME STAMP FIELD lv_t0.
  " Same materials/plants as MARC (join instead of the per-row
  " READ TABLE on GT_MARC of v1.2)
  SELECT d~matnr d~werks d~lgort d~labst d~insme d~einme
         d~umlme d~speme d~retme
    FROM mard AS d
    INNER JOIN marc AS c
      ON  c~matnr = d~matnr
      AND c~werks = d~werks
    INNER JOIN mara AS m
      ON m~matnr = d~matnr
    INTO TABLE gt_mard
    WHERE d~werks IN s_werks
      AND d~lvorm = ''
      AND c~dispo IN s_dispo
      AND c~lvorm = ''
      AND m~mtart IN s_mtart
      AND m~lvorm = ''.
  PERFORM stopwatch USING lv_t0 'MARD read in'.

  gv_count = lines( gt_mard ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'MARD_export.csv' INTO gv_filename.
  PERFORM write_mard_csv USING gv_filename.
  FREE gt_mard.   " file written: release the memory
ENDFORM.

FORM extract_ekko.
  DATA: lv_t0 TYPE timestampl.

  WRITE: / 'Extracting EKKO...'.
  PERFORM progress USING 'Reading EKKO'.
  GET TIME STAMP FIELD lv_t0.
  " Purchase orders of the history period (was fixed to 12 months up to
  " v1.2). Same header conditions as EXTRACT_EKPO, so every exported PO
  " item finds its header (supplier) here.
  SELECT ebeln bsart lifnr ekorg bedat waers
    FROM ekko
    INTO TABLE gt_ekko
    WHERE bedat >= gv_cutoff
      AND bstyp = 'F'
      AND loekz = ''.
  PERFORM stopwatch USING lv_t0 'EKKO read in'.

  gv_count = lines( gt_ekko ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'EKKO_export.csv' INTO gv_filename.
  PERFORM write_ekko_csv USING gv_filename.
  FREE gt_ekko.   " file written: release the memory
ENDFORM.

FORM extract_ekpo.
  " One row per schedule line (EKET), folded into one row per PO item
  " below. Up to v1.6 EKET was read FOR ALL ENTRIES over one key per PO
  " item (thousands of statements on ECC); now it is part of the join.
  TYPES: BEGIN OF ty_ekpo_line,
           ebeln    TYPE ekpo-ebeln,
           ebelp    TYPE ekpo-ebelp,
           matnr    TYPE ekpo-matnr,
           werks    TYPE ekpo-werks,
           menge    TYPE ekpo-menge,
           meins    TYPE ekpo-meins,
           netpr    TYPE ekpo-netpr,
           elikz    TYPE ekpo-elikz,
           loekz    TYPE ekpo-loekz,
           bedat    TYPE ekko-bedat,
           etenr    TYPE eket-etenr,
           eindt    TYPE eket-eindt,
           et_menge TYPE eket-menge,    " scheduled quantity of the line
           wemng    TYPE eket-wemng,
         END OF ty_ekpo_line.

  DATA: lt_lines TYPE STANDARD TABLE OF ty_ekpo_line,
        ls_item  TYPE ty_ekpo,
        lv_t0    TYPE timestampl.

  FIELD-SYMBOLS: <ls_line> TYPE ty_ekpo_line.

  WRITE: / 'Extracting EKPO...'.
  PERFORM progress USING 'Reading EKPO + EKET'.
  GET TIME STAMP FIELD lv_t0.

  " Every item of the purchase orders of the history period - open AND
  " completed (v1.2 exported only items without ELIKZ). Completed items
  " give the planned lead time (EINDT - BEDAT) and the order sizes; the
  " Python side marks an item open when ELIKZ is blank and
  " MENGE - WEMNG > 0. Restricted to the materials of S_MTART and to
  " items that replenish own stock: no account assignment (KNTTP), no
  " returns item (RETPO), no consignment item (PSTYP 2).
  " LEFT OUTER JOIN: an item without schedule lines is kept (with empty
  " dates and nothing received), exactly as before.
  SELECT p~ebeln p~ebelp p~matnr p~werks p~menge p~meins p~netpr
         p~elikz p~loekz k~bedat
         t~etenr t~eindt t~menge AS et_menge t~wemng
    FROM ekpo AS p
    INNER JOIN ekko AS k
      ON k~ebeln = p~ebeln
    INNER JOIN mara AS m
      ON m~matnr = p~matnr
    LEFT OUTER JOIN eket AS t
      ON  t~ebeln = p~ebeln
      AND t~ebelp = p~ebelp
    INTO TABLE lt_lines
    WHERE k~bedat >= gv_cutoff
      AND k~bstyp = 'F'
      AND k~loekz = ''
      AND p~loekz = ''
      AND p~knttp = ''
      AND p~retpo = ''
      AND p~pstyp <> '2'
      AND p~werks IN s_werks
      AND m~mtart IN s_mtart
      AND m~lvorm = ''.

  " One row per PO item, schedule lines in ETENR order (the same rules
  " as READ_EKET of v1.3-v1.6):
  "   EINDT      = first schedule line with a date (lead time)
  "   EINDT_OPEN = first schedule line not fully received
  "   WEMNG      = received quantity, summed over the schedule lines
  SORT lt_lines BY ebeln ebelp etenr.
  LOOP AT lt_lines ASSIGNING <ls_line>.
    IF <ls_line>-ebeln <> ls_item-ebeln OR <ls_line>-ebelp <> ls_item-ebelp.
      IF ls_item-ebeln IS NOT INITIAL.
        APPEND ls_item TO gt_ekpo.
      ENDIF.
      CLEAR ls_item.
      ls_item-ebeln = <ls_line>-ebeln.
      ls_item-ebelp = <ls_line>-ebelp.
      ls_item-matnr = <ls_line>-matnr.
      ls_item-werks = <ls_line>-werks.
      ls_item-menge = <ls_line>-menge.
      ls_item-meins = <ls_line>-meins.
      ls_item-netpr = <ls_line>-netpr.
      ls_item-elikz = <ls_line>-elikz.
      ls_item-loekz = <ls_line>-loekz.
      ls_item-bedat = <ls_line>-bedat.
    ENDIF.
    IF ls_item-eindt IS INITIAL.
      ls_item-eindt = <ls_line>-eindt.
    ENDIF.
    IF ls_item-eindt_open IS INITIAL AND <ls_line>-et_menge > <ls_line>-wemng.
      ls_item-eindt_open = <ls_line>-eindt.
    ENDIF.
    ls_item-wemng = ls_item-wemng + <ls_line>-wemng.
  ENDLOOP.
  IF ls_item-ebeln IS NOT INITIAL.
    APPEND ls_item TO gt_ekpo.
  ENDIF.
  FREE lt_lines.
  PERFORM stopwatch USING lv_t0 'EKPO + EKET read in'.

  gv_count = lines( gt_ekpo ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'EKPO_export.csv' INTO gv_filename.
  PERFORM write_ekpo_csv USING gv_filename.
  FREE gt_ekpo.   " file written: release the memory
ENDFORM.

FORM extract_mb51.
  DATA: lv_t0 TYPE timestampl.

  WRITE: / 'Extracting MB51 (MSEG+MKPF)...'.
  PERFORM progress USING 'Reading MSEG + MKPF'.
  GET TIME STAMP FIELD lv_t0.

  WRITE: / '  Cutoff date:', gv_cutoff.

  " Every movement type unless S_BWART restricts it. Up to v1.2 a fixed
  " list was used, which missed the goods receipts of companies that do
  " not post them with 101 (e.g. 103/105, 107/109, 501, Z-types).
  " The SHKZG-signed quantity keeps every stock change consistent; the
  " Python side decides which movement types are demand.
  IF p_mbmon = 'X'.
    PERFORM read_mb51_by_month.
  ELSE.
    SELECT s~mblnr s~mjahr s~zeile s~matnr s~werks s~lgort s~bwart
           s~menge s~meins s~shkzg h~budat s~sobkz
      FROM mseg AS s
      INNER JOIN mkpf AS h
        ON  h~mblnr = s~mblnr
        AND h~mjahr = s~mjahr
      INNER JOIN mara AS m
        ON m~matnr = s~matnr
      INTO TABLE gt_mb51
      WHERE h~budat >= gv_cutoff
        AND s~werks IN s_werks
        AND s~bwart IN s_bwart
        AND m~mtart IN s_mtart
        AND m~lvorm = ''.
  ENDIF.
  PERFORM stopwatch USING lv_t0 'MB51 read in'.

  gv_count = lines( gt_mb51 ).
  WRITE: / '  ', gv_count, 'records'.

  CONCATENATE p_path 'MB51_export.csv' INTO gv_filename.
  PERFORM write_mb51_csv USING gv_filename.
  FREE gt_mb51.   " file written: release the memory
ENDFORM.

*&---------------------------------------------------------------------*
*& Form READ_MB51_BY_MONTH (option "MB51 month by month", v1.7)
*& Same rows as the single statement 'BUDAT >= cutoff': calendar-month
*& slices of the posting date that do not overlap, the last one
*& open-ended. Progress per month in the status bar (fewer TIME_OUTs in
*& dialog). Faster only if the database reads MKPF by posting date; if
*& it starts from the materials (index MSEG~M) every slice re-reads the
*& same movements - compare the 'MB51 read in' seconds of both modes.
*& The slices are separate reads: a movement posted DURING the run with
*& a posting date in a month already read is not included.
*&---------------------------------------------------------------------*
FORM read_mb51_by_month.
  DATA: lv_from   TYPE sy-datum,
        lv_to     TYPE sy-datum,
        lv_next   TYPE sy-datum,
        lv_ymd    TYPE c LENGTH 8,    " date as text: substrings are type c
        lv_year   TYPE n LENGTH 4,
        lv_month  TYPE n LENGTH 2,
        lv_y0     TYPE i,
        lv_m0     TYPE i,
        lv_y1     TYPE i,
        lv_m1     TYPE i,
        lv_slices TYPE i,
        lv_slice  TYPE i,
        lv_text   TYPE string.

  " Number of slices (only for the progress text)
  lv_ymd = gv_cutoff.
  lv_y0  = lv_ymd(4).
  lv_m0  = lv_ymd+4(2).
  lv_ymd = sy-datum.
  lv_y1  = lv_ymd(4).
  lv_m1  = lv_ymd+4(2).
  lv_slices = ( lv_y1 - lv_y0 ) * 12 + ( lv_m1 - lv_m0 ) + 1.

  lv_from = gv_cutoff.
  DO.
    lv_slice = sy-index.
    " First day of the next month -> last day of this slice
    lv_ymd   = lv_from.
    lv_year  = lv_ymd(4).
    lv_month = lv_ymd+4(2).
    IF lv_month = 12.
      lv_year  = lv_year + 1.
      lv_month = 1.
    ELSE.
      lv_month = lv_month + 1.
    ENDIF.
    CONCATENATE lv_year lv_month '01' INTO lv_ymd.
    lv_next = lv_ymd.
    lv_to   = lv_next - 1.
    " Current month, or safety stop: open-ended last slice
    IF lv_to >= sy-datum OR lv_slice >= 100.
      lv_to = '99991231'.
    ENDIF.

    lv_ymd  = lv_from.
    lv_text = |Reading MSEG + MKPF, month { lv_ymd(4) }-{ lv_ymd+4(2) } | &&
              |({ lv_slice }/{ lv_slices })|.
    PERFORM progress USING lv_text.

    SELECT s~mblnr s~mjahr s~zeile s~matnr s~werks s~lgort s~bwart
           s~menge s~meins s~shkzg h~budat s~sobkz
      FROM mseg AS s
      INNER JOIN mkpf AS h
        ON  h~mblnr = s~mblnr
        AND h~mjahr = s~mjahr
      INNER JOIN mara AS m
        ON m~matnr = s~matnr
      APPENDING TABLE gt_mb51
      WHERE h~budat BETWEEN lv_from AND lv_to
        AND s~werks IN s_werks
        AND s~bwart IN s_bwart
        AND m~mtart IN s_mtart
        AND m~lvorm = ''.

    IF lv_to = '99991231'.
      EXIT.
    ENDIF.
    lv_from = lv_next.
  ENDDO.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form EXTRACT_T156T (v1.8) - texts of the movement types, so that the
*& company's own types (9xx, Z..) can be told apart: receipt, sale,
*& inventory difference... One text per special stock / movement
*& indicator (SOBKZ, KZBEW, KZZUG, KZVBR).
*&---------------------------------------------------------------------*
FORM extract_t156t.
  TYPES: BEGIN OF ty_t156t,
           spras TYPE t156t-spras,
           bwart TYPE t156t-bwart,
           sobkz TYPE t156t-sobkz,
           kzbew TYPE t156t-kzbew,
           kzzug TYPE t156t-kzzug,
           kzvbr TYPE t156t-kzvbr,
           btext TYPE t156t-btext,
         END OF ty_t156t.
  DATA: lt_t156t TYPE STANDARD TABLE OF ty_t156t,
        lt_csv   TYPE TABLE OF string,
        lv_text  TYPE string,
        lv_t0    TYPE timestampl.

  WRITE: / 'Extracting T156T...'.
  PERFORM progress USING 'Reading T156T'.
  GET TIME STAMP FIELD lv_t0.
  " Language of the descriptions; English if it has no texts
  SELECT spras bwart sobkz kzbew kzzug kzvbr btext
    FROM t156t
    INTO TABLE lt_t156t
    WHERE spras = p_lang.
  IF lt_t156t IS INITIAL AND p_lang <> 'E'.
    SELECT spras bwart sobkz kzbew kzzug kzvbr btext
      FROM t156t
      INTO TABLE lt_t156t
      WHERE spras = 'E'.
  ENDIF.
  PERFORM stopwatch USING lv_t0 'T156T read in'.
  SORT lt_t156t BY bwart sobkz kzbew kzzug kzvbr.

  gv_count = lines( lt_t156t ).
  WRITE: / '  ', gv_count, 'records'.

  APPEND 'SPRAS;BWART;SOBKZ;KZBEW;KZZUG;KZVBR;BTEXT' TO lt_csv.
  LOOP AT lt_t156t INTO DATA(ls).
    " Same sanitizing as the material descriptions
    lv_text = ls-btext.
    REPLACE ALL OCCURRENCES OF ';' IN lv_text WITH ','.
    REPLACE ALL OCCURRENCES OF '"' IN lv_text WITH ''''.
    CONCATENATE ls-spras ls-bwart ls-sobkz ls-kzbew ls-kzzug ls-kzvbr lv_text
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
  ENDLOOP.

  CONCATENATE p_path 'T156T_export.csv' INTO gv_filename.
  PERFORM write_file USING gv_filename lt_csv.
ENDFORM.

FORM write_mara_csv USING p_file TYPE string.
  DATA: lt_csv     TYPE TABLE OF string,
        lv_maktx   TYPE string.

  APPEND 'MATNR;MTART;MEINS;MATKL;BRGEW;NTGEW;ERSDA;LAEDA;MAKTX' TO lt_csv.

  LOOP AT gt_mara INTO DATA(ls).
    DATA(lv_brgew) = CONV string( ls-brgew ).
    DATA(lv_ntgew) = CONV string( ls-ntgew ).

    " Sanitize description: replace CSV-breaking chars
    "   ';' -> ',' (otherwise breaks the field separator)
    "   CR/LF -> ' ' (otherwise breaks line structure)
    "   '"' -> "'"  (cleaner than escaping)
    lv_maktx = ls-maktx.
    REPLACE ALL OCCURRENCES OF ';'        IN lv_maktx WITH ','.
    REPLACE ALL OCCURRENCES OF cl_abap_char_utilities=>cr_lf
                                          IN lv_maktx WITH ' '.
    REPLACE ALL OCCURRENCES OF cl_abap_char_utilities=>newline
                                          IN lv_maktx WITH ' '.
    REPLACE ALL OCCURRENCES OF '"'        IN lv_maktx WITH ''''.
    CONDENSE lv_maktx.

    CONCATENATE ls-matnr ls-mtart ls-meins ls-matkl
                lv_brgew lv_ntgew ls-ersda ls-laeda
                lv_maktx
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_brgew, lv_ntgew, lv_maktx.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_marc_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  " VPRSV / VERPR appended at the end (v1.2) so older readers keep working
  APPEND 'MATNR;WERKS;DISPO;DISMM;DISLS;BESKZ;PLIFZ;EISBE;MINBE;BSTMI;BSTMA;BSTRF;STPRS;PEINH;VPRSV;VERPR'
    TO lt_csv.

  LOOP AT gt_marc INTO DATA(ls).
    DATA(lv_plifz) = CONV string( ls-plifz ).
    DATA(lv_eisbe) = CONV string( ls-eisbe ).
    DATA(lv_minbe) = CONV string( ls-minbe ).
    DATA(lv_bstmi) = CONV string( ls-bstmi ).
    DATA(lv_bstma) = CONV string( ls-bstma ).
    DATA(lv_bstrf) = CONV string( ls-bstrf ).
    DATA(lv_stprs) = CONV string( ls-stprs ).
    DATA(lv_peinh) = CONV string( ls-peinh ).
    DATA(lv_verpr) = CONV string( ls-verpr ).
    CONCATENATE ls-matnr ls-werks ls-dispo ls-dismm ls-disls
                ls-beskz lv_plifz lv_eisbe lv_minbe lv_bstmi
                lv_bstma lv_bstrf lv_stprs lv_peinh ls-vprsv lv_verpr
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_plifz, lv_eisbe, lv_minbe, lv_bstmi, lv_bstma, lv_bstrf,
           lv_stprs, lv_peinh, lv_verpr.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_mard_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  " UMLME / SPEME / RETME appended after ERSDA (v1.8): older readers that
  " use the column positions keep working.
  APPEND 'MATNR;WERKS;LGORT;LABST;INSME;EINME;ERSDA;UMLME;SPEME;RETME' TO lt_csv.

  LOOP AT gt_mard INTO DATA(ls).
    DATA(lv_today) = sy-datum.
    DATA(lv_labst) = CONV string( ls-labst ).
    DATA(lv_insme) = CONV string( ls-insme ).
    DATA(lv_einme) = CONV string( ls-einme ).
    DATA(lv_umlme) = CONV string( ls-umlme ).
    DATA(lv_speme) = CONV string( ls-speme ).
    DATA(lv_retme) = CONV string( ls-retme ).
    CONCATENATE ls-matnr ls-werks ls-lgort
                lv_labst lv_insme lv_einme lv_today
                lv_umlme lv_speme lv_retme
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_labst, lv_insme, lv_einme, lv_umlme, lv_speme, lv_retme.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_ekko_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  APPEND 'EBELN;BSART;LIFNR;EKORG;BEDAT;WAERS' TO lt_csv.

  LOOP AT gt_ekko INTO DATA(ls).
    CONCATENATE ls-ebeln ls-bsart ls-lifnr ls-ekorg ls-bedat ls-waers
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_ekpo_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  " BEDAT / WEMNG / EINDT_OPEN appended at the end (v1.3) so older
  " readers keep working
  APPEND 'EBELN;EBELP;MATNR;WERKS;MENGE;MEINS;NETPR;EINDT;ELIKZ;LOEKZ;BEDAT;WEMNG;EINDT_OPEN'
    TO lt_csv.

  LOOP AT gt_ekpo INTO DATA(ls).
    DATA(lv_menge) = CONV string( |{ ls-menge DECIMALS = 0 }| ).
    DATA(lv_netpr) = CONV string( ls-netpr ).
    DATA(lv_wemng) = CONV string( |{ ls-wemng DECIMALS = 0 }| ).
    CONCATENATE ls-ebeln ls-ebelp ls-matnr ls-werks lv_menge ls-meins
                lv_netpr ls-eindt ls-elikz ls-loekz ls-bedat lv_wemng
                ls-eindt_open
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_menge, lv_netpr, lv_wemng.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form WRITE_MB51_CSV
*& FIXED v1.1 - uses SHKZG for sign instead of forcing negative
*&   SHKZG = 'S' (Soll/Debit)   -> goods receipt -> POSITIVE
*&   SHKZG = 'H' (Haben/Credit) -> goods issue   -> NEGATIVE
*&---------------------------------------------------------------------*
FORM write_mb51_csv USING p_file TYPE string.

  DATA: lt_csv     TYPE TABLE OF string,
        lv_menge   TYPE string,
        lv_signed  TYPE p DECIMALS 3.

  " SHKZG / SOBKZ appended at the end (v1.3) so older readers keep working;
  " MENGE stays signed as in v1.1
  APPEND 'MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT;SHKZG;SOBKZ'
    TO lt_csv.

  LOOP AT gt_mb51 INTO DATA(ls).

    " Sign correction based on Debit/Credit indicator.
    " MSEG-MENGE in SAP is unsigned; the sign comes from SHKZG.
    IF ls-shkzg = 'H'.
      lv_signed = ls-menge * -1.
    ELSE.
      lv_signed = ls-menge.
    ENDIF.

    " Format as plain integer string. SIGN = LEFT puts the sign at the
    " front (e.g. '-50' instead of SAP's default trailing '50-').
    lv_menge = CONV string( |{ lv_signed DECIMALS = 0 SIGN = LEFT }| ).
    CONDENSE lv_menge.

    CONCATENATE ls-mblnr ls-mjahr ls-zeile ls-matnr ls-werks ls-lgort
                ls-bwart lv_menge ls-meins ls-budat ls-shkzg ls-sobkz
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_menge, lv_signed.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.

ENDFORM.

FORM write_file USING p_file TYPE string
                      pt_data TYPE STANDARD TABLE.
  DATA: lv_error_text TYPE string,
        lv_progress   TYPE string,
        lv_t0         TYPE timestampl.
  FIELD-SYMBOLS: <lv_line> TYPE any.

  lv_progress = |Writing { p_file }|.
  PERFORM progress USING lv_progress.
  gv_done = gv_done + 1.   " counted here: the error paths below RETURN early
  GET TIME STAMP FIELD lv_t0.

  IF p_local = 'X'.
    cl_gui_frontend_services=>gui_download(
      EXPORTING
        filename                = p_file
        filetype                = 'ASC'
        write_field_separator   = ' '
        codepage                = '4110'
        trunc_trailing_blanks   = 'X'
      CHANGING
        data_tab                = pt_data
      EXCEPTIONS
        OTHERS                  = 99 ).
    IF sy-subrc <> 0.
      lv_error_text = |Could not write { p_file } (GUI_DOWNLOAD code { sy-subrc })|.
      PERFORM report_error USING lv_error_text.
    ELSE.
      WRITE: / '  Saved:', p_file.
      PERFORM stopwatch USING lv_t0 'File written in'.
    ENDIF.
  ELSE.
    " Application server (v1.3) - e.g. for a background job (SM36).
    " UTF-8 like the local download; fetch the files with CG3Y or AL11.
    TRY.
        OPEN DATASET p_file FOR OUTPUT IN TEXT MODE ENCODING UTF-8.
        IF sy-subrc <> 0.
          lv_error_text = |Could not open { p_file } on the application server|.
          PERFORM report_error USING lv_error_text.
          RETURN.
        ENDIF.
        LOOP AT pt_data ASSIGNING <lv_line>.
          TRANSFER <lv_line> TO p_file.
        ENDLOOP.
        CLOSE DATASET p_file.
        WRITE: / '  Saved (server):', p_file.
        PERFORM stopwatch USING lv_t0 'File written in'.
      CATCH cx_root INTO DATA(lx_error).   " e.g. no S_DATASET authorization
        CLOSE DATASET p_file.
        lv_error_text = |Could not write { p_file }: { lx_error->get_text( ) }|.
        PERFORM report_error USING lv_error_text.
    ENDTRY.
  ENDIF.
ENDFORM.
