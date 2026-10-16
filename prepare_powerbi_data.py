"""Export the Power BI-ready data snapshot (Phase 4A).

Steps
  1. Check the Phase 2 database and report, and the Phase 3 analytics summary.
  2. Refresh the Phase 3 views and read the referral journey and master data.
  3. Write six compact CSV files and expected_kpis.json to a staging folder.
     Every KPI comes from the Phase 3 SQL views.
  4. Validate the staged files: columns, row counts, keys, formats, flags,
     date table and KPIs recomputed from the CSVs.
  5. Only if every check passes, replace powerbi/data/*.csv and
     powerbi/expected_kpis.json. A failed run leaves the previous snapshot as it was.

This script does not create the Power BI report (.pbix); that is built by hand in
Power BI Desktop (see powerbi/POWER_BI_BUILD_GUIDE.md). All data is fully
synthetic and for portfolio and educational use only, not for clinical
decision-making.

Usage (PowerShell, from the project folder):
    .\\.venv\\Scripts\\python.exe prepare_powerbi_data.py
"""

import argparse
import calendar
import csv
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import config
from generate_data import SYNTHETIC_DATA_NOTICE

ANALYZE_COMMAND = r".\.venv\Scripts\python.exe analyze_data.py"
PREPARE_COMMAND = r".\.venv\Scripts\python.exe prepare_data.py"
GENERATE_COMMAND = r".\.venv\Scripts\python.exe generate_data.py --referrals 150000 --seed 42"
TOLERANCE = 1e-6
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Snapshot column (Power BI name) -> source column in vw_referral_journey.
REFERRAL_COLUMNS = {
    "referral_id": "referral_id",
    "referral_date": "referral_date",
    "provider_id": "receiving_provider_id",
    "referral_source": "referral_source",
    "urgency": "urgency",
    "insurance_type": "insurance_type",
    "age_group": "age_group",
    "gender": "gender",
    "referral_status": "referral_status",
    "outcome": "outcome_category",
    "primary_leakage_reason": "primary_leakage_reason",
    "leakage_reason_priority": None,  # from vw_leakage_reasons
    "contacted_flag": "contacted_flag",
    "scheduled_flag": "scheduled_flag",
    "completed_flag": "completed_flag",
    "confirmed_external_outcome_flag": "confirmed_external_outcome_flag",
    "converted_flag": "converted_flag",
    "active_flag": "active_in_progress_flag",
    "leakage_flag": "leakage_flag",
    "had_cancellation_flag": "had_cancellation_flag",
    "had_no_show_flag": "had_no_show_flag",
    "delayed_scheduling_flag": "delayed_schedule_flag",
    "delayed_appointment_flag": "delayed_appointment_flag",
    "first_contact_date": "first_contact_date",
    "first_booking_date": "first_booking_date",
    "first_appointment_date": "first_appointment_date",
    "days_to_first_contact": "days_to_first_contact",
    "days_to_schedule": "days_to_schedule",
    "days_to_first_appointment": "days_to_first_appointment",
    "duplicate_record_count": "duplicate_record_count",
    "data_quality_issue_count": "data_quality_issue_count",
    "has_data_quality_issue": "has_data_quality_issue",
}
FLAG_COLUMNS = [c for c in REFERRAL_COLUMNS if c.endswith("_flag")] + ["has_data_quality_issue"]
DURATIONS = {  # duration column -> the date it is measured to
    "days_to_first_contact": "first_contact_date",
    "days_to_schedule": "first_booking_date",
    "days_to_first_appointment": "first_appointment_date",
}
# Readable labels for the Phase 2 issue types.
ISSUE_LABELS = {
    "extra_whitespace": "Extra whitespace",
    "nonstandard_date_format": "Non-standard date format",
    "duplicate_referral_record": "Duplicate referral record",
    "missing_referral_source": "Missing referral source",
    "missing_receiving_facility": "Missing receiving facility",
    "missing_first_contact_date": "Missing first-contact date",
    "missing_closed_date": "Missing closed date",
    "open_referral_with_closed_date": "Open referral with closed date",
}
COLUMNS = {
    "Referrals": list(REFERRAL_COLUMNS),
    "DataQualityExceptions": ["exception_id", "referral_id", "entity_type", "issue_type", "issue_label",
                              "field_name", "resolution_status"],
    "ServiceCategories": ["service_category_id", "service_category_name", "service_line",
                          "target_days_to_appointment"],
    "Facilities": ["facility_id", "facility_name", "facility_type", "region", "network_status"],
    "Providers": ["provider_id", "provider_name", "provider_type", "facility_id", "service_category_id"],
    "Date": ["date", "year", "quarter_number", "quarter_label", "month_number", "month_name", "year_month",
             "year_month_sort", "week_number", "day_of_month", "weekday_number", "weekday_name", "is_weekend"],
}
KEYS = {"Referrals": "referral_id", "DataQualityExceptions": "exception_id",
        "ServiceCategories": "service_category_id", "Facilities": "facility_id",
        "Providers": "provider_id", "Date": "date"}
