"""Phase 3 tests for the analytical views, reconciliation and exports."""

import hashlib
import json
import shutil
import sqlite3
import statistics

import pandas as pd
import pytest

import analyze_data
import config
import generate_data
import prepare_data

REQUIRED_VIEWS = [
    "vw_referral_journey", "vw_overall_kpis", "vw_referral_funnel", "vw_monthly_metrics",
    "vw_service_category_metrics", "vw_facility_metrics", "vw_referral_source_metrics",
    "vw_urgency_metrics", "vw_insurance_metrics", "vw_leakage_reason_metrics",
    "vw_turnaround_metrics", "vw_data_quality_metrics",
]
PHASE2_TABLES = analyze_data.PHASE2_TABLES


# ---------------------------------------------------------------------------
# Small hand-built databases
# ---------------------------------------------------------------------------
def create_schema(db_path):
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(config.SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
    return connection


def add_masters(connection):
    connection.executemany("INSERT INTO service_categories VALUES (?, ?, ?, ?)", [
        ("SVC001", "Cardiology", "Medical Specialty", 21),
        ("SVC002", "Neurology", "Medical Specialty", 28),
    ])
    connection.executemany("INSERT INTO facilities VALUES (?, ?, ?, ?, ?)", [
        ("FAC001", "Test Internal Clinic", "Hospital", "North", "In-Network"),
        ("FAC002", "Test External Group", "Independent Practice", "South", "Out-of-Network"),
    ])
    connection.executemany("INSERT INTO providers VALUES (?, ?, ?, ?, ?)", [
        ("PRV001", "Cardiology Provider 001", "Physician", "FAC001", "SVC001"),
        ("PRV002", "Cardiology Provider 002", "Physician", "FAC002", "SVC001"),
        ("PRV003", "Neurology Provider 003", "Physician", "FAC001", "SVC002"),
    ])
    connection.executemany("INSERT INTO patients VALUES (?, ?, ?, ?, ?)", [
        ("PAT000001", "35-49", "Female", "Commercial", "North"),
        ("PAT000002", "65-74", "Male", "Medicare", "South"),
    ])


def add_referral(connection, number, status="Pending", referral_date="2025-06-02", first_contact="2025-06-03",
                 closure_reason=None, closed_date=None, external=False, category="SVC001",
                 source="Primary Care", urgency="Routine", patient="PAT000001", duplicates=0, issues=0,
                 appointments=()):
    """Insert one referral; appointments are (status, booked_date, appointment_date) tuples."""
    referral_id = f"REF{number:07d}"
    facility, provider = ("FAC002", "PRV002") if external else ("FAC001", "PRV001")
    if category == "SVC002":
        provider = "PRV003"
    connection.execute(
        "INSERT INTO referrals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (referral_id, f"REC{number:07d}", patient, category, facility, provider, source, urgency,
         referral_date, first_contact, status, closure_reason, closed_date, duplicates, issues,
         1 if issues else 0))
    for sequence, (appointment_status, booked, day) in enumerate(appointments, start=1):
        connection.execute(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"APT{number:05d}{sequence:02d}", referral_id, sequence, facility, provider, booked,
             f"{day} 09:00:00", day, appointment_status,
             "Patient Request" if appointment_status in ("Cancelled", "Rescheduled") else None))
    return referral_id


def create_views(connection):
    connection.executescript(config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8"))
    connection.commit()


def journey_row(connection, referral_id):
    cursor = connection.execute("SELECT * FROM vw_referral_journey WHERE referral_id = ?", (referral_id,))
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, cursor.fetchone()))


def view_rows(connection, view):
    cursor = connection.execute(f"SELECT * FROM {view}")
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@pytest.fixture
def mini(tmp_path):
    connection = create_schema(tmp_path / "mini.db")
    add_masters(connection)
    yield connection
    connection.close()


def classify(mini, **referral):
    referral_id = add_referral(mini, 1, **referral)
    create_views(mini)
    return journey_row(mini, referral_id)


