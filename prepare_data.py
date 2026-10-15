"""Validate, clean and load the synthetic referral data into SQLite (Phase 2).

Steps
  1. Load the six raw CSV files from data/raw as text.
  2. Standardize: trim whitespace, turn blanks into missing values and
     normalize dates to ISO format.
  3. Validate structure and relationships. Any structural error stops the run.
  4. Clean the controlled data-quality issues and record every one of them in
     data_quality_exceptions.csv.
  5. Write processed CSVs, build the SQLite database and write a JSON
     data-quality report. Outputs are built in a temporary folder and only
     replace the previous outputs after everything has succeeded.

All data is fully synthetic and for portfolio and educational use only, not
for clinical decision-making. Leakage rules and KPIs belong to Phase 3.

Usage (PowerShell, from the project folder):
    .\\.venv\\Scripts\\python.exe prepare_data.py
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import config
from generate_data import COLUMNS as RAW_COLUMNS
from generate_data import OUTPUT_FILES as RAW_FILES
from generate_data import SYNTHETIC_DATA_NOTICE, data_quality_counts

GENERATE_COMMAND = r".\.venv\Scripts\python.exe generate_data.py --referrals 150000 --seed 42"

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# Accepted raw formats; everything else is a malformed date and stops the run.
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%Y/%m/%d"]
DATETIME_INPUT_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                          "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"]
DATE_COLUMNS = {
    "referrals": ["referral_date", "first_contact_date", "closed_date"],
    "appointments": ["booked_date"],
}
DATETIME_COLUMNS = {"appointments": ["appointment_datetime"]}

TABLE_NAMES = list(RAW_FILES)  # service_categories, facilities, providers, patients, referrals, appointments
ENTITY_TYPES = {
    "service_categories": "service_category", "facilities": "facility", "providers": "provider",
    "patients": "patient", "referrals": "referral", "appointments": "appointment",
}
# Row identifier of each raw table (referral_id is a business ID that may repeat).
RECORD_KEYS = {
    "service_categories": "service_category_id", "facilities": "facility_id",
    "providers": "provider_id", "patients": "patient_id",
    "referrals": "referral_record_id", "appointments": "appointment_id",
}
ID_PATTERNS = {
    "service_category_id": r"SVC\d{3,}", "facility_id": r"FAC\d{3,}", "provider_id": r"PRV\d{3,}",
    "patient_id": r"PAT\d{6,}", "referral_record_id": r"REC\d{7,}", "referral_id": r"REF\d{7,}",
    "appointment_id": r"APT\d{7,}", "receiving_facility_id": r"FAC\d{3,}",
    "receiving_provider_id": r"PRV\d{3,}",
}

# Fields allowed to be blank in the raw data. Every other field is required.
# These are the controlled issues in config.DATA_QUALITY_RATES plus blanks that
# are part of the design (never contacted, still open, no reason applicable).
NULLABLE_COLUMNS = {
    "referrals": {"referral_source", "receiving_facility_id", "first_contact_date",
                  "closure_reason", "closed_date"},
    "appointments": {"status_reason"},
}

OPEN_STATUSES = ["Pending", "Scheduled"]
# Closure reasons allowed for each referral status (None = blank).
CLOSURE_REASONS_BY_STATUS = {
    "Completed": {"Appointment Completed"},
    "Declined": {"Patient Declined", "Chose Other Provider"},
    "Cancelled": {"Appointment Cancelled - Not Rebooked", "No-Show - Not Rebooked"},
    "Expired": {"Referral Expired"},
    "Sent External": {"External Visit Confirmed", None},
    "Pending": {None},
    "Scheduled": {None},
}
UNKNOWN_SOURCE = "Unknown"

PROCESSED_COLUMNS = {
    "service_categories": RAW_COLUMNS["service_categories"],
    "facilities": RAW_COLUMNS["facilities"],
    "providers": RAW_COLUMNS["providers"],
    "patients": RAW_COLUMNS["patients"],
    "referrals": [
        "referral_id", "referral_record_id", "patient_id", "service_category_id",
        "receiving_facility_id", "receiving_provider_id", "referral_source", "urgency",
        "referral_date", "first_contact_date", "referral_status", "closure_reason",
        "closed_date", "duplicate_record_count", "data_quality_issue_count",
        "has_data_quality_issue",
    ],
    "appointments": [
        "appointment_id", "referral_id", "appointment_sequence", "facility_id", "provider_id",
        "booked_date", "appointment_datetime", "appointment_date", "appointment_status",
        "status_reason",
    ],
    "data_quality_exceptions": [
        "exception_id", "entity_type", "record_id", "referral_id", "issue_type", "field_name",
        "original_value", "cleaned_value", "action_taken", "resolution_status",
    ],
}
PROCESSED_FILES = {name: f"{name}.csv" for name in PROCESSED_COLUMNS}
PROCESSED_FILES["data_quality_exceptions"] = config.DATA_QUALITY_EXCEPTIONS_FILE
SORT_KEYS = {
    "service_categories": "service_category_id", "facilities": "facility_id",
    "providers": "provider_id", "patients": "patient_id", "referrals": "referral_id",
    "appointments": "appointment_id", "data_quality_exceptions": "exception_id",
}
INTEGER_COLUMNS = {
    "service_categories": ["target_days_to_appointment"],
    "appointments": ["appointment_sequence"],
}

# Issue types in the order the cleaning rules are applied.
ISSUE_TYPES = [
    "extra_whitespace",
    "nonstandard_date_format",
    "duplicate_referral_record",
    "missing_referral_source",
    "missing_receiving_facility",
    "missing_first_contact_date",
    "missing_closed_date",
    "open_referral_with_closed_date",
]
# Generator data-quality settings that each Phase 2 issue type corresponds to.
GENERATOR_ISSUES = {
    "duplicate_referral_record": "duplicate_referral_id",
    "missing_referral_source": "missing_referral_source",
    "missing_receiving_facility": "missing_receiving_facility",
    "missing_first_contact_date": "missing_first_contact_date",
    "missing_closed_date": "missing_closed_date",
    "open_referral_with_closed_date": "inconsistent_closed_date",
}


class PipelineError(Exception):
    """A structural problem that stops the pipeline."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def display_path(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def add_check(checks, name, description, violations):
    """Record one validation check. `violations` is a list of offending identifiers."""
    violations = sorted({str(value) for value in violations})
    checks.append({
        "check": name,
        "description": description,
        "status": "failed" if violations else "passed",
        "violation_count": len(violations),
        "examples": violations[:5],
    })


