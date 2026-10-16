# Power BI Verification Checklist

> **Synthetic data only.** The dashboard uses computer-generated data. It contains no real
> patient information and is not for clinical decision-making.

Python tests can check the snapshot files, measures, theme and documents. They **cannot**
open, render or calculate a `.pbix` report, so every report check must be done by hand
in Power BI Desktop.

## Status

- **Phase 4A (data package and specifications):** complete. The automated items marked
  **[F]** pass.
- **Phase 4B (report build):** not started. The `.pbix` and the screenshots do not exist
  yet, and every item marked **[M]** is still open.

| Mark | Meaning |
|---|---|
| **[F]** | **Automated file check.** Verified from repository files by `pytest` (`tests/test_powerbi_assets.py`) or by `prepare_powerbi_data.py` validation, without Power BI Desktop |
| **[M]** | **Manual check in Power BI Desktop.** Done and recorded by the person building the report in Phase 4B. Not verifiable from the repository except through the saved screenshots |

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
- [ ] **[M]** All six files were imported with UTF-8, comma delimiter and the query names
  in the build guide.
- [ ] **[M]** Table view row counts match Step 4 of the build guide.

## 2. Data types

- [x] **[F]** The CSV values use stable formats:
  - dates are ISO `YYYY-MM-DD`;
  - flags are `0` or `1`;
  - durations and counts are whole numbers;
  - blanks appear only where documented.
- [ ] **[M]** Column types are set as in `DATA_DICTIONARY.md`: IDs and categories as
  Text, dates as Date, flags, counts and durations as Whole number.
- [ ] **[M]** Power Query *Column quality* shows 0% errors in every column.

## 3. Relationships

- [x] **[F]** The five relationships, their cardinality and their direction are documented
  in `POWER_BI_DATA_MODEL.md`, and every key relationship is valid in the CSV files.
- [ ] **[M]** Autodetect relationships is turned off, and only these five relationships
  exist, all *One to many*, *Single* and *Active*:
  1. `Date[date]` → `Referrals[referral_date]`
  2. `Providers[provider_id]` → `Referrals[provider_id]`
  3. `ServiceCategories[service_category_id]` → `Providers[service_category_id]`
  4. `Facilities[facility_id]` → `Providers[facility_id]`
  5. `Referrals[referral_id]` → `DataQualityExceptions[referral_id]`
- [ ] **[M]** No relationship is bidirectional, no relationship links ServiceCategories
  or Facilities directly to Referrals, and no many-to-many relationship exists.

## 4. Date table, sorting and hidden fields

- [x] **[F]** `date.csv` is continuous (2025-01-01 to 2025-12-31, no gaps), with Monday =
  1 … Sunday = 7 and correct sort columns.
- [ ] **[M]** **Auto date/time** is off for this file.
- [ ] **[M]** Date is marked as the date table on `Date[date]`.
- [ ] **[M]** Sort-by-column is set:
  - `month_name` by `month_number`;
  - `year_month` by `year_month_sort`;
  - `weekday_name` by `weekday_number`;
  - `quarter_label` by `quarter_number`;
  - `primary_leakage_reason` by `leakage_reason_priority`.
- [ ] **[M]** Technical fields are hidden, following the list in
  `POWER_BI_DATA_MODEL.md`.
- [ ] **[M]** *Don't summarize* is set on the Date number columns and on the flag, count
  and duration columns.

## 5. DAX measures

- [x] **[F]** `dax_measures.txt` contains exactly 20 uniquely named measures:
  - every rate uses `DIVIDE` and none uses `/`;
  - the medians exclude blanks;
  - every measure has a `// Format:` line;
  - the definitions use the Phase 3 flags.
- [ ] **[M]** All 20 measures were added with their documented formats.
- [ ] **[M]** A temporary table of all 20 measures, with no filters, matches the
  `display` values under `kpis` in `expected_kpis.json`.

