# KPI and Referral-Leakage Definitions (Phase 3)

These definitions are implemented in `sql/02_create_analytics_views.sql`. They are checked
automatically by `analyze_data.py`.

> All data is fully synthetic and fictional. These definitions are for portfolio and
> educational use only. They are not clinical standards, and the data must not be used for
> clinical decision-making.

## Parameters

| Parameter | Value | Source |
| --- | --- | --- |
| Reporting period | 2025-01-01 to 2025-12-31 (referral dates) | `config.py` |
| Extract date | 2026-01-31: the last date of follow-up activity in the data | `config.py` |
| Follow-up window | 30 days | `config.FOLLOW_UP_WINDOW_DAYS` |
| Scheduling delay threshold | 30 days | `config.SCHEDULING_DELAY_THRESHOLD_DAYS` |
| Appointment target | `service_categories.target_days_to_appointment` (illustrative, 10–30 days) | Phase 1 master data |

The SQL repeats these values in `vw_analysis_parameters`, so the views can be queried on
their own. `analyze_data.py` fails if they differ from `config.py`.

## Referral-level vs appointment-level

- **Referral-level** measures count **referrals**. Each referral counts once, however many
  appointments it has. Appointments are aggregated per referral in
  `vw_appointment_summary` *before* they are joined to referrals.
- **Appointment-level** measures count **appointment rows**. Their column names always
  contain `appointment`, for example `cancelled_appointments` and
  `appointment_no_show_rate`.

For example, `cancelled_referrals` is the number of referrals with at least one cancelled
appointment. `cancelled_appointments` is the number of cancelled appointment rows.

## Definitions

