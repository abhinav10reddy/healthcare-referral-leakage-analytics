"""Phase 4A tests: Power BI snapshot, expected KPIs, DAX, theme and documentation."""

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess

import pandas as pd
import pytest

import analyze_data
import config
import prepare_data
import prepare_powerbi_data as pbi
from conftest import PROJECT_ROOT

POWERBI = config.POWERBI_DIR
DATA = config.POWERBI_DATA_DIR
EXPECTED_PATH = POWERBI / config.POWERBI_EXPECTED_KPIS_FILE
DOCS = ["DATA_DICTIONARY.md", "POWER_BI_DATA_MODEL.md", "POWER_BI_BUILD_GUIDE.md",
        "POWER_BI_VERIFICATION_CHECKLIST.md"]
MEASURES = {  # measure -> text its definition must contain (Phase 3 flag or construct)
    "Total Referrals": "COUNTROWS ( Referrals )",
    "Scheduled Referrals": "Referrals[scheduled_flag] = 1",
    "Completed Referrals": "Referrals[completed_flag] = 1",
    "Converted Referrals": "Referrals[converted_flag] = 1",
    "Leaked Referrals": "Referrals[leakage_flag] = 1",
    "Active Referrals": "Referrals[active_flag] = 1",
    "Referrals with Cancellation": "Referrals[had_cancellation_flag] = 1",
    "Referrals with No Show": "Referrals[had_no_show_flag] = 1",
    "Delayed Scheduling Referrals": "Referrals[delayed_scheduling_flag] = 1",
    "Delayed Appointment Referrals": "Referrals[delayed_appointment_flag] = 1",
    "Referrals with Data Quality Issues": "Referrals[has_data_quality_issue] = 1",
    "Referrals with Duplicate Records": "Referrals[duplicate_record_count] > 0",
    "Data Quality Exceptions": "COUNTROWS ( DataQualityExceptions )",
    "Conversion Rate": "DIVIDE ( [Converted Referrals], [Total Referrals] )",
    "Leakage Rate": "DIVIDE ( [Leaked Referrals], [Total Referrals] )",
    "Scheduling Rate": "DIVIDE ( [Scheduled Referrals], [Total Referrals] )",
    "Completion Rate": "DIVIDE ( [Completed Referrals], [Total Referrals] )",
    "Median Days to First Contact": "NOT ISBLANK ( Referrals[days_to_first_contact] )",
    "Median Days to Schedule": "NOT ISBLANK ( Referrals[days_to_schedule] )",
    "Median Days to First Appointment": "NOT ISBLANK ( Referrals[days_to_first_appointment] )",
}
RATES = ["Conversion Rate", "Leakage Rate", "Scheduling Rate", "Completion Rate"]
RELATIONSHIPS = [
    ("Date[date]", "Referrals[referral_date]"),
    ("Providers[provider_id]", "Referrals[provider_id]"),
    ("ServiceCategories[service_category_id]", "Providers[service_category_id]"),
    ("Facilities[facility_id]", "Providers[facility_id]"),
    ("Referrals[referral_id]", "DataQualityExceptions[referral_id]"),
]
CARDS = {  # build-guide card -> expected_kpis key
    "Total Referrals": "total_referrals", "Converted Referrals": "converted_referrals",
    "Conversion Rate": "conversion_rate", "Leakage Rate": "leakage_rate",
    "Median Days to Schedule": "median_days_to_schedule",
    "Median Days to First Appointment": "median_days_to_first_appointment",
    "Leaked Referrals": "leaked_referrals", "Delayed Scheduling Referrals": "delayed_scheduling_referrals",
    "Delayed Appointment Referrals": "delayed_appointment_referrals", "Active Referrals": "active_referrals",
    "Median Days to First Contact": "median_days_to_first_contact",
    "Referrals with Data Quality Issues": "referrals_with_data_quality_issues",
    "Referrals with Duplicate Records": "referrals_with_duplicates",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def expected():
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def snapshot():
    return pbi.read_snapshot(DATA)


@pytest.fixture(scope="session")
def dax_text():
    return (POWERBI / "dax_measures.txt").read_text(encoding="utf-8")


def parse_measures(text):
    """Return {measure name: (preceding comment lines, expression)}."""
    measures, comments, current, body = {}, [], None, []
    for line in text.splitlines():
        match = re.match(r"^([A-Z][A-Za-z ]+?) =\s*$", line)
        if match:
            if current:
                measures[current] = (current_comments, "\n".join(body))
            current, current_comments, body = match.group(1), comments, []
            comments = []
        elif line.startswith("//"):
            if current:
                measures[current] = (current_comments, "\n".join(body))
                current = None
            comments.append(line)
        elif line.strip():
            body.append(line)
        else:
            if not current:
                comments = comments if comments and not comments[-1].startswith("// ---") else []
    if current:
        measures[current] = (current_comments, "\n".join(body))
    return measures


@pytest.fixture(scope="session")
def small_pipeline(small_dataset_dir, tmp_path_factory):
    """Phase 2 -> Phase 3 -> Power BI snapshot for the shared small dataset."""
    base = tmp_path_factory.mktemp("phase4")
    assert prepare_data.run_pipeline(small_dataset_dir, base / "processed", base / "output")["pipeline_status"] \
        == "succeeded"
    assert analyze_data.run_analysis(base / "output")["analytics_status"] == "succeeded"
    pbi.run_snapshot(base / "output", base / "powerbi")
    return base


def folder_hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# Tracked snapshot
# ---------------------------------------------------------------------------
def test_required_files_exist():
    for file_name in config.POWERBI_FILES.values():
        assert (DATA / file_name).is_file(), file_name
    for name in ["expected_kpis.json", "dax_measures.txt", "healthcare_referral_theme.json", *DOCS]:
        assert (POWERBI / name).is_file(), name


def test_snapshot_has_exact_columns(snapshot):
    for table, frame in snapshot.items():
        assert list(frame.columns) == pbi.COLUMNS[table], table


def test_referral_journey_has_all_unique_referrals(snapshot, expected):
    referrals = snapshot["Referrals"]
    assert len(referrals) == 147_750
    assert referrals["referral_id"].is_unique
    assert expected["snapshot"]["row_counts"]["referral_journey.csv"] == 147_750


def test_tracked_snapshot_passes_every_validation(expected):
    failures = [(name, problems) for name, problems in pbi.validate_snapshot(DATA, expected) if problems]
    assert failures == []


def test_model_keys_are_valid(snapshot):
    referrals, providers = snapshot["Referrals"], snapshot["Providers"]
    assert set(referrals["provider_id"]) <= set(providers["provider_id"])
    assert set(providers["facility_id"]) <= set(snapshot["Facilities"]["facility_id"])
    assert set(providers["service_category_id"]) <= set(snapshot["ServiceCategories"]["service_category_id"])
    assert set(referrals["referral_date"]) <= set(snapshot["Date"]["date"])
    assert set(snapshot["DataQualityExceptions"]["referral_id"].dropna()) <= set(referrals["referral_id"])
    for table, key in pbi.KEYS.items():
        assert snapshot[table][key].is_unique, table


def test_dates_and_numbers_use_stable_formats(snapshot):
    referrals = snapshot["Referrals"]
    for column in ["referral_date", "first_contact_date", "first_booking_date", "first_appointment_date"]:
        assert referrals[column].dropna().str.fullmatch(r"\d{4}-\d{2}-\d{2}").all(), column
    for column in pbi.FLAG_COLUMNS:
        assert set(referrals[column]) <= {"0", "1"}, column
    for column in pbi.DURATIONS:
        assert referrals[column].dropna().str.fullmatch(r"\d+").all(), column
    raw = (DATA / "referral_journey.csv").read_bytes()
    assert b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    for token in [b"nan", b"None", b"NaT", b".0,"]:
        assert token not in raw


def test_blanks_are_preserved(snapshot):
    referrals = snapshot["Referrals"]
    for duration, date_column in pbi.DURATIONS.items():
        assert (referrals[duration].isna() == referrals[date_column].isna()).all(), duration
    unscheduled = referrals[referrals["scheduled_flag"] == "0"]
    assert unscheduled["days_to_schedule"].isna().all() and unscheduled["first_booking_date"].isna().all()
    not_leaked = referrals[referrals["leakage_flag"] == "0"]
    assert not_leaked["primary_leakage_reason"].isna().all()
    assert not_leaked["leakage_reason_priority"].isna().all()
    assert (referrals["days_to_first_contact"].isna()).sum() > 0  # never replaced by 0


def test_outcome_flags_are_mutually_exclusive(snapshot):
    referrals = snapshot["Referrals"]
    flags = referrals[["converted_flag", "active_flag", "leakage_flag"]].astype(int)
    assert (flags.sum(axis=1) <= 1).all()
    for outcome, flag in [("Converted", "converted_flag"), ("Active", "active_flag"), ("Leaked", "leakage_flag")]:
        assert ((referrals["outcome"] == outcome) == (referrals[flag] == "1")).all()


def test_no_personal_information(snapshot):
    for frame in snapshot.values():
        for column in frame.columns:
            assert not re.search(r"patient_id|name_first|last_name|email|phone|address|street", column), column
    text = "".join((DATA / f).read_text(encoding="utf-8")[:200_000] for f in config.POWERBI_FILES.values())
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text)
    assert not re.search(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b", text)


# ---------------------------------------------------------------------------
# Date table
# ---------------------------------------------------------------------------
def test_date_table_is_continuous_and_complete(snapshot, expected):
    dates = pd.to_datetime(snapshot["Date"]["date"])
    assert (dates.diff().dropna() == pd.Timedelta(days=1)).all()
    assert dates.iloc[0] == pd.Timestamp(expected["reporting_period"]["start"])
    assert dates.iloc[-1] == pd.Timestamp(expected["reporting_period"]["end"])
    assert len(dates) == 365
    referral_dates = pd.to_datetime(snapshot["Referrals"]["referral_date"])
    assert referral_dates.min() >= dates.min() and referral_dates.max() <= dates.max()


def test_date_attributes_and_weekday_numbering(snapshot):
    dates = snapshot["Date"].set_index("date")
    monday, sunday = dates.loc["2025-01-06"], dates.loc["2025-01-05"]
    assert (monday["weekday_number"], monday["weekday_name"], monday["is_weekend"]) == ("1", "Monday", "0")
    assert (sunday["weekday_number"], sunday["weekday_name"], sunday["is_weekend"]) == ("7", "Sunday", "1")
    row = dates.loc["2025-05-15"]
    assert (row["year"], row["quarter_number"], row["quarter_label"]) == ("2025", "2", "Q2")
    assert (row["month_number"], row["month_name"], row["year_month"], row["year_month_sort"]) == \
        ("5", "May", "May 2025", "202505")
    assert (row["week_number"], row["day_of_month"]) == ("20", "15")
    assert dates.loc["2025-12-31", "week_number"] == "1"  # ISO week 1 of 2026


def test_sort_columns_map_one_to_one(snapshot):
    dates = snapshot["Date"]
    for label, sort in [("month_name", "month_number"), ("year_month", "year_month_sort"),
                        ("weekday_name", "weekday_number"), ("quarter_label", "quarter_number")]:
        pairs = dates[[label, sort]].drop_duplicates()
        assert pairs[label].is_unique and pairs[sort].is_unique, label
    reasons = snapshot["Referrals"][["primary_leakage_reason", "leakage_reason_priority"]].dropna().drop_duplicates()
    assert reasons["primary_leakage_reason"].is_unique and reasons["leakage_reason_priority"].is_unique


# ---------------------------------------------------------------------------
# Expected KPIs
# ---------------------------------------------------------------------------
def test_expected_kpis_hold_verified_seed42_values(expected):
    kpis = {k: v["value"] for k, v in expected["kpis"].items()}
    assert kpis["total_referrals"] == 147_750
    assert kpis["converted_referrals"] == 106_864 and kpis["leaked_referrals"] == 38_594
    assert kpis["active_referrals"] == 2_292
    assert kpis["delayed_scheduling_referrals"] == 6_831 and kpis["delayed_appointment_referrals"] == 58_388
    assert kpis["referrals_with_data_quality_issues"] == 10_805 and kpis["referrals_with_duplicates"] == 2_250
    assert (kpis["median_days_to_first_contact"], kpis["median_days_to_schedule"],
            kpis["median_days_to_first_appointment"]) == (1.0, 5.0, 21.0)
    displays = {k: v["display"] for k, v in expected["kpis"].items()}
    assert (displays["conversion_rate"], displays["leakage_rate"], displays["scheduling_rate"],
            displays["completion_rate"]) == ("72.3%", "26.1%", "73.5%", "65.8%")
    assert expected["reporting_period"] == {"start": "2025-01-01", "end": "2025-12-31"}
    assert expected["extract_date"] == "2026-01-31"
    assert expected["synthetic_data"] is True


def test_expected_rates_counts_reasons_and_funnel_reconcile(expected):
    kpis = {k: v["value"] for k, v in expected["kpis"].items()}
    total = kpis["total_referrals"]
    for rate, numerator in pbi.RATE_PARTS.items():
        assert kpis[rate] == pytest.approx(kpis[numerator] / total, abs=1e-6)
    assert sum(expected["outcomes"].values()) == total
    assert expected["outcomes"]["Leaked"] == kpis["leaked_referrals"]
    reasons = expected["leakage_reasons"]
    assert [r["priority"] for r in reasons] == [1, 2, 3, 4, 5, 6]
    assert sum(r["leaked_referrals"] for r in reasons) == kpis["leaked_referrals"]
    funnel = [s["referrals"] for s in expected["referral_funnel"]]
    assert funnel == [total, funnel[1], kpis["scheduled_referrals"], kpis["converted_referrals"]]
    assert funnel == sorted(funnel, reverse=True)
    assert sum(q["exceptions"] for q in expected["data_quality_by_issue_type"]) == kpis["data_quality_exceptions"]
    for key in pbi.GROUPED:
        assert sum(g["total_referrals"] for g in expected[key]) == total, key


def test_expected_kpis_match_phase3_sql(small_pipeline):
    expected = json.loads((small_pipeline / "powerbi" / config.POWERBI_EXPECTED_KPIS_FILE).read_text("utf-8"))
    connection = sqlite3.connect(small_pipeline / "output" / config.DATABASE_FILE)
    cursor = connection.execute("SELECT * FROM vw_overall_kpis")
    overall = dict(zip([d[0] for d in cursor.description], cursor.fetchone()))
    reasons = connection.execute("SELECT leakage_reason, leaked_referrals FROM vw_leakage_reason_metrics "
                                 "ORDER BY priority").fetchall()
    funnel = connection.execute("SELECT referrals FROM vw_referral_funnel ORDER BY stage_order").fetchall()
    connection.close()
    for name, item in expected["kpis"].items():
        assert item["value"] == pytest.approx(overall[name], abs=1e-6), name
    assert [(r["leakage_reason"], r["leaked_referrals"]) for r in expected["leakage_reasons"]] == reasons
    assert [s["referrals"] for s in expected["referral_funnel"]] == [r[0] for r in funnel]


def test_small_snapshot_matches_sqlite(small_pipeline):
    expected = json.loads((small_pipeline / "powerbi" / config.POWERBI_EXPECTED_KPIS_FILE).read_text("utf-8"))
    results = pbi.validate_snapshot(small_pipeline / "powerbi" / "data", expected,
                                    small_pipeline / "output" / config.DATABASE_FILE)
    assert [name for name, problems in results if problems] == []
    assert len(results) >= 12


# ---------------------------------------------------------------------------
# Rebuilds and failures
# ---------------------------------------------------------------------------
def test_snapshot_rebuild_is_deterministic(small_pipeline, tmp_path):
    pbi.run_snapshot(small_pipeline / "output", tmp_path / "powerbi")
    assert folder_hashes(tmp_path / "powerbi") == folder_hashes(small_pipeline / "powerbi")


def test_failed_validation_keeps_previous_snapshot(small_pipeline, tmp_path, monkeypatch):
    target = tmp_path / "powerbi"
    shutil.copytree(small_pipeline / "powerbi", target)
    before = folder_hashes(target)
    original = pbi.build_date_table
    monkeypatch.setattr(pbi, "build_date_table", lambda dates: original(dates)[:-1])  # drop 31 December
    with pytest.raises(pbi.SnapshotError, match="date_table_valid"):
        pbi.run_snapshot(small_pipeline / "output", target)
    assert folder_hashes(target) == before
    assert not list(target.glob(".snapshot_staging_*"))


def test_missing_database_gives_helpful_error(tmp_path, capsys):
    assert pbi.main(["--output-dir", str(tmp_path / "output"), "--powerbi-dir", str(tmp_path / "pbi")]) == 1
    error = capsys.readouterr().err
    assert "database not found" in error and "prepare_data.py" in error and "analyze_data.py" in error
    assert not (tmp_path / "pbi").exists()


def test_failed_phase3_is_rejected(small_pipeline, tmp_path):
    output = tmp_path / "output"
    shutil.copytree(small_pipeline / "output", output)
    summary_path = output / config.ANALYTICS_SUMMARY_FILE
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["analytics_status"] = "failed"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(pbi.SnapshotError, match="Phase 3"):
        pbi.run_snapshot(output, tmp_path / "powerbi")


# ---------------------------------------------------------------------------
# DAX
# ---------------------------------------------------------------------------
def test_all_required_measures_exist_once(dax_text):
    names = re.findall(r"^([A-Z][A-Za-z ]+?) =\s*$", dax_text, flags=re.MULTILINE)
    assert len(names) == len(set(names)) == 20
    assert set(names) == set(MEASURES)


def test_measure_definitions_follow_phase3(dax_text):
    measures = parse_measures(dax_text)
    for name, required in MEASURES.items():
        comments, expression = measures[name]
        assert required in expression, name
        assert any(c.startswith("// Format:") for c in comments), f"{name} has no format line"
        assert any(c.startswith(f"// {name}:") for c in comments), f"{name} has no comment"


def test_rates_use_divide_and_never_slash(dax_text):
    measures = parse_measures(dax_text)
    for name in RATES:
        expression = measures[name][1]
        assert "DIVIDE" in expression and "/" not in expression, name
    code = "\n".join(line for line in dax_text.splitlines() if not line.lstrip().startswith("//"))
    assert "/" not in code


def test_dax_column_references_exist(dax_text):
    code = "\n".join(line for line in dax_text.splitlines() if not line.lstrip().startswith("//"))
    for table, column in re.findall(r"(\w+)\[(\w+)\]", code):
        assert table in pbi.COLUMNS and column in pbi.COLUMNS[table], f"{table}[{column}]"


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
def test_theme_is_valid_json_with_expected_colours():
    theme = json.loads((POWERBI / "healthcare_referral_theme.json").read_text(encoding="utf-8"))
    assert theme["name"]
    colours = [c.upper() for c in theme["dataColors"]]
    for colour in ["#2F6DB5", "#1A8A7D", "#2E7D4F", "#C8553D", "#8A939E"]:
        assert colour in colours
    assert colours[0] == "#2F6DB5"
    assert (theme["good"], theme["bad"], theme["background"]) == ("#2E7D4F", "#C8553D", "#FFFFFF")
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in colours)


