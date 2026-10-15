-- Healthcare Referral Leakage Analytics - Phase 3 analytical views
--
-- Drops and recreates ONLY the Phase 3 views; Phase 2 tables are never touched.
-- Every definition is documented in sql/KPI_DEFINITIONS.md.
-- All data is fully synthetic and for portfolio and educational use only,
-- not for clinical decision-making.
--
-- Conventions
--   *_flag   0/1 integer
--   *_rate   share between 0 and 1; NULL when the denominator is zero
--   days_*   whole days between two ISO dates; NULL when a date is missing
--   Referral-level measures count referrals; appointment-level measures
--   count appointment rows and always contain "appointment" in their name.

-- Drop in reverse dependency order.
DROP VIEW IF EXISTS vw_data_quality_metrics;
DROP VIEW IF EXISTS vw_turnaround_metrics;
DROP VIEW IF EXISTS vw_leakage_reason_metrics;
DROP VIEW IF EXISTS vw_insurance_metrics;
DROP VIEW IF EXISTS vw_urgency_metrics;
DROP VIEW IF EXISTS vw_referral_source_metrics;
DROP VIEW IF EXISTS vw_facility_metrics;
DROP VIEW IF EXISTS vw_service_category_metrics;
DROP VIEW IF EXISTS vw_monthly_metrics;
DROP VIEW IF EXISTS vw_referral_funnel;
DROP VIEW IF EXISTS vw_overall_kpis;
DROP VIEW IF EXISTS vw_dimension_metrics;
DROP VIEW IF EXISTS vw_dimension_turnaround;
DROP VIEW IF EXISTS vw_journey_by_dimension;
DROP VIEW IF EXISTS vw_analysis_dimensions;
DROP VIEW IF EXISTS vw_referral_journey;
DROP VIEW IF EXISTS vw_appointment_summary;
DROP VIEW IF EXISTS vw_leakage_reasons;
DROP VIEW IF EXISTS vw_analysis_parameters;

-- ---------------------------------------------------------------------------
-- Parameters (must match config.py; analyze_data.py checks this)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_analysis_parameters AS
SELECT
    '2025-01-01' AS reporting_start_date,
    '2025-12-31' AS reporting_end_date,
    '2026-01-31' AS extract_date,
    30           AS follow_up_window_days,           -- time allowed before an open item counts as leaked
    30           AS scheduling_delay_threshold_days;  -- booking later than this is "delayed scheduling"

-- Leakage reasons in priority order (1 = checked first).
CREATE VIEW vw_leakage_reasons AS
WITH reasons (priority, leakage_reason, rule_summary) AS (
    VALUES
    (1, 'External Outcome Missing',
        'Sent External, no confirmed external outcome, follow-up window has passed'),
    (2, 'Expired Before Completion',
        'Referral status Expired without a completed appointment or confirmed external outcome'),
    (3, 'Cancelled Without Successful Rebooking',
        'Last appointment was Cancelled and no later appointment exists'),
    (4, 'No-Show Without Successful Follow-Up',
        'Last appointment was a No-Show and no later appointment exists'),
    (5, 'Declined Before Scheduling',
        'Referral status Declined without a completed appointment or confirmed external outcome'),
    (6, 'Not Scheduled Within 30 Days',
        'No appointment and at least 30 days since the referral date')
)
SELECT priority, leakage_reason, rule_summary FROM reasons;

-- ---------------------------------------------------------------------------
-- Appointments aggregated to one row per referral (prevents double counting)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_appointment_summary AS
WITH ordered AS (
    SELECT a.*,
           ROW_NUMBER() OVER (PARTITION BY a.referral_id
                              ORDER BY a.appointment_sequence DESC) AS reverse_sequence
    FROM appointments a
)
SELECT
    o.referral_id,
    COUNT(*)                                                         AS appointment_count,
    MIN(o.booked_date)                                               AS first_booking_date,
    MIN(o.appointment_date)                                          AS first_appointment_date,
    MAX(CASE WHEN o.reverse_sequence = 1 THEN o.appointment_date END)   AS last_appointment_date,
    MAX(CASE WHEN o.reverse_sequence = 1 THEN o.appointment_status END) AS last_appointment_status,
    SUM(o.appointment_status = 'Completed')                          AS completed_appointment_count,
    SUM(o.appointment_status = 'Cancelled')                          AS cancelled_appointment_count,
    SUM(o.appointment_status = 'No-Show')                            AS no_show_appointment_count,
    SUM(o.appointment_status = 'Rescheduled')                        AS rescheduled_appointment_count,
    SUM(o.appointment_status = 'Scheduled' AND o.appointment_date > p.extract_date)
                                                                     AS future_scheduled_appointment_count,
    MIN(CASE WHEN o.appointment_status = 'Completed' THEN o.appointment_date END)
                                                                     AS first_completed_appointment_date
