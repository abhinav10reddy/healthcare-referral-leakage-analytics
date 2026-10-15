"""Settings for the synthetic healthcare referral data generator.

Every value in this file is a fictional generator setting. Nothing here is
based on real patients, providers, facilities or published healthcare
benchmarks. The data is for portfolio and educational use only.
"""

from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to the project folder)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DATA_DIR = PROJECT_ROOT / "data" / "output"
SQL_DIR = PROJECT_ROOT / "sql"

# Phase 2 outputs (processed CSVs keep the raw file names)
SCHEMA_SQL_PATH = SQL_DIR / "01_create_schema.sql"
DATA_QUALITY_EXCEPTIONS_FILE = "data_quality_exceptions.csv"  # in PROCESSED_DATA_DIR
DATABASE_FILE = "healthcare_referrals.db"                     # in OUTPUT_DATA_DIR
DATA_QUALITY_REPORT_FILE = "phase2_data_quality.json"         # in OUTPUT_DATA_DIR

# ---------------------------------------------------------------------------
# Run settings
# ---------------------------------------------------------------------------
DEFAULT_REFERRAL_COUNT = 150_000  # rows in referrals.csv, duplicates included
DEFAULT_SEED = 42
MAX_REFERRAL_COUNT = 1_000_000  # guard against accidental huge runs

# ---------------------------------------------------------------------------
# Reporting period
# ---------------------------------------------------------------------------
# Referrals are created inside the reporting year. Follow-up activity
# (contact, scheduling, appointments, closure) is captured up to the data
# extract date, so late-December referrals can still show progress.
REPORTING_START_DATE = date(2025, 1, 1)
REPORTING_END_DATE = date(2025, 12, 31)
DATA_EXTRACT_DATE = date(2026, 1, 31)

# An unscheduled referral expires this many days after the referral date.
REFERRAL_EXPIRY_DAYS = 90

# Referral volume shape: relative weight by month and for weekend days.
MONTH_WEIGHTS = {
    1: 1.00, 2: 0.97, 3: 1.06, 4: 1.03, 5: 1.02, 6: 0.96,
    7: 0.92, 8: 0.98, 9: 1.04, 10: 1.07, 11: 0.99, 12: 0.90,
}
WEEKEND_REFERRAL_WEIGHT = 0.15

