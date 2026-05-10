*&---------------------------------------------------------------------*
*& Report  ZMRP_AGENT_EXPORT
*&---------------------------------------------------------------------*
*& Title       : Data extraction for Replenishment Agent (Athens MBA)
*& Description : Extracts MARA, MARC, MARD, EKKO, EKPO, MB51 to flat
*&               files (CSV format) ready for the Python ETL pipeline.
*&
*& Author      : George Drakos
*& Created     : 2026
*& Thesis      : Athens MBA - Intelligent Agent for Inventory
*&               Replenishment with SAP Integration
*& Supervisor  : Σωτήρης Γκαγιαλής
*&
*& AUTHORIZATION: Read-only on tables MARA, MARC, MARD, EKKO, EKPO,
*&                MSEG, MKPF. No data modification.
*&
*& OUTPUT: Six CSV files in the chosen folder, named:
*&           MARA_export.csv      -- general material master
*&           MARC_export.csv      -- material per plant (MRP fields)
*&           MARD_export.csv      -- stock per storage location
*&           EKKO_export.csv      -- PO header
*&           EKPO_export.csv      -- PO line items
*&           MB51_export.csv      -- material movements (MSEG+MKPF join)
*&
*& CHANGELOG:
*&   v1.1 - Fixed MB51 sign logic (was forcing negative for all movements,
*&          breaking goods receipts). Now uses the proper SHKZG-based sign.
*&   v1.0 - Initial version
*&---------------------------------------------------------------------*
REPORT zmrp_agent_export.

TABLES: mara, marc, mard, ekko, ekpo, mseg, mkpf.

TYPES: BEGIN OF ty_mara,
         matnr TYPE mara-matnr,
         mtart TYPE mara-mtart,
         meins TYPE mara-meins,
         matkl TYPE mara-matkl,
         brgew TYPE mara-brgew,
         ntgew TYPE mara-ntgew,
         ersda TYPE mara-ersda,
         laeda TYPE mara-laeda,
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
         stprs TYPE c LENGTH 10,
         peinh TYPE c LENGTH 10,
       END OF ty_marc.

TYPES: BEGIN OF ty_mard,
         matnr TYPE mard-matnr,
         werks TYPE mard-werks,
         lgort TYPE mard-lgort,
         labst TYPE mard-labst,
         insme TYPE mard-insme,
         einme TYPE mard-einme,
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
         eindt TYPE eket-eindt,
         elikz TYPE ekpo-elikz,
         loekz TYPE ekpo-loekz,
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
      gv_count    TYPE i.

SELECTION-SCREEN BEGIN OF BLOCK b1 WITH FRAME TITLE TEXT-001.
  PARAMETERS: p_path  TYPE string DEFAULT 'C:\sap_exports\' OBLIGATORY,
              p_local AS CHECKBOX DEFAULT 'X'.
SELECTION-SCREEN END OF BLOCK b1.

SELECTION-SCREEN BEGIN OF BLOCK b2 WITH FRAME TITLE TEXT-002.
  SELECT-OPTIONS: s_werks FOR marc-werks,
                  s_mtart FOR mara-mtart,
                  s_dispo FOR marc-dispo.
  PARAMETERS: p_months TYPE i DEFAULT 24.
SELECTION-SCREEN END OF BLOCK b2.

SELECTION-SCREEN BEGIN OF BLOCK b3 WITH FRAME TITLE TEXT-003.
  PARAMETERS: p_mara AS CHECKBOX DEFAULT 'X',
              p_marc AS CHECKBOX DEFAULT 'X',
              p_mard AS CHECKBOX DEFAULT 'X',
              p_ekko AS CHECKBOX DEFAULT 'X',
              p_ekpo AS CHECKBOX DEFAULT 'X',
              p_mb51 AS CHECKBOX DEFAULT 'X'.
SELECTION-SCREEN END OF BLOCK b3.

INITIALIZATION.
  " text-001 = Output Settings
  " text-002 = Selection Filters
  " text-003 = Tables to Export