# ---------------------------------------------------------------------------
# Views exist and are safely recreated
# ---------------------------------------------------------------------------
def test_required_views_exist_and_recreate_safely(mini):
    add_referral(mini, 1, status="Completed", closure_reason="Appointment Completed", closed_date="2025-06-20",
                 appointments=[("Completed", "2025-06-05", "2025-06-20")])
    create_views(mini)
    create_views(mini)
    views = {row[0] for row in mini.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
    assert set(REQUIRED_VIEWS) <= views
    tables = {row[0] for row in mini.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(PHASE2_TABLES)
    assert mini.execute("SELECT COUNT(*) FROM referrals").fetchone()[0] == 1
    for view in REQUIRED_VIEWS:
        mini.execute(f"SELECT * FROM {view}").fetchall()


def test_views_sql_never_drops_tables():
    sql = config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8").upper()
    assert "DROP TABLE" not in sql
    assert "DELETE FROM" not in sql and "UPDATE " not in sql


# ---------------------------------------------------------------------------
# Journey grain
# ---------------------------------------------------------------------------
def test_multiple_appointments_do_not_multiply_referrals(mini):
    add_referral(mini, 1, status="Completed", closure_reason="Appointment Completed", closed_date="2025-07-20",
                 appointments=[("Rescheduled", "2025-06-05", "2025-06-20"),
                               ("No-Show", "2025-06-10", "2025-07-01"),
                               ("Completed", "2025-07-02", "2025-07-20")])
    add_referral(mini, 2, status="Expired", first_contact=None, closure_reason="Referral Expired",
                 closed_date="2025-08-31")
    create_views(mini)
    assert mini.execute("SELECT COUNT(*), COUNT(DISTINCT referral_id) FROM vw_referral_journey").fetchone() == (2, 2)
    overall = view_rows(mini, "vw_overall_kpis")[0]
    assert overall["total_referrals"] == 2
    assert overall["total_appointments"] == 3
    assert overall["scheduled_referrals"] == 1
    row = journey_row(mini, "REF0000001")
    assert row["appointment_count"] == 3
    assert row["last_appointment_status"] == "Completed"
    assert (row["rescheduled_appointment_count"], row["no_show_appointment_count"]) == (1, 1)


# ---------------------------------------------------------------------------
# Leakage rules, one at a time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("referral, expected_reason", [
    (dict(status="Sent External", external=True), "External Outcome Missing"),
    (dict(status="Expired", first_contact=None, closure_reason="Referral Expired", closed_date="2025-08-31"),
     "Expired Before Completion"),
    (dict(status="Cancelled", closure_reason="Appointment Cancelled - Not Rebooked", closed_date="2025-07-01",
          appointments=[("Cancelled", "2025-06-05", "2025-06-25")]), "Cancelled Without Successful Rebooking"),
    (dict(status="Cancelled", closure_reason="No-Show - Not Rebooked", closed_date="2025-07-01",
          appointments=[("No-Show", "2025-06-05", "2025-06-25")]), "No-Show Without Successful Follow-Up"),
    (dict(status="Declined", closure_reason="Patient Declined", closed_date="2025-06-04"),
     "Declined Before Scheduling"),
    (dict(status="Pending", referral_date="2025-11-01", first_contact="2025-11-03"),
     "Not Scheduled Within 30 Days"),
])
def test_each_leakage_rule(mini, referral, expected_reason):
    row = classify(mini, **referral)
    assert row["leakage_flag"] == 1
    assert row["primary_leakage_reason"] == expected_reason
    assert row["converted_flag"] == 0 and row["active_in_progress_flag"] == 0
    assert row["outcome_category"] == "Leaked"


@pytest.mark.parametrize("referral, expected_reason", [
    # Expired (priority 2) wins over a cancelled last appointment (priority 3).
    (dict(status="Expired", closure_reason="Referral Expired", closed_date="2025-08-31",
          appointments=[("Cancelled", "2025-06-05", "2025-06-25")]), "Expired Before Completion"),
    # A no-show (priority 4) wins over a decline (priority 5).
    (dict(status="Declined", closure_reason="Patient Declined", closed_date="2025-07-01",
          appointments=[("No-Show", "2025-06-05", "2025-06-25")]), "No-Show Without Successful Follow-Up"),
    # Missing external outcome (priority 1) wins over everything else.
    (dict(status="Sent External", external=True, appointments=[("Cancelled", "2025-06-05", "2025-06-25")]),
     "External Outcome Missing"),
])
def test_leakage_reason_priority(mini, referral, expected_reason):
    row = classify(mini, **referral)
    assert row["primary_leakage_reason"] == expected_reason


def test_cancellation_then_no_show_uses_last_appointment(mini):
    row = classify(mini, status="Cancelled", closure_reason="No-Show - Not Rebooked", closed_date="2025-07-20",
                   appointments=[("Cancelled", "2025-06-05", "2025-06-20"), ("No-Show", "2025-06-18", "2025-07-10")])
    assert row["primary_leakage_reason"] == "No-Show Without Successful Follow-Up"
    assert row["had_cancellation_flag"] == 1 and row["had_no_show_flag"] == 1


