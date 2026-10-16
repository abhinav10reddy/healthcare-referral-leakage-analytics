# Power BI Data Dictionary

> **Synthetic data only.** Every value is computer-generated. Nothing describes real
> patients, providers or facilities. This data is for portfolio and educational use only,
> not for clinical decision-making.

These six CSV files in `powerbi/data/` are the Power BI snapshot. `prepare_powerbi_data.py`
writes them from the validated Phase 2 database and the Phase 3 SQL views.

All files share these formats:
- **Encoding:** UTF-8, comma-separated, `\n` line endings.
- **Dates:** ISO `YYYY-MM-DD`.
- **Flags:** `0` or `1`.
- **Missing values:** empty fields. These load as blanks in Power BI.

The model is described in [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md).

## Referrals (`referral_journey.csv`)

This is the fact table, with one row per processed referral: 147,750 rows with seed 42.

- **Source:** `vw_referral_journey`.
- **Excluded columns:** the patient identifier and the other journey columns (the
  appointment summary, closure details and data-quality IDs). The dashboard does not
  use them.
- **Flags:** every flag was calculated in SQL and uses the definitions in
  [sql/KPI_DEFINITIONS.md](../sql/KPI_DEFINITIONS.md).

| Column | Power BI type | Source column (`vw_referral_journey`) | Description | Blank when |
|---|---|---|---|---|
| `referral_id` | Text | `referral_id` | Business referral ID (key) | never |
| `referral_date` | Date | `referral_date` | Date the referral was created; relates to `Date[date]` | never |
| `provider_id` | Text | `receiving_provider_id` | Receiving provider; relates to `Providers[provider_id]` | never |
| `referral_source` | Text | `referral_source` | Primary Care, Specialist, Emergency Department, Hospital Discharge, Urgent Care, Patient Portal or Unknown | never |
| `urgency` | Text | `urgency` | Routine, Urgent or Stat | never |
| `insurance_type` | Text | `insurance_type` | Commercial, Medicaid, Medicare or Self-Pay | never |
| `age_group` | Text | `age_group` | Patient age band (0-17 … 75+) | never |
| `gender` | Text | `gender` | Female, Male or Unknown | never |
| `referral_status` | Text | `referral_status` | Status on the extract date | never |
| `outcome` | Text | `outcome_category` | Converted, Active, Leaked or Unclassified | never |
| `primary_leakage_reason` | Text | `primary_leakage_reason` | One of the six leakage reasons | not leaked |
| `leakage_reason_priority` | Whole number | `vw_leakage_reasons.priority` | Sort order for `primary_leakage_reason` (1–6) | not leaked |
| `contacted_flag` | Whole number | `contacted_flag` | Contact recorded or evidenced | never |
| `scheduled_flag` | Whole number | `scheduled_flag` | At least one appointment record | never |
| `completed_flag` | Whole number | `completed_flag` | At least one Completed appointment | never |
| `confirmed_external_outcome_flag` | Whole number | `confirmed_external_outcome_flag` | Sent External with a confirmed visit | never |
| `converted_flag` | Whole number | `converted_flag` | Completed or confirmed external | never |
| `active_flag` | Whole number | `active_in_progress_flag` | Still legitimately open | never |
| `leakage_flag` | Whole number | `leakage_flag` | Leaked | never |
| `had_cancellation_flag` | Whole number | `had_cancellation_flag` | At least one Cancelled appointment | never |
| `had_no_show_flag` | Whole number | `had_no_show_flag` | At least one No-Show appointment | never |
| `delayed_scheduling_flag` | Whole number | `delayed_schedule_flag` | First booking more than 30 days after referral | never |
| `delayed_appointment_flag` | Whole number | `delayed_appointment_flag` | First appointment later than the category target | never |
| `first_contact_date` | Date | `first_contact_date` | First successful contact | never contacted, or flagged missing in Phase 2 |
| `first_booking_date` | Date | `first_booking_date` | Earliest appointment booking | no appointment |
| `first_appointment_date` | Date | `first_appointment_date` | Date of the first appointment slot | no appointment |
| `days_to_first_contact` | Whole number | `days_to_first_contact` | `first_contact_date` − `referral_date` | `first_contact_date` blank |
| `days_to_schedule` | Whole number | `days_to_schedule` | `first_booking_date` − `referral_date` | no appointment |
| `days_to_first_appointment` | Whole number | `days_to_first_appointment` | `first_appointment_date` − `referral_date` | no appointment |
| `duplicate_record_count` | Whole number | `duplicate_record_count` | Duplicate raw rows removed in Phase 2 | never |
| `data_quality_issue_count` | Whole number | `data_quality_issue_count` | Phase 2 exceptions linked to the referral | never |
| `has_data_quality_issue` | Whole number | `has_data_quality_issue` | 1 if `data_quality_issue_count` > 0 | never |

