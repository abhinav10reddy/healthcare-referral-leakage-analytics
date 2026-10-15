"""Phase 1 tests for the synthetic referral data generator."""

import re
import shutil
import subprocess

import pandas as pd
import pytest

import config
import generate_data
from conftest import PROJECT_ROOT, SMALL_REFERRAL_COUNT, read_tables

EXTRACT_DATE = pd.Timestamp(config.DATA_EXTRACT_DATE)
CLOSED_STATUSES = ["Completed", "Declined", "Cancelled", "Expired"]
OPEN_STATUSES = ["Pending", "Scheduled"]


def to_dates(series):
    return pd.to_datetime(series, format="%Y-%m-%d")


def appointment_days(appointments):
    return pd.to_datetime(appointments["appointment_datetime"], format="%Y-%m-%d %H:%M:%S").dt.normalize()


# ---------------------------------------------------------------------------
# Configuration sanity
# ---------------------------------------------------------------------------
def test_config_defaults():
    assert config.DEFAULT_REFERRAL_COUNT == 150_000
    assert config.DEFAULT_SEED == 42
    assert config.REPORTING_START_DATE.year == config.REPORTING_END_DATE.year
    assert config.REPORTING_END_DATE < config.DATA_EXTRACT_DATE


def test_every_service_has_in_network_and_external_facility():
    for category in config.SERVICE_CATEGORIES:
        networks = {f["network_status"] for f in config.FACILITIES
                    if category["service_category_id"] in f["service_category_ids"]}
        assert networks == {"In-Network", "Out-of-Network"}, category["service_category_name"]


# ---------------------------------------------------------------------------
# Files, columns and row counts
# ---------------------------------------------------------------------------
def test_all_six_csv_files_are_created(small_dataset_dir):
    created = sorted(p.name for p in small_dataset_dir.glob("*.csv"))
    assert created == sorted(generate_data.OUTPUT_FILES.values())


def test_columns_match_expected_schema(tables):
    for name, frame in tables.items():
        assert list(frame.columns) == generate_data.COLUMNS[name], name


def test_requested_referral_row_count(tables):
    assert len(tables["referrals"]) == SMALL_REFERRAL_COUNT
    assert len(tables["service_categories"]) == len(config.SERVICE_CATEGORIES)
    assert len(tables["facilities"]) == len(config.FACILITIES)
    assert len(tables["patients"]) == generate_data.patient_count_for(SMALL_REFERRAL_COUNT)


def test_returned_row_counts_match_files(tmp_path):
    row_counts = generate_data.generate_dataset(300, 3, tmp_path)
    for file_name, count in row_counts.items():
        assert len(pd.read_csv(tmp_path / file_name)) == count
    assert row_counts["referrals.csv"] == 300


def test_single_referral_run_works(tmp_path):
    row_counts = generate_data.generate_dataset(1, 42, tmp_path)
    assert row_counts["referrals.csv"] == 1
    assert row_counts["patients.csv"] == 1


def test_150000_referrals_are_supported(tmp_path):
    row_counts = generate_data.generate_dataset(150_000, 42, tmp_path)
    referrals = pd.read_csv(tmp_path / "referrals.csv", dtype=str,
                            usecols=["referral_record_id", "referral_id"])
    assert row_counts["referrals.csv"] == 150_000
    assert len(referrals) == 150_000
    assert referrals["referral_record_id"].is_unique
    _, counts = generate_data.data_quality_counts(150_000)
    assert len(referrals) - referrals["referral_id"].nunique() == counts["duplicate_referral_id"] == 2_250


# ---------------------------------------------------------------------------
# Identifiers and duplicates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("table, column, pattern", [
    ("service_categories", "service_category_id", r"SVC\d{3}"),
    ("facilities", "facility_id", r"FAC\d{3}"),
    ("providers", "provider_id", r"PRV\d{3}"),
    ("patients", "patient_id", r"PAT\d{6}"),
    ("appointments", "appointment_id", r"APT\d{7}"),
    ("referrals", "referral_record_id", r"REC\d{7}"),
])
def test_identifiers_are_unique_and_well_formed(tables, table, column, pattern):
    values = tables[table][column]
    assert values.is_unique
    assert values.str.fullmatch(pattern).all()


