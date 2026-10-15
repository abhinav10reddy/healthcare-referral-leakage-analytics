"""Generate fully synthetic healthcare referral data (Phase 1).

Every record is fictional and produced by a single seeded random-number
generator, so the same seed and package versions always give byte-identical
CSV files. The output is for portfolio and educational use only and must not
be used for clinical decision-making.

Usage (PowerShell, from the project folder):
    .\\.venv\\Scripts\\python.exe generate_data.py
    .\\.venv\\Scripts\\python.exe generate_data.py --referrals 150000 --seed 42
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import config

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

SYNTHETIC_DATA_NOTICE = (
    "All records are fully synthetic and fictional. They contain no real patient "
    "information and are for portfolio and educational use only, not for clinical "
    "decision-making."
)

OUTPUT_FILES = {
    "service_categories": "service_categories.csv",
    "facilities": "facilities.csv",
    "providers": "providers.csv",
    "patients": "patients.csv",
    "referrals": "referrals.csv",
    "appointments": "appointments.csv",
}

COLUMNS = {
    "service_categories": [
        "service_category_id", "service_category_name", "service_line",
        "target_days_to_appointment",
    ],
    "facilities": [
        "facility_id", "facility_name", "facility_type", "region", "network_status",
    ],
    "providers": [
        "provider_id", "provider_name", "provider_type", "facility_id",
        "service_category_id",
    ],
    "patients": [
        "patient_id", "age_group", "gender", "insurance_type", "home_region",
    ],
    "referrals": [
        "referral_record_id", "referral_id", "patient_id", "service_category_id",
        "receiving_facility_id", "receiving_provider_id", "referral_source",
        "urgency", "referral_date", "first_contact_date", "referral_status",
        "closure_reason", "closed_date",
    ],
    "appointments": [
        "appointment_id", "referral_id", "appointment_sequence", "facility_id",
        "provider_id", "booked_date", "appointment_datetime",
        "appointment_status", "status_reason",
    ],
}

DATE_COLUMNS = {
    "referrals": ["referral_date", "first_contact_date", "closed_date"],
    "appointments": ["booked_date"],
}
DATETIME_COLUMNS = {"appointments": ["appointment_datetime"]}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def weighted_choice(rng, weights, size=None):
    """Pick option(s) from a {option: weight} dictionary."""
    options = list(weights)
    probabilities = np.array(list(weights.values()), dtype=float)
    probabilities = probabilities / probabilities.sum()
    picks = rng.choice(len(options), size=size, p=probabilities)
    if size is None:
        return options[int(picks)]
    return [options[i] for i in picks]


def next_weekday(day):
    """Move Saturday or Sunday forward to the following Monday."""
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def days(count):
    return timedelta(days=int(count))


def data_quality_counts(referral_count):
    """Return (unique referral count, target row count for each data-quality issue)."""
    rates = config.DATA_QUALITY_RATES
    duplicate_count = int(round(referral_count * rates["duplicate_referral_id"]))
    canonical_count = referral_count - duplicate_count
    counts = {"duplicate_referral_id": duplicate_count}
    for issue, rate in rates.items():
        if issue != "duplicate_referral_id":
            counts[issue] = int(round(canonical_count * rate))
    return canonical_count, counts


def patient_count_for(referral_count):
    return max(1, int(round(referral_count * config.PATIENTS_PER_REFERRAL)))


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------
def build_service_categories():
    return pd.DataFrame(config.SERVICE_CATEGORIES)[COLUMNS["service_categories"]]


def build_facilities():
    return pd.DataFrame(config.FACILITIES)[COLUMNS["facilities"]]


def build_providers(rng):
    categories = {c["service_category_id"]: c for c in config.SERVICE_CATEGORIES}
    rows = []
    for facility in config.FACILITIES:
        for category_id in facility["service_category_ids"]:
            category = categories[category_id]
            provider_count = rng.integers(config.MIN_PROVIDERS_PER_SERVICE,
                                          config.MAX_PROVIDERS_PER_SERVICE + 1)
            for _ in range(provider_count):
                number = len(rows) + 1
                rows.append({
                    "provider_id": f"PRV{number:03d}",
                    "provider_name": f"{category['service_category_name']} Provider {number:03d}",
                    "provider_type": weighted_choice(rng, category["provider_types"]),
                    "facility_id": facility["facility_id"],
                    "service_category_id": category_id,
                })
    return pd.DataFrame(rows, columns=COLUMNS["providers"])


def build_patients(rng, patient_count):
    age_groups = weighted_choice(rng, config.AGE_GROUPS, patient_count)
    genders = weighted_choice(rng, config.GENDERS, patient_count)
    regions = weighted_choice(rng, config.REGIONS, patient_count)
    insurance_under_65 = weighted_choice(rng, config.INSURANCE_WEIGHTS_UNDER_65, patient_count)
    insurance_senior = weighted_choice(rng, config.INSURANCE_WEIGHTS_SENIOR, patient_count)
    insurance = [
        senior if age in config.SENIOR_AGE_GROUPS else under_65
        for age, senior, under_65 in zip(age_groups, insurance_senior, insurance_under_65)
    ]
    return pd.DataFrame({
        "patient_id": [f"PAT{i:06d}" for i in range(1, patient_count + 1)],
        "age_group": age_groups,
        "gender": genders,
        "insurance_type": insurance,
        "home_region": regions,
    })


# ---------------------------------------------------------------------------
# Referrals and appointments
# ---------------------------------------------------------------------------
def build_referral_dates(rng, count):
    """Draw referral dates across the reporting year, sorted ascending."""
    total_days = (config.REPORTING_END_DATE - config.REPORTING_START_DATE).days + 1
    calendar = [config.REPORTING_START_DATE + days(i) for i in range(total_days)]
    weights = np.array([
        config.MONTH_WEIGHTS[d.month] * (config.WEEKEND_REFERRAL_WEIGHT if d.weekday() >= 5 else 1.0)
        for d in calendar
    ])
    picks = np.sort(rng.choice(total_days, size=count, p=weights / weights.sum()))
    return [calendar[i] for i in picks]


def close_referral(outcome, status, reason, closed_date):
    """Close the referral if the closure happened by the extract date; otherwise it stays Pending."""
    if closed_date <= config.DATA_EXTRACT_DATE:
        outcome.update(referral_status=status, closure_reason=reason, closed_date=closed_date)


def simulate_referral(rng, referral_date, category, urgency, source, insurance_type,
                      facility_id, provider_id, provider_pool, is_external):
    """Follow one referral from creation to its status on the extract date.

    Returns (outcome dictionary, list of appointment dictionaries).
    """
    extract_date = config.DATA_EXTRACT_DATE
    expiry_date = referral_date + days(config.REFERRAL_EXPIRY_DAYS)
    outcome = {"first_contact_date": None, "referral_status": "Pending",
               "closure_reason": None, "closed_date": None}
    appointments = []

    def expire_or_stay_pending():
        if expiry_date <= extract_date:
            close_referral(outcome, "Expired", "Referral Expired", expiry_date)
        return outcome, appointments

    # Step 1: first contact with the patient.
    if rng.random() < config.CONTACT_RATE_BY_SOURCE[source]:
        contact_lag = rng.exponential(config.URGENCY_CONTACT_MEAN_DAYS[urgency])
        first_contact = referral_date + days(contact_lag)
        if first_contact <= extract_date:
            outcome["first_contact_date"] = first_contact

    # Step 2: out-of-network referrals leave our system; the outcome may or may not come back.
    if is_external:
        outcome["referral_status"] = "Sent External"
        if rng.random() < config.EXTERNAL_OUTCOME_RECORDED_RATE:
            confirmed_date = referral_date + days(rng.integers(14, 61))
            if confirmed_date <= extract_date:
                outcome.update(closure_reason="External Visit Confirmed", closed_date=confirmed_date)
        return outcome, appointments

    first_contact = outcome["first_contact_date"]
    if first_contact is None:
        return expire_or_stay_pending()

    # Step 3: the patient may decline, or the referral may never be booked.
    if rng.random() < config.DECLINE_RATE * config.INSURANCE_DECLINE_MULTIPLIER[insurance_type]:
        reason = ("Chose Other Provider" if rng.random() < config.CHOSE_OTHER_PROVIDER_SHARE
                  else "Patient Declined")
        close_referral(outcome, "Declined", reason, first_contact + days(rng.integers(0, 4)))
        return outcome, appointments
    if rng.random() < config.UNSCHEDULED_RATE:
        return expire_or_stay_pending()

    # Step 4: book the first appointment.
    booking_lag = rng.exponential(config.SCHEDULING_MEAN_DAYS)
    if rng.random() < config.DELAYED_SCHEDULING_RATE:
        booking_lag += rng.integers(14, 46)
    booked_date = first_contact + days(booking_lag)
    if booked_date > expiry_date or booked_date > extract_date:
        return expire_or_stay_pending()

    wait_mean = (category["average_wait_days"] * config.URGENCY_WAIT_MULTIPLIER[urgency]
                 * config.FACILITY_WAIT_FACTOR[facility_id])
    appointment_date = next_weekday(booked_date + days(1 + rng.gamma(2.0, wait_mean / 2.0)))
    no_show_rate = category["no_show_rate"] * config.INSURANCE_NO_SHOW_MULTIPLIER[insurance_type]

    # Step 5: follow the appointment chain (reschedules, cancellations, no-shows).
    for sequence in range(1, config.MAX_APPOINTMENTS_PER_REFERRAL + 1):
        slot = int(rng.integers(config.APPOINTMENT_SLOTS_PER_DAY))
        start_time = time(config.FIRST_APPOINTMENT_HOUR + slot // 2, 30 * (slot % 2))
        appointment = {
            "appointment_sequence": sequence,
            "facility_id": facility_id,
            "provider_id": provider_id,
            "booked_date": booked_date,
            "appointment_datetime": datetime.combine(appointment_date, start_time),
            "appointment_status": "Scheduled",
            "status_reason": None,
        }
        appointments.append(appointment)

        if appointment_date > extract_date:
            outcome["referral_status"] = "Scheduled"
            return outcome, appointments

        is_last = sequence == config.MAX_APPOINTMENTS_PER_REFERRAL
        reschedule_rate = 0.0 if is_last else config.RESCHEDULE_RATE
        draw = rng.random()
        if draw < reschedule_rate:
            appointment["appointment_status"] = "Rescheduled"
            appointment["status_reason"] = weighted_choice(rng, config.RESCHEDULE_REASONS)
            # The move is agreed on or before the original date.
            booked_date = booked_date + days(rng.integers(0, (appointment_date - booked_date).days + 1))
            next_date = appointment_date + days(rng.integers(3, 22))
        elif draw < reschedule_rate + config.CANCEL_RATE:
            appointment["appointment_status"] = "Cancelled"
            appointment["status_reason"] = weighted_choice(rng, config.CANCELLATION_REASONS)
            if is_last or rng.random() >= config.CANCEL_REBOOK_RATE:
                close_referral(outcome, "Cancelled", "Appointment Cancelled - Not Rebooked",
                               appointment_date + days(rng.integers(0, 15)))
                return outcome, appointments
            booked_date = booked_date + days(rng.integers(0, (appointment_date - booked_date).days + 8))
            next_date = max(booked_date, appointment_date) + days(rng.integers(5, 31))
        elif draw < reschedule_rate + config.CANCEL_RATE + no_show_rate:
            appointment["appointment_status"] = "No-Show"
            if is_last or rng.random() >= config.NO_SHOW_REBOOK_RATE:
                close_referral(outcome, "Cancelled", "No-Show - Not Rebooked",
                               appointment_date + days(rng.integers(0, 15)))
                return outcome, appointments
            booked_date = appointment_date + days(rng.integers(1, 11))
            next_date = booked_date + days(rng.integers(5, 31))
        else:
            appointment["appointment_status"] = "Completed"
            close_referral(outcome, "Completed", "Appointment Completed", appointment_date)
            return outcome, appointments

        # A replacement booked after the extract date is not visible yet.
        if booked_date > extract_date:
            return outcome, appointments
        if rng.random() < config.PROVIDER_CHANGE_RATE:
            provider_id = provider_pool[rng.integers(len(provider_pool))]
        appointment_date = next_weekday(next_date)

    return outcome, appointments


def build_referrals_and_appointments(rng, canonical_count, patients, providers):
    categories = {c["service_category_id"]: c for c in config.SERVICE_CATEGORIES}
    facilities_by_service = {}
    for facility in config.FACILITIES:
        for category_id in facility["service_category_ids"]:
            key = (category_id, facility["network_status"])
            facilities_by_service.setdefault(key, []).append(facility["facility_id"])
    providers_by_service = {}
    for row in providers.itertuples(index=False):
        providers_by_service.setdefault((row.facility_id, row.service_category_id), []).append(row.provider_id)

    referral_dates = build_referral_dates(rng, canonical_count)
    category_weights = {c["service_category_id"]: c["referral_weight"] for c in config.SERVICE_CATEGORIES}
    category_ids = weighted_choice(rng, category_weights, canonical_count)
    urgencies = weighted_choice(rng, config.URGENCY_LEVELS, canonical_count)
    sources = weighted_choice(rng, config.REFERRAL_SOURCES, canonical_count)
    patient_rows = rng.integers(0, len(patients), canonical_count)
    patient_ids = patients["patient_id"].tolist()
    insurance_types = patients["insurance_type"].tolist()

    referrals = []
    appointments = []
    for i in range(canonical_count):
        category_id = category_ids[i]
        category = categories[category_id]
        is_external = rng.random() < category["external_rate"]
        network_status = "Out-of-Network" if is_external else "In-Network"
        facility_options = facilities_by_service[(category_id, network_status)]
        facility_id = facility_options[rng.integers(len(facility_options))]
        provider_pool = providers_by_service[(facility_id, category_id)]
        provider_id = provider_pool[rng.integers(len(provider_pool))]
        patient_row = patient_rows[i]
        referral_id = f"REF{i + 1:07d}"

        outcome, referral_appointments = simulate_referral(
            rng, referral_dates[i], category, urgencies[i], sources[i], insurance_types[patient_row],
            facility_id, provider_id, provider_pool, is_external,
        )
        referrals.append({
            "referral_id": referral_id,
            "patient_id": patient_ids[patient_row],
            "service_category_id": category_id,
            "receiving_facility_id": facility_id,
            "receiving_provider_id": provider_id,
            "referral_source": sources[i],
            "urgency": urgencies[i],
            "referral_date": referral_dates[i],
            **outcome,
        })
        for appointment in referral_appointments:
            appointments.append({
                "appointment_id": f"APT{len(appointments) + 1:07d}",
                "referral_id": referral_id,
                **appointment,
            })

    referrals_frame = pd.DataFrame(referrals)
    appointments_frame = pd.DataFrame(appointments, columns=COLUMNS["appointments"])
    return referrals_frame, appointments_frame


# ---------------------------------------------------------------------------
# Controlled data-quality issues
# ---------------------------------------------------------------------------
def pick_rows(rng, eligible_mask, count):
    """Choose up to `count` row positions from the eligible rows, without repeats."""
    eligible = np.flatnonzero(np.asarray(eligible_mask))
    count = min(count, len(eligible))
    return np.sort(rng.choice(eligible, size=count, replace=False))


def apply_data_quality_issues(rng, referrals, appointments, counts):
    referrals = referrals.copy()
    index = referrals.index

    rows = pick_rows(rng, np.ones(len(referrals), dtype=bool), counts["missing_referral_source"])
    referrals.loc[index[rows], "referral_source"] = None

    rows = pick_rows(rng, np.ones(len(referrals), dtype=bool), counts["missing_receiving_facility"])
    referrals.loc[index[rows], "receiving_facility_id"] = None

    # Only blank first contact where contact clearly happened, so Phase 2 can detect it.
    has_appointment = referrals["referral_id"].isin(set(appointments["referral_id"]))
    contact_proven = has_appointment | (referrals["referral_status"] == "Declined")
    eligible = contact_proven & referrals["first_contact_date"].notna()
    rows = pick_rows(rng, eligible, counts["missing_first_contact_date"])
    referrals.loc[index[rows], "first_contact_date"] = None

    eligible = referrals["closed_date"].notna()
    rows = pick_rows(rng, eligible, counts["missing_closed_date"])
    referrals.loc[index[rows], "closed_date"] = None

    eligible = referrals["referral_status"].isin(["Pending", "Scheduled"]) & referrals["closed_date"].isna()
    rows = pick_rows(rng, eligible, counts["inconsistent_closed_date"])
    offsets = rng.integers(7, 61, size=len(rows))
    referrals.loc[index[rows], "closed_date"] = [
        min(referral_date + days(offset), config.DATA_EXTRACT_DATE)
        for referral_date, offset in zip(referrals.loc[index[rows], "referral_date"], offsets)
    ]
    return referrals


def add_duplicate_records(rng, referrals, duplicate_count):
    """Repeat some referrals once, right after the original, and number every row."""
    copies = np.ones(len(referrals), dtype=int)
    copies[rng.choice(len(referrals), size=duplicate_count, replace=False)] = 2
    result = referrals.loc[referrals.index.repeat(copies)].reset_index(drop=True)
    result.insert(0, "referral_record_id", [f"REC{i:07d}" for i in range(1, len(result) + 1)])
    return result[COLUMNS["referrals"]]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def format_values(series, fmt):
    return [None if pd.isna(value) else value.strftime(fmt) for value in series]


def write_csv(frame, path):
    frame.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")


def generate_dataset(referral_count=config.DEFAULT_REFERRAL_COUNT, seed=config.DEFAULT_SEED,
                     output_dir=config.RAW_DATA_DIR):
    """Generate all six raw CSV files and return {file name: row count}."""
    if referral_count < 1 or referral_count > config.MAX_REFERRAL_COUNT:
        raise ValueError(f"referral_count must be between 1 and {config.MAX_REFERRAL_COUNT:,}.")
    if seed < 0:
        raise ValueError("seed must be zero or a positive whole number.")

    rng = np.random.default_rng(seed)
    canonical_count, dq_counts = data_quality_counts(referral_count)

    providers = build_providers(rng)
    patients = build_patients(rng, patient_count_for(referral_count))
    referrals, appointments = build_referrals_and_appointments(rng, canonical_count, patients, providers)
    referrals = apply_data_quality_issues(rng, referrals, appointments, dq_counts)
    referrals = add_duplicate_records(rng, referrals, dq_counts["duplicate_referral_id"])

    tables = {
        "service_categories": build_service_categories(),
        "facilities": build_facilities(),
        "providers": providers,
        "patients": patients,
        "referrals": referrals,
        "appointments": appointments,
    }

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    row_counts = {}
    for name, frame in tables.items():
        frame = frame.copy()
        for column in DATE_COLUMNS.get(name, []):
            frame[column] = format_values(frame[column], DATE_FORMAT)
        for column in DATETIME_COLUMNS.get(name, []):
            frame[column] = format_values(frame[column], DATETIME_FORMAT)
        file_name = OUTPUT_FILES[name]
        write_csv(frame[COLUMNS[name]], output_dir / file_name)
        row_counts[file_name] = len(frame)
    return row_counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def positive_referral_count(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got '{text}'.")
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}.")
    if value > config.MAX_REFERRAL_COUNT:
        raise argparse.ArgumentTypeError(
            f"must be at most {config.MAX_REFERRAL_COUNT:,}, got {value:,}.")
    return value


def non_negative_seed(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got '{text}'.")
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be zero or greater, got {value}.")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate deterministic synthetic healthcare referral data. " + SYNTHETIC_DATA_NOTICE)
    parser.add_argument("--referrals", type=positive_referral_count,
                        default=config.DEFAULT_REFERRAL_COUNT,
                        help=f"rows to write to referrals.csv, duplicates included "
                             f"(default: {config.DEFAULT_REFERRAL_COUNT})")
    parser.add_argument("--seed", type=non_negative_seed, default=config.DEFAULT_SEED,
                        help=f"random seed (default: {config.DEFAULT_SEED})")
    parser.add_argument("--output-dir", type=Path, default=config.RAW_DATA_DIR,
                        help="folder for the CSV files (default: data\\raw)")
    return parser.parse_args(argv)


def display_path(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(path)


def main(argv=None):
    args = parse_args(argv)
    row_counts = generate_dataset(args.referrals, args.seed, args.output_dir)

    print("Synthetic referral data generated successfully.")
    print(f"  Output folder    : {display_path(args.output_dir)}")
    print(f"  Seed             : {args.seed}")
    print(f"  Reporting period : {config.REPORTING_START_DATE:%Y-%m-%d} to "
          f"{config.REPORTING_END_DATE:%Y-%m-%d} "
          f"(activity captured through {config.DATA_EXTRACT_DATE:%Y-%m-%d})")
    print("  Rows written:")
    for file_name, count in row_counts.items():
        print(f"    {file_name:<24}{count:>10,}")
    print(f"NOTICE: {SYNTHETIC_DATA_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