`first_contact_date`, `first_booking_date` and `first_appointment_date` are plain date
columns with no relationship to the Date table. Some fall in 2026, after the reporting
year. Durations are blank, never 0, when a date is missing.

## DataQualityExceptions (`data_quality_exceptions.csv`)

One row per Phase 2 data-quality exception: 11,116 rows with seed 42. The source is the
Phase 2 table `data_quality_exceptions`. The original and cleaned values are left out,
because the dashboard does not need them.

| Column | Power BI type | Description |
|---|---|---|
| `exception_id` | Text | Exception ID (key) |
| `referral_id` | Text | Related referral; relates to `Referrals[referral_id]`. Blank only for exceptions on master records (none with seed 42) |
| `entity_type` | Text | Record type the issue was found on (`referral` for every seed-42 row) |
| `issue_type` | Text | Phase 2 issue code, such as `missing_referral_source` |
| `issue_label` | Text | Readable label for charts, such as *Missing referral source* |
| `field_name` | Text | Affected field |
| `resolution_status` | Text | Resolved or Unresolved |

Each `issue_type` code maps to one label:

| `issue_type` | `issue_label` |
|---|---|
| `extra_whitespace` | Extra whitespace |
| `nonstandard_date_format` | Non-standard date format |
| `duplicate_referral_record` | Duplicate referral record |
| `missing_referral_source` | Missing referral source |
| `missing_receiving_facility` | Missing receiving facility |
| `missing_first_contact_date` | Missing first-contact date |
| `missing_closed_date` | Missing closed date |
| `open_referral_with_closed_date` | Open referral with closed date |

## ServiceCategories (`service_categories.csv`)

| Column | Power BI type | Description |
|---|---|---|
| `service_category_id` | Text | Key (SVC001 …) |
| `service_category_name` | Text | Cardiology, Orthopedics, … |
| `service_line` | Text | Medical Specialty, Surgical Specialty, Rehabilitation, Behavioral Health |
| `target_days_to_appointment` | Whole number | Illustrative synthetic target used by the delayed-appointment flag |

## Facilities (`facilities.csv`)

| Column | Power BI type | Description |
|---|---|---|
| `facility_id` | Text | Key (FAC001 …) |
| `facility_name` | Text | Fictional facility name |
| `facility_type` | Text | Hospital, Specialty Clinic, … |
| `region` | Text | North, South, East, West, Central |
| `network_status` | Text | In-Network or Out-of-Network |

## Providers (`providers.csv`)

| Column | Power BI type | Description |
|---|---|---|
| `provider_id` | Text | Key (PRV001 …) |
| `provider_name` | Text | Fictional label, such as *Cardiology Provider 001* |
| `provider_type` | Text | Physician, Advanced Practice Provider or Therapist |
| `facility_id` | Text | Facility the provider works at; relates to `Facilities[facility_id]` |
| `service_category_id` | Text | Service the provider offers; relates to `ServiceCategories[service_category_id]` |

## Date (`date.csv`)

One row per calendar day, covering every complete year that contains a referral date:
2025-01-01 to 2025-12-31 (365 rows) with seed 42.

| Column | Power BI type | Example | Notes |
|---|---|---|---|
| `date` | Date | 2025-01-01 | Key; mark the table as a date table on this column |
| `year` | Whole number | 2025 | |
| `quarter_number` | Whole number | 1 | Sort column for `quarter_label` |
| `quarter_label` | Text | Q1 | |
| `month_number` | Whole number | 1 | Sort column for `month_name` |
| `month_name` | Text | January | |
| `year_month` | Text | Jan 2025 | Axis label; sort by `year_month_sort` |
| `year_month_sort` | Whole number | 202501 | `year × 100 + month` |
| `week_number` | Whole number | 1 | ISO 8601 week. 29–31 Dec 2025 belong to ISO week 1 of 2026 |
| `day_of_month` | Whole number | 1 | |
| `weekday_number` | Whole number | 3 | Monday = 1 … Sunday = 7; sort column for `weekday_name` |
| `weekday_name` | Text | Wednesday | |
| `is_weekend` | Whole number | 0 | 1 for Saturday and Sunday |

## Not included

The snapshot leaves out three kinds of data:
- **Patient identifiers:** no patient ID or patient table. Age group, gender and
  insurance type are kept as columns on Referrals for filtering, and no names, addresses,
  emails or phone numbers exist anywhere in the project.
- **Appointment rows:** every appointment measure the dashboard needs is already
  summarized per referral.
- **Raw values in the exception table:** the original and cleaned values.