# ---------------------------------------------------------------------------
# Successful and active referrals are never leaked
# ---------------------------------------------------------------------------
def test_confirmed_external_outcome_is_converted(mini):
    row = classify(mini, status="Sent External", external=True, closure_reason="External Visit Confirmed",
                   closed_date="2025-07-15")
    assert row["confirmed_external_outcome_flag"] == 1
    assert row["converted_flag"] == 1 and row["leakage_flag"] == 0
    assert row["primary_leakage_reason"] is None
    assert row["external_outcome_date"] == "2025-07-15"


def test_confirmed_external_outcome_without_closed_date_is_still_converted(mini):
    row = classify(mini, status="Sent External", external=True, closure_reason="External Visit Confirmed")
    assert row["converted_flag"] == 1 and row["external_outcome_date"] is None


def test_cancellation_with_successful_rebooking_is_converted(mini):
    row = classify(mini, status="Completed", closure_reason="Appointment Completed", closed_date="2025-07-15",
                   appointments=[("Cancelled", "2025-06-05", "2025-06-20"), ("Completed", "2025-06-18", "2025-07-15")])
    assert row["converted_flag"] == 1 and row["leakage_flag"] == 0
    assert row["had_cancellation_flag"] == 1


def test_no_show_followed_by_completion_is_converted(mini):
    row = classify(mini, status="Completed", closure_reason="Appointment Completed", closed_date="2025-07-15",
                   appointments=[("No-Show", "2025-06-05", "2025-06-20"), ("Completed", "2025-06-22", "2025-07-15")])
    assert row["converted_flag"] == 1 and row["leakage_flag"] == 0


@pytest.mark.parametrize("referral", [
    # Future appointment after the extract date.
    dict(status="Scheduled", referral_date="2025-12-01", first_contact="2025-12-02",
         appointments=[("Scheduled", "2025-12-05", "2026-02-10")]),
    # Not yet booked, less than 30 days old.
    dict(status="Pending", referral_date="2026-01-20", first_contact="2026-01-21"),
    # Awaiting rebooking after a cancellation 10 days before the extract date.
    dict(status="Pending", referral_date="2025-12-01", first_contact="2025-12-02",
         appointments=[("Cancelled", "2025-12-05", "2026-01-21")]),
    # Sent externally less than 30 days ago.
    dict(status="Sent External", external=True, referral_date="2026-01-15", first_contact="2026-01-16"),
])
def test_active_referrals_are_not_leaked(mini, referral):
    row = classify(mini, **referral)
    assert row["active_in_progress_flag"] == 1
    assert row["leakage_flag"] == 0 and row["primary_leakage_reason"] is None
    assert row["outcome_category"] == "Active"


def test_scheduled_appointment_on_or_before_extract_is_never_not_scheduled(mini):
    # Phase 2 rejects this state; if it ever reached Phase 3 it must not be called "not scheduled".
    row = classify(mini, status="Scheduled", referral_date="2025-11-01", first_contact="2025-11-02",
                   appointments=[("Scheduled", "2025-11-05", "2026-01-20")])
    assert row["scheduled_flag"] == 1 and row["appointment_count"] == 1
    assert row["future_scheduled_appointment_count"] == 0
    assert row["primary_leakage_reason"] is None
    assert row["outcome_category"] == "Unclassified"


def test_old_cancellation_on_open_referral_is_leaked(mini):
    row = classify(mini, status="Pending", appointments=[("Cancelled", "2025-06-05", "2025-10-01")])
    assert row["active_in_progress_flag"] == 0
    assert row["primary_leakage_reason"] == "Cancelled Without Successful Rebooking"


