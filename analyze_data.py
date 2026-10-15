"""Build the Phase 3 analytics layer: SQL views, reconciliation and exports.

Steps
  1. Check that the Phase 2 database exists and that Phase 2 succeeded.
  2. Create or refresh the analytical views from sql/02_create_analytics_views.sql.
  3. Query every analytical view.
  4. Run reconciliation checks against the views and the Phase 2 tables.
  5. Only if every check passes, export deterministic CSV files and a JSON
     summary to data/output. A failed run writes a failed summary and keeps the
     previous exports.

Definitions are documented in sql/KPI_DEFINITIONS.md. All data is fully
synthetic and for portfolio and educational use only, not for clinical
decision-making.

Usage (PowerShell, from the project folder):
    .\\.venv\\Scripts\\python.exe analyze_data.py
"""

import argparse
import csv
import json
import math
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
from pathlib import Path

import pandas as pd

import config
from generate_data import SYNTHETIC_DATA_NOTICE

PREPARE_COMMAND = r".\.venv\Scripts\python.exe prepare_data.py"
GENERATE_COMMAND = r".\.venv\Scripts\python.exe generate_data.py --referrals 150000 --seed 42"
PHASE2_TABLES = ["service_categories", "facilities", "providers", "patients", "referrals",
                 "appointments", "data_quality_exceptions"]
FLOAT_DECIMALS = 6
TOLERANCE = 1e-9

GROUPED_COLUMNS = [
    "dimension_order", "dimension", "dimension_key", "dimension_label",
    "total_referrals", "contacted_referrals", "scheduled_referrals", "completed_referrals",
    "confirmed_external_outcomes", "converted_referrals", "active_referrals", "leaked_referrals",
    "scheduling_rate", "completion_rate", "conversion_rate", "leakage_rate",
    "external_referrals", "cancelled_referrals", "no_show_referrals", "rescheduled_referrals",
    "delayed_scheduling_referrals", "delayed_appointment_referrals",
    "referrals_with_duplicates", "referrals_with_data_quality_issues",
    "average_days_to_first_contact", "median_days_to_first_contact",
    "average_days_to_schedule", "median_days_to_schedule",
    "average_days_to_first_appointment", "median_days_to_first_appointment",
]
# Each export: (sort column or None, expected columns). Columns are a fixed contract.
EXPORTS = {
    "vw_referral_journey": ("referral_id", [
        "referral_id", "referral_record_id", "referral_date", "referral_month",
        "patient_id", "age_group", "gender", "insurance_type", "home_region",
        "urgency", "referral_source",
        "service_category_id", "service_category_name", "service_line", "target_days_to_appointment",
        "receiving_provider_id", "receiving_facility_id", "receiving_facility_name", "receiving_network_status",
        "referral_status", "closure_reason", "first_contact_date", "closed_date",
        "external_referral_flag", "confirmed_external_outcome_flag", "external_outcome_date",
        "appointment_count", "first_booking_date", "first_appointment_date", "last_appointment_date",
        "last_appointment_status", "completed_appointment_count", "cancelled_appointment_count",
        "no_show_appointment_count", "rescheduled_appointment_count", "future_scheduled_appointment_count",
        "first_completed_appointment_date",
        "days_since_referral", "days_to_first_contact", "days_to_schedule", "days_to_first_appointment",
        "invalid_duration_flag",
        "contacted_flag", "scheduled_flag", "completed_flag", "converted_flag", "active_in_progress_flag",
        "leakage_flag", "primary_leakage_reason", "outcome_category",
        "had_cancellation_flag", "had_no_show_flag", "had_reschedule_flag",
        "delayed_schedule_flag", "delayed_appointment_flag",
        "duplicate_record_count", "data_quality_issue_count", "has_data_quality_issue",
    ]),
    "vw_overall_kpis": (None, [
        "extract_date", "total_referrals", "contacted_referrals", "scheduled_referrals",
        "completed_referrals", "confirmed_external_outcomes", "converted_referrals",
        "active_referrals", "leaked_referrals", "unclassified_referrals",
        "scheduling_rate", "completion_rate", "conversion_rate", "leakage_rate",
        "external_referrals", "cancelled_referrals", "no_show_referrals", "rescheduled_referrals",
        "cancelled_referral_rate", "no_show_referral_rate",
        "delayed_scheduling_referrals", "delayed_appointment_referrals",
        "total_appointments", "completed_appointments", "cancelled_appointments",
        "no_show_appointments", "rescheduled_appointments", "scheduled_future_appointments",
        "appointment_cancellation_rate", "appointment_no_show_rate",
        "referrals_with_duplicates", "duplicate_records_removed",
        "referrals_with_data_quality_issues", "data_quality_exceptions",
        "average_days_to_first_contact", "median_days_to_first_contact",
        "average_days_to_schedule", "median_days_to_schedule",
        "average_days_to_first_appointment", "median_days_to_first_appointment",
    ]),
    "vw_referral_funnel": ("stage_order", [
        "stage_order", "stage", "referrals", "internal_referrals", "external_referrals",
        "share_of_total_referrals", "stage_definition",
    ]),
    "vw_monthly_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_service_category_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_facility_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_referral_source_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_urgency_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_insurance_metrics": ("dimension_key", GROUPED_COLUMNS),
    "vw_leakage_reason_metrics": ("priority", [
        "priority", "leakage_reason", "leaked_referrals", "share_of_leaked_referrals",
        "rate_of_total_referrals", "rule_summary",
    ]),
    "vw_turnaround_metrics": ("measure_order", [
        "measure_order", "measure", "start_event", "end_event", "total_referrals",
        "eligible_referrals", "missing_or_not_applicable", "average_days", "median_days",
        "min_days", "max_days", "invalid_duration_referrals",
    ]),
    "vw_data_quality_metrics": ("first_exception_id", [
        "first_exception_id", "issue_type", "exception_count", "resolved_exceptions",
        "unresolved_exceptions", "affected_referrals", "affected_referral_rate",
    ]),
}
GROUPED_VIEWS = {
    "vw_monthly_metrics": "Referral Month", "vw_service_category_metrics": "Service Category",
    "vw_facility_metrics": "Receiving Facility", "vw_referral_source_metrics": "Referral Source",
    "vw_urgency_metrics": "Urgency", "vw_insurance_metrics": "Insurance Type",
}
# Counts that must add up across every grouped view (each dimension is exhaustive).
ADDITIVE_COUNTS = [
    "total_referrals", "contacted_referrals", "scheduled_referrals", "completed_referrals",
    "confirmed_external_outcomes", "converted_referrals", "active_referrals", "leaked_referrals",
    "external_referrals", "cancelled_referrals", "no_show_referrals", "rescheduled_referrals",
    "delayed_scheduling_referrals", "delayed_appointment_referrals",
    "referrals_with_duplicates", "referrals_with_data_quality_issues",
]
# rate column -> (numerator column, denominator column)
REFERRAL_RATES = {
    "scheduling_rate": ("scheduled_referrals", "total_referrals"),
    "completion_rate": ("completed_referrals", "total_referrals"),
    "conversion_rate": ("converted_referrals", "total_referrals"),
    "leakage_rate": ("leaked_referrals", "total_referrals"),
}
OVERALL_RATES = {
    **REFERRAL_RATES,
    "cancelled_referral_rate": ("cancelled_referrals", "total_referrals"),
    "no_show_referral_rate": ("no_show_referrals", "total_referrals"),
    "appointment_cancellation_rate": ("cancelled_appointments", "total_appointments"),
    "appointment_no_show_rate": ("no_show_appointments", "total_appointments"),
}
TURNAROUND_MEASURES = ["days_to_first_contact", "days_to_schedule", "days_to_first_appointment"]


