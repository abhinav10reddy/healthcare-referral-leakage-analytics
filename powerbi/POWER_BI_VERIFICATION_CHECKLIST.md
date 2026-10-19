# Power BI Verification Checklist

> **Synthetic data only.** The dashboard uses computer-generated data. It contains no real
> patient information and is not for clinical decision-making.

This is the verification record for the finished dashboard:
- `powerbi/healthcare_referral_leakage_dashboard.pbix`
- `screenshots/powerbi_referral_overview.png`
- `screenshots/powerbi_leakage_service_performance.png`
- `screenshots/powerbi_turnaround_data_quality.png`

The saved `.pbix` and the three screenshots are the source of truth. The design is
approved as final.

## Status

- **Phase 4A (data package and specifications):** complete. Every **[F]** item passes.
- **Phase 4B (report build):** complete. The report was built by hand in Power BI Desktop,
  and the `.pbix` and three screenshots are in the repository. Every readable value in
  the screenshots matches the snapshot.
- **Open items:** the **[N]** items cannot be proven from the saved files and are left
  unticked. They are not claimed.

| Mark | Meaning |
|---|---|
| **[F]** | **Automated file check.** Verified from repository files without Power BI Desktop, either by `pytest` (`tests/test_powerbi_assets.py`), by the `prepare_powerbi_data.py` validation, or by a read-only review of the `.pbix` package's report definition (page, visual and theme JSON) |
| **[S]** | **Screenshot-visible check.** Seen in the saved screenshots and compared with `expected_kpis.json` and the tracked snapshot CSV files. A screenshot shows one unfiltered state only |
| **[M]** | **Completed manually in Power BI Desktop** during the Phase 4B build. The evidence in the saved files is noted beside each item |
| **[N]** | **Not provable from screenshots or files.** These settings live in the binary data model, or need interaction to test. They are left unticked, not claimed |

## 1. Snapshot files and import

- [x] **[F]** Six CSV files exist in `powerbi/data/`, each with the documented columns.
- [x] **[F]** Row counts match SQLite:
  - Referrals: 147,750 unique referral IDs;
  - DataQualityExceptions: 11,116;
  - ServiceCategories: 8;
  - Facilities: 12;
  - Providers: 132;
  - Date: 365.
- [x] **[F]** Model keys are valid:
  - every referral's provider exists;
  - every provider's facility and category exist;
  - every referral date is in the Date table;
  - every exception's referral exists.
- [x] **[F]** Every file is below the 50 MB safety limit (GitHub rejects files over
  100 MB).
- [x] **[M]** The six files were imported under the table names in the build guide. The
  report's diagram layout and visual field references name exactly these tables:
  `Referrals`, `DataQualityExceptions`, `ServiceCategories`, `Facilities`, `Providers`
  and `Date`.
- [ ] **[N]** Import settings (UTF-8, comma delimiter) and Table view row counts. These are
  not stored in a readable part of the `.pbix`. The unsliced totals in the screenshots
  (147,750 referrals and 11,116 exceptions) are consistent with complete imports.

## 2. Data types

- [x] **[F]** The CSV values use stable formats:
  - dates are ISO `YYYY-MM-DD`;
  - flags are `0` or `1`;
  - durations and counts are whole numbers;
  - blanks appear only where documented.
- [ ] **[N]** Column types match `DATA_DICTIONARY.md`, and Power Query *Column quality*
  shows 0% errors. These are stored in the binary data model.

## 3. Relationships

- [x] **[F]** The five relationships, their cardinality and their direction are documented
  in `POWER_BI_DATA_MODEL.md`, and every key relationship is valid in the CSV files.
- [x] **[S]** The filter paths the pages use are working. Values grouped by month,
  service category and provider, and data-quality exceptions by issue type, all match the
  snapshot. That requires the `Date → Referrals`, `Providers → Referrals` and
  `ServiceCategories → Providers` paths.
- [ ] **[N]** Exactly five relationships exist, all *One to many*, *Single* and *Active*;
  autodetect is off; nothing is bidirectional or many-to-many. These are stored in the
  binary data model. The `Facilities → Providers` and `Referrals → DataQualityExceptions`
  paths are not exercised in the unfiltered screenshots.