def test_no_claim_that_category_colours_map_automatically():
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    assert "manually" in guide and "cannot" in guide
    for name in DOCS:
        text = (POWERBI / name).read_text(encoding="utf-8").lower()
        assert not re.search(r"automatically (assign|map|apply|colou?r)", text), name


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------
def test_relationships_are_documented():
    model = (POWERBI / "POWER_BI_DATA_MODEL.md").read_text(encoding="utf-8")
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    for one, many in RELATIONSHIPS:
        assert f"`{one}` | `{many}`" in model, (one, many)
        assert f"`{one}` | `{many}`" in guide, (one, many)
    assert "```mermaid" in model and "Single" in model and "Mark as date table" in model
    assert "Auto date/time" in model


def test_three_pages_are_documented():
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    for page in ["Page 1: Referral Overview", "Page 2: Leakage and Service Performance",
                 "Page 3: Turnaround Time and Data Quality"]:
        assert f"### {page}" in guide
    assert guide.count("Wireframe") >= 3


PAGE_HEADINGS = ["### Page 1: Referral Overview", "### Page 2: Leakage and Service Performance",
                 "### Page 3: Turnaround Time and Data Quality", "## Step 10"]
CANVAS_WIDTH, CANVAS_HEIGHT, MARGIN, GAP = 1920, 1080, 20, 16