# ---------------------------------------------------------------------------
# Service categories
# ---------------------------------------------------------------------------
# referral_weight     : share of referral volume
# average_wait_days   : typical routine wait from booking to appointment
# external_rate       : share of referrals sent to out-of-network facilities
# no_show_rate        : base chance an appointment is a no-show
# target_days_to_appointment is exported as an illustrative benchmark.
SERVICE_CATEGORIES = [
    {
        "service_category_id": "SVC001", "service_category_name": "Cardiology",
        "service_line": "Medical Specialty", "target_days_to_appointment": 21,
        "referral_weight": 0.16, "average_wait_days": 18,
        "external_rate": 0.10, "no_show_rate": 0.06,
        "provider_types": {"Physician": 0.75, "Advanced Practice Provider": 0.25},
    },
    {
        "service_category_id": "SVC002", "service_category_name": "Orthopedics",
        "service_line": "Surgical Specialty", "target_days_to_appointment": 21,
        "referral_weight": 0.17, "average_wait_days": 20,
        "external_rate": 0.14, "no_show_rate": 0.05,
        "provider_types": {"Physician": 0.70, "Advanced Practice Provider": 0.30},
    },
    {
        "service_category_id": "SVC003", "service_category_name": "Neurology",
        "service_line": "Medical Specialty", "target_days_to_appointment": 28,
        "referral_weight": 0.10, "average_wait_days": 30,
        "external_rate": 0.16, "no_show_rate": 0.07,
        "provider_types": {"Physician": 0.80, "Advanced Practice Provider": 0.20},
    },
    {
        "service_category_id": "SVC004", "service_category_name": "Gastroenterology",
        "service_line": "Medical Specialty", "target_days_to_appointment": 28,
        "referral_weight": 0.11, "average_wait_days": 25,
        "external_rate": 0.12, "no_show_rate": 0.06,
        "provider_types": {"Physician": 0.80, "Advanced Practice Provider": 0.20},
    },
    {
        "service_category_id": "SVC005", "service_category_name": "Dermatology",
        "service_line": "Medical Specialty", "target_days_to_appointment": 30,
        "referral_weight": 0.10, "average_wait_days": 35,
        "external_rate": 0.18, "no_show_rate": 0.08,
        "provider_types": {"Physician": 0.65, "Advanced Practice Provider": 0.35},
    },
    {
        "service_category_id": "SVC006", "service_category_name": "Physical Therapy",
        "service_line": "Rehabilitation", "target_days_to_appointment": 10,
        "referral_weight": 0.15, "average_wait_days": 8,
        "external_rate": 0.08, "no_show_rate": 0.11,
        "provider_types": {"Therapist": 1.00},
    },
    {
        "service_category_id": "SVC007", "service_category_name": "Behavioral Health",
        "service_line": "Behavioral Health", "target_days_to_appointment": 14,
        "referral_weight": 0.12, "average_wait_days": 21,
        "external_rate": 0.15, "no_show_rate": 0.14,
        "provider_types": {"Physician": 0.30, "Therapist": 0.70},
    },
    {
        "service_category_id": "SVC008", "service_category_name": "General Surgery",
        "service_line": "Surgical Specialty", "target_days_to_appointment": 21,
        "referral_weight": 0.09, "average_wait_days": 16,
        "external_rate": 0.07, "no_show_rate": 0.04,
        "provider_types": {"Physician": 0.85, "Advanced Practice Provider": 0.15},
    },
]

# ---------------------------------------------------------------------------
# Facilities (all names are invented)
# ---------------------------------------------------------------------------
# wait_factor scales appointment wait times at that facility.
# service_category_ids lists the services each facility accepts referrals for.
FACILITIES = [
    {
        "facility_id": "FAC001", "facility_name": "Ambervale Regional Medical Center",
        "facility_type": "Hospital", "region": "North", "network_status": "In-Network",
        "wait_factor": 1.00,
        "service_category_ids": ["SVC001", "SVC002", "SVC003", "SVC004",
                                 "SVC005", "SVC006", "SVC007", "SVC008"],
    },
    {
        "facility_id": "FAC002", "facility_name": "Brightwater Community Hospital",
        "facility_type": "Hospital", "region": "South", "network_status": "In-Network",
        "wait_factor": 1.10,
        "service_category_ids": ["SVC001", "SVC002", "SVC004", "SVC006", "SVC008"],
    },
    {
        "facility_id": "FAC003", "facility_name": "Corrowind Heart and Vascular Clinic",
        "facility_type": "Specialty Clinic", "region": "Central", "network_status": "In-Network",
        "wait_factor": 0.90,
        "service_category_ids": ["SVC001"],
    },
    {
        "facility_id": "FAC004", "facility_name": "Dunmere Orthopedic and Spine Center",
        "facility_type": "Specialty Clinic", "region": "East", "network_status": "In-Network",
        "wait_factor": 1.20,
        "service_category_ids": ["SVC002", "SVC006", "SVC008"],
    },
    {
        "facility_id": "FAC005", "facility_name": "Elderglen Neurosciences Clinic",
        "facility_type": "Specialty Clinic", "region": "West", "network_status": "In-Network",
        "wait_factor": 1.30,
        "service_category_ids": ["SVC003"],
    },
    {
        "facility_id": "FAC006", "facility_name": "Fernhallow Digestive Health Center",
        "facility_type": "Specialty Clinic", "region": "Central", "network_status": "In-Network",
        "wait_factor": 1.00,
        "service_category_ids": ["SVC004", "SVC008"],
    },
    {
        "facility_id": "FAC007", "facility_name": "Glimmerton Skin and Wellness Clinic",
        "facility_type": "Outpatient Center", "region": "East", "network_status": "In-Network",
        "wait_factor": 1.15,
        "service_category_ids": ["SVC005"],
    },
    {
        "facility_id": "FAC008", "facility_name": "Hollowmere Rehabilitation Center",
        "facility_type": "Rehabilitation Center", "region": "South", "network_status": "In-Network",
        "wait_factor": 0.85,
        "service_category_ids": ["SVC006"],
    },
    {
        "facility_id": "FAC009", "facility_name": "Ivystone Behavioral Health Center",
        "facility_type": "Behavioral Health Center", "region": "West", "network_status": "In-Network",
        "wait_factor": 1.25,
        "service_category_ids": ["SVC007"],
    },
    {
        "facility_id": "FAC010", "facility_name": "Juniper Hollow Outpatient Center",
        "facility_type": "Outpatient Center", "region": "North", "network_status": "In-Network",
        "wait_factor": 0.95,
        "service_category_ids": ["SVC001", "SVC003", "SVC005", "SVC006", "SVC007"],
    },
    {
        "facility_id": "FAC011", "facility_name": "Kestrelmoor Independent Medical Group",
        "facility_type": "Independent Practice", "region": "Central", "network_status": "Out-of-Network",
        "wait_factor": 0.80,
        "service_category_ids": ["SVC001", "SVC003", "SVC004", "SVC005", "SVC007"],
    },
    {
        "facility_id": "FAC012", "facility_name": "Larkspur Valley Specialty Partners",
        "facility_type": "Independent Practice", "region": "East", "network_status": "Out-of-Network",
        "wait_factor": 0.90,
        "service_category_ids": ["SVC002", "SVC004", "SVC006", "SVC007", "SVC008"],
    },
]