START-OF-SELECTION.

  PERFORM normalize_path.

  WRITE: / 'Replenishment Agent — Data Export'.
  WRITE: / '====================================='.
  WRITE: / 'Output folder:', p_path.
  ULINE.

  IF p_mara = 'X'. PERFORM extract_mara. ENDIF.
  IF p_marc = 'X'. PERFORM extract_marc. ENDIF.
  IF p_mard = 'X'. PERFORM extract_mard. ENDIF.
  IF p_ekko = 'X'. PERFORM extract_ekko. ENDIF.
  IF p_ekpo = 'X'. PERFORM extract_ekpo. ENDIF.
  IF p_mb51 = 'X'. PERFORM extract_mb51. ENDIF.

  ULINE.
  WRITE: / 'Done. Copy files to data/raw/ in your project.'.
  WRITE: / 'Then run: python -m src.data_layer.anonymization'.

FORM normalize_path.
  DATA: lv_last TYPE c LENGTH 1.
  IF p_path IS NOT INITIAL.
    DATA(lv_length) = strlen( p_path ) - 1.
    lv_last = p_path+lv_length(1).
    IF lv_last <> '\' AND lv_last <> '/'.
      CONCATENATE p_path '\' INTO p_path.
    ENDIF.
  ENDIF.
ENDFORM.