# ---------------------------------------------------------------------------
# Rates, funnel, turnaround and grouped totals on a known mini dataset
# ---------------------------------------------------------------------------
@pytest.fixture
def known(mini):
    """Six referrals with hand-checked outcomes."""
    add_referral(mini, 1, status="Completed", closure_reason="Appointment Completed", closed_date="2025-06-20",
                 appointments=[("Completed", "2025-06-03", "2025-06-20")], duplicates=1, issues=1)
    add_referral(mini, 2, status="Completed", closure_reason="Appointment Completed", closed_date="2025-07-01",
                 appointments=[("Cancelled", "2025-06-04", "2025-06-10"), ("Completed", "2025-06-12", "2025-07-01")],
                 category="SVC002", source="Specialist")
    add_referral(mini, 3, status="Cancelled", closure_reason="No-Show - Not Rebooked", closed_date="2025-07-10",
                 first_contact=None, appointments=[("No-Show", "2025-06-05", "2025-07-01")], issues=1)
    add_referral(mini, 4, status="Sent External", external=True, closure_reason="External Visit Confirmed",
                 closed_date="2025-07-15", patient="PAT000002")
    add_referral(mini, 5, status="Sent External", external=True, patient="PAT000002", urgency="Urgent")
    add_referral(mini, 6, status="Scheduled", referral_date="2025-12-20", first_contact="2025-12-21",
                 appointments=[("Scheduled", "2025-12-22", "2026-02-15")], source="Specialist")
    create_views(mini)
    return mini


def test_rates_use_correct_numerators_and_denominators(known):
    overall = view_rows(known, "vw_overall_kpis")[0]
    assert overall["total_referrals"] == 6
    assert (overall["scheduled_referrals"], overall["completed_referrals"]) == (4, 2)
    assert (overall["converted_referrals"], overall["active_referrals"], overall["leaked_referrals"]) == (3, 1, 2)
    assert overall["scheduling_rate"] == pytest.approx(4 / 6)
    assert overall["completion_rate"] == pytest.approx(2 / 6)
    assert overall["conversion_rate"] == pytest.approx(3 / 6)
    assert overall["leakage_rate"] == pytest.approx(2 / 6)
    assert overall["conversion_rate"] + overall["leakage_rate"] < 1  # active referral is neither
    assert (overall["cancelled_referrals"], overall["no_show_referrals"]) == (1, 1)
    assert overall["total_appointments"] == 5
    assert overall["appointment_cancellation_rate"] == pytest.approx(1 / 5)
    assert overall["appointment_no_show_rate"] == pytest.approx(1 / 5)
    assert overall["duplicate_records_removed"] == 1 and overall["referrals_with_duplicates"] == 1
    assert overall["referrals_with_data_quality_issues"] == 2


def test_leakage_reasons_reconcile(known):
    reasons = view_rows(known, "vw_leakage_reason_metrics")
    assert [r["priority"] for r in reasons] == [1, 2, 3, 4, 5, 6]
    counts = {r["leakage_reason"]: r["leaked_referrals"] for r in reasons}
    assert counts["External Outcome Missing"] == 1
    assert counts["No-Show Without Successful Follow-Up"] == 1
    assert sum(counts.values()) == view_rows(known, "vw_overall_kpis")[0]["leaked_referrals"]
    assert sum(r["share_of_leaked_referrals"] for r in reasons) == pytest.approx(1)


def test_funnel_follows_definitions(known):
    funnel = view_rows(known, "vw_referral_funnel")
    assert [f["stage"] for f in funnel] == ["Total Referrals", "Contacted", "Scheduled",
                                            "Completed or Confirmed External Outcome"]
    assert [f["referrals"] for f in funnel] == [6, 6, 4, 3]  # referral 3 contact is evidenced by its appointment
    final = funnel[3]
    assert (final["internal_referrals"], final["external_referrals"]) == (2, 1)
    assert funnel[2]["external_referrals"] == 0


def test_grouped_results_reconcile_to_overall(known):
    overall = view_rows(known, "vw_overall_kpis")[0]
    for view in analyze_data.GROUPED_VIEWS:
        rows = view_rows(known, view)
        for column in analyze_data.ADDITIVE_COUNTS:
            assert sum(r[column] for r in rows) == overall[column], (view, column)
    sources = {r["dimension_key"]: r["total_referrals"] for r in view_rows(known, "vw_referral_source_metrics")}
    assert sources == {"Primary Care": 4, "Specialist": 2}


def test_missing_category_is_grouped_as_unknown(known):
    known.execute("UPDATE referrals SET receiving_facility_id = NULL WHERE referral_id = 'REF0000001'")
    facilities = {r["dimension_key"]: r for r in view_rows(known, "vw_facility_metrics")}
    assert facilities["Unknown"]["total_referrals"] == 1
    assert facilities["Unknown"]["dimension_label"] == "Unknown"
    assert sum(r["total_referrals"] for r in facilities.values()) == 6