def test_referral_ids_are_well_formed(tables):
    assert tables["referrals"]["referral_id"].str.fullmatch(r"REF\d{7}").all()


def test_duplicate_referral_ids_match_configured_rate(tables):
    referrals = tables["referrals"]
    _, counts = generate_data.data_quality_counts(SMALL_REFERRAL_COUNT)
    duplicate_rows = len(referrals) - referrals["referral_id"].nunique()
    assert duplicate_rows == counts["duplicate_referral_id"]
    assert duplicate_rows <= round(SMALL_REFERRAL_COUNT * config.DATA_QUALITY_RATES["duplicate_referral_id"])
    assert referrals["referral_id"].value_counts().max() <= 2


def test_duplicates_are_exact_business_copies(tables):
    referrals = tables["referrals"]
    duplicated = referrals[referrals["referral_id"].duplicated(keep=False)]
    business_columns = [c for c in referrals.columns if c != "referral_record_id"]
    assert len(duplicated.drop_duplicates(business_columns)) == duplicated["referral_id"].nunique()


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------
def test_referral_foreign_keys_are_valid(tables, canonical_referrals):
    referrals = canonical_referrals
    assert referrals["patient_id"].isin(tables["patients"]["patient_id"]).all()
    assert referrals["service_category_id"].isin(tables["service_categories"]["service_category_id"]).all()
    assert referrals["receiving_provider_id"].isin(tables["providers"]["provider_id"]).all()
    assert referrals["receiving_facility_id"].dropna().isin(tables["facilities"]["facility_id"]).all()


def test_provider_foreign_keys_are_valid(tables):
    providers = tables["providers"]
    assert providers["facility_id"].isin(tables["facilities"]["facility_id"]).all()
    assert providers["service_category_id"].isin(tables["service_categories"]["service_category_id"]).all()


def test_appointments_reference_canonical_referrals(tables, canonical_referrals):
    appointments = tables["appointments"]
    assert appointments["referral_id"].isin(canonical_referrals["referral_id"]).all()
    assert appointments["provider_id"].isin(tables["providers"]["provider_id"]).all()
    assert appointments["facility_id"].isin(tables["facilities"]["facility_id"]).all()


def test_providers_match_configured_facility_and_service(tables):
    offered = {(f["facility_id"], c) for f in config.FACILITIES for c in f["service_category_ids"]}
    providers = tables["providers"]
    pairs = set(zip(providers["facility_id"], providers["service_category_id"]))
    assert pairs == offered
    per_service = providers.groupby(["facility_id", "service_category_id"]).size()
    assert per_service.between(config.MIN_PROVIDERS_PER_SERVICE, config.MAX_PROVIDERS_PER_SERVICE).all()


def test_referral_provider_matches_referral_facility_and_service(tables, canonical_referrals):
    merged = canonical_referrals.merge(tables["providers"], left_on="receiving_provider_id",
                                       right_on="provider_id", suffixes=("", "_provider"))
    assert (merged["service_category_id"] == merged["service_category_id_provider"]).all()
    has_facility = merged["receiving_facility_id"].notna()
    assert (merged.loc[has_facility, "receiving_facility_id"]
            == merged.loc[has_facility, "facility_id"]).all()


def test_appointment_provider_matches_facility_and_service(tables, canonical_referrals):
    merged = (tables["appointments"]
              .merge(canonical_referrals[["referral_id", "service_category_id"]], on="referral_id")
              .merge(tables["providers"], on="provider_id", suffixes=("", "_provider")))
    assert (merged["facility_id"] == merged["facility_id_provider"]).all()
    assert (merged["service_category_id"] == merged["service_category_id_provider"]).all()


