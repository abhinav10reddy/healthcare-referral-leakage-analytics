-- Healthcare Referral Leakage Analytics - Phase 2 SQLite schema
--
-- Drops and recreates the Phase 2 tables, so it is safe to rerun.
-- All data loaded into these tables is fully synthetic and for portfolio and
-- educational use only, not for clinical decision-making.
--
-- Conventions
--   TEXT    identifiers, categories, ISO dates (YYYY-MM-DD) and
--           date-times (YYYY-MM-DD HH:MM:SS)
--   INTEGER counts and 0/1 flags
--   Allowed category values mirror config.py; prepare_data.py validates the
--   data first, and these CHECK constraints are a second line of defence.

PRAGMA foreign_keys = ON;

-- Drop in reverse dependency order.
DROP TABLE IF EXISTS data_quality_exceptions;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS referrals;
DROP TABLE IF EXISTS patients;
DROP TABLE IF EXISTS providers;
DROP TABLE IF EXISTS facilities;
DROP TABLE IF EXISTS service_categories;

-- ---------------------------------------------------------------------------
-- Master tables
-- ---------------------------------------------------------------------------
CREATE TABLE service_categories (
    service_category_id         TEXT    PRIMARY KEY,
    service_category_name       TEXT    NOT NULL UNIQUE,
    service_line                TEXT    NOT NULL,
    target_days_to_appointment  INTEGER NOT NULL
        CHECK (target_days_to_appointment BETWEEN 1 AND 365)
);

CREATE TABLE facilities (
    facility_id     TEXT PRIMARY KEY,
    facility_name   TEXT NOT NULL UNIQUE,
    facility_type   TEXT NOT NULL,
    region          TEXT NOT NULL
        CHECK (region IN ('North', 'South', 'East', 'West', 'Central')),
    network_status  TEXT NOT NULL
        CHECK (network_status IN ('In-Network', 'Out-of-Network'))
);

CREATE TABLE providers (
    provider_id          TEXT PRIMARY KEY,
    provider_name        TEXT NOT NULL,
    provider_type        TEXT NOT NULL,
    facility_id          TEXT NOT NULL REFERENCES facilities (facility_id),
    service_category_id  TEXT NOT NULL REFERENCES service_categories (service_category_id)
);

CREATE TABLE patients (
    patient_id      TEXT PRIMARY KEY,
    age_group       TEXT NOT NULL
        CHECK (age_group IN ('0-17', '18-34', '35-49', '50-64', '65-74', '75+')),
    gender          TEXT NOT NULL
        CHECK (gender IN ('Female', 'Male', 'Unknown')),
    insurance_type  TEXT NOT NULL
        CHECK (insurance_type IN ('Commercial', 'Medicaid', 'Medicare', 'Self-Pay')),
    home_region     TEXT NOT NULL
        CHECK (home_region IN ('North', 'South', 'East', 'West', 'Central'))
);