def test_turnaround_average_and_median(mini):
    for number, booked in enumerate(["2025-06-03", "2025-06-04", "2025-06-05", "2025-06-12"], start=1):
        add_referral(mini, number, status="Completed", closure_reason="Appointment Completed",
                     closed_date="2025-06-30", appointments=[("Completed", booked, "2025-06-30")])
    create_views(mini)
    schedule = {r["measure"]: r for r in view_rows(mini, "vw_turnaround_metrics")}["days_to_schedule"]
    assert schedule["eligible_referrals"] == 4
    assert schedule["average_days"] == pytest.approx(statistics.fmean([1, 2, 3, 10]))
    assert schedule["median_days"] == pytest.approx(2.5)
    add_referral(mini, 5, status="Completed", closure_reason="Appointment Completed", closed_date="2025-06-30",
                 appointments=[("Completed", "2025-06-22", "2025-06-30")])
    schedule = {r["measure"]: r for r in view_rows(mini, "vw_turnaround_metrics")}["days_to_schedule"]
    assert schedule["median_days"] == pytest.approx(statistics.median([1, 2, 3, 10, 20]))
    overall = view_rows(mini, "vw_overall_kpis")[0]
    assert overall["median_days_to_schedule"] == schedule["median_days"]


def test_missing_dates_are_excluded_not_zero(mini):
    add_referral(mini, 1, status="Completed", first_contact="2025-06-06", closure_reason="Appointment Completed",
                 closed_date="2025-06-30", appointments=[("Completed", "2025-06-07", "2025-06-30")])
    add_referral(mini, 2, status="Completed", first_contact=None, closure_reason="Appointment Completed",
                 closed_date="2025-06-30", appointments=[("Completed", "2025-06-07", "2025-06-30")])
    create_views(mini)
    assert journey_row(mini, "REF0000002")["days_to_first_contact"] is None
    contact = {r["measure"]: r for r in view_rows(mini, "vw_turnaround_metrics")}["days_to_first_contact"]
    assert contact["eligible_referrals"] == 1
    assert contact["missing_or_not_applicable"] == 1
    assert contact["average_days"] == 4 and contact["median_days"] == 4


def test_negative_durations_are_excluded_and_flagged(mini):
    add_referral(mini, 1, status="Completed", closure_reason="Appointment Completed", closed_date="2025-06-30",
                 appointments=[("Completed", "2025-05-25", "2025-06-30")])  # booked before the referral
    create_views(mini)
    row = journey_row(mini, "REF0000001")
    assert row["days_to_schedule"] is None
    assert row["invalid_duration_flag"] == 1
    schedule = {r["measure"]: r for r in view_rows(mini, "vw_turnaround_metrics")}["days_to_schedule"]
    assert schedule["eligible_referrals"] == 0 and schedule["invalid_duration_referrals"] == 1


def test_delay_flags(mini):
    add_referral(mini, 1, status="Completed", closure_reason="Appointment Completed", closed_date="2025-08-01",
                 appointments=[("Completed", "2025-07-10", "2025-08-01")])  # booked after 38 days, 60 days total
    add_referral(mini, 2, status="Completed", closure_reason="Appointment Completed", closed_date="2025-06-20",
                 appointments=[("Completed", "2025-06-03", "2025-06-20")])  # 18 days, within the 21-day target
    create_views(mini)
    late, quick = journey_row(mini, "REF0000001"), journey_row(mini, "REF0000002")
    assert (late["delayed_schedule_flag"], late["delayed_appointment_flag"]) == (1, 1)
    assert (quick["delayed_schedule_flag"], quick["delayed_appointment_flag"]) == (0, 0)


def test_empty_database_returns_null_rates(mini):
    create_views(mini)
    overall = view_rows(mini, "vw_overall_kpis")
    assert len(overall) == 1
    row = overall[0]
    assert row["total_referrals"] == 0 and row["leaked_referrals"] == 0
    for column in ["scheduling_rate", "completion_rate", "conversion_rate", "leakage_rate",
                   "appointment_cancellation_rate", "median_days_to_schedule"]:
        assert row[column] is None, column
    assert all(r["share_of_leaked_referrals"] is None for r in view_rows(mini, "vw_leakage_reason_metrics"))
    assert all(r["share_of_total_referrals"] is None for r in view_rows(mini, "vw_referral_funnel"))
    assert all(r["eligible_referrals"] == 0 and r["median_days"] is None
               for r in view_rows(mini, "vw_turnaround_metrics"))
    assert view_rows(mini, "vw_service_category_metrics") == []