SOURCE_QUERIES = {
    "DataQualityExceptions": "SELECT exception_id, referral_id, entity_type, issue_type, NULL AS issue_label, "
                             "field_name, resolution_status FROM data_quality_exceptions ORDER BY exception_id",
    "ServiceCategories": "SELECT service_category_id, service_category_name, service_line, "
                         "target_days_to_appointment FROM service_categories ORDER BY service_category_id",
    "Facilities": "SELECT facility_id, facility_name, facility_type, region, network_status "
                  "FROM facilities ORDER BY facility_id",
    "Providers": "SELECT provider_id, provider_name, provider_type, facility_id, service_category_id "
                 "FROM providers ORDER BY provider_id",
}
COUNT_KPIS = [
    "total_referrals", "scheduled_referrals", "completed_referrals", "converted_referrals",
    "leaked_referrals", "active_referrals", "delayed_scheduling_referrals", "delayed_appointment_referrals",
    "cancelled_referrals", "no_show_referrals", "referrals_with_duplicates",
    "referrals_with_data_quality_issues", "data_quality_exceptions",
]
RATE_KPIS = ["conversion_rate", "leakage_rate", "scheduling_rate", "completion_rate"]
MEDIAN_KPIS = ["median_days_to_first_contact", "median_days_to_schedule", "median_days_to_first_appointment"]
# Snapshot flag used to recompute each count KPI from the CSV files.
COUNT_FLAGS = {
    "scheduled_referrals": "scheduled_flag", "completed_referrals": "completed_flag",
    "converted_referrals": "converted_flag", "leaked_referrals": "leakage_flag",
    "active_referrals": "active_flag", "delayed_scheduling_referrals": "delayed_scheduling_flag",
    "delayed_appointment_referrals": "delayed_appointment_flag", "cancelled_referrals": "had_cancellation_flag",
    "no_show_referrals": "had_no_show_flag", "referrals_with_data_quality_issues": "has_data_quality_issue",
}
RATE_PARTS = {"conversion_rate": "converted_referrals", "leakage_rate": "leaked_referrals",
              "scheduling_rate": "scheduled_referrals", "completion_rate": "completed_referrals"}
GROUPED = {  # expected_kpis key -> (Phase 3 dimension, snapshot column or None)
    "by_month": ("Referral Month", None),
    "by_service_category": ("Service Category", None),
    "by_referral_source": ("Referral Source", "referral_source"),
    "by_urgency": ("Urgency", "urgency"),
    "by_insurance_type": ("Insurance Type", "insurance_type"),
}


