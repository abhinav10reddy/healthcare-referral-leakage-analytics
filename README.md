# Healthcare Referral Leakage Analytics

An end-to-end analytics project that follows specialist referrals from creation through
contact, scheduling and appointment outcome to show where referrals are lost. It covers
referral leakage, delays, cancellations, no-shows, duplicates and data-quality gaps across
service categories, facilities and patient segments. The project uses Python, Pandas, SQL
(SQLite) and Power BI.

> **Synthetic data and non-clinical use notice**
>
> Every record in this project is **fully synthetic and fictional**. It is produced by a
> seeded random-number generator and contains no real patient information, medical
> records or external healthcare datasets. Patients have no names, contact details,
> addresses, diagnoses or clinical notes. Facility and provider names are invented, and
> any resemblance to real organisations or people is coincidental. All rates and
> benchmarks are illustrative generator settings, not real-world statistics.
>
> This project is for **portfolio and educational use only**. It must not be used for
> clinical decision-making, patient care or real operational decisions.

## Project objectives

- Generate a realistic, reproducible synthetic referral dataset of 150,000 referral records.
- Clean and validate the raw data and load it into a SQLite database.
- Define transparent rules for referral leakage, delays and operational exceptions.
- Calculate referral conversion, turnaround times and leakage points with SQL and Python,
  and reconcile the KPIs between the two.
- Present the results in a Power BI dashboard for process-improvement discussions.

## Technology stack

| Area | Tools |
| --- | --- |
| Data generation and cleaning | Python 3.12, Pandas, NumPy |
| Database and analytics | SQL, SQLite |
| Dashboard | Power BI Desktop (DAX) |
| Testing | pytest |

## Project phases

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Project setup and deterministic synthetic-data generator | Complete |
| 2 | Data cleaning, validation and SQLite pipeline | Complete |
| 3 | Referral-leakage rules, SQL analytics and KPI reconciliation | Planned |
| 4 | Power BI data package, DAX measures, theme, build guide and dashboard | Planned |
| 5 | Final testing, screenshots, documentation and GitHub QA | Planned |

## Synthetic data model

The generator writes six raw CSV files. Identifiers are stable text codes.

```
service_categories (SVC###) ─┐
facilities (FAC###) ─────────┼─< providers (PRV###)
                             │
patients (PAT######) ────────┴─< referrals (REF#######) ─< appointments (APT#######)
```

- Each provider belongs to one facility and one service category.
- Each referral names a patient, a service category, a receiving facility and a receiving
  provider who works at that facility in that service category.
- A referral can have zero, one or several appointments. Several appointments happen when
  an appointment is rescheduled, or when a cancellation or no-show is rebooked.
- Appointments always reference a valid referral ID.
- Referrals sent to out-of-network facilities leave the system and have no appointments.
  Some return a confirmed outcome; the rest have no recorded outcome.

### Reporting period

- Referral dates fall within the reporting year **2025-01-01 to 2025-12-31**.
- Follow-up activity (contact, booking, appointments, closure) is captured up to the
  **data extract date of 2026-01-31**, so late-year referrals can still show progress.
- Appointments booked on or before the extract date for a later date have the status
  `Scheduled`.
- A referral that is not booked within 90 days expires.

### Referral lifecycle

| referral_status | Meaning |
| --- | --- |
| Completed | An appointment was completed |
| Scheduled | An appointment is booked after the extract date |
| Pending | Open, awaiting contact, booking or rebooking |
| Declined | The patient declined or chose another provider |
| Cancelled | The last appointment was cancelled or missed and not rebooked |
| Expired | Not booked within the 90-day referral window |
| Sent External | Referred to an out-of-network facility |

Appointment statuses are `Completed`, `Cancelled`, `No-Show`, `Rescheduled` and `Scheduled`.

### Controlled data-quality issues

A small, fixed share of rows contains deliberate problems for Phase 2 to detect and clean.
The rates are set in `config.py`. Most rows are valid, and the generator never creates
impossible foreign keys or malformed CSV rows.

