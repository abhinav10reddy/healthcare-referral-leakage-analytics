"""Phase 2 tests for validation, cleaning and the SQLite pipeline."""

import hashlib
import json
import shutil
import sqlite3

import pandas as pd
import pytest

import config
import generate_data
import prepare_data

TABLES = list(prepare_data.PROCESSED_FILES)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------
def run(raw_dir, base_dir):
    """Run the pipeline into <base_dir>/processed and <base_dir>/output."""
    return prepare_data.run_pipeline(raw_dir, base_dir / "processed", base_dir / "output")


def read_raw(raw_dir, name):
    return pd.read_csv(raw_dir / generate_data.OUTPUT_FILES[name], dtype=str,
                       keep_default_na=False, na_filter=False)


def write_raw(frame, raw_dir, name):
    frame.to_csv(raw_dir / generate_data.OUTPUT_FILES[name], index=False, lineterminator="\n")


def read_processed(base_dir, name):
    return pd.read_csv(base_dir / "processed" / prepare_data.PROCESSED_FILES[name], dtype=str,
                       keep_default_na=False, na_values=[""])


def read_report(base_dir):
    return json.loads((base_dir / "output" / config.DATA_QUALITY_REPORT_FILE).read_text(encoding="utf-8"))


def failed_check_names(report):
    return {check["check"] for check in report["validation"]["checks"] if check["status"] == "failed"}


def output_hashes(base_dir):
    paths = [base_dir / "processed" / f for f in prepare_data.PROCESSED_FILES.values()]
    paths.append(base_dir / "output" / config.DATABASE_FILE)
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def table_contents(db_path):
    connection = sqlite3.connect(db_path)
    try:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in TABLES}
    finally:
        connection.close()


@pytest.fixture
def raw_copy(small_dataset_dir, tmp_path):
    """A private copy of the small raw dataset that a test may modify."""
    raw_dir = tmp_path / "raw"
    shutil.copytree(small_dataset_dir, raw_dir)
    return raw_dir


@pytest.fixture(scope="session")
def prepared(small_dataset_dir, tmp_path_factory):
    """Phase 2 outputs for the shared 5,000-row raw dataset."""
    base_dir = tmp_path_factory.mktemp("prepared")
    report = run(small_dataset_dir, base_dir)
    assert report["pipeline_status"] == "succeeded", report.get("error")
    return base_dir


@pytest.fixture(scope="session")
def processed(prepared):
    return {name: read_processed(prepared, name) for name in TABLES}


@pytest.fixture(scope="session")
def raw_canonical(small_dataset_dir):
    referrals = pd.read_csv(small_dataset_dir / "referrals.csv", dtype=str,
                            keep_default_na=False, na_values=[""])
    return referrals.drop_duplicates("referral_id").set_index("referral_id")


# ---------------------------------------------------------------------------
# Failed validation
# ---------------------------------------------------------------------------
def test_missing_raw_file_gives_helpful_error(raw_copy, tmp_path, capsys):
    (raw_copy / "appointments.csv").unlink()
    exit_code = prepare_data.main(["--raw-dir", str(raw_copy), "--processed-dir", str(tmp_path / "processed"),
                                   "--output-dir", str(tmp_path / "output")])
    error = capsys.readouterr().err
    assert exit_code == 1
    assert "appointments.csv" in error
    assert "generate_data.py --referrals 150000 --seed 42" in error
    report = read_report(tmp_path)
    assert report["pipeline_status"] == "failed"
    assert "raw_files_exist" in failed_check_names(report)


def drop_column(raw_dir):
    write_raw(read_raw(raw_dir, "patients").drop(columns="gender"), raw_dir, "patients")


def add_column(raw_dir):
    frame = read_raw(raw_dir, "facilities")
    frame["notes"] = "extra"
    write_raw(frame, raw_dir, "facilities")


def duplicate_master_key(raw_dir):
    frame = read_raw(raw_dir, "providers")
    frame.loc[1, "provider_id"] = frame.loc[0, "provider_id"]
    write_raw(frame, raw_dir, "providers")