| # | Measure | Definition |
| --- | --- | --- |
| 1 | Total Referrals | `COUNT(DISTINCT referral_id)` of processed referrals. `vw_referral_journey` has exactly one row per referral. |
| 2 | Scheduled Referral | At least one appointment record, of any status (`scheduled_flag`). |
| 3 | Completed Referral | At least one `Completed` appointment (`completed_flag`), counted once per referral. |
| 4 | Confirmed External Outcome | `referral_status = 'Sent External'` and `closure_reason = 'External Visit Confirmed'` (`confirmed_external_outcome_flag`). The closure reason is the evidence. A blank `closed_date` (a Phase 2 data-quality issue) does not cancel the confirmation. |
| 5 | Converted Referral | Completed referral **or** confirmed external outcome (`converted_flag`). |
| 6 | Conversion Rate | Converted / Total Referrals; NULL when there are no referrals. |
| 7 | Active / In Progress | Not converted, and still legitimately open at the extract date (see [Active / In Progress](#active--in-progress)). |
| 8 | Leakage | Not converted, not active, and meets one leakage rule. Each leaked referral gets exactly one `primary_leakage_reason` (see [Leakage rules](#leakage-rules)). |
| 9 | Leakage Rate | Leaked / Total Referrals; NULL when there are no referrals. |
| 10 | Scheduling Rate | Scheduled / Total Referrals. |
| 11 | Completion Rate | Completed / Total Referrals. |
| 12 | Cancellation and no-show | **Referral-level:** referrals with at least one Cancelled / No-Show appointment (`cancelled_referrals`, `no_show_referrals`, and rates over Total Referrals). **Appointment-level:** Cancelled / No-Show appointment rows over all appointment rows (`appointment_cancellation_rate`, `appointment_no_show_rate`). |
| 13 | Turnaround time | Whole days from `referral_date` (see [Turnaround time](#turnaround-time)). |
| 14 | Delayed Scheduling | First booking more than 30 days after the referral date (`delayed_schedule_flag`). The model has no scheduling target, so the documented 30-day threshold is used, matching the leakage window. Referrals never booked are not "delayed"; when they leak, it shows in their leakage reason. |
| 15 | Delayed Appointment | First appointment date more than the service category's `target_days_to_appointment` after the referral date (`delayed_appointment_flag`). The target is an illustrative synthetic benchmark, not a clinical standard. |
| 16 | Duplicate Referral | `duplicate_record_count > 0`, from Phase 2. This is the number of duplicate raw rows removed for that referral. |
| 17 | Data-Quality Exception | `data_quality_issue_count` and `has_data_quality_issue` on referrals, plus the Phase 2 `data_quality_exceptions` table. |

Every referral is classified as exactly one of **Converted**, **Active** or **Leaked**,
shown in `outcome_category`. Any referral that fits none of them is reported as
**Unclassified** rather than forced into a group. Conversion Rate plus Leakage Rate is
therefore not forced to equal 100%, because active referrals are neither.

## Active / In Progress

A referral that is not converted is **active** when any of these holds at the extract date:

1. It has a `Scheduled` appointment dated after the extract date.
2. Its status is `Pending`, it has no appointment, and it is less than 30 days old.
3. Its status is `Pending`, its last appointment was Cancelled or a No-Show, and that
   appointment was less than 30 days before the extract date. It is awaiting rebooking.
4. Its status is `Sent External`, it has no confirmed outcome, and it is less than 30 days
   old. An outcome may still arrive.

An open status on its own does not make a referral active. A `Pending` referral is active
only if a future appointment exists or something happened within the last 30 days.

## Leakage rules

A referral is checked against these rules only if it is neither converted nor active. The
first matching rule, in priority order, becomes its `primary_leakage_reason`.

| Priority | Primary leakage reason | Rule |
| --- | --- | --- |
| 1 | External Outcome Missing | `Sent External` with no confirmed external outcome, and the follow-up window has passed |
| 2 | Expired Before Completion | Status `Expired` |
| 3 | Cancelled Without Successful Rebooking | The last appointment (highest `appointment_sequence`) is `Cancelled`, so no later appointment exists |
| 4 | No-Show Without Successful Follow-Up | The last appointment is a `No-Show`, so no later appointment exists |
| 5 | Declined Before Scheduling | Status `Declined` |
| 6 | Not Scheduled Within 30 Days | No appointment, and at least 30 days since the referral date |

Two adjustments to the requested rules, both needed by the actual data:

- **Rules 3 and 4 use the last appointment.** A referral that was cancelled, rebooked and
  then completed is converted. If it was cancelled, rebooked and then a no-show, it was
  successfully rebooked once. Its journey ended at the no-show, so rule 4 applies. This
  keeps the reason consistent with Phase 1 closure reasons. Earlier cancellations and
  no-shows are still counted in `had_cancellation_flag` and `had_no_show_flag`.
- **Rule 1 waits 30 days.** A referral sent externally less than 30 days before the extract
  date is active, not leaked. In the seed-42 data every referral is at least 31 days old,
  so this exception never applies there.

Rescheduled appointments never end a journey (Phase 2 validates this), so there is no
rescheduling leakage rule. Reschedules appear in `had_reschedule_flag` and
`rescheduled_appointment_count`.

### Invariants

`analyze_data.py` enforces these invariants on every run. The run fails if any of them is
broken.

- **Not Scheduled Within 30 Days** requires `appointment_count = 0` and
  `scheduled_flag = 0`. A referral with any appointment booking is never described as
  "not scheduled".
- **Future appointments:** a non-converted referral with a `Scheduled` appointment after
  the extract date is always **Active** and never **Leaked**.
- **Matching conditions:** every leakage reason agrees with its underlying condition. For
  example, every "Cancelled Without Successful Rebooking" referral has a cancelled last
  appointment.

### Scheduled appointments on or before the extract date

An appointment still marked `Scheduled` on or before the extract date would be an overdue
status: it should have been completed, cancelled or marked a no-show. Phase 2 rejects this
as a structural error (`scheduled_appointment_after_extract_date`), so it cannot reach the
analytics; the seed-42 data has none.

If one ever did reach Phase 3, the referral would keep `scheduled_flag = 1` and would not be
treated as active. It would never be labelled "Not Scheduled", so it would show as
**Unclassified**, where it is visible in `unclassified_referrals`. No leakage rule is
invented for this state.

## Referral funnel

`vw_referral_funnel` shows progressive stages. They are not mutually exclusive.

| Stage | Definition |
| --- | --- |
| 1. Total Referrals | Every processed referral |
| 2. Contacted | `first_contact_date` recorded, **or** contact evidenced by an appointment or a `Declined` status. The evidence covers the Phase 2 blanks flagged as missing first-contact dates. |
| 3. Scheduled | At least one appointment record |
| 4. Completed or Confirmed External Outcome | Converted (definition 5) |

Each stage is split into `internal_referrals` and `external_referrals`, where external
means `referral_status = 'Sent External'`. External referrals never have internal
appointments, so they skip stage 3. Their confirmed outcomes still count in stage 4. That
is why stage 4 can include referrals that are not in stage 3.

## Turnaround time

| Measure | From | To |
| --- | --- | --- |
| `days_to_first_contact` | `referral_date` | `first_contact_date` |
| `days_to_schedule` | `referral_date` | earliest `booked_date` |
| `days_to_first_appointment` | `referral_date` | earliest `appointment_date` (the first slot booked, whatever its outcome) |

- **Missing dates:** a missing date gives NULL, never 0. Averages and medians use only
  nonmissing values, and `eligible_referrals` reports how many were used.
- **Negative durations:** these cannot pass Phase 2 validation. As a safeguard, the views
  turn any negative duration into NULL and set `invalid_duration_flag`.
- **Median method:** durations are whole days, so the median is read from the frequency
  distribution. Referrals are counted per day value, a running total is kept with a window
  `SUM`, and the value at the middle position is taken. For an even count, the median is
  the mean of the two middle values, at positions `(n + 1) / 2` and `(n + 2) / 2` using
  integer division.

## NULL and Unknown handling

- **Rates and averages:** a rate is NULL when its denominator is zero. An average or
  median is NULL when there are no eligible values.
- **Empty database:** `vw_overall_kpis` still returns one row, with zero counts and NULL
  rates.
- **Missing categories:** grouped views label a missing category value `Unknown` instead of
  dropping it. Each grouped view therefore sums to the overall totals.

## Fields not available in the model

`referring_provider_id` and `referring_facility_id` were requested but cannot be created.
The Phase 1 schema records only the **receiving** provider and facility. The referring side
appears only as `referral_source`, which is a category such as Primary Care or Emergency
Department. These fields are not invented.

## Views

| View | Grain |
| --- | --- |
| `vw_analysis_parameters` | One row of parameters |
| `vw_leakage_reasons` | Leakage reasons and priorities |
| `vw_appointment_summary` | One row per referral that has appointments (helper) |
| `vw_referral_journey` | **One row per referral**: segments, appointment summary, durations, flags and leakage reason |
| `vw_analysis_dimensions`, `vw_journey_by_dimension`, `vw_dimension_metrics` | Shared grouping helpers, so every grouped view uses identical logic |
| `vw_overall_kpis` | One row of overall referral-level and appointment-level KPIs |
| `vw_referral_funnel` | One row per funnel stage |
| `vw_monthly_metrics` | One row per referral month (`YYYY-MM`) |
| `vw_service_category_metrics` | One row per service category |
| `vw_facility_metrics` | One row per receiving facility |
| `vw_referral_source_metrics` | One row per referral source |
| `vw_urgency_metrics` | One row per urgency level |
| `vw_insurance_metrics` | One row per insurance type |
| `vw_leakage_reason_metrics` | One row per leakage reason, zeros included |
| `vw_turnaround_metrics` | One row per turnaround measure |
| `vw_data_quality_metrics` | One row per Phase 2 data-quality issue type |