FORM extract_mara.
  WRITE: / 'Extracting MARA...'.
  SELECT matnr mtart meins matkl brgew ntgew ersda laeda
    FROM mara
    INTO TABLE gt_mara
    WHERE mtart IN s_mtart
      AND lvorm = ''.
  gv_count = lines( gt_mara ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'MARA_export.csv' INTO gv_filename.
  PERFORM write_mara_csv USING gv_filename.
ENDFORM.

FORM extract_marc.
  WRITE: / 'Extracting MARC...'.
  SELECT matnr werks dispo dismm disls beskz plifz eisbe minbe
         bstmi bstma bstrf
    FROM marc
    INTO TABLE gt_marc
    WHERE werks IN s_werks
      AND dispo IN s_dispo
      AND lvorm = ''.

  IF p_mara = 'X' AND gt_mara IS NOT INITIAL.
    DATA: lt_marc_filtered TYPE STANDARD TABLE OF ty_marc.
    LOOP AT gt_marc INTO DATA(ls_marc).
      READ TABLE gt_mara WITH KEY matnr = ls_marc-matnr TRANSPORTING NO FIELDS.
      IF sy-subrc = 0.
        APPEND ls_marc TO lt_marc_filtered.
      ENDIF.
    ENDLOOP.
    gt_marc = lt_marc_filtered.
  ENDIF.

  gv_count = lines( gt_marc ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'MARC_export.csv' INTO gv_filename.
  PERFORM write_marc_csv USING gv_filename.
ENDFORM.

FORM extract_mard.
  WRITE: / 'Extracting MARD...'.
  SELECT matnr werks lgort labst insme einme
    FROM mard
    INTO TABLE gt_mard
    WHERE werks IN s_werks
      AND lvorm = ''.

  IF p_marc = 'X' AND gt_marc IS NOT INITIAL.
    DATA: lt_mard_filtered TYPE STANDARD TABLE OF ty_mard.
    LOOP AT gt_mard INTO DATA(ls_mard).
      READ TABLE gt_marc WITH KEY matnr = ls_mard-matnr
                                  werks = ls_mard-werks
                         TRANSPORTING NO FIELDS.
      IF sy-subrc = 0.
        APPEND ls_mard TO lt_mard_filtered.
      ENDIF.
    ENDLOOP.
    gt_mard = lt_mard_filtered.
  ENDIF.

  gv_count = lines( gt_mard ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'MARD_export.csv' INTO gv_filename.
  PERFORM write_mard_csv USING gv_filename.
ENDFORM.

FORM extract_ekko.
  WRITE: / 'Extracting EKKO...'.
  DATA: lv_cutoff TYPE sy-datum.
  lv_cutoff = sy-datum.
  CALL FUNCTION 'RP_CALC_DATE_IN_INTERVAL'
    EXPORTING
      date      = lv_cutoff
      months    = CONV t5a4a-dlymo( 12 )
      signum    = '-'
      days      = 0
      years     = 0
    IMPORTING
      calc_date = lv_cutoff.

  SELECT ebeln bsart lifnr ekorg bedat waers
    FROM ekko
    INTO TABLE gt_ekko
    WHERE bedat >= lv_cutoff
      AND bstyp = 'F'
      AND loekz = ''.

  gv_count = lines( gt_ekko ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'EKKO_export.csv' INTO gv_filename.
  PERFORM write_ekko_csv USING gv_filename.
ENDFORM.

FORM extract_ekpo.
  WRITE: / 'Extracting EKPO...'.

  DATA: lt_ebeln TYPE TABLE OF ekko-ebeln,
        ls_ebeln TYPE ekko-ebeln.

  IF p_ekko = 'X' AND gt_ekko IS NOT INITIAL.
    LOOP AT gt_ekko INTO DATA(ls_ekko).
      ls_ebeln = ls_ekko-ebeln.
      APPEND ls_ebeln TO lt_ebeln.
    ENDLOOP.
  ENDIF.

  IF lt_ebeln IS NOT INITIAL.
    SELECT p~ebeln p~ebelp p~matnr p~werks p~menge p~meins p~netpr
           t~eindt p~elikz p~loekz
      FROM ekpo AS p
      LEFT OUTER JOIN eket AS t
        ON  t~ebeln = p~ebeln
        AND t~ebelp = p~ebelp
        AND t~etenr = '0001'
      INTO TABLE gt_ekpo
      FOR ALL ENTRIES IN lt_ebeln
      WHERE p~ebeln = lt_ebeln-table_line
        AND p~loekz = ''
        AND p~elikz = ''
        AND p~werks IN s_werks.
  ELSE.
    SELECT p~ebeln p~ebelp p~matnr p~werks p~menge p~meins p~netpr
           t~eindt p~elikz p~loekz
      FROM ekpo AS p
      LEFT OUTER JOIN eket AS t
        ON  t~ebeln = p~ebeln
        AND t~ebelp = p~ebelp
        AND t~etenr = '0001'
      INTO TABLE gt_ekpo
      WHERE p~loekz = ''
        AND p~elikz = ''
        AND p~werks IN s_werks.
  ENDIF.

  gv_count = lines( gt_ekpo ).
  WRITE: / '  ', gv_count, 'records'.
  CONCATENATE p_path 'EKPO_export.csv' INTO gv_filename.
  PERFORM write_ekpo_csv USING gv_filename.
ENDFORM.

FORM extract_mb51.
  WRITE: / 'Extracting MB51 (MSEG+MKPF)...'.

  DATA: lv_cutoff TYPE sy-datum.
  lv_cutoff = sy-datum.
  CALL FUNCTION 'RP_CALC_DATE_IN_INTERVAL'
    EXPORTING
      date      = lv_cutoff
      months    = CONV t5a4a-dlymo( p_months )
      signum    = '-'
      days      = 0
      years     = 0
    IMPORTING
      calc_date = lv_cutoff.

  WRITE: / '  Cutoff date:', lv_cutoff.

  SELECT s~mblnr s~mjahr s~zeile s~matnr s~werks s~lgort s~bwart
         s~menge s~meins s~shkzg h~budat
    FROM mseg AS s
    INNER JOIN mkpf AS h
      ON  h~mblnr = s~mblnr
      AND h~mjahr = s~mjahr
    INTO TABLE gt_mb51
    WHERE h~budat >= lv_cutoff
      AND s~werks IN s_werks
      AND s~bwart IN ('101', '102',
                       '201', '202',
                       '261', '262',
                       '281', '282',
                       '301', '302',
                       '309', '310',
                       '311', '312',
                       '321', '322',
                       '601', '602',
                       '641', '642',
                       '651', '652',
                       '701', '702' ).

  gv_count = lines( gt_mb51 ).
  WRITE: / '  ', gv_count, 'records'.

  CONCATENATE p_path 'MB51_export.csv' INTO gv_filename.
  PERFORM write_mb51_csv USING gv_filename.
ENDFORM.

FORM write_mara_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  APPEND 'MATNR;MTART;MEINS;MATKL;BRGEW;NTGEW;ERSDA;LAEDA' TO lt_csv.

  LOOP AT gt_mara INTO DATA(ls).
    DATA(lv_brgew) = CONV string( ls-brgew ).
    DATA(lv_ntgew) = CONV string( ls-ntgew ).
    CONCATENATE ls-matnr ls-mtart ls-meins ls-matkl
                lv_brgew lv_ntgew ls-ersda ls-laeda
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_brgew, lv_ntgew.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_marc_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  APPEND 'MATNR;WERKS;DISPO;DISMM;DISLS;BESKZ;PLIFZ;EISBE;MINBE;BSTMI;BSTMA;BSTRF;STPRS;PEINH'
    TO lt_csv.

  LOOP AT gt_marc INTO DATA(ls).
    DATA(lv_plifz) = CONV string( ls-plifz ).
    DATA(lv_eisbe) = CONV string( ls-eisbe ).
    DATA(lv_minbe) = CONV string( ls-minbe ).
    DATA(lv_bstmi) = CONV string( ls-bstmi ).
    DATA(lv_bstma) = CONV string( ls-bstma ).
    DATA(lv_bstrf) = CONV string( ls-bstrf ).
    CONCATENATE ls-matnr ls-werks ls-dispo ls-dismm ls-disls
                ls-beskz lv_plifz lv_eisbe lv_minbe lv_bstmi
                lv_bstma lv_bstrf ls-stprs ls-peinh
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_plifz, lv_eisbe, lv_minbe, lv_bstmi, lv_bstma, lv_bstrf.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

FORM write_mard_csv USING p_file TYPE string.
  DATA: lt_csv TYPE TABLE OF string.
  APPEND 'MATNR;WERKS;LGORT;LABST;INSME;EINME;ERSDA' TO lt_csv.

  LOOP AT gt_mard INTO DATA(ls).
    DATA(lv_today) = sy-datum.
    DATA(lv_labst) = CONV string( ls-labst ).
    DATA(lv_insme) = CONV string( ls-insme ).
    DATA(lv_einme) = CONV string( ls-einme ).
    CONCATENATE ls-matnr ls-werks ls-lgort
                lv_labst lv_insme lv_einme lv_today
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_labst, lv_insme, lv_einme.
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
  APPEND 'EBELN;EBELP;MATNR;WERKS;MENGE;MEINS;NETPR;EINDT;ELIKZ;LOEKZ'
    TO lt_csv.

  LOOP AT gt_ekpo INTO DATA(ls).
    DATA(lv_menge) = CONV string( |{ ls-menge DECIMALS = 0 }| ).
    DATA(lv_netpr) = CONV string( ls-netpr ).
    CONCATENATE ls-ebeln ls-ebelp ls-matnr ls-werks lv_menge ls-meins
                lv_netpr ls-eindt ls-elikz ls-loekz
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_menge, lv_netpr.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.
ENDFORM.

*&---------------------------------------------------------------------*
*& Form WRITE_MB51_CSV
*& FIXED v1.1 — uses SHKZG for sign instead of forcing negative
*&   SHKZG = 'S' (Soll/Debit)   → goods receipt → POSITIVE
*&   SHKZG = 'H' (Haben/Credit) → goods issue   → NEGATIVE
*&---------------------------------------------------------------------*
FORM write_mb51_csv USING p_file TYPE string.

  DATA: lt_csv     TYPE TABLE OF string,
        lv_menge   TYPE string,
        lv_signed  TYPE p DECIMALS 3.

  APPEND 'MBLNR;MJAHR;ZEILE;MATNR;WERKS;LGORT;BWART;MENGE;MEINS;BUDAT'
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
                ls-bwart lv_menge ls-meins ls-budat
           INTO gv_csv_line SEPARATED BY ';'.
    APPEND gv_csv_line TO lt_csv.
    CLEAR: lv_menge, lv_signed.
  ENDLOOP.

  PERFORM write_file USING p_file lt_csv.

ENDFORM.

FORM write_file USING p_file TYPE string
                      pt_data TYPE STANDARD TABLE.
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
      WRITE: / '  ERROR writing', p_file, '— code', sy-subrc.
    ELSE.
      WRITE: / '  Saved:', p_file.
    ENDIF.
  ENDIF.
ENDFORM.