def failed_checks(checks):
    return [check for check in checks if check["status"] == "failed"]


def stop_if_failed(checks, stage):
    failures = failed_checks(checks)
    if failures:
        lines = [f"{stage} failed:"]
        for check in failures:
            examples = ", ".join(check["examples"])
            lines.append(f"  - {check['check']}: {check['description']} "
                         f"({check['violation_count']} violation(s); e.g. {examples})")
        raise PipelineError("\n".join(lines))


def to_dates(series, fmt=DATE_FORMAT):
    return pd.to_datetime(series, format=fmt)


def make_exceptions(entity_type, record_ids, referral_ids, issue_type, field_name,
                    original_values, cleaned_values, action_taken, resolution_status):
    """Build exception rows; every argument is a scalar or a list of equal length."""
    record_ids = list(record_ids)
    count = len(record_ids)

    def as_list(values):
        if isinstance(values, (pd.Series, np.ndarray, list)):
            return [None if pd.isna(value) else value for value in list(values)]
        return [values] * count

    return pd.DataFrame({
        "entity_type": [entity_type] * count,
        "record_id": record_ids,
        "referral_id": as_list(referral_ids),
        "issue_type": [issue_type] * count,
        "field_name": as_list(field_name),
        "original_value": as_list(original_values),
        "cleaned_value": as_list(cleaned_values),
        "action_taken": as_list(action_taken),
        "resolution_status": as_list(resolution_status),
    })


# ---------------------------------------------------------------------------
# Step 1: load raw files
# ---------------------------------------------------------------------------
def load_raw_tables(raw_dir, checks):
    """Read every raw CSV as text and check the files and columns."""
    missing_files = [name for name in RAW_FILES.values() if not (raw_dir / name).is_file()]
    add_check(checks, "raw_files_exist", "All six raw CSV files exist", missing_files)
    if missing_files:
        raise PipelineError(
            f"Raw file(s) not found in {display_path(raw_dir)}: {', '.join(missing_files)}.\n"
            f"Generate the raw data first with:\n  {GENERATE_COMMAND}")

    tables, unreadable = {}, []
    for name, file_name in RAW_FILES.items():
        try:
            tables[name] = pd.read_csv(raw_dir / file_name, dtype=str, keep_default_na=False,
                                       na_filter=False, encoding="utf-8-sig")
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as error:
            unreadable.append(f"{file_name}: {error}")
    add_check(checks, "raw_files_readable", "Every raw file is a readable CSV with a header", unreadable)
    stop_if_failed(checks, "Raw file loading")

    missing_columns, extra_columns = [], []
    for name, frame in tables.items():
        expected = RAW_COLUMNS[name]
        missing_columns += [f"{RAW_FILES[name]}: {c}" for c in expected if c not in frame.columns]
        extra_columns += [f"{RAW_FILES[name]}: {c}" for c in frame.columns if c not in expected]
    add_check(checks, "required_columns_present", "Every expected column is present", missing_columns)
    add_check(checks, "no_unexpected_columns",
              "No unexpected columns (strict schema: extra columns are rejected, not ignored)",
              extra_columns)
    stop_if_failed(checks, "Raw schema validation")
    return {name: frame[RAW_COLUMNS[name]].copy() for name, frame in tables.items()}


# ---------------------------------------------------------------------------
# Step 2: standardize text and dates (cleaning rules 1-3)
# ---------------------------------------------------------------------------
def standardize_tables(tables, checks):
    """Trim text, turn blanks into missing values and normalize dates to ISO format.

    Returns a list of exception frames for trimmed values and reformatted dates.
    """
    whitespace_changes = []
    for name, frame in tables.items():
        for column in frame.columns:
            original = frame[column]
            stripped = original.str.strip()
            changed = original.notna() & (stripped != original)
            frame[column] = stripped.mask(stripped == "")
            if changed.any():
                whitespace_changes.append((name, column, changed, original[changed]))

    exceptions = []
    for name, column, changed, original in whitespace_changes:
        frame = tables[name]
        exceptions.append(make_exceptions(
            ENTITY_TYPES[name], frame.loc[changed, RECORD_KEYS[name]],
            frame.loc[changed, "referral_id"] if "referral_id" in frame else None,
            "extra_whitespace", column, original, frame.loc[changed, column],
            "Trimmed leading/trailing whitespace", "Resolved"))

    malformed = []
    for name, columns, input_formats, output_format in (
        [(n, c, DATE_INPUT_FORMATS, DATE_FORMAT) for n, c in DATE_COLUMNS.items()]
        + [(n, c, DATETIME_INPUT_FORMATS, DATETIME_FORMAT) for n, c in DATETIME_COLUMNS.items()]
    ):
        frame = tables[name]
        for column in columns:
            values = frame[column]
            parsed = pd.to_datetime(values, format=input_formats[0], errors="coerce")
            for fmt in input_formats[1:]:
                parsed = parsed.fillna(pd.to_datetime(values, format=fmt, errors="coerce"))
            bad = values.notna() & parsed.isna()
            malformed += [f"{RAW_FILES[name]} {column}={value!r} ({key})"
                          for key, value in zip(frame.loc[bad, RECORD_KEYS[name]], values[bad])]
            normalized = parsed.dt.strftime(output_format).where(parsed.notna(), values)
            changed = values.notna() & parsed.notna() & (normalized != values)
            if changed.any():
                exceptions.append(make_exceptions(
                    ENTITY_TYPES[name], frame.loc[changed, RECORD_KEYS[name]],
                    frame.loc[changed, "referral_id"], "nonstandard_date_format", column,
                    values[changed], normalized[changed], "Normalized date to ISO format",
                    "Resolved"))
            frame[column] = normalized
    add_check(checks, "dates_parse", "All dates and date-times parse with an accepted format", malformed)
    stop_if_failed(checks, "Date parsing")
    return exceptions


