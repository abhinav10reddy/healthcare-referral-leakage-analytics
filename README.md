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
| 2 | Data cleaning, validation and SQLite pipeline | Planned |
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

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests generate data in temporary folders and do not use files in `data\raw`. They
check the files and columns, row counts (including a full 150,000-row run), identifier
uniqueness, duplicate and missing-value rates, foreign keys, provider–facility–service
consistency, date ranges and ordering, appointment status sequences, deterministic output,
privacy rules, command-line validation and Git ignore rules.

## Repository structure

```
healthcare-referral-leakage-analytics/
├── config.py              # Generator settings: period, seed, categories, rates, paths
├── generate_data.py       # Command-line synthetic data generator
├── requirements.txt       # Pinned Python dependencies
├── data/
│   ├── raw/               # Generated raw CSV files (ignored by Git)
│   ├── processed/         # Phase 2 cleaned data (ignored by Git)
│   └── output/            # Later analytical outputs (ignored by Git)
├── sql/                   # SQL scripts (Phase 2 onwards)
├── powerbi/               # Power BI files (Phase 4)
├── screenshots/           # Dashboard screenshots (Phase 5)
└── tests/
    ├── conftest.py
    └── test_generate_data.py
```

## Current limitations

- The data is synthetic. Distributions, rates and wait times are illustrative settings
  chosen for analysis practice and do not represent any real healthcare system.
- Only Phase 1 is complete. Cleaning, the SQLite pipeline, leakage rules, KPIs and the
  Power BI dashboard are planned for later phases.
- Byte-identical output is guaranteed only with the same seed and the same Python, NumPy
  and Pandas versions as in `requirements.txt`.
- Outcomes of out-of-network referrals are simplified: no appointments are recorded, and
  the outcome is either a confirmed external visit or missing.
- Patient attributes are limited to age group, gender, insurance type and home region.
  There are no clinical details, so the data cannot support clinical analysis.