class SnapshotError(Exception):
    """A problem that stops the snapshot before anything is replaced."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def display_path(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def rounded(value, digits=6):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), digits) if isinstance(value, float) else value


def display(value, kind):
    if value is None:
        return "(Blank)"
    if kind == "count":
        return f"{int(value):,}"
    if kind == "rate":
        return f"{value:.1%}"
    return f"{value:g}" if float(value).is_integer() else f"{value:.1f}"


def query(connection, sql, params=()):
    cursor = connection.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def write_csv(rows, columns, path):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row[c] is None else row[c] for c in columns])


def write_json(data, path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_snapshot(folder):
    """Read every snapshot CSV as text; empty fields become missing values."""
    return {table: pd.read_csv(Path(folder) / file_name, dtype=str, keep_default_na=False, na_values=[""])
            for table, file_name in config.POWERBI_FILES.items()}


# ---------------------------------------------------------------------------
# Step 1: prerequisites
# ---------------------------------------------------------------------------
def check_prerequisites(output_dir):
    database = output_dir / config.DATABASE_FILE
    if not database.is_file():
        raise SnapshotError(
            f"Phase 2 database not found: {display_path(database)}.\n"
            f"Build it first with:\n  {GENERATE_COMMAND}\n  {PREPARE_COMMAND}\n  {ANALYZE_COMMAND}")
    phase2_path = output_dir / config.DATA_QUALITY_REPORT_FILE
    phase2 = json.loads(phase2_path.read_text(encoding="utf-8")) if phase2_path.is_file() else {}
    if phase2.get("pipeline_status") != "succeeded":
        raise SnapshotError(f"The Phase 2 quality report is missing or did not pass. Rerun:\n  {PREPARE_COMMAND}")
    phase3_path = output_dir / config.ANALYTICS_SUMMARY_FILE
    phase3 = json.loads(phase3_path.read_text(encoding="utf-8")) if phase3_path.is_file() else {}
    reconciliation = phase3.get("reconciliation", {})
    if phase3.get("analytics_status") != "succeeded" or reconciliation.get("checks_failed") != 0 \
            or not reconciliation.get("checks_run"):
        raise SnapshotError(
            f"Phase 3 analytics are missing or a reconciliation check failed. Rerun:\n  {ANALYZE_COMMAND}")
    return database, phase3


# ---------------------------------------------------------------------------
# Step 2-3: build tables and expected KPIs from SQL
# ---------------------------------------------------------------------------
def build_date_table(referral_dates):
    """One row per day for every calendar year that contains a referral."""
    if not referral_dates:
        return []
    first_year, last_year = int(min(referral_dates)[:4]), int(max(referral_dates)[:4])
    rows, day = [], date(first_year, 1, 1)
    while day.year <= last_year:
        quarter = (day.month - 1) // 3 + 1
        rows.append({
            "date": day.isoformat(),
            "year": day.year,
            "quarter_number": quarter,
            "quarter_label": f"Q{quarter}",
            "month_number": day.month,
            "month_name": calendar.month_name[day.month],
            "year_month": f"{calendar.month_abbr[day.month]} {day.year}",
            "year_month_sort": day.year * 100 + day.month,
            "week_number": day.isocalendar().week,
            "day_of_month": day.day,
            "weekday_number": day.isoweekday(),
            "weekday_name": calendar.day_name[day.weekday()],
            "is_weekend": 1 if day.isoweekday() >= 6 else 0,
        })
        day += timedelta(days=1)
    return rows


def build_tables(connection):
    priorities = {r["leakage_reason"]: r["priority"] for r in query(connection, "SELECT * FROM vw_leakage_reasons")}
    source_columns = ", ".join(c for c in REFERRAL_COLUMNS.values() if c)
    journey = query(connection, f"SELECT {source_columns} FROM vw_referral_journey ORDER BY referral_id")
    referrals = []
    for row in journey:
        out = {name: row[source] for name, source in REFERRAL_COLUMNS.items() if source}
        out["leakage_reason_priority"] = priorities.get(row["primary_leakage_reason"])
        referrals.append(out)
    tables = {"Referrals": referrals}
    for table, sql in SOURCE_QUERIES.items():
        tables[table] = query(connection, sql)
    for row in tables["DataQualityExceptions"]:
        if row["issue_type"] not in ISSUE_LABELS:
            raise SnapshotError(f"Unknown data-quality issue type: {row['issue_type']!r}")
        row["issue_label"] = ISSUE_LABELS[row["issue_type"]]
    tables["Date"] = build_date_table([r["referral_date"] for r in referrals])
    return tables


def build_expected_kpis(connection, tables):
    """Collect every dashboard reference value from the Phase 3 SQL views."""
    overall = query(connection, "SELECT * FROM vw_overall_kpis")[0]
    parameters = query(connection, "SELECT * FROM vw_analysis_parameters")[0]
    kinds = {**{k: "count" for k in COUNT_KPIS}, **{k: "rate" for k in RATE_KPIS},
             **{k: "days" for k in MEDIAN_KPIS}}
    kpis = {}
    for name, kind in kinds.items():
        value = overall[name]
        kpis[name] = {"value": rounded(value), "display": display(value, kind)}
    outcome_rows = query(connection, "SELECT outcome_category, COUNT(*) AS referrals FROM vw_referral_journey "
                                     "GROUP BY outcome_category ORDER BY outcome_category")
    outcomes = {name: 0 for name in ["Converted", "Active", "Leaked", "Unclassified"]}
    outcomes.update({r["outcome_category"]: r["referrals"] for r in outcome_rows})
    reasons = [{
        "priority": r["priority"], "leakage_reason": r["leakage_reason"],
        "leaked_referrals": r["leaked_referrals"],
        "share_of_leaked_referrals": rounded(r["share_of_leaked_referrals"]),
        "rate_of_total_referrals": rounded(r["rate_of_total_referrals"]),
    } for r in query(connection, "SELECT * FROM vw_leakage_reason_metrics ORDER BY priority")]
    funnel = [{
        "stage_order": r["stage_order"], "stage": r["stage"], "referrals": r["referrals"],
        "internal_referrals": r["internal_referrals"], "external_referrals": r["external_referrals"],
        "share_of_total_referrals": rounded(r["share_of_total_referrals"]),
    } for r in query(connection, "SELECT * FROM vw_referral_funnel ORDER BY stage_order")]
    dimension_rows = query(connection, "SELECT * FROM vw_dimension_metrics ORDER BY dimension_order, dimension_key")
    grouped = {}
    for key, (dimension, _) in GROUPED.items():
        grouped[key] = [{
            "key": r["dimension_key"], "label": r["dimension_label"],
            "total_referrals": r["total_referrals"], "converted_referrals": r["converted_referrals"],
            "leaked_referrals": r["leaked_referrals"], "conversion_rate": rounded(r["conversion_rate"]),
            "leakage_rate": rounded(r["leakage_rate"]),
            "median_days_to_schedule": rounded(r["median_days_to_schedule"]),
            "delayed_scheduling_referrals": r["delayed_scheduling_referrals"],
        } for r in dimension_rows if r["dimension"] == dimension]
    quality = [{"issue_type": r["issue_type"], "issue_label": ISSUE_LABELS[r["issue_type"]],
                "exceptions": r["exception_count"]}
               for r in query(connection, "SELECT * FROM vw_data_quality_metrics ORDER BY first_exception_id")]
    dates = [r["date"] for r in tables["Date"]]
    return {
        "project": "Healthcare Referral Leakage Analytics",
        "phase": "4A",
        "synthetic_data": True,
        "non_clinical_use": SYNTHETIC_DATA_NOTICE,
        "source": "Phase 3 SQL views in the Phase 2 SQLite database (vw_overall_kpis, vw_leakage_reason_metrics, "
                  "vw_referral_funnel, vw_dimension_metrics, vw_data_quality_metrics)",
        "reporting_period": {"start": parameters["reporting_start_date"], "end": parameters["reporting_end_date"]},
        "extract_date": parameters["extract_date"],
        "snapshot": {
            "row_counts": {file_name: len(tables[table]) for table, file_name in config.POWERBI_FILES.items()},
            "date_table_range": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        },
        "kpis": kpis,
        "outcomes": outcomes,
        "leakage_reasons": reasons,
        "referral_funnel": funnel,
        **grouped,
        "data_quality_by_issue_type": quality,
    }


# ---------------------------------------------------------------------------
# Step 4: validation (also used by the tests on the tracked snapshot)
# ---------------------------------------------------------------------------
def validate_snapshot(folder, expected, database=None):
    """Check a snapshot folder against its expected KPIs. Returns (name, problems) pairs."""
    folder = Path(folder)
    results = []

    def check(name, problems):
        results.append((name, [str(p) for p in problems]))

    missing = [f for f in config.POWERBI_FILES.values() if not (folder / f).is_file()]
    check("files_exist", missing)
    if missing:
        return results
    data = read_snapshot(folder)
    referrals, exceptions = data["Referrals"], data["DataQualityExceptions"]
    providers, dates = data["Providers"], data["Date"]

    check("exact_columns", [f"{t}: {list(f.columns)}" for t, f in data.items() if list(f.columns) != COLUMNS[t]])
    row_counts = expected["snapshot"]["row_counts"]
    problems = [f"{config.POWERBI_FILES[t]}: {len(f)} rows, expected {row_counts[config.POWERBI_FILES[t]]}"
                for t, f in data.items() if len(f) != row_counts[config.POWERBI_FILES[t]]]
    if database is not None:
        connection = sqlite3.connect(database)
        try:
            sql_counts = {"Referrals": "referrals", "DataQualityExceptions": "data_quality_exceptions",
                          "ServiceCategories": "service_categories", "Facilities": "facilities",
                          "Providers": "providers"}
            for table, sql_table in sql_counts.items():
                count = connection.execute(f"SELECT COUNT(*) FROM {sql_table}").fetchone()[0]
                if count != len(data[table]):
                    problems.append(f"{table}: {len(data[table])} rows, SQLite has {count}")
        finally:
            connection.close()
    check("row_counts_match", problems)
    check("keys_unique_and_present",
          [f"{t}.{k}" for t, k in KEYS.items() if data[t][k].isna().any() or not data[t][k].is_unique])

    fk = []
    fk += [f"provider {v}" for v in set(referrals["provider_id"]) - set(providers["provider_id"])]
    fk += [f"facility {v}" for v in set(providers["facility_id"]) - set(data["Facilities"]["facility_id"])]
    fk += [f"category {v}" for v in set(providers["service_category_id"])
           - set(data["ServiceCategories"]["service_category_id"])]
    fk += [f"referral_date {v}" for v in set(referrals["referral_date"]) - set(dates["date"])]
    fk += [f"exception referral {v}" for v in set(exceptions["referral_id"].dropna()) - set(referrals["referral_id"])]
    check("model_keys_valid", fk)

    formats = []
    for column in ["referral_date", "first_contact_date", "first_booking_date", "first_appointment_date"]:
        values = referrals[column].dropna()
        formats += [f"{column}={v}" for v in values[~values.str.match(ISO_DATE)].head(5)]
    formats += [f"date={v}" for v in dates["date"][~dates["date"].str.match(ISO_DATE)].head(5)]
    integer_columns = FLAG_COLUMNS + list(DURATIONS) + ["duplicate_record_count", "data_quality_issue_count",
                                                       "leakage_reason_priority"]
    for column in integer_columns:
        values = referrals[column].dropna()
        formats += [f"{column}={v}" for v in values[~values.str.fullmatch(r"\d+")].head(5)]
    formats += [f"{c}={v}" for c in FLAG_COLUMNS for v in set(referrals[c]) - {"0", "1"}]
    check("stable_formats", formats)

    blanks = []
    for duration, date_column in DURATIONS.items():
        mismatch = referrals[duration].isna() != referrals[date_column].isna()
        blanks += [f"{duration} vs {date_column}: {r}" for r in referrals.loc[mismatch, "referral_id"].head(5)]
    no_appointments = referrals["scheduled_flag"] == "0"
    if referrals.loc[no_appointments, "first_booking_date"].notna().any():
        blanks.append("unscheduled referral has a booking date")
    check("blanks_preserved", blanks)

    flags = referrals[["converted_flag", "active_flag", "leakage_flag"]].astype(int)
    outcome = referrals["outcome"]
    bad = (flags.sum(axis=1) > 1) | ((outcome == "Converted") != (flags["converted_flag"] == 1)) \
        | ((outcome == "Active") != (flags["active_flag"] == 1)) | ((outcome == "Leaked") != (flags["leakage_flag"] == 1))
    check("outcome_flags_exclusive", referrals.loc[bad, "referral_id"].head(5).tolist())

    reason_priority = {r["leakage_reason"]: str(r["priority"]) for r in expected["leakage_reasons"]}
    leaked = referrals["leakage_flag"] == "1"
    problems = referrals.loc[leaked != referrals["primary_leakage_reason"].notna(), "referral_id"].head(5).tolist()
    pairs = referrals.loc[leaked, ["primary_leakage_reason", "leakage_reason_priority"]].drop_duplicates()
    problems += [f"{r} priority {p}" for r, p in pairs.itertuples(index=False) if reason_priority.get(r) != p]
    counts = referrals.loc[leaked, "primary_leakage_reason"].value_counts()
    problems += [f"{r['leakage_reason']}: snapshot {int(counts.get(r['leakage_reason'], 0))} "
                 f"expected {r['leaked_referrals']}" for r in expected["leakage_reasons"]
                 if int(counts.get(r["leakage_reason"], 0)) != r["leaked_referrals"]]
    check("leakage_reasons_reconcile", problems)

    problems = []
    if len(dates):
        days = pd.to_datetime(dates["date"])
        if not (days.diff().dropna() == pd.Timedelta(days=1)).all():
            problems.append("date table has gaps or is unsorted")
        if days.iloc[0].strftime("%m-%d") != "01-01" or days.iloc[-1].strftime("%m-%d") != "12-31":
            problems.append("date table does not cover complete calendar years")
        if (dates["weekday_number"].astype(int) != days.dt.dayofweek + 1).any():
            problems.append("weekday_number is not Monday = 1 ... Sunday = 7")
        if (dates["year_month_sort"].astype(int) != days.dt.year * 100 + days.dt.month).any():
            problems.append("year_month_sort is wrong")
        if (dates["is_weekend"].astype(int) != (days.dt.dayofweek >= 5).astype(int)).any():
            problems.append("is_weekend is wrong")
    check("date_table_valid", problems)

    # KPIs recomputed from the CSV files must equal the SQL-derived expected values.
    kpis = expected["kpis"]
    total = len(referrals)
    actual = {"total_referrals": total, "data_quality_exceptions": len(exceptions),
              "referrals_with_duplicates": int((referrals["duplicate_record_count"].astype(int) > 0).sum())}
    actual.update({k: int((referrals[f] == "1").sum()) for k, f in COUNT_FLAGS.items()})
    problems = [f"{k}: snapshot {actual[k]} expected {kpis[k]['value']}" for k in COUNT_KPIS
                if actual[k] != kpis[k]["value"]]
    for rate, numerator in RATE_PARTS.items():
        value = actual[numerator] / total if total else None
        if (value is None) != (kpis[rate]["value"] is None) or \
                (value is not None and abs(value - kpis[rate]["value"]) > TOLERANCE):
            problems.append(f"{rate}: snapshot {value} expected {kpis[rate]['value']}")
    for median, column in zip(MEDIAN_KPIS, DURATIONS):
        values = referrals[column].dropna().astype(int)
        value = float(values.median()) if len(values) else None
        if value != kpis[median]["value"]:
            problems.append(f"{median}: snapshot {value} expected {kpis[median]['value']}")
    outcome_counts = referrals["outcome"].value_counts()
    problems += [f"outcome {k}" for k, v in expected["outcomes"].items() if int(outcome_counts.get(k, 0)) != v]
    funnel_actual = [total, int((referrals["contacted_flag"] == "1").sum()),
                     actual["scheduled_referrals"], actual["converted_referrals"]]
    problems += [f"funnel {s['stage']}" for s, v in zip(expected["referral_funnel"], funnel_actual)
                 if s["referrals"] != v]
    for key, (_, column) in GROUPED.items():
        if column:
            totals = referrals[column].value_counts()
            problems += [f"{key} {g['key']}" for g in expected[key] if int(totals.get(g["key"], 0)) != g["total_referrals"]]
    category = referrals["provider_id"].map(providers.set_index("provider_id")["service_category_id"]).value_counts()
    problems += [f"by_service_category {g['key']}" for g in expected["by_service_category"]
                 if int(category.get(g["key"], 0)) != g["total_referrals"]]
    month = referrals["referral_date"].str.slice(0, 7).value_counts()
    problems += [f"by_month {g['key']}" for g in expected["by_month"] if int(month.get(g["key"], 0)) != g["total_referrals"]]
    issues = exceptions["issue_type"].value_counts()
    problems += [f"issue {g['issue_type']}" for g in expected["data_quality_by_issue_type"]
                 if int(issues.get(g["issue_type"], 0)) != g["exceptions"]]
    check("kpis_match_expected", problems)

    check("file_sizes_below_limit",
          [f"{f}: {(folder / f).stat().st_size:,} bytes" for f in config.POWERBI_FILES.values()
           if (folder / f).stat().st_size >= config.POWERBI_MAX_FILE_BYTES])
    return results


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_snapshot(output_dir=config.OUTPUT_DATA_DIR, powerbi_dir=config.POWERBI_DIR):
    """Build, validate and publish the snapshot. Returns a summary dictionary."""
    output_dir, powerbi_dir = Path(output_dir), Path(powerbi_dir)
    database, phase3 = check_prerequisites(output_dir)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8"))
        connection.commit()
        tables = build_tables(connection)
        expected = build_expected_kpis(connection, tables)
    finally:
        connection.close()

    # The Phase 3 summary must describe the same data (guards against stale analytics).
    stale = [k for k in COUNT_KPIS if phase3.get("overall_kpis", {}).get(k) != expected["kpis"][k]["value"]]
    if stale:
        raise SnapshotError("Phase 3 summary does not match the current database "
                            f"({', '.join(stale)}). Rerun:\n  {ANALYZE_COMMAND}")

    powerbi_dir.mkdir(parents=True, exist_ok=True)
    data_dir = powerbi_dir / config.POWERBI_DATA_DIR.name
    staging = Path(tempfile.mkdtemp(prefix=".snapshot_staging_", dir=powerbi_dir))
    try:
        for table, file_name in config.POWERBI_FILES.items():
            write_csv(tables[table], COLUMNS[table], staging / file_name)
        write_json(expected, staging / config.POWERBI_EXPECTED_KPIS_FILE)
        results = validate_snapshot(staging, expected, database)
        failures = [(name, problems) for name, problems in results if problems]
        if failures:
            lines = ["Snapshot validation failed; the previous snapshot was left unchanged:"]
            lines += [f"  - {name}: {'; '.join(problems[:5])}" for name, problems in failures]
            raise SnapshotError("\n".join(lines))
        data_dir.mkdir(parents=True, exist_ok=True)
        sizes = {}
        for file_name in config.POWERBI_FILES.values():
            sizes[file_name] = (staging / file_name).stat().st_size
            os.replace(staging / file_name, data_dir / file_name)
        os.replace(staging / config.POWERBI_EXPECTED_KPIS_FILE, powerbi_dir / config.POWERBI_EXPECTED_KPIS_FILE)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"expected": expected, "checks": results, "sizes": sizes, "data_dir": data_dir,
            "expected_path": powerbi_dir / config.POWERBI_EXPECTED_KPIS_FILE}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export the validated Power BI data snapshot. " + SYNTHETIC_DATA_NOTICE)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DATA_DIR,
                        help="folder with the Phase 2 database and Phase 2/3 reports (default: data\\output)")
    parser.add_argument("--powerbi-dir", type=Path, default=config.POWERBI_DIR,
                        help="Power BI folder; CSVs go to its data subfolder (default: powerbi)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = run_snapshot(args.output_dir, args.powerbi_dir)
    except (SnapshotError, sqlite3.Error, OSError) as error:
        print("Power BI snapshot FAILED.", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1

    expected = summary["expected"]
    print("Power BI snapshot exported successfully.")
    print(f"  Folder : {display_path(summary['data_dir'])}")
    print(f"  {'File':<30}{'Rows':>10}{'Size (bytes)':>16}")
    for file_name, size in summary["sizes"].items():
        print(f"  {file_name:<30}{expected['snapshot']['row_counts'][file_name]:>10,}{size:>16,}")
    print(f"  {'Total':<30}{'':>10}{sum(summary['sizes'].values()):>16,}")
    print(f"  Validation : {len(summary['checks'])} checks passed")
    for name, _ in summary["checks"]:
        print(f"    passed  {name}")
    kpis = expected["kpis"]
    print(f"  Expected KPIs : {display_path(summary['expected_path'])}")
    print(f"    Total Referrals {kpis['total_referrals']['display']} | Conversion Rate "
          f"{kpis['conversion_rate']['display']} | Leakage Rate {kpis['leakage_rate']['display']} | "
          f"Active {kpis['active_referrals']['display']}")
    print("  The .pbix report is built manually in Power BI Desktop (powerbi/POWER_BI_BUILD_GUIDE.md).")
    print(f"NOTICE: {SYNTHETIC_DATA_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