def test_external_referrals_go_to_out_of_network_facilities(tables, canonical_referrals):
    merged = (canonical_referrals
              .merge(tables["providers"], left_on="receiving_provider_id", right_on="provider_id",
                     suffixes=("", "_provider"))
              .merge(tables["facilities"], on="facility_id"))
    is_external = merged["referral_status"] == "Sent External"
    assert (merged.loc[is_external, "network_status"] == "Out-of-Network").all()
    assert (merged.loc[~is_external, "network_status"] == "In-Network").all()
    assert not tables["appointments"]["referral_id"].isin(merged.loc[is_external, "referral_id"]).any()


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def test_referral_dates_stay_in_reporting_year(canonical_referrals):
    referral_dates = to_dates(canonical_referrals["referral_date"])
    assert referral_dates.min() >= pd.Timestamp(config.REPORTING_START_DATE)
    assert referral_dates.max() <= pd.Timestamp(config.REPORTING_END_DATE)


def test_follow_up_dates_are_between_referral_and_extract_date(canonical_referrals):
    referral_dates = to_dates(canonical_referrals["referral_date"])
    for column in ["first_contact_date", "closed_date"]:
        values = to_dates(canonical_referrals[column])
        present = values.notna()
        assert (values[present] >= referral_dates[present]).all(), column
        assert (values[present] <= EXTRACT_DATE).all(), column


def test_appointment_dates_are_logically_ordered(tables, canonical_referrals):
    appointments = tables["appointments"].merge(
        canonical_referrals[["referral_id", "referral_date", "first_contact_date"]], on="referral_id")
    booked = to_dates(appointments["booked_date"])
    appointment_day = appointment_days(appointments)
    first_contact = to_dates(appointments["first_contact_date"])

    assert (booked >= to_dates(appointments["referral_date"])).all()
    assert (booked <= appointment_day).all()
    assert (booked <= EXTRACT_DATE).all()
    has_contact = first_contact.notna()
    assert (first_contact[has_contact] <= booked[has_contact]).all()
    assert (appointment_day.dt.weekday < 5).all()

    appointments = appointments.assign(day=appointment_day,
                                       sequence=appointments["appointment_sequence"].astype(int))
    appointments = appointments.sort_values(["referral_id", "sequence"])
    for _, group in appointments.groupby("referral_id"):
        assert group["sequence"].tolist() == list(range(1, len(group) + 1))
        assert group["day"].is_monotonic_increasing and group["day"].is_unique
    assert appointments["sequence"].max() <= config.MAX_APPOINTMENTS_PER_REFERRAL


def test_completed_appointments_have_appropriate_dates(tables, canonical_referrals):
    appointments = tables["appointments"].merge(
        canonical_referrals[["referral_id", "referral_date", "referral_status", "closed_date"]],
        on="referral_id")
    completed = appointments[appointments["appointment_status"] == "Completed"]
    day = appointment_days(completed)
    assert (day > to_dates(completed["referral_date"])).all()
    assert (day <= EXTRACT_DATE).all()
    assert completed["referral_id"].is_unique
    assert (completed["referral_status"] == "Completed").all()
    closed = to_dates(completed["closed_date"])
    assert (closed[closed.notna()] == day[closed.notna()]).all()


def test_appointment_status_sequence_is_consistent(tables, canonical_referrals):
    appointments = tables["appointments"].copy()
    appointments["sequence"] = appointments["appointment_sequence"].astype(int)
    last_sequence = appointments.groupby("referral_id")["sequence"].transform("max")
    is_last = appointments["sequence"] == last_sequence
    assert set(appointments.loc[~is_last, "appointment_status"]) <= {"Rescheduled", "Cancelled", "No-Show"}

    scheduled = appointments[appointments["appointment_status"] == "Scheduled"]
    assert is_last[scheduled.index].all()
    assert (appointment_days(scheduled) > EXTRACT_DATE).all()

    last = appointments[is_last].merge(canonical_referrals[["referral_id", "referral_status"]], on="referral_id")
    assert ((last["appointment_status"] == "Completed") == (last["referral_status"] == "Completed")).all()
    assert ((last["appointment_status"] == "Scheduled") == (last["referral_status"] == "Scheduled")).all()