def page_sections(guide):
    starts = [guide.index(heading) for heading in PAGE_HEADINGS]
    return [guide[start:end] for start, end in zip(starts, starts[1:])]


def test_every_page_uses_a_1920_by_1080_canvas():
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    sections = page_sections(guide)
    assert len(sections) == 3
    for section in sections:
        assert "Canvas: custom 1920 × 1080." in section
        assert "Wireframe (1920 × 1080)" in section
    assert "**Type: Custom**, **Width: 1920**" in guide and "**Height: 1080**" in guide
    assert "Set it by hand on each page" in guide
    assert "The theme file does not set page dimensions" in guide
    checklist = (POWERBI / "POWER_BI_VERIFICATION_CHECKLIST.md").read_text(encoding="utf-8")
    assert "**Width 1920**" in checklist and "**Height 1080**" in checklist
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "custom 1920 × 1080" in readme
    for path, text in [("guide", guide), ("checklist", checklist), ("README", readme)]:
        assert not re.search(r"\b1280\b|\b720\b", text), f"obsolete canvas size in {path}"
    theme = json.loads((POWERBI / "healthcare_referral_theme.json").read_text(encoding="utf-8"))
    assert not re.search(r"1920|1080|pageSize|canvas", json.dumps(theme), re.IGNORECASE)