# ---------------------------------------------------------------------------
# Step 3: structural validation
# ---------------------------------------------------------------------------
def rows_where(frame, mask, key):
    return frame.loc[mask, key].tolist()


def validate_tables(tables, checks):
    """Run every structural check. Any failure stops the pipeline."""
    categories, facilities = tables["service_categories"], tables["facilities"]
    providers, patients = tables["providers"], tables["patients"]
    referrals, appointments = tables["referrals"], tables["appointments"]
    canonical = referrals.drop_duplicates("referral_id", keep="first")

    # Required values and identifier formats
    missing = []
    for name, frame in tables.items():
        for column in frame.columns:
            if column not in NULLABLE_COLUMNS.get(name, set()):
                blank_rows = frame.index[frame[column].isna()]
                missing += [f"{RAW_FILES[name]} {column} (line {i + 2})" for i in blank_rows]
    add_check(checks, "required_values_present",
              "Required fields are not blank (blanks allowed only in approved fields)", missing)
    stop_if_failed(checks, "Required-value validation")

    bad_ids = []
    for name, frame in tables.items():
        for column in frame.columns:
            if column in ID_PATTERNS:
                values = frame[column].dropna()
                bad_ids += [f"{RAW_FILES[name]} {column}={v}"
                            for v in values[~values.str.fullmatch(ID_PATTERNS[column])]]
    add_check(checks, "identifier_format", "Identifiers follow the expected code format", bad_ids)

    # Primary keys
    duplicate_keys = []
    for name, key in RECORD_KEYS.items():
        values = tables[name][key]
        duplicate_keys += [f"{RAW_FILES[name]} {key}={v}" for v in values[values.duplicated()]]
    add_check(checks, "primary_keys_unique",
              "Master IDs, referral_record_id and appointment_id are unique", duplicate_keys)

    # Duplicate referral business IDs stay within the controlled design
    copies = referrals["referral_id"].value_counts()
    add_check(checks, "referral_id_max_two_rows", "No referral_id has more than two raw rows",
              copies[copies > 2].index)
    business_columns = [c for c in referrals.columns if c != "referral_record_id"]
    duplicated = referrals[referrals["referral_id"].duplicated(keep=False)]
    versions = duplicated.drop_duplicates(business_columns)["referral_id"].value_counts()
    add_check(checks, "duplicate_rows_identical",
              "Duplicate referral rows have identical business fields", versions[versions > 1].index)

    # Foreign keys
    def foreign_key(name, description, frame, column, parent, parent_key, record_key):
        values = frame[column]
        bad = values.notna() & ~values.isin(parent[parent_key])
        add_check(checks, name, description, rows_where(frame, bad, record_key))

    foreign_key("fk_referral_patient", "Referral patient exists in patients",
                referrals, "patient_id", patients, "patient_id", "referral_record_id")
    foreign_key("fk_referral_provider", "Referral provider exists in providers",
                referrals, "receiving_provider_id", providers, "provider_id", "referral_record_id")
    foreign_key("fk_referral_service_category", "Referral service category exists",
                referrals, "service_category_id", categories, "service_category_id", "referral_record_id")
    foreign_key("fk_referral_facility", "Nonblank referral facility exists in facilities",
                referrals, "receiving_facility_id", facilities, "facility_id", "referral_record_id")
    foreign_key("fk_appointment_referral", "Appointment referral_id exists in referrals",
                appointments, "referral_id", canonical, "referral_id", "appointment_id")
    foreign_key("fk_appointment_facility", "Appointment facility exists in facilities",
                appointments, "facility_id", facilities, "facility_id", "appointment_id")
    foreign_key("fk_appointment_provider", "Appointment provider exists in providers",
                appointments, "provider_id", providers, "provider_id", "appointment_id")
    foreign_key("fk_provider_facility", "Provider facility exists in facilities",
                providers, "facility_id", facilities, "facility_id", "provider_id")
    foreign_key("fk_provider_service_category", "Provider service category exists",
                providers, "service_category_id", categories, "service_category_id", "provider_id")
    stop_if_failed(checks, "Key validation")

    # Provider facility and service category agree with referrals and appointments
    provider_lookup = providers.set_index("provider_id")
    ref_facility = referrals["receiving_provider_id"].map(provider_lookup["facility_id"])
    ref_category = referrals["receiving_provider_id"].map(provider_lookup["service_category_id"])
    bad = (referrals["service_category_id"] != ref_category) | (
        referrals["receiving_facility_id"].notna() & (referrals["receiving_facility_id"] != ref_facility))
    add_check(checks, "referral_provider_consistent",
              "Referral provider works at the referral facility and service category",
              rows_where(referrals, bad, "referral_record_id"))
    appointment_category = appointments["referral_id"].map(
        canonical.set_index("referral_id")["service_category_id"])
    bad = ((appointments["facility_id"] != appointments["provider_id"].map(provider_lookup["facility_id"]))
           | (appointment_category != appointments["provider_id"].map(provider_lookup["service_category_id"])))
    add_check(checks, "appointment_provider_consistent",
              "Appointment provider works at the appointment facility in the referral's service category",
              rows_where(appointments, bad, "appointment_id"))

    # Enumerated values
    configured_categories = {c["service_category_id"]: c["service_category_name"]
                             for c in config.SERVICE_CATEGORIES}
    provider_types = {t for c in config.SERVICE_CATEGORIES for t in c["provider_types"]}
    enumerations = [
        ("referrals", "referral_status", config.REFERRAL_STATUSES),
        ("referrals", "closure_reason", config.CLOSURE_REASONS),
        ("referrals", "urgency", config.URGENCY_LEVELS),
        ("referrals", "referral_source", config.REFERRAL_SOURCES),
        ("appointments", "appointment_status", config.APPOINTMENT_STATUSES),
        ("patients", "insurance_type", config.INSURANCE_TYPES),
        ("patients", "gender", config.GENDERS),
        ("patients", "age_group", config.AGE_GROUPS),
        ("patients", "home_region", config.REGIONS),
        ("facilities", "region", config.REGIONS),
        ("facilities", "network_status", ["In-Network", "Out-of-Network"]),
        ("providers", "provider_type", provider_types),
        ("service_categories", "service_category_id", configured_categories),
    ]
    invalid = []
    for name, column, allowed in enumerations:
        values = tables[name][column].dropna()
        invalid += [f"{RAW_FILES[name]} {column}={v!r}" for v in sorted(set(values) - set(allowed))]
    names = categories.set_index("service_category_id")["service_category_name"]
    invalid += [f"service_categories.csv {i} name={n!r}" for i, n in names.items()
                if configured_categories.get(i) not in (None, n)]
    add_check(checks, "enumerations_valid", "Category fields only contain configured values", invalid)

    # Numeric fields
    target = pd.to_numeric(categories["target_days_to_appointment"], errors="coerce")
    sequence = pd.to_numeric(appointments["appointment_sequence"], errors="coerce")
    bad_numbers = rows_where(categories, ~target.between(1, 365) | (target % 1 != 0), "service_category_id")
    bad_numbers += rows_where(
        appointments, ~sequence.between(1, config.MAX_APPOINTMENTS_PER_REFERRAL) | (sequence % 1 != 0),
        "appointment_id")
    add_check(checks, "numeric_ranges",
              "target_days_to_appointment is 1-365 and appointment_sequence is "
              f"1-{config.MAX_APPOINTMENTS_PER_REFERRAL} (whole numbers)", bad_numbers)
    stop_if_failed(checks, "Value validation")

    # Dates
    start, end = pd.Timestamp(config.REPORTING_START_DATE), pd.Timestamp(config.REPORTING_END_DATE)
    extract = pd.Timestamp(config.DATA_EXTRACT_DATE)
    referral_date = to_dates(referrals["referral_date"])
    add_check(checks, "referral_date_in_reporting_year",
              f"Referral dates fall within {start:%Y-%m-%d} to {end:%Y-%m-%d}",
              rows_where(referrals, ~referral_date.between(start, end), "referral_record_id"))

    late, early = [], []
    for column in ["first_contact_date", "closed_date"]:
        values = to_dates(referrals[column])
        late += rows_where(referrals, values > extract, "referral_record_id")
        early += rows_where(referrals, values < referral_date, "referral_record_id")

    appointments_view = appointments.assign(
        referral_date=appointments["referral_id"].map(canonical.set_index("referral_id")["referral_date"]),
        first_contact=appointments["referral_id"].map(canonical.set_index("referral_id")["first_contact_date"]),
        referral_status=appointments["referral_id"].map(canonical.set_index("referral_id")["referral_status"]),
        sequence=sequence.astype(int),
    )
    booked = to_dates(appointments_view["booked_date"])
    appointment_day = to_dates(appointments_view["appointment_datetime"], DATETIME_FORMAT).dt.normalize()
    appointment_referral_date = to_dates(appointments_view["referral_date"])
    status = appointments_view["appointment_status"]
    late += rows_where(appointments_view, booked > extract, "appointment_id")
    late += rows_where(appointments_view, (status != "Scheduled") & (appointment_day > extract), "appointment_id")
    add_check(checks, "dates_not_after_extract_date",
              f"Contact, closure, booking and held appointment dates are on or before "
              f"{extract:%Y-%m-%d}", late)
    early += rows_where(appointments_view, booked < appointment_referral_date, "appointment_id")
    early += rows_where(appointments_view, to_dates(appointments_view["first_contact"]) > booked,
                        "appointment_id")
    add_check(checks, "dates_not_before_referral",
              "Contact, closure and booking dates are not before the referral date "
              "(and first contact is not after booking)", early)
    add_check(checks, "appointment_not_before_booking", "Appointment dates are not before booking dates",
              rows_where(appointments_view, appointment_day < booked, "appointment_id"))
    add_check(checks, "completed_appointment_after_referral",
              "Completed appointments occur after the referral date",
              rows_where(appointments_view, (status == "Completed") & (appointment_day <= appointment_referral_date),
                         "appointment_id"))
    add_check(checks, "scheduled_appointment_after_extract_date",
              "Appointments still marked Scheduled are dated after the extract date",
              rows_where(appointments_view, (status == "Scheduled") & (appointment_day <= extract), "appointment_id"))

    # Appointment journeys
    journey = appointments_view.assign(day=appointment_day).sort_values(["referral_id", "sequence"])
    same_referral = journey["referral_id"].eq(journey["referral_id"].shift())
    is_last = ~journey["referral_id"].eq(journey["referral_id"].shift(-1))
    expected_sequence = np.where(same_referral, journey["sequence"].shift() + 1, 1)
    add_check(checks, "appointment_sequence_consecutive",
              "Appointment sequences run 1, 2, 3... within each referral",
              rows_where(journey, journey["sequence"] != expected_sequence, "appointment_id"))
    add_check(checks, "appointment_dates_increase",
              "Appointment dates increase with the sequence within each referral",
              rows_where(journey, same_referral & (journey["day"] <= journey["day"].shift()), "appointment_id"))
    final_status_early = ~is_last & journey["appointment_status"].isin(["Completed", "Scheduled"])
    add_check(checks, "appointment_journey_order",
              "Only the last appointment of a referral can be Completed or Scheduled",
              rows_where(journey, final_status_early, "appointment_id"))
    last = journey[is_last]
    mismatch = ((last["appointment_status"] == "Completed") != (last["referral_status"] == "Completed")) | (
        (last["appointment_status"] == "Scheduled") != (last["referral_status"] == "Scheduled"))
    has_appointments = canonical["referral_id"].isin(appointments["referral_id"])
    no_appointment_but_needs_one = canonical["referral_status"].isin(["Completed", "Scheduled"]) & ~has_appointments
    external_with_appointments = (canonical["referral_status"] == "Sent External") & has_appointments
    add_check(checks, "referral_status_matches_appointments",
              "Completed/Scheduled referrals end with a Completed/Scheduled appointment, and "
              "external referrals have no appointments",
              rows_where(last, mismatch, "referral_id")
              + rows_where(canonical, no_appointment_but_needs_one | external_with_appointments, "referral_id"))

    # Status, closure and reason consistency
    bad_closure = [
        record for record, status_value, reason in zip(
            referrals["referral_record_id"], referrals["referral_status"], referrals["closure_reason"])
        if (None if pd.isna(reason) else reason) not in CLOSURE_REASONS_BY_STATUS.get(status_value, set())
    ]
    unexplained_closed_date = (referrals["closed_date"].notna() & referrals["closure_reason"].isna()
                               & ~referrals["referral_status"].isin(OPEN_STATUSES))
    bad_closure += rows_where(referrals, unexplained_closed_date, "referral_record_id")
    add_check(checks, "closure_matches_status",
              "Closure reason fits the referral status; closed dates without a reason occur "
              "only on open referrals (controlled issue)", bad_closure)
    reasons = appointments["status_reason"]
    bad_reason = (
        ((status == "Cancelled") & ~reasons.isin(list(config.CANCELLATION_REASONS)))
        | ((status == "Rescheduled") & ~reasons.isin(list(config.RESCHEDULE_REASONS)))
        | (~status.isin(["Cancelled", "Rescheduled"]) & reasons.notna())
    )
    add_check(checks, "status_reason_matches_status",
              "Cancelled and rescheduled appointments have a valid reason; others have none",
              rows_where(appointments, bad_reason, "appointment_id"))
    stop_if_failed(checks, "Content validation")