## 4. Date table, sorting and hidden fields

- [x] **[F]** `date.csv` is continuous (2025-01-01 to 2025-12-31, no gaps), with Monday =
  1 … Sunday = 7 and correct sort columns.
- [x] **[S]** `year_month` sorts by `year_month_sort`. The monthly axes on Pages 1 and 2
  run Jan 2025 → Dec 2025; an unsorted text axis would start at Apr 2025.
- [ ] **[N]** Auto date/time is off, and Date is marked as the date table.
- [ ] **[N]** The other sort-by-column settings:
  - `month_name`, `weekday_name` and `quarter_label` are not used on any page;
  - the leakage-reason funnel sorts by value, so its priority sort is not visible.
- [ ] **[N]** Technical fields are hidden, and *Don't summarize* is set.

## 5. DAX measures

- [x] **[F]** `dax_measures.txt` contains exactly 20 uniquely named measures:
  - every rate uses `DIVIDE` and none uses `/`;
  - the medians exclude blanks;
  - every measure has a `// Format:` line;
  - the definitions use the Phase 3 flags.
- [x] **[F]** The report's visuals reference 13 of the 20 measures by name:
  - Total Referrals, Converted Referrals, Leaked Referrals and Active Referrals;
  - Conversion Rate and Leakage Rate;
  - Delayed Scheduling Referrals and Delayed Appointment Referrals;
  - Referrals with Data Quality Issues and Data Quality Exceptions;
  - Median Days to First Contact, Median Days to Schedule and Median Days to First
    Appointment.
- [x] **[S]** Every value these 13 measures show in the screenshots matches the snapshot
  and `expected_kpis.json`, in the documented formats (`#,0`, `0.0%`, `0.0`).
- [ ] **[N]** The DAX text of each measure, and whether the seven unused measures exist,
  are stored in the binary data model. The unused measures are Scheduled Referrals,
  Completed Referrals, Referrals with Cancellation, Referrals with No Show, Referrals
  with Duplicate Records, Scheduling Rate and Completion Rate.

## 6. Theme and colors

- [x] **[F]** `healthcare_referral_theme.json` is valid JSON with the documented palette.
- [x] **[M]** The theme was imported. The `.pbix` embeds *Healthcare Referral Leakage
  (synthetic data)*:
  - its first eight data colors match the tracked theme file, and Power BI appended its
    own generated colors on import;
  - every other theme setting is identical.
- [x] **[F]** No visual has a per-category color override, so the colors follow the theme
  palette in order. The approved colors are listed in Step 7 of the build guide.
- [x] **[S]** Every chart names its categories on an axis, in a legend or in its data
  labels; color is not the only signal.

## 7. Pages and values

- [x] **[F]** The `.pbix` has exactly three pages, in this order (checked by `pytest`):
  1. Referral Overview
  2. Leakage & Service Performance
  3. Turnaround Time & Data Quality
- [x] **[F]** Every page is 1920 × 1080 (16:9) and uses *Fit to page* (checked by
  `pytest`).
- [x] **[M]** Every page's canvas was set manually to **Type: Custom**, **Width 1920**,
  **Height 1080** under **Format page > Canvas settings**. The saved page definitions
  confirm it. The theme does not set page dimensions.
- [x] **[F]** The build guide documents every page at 1920 × 1080, and every documented
  position fits inside the canvas (checked by `pytest`).