FROM ordered o
CROSS JOIN vw_analysis_parameters p
GROUP BY o.referral_id;

-- ---------------------------------------------------------------------------
-- Central view: exactly one row per processed referral
-- ---------------------------------------------------------------------------
CREATE VIEW vw_referral_journey AS
WITH base AS (
    SELECT
        r.referral_id,
        r.referral_record_id,
        r.referral_date,
        substr(r.referral_date, 1, 7)                       AS referral_month,
        r.patient_id,
        COALESCE(pt.age_group, 'Unknown')                   AS age_group,
        COALESCE(pt.gender, 'Unknown')                      AS gender,
        COALESCE(pt.insurance_type, 'Unknown')              AS insurance_type,
        COALESCE(pt.home_region, 'Unknown')                 AS home_region,
        COALESCE(r.urgency, 'Unknown')                      AS urgency,
        COALESCE(r.referral_source, 'Unknown')              AS referral_source,
        r.service_category_id,
        COALESCE(sc.service_category_name, 'Unknown')       AS service_category_name,
        COALESCE(sc.service_line, 'Unknown')                AS service_line,
        sc.target_days_to_appointment,
        r.receiving_provider_id,
        r.receiving_facility_id,
        COALESCE(f.facility_name, 'Unknown')                AS receiving_facility_name,
        COALESCE(f.network_status, 'Unknown')               AS receiving_network_status,
        r.referral_status,
        r.closure_reason,
        r.first_contact_date,
        r.closed_date,
        COALESCE(s.appointment_count, 0)                    AS appointment_count,
        s.first_booking_date,
        s.first_appointment_date,
        s.last_appointment_date,
        s.last_appointment_status,
        COALESCE(s.completed_appointment_count, 0)          AS completed_appointment_count,
        COALESCE(s.cancelled_appointment_count, 0)          AS cancelled_appointment_count,
        COALESCE(s.no_show_appointment_count, 0)            AS no_show_appointment_count,
        COALESCE(s.rescheduled_appointment_count, 0)        AS rescheduled_appointment_count,
        COALESCE(s.future_scheduled_appointment_count, 0)   AS future_scheduled_appointment_count,
        s.first_completed_appointment_date,
        r.duplicate_record_count,
        r.data_quality_issue_count,
        r.has_data_quality_issue,
        p.follow_up_window_days,
        p.scheduling_delay_threshold_days,
        CAST(julianday(p.extract_date) - julianday(r.referral_date) AS INTEGER)          AS days_since_referral,
        CAST(julianday(p.extract_date) - julianday(s.last_appointment_date) AS INTEGER)  AS days_since_last_appointment,
        CAST(julianday(r.first_contact_date) - julianday(r.referral_date) AS INTEGER)    AS raw_days_to_first_contact,
        CAST(julianday(s.first_booking_date) - julianday(r.referral_date) AS INTEGER)    AS raw_days_to_schedule,
        CAST(julianday(s.first_appointment_date) - julianday(r.referral_date) AS INTEGER) AS raw_days_to_first_appointment
    FROM referrals r
    CROSS JOIN vw_analysis_parameters p
    LEFT JOIN vw_appointment_summary s ON s.referral_id = r.referral_id
    LEFT JOIN patients pt              ON pt.patient_id = r.patient_id
    LEFT JOIN service_categories sc    ON sc.service_category_id = r.service_category_id
    LEFT JOIN facilities f             ON f.facility_id = r.receiving_facility_id
),
flags AS (
    SELECT
        b.*,
        -- Negative durations are impossible after Phase 2 validation; they become NULL as a safeguard.
        CASE WHEN raw_days_to_first_contact >= 0 THEN raw_days_to_first_contact END         AS days_to_first_contact,
        CASE WHEN raw_days_to_schedule >= 0 THEN raw_days_to_schedule END                   AS days_to_schedule,
        CASE WHEN raw_days_to_first_appointment >= 0 THEN raw_days_to_first_appointment END AS days_to_first_appointment,
        CASE WHEN raw_days_to_first_contact < 0 OR raw_days_to_schedule < 0
                  OR raw_days_to_first_appointment < 0 THEN 1 ELSE 0 END                   AS invalid_duration_flag,
        CASE WHEN referral_status = 'Sent External' THEN 1 ELSE 0 END                       AS external_referral_flag,
        CASE WHEN referral_status = 'Sent External'
                  AND closure_reason = 'External Visit Confirmed' THEN 1 ELSE 0 END         AS confirmed_external_outcome_flag,
        CASE WHEN first_contact_date IS NOT NULL OR appointment_count > 0
                  OR referral_status = 'Declined' THEN 1 ELSE 0 END                         AS contacted_flag,
        CASE WHEN appointment_count > 0 THEN 1 ELSE 0 END                                   AS scheduled_flag,
        CASE WHEN completed_appointment_count > 0 THEN 1 ELSE 0 END                         AS completed_flag,
        CASE WHEN cancelled_appointment_count > 0 THEN 1 ELSE 0 END                         AS had_cancellation_flag,
        CASE WHEN no_show_appointment_count > 0 THEN 1 ELSE 0 END                           AS had_no_show_flag,
        CASE WHEN rescheduled_appointment_count > 0 THEN 1 ELSE 0 END                       AS had_reschedule_flag
    FROM base b
),
outcomes AS (
    SELECT
        f.*,
        CASE WHEN completed_flag = 1 OR confirmed_external_outcome_flag = 1 THEN 1 ELSE 0 END AS converted_flag,
        CASE WHEN days_to_schedule > scheduling_delay_threshold_days THEN 1 ELSE 0 END        AS delayed_schedule_flag,
        CASE WHEN days_to_first_appointment > target_days_to_appointment THEN 1 ELSE 0 END    AS delayed_appointment_flag
    FROM flags f
),
active AS (
    SELECT
        o.*,
        CASE
            WHEN converted_flag = 1 THEN 0
            -- A future appointment is booked.
            WHEN future_scheduled_appointment_count > 0 THEN 1
            -- Open and not yet booked, still inside the follow-up window.
            WHEN referral_status = 'Pending' AND appointment_count = 0
                 AND days_since_referral < follow_up_window_days THEN 1
            -- Open and awaiting rebooking after a recent cancellation or no-show.
            WHEN referral_status = 'Pending' AND last_appointment_status IN ('Cancelled', 'No-Show')
                 AND days_since_last_appointment < follow_up_window_days THEN 1
            -- Sent externally recently; an outcome may still arrive.
            WHEN referral_status = 'Sent External' AND confirmed_external_outcome_flag = 0
                 AND days_since_referral < follow_up_window_days THEN 1
            ELSE 0
        END AS active_in_progress_flag
    FROM outcomes o
),
classified AS (
    SELECT
        a.*,
        CASE
            WHEN converted_flag = 1 OR active_in_progress_flag = 1 THEN NULL
            WHEN referral_status = 'Sent External' AND confirmed_external_outcome_flag = 0
                THEN 'External Outcome Missing'
            WHEN referral_status = 'Expired'                THEN 'Expired Before Completion'
            WHEN last_appointment_status = 'Cancelled'      THEN 'Cancelled Without Successful Rebooking'
            WHEN last_appointment_status = 'No-Show'        THEN 'No-Show Without Successful Follow-Up'
            WHEN referral_status = 'Declined'               THEN 'Declined Before Scheduling'
            WHEN appointment_count = 0 AND days_since_referral >= follow_up_window_days
                THEN 'Not Scheduled Within 30 Days'
        END AS primary_leakage_reason
    FROM active a
)
SELECT
    referral_id, referral_record_id, referral_date, referral_month,
    patient_id, age_group, gender, insurance_type, home_region,
    urgency, referral_source,
    service_category_id, service_category_name, service_line, target_days_to_appointment,
    receiving_provider_id, receiving_facility_id, receiving_facility_name, receiving_network_status,
    referral_status, closure_reason, first_contact_date, closed_date,
    external_referral_flag, confirmed_external_outcome_flag,
    CASE WHEN confirmed_external_outcome_flag = 1 THEN closed_date END AS external_outcome_date,
    appointment_count, first_booking_date, first_appointment_date, last_appointment_date,
    last_appointment_status, completed_appointment_count, cancelled_appointment_count,
    no_show_appointment_count, rescheduled_appointment_count, future_scheduled_appointment_count,
    first_completed_appointment_date,
    days_since_referral, days_to_first_contact, days_to_schedule, days_to_first_appointment,
    invalid_duration_flag,
    contacted_flag, scheduled_flag, completed_flag, converted_flag, active_in_progress_flag,
    CASE WHEN primary_leakage_reason IS NULL THEN 0 ELSE 1 END AS leakage_flag,
    primary_leakage_reason,
    CASE
        WHEN converted_flag = 1          THEN 'Converted'
        WHEN active_in_progress_flag = 1 THEN 'Active'
        WHEN primary_leakage_reason IS NOT NULL THEN 'Leaked'
        ELSE 'Unclassified'
    END AS outcome_category,
    had_cancellation_flag, had_no_show_flag, had_reschedule_flag,
    delayed_schedule_flag, delayed_appointment_flag,
    duplicate_record_count, data_quality_issue_count, has_data_quality_issue