# ---------------------------------------------------------------------------
# Step 4: clean controlled data-quality issues (cleaning rules 4-10)
# ---------------------------------------------------------------------------
def clean_referrals(referrals, appointments, providers):
    """Deduplicate referrals and apply the controlled-issue rules.

    Returns (cleaned referrals, list of exception frames, missing values before cleaning).
    """
    exceptions = []

    # Rule 4: keep the row with the smallest referral_record_id for each referral_id.
    ordered = referrals.sort_values("referral_record_id", kind="stable")
    is_duplicate = ordered["referral_id"].duplicated(keep="first")
    removed = ordered[is_duplicate]
    kept = ordered[~is_duplicate].copy()
    kept_record = kept.set_index("referral_id")["referral_record_id"]
    exceptions.append(make_exceptions(
        "referral", removed["referral_record_id"], removed["referral_id"],
        "duplicate_referral_record", "referral_record_id", removed["referral_record_id"],
        removed["referral_id"].map(kept_record), "Removed duplicate row; kept lowest referral_record_id",
        "Resolved"))
    kept["duplicate_record_count"] = kept["referral_id"].map(
        removed["referral_id"].value_counts()).fillna(0).astype(int)
    kept = kept.sort_values("referral_id", kind="stable").reset_index(drop=True)

    missing_before = {column: int(kept[column].isna().sum())
                      for column in sorted(NULLABLE_COLUMNS["referrals"])}

    def flag(mask, issue_type, field, cleaned, action, resolution):
        exceptions.append(make_exceptions(
            "referral", kept.loc[mask, "referral_record_id"], kept.loc[mask, "referral_id"],
            issue_type, field, kept.loc[mask, field], cleaned, action, resolution))

    # Rule 5: missing referral source becomes "Unknown".
    mask = kept["referral_source"].isna()
    flag(mask, "missing_referral_source", "referral_source", UNKNOWN_SOURCE,
         "Replaced blank with Unknown", "Unresolved")
    kept.loc[mask, "referral_source"] = UNKNOWN_SOURCE

    # Rule 6: infer the receiving facility from the provider when it is unambiguous.
    facilities_per_provider = providers.groupby("provider_id")["facility_id"].nunique()
    single_facility = providers.drop_duplicates("provider_id").set_index("provider_id")["facility_id"]
    single_facility = single_facility[facilities_per_provider == 1]
    inferred = kept["receiving_provider_id"].map(single_facility)
    mask = kept["receiving_facility_id"].isna()
    can_infer = mask & inferred.notna()
    flag(can_infer, "missing_receiving_facility", "receiving_facility_id", inferred[can_infer],
         "Inferred from receiving provider's facility", "Resolved")
    flag(mask & inferred.isna(), "missing_receiving_facility", "receiving_facility_id", None,
         "Could not infer facility; left blank", "Unresolved")
    kept.loc[can_infer, "receiving_facility_id"] = inferred[can_infer]

    # Rule 7: first contact is blank although an appointment or decline proves contact.
    contact_proven = kept["referral_id"].isin(appointments["referral_id"]) | (kept["referral_status"] == "Declined")
    mask = kept["first_contact_date"].isna() & contact_proven
    flag(mask, "missing_first_contact_date", "first_contact_date", None,
         "Kept blank; contact is evidenced by an appointment or decline", "Unresolved")

    # Rule 8: closure reason recorded without a closed date.
    mask = kept["closure_reason"].notna() & kept["closed_date"].isna()
    flag(mask, "missing_closed_date", "closed_date", None,
         "Kept blank; closure reason retained", "Unresolved")

    # Rule 9: open referral carrying a closed date.
    mask = kept["referral_status"].isin(OPEN_STATUSES) & kept["closed_date"].notna()
    flag(mask, "open_referral_with_closed_date", "closed_date", None,
         "Cleared closed date on open referral", "Resolved")
    kept.loc[mask, "closed_date"] = None

    # Rule 10: all other blanks (never contacted, still open, no reason) stay blank.
    return kept, exceptions, missing_before