class AnalysisError(Exception):
    """A problem that stops the analysis before or during reconciliation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def display_path(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def same_number(a, b):
    """Compare numbers with a small tolerance; None only equals None."""
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)) \
            or (isinstance(b, float) and math.isnan(b)):
        return (a is None or (isinstance(a, float) and math.isnan(a))) and \
               (b is None or (isinstance(b, float) and math.isnan(b)))
    return abs(float(a) - float(b)) <= TOLERANCE


def expected_rate(numerator, denominator):
    if denominator is None or denominator == 0:
        return None
    return numerator / denominator


def clean(value):
    """Return a plain Python value: None for missing, rounded floats."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, float):
        return round(value, FLOAT_DECIMALS)
    if hasattr(value, "item"):  # numpy scalar
        return clean(value.item())
    return value


def format_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{FLOAT_DECIMALS}f}"
    return value


def add_check(checks, name, description, problems):
    """Record one reconciliation check. `problems` is a list of messages."""
    problems = [str(problem) for problem in problems]
    checks.append({
        "check": name,
        "description": description,
        "status": "failed" if problems else "passed",
        "problem_count": len(problems),
        "examples": problems[:5],
    })


def scalar(connection, sql):
    return connection.execute(sql).fetchone()[0]


def write_json(data, path):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Step 1-3: load prerequisites, create views, query them
# ---------------------------------------------------------------------------
def load_phase2_report(output_dir):
    database = output_dir / config.DATABASE_FILE
    report_path = output_dir / config.DATA_QUALITY_REPORT_FILE
    if not database.is_file():
        raise AnalysisError(
            f"Phase 2 database not found: {display_path(database)}.\n"
            f"Create it first with:\n  {GENERATE_COMMAND}\n  {PREPARE_COMMAND}")
    if not report_path.is_file():
        raise AnalysisError(
            f"Phase 2 report not found: {display_path(report_path)}. Rerun:\n  {PREPARE_COMMAND}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("pipeline_status") != "succeeded":
        raise AnalysisError(
            f"The last Phase 2 run did not succeed (pipeline_status = "
            f"{report.get('pipeline_status')!r}). Fix the data and rerun:\n  {PREPARE_COMMAND}")
    return report


def query_view(connection, view):
    order_by, _ = EXPORTS[view]
    sql = f"SELECT * FROM {view}" + (f" ORDER BY {order_by}" if order_by else "")
    cursor = connection.execute(sql)
    columns = [description[0] for description in cursor.description]
    return columns, cursor.fetchall()


def as_frame(result):
    columns, rows = result
    return pd.DataFrame.from_records(rows, columns=columns)


# ---------------------------------------------------------------------------
# Step 4: reconciliation
# ---------------------------------------------------------------------------
def reconcile(connection, results, phase2, parameters):
    """Run every reconciliation check and return the list of results."""
    checks = []
    frames = {view: as_frame(result) for view, result in results.items()}
    journey = frames["vw_referral_journey"]
    overall = frames["vw_overall_kpis"].iloc[0].to_dict()
    funnel = frames["vw_referral_funnel"]
    leakage = frames["vw_leakage_reason_metrics"]
    turnaround = frames["vw_turnaround_metrics"]
    quality = frames["vw_data_quality_metrics"]
    referral_count = scalar(connection, "SELECT COUNT(*) FROM referrals")
    appointment_count = scalar(connection, "SELECT COUNT(*) FROM appointments")

    def flag_sum(column):
        return int(journey[column].sum()) if len(journey) else 0

    # Parameters and Phase 2 hand-over
    expected_parameters = {
        "reporting_start_date": f"{config.REPORTING_START_DATE:%Y-%m-%d}",
        "reporting_end_date": f"{config.REPORTING_END_DATE:%Y-%m-%d}",
        "extract_date": f"{config.DATA_EXTRACT_DATE:%Y-%m-%d}",
        "follow_up_window_days": config.FOLLOW_UP_WINDOW_DAYS,
        "scheduling_delay_threshold_days": config.SCHEDULING_DELAY_THRESHOLD_DAYS,
    }
    add_check(checks, "parameters_match_config", "vw_analysis_parameters matches config.py",
              [f"{k}: view={parameters.get(k)!r} config={v!r}" for k, v in expected_parameters.items()
               if parameters.get(k) != v])
    phase2_counts = phase2.get("database", {}).get("table_row_counts", {})
    add_check(checks, "phase2_table_counts_unchanged",
              "Database table counts equal the counts recorded by Phase 2",
              [f"{t}: database={scalar(connection, f'SELECT COUNT(*) FROM {t}')} phase2={phase2_counts.get(t)}"
               for t in PHASE2_TABLES if scalar(connection, f"SELECT COUNT(*) FROM {t}") != phase2_counts.get(t)])

    # 1-2. One journey row per referral; totals match the referrals table
    problems = []
    if len(journey) != referral_count:
        problems.append(f"journey rows={len(journey)} referrals table={referral_count}")
    if len(journey) and not journey["referral_id"].is_unique:
        problems.append("referral_id repeats in vw_referral_journey")
    add_check(checks, "journey_one_row_per_referral",
              "vw_referral_journey has exactly one row per processed referral", problems)
    add_check(checks, "total_referrals_match", "Overall total_referrals equals the referrals table count",
              [] if overall["total_referrals"] == referral_count
              else [f"overall={overall['total_referrals']} table={referral_count}"])

    # 3-6. Outcome flags and leakage reasons
    def both(a, b):
        return journey.loc[(journey[a] == 1) & (journey[b] == 1), "referral_id"].tolist() if len(journey) else []

    add_check(checks, "converted_never_leaked", "No referral is both converted and leaked",
              both("converted_flag", "leakage_flag"))
    add_check(checks, "active_never_leaked", "No referral is both active and leaked",
              both("active_in_progress_flag", "leakage_flag"))
    add_check(checks, "converted_never_active", "No referral is both converted and active",
              both("converted_flag", "active_in_progress_flag"))
    reasons = set(leakage["leakage_reason"])
    if len(journey):
        leaked = journey[journey["leakage_flag"] == 1]
        bad = leaked[leaked["primary_leakage_reason"].isna()
                     | ~leaked["primary_leakage_reason"].isin(reasons)]["referral_id"].tolist()
        not_leaked = journey[journey["leakage_flag"] == 0]
        stray = not_leaked[not_leaked["primary_leakage_reason"].notna()]["referral_id"].tolist()
    else:
        bad, stray = [], []
    add_check(checks, "leaked_have_one_reason",
              "Every leaked referral has exactly one documented primary leakage reason", bad)
    add_check(checks, "non_leaked_have_no_reason", "Referrals that are not leaked have no leakage reason", stray)

    # 7. Leakage reasons reconcile
    problems = []
    if int(leakage["leaked_referrals"].sum()) != overall["leaked_referrals"]:
        problems.append(f"reason total={int(leakage['leaked_referrals'].sum())} "
                        f"overall leaked={overall['leaked_referrals']}")
    if overall["leaked_referrals"] != flag_sum("leakage_flag"):
        problems.append("overall leaked differs from journey leakage_flag sum")
    journey_reasons = journey["primary_leakage_reason"].value_counts() if len(journey) else pd.Series(dtype=int)
    for row in leakage.itertuples():
        if row.leaked_referrals != int(journey_reasons.get(row.leakage_reason, 0)):
            problems.append(f"{row.leakage_reason}: view={row.leaked_referrals} "
                            f"journey={int(journey_reasons.get(row.leakage_reason, 0))}")
    add_check(checks, "leakage_reasons_reconcile",
              "Leakage-reason counts sum to total leaked referrals and match the journey", problems)

    # Every leakage label agrees with the condition it names
    window = config.FOLLOW_UP_WINDOW_DAYS
    reason_conditions = {
        "External Outcome Missing": lambda f: (f["referral_status"] == "Sent External")
        & (f["confirmed_external_outcome_flag"] == 0),
        "Expired Before Completion": lambda f: f["referral_status"] == "Expired",
        "Cancelled Without Successful Rebooking": lambda f: f["last_appointment_status"] == "Cancelled",
        "No-Show Without Successful Follow-Up": lambda f: f["last_appointment_status"] == "No-Show",
        "Declined Before Scheduling": lambda f: f["referral_status"] == "Declined",
        "Not Scheduled Within 30 Days": lambda f: (f["appointment_count"] == 0) & (f["scheduled_flag"] == 0)
        & (f["days_since_referral"] >= window),
    }
    problems = []
    for reason, condition in reason_conditions.items():
        rows = journey[journey["primary_leakage_reason"] == reason] if len(journey) else journey
        if len(rows):
            problems += [f"{reason}: {referral_id}" for referral_id in rows.loc[~condition(rows), "referral_id"]]
    add_check(checks, "leakage_reasons_match_conditions",
              "Every leakage reason agrees with its condition (e.g. Not Scheduled requires zero appointments)",
              problems)
    if len(journey):
        future = journey[(journey["future_scheduled_appointment_count"] > 0) & (journey["converted_flag"] == 0)]
        wrong = future.loc[(future["active_in_progress_flag"] != 1) | (future["leakage_flag"] != 0), "referral_id"]
    else:
        wrong = []
    add_check(checks, "future_scheduled_never_leaked",
              "Every non-converted referral with a future Scheduled appointment is active, never leaked",
              list(wrong))

    # Outcome categories cover every referral
    categories = journey["outcome_category"].value_counts() if len(journey) else pd.Series(dtype=int)
    problems = []
    for name, column in [("Converted", "converted_referrals"), ("Active", "active_referrals"),
                         ("Leaked", "leaked_referrals"), ("Unclassified", "unclassified_referrals")]:
        if int(categories.get(name, 0)) != overall[column]:
            problems.append(f"{name}: journey={int(categories.get(name, 0))} overall={overall[column]}")
    if (overall["converted_referrals"] + overall["active_referrals"] + overall["leaked_referrals"]
            + overall["unclassified_referrals"]) != overall["total_referrals"]:
        problems.append("converted + active + leaked + unclassified != total")
    add_check(checks, "outcome_categories_reconcile",
              "Converted, active, leaked and unclassified referrals add up to the total", problems)

    # 8. Grouped totals reconcile to overall
    problems = []
    for view, dimension in GROUPED_VIEWS.items():
        frame = frames[view]
        if len(frame) and (frame["dimension"] != dimension).any():
            problems.append(f"{view}: rows from another dimension")
        if len(frame) and (frame["dimension_key"].isna().any() or not frame["dimension_key"].is_unique):
            problems.append(f"{view}: missing or repeated group keys")
        for column in ADDITIVE_COUNTS:
            total = int(frame[column].sum()) if len(frame) else 0
            if total != overall[column]:
                problems.append(f"{view}.{column}: groups={total} overall={overall[column]}")
    add_check(checks, "grouped_totals_reconcile",
              "Every grouped view sums to the overall totals (dimensions are exhaustive; missing = Unknown)",
              problems)

    # 9. Status-based counts reconcile
    table_status = dict(connection.execute(
        "SELECT referral_status, COUNT(*) FROM referrals GROUP BY referral_status").fetchall())
    journey_status = journey["referral_status"].value_counts().to_dict() if len(journey) else {}
    add_check(checks, "status_counts_reconcile", "Referral status counts in the journey match the referrals table",
              [f"{s}: journey={journey_status.get(s, 0)} table={n}" for s, n in table_status.items()
               if journey_status.get(s, 0) != n])

    # 10. Referral-level flags match the appointments table and never exceed the total
    direct = {
        "scheduled_referrals": "SELECT COUNT(DISTINCT referral_id) FROM appointments",
        "completed_referrals": "SELECT COUNT(DISTINCT referral_id) FROM appointments WHERE appointment_status = 'Completed'",
        "cancelled_referrals": "SELECT COUNT(DISTINCT referral_id) FROM appointments WHERE appointment_status = 'Cancelled'",
        "no_show_referrals": "SELECT COUNT(DISTINCT referral_id) FROM appointments WHERE appointment_status = 'No-Show'",
        "rescheduled_referrals": "SELECT COUNT(DISTINCT referral_id) FROM appointments WHERE appointment_status = 'Rescheduled'",
        "confirmed_external_outcomes": "SELECT COUNT(*) FROM referrals WHERE referral_status = 'Sent External' "
                                       "AND closure_reason = 'External Visit Confirmed'",
    }
    problems = [f"{column}: view={overall[column]} direct={scalar(connection, sql)}"
                for column, sql in direct.items() if overall[column] != scalar(connection, sql)]
    problems += [f"{column}={overall[column]} exceeds total" for column in direct
                 if overall[column] > overall["total_referrals"]]
    add_check(checks, "referral_level_counts_reconcile",
              "Referral-level scheduled/completed/cancellation/no-show counts match the base tables "
              "and never exceed total referrals", problems)

    # 11. Appointment-level counts reconcile
    table_appointments = dict(connection.execute(
        "SELECT appointment_status, COUNT(*) FROM appointments GROUP BY appointment_status").fetchall())
    problems = []
    for status, column in [("Completed", "completed_appointments"), ("Cancelled", "cancelled_appointments"),
                           ("No-Show", "no_show_appointments"), ("Rescheduled", "rescheduled_appointments"),
                           ("Scheduled", "scheduled_future_appointments")]:
        if overall[column] != table_appointments.get(status, 0):
            problems.append(f"{column}: view={overall[column]} table={table_appointments.get(status, 0)}")
    if overall["total_appointments"] != appointment_count:
        problems.append(f"total_appointments={overall['total_appointments']} table={appointment_count}")
    if flag_sum("appointment_count") != appointment_count:
        problems.append(f"journey appointment_count sum={flag_sum('appointment_count')} table={appointment_count}")
    add_check(checks, "appointment_level_counts_reconcile",
              "Appointment-level status counts match the appointments table", problems)

    # 12. Rates use the documented numerators and denominators
    problems = []
    for rate, (numerator, denominator) in OVERALL_RATES.items():
        if not same_number(overall[rate], expected_rate(overall[numerator], overall[denominator])):
            problems.append(f"overall {rate}={overall[rate]}")
    for view in GROUPED_VIEWS:
        for row in frames[view].to_dict("records"):
            for rate, (numerator, denominator) in REFERRAL_RATES.items():
                if not same_number(row[rate], expected_rate(row[numerator], row[denominator])):
                    problems.append(f"{view} {row['dimension_key']} {rate}={row[rate]}")
    total_leaked = overall["leaked_referrals"]
    for row in leakage.to_dict("records"):
        if not same_number(row["share_of_leaked_referrals"], expected_rate(row["leaked_referrals"], total_leaked)):
            problems.append(f"leakage share {row['leakage_reason']}")
        if not same_number(row["rate_of_total_referrals"],
                           expected_rate(row["leaked_referrals"], overall["total_referrals"])):
            problems.append(f"leakage rate {row['leakage_reason']}")
    for row in funnel.to_dict("records"):
        if not same_number(row["share_of_total_referrals"], expected_rate(row["referrals"], overall["total_referrals"])):
            problems.append(f"funnel share {row['stage']}")
    for row in quality.to_dict("records"):
        if not same_number(row["affected_referral_rate"], expected_rate(row["affected_referrals"], referral_count)):
            problems.append(f"data quality rate {row['issue_type']}")
    add_check(checks, "rates_use_correct_denominators",
              "Every rate equals its documented numerator / denominator (NULL when the denominator is 0)", problems)

    # 13. Turnaround uses only nonmissing values
    problems = []
    for row in turnaround.to_dict("records"):
        values = journey[row["measure"]].dropna().tolist() if len(journey) else []
        if row["eligible_referrals"] != len(values):
            problems.append(f"{row['measure']}: eligible={row['eligible_referrals']} nonmissing={len(values)}")
        if row["missing_or_not_applicable"] != overall["total_referrals"] - len(values):
            problems.append(f"{row['measure']}: missing count")
        if not same_number(row["average_days"], statistics.fmean(values) if values else None):
            problems.append(f"{row['measure']}: average={row['average_days']}")
        if not same_number(row["median_days"], statistics.median(values) if values else None):
            problems.append(f"{row['measure']}: median={row['median_days']}")
        for kind in ("average", "median"):
            overall_value = overall[f"{kind}_days_to_{row['measure'][len('days_to_'):]}"]
            if not same_number(overall_value, row[f"{kind}_days"]):
                problems.append(f"overall {kind} {row['measure']} differs from vw_turnaround_metrics")
    add_check(checks, "turnaround_uses_nonmissing_values",
              "Turnaround averages and medians match an independent calculation over nonmissing values only",
              problems)

    # 14. Data-quality counts reconcile to Phase 2
    exceptions_total = scalar(connection, "SELECT COUNT(*) FROM data_quality_exceptions")
    referral_exceptions = scalar(connection,
                                 "SELECT COUNT(*) FROM data_quality_exceptions WHERE entity_type = 'referral'")
    phase2_exceptions = phase2.get("exceptions", {})
    problems = []
    if overall["data_quality_exceptions"] != exceptions_total or exceptions_total != phase2_exceptions.get("total"):
        problems.append(f"exceptions: view={overall['data_quality_exceptions']} table={exceptions_total} "
                        f"phase2={phase2_exceptions.get('total')}")
    if flag_sum("data_quality_issue_count") != referral_exceptions:
        problems.append(f"sum data_quality_issue_count={flag_sum('data_quality_issue_count')} "
                        f"referral exceptions={referral_exceptions}")
    if overall["referrals_with_data_quality_issues"] != phase2_exceptions.get("referrals_with_issues"):
        problems.append(f"referrals with issues={overall['referrals_with_data_quality_issues']} "
                        f"phase2={phase2_exceptions.get('referrals_with_issues')}")
    by_issue = {k: v for k, v in phase2_exceptions.get("by_issue_type", {}).items() if v}
    view_issues = dict(zip(quality["issue_type"], quality["exception_count"].astype(int))) if len(quality) else {}
    if view_issues != by_issue:
        problems.append(f"by issue type: view={view_issues} phase2={by_issue}")
    add_check(checks, "data_quality_reconciles_to_phase2",
              "Data-quality exception counts match the exceptions table and the Phase 2 report", problems)

    # 15. Duplicate counts reconcile to Phase 2
    phase2_duplicates = phase2.get("duplicates", {})
    duplicate_exceptions = scalar(connection, "SELECT COUNT(*) FROM data_quality_exceptions "
                                              "WHERE issue_type = 'duplicate_referral_record'")
    problems = []
    if not (overall["duplicate_records_removed"] == duplicate_exceptions
            == phase2_duplicates.get("removed_duplicate_rows")):
        problems.append(f"removed duplicates: view={overall['duplicate_records_removed']} "
                        f"exceptions={duplicate_exceptions} phase2={phase2_duplicates.get('removed_duplicate_rows')}")
    if overall["referrals_with_duplicates"] != phase2_duplicates.get("referral_ids_with_duplicates"):
        problems.append(f"referrals with duplicates: view={overall['referrals_with_duplicates']} "
                        f"phase2={phase2_duplicates.get('referral_ids_with_duplicates')}")
    add_check(checks, "duplicates_reconcile_to_phase2",
              "Duplicate counts match the exceptions table and the Phase 2 report", problems)

    # 16. Funnel stages follow the documented definitions
    expected_funnel = [overall["total_referrals"], flag_sum("contacted_flag"),
                       flag_sum("scheduled_flag"), flag_sum("converted_flag")]
    problems = [f"stage {row['stage_order']}: {row['referrals']} != {expected}"
                for row, expected in zip(funnel.to_dict("records"), expected_funnel)
                if row["referrals"] != expected]
    problems += [f"stage {row['stage_order']}: internal + external != total"
                 for row in funnel.to_dict("records")
                 if row["internal_referrals"] + row["external_referrals"] != row["referrals"]]
    if len(funnel) != 4:
        problems.append(f"expected 4 funnel stages, found {len(funnel)}")
    elif funnel.iloc[3]["external_referrals"] != overall["confirmed_external_outcomes"]:
        problems.append("final stage external count differs from confirmed external outcomes")
    add_check(checks, "funnel_matches_definitions",
              "Funnel stages equal total, contacted, scheduled and converted referrals", problems)

    # 17. Rates between 0 and 1
    problems = []
    for view, frame in frames.items():
        for column in frame.columns:
            if column.endswith("_rate") or column.startswith("share_"):
                values = frame[column].dropna()
                problems += [f"{view}.{column}={v}" for v in values if v < 0 or v > 1]
    add_check(checks, "rates_between_0_and_1", "No rate or share is below 0 or above 1", problems)

    # 18. No negative durations
    problems = []
    for column in TURNAROUND_MEASURES:
        if len(journey) and (journey[column].dropna() < 0).any():
            problems.append(f"vw_referral_journey.{column} has negative values")
    if len(turnaround) and (turnaround["min_days"].dropna() < 0).any():
        problems.append("vw_turnaround_metrics has a negative minimum")
    add_check(checks, "no_negative_durations",
              "No turnaround duration is negative (invalid ones are excluded and flagged)", problems)

    # 19. Zero denominators return NULL
    problems = []
    rows_to_check = [("overall", overall)] + [
        (view, row) for view in GROUPED_VIEWS for row in frames[view].to_dict("records")]
    for name, row in rows_to_check:
        if row["total_referrals"] == 0:
            problems += [f"{name}.{rate} not NULL" for rate in REFERRAL_RATES if row[rate] is not None
                         and not (isinstance(row[rate], float) and math.isnan(row[rate]))]
    if overall["total_appointments"] == 0:
        problems += [f"overall.{rate} not NULL" for rate in ("appointment_cancellation_rate",
                                                             "appointment_no_show_rate")
                     if not same_number(overall[rate], None)]
    if total_leaked == 0:
        problems += [f"leakage share {row['leakage_reason']} not NULL" for row in leakage.to_dict("records")
                     if not same_number(row["share_of_leaked_referrals"], None)]
    add_check(checks, "zero_denominators_return_null", "Rates are NULL (not 0) when their denominator is 0",
              problems)

    # 20. Exports have stable columns and ordering
    problems = []
    for view, (order_by, expected_columns) in EXPORTS.items():
        columns, rows = results[view]
        if columns != expected_columns:
            problems.append(f"{view}: columns {columns} differ from the documented export")
        if order_by:
            keys = [row[columns.index(order_by)] for row in rows]
            if keys != sorted(keys) or len(set(keys)) != len(keys):
                problems.append(f"{view}: rows not uniquely ordered by {order_by}")
    if len(frames["vw_overall_kpis"]) != 1:
        problems.append("vw_overall_kpis must return exactly one row")
    add_check(checks, "exports_have_stable_columns_and_order",
              "Every export has its documented columns and a unique, stable sort order", problems)
    return checks


# ---------------------------------------------------------------------------
# Step 5: outputs
# ---------------------------------------------------------------------------
def write_export(result, path):
    columns, rows = result
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([format_csv_value(clean(value)) for value in row])


def records(result):
    columns, rows = result
    return [{column: clean(value) for column, value in zip(columns, row)} for row in rows]


def build_summary(results, checks, parameters):
    overall = records(results["vw_overall_kpis"])[0]
    return {
        "project": "Healthcare Referral Leakage Analytics",
        "phase": 3,
        "analytics_status": "succeeded",
        "synthetic_data": True,
        "non_clinical_use": SYNTHETIC_DATA_NOTICE,
        "definitions": "sql/KPI_DEFINITIONS.md",
        "parameters": parameters,
        "overall_kpis": overall,
        "outcome_breakdown": {
            "converted": overall["converted_referrals"],
            "active": overall["active_referrals"],
            "leaked": overall["leaked_referrals"],
            "unclassified": overall["unclassified_referrals"],
        },
        "referral_funnel": records(results["vw_referral_funnel"]),
        "leakage_reasons": records(results["vw_leakage_reason_metrics"]),
        "turnaround": records(results["vw_turnaround_metrics"]),
        "reconciliation": {
            "status": "passed",
            "checks_run": len(checks),
            "checks_failed": 0,
            "checks": checks,
        },
        "exports": {config.ANALYTICS_EXPORT_FILES[view]: len(result[1]) for view, result in results.items()},
    }


def failed_summary(message, checks):
    failures = [check for check in checks if check["status"] == "failed"]
    return {
        "project": "Healthcare Referral Leakage Analytics",
        "phase": 3,
        "analytics_status": "failed",
        "synthetic_data": True,
        "non_clinical_use": SYNTHETIC_DATA_NOTICE,
        "error": message,
        "exports_replaced": False,
        "note": "CSV exports from the last successful run were left unchanged.",
        "reconciliation": {
            "status": "failed" if checks else "not run",
            "checks_run": len(checks),
            "checks_failed": len(failures),
            "checks": checks,
        },
    }


def run_analysis(output_dir=config.OUTPUT_DATA_DIR):
    """Run Phase 3 and return the summary dictionary."""
    output_dir = Path(output_dir)
    checks = []
    staging_dir = None
    try:
        phase2 = load_phase2_report(output_dir)
        connection = sqlite3.connect(output_dir / config.DATABASE_FILE)
        try:
            missing = [t for t in PHASE2_TABLES if scalar(
                connection, f"SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = '{t}'") == 0]
            if missing:
                raise AnalysisError(f"Phase 2 tables missing from the database: {', '.join(missing)}. "
                                    f"Rerun:\n  {PREPARE_COMMAND}")
            connection.executescript(config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8"))
            connection.commit()
            results = {view: query_view(connection, view) for view in config.ANALYTICS_EXPORT_FILES}
            parameter_cursor = connection.execute("SELECT * FROM vw_analysis_parameters")
            parameters = dict(zip([d[0] for d in parameter_cursor.description], parameter_cursor.fetchone()))
            checks = reconcile(connection, results, phase2, parameters)
        finally:
            connection.close()

        failures = [check for check in checks if check["status"] == "failed"]
        if failures:
            lines = ["Reconciliation failed:"]
            lines += [f"  - {c['check']}: {c['description']} ({c['problem_count']} problem(s); "
                      f"e.g. {'; '.join(c['examples'])})" for c in failures]
            raise AnalysisError("\n".join(lines))

        staging_dir = Path(tempfile.mkdtemp(prefix=".phase3_staging_", dir=output_dir))
        for view, result in results.items():
            write_export(result, staging_dir / config.ANALYTICS_EXPORT_FILES[view])
        summary = build_summary(results, checks, parameters)
        write_json(summary, staging_dir / config.ANALYTICS_SUMMARY_FILE)
        for file_name in list(config.ANALYTICS_EXPORT_FILES.values()) + [config.ANALYTICS_SUMMARY_FILE]:
            os.replace(staging_dir / file_name, output_dir / file_name)
        return summary
    except (AnalysisError, sqlite3.Error, OSError) as error:
        message = str(error) if isinstance(error, AnalysisError) else f"{type(error).__name__}: {error}"
        summary = failed_summary(message, checks)
        if output_dir.is_dir():
            temporary = output_dir / f".{config.ANALYTICS_SUMMARY_FILE}.tmp"
            write_json(summary, temporary)
            os.replace(temporary, output_dir / config.ANALYTICS_SUMMARY_FILE)
        return summary
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Create the Phase 3 analytical views, reconcile KPIs and export results. "
                    + SYNTHETIC_DATA_NOTICE)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DATA_DIR,
                        help="folder with the Phase 2 database and report; exports are written here "
                             "(default: data\\output)")
    return parser.parse_args(argv)