FROM classified;

-- ---------------------------------------------------------------------------
-- Grouping helpers: every grouped view uses the same calculations
-- ---------------------------------------------------------------------------
CREATE VIEW vw_analysis_dimensions AS
WITH dimensions (dimension_order, dimension) AS (
    VALUES (0, 'Overall'), (1, 'Referral Month'), (2, 'Service Category'),
           (3, 'Receiving Facility'), (4, 'Referral Source'), (5, 'Urgency'),
           (6, 'Insurance Type')
)
SELECT dimension_order, dimension FROM dimensions;

-- Each referral appears once per dimension (so each dimension still sums to the
-- total). Only the columns needed for grouped metrics are carried.
CREATE VIEW vw_journey_by_dimension AS
SELECT
    d.dimension_order,
    d.dimension,
    CASE d.dimension
        WHEN 'Overall'            THEN 'ALL'
        WHEN 'Referral Month'     THEN COALESCE(j.referral_month, 'Unknown')
        WHEN 'Service Category'   THEN COALESCE(j.service_category_id, 'Unknown')
        WHEN 'Receiving Facility' THEN COALESCE(j.receiving_facility_id, 'Unknown')
        WHEN 'Referral Source'    THEN j.referral_source
        WHEN 'Urgency'            THEN j.urgency
        WHEN 'Insurance Type'     THEN j.insurance_type
    END AS dimension_key,
    CASE d.dimension
        WHEN 'Overall'            THEN 'All Referrals'
        WHEN 'Referral Month'     THEN COALESCE(j.referral_month, 'Unknown')
        WHEN 'Service Category'   THEN j.service_category_name
        WHEN 'Receiving Facility' THEN j.receiving_facility_name
        WHEN 'Referral Source'    THEN j.referral_source
        WHEN 'Urgency'            THEN j.urgency
        WHEN 'Insurance Type'     THEN j.insurance_type
    END AS dimension_label,
    j.contacted_flag, j.scheduled_flag, j.completed_flag, j.confirmed_external_outcome_flag,
    j.converted_flag, j.active_in_progress_flag, j.leakage_flag, j.external_referral_flag,
    j.had_cancellation_flag, j.had_no_show_flag, j.had_reschedule_flag,
    j.delayed_schedule_flag, j.delayed_appointment_flag,
    j.duplicate_record_count, j.has_data_quality_issue,
    j.days_to_first_contact, j.days_to_schedule, j.days_to_first_appointment