def assemble_exceptions(exception_frames):
    """Combine exception frames in rule order and give each a stable ID."""
    columns = PROCESSED_COLUMNS["data_quality_exceptions"][1:]
    frames = [frame for frame in exception_frames if len(frame)]
    if not frames:
        return pd.DataFrame(columns=PROCESSED_COLUMNS["data_quality_exceptions"])
    exceptions = pd.concat(frames, ignore_index=True)[columns]
    exceptions["issue_order"] = exceptions["issue_type"].map(ISSUE_TYPES.index)
    exceptions["entity_order"] = exceptions["entity_type"].map(list(ENTITY_TYPES.values()).index)
    field_order = {column: i for name in TABLE_NAMES for i, column in enumerate(RAW_COLUMNS[name])}
    exceptions["field_order"] = exceptions["field_name"].map(field_order)
    exceptions = exceptions.sort_values(
        ["issue_order", "entity_order", "record_id", "field_order"], kind="stable").reset_index(drop=True)
    exceptions.insert(0, "exception_id", [f"DQE{i:07d}" for i in range(1, len(exceptions) + 1)])
    return exceptions[PROCESSED_COLUMNS["data_quality_exceptions"]]


def build_processed_tables(tables, referrals, exceptions):
    issue_counts = exceptions[exceptions["entity_type"] == "referral"]["referral_id"].value_counts()
    referrals = referrals.copy()
    referrals["data_quality_issue_count"] = referrals["referral_id"].map(issue_counts).fillna(0).astype(int)
    referrals["has_data_quality_issue"] = (referrals["data_quality_issue_count"] > 0).astype(int)

    appointments = tables["appointments"].copy()
    appointments["appointment_date"] = appointments["appointment_datetime"].str.slice(0, 10)

    processed = {
        "service_categories": tables["service_categories"],
        "facilities": tables["facilities"],
        "providers": tables["providers"],
        "patients": tables["patients"],
        "referrals": referrals,
        "appointments": appointments,
        "data_quality_exceptions": exceptions,
    }
    for name, frame in processed.items():
        frame = frame[PROCESSED_COLUMNS[name]].copy()
        for column in INTEGER_COLUMNS.get(name, []):
            frame[column] = frame[column].astype(int)
        processed[name] = frame.sort_values(SORT_KEYS[name], kind="stable").reset_index(drop=True)
    return processed