- [x] **[S]** Each page has the approved visuals:

  | Page | Cards | Slicers | Visuals |
  |---|---|---|---|
  | 1 | Total Referrals; Converted Referrals; Conversion Rate; Leakage Rate; Median Days to Schedule; Median Days to First Appointment | Provider; Service Category; Referral Date | Monthly Referral Volume; Referrals by Service Category; Referral Outcomes (donut); Service Category Performance (matrix) |
  | 2 | Leaked Referrals; Leakage Rate; Delayed Scheduling Referrals; Delayed Appointment Referrals | Facility; Service Category; Urgency | Top 15 Providers by Leaked Referrals; Leakage Rate by Service Category; Monthly Referrals vs Leakage; Provider Performance (matrix) |
  | 3 | Median Days to First Contact; Median Days to Schedule; Referrals with Data Quality Issues; Data Quality Exceptions | Referral Date; Service Category; Provider; Referral Source; Urgency | Primary Leakage Reasons (funnel); Referral Outcomes by Urgency (100% stacked); Data Quality Exceptions by Issue Type; Turnaround Time by Service Category (combo); Data Quality Resolution Status (donut) |

- [x] **[S]** With no slicer selections, every card matches `expected_kpis.json`:

  | Page | Cards |
  |---|---|
  | 1 | Total Referrals 147,750; Converted Referrals 106,864; Conversion Rate 72.3%; Leakage Rate 26.1%; Median Days to Schedule 5.0; Median Days to First Appointment 21.0 |
  | 2 | Leaked Referrals 38,594; Leakage Rate 26.1%; Delayed Scheduling Referrals 6,831; Delayed Appointment Referrals 58,388 |
  | 3 | Median Days to First Contact 1.0; Median Days to Schedule 5.0; Referrals with Data Quality Issues 10,805; Data Quality Exceptions 11,116 |

  The screenshots show Indian digit grouping (`1,47,750` and `1,06,864`) from the
  computer's regional settings. The values are the same.
- [x] **[S]** The charts reconcile with the snapshot:
  - **Outcome donut:** Converted 72.33%, Leaked 26.12% and Active 1.55%, which sum to
    147,750 referrals.
  - **Leakage-reason funnel:** the step labels (11K, 8K, 8K, 5K, 4K, 2K) and the 19.5%
    bottom ratio match the six reasons, which total 38,594.
  - **Issue types:** the bars match the six issue counts, which total 11,116.
  - **Resolution status:** Unresolved 59.81% and Resolved 40.19% of 11,116.
  - **Outcomes by urgency:** every share matches. For example, Routine is 71.97% /
    26.06%, Urgent is 73.13% / 26.35% and Stat is 73.80% / 25.98%.
  - **Service Category Performance matrix:** every row and the Total row match.
  - **Provider Performance matrix:** the visible rows and the Total row match.
- [x] **[S]** The Top 15 Providers chart shows the 15 providers with the most leaked
  referrals, in order: Behavioral Health Provider 075 (709) down to Orthopedics
  Provider 113 (540). The `.pbix` stores a Top N = 15 filter by Leaked Referrals.
- [x] **[S]** The monthly axes run Jan 2025 → Dec 2025.
- **Not applicable as built:** the pages have no on-canvas synthetic-data notice. The
  approved design keeps the notice in the README and the Power BI documents (see
  *Deviations*).

## 8. Interactions

- [x] **[F]** The saved report opens unfiltered:
  - no slicer stores a selection;
  - there are no page-level or report-level filters.
- [x] **[S]** Out-of-network providers show a blank median, not 0. In the Page 2 matrix,
  Behavioral Health Provider 108 (275 referrals, all external) has a blank Median Days
  to Schedule.
- [ ] **[N]** Each slicer was tested by hand: it changes the visuals on its own page
  only, Service Category limits the Provider list (*Cardiology*: 23,684 referrals, 74.3%
  conversion, 24.6% leakage), and Facility filters through Providers. The screenshots
  capture only the unfiltered state, and no interaction test is recorded in the
  repository.
- [ ] **[N]** Clicking an exception visual filters only exception-based visuals. This is
  not tested in a saved file.

## 9. Privacy and save

- [x] **[F]** The snapshot contains no patient ID, names, addresses, emails or phone
  numbers.
- [x] **[S]** No visual shows referral-level detail. The finest grain shown is the
  provider.
- [x] **[S]** All slicers show *All* or the full 2025 date range in the screenshots.
- [x] **[F]** The report is saved as `powerbi/healthcare_referral_leakage_dashboard.pbix`
  (checked by `pytest`):
  - it is a non-empty, valid ZIP package;
  - it is the only `.pbix` in the repository, and none is inside `powerbi/data/`;
  - it is not ignored by Git.