| Issue | Rate | How it appears |
| --- | --- | --- |
| Duplicate referral ID | 1.5% of referral rows | Exact copy of a referral's business fields with a new `referral_record_id` |
| Missing referral source | 2.0% of unique referrals | `referral_source` is blank |
| Missing receiving facility | 1.0% of unique referrals | `receiving_facility_id` is blank (the provider is still recorded) |
| Missing first-contact date | 1.5% of unique referrals | Blank although the referral has an appointment or was declined |
| Missing closure date | 1.0% of unique referrals | Closure reason recorded but `closed_date` is blank |
| Inconsistent closure | 0.5% of unique referrals | `Pending` or `Scheduled` referral with a `closed_date` |

Some fields are blank by design rather than through data-quality issues. For example,
`first_contact_date` is blank when a patient was never reached, `closure_reason` and
`closed_date` are blank for open referrals, and `status_reason` is filled only for
cancelled or rescheduled appointments.

## Setup and data generation (Windows PowerShell)

Run these commands from the project folder. They need Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Generate the default dataset of 150,000 referral rows with seed 42:

```powershell
.\.venv\Scripts\python.exe generate_data.py
```

Or set the referral count and seed explicitly:

```powershell
.\.venv\Scripts\python.exe generate_data.py --referrals 150000 --seed 42
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `--referrals` | 150000 | Rows in `referrals.csv`, including duplicate rows (1 to 1,000,000) |
| `--seed` | 42 | Random seed; the same seed gives byte-identical files |
| `--output-dir` | `data\raw` | Folder for the generated CSV files |

The generator prints the output folder, the seed, the reporting period and the row count
for every file. Generating 150,000 referrals takes about 15 seconds. Generated data files
are ignored by Git and can be recreated at any time.

## Generated files

All files are written to `data\raw` as UTF-8 CSV with `\n` line endings. Dates use
`YYYY-MM-DD`, date-times use `YYYY-MM-DD HH:MM:SS`, and missing values are empty fields.

| File | Rows (default run) | Description |
| --- | --- | --- |
| `service_categories.csv` | 8 | Service categories, service line and an illustrative target days to appointment |
| `facilities.csv` | 12 | Fictional facilities with type, region and network status (10 in-network, 2 out-of-network) |
| `providers.csv` | 132 | Fictional providers with provider type, facility and service category |
| `patients.csv` | 60,000 | Age group, gender, insurance type and home region only |
| `referrals.csv` | 150,000 | One row per referral record, including controlled duplicates (147,750 unique referral IDs) |
| `appointments.csv` | 128,718 | Appointment attempts per referral, with booking date, appointment date-time, status and reason |

### Referral columns

| Column | Description |
| --- | --- |
| `referral_record_id` | Unique row identifier, also unique across duplicate rows |
| `referral_id` | Business referral identifier (repeated on duplicate rows) |
| `patient_id`, `service_category_id` | Patient and requested service |
| `receiving_facility_id`, `receiving_provider_id` | Destination facility and provider |
| `referral_source` | Primary Care, Specialist, Emergency Department, Hospital Discharge, Urgent Care or Patient Portal |
| `urgency` | Routine, Urgent or Stat |
| `referral_date`, `first_contact_date` | Referral creation date and first successful patient contact |
| `referral_status`, `closure_reason`, `closed_date` | Status on the extract date and closure details |

### Appointment columns

| Column | Description |
| --- | --- |
| `appointment_id`, `referral_id`, `appointment_sequence` | Appointment identifier, referral and attempt number (1, 2, ...) |
| `facility_id`, `provider_id` | Where and with whom the appointment was booked |
| `booked_date`, `appointment_datetime` | When it was booked and when it was planned to take place |
| `appointment_status`, `status_reason` | Outcome, plus the reason for cancellations and reschedules |

## Data preparation (Phase 2)

Phase 2 validates the raw files, cleans the controlled data-quality issues, and builds a
SQLite database for analysis. Run it after generating the raw data:

```powershell
.\.venv\Scripts\python.exe prepare_data.py
```

If the raw files are missing, the script stops and shows the generation command. The
`--raw-dir`, `--processed-dir` and `--output-dir` options change the input and output
folders. They default to `data\raw`, `data\processed` and `data\output`.

The pipeline works in this order:

1. **Load:** read the six raw CSVs as text and enforce a strict schema. A missing column
   or an unexpected extra column stops the run.
2. **Standardize:** trim whitespace, treat blank text as missing, and normalize dates to
   `YYYY-MM-DD` and date-times to `YYYY-MM-DD HH:MM:SS`. Raw dates may use `-` or `/`;
   any other date format is rejected.
3. **Validate:** run 35 structural checks covering:
   - required values, identifier formats and unique keys;
   - the duplicate design (at most two identical rows per referral ID);
   - foreign keys and provider–facility–service consistency;
   - allowed category values and numeric ranges;
   - reporting-year and extract-date limits, date ordering and appointment journeys;
   - status and closure consistency.

   Any failure is a **fatal structural error**. The run stops, exits with code 1, and
   writes a failed JSON report. The previous successful CSVs and database are left
   unchanged.
4. **Clean:** apply the rules below and record every controlled issue as an exception.
5. **Publish:** build all outputs in a temporary folder inside `data\output`, create the
   database from `sql\01_create_schema.sql`, and check foreign keys and row counts.
   Only then are the outputs moved into place.

### Cleaning rules

| Issue | Rule | Exception status |
| --- | --- | --- |
| Leading or trailing whitespace | Trimmed | Resolved |
| Non-ISO date format (e.g. `2025/03/05`) | Normalized to ISO | Resolved |
| Duplicate referral ID | Keep the row with the smallest `referral_record_id`; log each removed row | Resolved |
| Blank referral source | Replaced with `Unknown` | Unresolved (true source unknown) |
| Blank receiving facility | Inferred from the receiving provider's facility when it is unambiguous; otherwise left blank | Resolved, or Unresolved if not inferred |
| Blank first-contact date where an appointment or decline proves contact | Kept blank; no date is invented | Unresolved |
| Closure reason without a closed date | Kept blank; closure reason retained | Unresolved |
| Open referral (`Pending`/`Scheduled`) with a closed date | Closed date cleared | Resolved |

Some blanks are part of the design and are kept without being flagged:
- patients who were never contacted;
- open referrals with no closure details;
- `status_reason` on appointments that were not cancelled or rescheduled.

### Data-quality exceptions

`data_quality_exceptions.csv` has one row per detected issue, with these columns:

| Column | Description |
| --- | --- |
| `exception_id` | Stable ID (`DQE0000001`, ...) |
| `entity_type` | Kind of record the issue was found on |
| `record_id` | Raw row identifier (for referrals, the `referral_record_id`) |
| `referral_id` | Related referral ID |
| `issue_type` | What was wrong |
| `field_name` | Affected field |
| `original_value` | Value before cleaning |
| `cleaned_value` | Value after cleaning |
| `action_taken` | Cleaning action applied |
| `resolution_status` | `Resolved` or `Unresolved` |

Processed referrals carry three summary fields:
- `duplicate_record_count`: duplicate rows removed for that referral;
- `data_quality_issue_count`: number of exceptions linked to the referral;
- `has_data_quality_issue`: 1 if the referral has any exceptions, otherwise 0.

These support data-quality analysis in Power BI later. Phase 2 does not add leakage flags
or KPIs; those are defined in Phase 3.

### Phase 2 outputs (default run)

| Output | Rows | Description |
| --- | --- | --- |
| `data\processed\service_categories.csv` | 8 | Validated master data |
| `data\processed\facilities.csv` | 12 | Validated master data |
| `data\processed\providers.csv` | 132 | Validated master data |
| `data\processed\patients.csv` | 60,000 | Validated master data |
| `data\processed\referrals.csv` | 147,750 | One row per unique referral ID; raw columns plus the three data-quality fields |
| `data\processed\appointments.csv` | 128,718 | Validated appointments plus a derived `appointment_date` |
| `data\processed\data_quality_exceptions.csv` | 11,116 | One row per detected data-quality issue |
| `data\output\healthcare_referrals.db` | 7 tables | SQLite database with the same seven tables |
| `data\output\phase2_data_quality.json` | — | Validation and data-quality report |

The default run removes 2,250 duplicate rows. It records these exceptions:

| Exception | Count |
| --- | --- |
| Duplicate referral row removed | 2,250 |
| Referral source replaced with `Unknown` | 2,955 |
| Receiving facility inferred from provider | 1,478 |
| First-contact date kept blank | 2,216 |
| Closed date kept blank | 1,478 |
| Closed date cleared on open referral | 739 |

These counts match the generator's configured data-quality targets, and the run reports
no structural violations.

### SQLite database

- **Schema:** `sql\01_create_schema.sql` drops and recreates the seven tables, so it is
  safe to rerun.
- **Keys:** foreign keys are enabled. Every table has a primary key, and the schema adds
  unique constraints such as `referral_record_id` and (`referral_id`,
  `appointment_sequence`).
- **CHECK constraints:** these cover allowed category values, 0/1 flags and date order,
  and require that open referrals have no closed date after cleaning.
- **Indexes:** these cover referral date, status, service category, facility, provider,
  patient, source and urgency, plus appointment referral, status, date, facility and
  provider.
- **Types:** identifiers, categories and ISO dates are TEXT; counts and flags are INTEGER.
- **Post-load checks:** after loading, the pipeline confirms `PRAGMA foreign_key_check`
  returns no rows, `PRAGMA integrity_check` returns `ok`, and every table's row count
  matches its processed CSV.

Phase 3 analytical views are not created yet.

### JSON report

`phase2_data_quality.json` contains:
- the pipeline status;
- the synthetic-data and non-clinical-use notice;
- the reporting period and extract date;
- input and output row counts and duplicate counts;
- missing values per approved field, before and after cleaning, separating flagged
  exceptions from legitimate blanks;
- cleaning actions and exception counts, including unresolved exceptions;
- a reconciliation against the generator's data-quality targets;
- every validation check and its result;
- referral and appointment status counts;
- database row counts and the foreign-key check result.

The report contains no timestamps or machine-specific paths.

### Deterministic rebuilds

Running `prepare_data.py` again on unchanged raw data produces byte-identical processed
CSVs and an identical JSON report. The database is rebuilt from scratch with identical
table contents. Outputs use stable sort orders, UTF-8, `\n` line endings, and empty fields
for missing values.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests generate data in temporary folders and do not use files in `data\raw`.

- **Phase 1 tests** check:
  - files, columns and row counts, including a full 150,000-row run;
  - identifier uniqueness, and duplicate and missing-value rates;
  - foreign keys and provider–facility–service consistency;
  - date ranges and ordering, and appointment status sequences;
  - deterministic output, privacy rules, command-line validation and Git ignore rules.
- **Phase 2 tests** check:
  - that each kind of structural problem is rejected;
  - that a failed run writes a failed report and keeps the previous outputs;
  - every cleaning rule, plus exception IDs and reconciliation with the report;
  - processed columns and row counts;
  - SQLite tables, keys, indexes and constraints, and the foreign-key check;
  - byte-identical reruns;
  - a full run on the standard 150,000-row dataset.

## Repository structure

```
healthcare-referral-leakage-analytics/
├── config.py              # Settings: period, seed, categories, rates, paths
├── generate_data.py       # Phase 1: command-line synthetic data generator
├── prepare_data.py        # Phase 2: validation, cleaning and SQLite pipeline
├── requirements.txt       # Pinned Python dependencies
├── data/
│   ├── raw/               # Generated raw CSV files (ignored by Git)
│   ├── processed/         # Cleaned CSVs and data-quality exceptions (ignored by Git)
│   └── output/            # SQLite database and JSON report (ignored by Git)
├── sql/
│   └── 01_create_schema.sql  # SQLite schema: tables, keys, checks and indexes
├── powerbi/               # Power BI files (Phase 4)
├── screenshots/           # Dashboard screenshots (Phase 5)
└── tests/
    ├── conftest.py
    ├── test_generate_data.py
    └── test_prepare_data.py
```

## Current limitations

- The data is synthetic. Distributions, rates and wait times are illustrative settings
  chosen for analysis practice and do not represent any real healthcare system.
- Phases 1 and 2 are complete. Leakage rules, KPIs, analytical SQL views and the Power BI
  dashboard are planned for later phases.
- Phase 2 validation is strict and tailored to this synthetic schema. Unexpected columns,
  values or date formats stop the run rather than being guessed at.
- Missing first-contact and closed dates are flagged but never filled in, so time-based
  measures in later phases must handle these blanks.
- Outputs are replaced one file at a time after a successful build. If the database file
  is open in another program, Windows may refuse the replacement; the run then reports a
  failure.
- A full Phase 2 run on 150,000 referral records takes about 30 seconds.
- Byte-identical output is guaranteed only with the same seed and the same Python, NumPy
  and Pandas versions as in `requirements.txt`.
- Outcomes of out-of-network referrals are simplified: no appointments are recorded, and
  the outcome is either a confirmed external visit or missing.
- Patient attributes are limited to age group, gender, insurance type and home region.
  There are no clinical details, so the data cannot support clinical analysis.