# ---------------------------------------------------------------------------
# Step 5: outputs
# ---------------------------------------------------------------------------
def write_csv(frame, path):
    frame.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")


def write_json(data, path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def build_database(db_path, processed):
    """Create the schema from sql/01_create_schema.sql and load every processed table."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(config.SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
        with connection:
            for name, frame in processed.items():
                columns = list(frame.columns)
                # object dtype gives plain Python str/int values; missing values become NULL.
                values = frame.astype(object)
                rows = list(values.where(frame.notna(), None).itertuples(index=False, name=None))
                connection.executemany(
                    f"INSERT INTO {name} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    rows)
        row_counts = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                      for name in processed}
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if foreign_key_violations:
        raise PipelineError(f"SQLite foreign_key_check found {len(foreign_key_violations)} violation(s).")
    if integrity != "ok":
        raise PipelineError(f"SQLite integrity_check failed: {integrity}")
    return {"table_row_counts": row_counts, "foreign_key_check": "passed",
            "foreign_key_violations": 0, "integrity_check": integrity}


def summarize_report(raw_counts, processed, referrals_before, missing_before, checks, database):
    exceptions = processed["data_quality_exceptions"]
    referrals = processed["referrals"]
    issue_counts = exceptions["issue_type"].value_counts()
    by_issue = {issue: int(issue_counts.get(issue, 0)) for issue in ISSUE_TYPES}
    unresolved = exceptions[exceptions["resolution_status"] == "Unresolved"]
    unresolved_counts = unresolved["issue_type"].value_counts()

    facility_actions = exceptions[exceptions["issue_type"] == "missing_receiving_facility"]
    cleaning_actions = {
        "trimmed_whitespace": by_issue["extra_whitespace"],
        "normalized_date_format": by_issue["nonstandard_date_format"],
        "removed_duplicate_referral_rows": by_issue["duplicate_referral_record"],
        "replaced_missing_referral_source_with_unknown": by_issue["missing_referral_source"],
        "inferred_receiving_facility_from_provider":
            int((facility_actions["resolution_status"] == "Resolved").sum()),
        "receiving_facility_not_inferred":
            int((facility_actions["resolution_status"] == "Unresolved").sum()),
        "kept_missing_first_contact_date_blank": by_issue["missing_first_contact_date"],
        "kept_missing_closed_date_blank": by_issue["missing_closed_date"],
        "cleared_closed_date_on_open_referral": by_issue["open_referral_with_closed_date"],
    }

    # For each approved blank field: blanks before and after cleaning, blanks
    # flagged as exceptions, and the remaining blanks that are part of the design.
    missing_values = {}
    referral_blanks = exceptions[(exceptions["entity_type"] == "referral")
                                 & exceptions["original_value"].isna()]
    for column in sorted(NULLABLE_COLUMNS["referrals"]):
        flagged = referral_blanks[referral_blanks["field_name"] == column]
        after = int(referrals[column].isna().sum())
        missing_values[f"referrals.{column}"] = {
            "before_cleaning": missing_before[column],
            "flagged_as_exception": len(flagged),
            "filled_by_cleaning": int(flagged["cleaned_value"].notna().sum()),
            "after_cleaning": after,
            "legitimate_structural_blanks": after - int(flagged["cleaned_value"].isna().sum()),
        }
    status_reason_blank = int(processed["appointments"]["status_reason"].isna().sum())
    missing_values["appointments.status_reason"] = {
        "before_cleaning": status_reason_blank, "flagged_as_exception": 0, "filled_by_cleaning": 0,
        "after_cleaning": status_reason_blank, "legitimate_structural_blanks": status_reason_blank,
    }

    _, generator_targets = data_quality_counts(raw_counts["referrals.csv"])
    reconciliation = {
        issue: {"generator_target": generator_targets[setting], "detected": by_issue[issue],
                "matches": generator_targets[setting] == by_issue[issue]}
        for issue, setting in GENERATOR_ISSUES.items()
    }

    output_counts = {PROCESSED_FILES[name]: len(frame) for name, frame in processed.items()}
    db_counts = database["table_row_counts"]
    unique_ids = len(referrals)
    return {
        "project": "Healthcare Referral Leakage Analytics",
        "phase": 2,
        "pipeline_status": "succeeded",
        "synthetic_data": True,
        "non_clinical_use": SYNTHETIC_DATA_NOTICE,
        "reporting_period": {"start": f"{config.REPORTING_START_DATE:%Y-%m-%d}",
                             "end": f"{config.REPORTING_END_DATE:%Y-%m-%d}"},
        "extract_date": f"{config.DATA_EXTRACT_DATE:%Y-%m-%d}",
        "outputs": {
            "processed_files": list(PROCESSED_FILES.values()),
            "database_file": config.DATABASE_FILE,
            "report_file": config.DATA_QUALITY_REPORT_FILE,
        },
        "input_row_counts": raw_counts,
        "output_row_counts": output_counts,
        "duplicates": {
            "input_referral_records": referrals_before,
            "unique_referral_ids": unique_ids,
            "removed_duplicate_rows": referrals_before - unique_ids,
            "referral_ids_with_duplicates": int((referrals["duplicate_record_count"] > 0).sum()),
            "rule": "Keep the row with the smallest referral_record_id",
        },
        "missing_values": missing_values,
        "cleaning_actions": cleaning_actions,
        "exceptions": {
            "total": len(exceptions),
            "resolved": len(exceptions) - len(unresolved),
            "unresolved": len(unresolved),
            "by_issue_type": by_issue,
            "unresolved_by_issue_type": {issue: int(unresolved_counts.get(issue, 0)) for issue in ISSUE_TYPES},
            "referrals_with_issues": int(referrals["has_data_quality_issue"].sum()),
        },
        "controlled_issue_reconciliation": {
            "note": "Compares detected issues with the generator's configured targets "
                    "for this referral count.",
            "all_match": all(item["matches"] for item in reconciliation.values()),
            "issues": reconciliation,
        },
        "validation": {
            "status": "passed",
            "checks_run": len(checks),
            "checks_failed": len(failed_checks(checks)),
            "structural_violations": sum(check["violation_count"] for check in failed_checks(checks)),
            "checks": checks,
        },
        "referral_status_counts": {
            status: int(count) for status, count in
            referrals["referral_status"].value_counts().reindex(config.REFERRAL_STATUSES, fill_value=0).items()},
        "appointment_status_counts": {
            status: int(count) for status, count in processed["appointments"]["appointment_status"]
            .value_counts().reindex(config.APPOINTMENT_STATUSES, fill_value=0).items()},
        "database": {
            **database,
            "row_counts_match_processed_csvs": all(
                db_counts[name] == len(frame) for name, frame in processed.items()),
        },
    }


def failed_report(message, checks, raw_counts, outputs_replaced=False):
    note = ("Processed CSVs and the database from the last successful run were left unchanged."
            if not outputs_replaced else
            "The failure happened while moving outputs into place; some outputs may have been "
            "replaced. Rerun the pipeline.")
    return {
        "project": "Healthcare Referral Leakage Analytics",
        "phase": 2,
        "pipeline_status": "failed",
        "synthetic_data": True,
        "non_clinical_use": SYNTHETIC_DATA_NOTICE,
        "reporting_period": {"start": f"{config.REPORTING_START_DATE:%Y-%m-%d}",
                             "end": f"{config.REPORTING_END_DATE:%Y-%m-%d}"},
        "extract_date": f"{config.DATA_EXTRACT_DATE:%Y-%m-%d}",
        "error": message,
        "outputs_replaced": outputs_replaced,
        "note": note,
        "input_row_counts": raw_counts,
        "validation": {
            "status": "failed",
            "checks_run": len(checks),
            "checks_failed": len(failed_checks(checks)),
            "structural_violations": sum(check["violation_count"] for check in failed_checks(checks)),
            "checks": checks,
        },
    }


def publish_outputs(staging_dir, processed_dir, output_dir):
    """Move staged files into place: database first, then CSVs, then the report."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir / config.DATABASE_FILE, output_dir / config.DATABASE_FILE)
    for file_name in PROCESSED_FILES.values():
        os.replace(staging_dir / file_name, processed_dir / file_name)
    os.replace(staging_dir / config.DATA_QUALITY_REPORT_FILE, output_dir / config.DATA_QUALITY_REPORT_FILE)


def run_pipeline(raw_dir=config.RAW_DATA_DIR, processed_dir=config.PROCESSED_DATA_DIR,
                 output_dir=config.OUTPUT_DATA_DIR):
    """Run Phase 2 end to end and return the JSON report as a dictionary."""
    raw_dir, processed_dir, output_dir = Path(raw_dir), Path(processed_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".phase2_staging_", dir=output_dir))
    checks, raw_counts = [], {}
    publishing = False
    try:
        try:
            tables = load_raw_tables(raw_dir, checks)
            raw_counts = {RAW_FILES[name]: len(frame) for name, frame in tables.items()}
            exception_frames = standardize_tables(tables, checks)
            validate_tables(tables, checks)

            referrals, cleaning_exceptions, missing_before = clean_referrals(
                tables["referrals"], tables["appointments"], tables["providers"])
            exceptions = assemble_exceptions(exception_frames + cleaning_exceptions)
            processed = build_processed_tables(tables, referrals, exceptions)

            for name, frame in processed.items():
                write_csv(frame, staging_dir / PROCESSED_FILES[name])
            database = build_database(staging_dir / config.DATABASE_FILE, processed)
            report = summarize_report(raw_counts, processed, len(tables["referrals"]),
                                      missing_before, checks, database)
            if not report["database"]["row_counts_match_processed_csvs"]:
                raise PipelineError("SQLite row counts do not match the processed CSV files.")
            write_json(report, staging_dir / config.DATA_QUALITY_REPORT_FILE)
            publishing = True
            publish_outputs(staging_dir, processed_dir, output_dir)
            return report
        except (PipelineError, sqlite3.Error, OSError) as error:
            message = str(error) if isinstance(error, PipelineError) else f"{type(error).__name__}: {error}"
            report = failed_report(message, checks, raw_counts, outputs_replaced=publishing)
            write_json(report, staging_dir / config.DATA_QUALITY_REPORT_FILE)
            os.replace(staging_dir / config.DATA_QUALITY_REPORT_FILE,
                       output_dir / config.DATA_QUALITY_REPORT_FILE)
            return report
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate, clean and load the synthetic referral data into SQLite. "
                    + SYNTHETIC_DATA_NOTICE)
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_DATA_DIR,
                        help="folder with the raw CSV files (default: data\\raw)")
    parser.add_argument("--processed-dir", type=Path, default=config.PROCESSED_DATA_DIR,
                        help="folder for processed CSV files (default: data\\processed)")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DATA_DIR,
                        help="folder for the database and JSON report (default: data\\output)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    report = run_pipeline(args.raw_dir, args.processed_dir, args.output_dir)
    report_path = display_path(args.output_dir / config.DATA_QUALITY_REPORT_FILE)

    if report["pipeline_status"] != "succeeded":
        print("Phase 2 data preparation FAILED.", file=sys.stderr)
        print(report["error"], file=sys.stderr)
        print(f"Failure report: {report_path}", file=sys.stderr)
        print("Previous successful processed files and database were left unchanged.", file=sys.stderr)
        return 1

    validation, duplicates = report["validation"], report["duplicates"]
    print("Phase 2 data preparation completed successfully.")
    print(f"  Raw files validated : {len(report['input_row_counts'])} files, "
          f"{validation['checks_run']} checks passed, 0 structural violations")
    print("  Row counts (raw -> processed):")
    for name in TABLE_NAMES:
        file_name = RAW_FILES[name]
        print(f"    {file_name:<28}{report['input_row_counts'][file_name]:>10,} -> "
              f"{report['output_row_counts'][file_name]:>10,}")
    exceptions_file = PROCESSED_FILES["data_quality_exceptions"]
    print(f"    {exceptions_file:<28}{'':>10}    {report['output_row_counts'][exceptions_file]:>10,}")
    print(f"  Duplicates removed  : {duplicates['removed_duplicate_rows']:,}")
    print(f"  Exceptions found    : {report['exceptions']['total']:,} "
          f"({report['exceptions']['resolved']:,} resolved, {report['exceptions']['unresolved']:,} unresolved)")
    print("  Cleaning actions:")
    for action, count in report["cleaning_actions"].items():
        print(f"    {action:<48}{count:>8,}")
    print(f"  Processed folder    : {display_path(args.processed_dir)}")
    print(f"  Database            : {display_path(args.output_dir / config.DATABASE_FILE)}")
    print(f"  Report              : {report_path}")
    print(f"NOTICE: {SYNTHETIC_DATA_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