## 10. Screenshots

- [x] **[F]** The three screenshots exist under their exact lower-case names (checked by
  `pytest`):
  - each is a valid, complete PNG with an intact chunk structure and an `IEND` end
    chunk;
  - each is close to 16:9 (1343 × 756, 1346 × 753 and 1350 × 752);
  - none is ignored by Git.
- [x] **[S]** Each screenshot shows a full page with no slicer selections, and its card
  values match `expected_kpis.json`.

## Deviations from the Phase 4A plan

The design is approved as final. These differences from the original Phase 4A plan are
documented as built in the build guide. None changes a KPI, a measure or the data model.

1. **Page names:** Pages 2 and 3 use "&" (*Leakage & Service Performance*, *Turnaround
   Time & Data Quality*).
2. **Page 1:**
   - a **Referral Outcomes donut** replaces the outcome column chart;
   - the line chart and the category bar chart sit side by side, above the donut and the
     matrix;
   - the matrix shows Median Days to First Appointment instead of Delayed Scheduling
     Referrals.
3. **Page 2:**
   - the slicers are **Facility, Service Category and Urgency**, not Provider, Service
     Category and Referral Date;
   - the provider chart ranks the **Top 15 by Leaked Referrals**, not by Leakage Rate;
   - the monthly combo chart puts Leaked Referrals on a secondary axis;
   - the matrix leaves out Converted Referrals, and shows Median Days to Schedule
     instead of Median Days to First Appointment.
4. **Page 3:**
   - the cards are Median Days to First Contact, Median Days to Schedule, Referrals with
     Data Quality Issues and Data Quality Exceptions, replacing Active Referrals and
     Referrals with Duplicate Records;
   - the visuals are a leakage-reason **funnel** (sorted by size), **Referral Outcomes by
     Urgency** (100% stacked), **Data Quality Exceptions by Issue Type**, **Turnaround
     Time by Service Category** and **Data Quality Resolution Status**;
   - these replace the source, urgency-rate and insurance charts.
5. **Layout:**
   - visuals tile edge to edge with no margins, like the earlier dashboard;
   - on Page 2, the two upper-right chart frames extend 15 px into the matrix frame,
     with no visible overlap.
6. **No on-canvas synthetic-data notice.**
7. **Colors** follow the theme palette in order, with no per-category overrides. For
   example, Leaked is green and Converted is teal in the outcome donut.
8. **Number and date display** follow the Windows regional settings of the computer
   that took the screenshots: Indian digit grouping and `DD-MM-YYYY` dates.
9. **Screenshot file names** were saved with an upper-case `.PNG` extension. They were
   renamed to the documented lower-case `.png` names, because Git and GitHub are
   case-sensitive. The image bytes are unchanged.

## Verification record

- **Date:** 2026-10-16. The screenshots were taken at 15:11–15:12, and the `.pbix` was
  last saved at 15:33. The file and screenshot review was completed on 2026-10-19.
- **Final save of the `.pbix`:** the file was saved again after the screenshots.
  - **What changed:** only the binary `DataModel` part and the small `Settings` part
    changed size.
  - **What did not change:** the report definition (pages, canvas size, visuals,
    fields, titles, positions, sorting, Top N filter, saved filter state and theme) is
    identical to the version the screenshots show.
  - **What cannot be compared:** the binary data model's contents.
- **Power BI Desktop version:** the `.pbix` `Settings` part records `2.158.928.0`, most
  likely the build that last saved it.
  - The `.pbix` uses the enhanced report format (PBIR, report definition version
    2.0.0).
  - Its base theme is *Fluent2-CY26SU09*.
- **Report file size:** about 2.9 MB, well below the 50 MB limit.
- **Checked by:** the report author (manual build and design approval), plus automated
  file, report-definition and screenshot checks.
- **Deviations from the build guide, and why:** see *Deviations from the Phase 4A plan*.
  The design was approved as final, and the build guide now records it as built.