def percent(value):
    return "n/a" if value is None else f"{value:.1%}"


def main(argv=None):
    args = parse_args(argv)
    summary = run_analysis(args.output_dir)
    if summary["analytics_status"] != "succeeded":
        print("Phase 3 analytics FAILED.", file=sys.stderr)
        print(summary["error"], file=sys.stderr)
        print("Previous exports were left unchanged.", file=sys.stderr)
        return 1

    kpis = summary["overall_kpis"]
    print("Phase 3 analytics completed successfully.")
    print(f"  Views created        : {len(config.ANALYTICS_EXPORT_FILES)} exported views plus helper views")
    print(f"  Reconciliation       : {summary['reconciliation']['checks_run']} checks passed")
    print(f"  Total referrals      : {kpis['total_referrals']:,}")
    print(f"  Converted            : {kpis['converted_referrals']:,} ({percent(kpis['conversion_rate'])})")
    print(f"  Leaked               : {kpis['leaked_referrals']:,} ({percent(kpis['leakage_rate'])})")
    print(f"  Active / in progress : {kpis['active_referrals']:,}")
    print(f"  Scheduling rate      : {percent(kpis['scheduling_rate'])}")
    print(f"  Completion rate      : {percent(kpis['completion_rate'])}")
    print("  Leakage reasons:")
    for reason in summary["leakage_reasons"]:
        print(f"    {reason['priority']}. {reason['leakage_reason']:<42}{reason['leaked_referrals']:>8,}")
    print(f"  Exports              : {len(summary['exports'])} CSV files in {display_path(args.output_dir)}")
    print(f"  Summary              : {display_path(args.output_dir / config.ANALYTICS_SUMMARY_FILE)}")
    print(f"NOTICE: {SYNTHETIC_DATA_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