# ---------------------------------------------------------------------------
# analyze_data.py on a prepared dataset
# ---------------------------------------------------------------------------
def output_hashes(folder):
    names = list(config.ANALYTICS_EXPORT_FILES.values())
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names}


def read_summary(folder):
    return json.loads((folder / config.ANALYTICS_SUMMARY_FILE).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def prepared_output(small_dataset_dir, tmp_path_factory):
    """Phase 2 outputs for the shared small dataset (read-only; copy before use)."""
    base = tmp_path_factory.mktemp("phase3_prepared")
    report = prepare_data.run_pipeline(small_dataset_dir, base / "processed", base / "output")
    assert report["pipeline_status"] == "succeeded"
    return base / "output"


@pytest.fixture(scope="session")
def analyzed(prepared_output, tmp_path_factory):
    folder = tmp_path_factory.mktemp("phase3_analyzed") / "output"
    shutil.copytree(prepared_output, folder)
    summary = analyze_data.run_analysis(folder)
    assert summary["analytics_status"] == "succeeded", summary.get("error")
    return folder


@pytest.fixture
def output_copy(analyzed, tmp_path):
    folder = tmp_path / "output"
    shutil.copytree(analyzed, folder)
    return folder


def test_missing_database_gives_helpful_error(tmp_path, capsys):
    assert analyze_data.main(["--output-dir", str(tmp_path)]) == 1
    error = capsys.readouterr().err
    assert "database not found" in error
    assert "prepare_data.py" in error and "generate_data.py" in error
    assert read_summary(tmp_path)["analytics_status"] == "failed"


def test_failed_phase2_report_is_rejected(output_copy):
    report_path = output_copy / config.DATA_QUALITY_REPORT_FILE
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["pipeline_status"] = "failed"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary = analyze_data.run_analysis(output_copy)
    assert summary["analytics_status"] == "failed"
    assert "did not succeed" in summary["error"]


def test_analysis_succeeds_and_exports_documented_columns(analyzed):
    summary = read_summary(analyzed)
    assert summary["analytics_status"] == "succeeded"
    assert summary["synthetic_data"] is True
    assert summary["reconciliation"]["checks_failed"] == 0
    assert summary["reconciliation"]["checks_run"] >= 20
    for view, file_name in config.ANALYTICS_EXPORT_FILES.items():
        frame = pd.read_csv(analyzed / file_name, dtype=str, keep_default_na=False)
        assert list(frame.columns) == analyze_data.EXPORTS[view][1], view
        assert len(frame) == summary["exports"][file_name]
    text = (analyzed / config.ANALYTICS_SUMMARY_FILE).read_text(encoding="utf-8")
    assert "timestamp" not in text.lower() and "\\" not in text


def test_exported_journey_has_one_row_per_processed_referral(analyzed, prepared_output):
    journey = pd.read_csv(analyzed / "referral_journey.csv", dtype=str, keep_default_na=False)
    connection = sqlite3.connect(prepared_output / config.DATABASE_FILE)
    referrals = connection.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    connection.close()
    assert len(journey) == referrals and journey["referral_id"].is_unique
    flags = journey[["converted_flag", "active_in_progress_flag", "leakage_flag"]].astype(int)
    assert (flags.sum(axis=1) <= 1).all()


def test_exported_groups_reconcile_with_overall(analyzed):
    overall = pd.read_csv(analyzed / "overall_kpis.csv").iloc[0]
    for view in analyze_data.GROUPED_VIEWS:
        grouped = pd.read_csv(analyzed / config.ANALYTICS_EXPORT_FILES[view])
        for column in ["total_referrals", "converted_referrals", "leaked_referrals", "active_referrals"]:
            assert grouped[column].sum() == overall[column], (view, column)
    reasons = pd.read_csv(analyzed / "leakage_reason_metrics.csv")
    assert reasons["leaked_referrals"].sum() == overall["leaked_referrals"]


@pytest.fixture(scope="session")
def exported_journey(analyzed):
    return pd.read_csv(analyzed / "referral_journey.csv", keep_default_na=False, na_values=[""])


def test_not_scheduled_rows_have_no_appointments(exported_journey):
    rows = exported_journey[exported_journey["primary_leakage_reason"] == "Not Scheduled Within 30 Days"]
    assert len(rows) > 0
    assert (rows["appointment_count"] == 0).all()
    assert (rows["scheduled_flag"] == 0).all()
    assert rows["first_booking_date"].isna().all() and rows["first_appointment_date"].isna().all()
    assert (rows["days_since_referral"] >= config.FOLLOW_UP_WINDOW_DAYS).all()


def test_future_scheduled_referrals_are_active_and_never_leaked(exported_journey):
    future = exported_journey[exported_journey["future_scheduled_appointment_count"] > 0]
    assert len(future) > 0
    assert (future["converted_flag"] == 0).all()
    assert (future["active_in_progress_flag"] == 1).all()
    assert (future["leakage_flag"] == 0).all() and future["primary_leakage_reason"].isna().all()
    assert len(future) == (exported_journey["referral_status"] == "Scheduled").sum()


def test_every_leakage_label_agrees_with_its_condition(exported_journey):
    j = exported_journey
    conditions = {
        "External Outcome Missing": (j["referral_status"] == "Sent External") & (j["confirmed_external_outcome_flag"] == 0),
        "Expired Before Completion": j["referral_status"] == "Expired",
        "Cancelled Without Successful Rebooking": j["last_appointment_status"] == "Cancelled",
        "No-Show Without Successful Follow-Up": j["last_appointment_status"] == "No-Show",
        "Declined Before Scheduling": j["referral_status"] == "Declined",
        "Not Scheduled Within 30 Days": (j["appointment_count"] == 0) & (j["scheduled_flag"] == 0),
    }
    for reason, condition in conditions.items():
        labelled = j["primary_leakage_reason"] == reason
        assert labelled.any(), reason
        assert condition[labelled].all(), reason
    leaked = j[j["leakage_flag"] == 1]
    assert (leaked["converted_flag"] == 0).all() and (leaked["active_in_progress_flag"] == 0).all()


def test_mislabelled_scheduled_referrals_are_caught(output_copy, tmp_path, monkeypatch):
    """Simulate the suspected defect: future-scheduled referrals labelled 'Not Scheduled'."""
    before = output_hashes(output_copy)
    sql = config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8")
    broken = sql.replace("WHEN future_scheduled_appointment_count > 0 THEN 1",
                         "WHEN future_scheduled_appointment_count > 99 THEN 1")
    broken = broken.replace("WHEN appointment_count = 0 AND days_since_referral >= follow_up_window_days",
                            "WHEN days_since_referral >= follow_up_window_days")
    assert broken.count("> 99 THEN 1") == 1 and "WHEN appointment_count = 0 AND days_since" not in broken
    broken_path = tmp_path / "mislabelled_views.sql"
    broken_path.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(config, "ANALYTICS_VIEWS_SQL_PATH", broken_path)
    summary = analyze_data.run_analysis(output_copy)
    failed = {c["check"] for c in summary["reconciliation"]["checks"] if c["status"] == "failed"}
    assert summary["analytics_status"] == "failed"
    assert {"leakage_reasons_match_conditions", "future_scheduled_never_leaked"} <= failed
    assert output_hashes(output_copy) == before


def test_duplicate_and_quality_counts_reconcile_with_phase2(analyzed):
    phase2 = json.loads((analyzed / config.DATA_QUALITY_REPORT_FILE).read_text(encoding="utf-8"))
    overall = pd.read_csv(analyzed / "overall_kpis.csv").iloc[0]
    assert overall["duplicate_records_removed"] == phase2["duplicates"]["removed_duplicate_rows"]
    assert overall["data_quality_exceptions"] == phase2["exceptions"]["total"]
    quality = pd.read_csv(analyzed / "data_quality_metrics.csv")
    assert quality["exception_count"].sum() == phase2["exceptions"]["total"]


def test_turnaround_export_matches_independent_calculation(analyzed):
    journey = pd.read_csv(analyzed / "referral_journey.csv")
    turnaround = pd.read_csv(analyzed / "turnaround_metrics.csv").set_index("measure")
    for measure in analyze_data.TURNAROUND_MEASURES:
        values = journey[measure].dropna()
        assert turnaround.loc[measure, "eligible_referrals"] == len(values)
        assert turnaround.loc[measure, "average_days"] == pytest.approx(values.mean(), abs=1e-6)
        assert turnaround.loc[measure, "median_days"] == pytest.approx(values.median())


def test_reruns_are_byte_identical(analyzed, tmp_path):
    folder = tmp_path / "rerun"
    shutil.copytree(analyzed, folder)
    assert analyze_data.run_analysis(folder)["analytics_status"] == "succeeded"
    assert output_hashes(folder) == output_hashes(analyzed)
    assert (folder / config.ANALYTICS_SUMMARY_FILE).read_bytes() == \
        (analyzed / config.ANALYTICS_SUMMARY_FILE).read_bytes()


def test_empty_database_analysis(tmp_path):
    connection = create_schema(tmp_path / config.DATABASE_FILE)
    connection.close()
    phase2 = {
        "pipeline_status": "succeeded",
        "database": {"table_row_counts": {table: 0 for table in PHASE2_TABLES}},
        "duplicates": {"removed_duplicate_rows": 0, "referral_ids_with_duplicates": 0},
        "exceptions": {"total": 0, "by_issue_type": {}, "referrals_with_issues": 0},
    }
    (tmp_path / config.DATA_QUALITY_REPORT_FILE).write_text(json.dumps(phase2), encoding="utf-8")
    summary = analyze_data.run_analysis(tmp_path)
    assert summary["analytics_status"] == "succeeded", summary.get("error")
    assert summary["overall_kpis"]["total_referrals"] == 0
    assert summary["overall_kpis"]["conversion_rate"] is None
    overall_csv = (tmp_path / "overall_kpis.csv").read_text(encoding="utf-8").splitlines()
    assert len(overall_csv) == 2


@pytest.mark.parametrize("tamper, failed_check", [
    ("UPDATE referrals SET duplicate_record_count = duplicate_record_count + 1 "
     "WHERE referral_id = (SELECT MIN(referral_id) FROM referrals)", "duplicates_reconcile_to_phase2"),
    ("DELETE FROM data_quality_exceptions WHERE exception_id = "
     "(SELECT MAX(exception_id) FROM data_quality_exceptions)", "data_quality_reconciles_to_phase2"),
    ("DELETE FROM appointments WHERE appointment_id = (SELECT MIN(appointment_id) FROM appointments)",
     "phase2_table_counts_unchanged"),
])
def test_tampered_database_fails_without_replacing_exports(output_copy, capsys, tamper, failed_check):
    before = output_hashes(output_copy)
    connection = sqlite3.connect(output_copy / config.DATABASE_FILE)
    connection.execute(tamper)
    connection.commit()
    connection.close()

    assert analyze_data.main(["--output-dir", str(output_copy)]) == 1
    assert failed_check in capsys.readouterr().err
    assert output_hashes(output_copy) == before
    summary = read_summary(output_copy)
    assert summary["analytics_status"] == "failed"
    assert failed_check in {c["check"] for c in summary["reconciliation"]["checks"] if c["status"] == "failed"}
    assert not list(output_copy.glob(".phase3_staging_*"))


def test_wrong_rate_logic_is_caught(output_copy, tmp_path, monkeypatch):
    before = output_hashes(output_copy)
    sql = config.ANALYTICS_VIEWS_SQL_PATH.read_text(encoding="utf-8")
    broken = sql.replace("1.0 * c.leaked_referrals / c.total_referrals END    AS leakage_rate",
                         "1.0 * c.leaked_referrals / c.scheduled_referrals END    AS leakage_rate")
    assert broken != sql
    broken_path = tmp_path / "broken_views.sql"
    broken_path.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(config, "ANALYTICS_VIEWS_SQL_PATH", broken_path)
    summary = analyze_data.run_analysis(output_copy)
    assert summary["analytics_status"] == "failed"
    failed = {c["check"] for c in summary["reconciliation"]["checks"] if c["status"] == "failed"}
    assert "rates_use_correct_denominators" in failed
    assert output_hashes(output_copy) == before


# ---------------------------------------------------------------------------
# Full-size integration
# ---------------------------------------------------------------------------
def test_standard_dataset_end_to_end(tmp_path):
    generate_data.generate_dataset(150_000, 42, tmp_path / "raw")
    report = prepare_data.run_pipeline(tmp_path / "raw", tmp_path / "processed", tmp_path / "output")
    assert report["pipeline_status"] == "succeeded"
    summary = analyze_data.run_analysis(tmp_path / "output")
    assert summary["analytics_status"] == "succeeded", summary.get("error")
    kpis = summary["overall_kpis"]
    assert kpis["total_referrals"] == 147_750
    assert kpis["converted_referrals"] + kpis["active_referrals"] + kpis["leaked_referrals"] \
        + kpis["unclassified_referrals"] == 147_750
    assert sum(r["leaked_referrals"] for r in summary["leakage_reasons"]) == kpis["leaked_referrals"]
    assert summary["reconciliation"]["checks_failed"] == 0