def test_status_values_come_from_config(tables, canonical_referrals):
    assert set(canonical_referrals["referral_status"]) <= set(config.REFERRAL_STATUSES)
    assert set(canonical_referrals["closure_reason"].dropna()) <= set(config.CLOSURE_REASONS)
    assert set(canonical_referrals["urgency"]) <= set(config.URGENCY_LEVELS)
    assert set(canonical_referrals["referral_source"].dropna()) <= set(config.REFERRAL_SOURCES)
    assert set(tables["appointments"]["appointment_status"]) <= set(config.APPOINTMENT_STATUSES)
    assert set(tables["patients"]["insurance_type"]) <= set(config.INSURANCE_TYPES)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_same_seed_produces_byte_identical_files(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    generate_data.generate_dataset(2_000, 42, first)
    generate_data.generate_dataset(2_000, 42, second)
    for file_name in generate_data.OUTPUT_FILES.values():
        assert (first / file_name).read_bytes() == (second / file_name).read_bytes(), file_name


def test_different_seeds_produce_different_data(tmp_path):
    generate_data.generate_dataset(2_000, 42, tmp_path / "seed42")
    generate_data.generate_dataset(2_000, 7, tmp_path / "seed7")
    for file_name in ["providers.csv", "patients.csv", "referrals.csv", "appointments.csv"]:
        assert (tmp_path / "seed42" / file_name).read_bytes() != (tmp_path / "seed7" / file_name).read_bytes()


def test_csv_formatting_is_consistent(small_dataset_dir):
    raw = (small_dataset_dir / "referrals.csv").read_bytes()
    assert b"\r\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    for token in [b"nan", b"NaN", b"None", b"NaT"]:
        assert token not in raw


# ---------------------------------------------------------------------------
# Privacy and controlled missing values
# ---------------------------------------------------------------------------
def test_no_personal_identifiers_are_generated(tables):
    forbidden = re.compile(r"name|email|phone|address|street|zip|postal|ssn|birth|diagnos|note")
    for table in ["patients", "referrals", "appointments"]:
        for column in tables[table].columns:
            assert not forbidden.search(column), f"{table}.{column}"
    assert list(tables["patients"].columns) == ["patient_id", "age_group", "gender",
                                                "insurance_type", "home_region"]

    email = re.compile(r"[\w.+-]+@[\w-]+\.\w+")
    phone = re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
    street = re.compile(r"\b\d+\s+\w+(\s\w+)*\s(Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd)\b",
                        re.IGNORECASE)
    for name, frame in tables.items():
        text = frame.fillna("").astype(str).to_csv(index=False)
        assert not email.search(text), name
        assert not phone.search(text), name
        assert not street.search(text), name


def test_missing_values_only_in_approved_fields(tables):
    approved = {
        "referrals": {"referral_source", "receiving_facility_id", "first_contact_date",
                      "closure_reason", "closed_date"},
        "appointments": {"status_reason"},
    }
    for name, frame in tables.items():
        missing_columns = set(frame.columns[frame.isna().any()])
        assert missing_columns <= approved.get(name, set()), name


def test_controlled_missing_value_counts(tables, canonical_referrals):
    referrals = canonical_referrals
    _, counts = generate_data.data_quality_counts(SMALL_REFERRAL_COUNT)
    assert referrals["referral_source"].isna().sum() == counts["missing_referral_source"]
    assert referrals["receiving_facility_id"].isna().sum() == counts["missing_receiving_facility"]

    has_appointment = referrals["referral_id"].isin(tables["appointments"]["referral_id"])
    contact_proven = has_appointment | (referrals["referral_status"] == "Declined")
    blanked_contact = (contact_proven & referrals["first_contact_date"].isna()).sum()
    assert blanked_contact == min(counts["missing_first_contact_date"], contact_proven.sum())

    has_closure = referrals["closure_reason"].notna()
    missing_closed = (has_closure & referrals["closed_date"].isna()).sum()
    assert missing_closed == min(counts["missing_closed_date"], has_closure.sum())

    is_open = referrals["referral_status"].isin(OPEN_STATUSES)
    inconsistent = (is_open & referrals["closed_date"].notna()).sum()
    assert inconsistent == min(counts["inconsistent_closed_date"], is_open.sum())


def test_designed_blanks_follow_status_rules(tables, canonical_referrals):
    referrals = canonical_referrals
    no_reason = referrals[referrals["closure_reason"].isna()]
    assert set(no_reason["referral_status"]) <= {"Pending", "Scheduled", "Sent External"}
    closed = referrals[referrals["referral_status"].isin(CLOSED_STATUSES)]
    assert closed["closure_reason"].notna().all()

    appointments = tables["appointments"]
    needs_reason = appointments["appointment_status"].isin(["Cancelled", "Rescheduled"])
    assert appointments.loc[needs_reason, "status_reason"].notna().all()
    assert appointments.loc[~needs_reason, "status_reason"].isna().all()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def test_cli_defaults():
    args = generate_data.parse_args([])
    assert args.referrals == config.DEFAULT_REFERRAL_COUNT
    assert args.seed == config.DEFAULT_SEED


def test_cli_run_prints_summary(tmp_path, capsys):
    assert generate_data.main(["--referrals", "250", "--seed", "5", "--output-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Seed             : 5" in output
    assert "2025-01-01 to 2025-12-31" in output
    assert "fully synthetic" in output
    for file_name in generate_data.OUTPUT_FILES.values():
        assert file_name in output
        assert (tmp_path / file_name).exists()


@pytest.mark.parametrize("arguments, message", [
    (["--referrals", "0"], "must be at least 1"),
    (["--referrals", "-5"], "must be at least 1"),
    (["--referrals", "abc"], "must be a whole number"),
    (["--referrals", "1.5"], "must be a whole number"),
    (["--referrals", "1000001"], "must be at most"),
    (["--seed", "-1"], "must be zero or greater"),
    (["--seed", "x"], "must be a whole number"),
])
def test_invalid_cli_arguments_are_rejected(arguments, message, capsys):
    with pytest.raises(SystemExit) as error:
        generate_data.parse_args(arguments)
    assert error.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("referral_count, seed", [(0, 42), (-1, 42), (10, -1)])
def test_invalid_function_arguments_are_rejected(tmp_path, referral_count, seed):
    with pytest.raises(ValueError):
        generate_data.generate_dataset(referral_count, seed, tmp_path)


# ---------------------------------------------------------------------------
# Git ignore rules
# ---------------------------------------------------------------------------
def is_git_ignored(path):
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path],
                            cwd=PROJECT_ROOT, capture_output=True)
    if result.returncode not in (0, 1):
        pytest.skip("git check-ignore is not available here")
    return result.returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_generated_data_is_ignored_but_placeholders_are_not():
    ignored = [f"data/raw/{name}" for name in generate_data.OUTPUT_FILES.values()] + [
        "data/processed/referrals_clean.csv", "data/output/kpi_summary.csv",
        "referrals.db", "data/processed/referrals.sqlite",
        ".venv/pyvenv.cfg", "tests/__pycache__/x.pyc", ".pytest_cache/README.md",
        "powerbi/~$dashboard.pbix", "~$workbook.xlsx", "notes.tmp",
    ]
    tracked = [
        "data/raw/.gitkeep", "data/processed/.gitkeep", "data/output/.gitkeep",
        "sql/.gitkeep", "powerbi/.gitkeep", "screenshots/.gitkeep",
        "powerbi/referral_dashboard.pbix", "screenshots/overview.png",
        "sql/analysis.sql", "README.md", "config.py", "generate_data.py",
    ]
    for path in ignored:
        assert is_git_ignored(path), f"{path} should be ignored"
    for path in tracked:
        assert not is_git_ignored(path), f"{path} should not be ignored"