FACILITY_WAIT_FACTOR = {f["facility_id"]: f["wait_factor"] for f in FACILITIES}

# Providers are generated per facility and service category.
MIN_PROVIDERS_PER_SERVICE = 2
MAX_PROVIDERS_PER_SERVICE = 5

# ---------------------------------------------------------------------------
# Patients (no names, contact details or clinical information)
# ---------------------------------------------------------------------------
PATIENTS_PER_REFERRAL = 0.40  # 150,000 referrals -> 60,000 patients

AGE_GROUPS = {"0-17": 0.08, "18-34": 0.18, "35-49": 0.20,
              "50-64": 0.26, "65-74": 0.16, "75+": 0.12}
SENIOR_AGE_GROUPS = ("65-74", "75+")
GENDERS = {"Female": 0.53, "Male": 0.46, "Unknown": 0.01}
REGIONS = {"North": 0.22, "South": 0.20, "East": 0.19, "West": 0.17, "Central": 0.22}

INSURANCE_WEIGHTS_UNDER_65 = {"Commercial": 0.62, "Medicaid": 0.24,
                              "Medicare": 0.04, "Self-Pay": 0.10}
INSURANCE_WEIGHTS_SENIOR = {"Commercial": 0.12, "Medicaid": 0.04,
                            "Medicare": 0.82, "Self-Pay": 0.02}
INSURANCE_TYPES = ("Commercial", "Medicaid", "Medicare", "Self-Pay")

# Behaviour differences by insurance type (multipliers on base rates).
INSURANCE_NO_SHOW_MULTIPLIER = {"Commercial": 1.00, "Medicaid": 1.35,
                                "Medicare": 0.85, "Self-Pay": 1.50}
INSURANCE_DECLINE_MULTIPLIER = {"Commercial": 1.00, "Medicaid": 1.10,
                                "Medicare": 0.90, "Self-Pay": 1.60}