FROM vw_referral_journey j
CROSS JOIN vw_analysis_dimensions d;

-- Every grouped metric for every dimension, computed in one pass.
-- The per-dimension rows are materialized once and reused for counts and
-- turnaround. Averages and medians use only nonmissing durations.
-- Durations are whole days, so the median is read from the frequency
-- distribution: count referrals per day value, keep a running total (window
-- SUM) and take the value at the middle position. For an even count it is the
-- mean of the two middle values: positions (n + 1) / 2 and (n + 2) / 2 with
-- integer division.
CREATE VIEW vw_dimension_metrics AS
WITH rows_by_dimension AS MATERIALIZED (
    SELECT * FROM vw_journey_by_dimension
),
counts AS (
    SELECT
        dimension_order, dimension, dimension_key,
        MIN(dimension_label)                    AS dimension_label,
        COUNT(*)                                AS total_referrals,
        SUM(contacted_flag)                     AS contacted_referrals,
        SUM(scheduled_flag)                     AS scheduled_referrals,
        SUM(completed_flag)                     AS completed_referrals,
        SUM(confirmed_external_outcome_flag)    AS confirmed_external_outcomes,
        SUM(converted_flag)                     AS converted_referrals,
        SUM(active_in_progress_flag)            AS active_referrals,
        SUM(leakage_flag)                       AS leaked_referrals,
        SUM(external_referral_flag)             AS external_referrals,
        SUM(had_cancellation_flag)              AS cancelled_referrals,
        SUM(had_no_show_flag)                   AS no_show_referrals,
        SUM(had_reschedule_flag)                AS rescheduled_referrals,
        SUM(delayed_schedule_flag)              AS delayed_scheduling_referrals,
        SUM(delayed_appointment_flag)           AS delayed_appointment_referrals,
        SUM(duplicate_record_count > 0)         AS referrals_with_duplicates,
        SUM(has_data_quality_issue)             AS referrals_with_data_quality_issues
    FROM rows_by_dimension
    GROUP BY dimension_order, dimension, dimension_key
),
frequencies AS (
    SELECT dimension, dimension_key, 'days_to_first_contact' AS measure,
           days_to_first_contact AS days, COUNT(*) AS referrals
    FROM rows_by_dimension WHERE days_to_first_contact IS NOT NULL
    GROUP BY dimension, dimension_key, days_to_first_contact
    UNION ALL
    SELECT dimension, dimension_key, 'days_to_schedule', days_to_schedule, COUNT(*)
    FROM rows_by_dimension WHERE days_to_schedule IS NOT NULL
    GROUP BY dimension, dimension_key, days_to_schedule
    UNION ALL
    SELECT dimension, dimension_key, 'days_to_first_appointment', days_to_first_appointment, COUNT(*)
    FROM rows_by_dimension WHERE days_to_first_appointment IS NOT NULL
    GROUP BY dimension, dimension_key, days_to_first_appointment
),
cumulative AS (
    SELECT frequencies.*,
           SUM(referrals) OVER (PARTITION BY dimension, dimension_key, measure) AS eligible,
           SUM(referrals) OVER (PARTITION BY dimension, dimension_key, measure ORDER BY days
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total
    FROM frequencies
),
turnaround_long AS (
    SELECT dimension, dimension_key, measure,
           1.0 * SUM(days * referrals) / SUM(referrals) AS average_days,
           (MIN(CASE WHEN running_total >= (eligible + 1) / 2 THEN days END)
            + MIN(CASE WHEN running_total >= (eligible + 2) / 2 THEN days END)) / 2.0 AS median_days
    FROM cumulative
    GROUP BY dimension, dimension_key, measure
),
turnaround AS (
    SELECT
        dimension, dimension_key,
        MAX(CASE WHEN measure = 'days_to_first_contact' THEN average_days END)     AS average_days_to_first_contact,
        MAX(CASE WHEN measure = 'days_to_first_contact' THEN median_days END)      AS median_days_to_first_contact,
        MAX(CASE WHEN measure = 'days_to_schedule' THEN average_days END)          AS average_days_to_schedule,
        MAX(CASE WHEN measure = 'days_to_schedule' THEN median_days END)           AS median_days_to_schedule,
        MAX(CASE WHEN measure = 'days_to_first_appointment' THEN average_days END) AS average_days_to_first_appointment,
        MAX(CASE WHEN measure = 'days_to_first_appointment' THEN median_days END)  AS median_days_to_first_appointment
    FROM turnaround_long
    GROUP BY dimension, dimension_key
)
SELECT
    c.dimension_order, c.dimension, c.dimension_key, c.dimension_label,
    c.total_referrals, c.contacted_referrals, c.scheduled_referrals, c.completed_referrals,
    c.confirmed_external_outcomes, c.converted_referrals, c.active_referrals, c.leaked_referrals,
    CASE WHEN c.total_referrals > 0 THEN 1.0 * c.scheduled_referrals / c.total_referrals END AS scheduling_rate,
    CASE WHEN c.total_referrals > 0 THEN 1.0 * c.completed_referrals / c.total_referrals END AS completion_rate,
    CASE WHEN c.total_referrals > 0 THEN 1.0 * c.converted_referrals / c.total_referrals END AS conversion_rate,
    CASE WHEN c.total_referrals > 0 THEN 1.0 * c.leaked_referrals / c.total_referrals END    AS leakage_rate,
    c.external_referrals, c.cancelled_referrals, c.no_show_referrals, c.rescheduled_referrals,
    c.delayed_scheduling_referrals, c.delayed_appointment_referrals,
    c.referrals_with_duplicates, c.referrals_with_data_quality_issues,
    t.average_days_to_first_contact, t.median_days_to_first_contact,
    t.average_days_to_schedule, t.median_days_to_schedule,
    t.average_days_to_first_appointment, t.median_days_to_first_appointment
FROM counts c
LEFT JOIN turnaround t ON t.dimension = c.dimension AND t.dimension_key = c.dimension_key;

-- ---------------------------------------------------------------------------
-- Overall KPIs: always one row, even for an empty database
-- ---------------------------------------------------------------------------
CREATE VIEW vw_overall_kpis AS
WITH appointment_level AS (
    SELECT
        COUNT(*)                                      AS total_appointments,
        COALESCE(SUM(appointment_status = 'Completed'), 0)   AS completed_appointments,
        COALESCE(SUM(appointment_status = 'Cancelled'), 0)   AS cancelled_appointments,
        COALESCE(SUM(appointment_status = 'No-Show'), 0)     AS no_show_appointments,
        COALESCE(SUM(appointment_status = 'Rescheduled'), 0) AS rescheduled_appointments,
        COALESCE(SUM(appointment_status = 'Scheduled'), 0)   AS scheduled_future_appointments
    FROM appointments
),
quality AS (
    SELECT
        (SELECT COUNT(*) FROM data_quality_exceptions)                     AS data_quality_exceptions,
        (SELECT COALESCE(SUM(duplicate_record_count), 0) FROM referrals)   AS duplicate_records_removed
)
SELECT
    p.extract_date,
    COALESCE(m.total_referrals, 0)                    AS total_referrals,
    COALESCE(m.contacted_referrals, 0)                AS contacted_referrals,
    COALESCE(m.scheduled_referrals, 0)                AS scheduled_referrals,
    COALESCE(m.completed_referrals, 0)                AS completed_referrals,
    COALESCE(m.confirmed_external_outcomes, 0)        AS confirmed_external_outcomes,
    COALESCE(m.converted_referrals, 0)                AS converted_referrals,
    COALESCE(m.active_referrals, 0)                   AS active_referrals,
    COALESCE(m.leaked_referrals, 0)                   AS leaked_referrals,
    COALESCE(m.total_referrals, 0) - COALESCE(m.converted_referrals, 0)
        - COALESCE(m.active_referrals, 0) - COALESCE(m.leaked_referrals, 0) AS unclassified_referrals,
    m.scheduling_rate, m.completion_rate, m.conversion_rate, m.leakage_rate,
    COALESCE(m.external_referrals, 0)                 AS external_referrals,
    COALESCE(m.cancelled_referrals, 0)                AS cancelled_referrals,
    COALESCE(m.no_show_referrals, 0)                  AS no_show_referrals,
    COALESCE(m.rescheduled_referrals, 0)              AS rescheduled_referrals,
    CASE WHEN m.total_referrals > 0 THEN 1.0 * m.cancelled_referrals / m.total_referrals END AS cancelled_referral_rate,
    CASE WHEN m.total_referrals > 0 THEN 1.0 * m.no_show_referrals / m.total_referrals END   AS no_show_referral_rate,
    COALESCE(m.delayed_scheduling_referrals, 0)       AS delayed_scheduling_referrals,
    COALESCE(m.delayed_appointment_referrals, 0)      AS delayed_appointment_referrals,
    a.total_appointments, a.completed_appointments, a.cancelled_appointments,
    a.no_show_appointments, a.rescheduled_appointments, a.scheduled_future_appointments,
    CASE WHEN a.total_appointments > 0 THEN 1.0 * a.cancelled_appointments / a.total_appointments END
        AS appointment_cancellation_rate,
    CASE WHEN a.total_appointments > 0 THEN 1.0 * a.no_show_appointments / a.total_appointments END
        AS appointment_no_show_rate,
    COALESCE(m.referrals_with_duplicates, 0)          AS referrals_with_duplicates,
    q.duplicate_records_removed,
    COALESCE(m.referrals_with_data_quality_issues, 0) AS referrals_with_data_quality_issues,
    q.data_quality_exceptions,
    m.average_days_to_first_contact, m.median_days_to_first_contact,
    m.average_days_to_schedule, m.median_days_to_schedule,
    m.average_days_to_first_appointment, m.median_days_to_first_appointment
FROM vw_analysis_parameters p
CROSS JOIN appointment_level a
CROSS JOIN quality q
LEFT JOIN vw_dimension_metrics m ON m.dimension = 'Overall';

-- ---------------------------------------------------------------------------
-- Referral funnel (progressive stages, not mutually exclusive)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_referral_funnel AS
WITH totals AS (
    SELECT
        COUNT(*)                                                         AS total_all,
        COALESCE(SUM(external_referral_flag = 0), 0)                     AS total_internal,
        COALESCE(SUM(external_referral_flag), 0)                         AS total_external,
        COALESCE(SUM(contacted_flag), 0)                                 AS contacted_all,
        COALESCE(SUM(contacted_flag * (external_referral_flag = 0)), 0)  AS contacted_internal,
        COALESCE(SUM(contacted_flag * external_referral_flag), 0)        AS contacted_external,
        COALESCE(SUM(scheduled_flag), 0)                                 AS scheduled_all,
        COALESCE(SUM(scheduled_flag * (external_referral_flag = 0)), 0)  AS scheduled_internal,
        COALESCE(SUM(scheduled_flag * external_referral_flag), 0)        AS scheduled_external,
        COALESCE(SUM(converted_flag), 0)                                 AS converted_all,
        COALESCE(SUM(converted_flag * (external_referral_flag = 0)), 0)  AS converted_internal,
        COALESCE(SUM(converted_flag * external_referral_flag), 0)        AS converted_external
    FROM vw_referral_journey
),
stages (stage_order, stage, stage_definition) AS (
    VALUES
    (1, 'Total Referrals', 'Every processed referral'),
    (2, 'Contacted', 'First-contact date recorded, or contact evidenced by an appointment or a decline'),
    (3, 'Scheduled', 'At least one appointment record (internal referrals only)'),
    (4, 'Completed or Confirmed External Outcome',
        'Converted: a completed appointment, or a Sent External referral with a confirmed external visit')
)
SELECT
    s.stage_order,
    s.stage,
    CASE s.stage_order WHEN 1 THEN t.total_all WHEN 2 THEN t.contacted_all
                       WHEN 3 THEN t.scheduled_all ELSE t.converted_all END AS referrals,
    CASE s.stage_order WHEN 1 THEN t.total_internal WHEN 2 THEN t.contacted_internal
                       WHEN 3 THEN t.scheduled_internal ELSE t.converted_internal END AS internal_referrals,
    CASE s.stage_order WHEN 1 THEN t.total_external WHEN 2 THEN t.contacted_external
                       WHEN 3 THEN t.scheduled_external ELSE t.converted_external END AS external_referrals,
    CASE WHEN t.total_all > 0 THEN 1.0 * (CASE s.stage_order WHEN 1 THEN t.total_all WHEN 2 THEN t.contacted_all
                       WHEN 3 THEN t.scheduled_all ELSE t.converted_all END) / t.total_all END AS share_of_total_referrals,
    s.stage_definition
FROM stages s
CROSS JOIN totals t;

-- ---------------------------------------------------------------------------
-- Grouped views (same columns; one row per group, Unknown when missing)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_monthly_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Referral Month';

CREATE VIEW vw_service_category_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Service Category';

CREATE VIEW vw_facility_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Receiving Facility';

CREATE VIEW vw_referral_source_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Referral Source';

CREATE VIEW vw_urgency_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Urgency';

CREATE VIEW vw_insurance_metrics AS
SELECT * FROM vw_dimension_metrics WHERE dimension = 'Insurance Type';

-- ---------------------------------------------------------------------------
-- Leakage reasons: one row per reason in priority order (zeros included)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_leakage_reason_metrics AS
WITH totals AS (
    SELECT COUNT(*) AS total_referrals, COALESCE(SUM(leakage_flag), 0) AS leaked_referrals
    FROM vw_referral_journey
),
reason_counts AS (
    SELECT primary_leakage_reason, COUNT(*) AS leaked_referrals
    FROM vw_referral_journey
    WHERE leakage_flag = 1
    GROUP BY primary_leakage_reason
)
SELECT
    r.priority,
    r.leakage_reason,
    COALESCE(c.leaked_referrals, 0) AS leaked_referrals,
    CASE WHEN t.leaked_referrals > 0
         THEN 1.0 * COALESCE(c.leaked_referrals, 0) / t.leaked_referrals END AS share_of_leaked_referrals,
    CASE WHEN t.total_referrals > 0
         THEN 1.0 * COALESCE(c.leaked_referrals, 0) / t.total_referrals END  AS rate_of_total_referrals,
    r.rule_summary
FROM vw_leakage_reasons r
CROSS JOIN totals t
LEFT JOIN reason_counts c ON c.primary_leakage_reason = r.leakage_reason;

-- ---------------------------------------------------------------------------
-- Turnaround: one row per measure; only nonmissing durations are used
-- ---------------------------------------------------------------------------
CREATE VIEW vw_turnaround_metrics AS
WITH measures (measure_order, measure, start_event, end_event) AS (
    VALUES
    (1, 'days_to_first_contact', 'referral_date', 'first_contact_date'),
    (2, 'days_to_schedule', 'referral_date', 'first booked_date'),
    (3, 'days_to_first_appointment', 'referral_date', 'first appointment_date')
),
totals AS (
    SELECT COUNT(*) AS total_referrals, COALESCE(SUM(invalid_duration_flag), 0) AS invalid_duration_referrals
    FROM vw_referral_journey
),
frequencies AS (
    SELECT m.measure,
           CASE m.measure
               WHEN 'days_to_first_contact'     THEN j.days_to_first_contact
               WHEN 'days_to_schedule'          THEN j.days_to_schedule
               WHEN 'days_to_first_appointment' THEN j.days_to_first_appointment
           END AS days,
           COUNT(*) AS referrals
    FROM vw_referral_journey j
    CROSS JOIN measures m
    GROUP BY m.measure, days
    HAVING days IS NOT NULL
),
cumulative AS (
    SELECT frequencies.*,
           SUM(referrals) OVER (PARTITION BY measure) AS eligible,
           SUM(referrals) OVER (PARTITION BY measure ORDER BY days
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total
    FROM frequencies
),
stats AS (
    -- Same median method as vw_dimension_turnaround.
    SELECT measure,
           MAX(eligible)                                AS eligible_referrals,
           1.0 * SUM(days * referrals) / SUM(referrals) AS average_days,
           (MIN(CASE WHEN running_total >= (eligible + 1) / 2 THEN days END)
            + MIN(CASE WHEN running_total >= (eligible + 2) / 2 THEN days END)) / 2.0 AS median_days,
           MIN(days) AS min_days, MAX(days) AS max_days
    FROM cumulative
    GROUP BY measure
)
SELECT
    m.measure_order, m.measure, m.start_event, m.end_event,
    t.total_referrals,
    COALESCE(s.eligible_referrals, 0)                     AS eligible_referrals,
    t.total_referrals - COALESCE(s.eligible_referrals, 0) AS missing_or_not_applicable,
    s.average_days, s.median_days, s.min_days, s.max_days,
    t.invalid_duration_referrals
FROM measures m
CROSS JOIN totals t
LEFT JOIN stats s ON s.measure = m.measure;

-- ---------------------------------------------------------------------------
-- Data quality: Phase 2 exceptions by issue type (in rule order)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_data_quality_metrics AS
WITH totals AS (SELECT COUNT(*) AS total_referrals FROM referrals)
SELECT
    MIN(e.exception_id)                                   AS first_exception_id,
    e.issue_type,
    COUNT(*)                                              AS exception_count,
    SUM(e.resolution_status = 'Resolved')                 AS resolved_exceptions,
    SUM(e.resolution_status = 'Unresolved')               AS unresolved_exceptions,
    COUNT(DISTINCT e.referral_id)                         AS affected_referrals,
    CASE WHEN t.total_referrals > 0
         THEN 1.0 * COUNT(DISTINCT e.referral_id) / t.total_referrals END AS affected_referral_rate
FROM data_quality_exceptions e
CROSS JOIN totals t
GROUP BY e.issue_type, t.total_referrals;