def test_documented_positions_fit_the_canvas_without_overlap():
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    notice = tuple(map(int, re.search(r"text box at `(\d+), (\d+), (\d+), (\d+)`", guide).groups()))
    for section, visuals in zip(page_sections(guide), [13, 11, 14]):
        boxes = [tuple(map(int, m)) for m in re.findall(r"\| (\d+), (\d+), (\d+), (\d+) \|", section)]
        assert len(boxes) == visuals
        boxes.append(notice)
        for x, y, w, h in boxes:
            assert x >= MARGIN and y >= MARGIN, (x, y, w, h)
            assert x + w <= CANVAS_WIDTH - MARGIN and y + h <= CANVAS_HEIGHT - MARGIN, (x, y, w, h)
        for i, (ax, ay, aw, ah) in enumerate(boxes):
            for bx, by, bw, bh in boxes[i + 1:]:
                apart = (ax + aw + GAP <= bx or bx + bw + GAP <= ax
                         or ay + ah + GAP <= by or by + bh + GAP <= ay)
                assert apart, ((ax, ay, aw, ah), (bx, by, bw, bh))


def test_card_values_in_guide_match_expected_kpis(expected):
    guide = (POWERBI / "POWER_BI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    for card, key in CARDS.items():
        assert f"| {card} | {expected['kpis'][key]['display']} |" in guide, card


def test_old_project_content_is_absent():
    forbidden = ["capacity", "booking rate", "available slots", "slot utilization", "average wait",
                 "providerschedules", "appointments by department", "patient flow", "patient_flow",
                 "operational_overview", "capacity_provider_performance", "patient_appointment_patterns",
                 "healthcare_theme.json", "unique patients", "department_name"]
    files = [POWERBI / name for name in DOCS + ["dax_measures.txt", "healthcare_referral_theme.json",
                                                "expected_kpis.json"]]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term not in text, f"{term!r} in {path.name}"


def test_planned_pbix_and_screenshot_names():
    assert config.POWERBI_PBIX_PATH == "powerbi/healthcare_referral_leakage_dashboard.pbix"
    for name in ["POWER_BI_BUILD_GUIDE.md", "POWER_BI_VERIFICATION_CHECKLIST.md"]:
        text = (POWERBI / name).read_text(encoding="utf-8")
        assert config.POWERBI_PBIX_PATH in text, name
        for screenshot in config.POWERBI_SCREENSHOTS:
            assert screenshot in text, (name, screenshot)


# ---------------------------------------------------------------------------
# Git and file sizes
# ---------------------------------------------------------------------------
def git_ignored(path):
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=PROJECT_ROOT,
                            capture_output=True)
    if result.returncode not in (0, 1):
        pytest.skip("git check-ignore is not available")
    return result.returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_powerbi_assets_are_trackable_and_outputs_ignored():
    assets = [f"powerbi/data/{f}" for f in config.POWERBI_FILES.values()] + [
        f"powerbi/{name}" for name in ["expected_kpis.json", "dax_measures.txt",
                                       "healthcare_referral_theme.json", *DOCS]]
    assets += ["prepare_powerbi_data.py", "tests/test_powerbi_assets.py", config.POWERBI_PBIX_PATH,
               *config.POWERBI_SCREENSHOTS]
    for path in assets:
        assert not git_ignored(path), path
    for path in ["data/raw/referrals.csv", "data/processed/referrals.csv", "data/output/referral_journey.csv",
                 "data/output/healthcare_referrals.db", "data/output/phase3_analytics_summary.json"]:
        assert git_ignored(path), path


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_snapshot_keeps_lf_line_endings_on_checkout():
    paths = [f"powerbi/data/{f}" for f in config.POWERBI_FILES.values()] + ["powerbi/expected_kpis.json"]
    result = subprocess.run(["git", "check-attr", "eol", "--", *paths], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("git check-attr is not available")
    for line in result.stdout.splitlines():
        assert line.endswith(": eol: lf"), line


def test_every_powerbi_file_is_below_the_safe_size_limit():
    assert config.POWERBI_MAX_FILE_BYTES <= 50 * 1024 * 1024 < 100 * 1024 * 1024
    files = [p for p in POWERBI.rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert path.stat().st_size < config.POWERBI_MAX_FILE_BYTES, path.name