# ---------------------------------------------------------------------------
# Referral attributes
# ---------------------------------------------------------------------------
URGENCY_LEVELS = {"Routine": 0.72, "Urgent": 0.23, "Stat": 0.05}
URGENCY_WAIT_MULTIPLIER = {"Routine": 1.00, "Urgent": 0.45, "Stat": 0.15}
URGENCY_CONTACT_MEAN_DAYS = {"Routine": 3.0, "Urgent": 1.2, "Stat": 0.4}

REFERRAL_SOURCES = {
    "Primary Care": 0.44, "Specialist": 0.18, "Emergency Department": 0.12,
    "Hospital Discharge": 0.10, "Urgent Care": 0.09, "Patient Portal": 0.07,
}

# ---------------------------------------------------------------------------
# Referral and appointment outcome settings (status distributions)
# ---------------------------------------------------------------------------
# Chance the patient is reached at least once, by referral source.
CONTACT_RATE_BY_SOURCE = {
    "Primary Care": 0.96, "Specialist": 0.97, "Emergency Department": 0.88,
    "Hospital Discharge": 0.97, "Urgent Care": 0.91, "Patient Portal": 0.90,
}
DECLINE_RATE = 0.06                 # contacted patient declines the referral
CHOSE_OTHER_PROVIDER_SHARE = 0.50   # share of declines recorded as "Chose Other Provider"
UNSCHEDULED_RATE = 0.05             # contacted, but never booked
SCHEDULING_MEAN_DAYS = 4.0          # typical days from first contact to booking
DELAYED_SCHEDULING_RATE = 0.10      # extra 14-45 day booking delay
CANCEL_RATE = 0.08                  # appointment cancelled
RESCHEDULE_RATE = 0.07              # appointment moved to a later date
CANCEL_REBOOK_RATE = 0.60           # cancelled appointment gets a replacement
NO_SHOW_REBOOK_RATE = 0.50          # no-show appointment gets a replacement
PROVIDER_CHANGE_RATE = 0.25         # replacement booked with another provider
EXTERNAL_OUTCOME_RECORDED_RATE = 0.55
MAX_APPOINTMENTS_PER_REFERRAL = 4

REFERRAL_STATUSES = ("Completed", "Scheduled", "Pending", "Declined",
                     "Cancelled", "Expired", "Sent External")
CLOSURE_REASONS = (
    "Appointment Completed", "Patient Declined", "Chose Other Provider",
    "Appointment Cancelled - Not Rebooked", "No-Show - Not Rebooked",
    "Referral Expired", "External Visit Confirmed",
)
APPOINTMENT_STATUSES = ("Completed", "Cancelled", "No-Show", "Rescheduled", "Scheduled")
CANCELLATION_REASONS = {
    "Patient Request": 0.40, "Provider Unavailable": 0.20,
    "Insurance Authorization Issue": 0.15, "Transportation Barrier": 0.15,
    "Clinic Schedule Change": 0.10,
}
RESCHEDULE_REASONS = {"Patient Request": 0.60, "Provider Schedule Change": 0.40}

# Appointment slots: every 30 minutes from 08:00 to 16:00.
FIRST_APPOINTMENT_HOUR = 8
APPOINTMENT_SLOTS_PER_DAY = 17

# ---------------------------------------------------------------------------
# Controlled data-quality issues (Phase 2 will flag and clean these)
# ---------------------------------------------------------------------------
# duplicate_referral_id is a share of all rows in referrals.csv. The other
# rates are shares of unique (canonical) referrals; each issue is applied to
# exactly round(rate * canonical referrals) eligible rows, or fewer when not
# enough eligible rows exist (very small runs).
DATA_QUALITY_RATES = {
    "duplicate_referral_id": 0.015,       # exact business copy, new referral_record_id
    "missing_referral_source": 0.020,     # referral_source blank
    "missing_receiving_facility": 0.010,  # receiving_facility_id blank (provider kept)
    "missing_first_contact_date": 0.015,  # blank although an appointment or decline exists
    "missing_closed_date": 0.010,         # closed status without closed_date
    "inconsistent_closed_date": 0.005,    # open status (Pending/Scheduled) with a closed_date
}