## 6. Theme and colors

- [x] **[F]** `healthcare_referral_theme.json` is valid JSON with the documented palette.
- [ ] **[M]** The theme was imported (**View > Themes > Browse for themes**).
- [ ] **[M]** Outcome colors were assigned **manually** on every outcome visual:
  - Converted green `#2E7D4F`;
  - Active blue `#2F6DB5`;
  - Leaked red-orange `#C8553D`;
  - Unclassified gray `#8A939E`.
- [ ] **[M]** Every chart names its categories on an axis or in a legend; color is not
  the only signal.

## 7. Pages and values

- [ ] **[M]** Three pages exist with the documented visuals and positions:
  1. Referral Overview
  2. Leakage and Service Performance
  3. Turnaround Time and Data Quality
- [x] **[F]** The build guide gives every page a custom 1920 × 1080 canvas (16:9). Every
  documented position fits inside 1920 × 1080, and no two visuals overlap.
- [ ] **[M]** Every page's canvas was set manually to **Type: Custom**, **Width 1920**,
  **Height 1080** under **Format page > Canvas settings**. The theme does not set page
  dimensions.
- [ ] **[M]** Every page has the synthetic-data notice.
- [ ] **[M]** With no slicer selections, every card matches `expected_kpis.json`:

  | Page | Cards |
  |---|---|
  | 1 | Total Referrals 147,750; Converted Referrals 106,864; Conversion Rate 72.3%; Leakage Rate 26.1%; Median Days to Schedule 5.0; Median Days to First Appointment 21.0 |
  | 2 | Leaked Referrals 38,594; Leakage Rate 26.1%; Delayed Scheduling Referrals 6,831; Delayed Appointment Referrals 58,388 |
  | 3 | Active Referrals 2,292; Median Days to First Contact 1.0; Referrals with Data Quality Issues 10,805; Referrals with Duplicate Records 2,250 |

- [ ] **[M]** Charts reconcile:
  - outcome bars sum to 147,750;
  - leakage-reason bars sum to 38,594;
  - issue-type bars sum to 11,116;
  - every matrix Total row equals the cards.
- [ ] **[M]** Monthly axes run Jan 2025 → Dec 2025, and leakage reasons run in priority
  order 1 → 6.

## 8. Interactions

- [ ] **[M]** Every slicer changes the visuals on its own page only.
- [ ] **[M]** **Service Category filters Provider.** Selecting *Cardiology* limits the
  Provider slicer to Cardiology providers, and the cards show 23,684 referrals, 74.3%
  conversion and 24.6% leakage.
- [ ] **[M]** **Facility filters Provider the same way** if a Facility slicer is added
  (optional).
- [ ] **[M]** Selecting an out-of-network provider shows "(Blank)", not 0, on the
  scheduling median cards, and no visual shows an error.
- [ ] **[M]** Clicking a bar in *Data-Quality Exceptions by Issue Type* filters only that
  visual. This is expected with single-direction relationships.

## 9. Privacy and save

- [x] **[F]** The snapshot contains no patient ID, names, addresses, emails or phone
  numbers.
- [ ] **[M]** No visual shows referral-level detail, such as a table of individual
  referral IDs.
- [ ] **[M]** All slicers were cleared before saving.
- [ ] **[M]** The report is saved as `powerbi/healthcare_referral_leakage_dashboard.pbix`.

## 10. Screenshots

- [ ] **[M]** Three full-page screenshots were taken with no slicer selections:
  - `screenshots/powerbi_referral_overview.png`
  - `screenshots/powerbi_leakage_service_performance.png`
  - `screenshots/powerbi_turnaround_data_quality.png`
- [ ] **[M]** The card values in each screenshot match `expected_kpis.json`.

## Verification record (fill in during Phase 4B)

- **Date:**
- **Power BI Desktop version:**
- **Report file size:**
- **Checked by:**
- **Deviations from the build guide, and why:**