def invalid_foreign_key(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    frame.loc[0, "patient_id"] = "PAT999999"
    write_raw(frame, raw_dir, "referrals")


def invalid_enumeration(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    frame.loc[0, "urgency"] = "Whenever"
    write_raw(frame, raw_dir, "referrals")


def malformed_date(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    frame.loc[0, "referral_date"] = "31/01/2025"
    write_raw(frame, raw_dir, "referrals")


def appointment_before_booking(raw_dir):
    frame = read_raw(raw_dir, "appointments")
    frame.loc[0, "booked_date"] = frame.loc[0, "appointment_datetime"][:10]
    day = pd.Timestamp(frame.loc[0, "appointment_datetime"]) - pd.Timedelta(days=1)
    frame.loc[0, "appointment_datetime"] = f"{day:%Y-%m-%d %H:%M:%S}"
    write_raw(frame, raw_dir, "appointments")


def completed_before_referral(raw_dir):
    appointments = read_raw(raw_dir, "appointments")
    referrals = read_raw(raw_dir, "referrals")
    row = appointments.index[appointments["appointment_status"] == "Completed"][0]
    referral_date = referrals.loc[referrals["referral_id"] == appointments.loc[row, "referral_id"],
                                  "referral_date"].iloc[0]
    appointments.loc[row, "booked_date"] = referral_date
    appointments.loc[row, "appointment_datetime"] = f"{referral_date} 09:00:00"
    write_raw(appointments, raw_dir, "appointments")


def three_rows_for_one_referral(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    duplicated_id = frame.loc[frame["referral_id"].duplicated(), "referral_id"].iloc[0]
    extra = frame[frame["referral_id"] == duplicated_id].head(1).copy()
    extra["referral_record_id"] = "REC9999999"
    write_raw(pd.concat([frame, extra], ignore_index=True), raw_dir, "referrals")


def nonidentical_duplicate(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    second_copy = frame.index[frame["referral_id"].duplicated()][0]
    frame.loc[second_copy, "urgency"] = "Stat" if frame.loc[second_copy, "urgency"] != "Stat" else "Routine"
    write_raw(frame, raw_dir, "referrals")


def missing_required_value(raw_dir):
    frame = read_raw(raw_dir, "referrals")
    frame.loc[0, "receiving_provider_id"] = ""
    write_raw(frame, raw_dir, "referrals")


@pytest.mark.parametrize("corrupt, expected_check", [
    (drop_column, "required_columns_present"),
    (add_column, "no_unexpected_columns"),
    (duplicate_master_key, "primary_keys_unique"),
    (invalid_foreign_key, "fk_referral_patient"),
    (invalid_enumeration, "enumerations_valid"),
    (malformed_date, "dates_parse"),
    (appointment_before_booking, "appointment_not_before_booking"),
    (completed_before_referral, "completed_appointment_after_referral"),
    (three_rows_for_one_referral, "referral_id_max_two_rows"),
    (nonidentical_duplicate, "duplicate_rows_identical"),
    (missing_required_value, "required_values_present"),
])
def test_structural_problems_are_rejected(raw_copy, tmp_path, corrupt, expected_check):
    corrupt(raw_copy)
    report = run(raw_copy, tmp_path)
    assert report["pipeline_status"] == "failed"
    assert expected_check in failed_check_names(report)
    assert expected_check in report["error"]
    assert report["validation"]["structural_violations"] >= 1
    assert read_report(tmp_path)["pipeline_status"] == "failed"
    assert not (tmp_path / "output" / config.DATABASE_FILE).exists()
    assert not (tmp_path / "processed" / "referrals.csv").exists()


def test_failed_run_keeps_previous_successful_outputs(raw_copy, tmp_path):
    assert run(raw_copy, tmp_path)["pipeline_status"] == "succeeded"
    before = output_hashes(tmp_path)

    invalid_foreign_key(raw_copy)
    assert prepare_data.main(["--raw-dir", str(raw_copy), "--processed-dir", str(tmp_path / "processed"),
                              "--output-dir", str(tmp_path / "output")]) == 1

    assert output_hashes(tmp_path) == before
    report = read_report(tmp_path)
    assert report["pipeline_status"] == "failed"
    assert report["outputs_replaced"] is False
    assert not list((tmp_path / "output").glob(".phase2_staging_*"))


def test_staging_folder_is_removed_after_success(prepared):
    assert not list((prepared / "output").glob(".phase2_staging_*"))


# ---------------------------------------------------------------------------
# Cleaning rules
# ---------------------------------------------------------------------------
def test_whitespace_is_trimmed_and_recorded(raw_copy, tmp_path):
    referrals = read_raw(raw_copy, "referrals")
    referrals.loc[0, "urgency"] = f"  {referrals.loc[0, 'urgency']} "
    write_raw(referrals, raw_copy, "referrals")
    patients = read_raw(raw_copy, "patients")
    patients.loc[0, "home_region"] = f"{patients.loc[0, 'home_region']}\t"
    write_raw(patients, raw_copy, "patients")

    report = run(raw_copy, tmp_path)
    assert report["pipeline_status"] == "succeeded"
    assert report["cleaning_actions"]["trimmed_whitespace"] == 2
    exceptions = read_processed(tmp_path, "data_quality_exceptions")
    trimmed = exceptions[exceptions["issue_type"] == "extra_whitespace"]
    assert set(trimmed["field_name"]) == {"urgency", "home_region"}
    processed = read_processed(tmp_path, "referrals")
    assert not processed["urgency"].str.contains(r"^\s|\s$").any()


def test_dates_are_normalized_to_iso(raw_copy, tmp_path):
    referrals = read_raw(raw_copy, "referrals")
    original = referrals.loc[0, "referral_date"]
    referrals.loc[referrals["referral_id"] == referrals.loc[0, "referral_id"], "referral_date"] = \
        original.replace("-", "/")
    write_raw(referrals, raw_copy, "referrals")
    appointments = read_raw(raw_copy, "appointments")
    appointments.loc[0, "appointment_datetime"] = appointments.loc[0, "appointment_datetime"][:16]
    write_raw(appointments, raw_copy, "appointments")

    report = run(raw_copy, tmp_path)
    assert report["pipeline_status"] == "succeeded"
    processed = read_processed(tmp_path, "referrals").set_index("referral_record_id")
    assert processed.loc[referrals.loc[0, "referral_record_id"], "referral_date"] == original
    processed_appointments = read_processed(tmp_path, "appointments")
    assert processed_appointments["appointment_datetime"].str.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}").all()
    exceptions = read_processed(tmp_path, "data_quality_exceptions")
    assert (exceptions["issue_type"] == "nonstandard_date_format").sum() == \
        report["cleaning_actions"]["normalized_date_format"] >= 2


def test_duplicate_referrals_are_removed(processed, small_dataset_dir):
    raw = read_raw(small_dataset_dir, "referrals")
    referrals = processed["referrals"]
    assert len(referrals) == raw["referral_id"].nunique()
    assert referrals["referral_id"].is_unique
    smallest = raw.sort_values("referral_record_id").drop_duplicates("referral_id")
    kept = referrals.set_index("referral_id")["referral_record_id"]
    assert (kept[smallest["referral_id"]].to_numpy() == smallest["referral_record_id"].to_numpy()).all()

    exceptions = processed["data_quality_exceptions"]
    removed = exceptions[exceptions["issue_type"] == "duplicate_referral_record"]
    assert len(removed) == len(raw) - len(referrals)
    assert set(removed["record_id"]) == set(raw["referral_record_id"]) - set(referrals["referral_record_id"])


def test_duplicate_record_count_is_added(processed, small_dataset_dir):
    raw = read_raw(small_dataset_dir, "referrals")
    extra_rows = raw["referral_id"].value_counts() - 1
    counts = processed["referrals"].set_index("referral_id")["duplicate_record_count"].astype(int)
    assert (counts == extra_rows.reindex(counts.index)).all()
    assert counts.sum() == len(raw) - len(counts)


def test_missing_source_becomes_unknown(processed, raw_canonical):
    referrals = processed["referrals"].set_index("referral_id")
    blank_ids = raw_canonical.index[raw_canonical["referral_source"].isna()]
    assert len(blank_ids) > 0
    assert (referrals.loc[blank_ids, "referral_source"] == "Unknown").all()
    assert referrals["referral_source"].notna().all()
    flagged = processed["data_quality_exceptions"].query("issue_type == 'missing_referral_source'")
    assert set(flagged["referral_id"]) == set(blank_ids)
    assert (flagged["cleaned_value"] == "Unknown").all()


def test_receiving_facility_is_inferred_from_provider(processed, raw_canonical):
    referrals = processed["referrals"].set_index("referral_id")
    provider_facility = processed["providers"].set_index("provider_id")["facility_id"]
    blank_ids = raw_canonical.index[raw_canonical["receiving_facility_id"].isna()]
    assert len(blank_ids) > 0
    inferred = referrals.loc[blank_ids]
    assert (inferred["receiving_facility_id"]
            == inferred["receiving_provider_id"].map(provider_facility)).all()
    flagged = processed["data_quality_exceptions"].query("issue_type == 'missing_receiving_facility'")
    assert set(flagged["referral_id"]) == set(blank_ids)
    assert (flagged["resolution_status"] == "Resolved").all()


def test_ambiguous_facility_is_left_blank_and_unresolved():
    referrals = pd.DataFrame({
        "referral_record_id": ["REC0000001"], "referral_id": ["REF0000001"],
        "receiving_provider_id": ["PRV001"], "receiving_facility_id": [None],
        "referral_source": ["Primary Care"], "first_contact_date": ["2025-01-02"],
        "referral_status": ["Pending"], "closure_reason": [None], "closed_date": [None],
        "patient_id": ["PAT000001"], "service_category_id": ["SVC001"], "urgency": ["Routine"],
        "referral_date": ["2025-01-01"],
    })
    providers = pd.DataFrame({"provider_id": ["PRV001", "PRV001"], "facility_id": ["FAC001", "FAC002"]})
    appointments = pd.DataFrame({"referral_id": pd.Series([], dtype=str)})
    cleaned, frames, _ = prepare_data.clean_referrals(referrals, appointments, providers)
    assert pd.isna(cleaned.loc[0, "receiving_facility_id"])
    exceptions = prepare_data.assemble_exceptions(frames)
    row = exceptions[exceptions["issue_type"] == "missing_receiving_facility"].iloc[0]
    assert row["resolution_status"] == "Unresolved"


def test_missing_contact_date_stays_blank_and_is_flagged(processed, raw_canonical):
    referrals = processed["referrals"].set_index("referral_id")
    flagged = processed["data_quality_exceptions"].query("issue_type == 'missing_first_contact_date'")
    assert len(flagged) > 0
    assert referrals.loc[flagged["referral_id"], "first_contact_date"].isna().all()
    has_appointment = referrals.index.isin(processed["appointments"]["referral_id"])
    proven = has_appointment | (referrals["referral_status"] == "Declined")
    assert set(flagged["referral_id"]) == set(referrals.index[proven & referrals["first_contact_date"].isna()])


def test_closure_without_date_is_recorded(processed):
    referrals = processed["referrals"].set_index("referral_id")
    flagged = processed["data_quality_exceptions"].query("issue_type == 'missing_closed_date'")
    expected = referrals.index[referrals["closure_reason"].notna() & referrals["closed_date"].isna()]
    assert len(expected) > 0
    assert set(flagged["referral_id"]) == set(expected)
    assert referrals.loc[expected, "closure_reason"].notna().all()
    assert (flagged["resolution_status"] == "Unresolved").all()


def test_open_status_closed_date_is_cleared(processed, raw_canonical):
    referrals = processed["referrals"].set_index("referral_id")
    is_open = referrals["referral_status"].isin(["Pending", "Scheduled"])
    assert referrals.loc[is_open, "closed_date"].isna().all()
    flagged = processed["data_quality_exceptions"].query("issue_type == 'open_referral_with_closed_date'")
    assert len(flagged) > 0
    original = raw_canonical.loc[flagged["referral_id"], "closed_date"].to_numpy()
    assert (flagged["original_value"].to_numpy() == original).all()
    assert flagged["cleaned_value"].isna().all()


def test_legitimate_blanks_remain_blank(processed, raw_canonical):
    referrals = processed["referrals"].set_index("referral_id")
    flagged_ids = set(processed["data_quality_exceptions"]["referral_id"].dropna())
    never_contacted = raw_canonical.index[raw_canonical["first_contact_date"].isna()
                                          & ~raw_canonical.index.isin(list(flagged_ids))]
    assert len(never_contacted) > 0
    assert referrals.loc[never_contacted, "first_contact_date"].isna().all()
    open_ids = referrals.index[referrals["referral_status"].isin(["Pending", "Scheduled"])]
    assert referrals.loc[open_ids, "closure_reason"].isna().all()
    appointments = processed["appointments"]
    no_reason = ~appointments["appointment_status"].isin(["Cancelled", "Rescheduled"])
    assert appointments.loc[no_reason, "status_reason"].isna().all()


def test_issue_flags_match_exceptions(processed):
    referrals = processed["referrals"].set_index("referral_id")
    exceptions = processed["data_quality_exceptions"]
    per_referral = exceptions[exceptions["entity_type"] == "referral"]["referral_id"].value_counts()
    counts = referrals["data_quality_issue_count"].astype(int)
    assert (counts == per_referral.reindex(counts.index, fill_value=0)).all()
    assert ((referrals["has_data_quality_issue"] == "1") == (counts > 0)).all()


# ---------------------------------------------------------------------------
# Exceptions file and report
# ---------------------------------------------------------------------------
def test_exception_ids_are_unique_and_deterministic(processed, small_dataset_dir, tmp_path):
    exceptions = processed["data_quality_exceptions"]
    assert exceptions["exception_id"].is_unique
    assert exceptions["exception_id"].tolist() == [f"DQE{i:07d}" for i in range(1, len(exceptions) + 1)]
    run(small_dataset_dir, tmp_path)
    rerun = read_processed(tmp_path, "data_quality_exceptions")
    assert rerun.equals(exceptions)


def test_exception_counts_reconcile_with_report(prepared, processed):
    report = read_report(prepared)
    exceptions = processed["data_quality_exceptions"]
    by_issue = exceptions["issue_type"].value_counts()
    assert report["exceptions"]["total"] == len(exceptions)
    for issue, count in report["exceptions"]["by_issue_type"].items():
        assert by_issue.get(issue, 0) == count, issue
    unresolved = exceptions[exceptions["resolution_status"] == "Unresolved"]
    assert report["exceptions"]["unresolved"] == len(unresolved)
    actions = report["cleaning_actions"]
    assert actions["removed_duplicate_referral_rows"] == report["duplicates"]["removed_duplicate_rows"]
    assert sum(actions.values()) == len(exceptions)
    assert report["controlled_issue_reconciliation"]["all_match"] is True


def test_report_contents(prepared, small_dataset_dir):
    report = read_report(prepared)
    assert report["pipeline_status"] == "succeeded"
    assert report["synthetic_data"] is True
    assert "not for clinical decision-making" in report["non_clinical_use"]
    assert report["reporting_period"] == {"start": "2025-01-01", "end": "2025-12-31"}
    assert report["extract_date"] == "2026-01-31"
    assert report["validation"]["checks_failed"] == 0
    assert report["validation"]["structural_violations"] == 0
    assert report["database"]["foreign_key_check"] == "passed"
    assert report["input_row_counts"]["referrals.csv"] == len(read_raw(small_dataset_dir, "referrals"))
    text = (prepared / "output" / config.DATA_QUALITY_REPORT_FILE).read_text(encoding="utf-8")
    assert str(prepared) not in text and "\\" not in text


def test_processed_files_have_expected_columns_and_rows(prepared, processed, small_dataset_dir):
    report = read_report(prepared)
    for name, frame in processed.items():
        assert list(frame.columns) == prepare_data.PROCESSED_COLUMNS[name], name
        assert len(frame) == report["output_row_counts"][prepare_data.PROCESSED_FILES[name]], name
    for name in ["service_categories", "facilities", "providers", "patients", "appointments"]:
        assert len(processed[name]) == len(read_raw(small_dataset_dir, name)), name
    raw = (prepared / "processed" / "referrals.csv").read_bytes()
    assert b"\r\n" not in raw and b"nan" not in raw.lower()


# ---------------------------------------------------------------------------
# SQLite database
# ---------------------------------------------------------------------------
@pytest.fixture
def database(prepared, tmp_path):
    """A private copy of the database so tests can try invalid inserts."""
    db_path = tmp_path / "copy.db"
    shutil.copyfile(prepared / "output" / config.DATABASE_FILE, db_path)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


def test_database_tables_keys_and_indexes_exist(database):
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(TABLES)
    indexes = {row[0] for row in database.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")}
    for expected in ["idx_referrals_referral_date", "idx_referrals_status", "idx_referrals_service_category",
                     "idx_referrals_facility", "idx_referrals_provider", "idx_referrals_patient",
                     "idx_appointments_status", "idx_appointments_date", "idx_appointments_referral"]:
        assert expected in indexes
    primary_keys = {table: [row[1] for row in database.execute(f"PRAGMA table_info({table})") if row[5]]
                    for table in TABLES}
    assert primary_keys["referrals"] == ["referral_id"]
    assert primary_keys["appointments"] == ["appointment_id"]
    foreign_keys = {(row[2], row[3]) for row in database.execute("PRAGMA foreign_key_list(appointments)")}
    assert ("referrals", "referral_id") in foreign_keys
    sql = database.execute("SELECT sql FROM sqlite_master WHERE name = 'referrals'").fetchone()[0]
    assert "CHECK" in sql and "UNIQUE" in sql


def test_database_counts_match_processed_csvs(database, processed):
    for name, frame in processed.items():
        assert database.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] == len(frame), name
    distinct = database.execute("SELECT COUNT(DISTINCT referral_id) FROM referrals").fetchone()[0]
    assert distinct == len(processed["referrals"])


def test_foreign_key_check_is_empty(database):
    assert database.execute("PRAGMA foreign_key_check").fetchall() == []
    assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("statement", [
    "UPDATE referrals SET referral_status = 'Lost' WHERE rowid = 1",
    "UPDATE referrals SET patient_id = 'PAT999999' WHERE rowid = 1",
    "UPDATE patients SET gender = 'X' WHERE rowid = 1",
    "UPDATE referrals SET has_data_quality_issue = 2 WHERE rowid = 1",
    "INSERT INTO appointments SELECT 'APT9999999', referral_id, 9, facility_id, provider_id, "
    "'2026-12-31', appointment_datetime, appointment_date, appointment_status, status_reason "
    "FROM appointments LIMIT 1",
    "INSERT INTO appointments SELECT 'APT9999999', 'REF9999999', 1, facility_id, provider_id, "
    "booked_date, appointment_datetime, appointment_date, appointment_status, status_reason "
    "FROM appointments LIMIT 1",
    "INSERT INTO referrals SELECT * FROM referrals LIMIT 1",
    "UPDATE referrals SET closed_date = '2025-06-01' WHERE referral_status = 'Pending' "
    "AND rowid = (SELECT MIN(rowid) FROM referrals WHERE referral_status = 'Pending')",
])
def test_database_constraints_reject_invalid_changes(database, statement):
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(statement)


def test_schema_script_is_safe_to_rerun(database):
    script = config.SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    database.executescript(script)
    database.executescript(script)
    assert database.execute("SELECT COUNT(*) FROM referrals").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_rerun_produces_identical_outputs(small_dataset_dir, prepared, tmp_path):
    run(small_dataset_dir, tmp_path)
    for file_name in prepare_data.PROCESSED_FILES.values():
        assert (tmp_path / "processed" / file_name).read_bytes() == \
            (prepared / "processed" / file_name).read_bytes(), file_name
    report_name = config.DATA_QUALITY_REPORT_FILE
    assert (tmp_path / "output" / report_name).read_bytes() == (prepared / "output" / report_name).read_bytes()
    assert table_contents(tmp_path / "output" / config.DATABASE_FILE) == \
        table_contents(prepared / "output" / config.DATABASE_FILE)


def test_rerun_into_same_folders_is_identical(small_dataset_dir, tmp_path):
    run(small_dataset_dir, tmp_path)
    first = output_hashes(tmp_path)
    first_report = (tmp_path / "output" / config.DATA_QUALITY_REPORT_FILE).read_bytes()
    first_tables = table_contents(tmp_path / "output" / config.DATABASE_FILE)
    run(small_dataset_dir, tmp_path)
    second = output_hashes(tmp_path)
    csv_names = list(prepare_data.PROCESSED_FILES.values())
    assert {k: first[k] for k in csv_names} == {k: second[k] for k in csv_names}
    assert (tmp_path / "output" / config.DATA_QUALITY_REPORT_FILE).read_bytes() == first_report
    assert table_contents(tmp_path / "output" / config.DATABASE_FILE) == first_tables


# ---------------------------------------------------------------------------
# Full-size integration
# ---------------------------------------------------------------------------
def test_standard_150000_row_dataset(tmp_path):
    raw_dir = tmp_path / "raw"
    generate_data.generate_dataset(150_000, 42, raw_dir)
    report = run(raw_dir, tmp_path)
    assert report["pipeline_status"] == "succeeded", report.get("error")
    assert report["duplicates"]["input_referral_records"] == 150_000
    assert report["duplicates"]["unique_referral_ids"] == 147_750
    assert report["duplicates"]["removed_duplicate_rows"] == 2_250
    assert report["controlled_issue_reconciliation"]["all_match"] is True
    assert report["validation"]["structural_violations"] == 0
    assert report["database"]["table_row_counts"]["referrals"] == 147_750
    assert report["database"]["foreign_key_violations"] == 0