-- ---------------------------------------------------------------------------
-- Referrals: one row per unique referral_id after deduplication
-- ---------------------------------------------------------------------------
CREATE TABLE referrals (
    referral_id              TEXT PRIMARY KEY,
    referral_record_id       TEXT NOT NULL UNIQUE,  -- raw row kept by deduplication
    patient_id               TEXT NOT NULL REFERENCES patients (patient_id),
    service_category_id      TEXT NOT NULL REFERENCES service_categories (service_category_id),
    receiving_facility_id    TEXT REFERENCES facilities (facility_id),
    receiving_provider_id    TEXT NOT NULL REFERENCES providers (provider_id),
    referral_source          TEXT NOT NULL
        CHECK (referral_source IN ('Primary Care', 'Specialist', 'Emergency Department',
                                   'Hospital Discharge', 'Urgent Care', 'Patient Portal',
                                   'Unknown')),
    urgency                  TEXT NOT NULL
        CHECK (urgency IN ('Routine', 'Urgent', 'Stat')),
    referral_date            TEXT NOT NULL
        CHECK (referral_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    first_contact_date       TEXT
        CHECK (first_contact_date IS NULL OR first_contact_date >= referral_date),
    referral_status          TEXT NOT NULL
        CHECK (referral_status IN ('Completed', 'Scheduled', 'Pending', 'Declined',
                                   'Cancelled', 'Expired', 'Sent External')),
    closure_reason           TEXT
        CHECK (closure_reason IS NULL OR closure_reason IN (
            'Appointment Completed', 'Patient Declined', 'Chose Other Provider',
            'Appointment Cancelled - Not Rebooked', 'No-Show - Not Rebooked',
            'Referral Expired', 'External Visit Confirmed')),
    closed_date              TEXT
        CHECK (closed_date IS NULL OR closed_date >= referral_date),
    duplicate_record_count   INTEGER NOT NULL DEFAULT 0
        CHECK (duplicate_record_count >= 0),
    data_quality_issue_count INTEGER NOT NULL DEFAULT 0
        CHECK (data_quality_issue_count >= 0),
    has_data_quality_issue   INTEGER NOT NULL DEFAULT 0
        CHECK (has_data_quality_issue IN (0, 1)),
    -- After cleaning, open referrals never carry a closed date.
    CHECK (referral_status NOT IN ('Pending', 'Scheduled') OR closed_date IS NULL),
    CHECK (has_data_quality_issue = (data_quality_issue_count > 0))
);

-- ---------------------------------------------------------------------------
-- Appointments: zero or more per referral
-- ---------------------------------------------------------------------------
CREATE TABLE appointments (
    appointment_id        TEXT    PRIMARY KEY,
    referral_id           TEXT    NOT NULL REFERENCES referrals (referral_id),
    appointment_sequence  INTEGER NOT NULL CHECK (appointment_sequence >= 1),
    facility_id           TEXT    NOT NULL REFERENCES facilities (facility_id),
    provider_id           TEXT    NOT NULL REFERENCES providers (provider_id),
    booked_date           TEXT    NOT NULL,
    appointment_datetime  TEXT    NOT NULL,
    appointment_date      TEXT    NOT NULL
        CHECK (appointment_date = substr(appointment_datetime, 1, 10)),
    appointment_status    TEXT    NOT NULL
        CHECK (appointment_status IN ('Completed', 'Cancelled', 'No-Show',
                                      'Rescheduled', 'Scheduled')),
    status_reason         TEXT,
    UNIQUE (referral_id, appointment_sequence),
    CHECK (booked_date <= appointment_date)
);

-- ---------------------------------------------------------------------------
-- Data-quality exceptions: one row per detected issue
-- ---------------------------------------------------------------------------
CREATE TABLE data_quality_exceptions (
    exception_id       TEXT PRIMARY KEY,
    entity_type        TEXT NOT NULL
        CHECK (entity_type IN ('service_category', 'facility', 'provider', 'patient',
                               'referral', 'appointment')),
    record_id          TEXT NOT NULL,
    referral_id        TEXT REFERENCES referrals (referral_id),
    issue_type         TEXT NOT NULL,
    field_name         TEXT NOT NULL,
    original_value     TEXT,
    cleaned_value      TEXT,
    action_taken       TEXT NOT NULL,
    resolution_status  TEXT NOT NULL
        CHECK (resolution_status IN ('Resolved', 'Unresolved')),
    UNIQUE (entity_type, record_id, issue_type, field_name)
);

-- ---------------------------------------------------------------------------
-- Indexes for later analysis
-- ---------------------------------------------------------------------------
CREATE INDEX idx_providers_facility           ON providers (facility_id);
CREATE INDEX idx_providers_service_category   ON providers (service_category_id);

CREATE INDEX idx_referrals_referral_date      ON referrals (referral_date);
CREATE INDEX idx_referrals_status             ON referrals (referral_status);
CREATE INDEX idx_referrals_service_category   ON referrals (service_category_id);
CREATE INDEX idx_referrals_facility           ON referrals (receiving_facility_id);
CREATE INDEX idx_referrals_provider           ON referrals (receiving_provider_id);
CREATE INDEX idx_referrals_patient            ON referrals (patient_id);
CREATE INDEX idx_referrals_source             ON referrals (referral_source);
CREATE INDEX idx_referrals_urgency            ON referrals (urgency);

CREATE INDEX idx_appointments_referral        ON appointments (referral_id);
CREATE INDEX idx_appointments_status          ON appointments (appointment_status);
CREATE INDEX idx_appointments_date            ON appointments (appointment_date);
CREATE INDEX idx_appointments_facility        ON appointments (facility_id);
CREATE INDEX idx_appointments_provider        ON appointments (provider_id);

CREATE INDEX idx_exceptions_referral          ON data_quality_exceptions (referral_id);
CREATE INDEX idx_exceptions_issue_type        ON data_quality_exceptions (issue_type);
