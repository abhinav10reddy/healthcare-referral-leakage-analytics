# Power BI Dashboard Build Guide

> **Synthetic data only.** The dashboard shows computer-generated data. It does not
> describe real patients, providers or facilities, and it is for portfolio and educational
> use only, not for clinical decision-making. The as-built pages carry no on-canvas
> notice, so this notice is given in the README and in every Power BI document instead.

This guide builds the dashboard **by hand in Power BI Desktop (Windows)** from the files
prepared in Phase 4A. No Python script creates, opens or checks a `.pbix` file. The
following are all manual steps, recorded in
[POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md):
- importing the CSV files;
- setting data types;
- creating relationships;
- marking the Date table;
- turning off Auto date/time;
- adding the DAX measures;
- importing the theme;
- building the visuals;
- assigning status colors;
- testing interactions;
- saving the report;
- taking screenshots.

**Status:** complete.
- **Phase 4A:** this guide and its data.
- **Phase 4B:** the report was built by hand in Power BI Desktop, following Steps 1–8.
  The design is approved as final.
- **Step 9 records the dashboard as built.** The page specifications describe the saved
  `.pbix` and the three screenshots, which are the source of truth. Where the as-built
  report differs from the original Phase 4A plan, the as-built version is documented.
  The differences are listed in the
  [verification checklist](POWER_BI_VERIFICATION_CHECKLIST.md#deviations-from-the-phase-4a-plan).

| You will use | File |
|---|---|
| Six data tables | `powerbi/data/*.csv` |
| Model specification | [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md) |
| Column types and meanings | [DATA_DICTIONARY.md](DATA_DICTIONARY.md) |
| DAX measures (20) | [dax_measures.txt](dax_measures.txt) |
| Theme | [healthcare_referral_theme.json](healthcare_referral_theme.json) |
| Reference values | [expected_kpis.json](expected_kpis.json) |
| Report (built in Phase 4B) | `powerbi/healthcare_referral_leakage_dashboard.pbix` |
| Screenshots (taken in Phase 4B) | `screenshots/powerbi_referral_overview.png`, `screenshots/powerbi_leakage_service_performance.png`, `screenshots/powerbi_turnaround_data_quality.png` |

## Step 0: Refresh the data files (optional)

The snapshot in `powerbi/data/` is already in the repository. To rebuild it from scratch,
run these commands from the project folder in PowerShell. The last command rewrites
`powerbi/data/` and `powerbi/expected_kpis.json`, but only if every validation check
passes.

```powershell
.\.venv\Scripts\python.exe generate_data.py --referrals 150000 --seed 42
.\.venv\Scripts\python.exe prepare_data.py
.\.venv\Scripts\python.exe analyze_data.py
.\.venv\Scripts\python.exe prepare_powerbi_data.py
```

## Step 1: Create the file and change two settings

1. Open Power BI Desktop and choose **Blank report**.
2. Go to **File > Options and settings > Options**. Under **CURRENT FILE > Data Load**:
   - under *Time intelligence*, clear **Auto date/time**;
   - under *Relationships*, clear **Autodetect new relationships after data is loaded**.
     You will create the relationships yourself in Step 5.
3. Select **OK**.
4. Save the file now as `powerbi/healthcare_referral_leakage_dashboard.pbix` (**File >
   Save as**), and save again after each step.

## Step 2: Import the six CSV files

Do this for each file in `powerbi/data/`:
1. Select **Home > Get data > Text/CSV**, then select the file.
2. In the preview window, check these settings:
   - **File origin:** `65001: Unicode (UTF-8)`;
   - **Delimiter:** Comma;
   - **Data type detection:** Based on entire dataset.
3. Select **Transform Data**. For the second and later files, use **Home > New Source >
   Text/CSV** inside Power Query.

Rename each query by double-clicking its name in the Queries pane:

| File | Query (table) name |
|---|---|
| `referral_journey.csv` | `Referrals` |
| `data_quality_exceptions.csv` | `DataQualityExceptions` |
| `service_categories.csv` | `ServiceCategories` |
| `facilities.csv` | `Facilities` |
| `providers.csv` | `Providers` |
| `date.csv` | `Date` |

## Step 3: Set the data types in Power Query

Check every column against [DATA_DICTIONARY.md](DATA_DICTIONARY.md). To change a type,
click the type icon in the column header and choose **Replace current** if asked.

- **Text:**
  - every `*_id` column;
  - every name, label and category column, such as `referral_source`, `outcome`,
    `primary_leakage_reason`, `issue_label` and `month_name`.
- **Date:**
  - `Referrals[referral_date]`, `[first_contact_date]`, `[first_booking_date]` and
    `[first_appointment_date]`;
  - `Date[date]`.
- **Whole number:**
  - every Referrals `*_flag` column;
  - `has_data_quality_issue`, `leakage_reason_priority`, `duplicate_record_count` and
    `data_quality_issue_count`;
  - the three `days_to_*` columns;
  - `ServiceCategories[target_days_to_appointment]`;
  - every number column in Date.

Then check for problems:
1. Turn on **View > Column quality** and **Column profiling based on entire data set**
   (in the status bar).
2. Every column must show **0% Error**.
3. Blanks are expected only in these columns:
   - Referrals: `primary_leakage_reason` and `leakage_reason_priority`, which are blank
     unless the referral is leaked;
   - Referrals: the three `first_*_date` columns and the three `days_to_*` columns;
   - `DataQualityExceptions[referral_id]`, which has no blanks with seed 42.
4. If a date column shows errors, change its type with **Using Locale…** and choose
   *English (United States)*. The files use ISO `YYYY-MM-DD`.

Select **Home > Close & Apply**.

## Step 4: Check the row counts

In **Table view**, select each table; the row count appears at the bottom left. Compare it
with `snapshot.row_counts` in `expected_kpis.json`:

| Table | Rows (seed 42) |
|---|---|
| Referrals | 147,750 |
| DataQualityExceptions | 11,116 |
| ServiceCategories | 8 |
| Facilities | 12 |
| Providers | 132 |
| Date | 365 |

## Step 5: Create the relationships

1. Open **Model view**, then **Home > Manage relationships**. Delete any relationship
   that is not in the list below.
2. Select **New** for each relationship and set:
   - **Cardinality:** One to many (1:\*)
   - **Cross filter direction:** Single
   - **Make this relationship active:** ticked

| # | One side | Many side |
|---|---|---|
| 1 | `Date[date]` | `Referrals[referral_date]` |
| 2 | `Providers[provider_id]` | `Referrals[provider_id]` |
| 3 | `ServiceCategories[service_category_id]` | `Providers[service_category_id]` |
| 4 | `Facilities[facility_id]` | `Providers[facility_id]` |
| 5 | `Referrals[referral_id]` | `DataQualityExceptions[referral_id]` |

Do **not** set any relationship to *Both*, and do not relate ServiceCategories or
Facilities directly to Referrals. Service Category and Facility reach referrals through
Providers. [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md) explains why.

## Step 6: Date table, sorting, hiding and summarization

1. **Mark the date table.** Select Date, then **Table tools > Mark as date table**, choose
   `date`, and select OK.
2. **Sort columns.** Select the column in the Data pane, then **Column tools > Sort by
   column**:
   - `Date[month_name]` → `month_number`
   - `Date[year_month]` → `year_month_sort`
   - `Date[weekday_name]` → `weekday_number`
   - `Date[quarter_label]` → `quarter_number`
   - `Referrals[primary_leakage_reason]` → `leakage_reason_priority`
3. **Hide technical columns.** Right-click each column, then **Hide in report view**.
   Use the list in [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md#model-settings):
   - Referrals: IDs, flags, counts, dates and durations;
   - every key column in the other tables;
   - the four Date sort columns.
4. **Don't summarize.** For the Date number columns,
   `ServiceCategories[target_days_to_appointment]` and the Referrals flag, count and
   duration columns, set **Column tools > Summarization > Don't summarize**. Every total
   on the dashboard comes from a measure.

## Step 7: Import the theme and plan the status colors

Select **View > Themes > Browse for themes**, then choose
`powerbi/healthcare_referral_theme.json`.

The theme sets:
- Segoe UI text and dark navy titles;
- white visuals on a light gray page (`#F4F6F8`);
- no borders or shadows;
- medium blue (`#2F6DB5`) as the first data color, so single-series charts are blue.

A Power BI theme **cannot** link a category value, such as "Leaked", to a fixed color.
It only supplies a palette, used in order. A color can be pinned to a category only
**manually**, on each visual, under **Format visual > Visual > Columns / Bars / Slices >
Colors**.

**As built,** the report keeps the theme palette in order and has no per-category color
overrides. The saved `.pbix` contains no color settings on any visual. The approved
colors, as seen in the screenshots, are:

| Visual | Series → theme color |
|---|---|
| Referral Outcomes (donut, Page 1) | Active → blue `#2F6DB5`; Converted → teal `#1A8A7D`; Leaked → green `#2E7D4F` |
| Referral Outcomes by Urgency (Page 3) | Converted Referrals → blue; Leaked Referrals → teal; Active Referrals → green |
| Monthly Referrals vs Leakage (Page 2) | Total Referrals columns → blue; Leaked Referrals line → teal |
| Turnaround Time by Service Category (Page 3) | Median Days to First Appointment columns → blue; First Contact line → teal; Schedule line → green |
| Data Quality Resolution Status (Page 3) | Resolved → blue; Unresolved → teal |
| Single-series bar and column charts | Blue |

Color is never the only signal. Every chart also names its categories on an axis or in a
legend.

## Step 8: Create the measures

Open [dax_measures.txt](dax_measures.txt) and add the 20 measures one at a time:
1. Select the home table named in the section heading.
2. Select **Home > New measure** and paste one measure (its name line and expression).
3. Under **Measure tools > Format**, set the format in its `// Format:` line:
   - **Counts:** Whole number with thousands separator (`#,0`).
   - **Rates:** Percentage, 1 decimal place (`0.0%`).
   - **Medians:** Decimal number, 1 decimal place (`0.0`).

| Group | Measures |
|---|---|
| Counts (13) | Total Referrals, Scheduled Referrals, Completed Referrals, Converted Referrals, Leaked Referrals, Active Referrals, Referrals with Cancellation, Referrals with No Show, Delayed Scheduling Referrals, Delayed Appointment Referrals, Referrals with Data Quality Issues, Referrals with Duplicate Records, Data Quality Exceptions |
| Rates (4) | Conversion Rate, Leakage Rate, Scheduling Rate, Completion Rate |
| Turnaround (3) | Median Days to First Contact, Median Days to Schedule, Median Days to First Appointment |

**Check the measures before building pages:**
1. On a blank page, add a **Table** visual containing all 20 measures, with no slicers.
2. Compare each value with its `display` value under `kpis` in `expected_kpis.json`.
   Medians show `1.0`, `5.0` and `21.0`.
3. Delete the page.

## Step 9: The three report pages (as built)

These specifications describe the saved report. Positions are *x, y, width, height* in
pixels on the 1920 × 1080 canvas, read from the saved `.pbix` and rounded to whole pixels.
Set them under **Format > General > Properties**.

### Settings for every page

- **Canvas: custom 1920 × 1080 px on every page.** This is the same canvas as the
  earlier portfolio dashboard, and it keeps the 16:9 aspect ratio.
  - **Set it by hand on each page.** Select an empty part of the canvas, then go to
    **Format page > Canvas settings**, and set **Type: Custom**, **Width: 1920** and
    **Height: 1080**.
  - **New pages start at the default 16:9 size,** so repeat this for all three pages.
  - **The theme file does not set page dimensions.** It controls only colors, text and
    visual styles.
  - **Page view:** the saved report uses **View > Page view > Fit to page**.
- **Layout:**
  - each page has a full-width row of KPI cards (`y = 0`, about 168 px high);
  - a full-width row of slicers sits below the cards (`y ≈ 167`, 76 px high);
  - the charts fill the rest of the page to the bottom edge;
  - visuals tile edge to edge with no margins, as in the earlier dashboard.
- **Overlaps:** manual placement leaves overlaps of at most 2 px between neighboring
  frames. The exception is Page 2, where the two upper-right charts extend 15 px into the
  top of the Provider Performance matrix's frame. The screenshot shows no visible overlap.
- **No on-canvas notice:** the pages carry no synthetic-data text box. The notice is in
  the README and in the Power BI documents.
- **Cards:** these use the new **Card** visual (`cardVisual`), with the measure name as
  the label.
- **Slicers:** each page's slicers filter only that page; slicers are not synced between
  pages.
  - **Dropdown slicers** are used for Provider, Facility, Service Category, Referral
    Source and Urgency. Each header shows its field name.
  - **Referral Date** is a *Between* slider on `Date[date]`.
- **Interactions:** the default **filter** interactions are kept. Selecting a slicer
  value or a data point filters the other visuals on the page.
  - **Service Category and Facility filter Provider.** Both reach referrals through
    Providers, so selecting either shortens the Provider slicer list.
  - **Selecting a provider does not shorten the category list.** This is expected with
    single-direction relationships.
  - **Referral filters reach the exception visuals.** Slicers and selections on
    referral fields filter the two data-quality exception visuals on Page 3, because
    Referrals filters DataQualityExceptions.
  - **Exception selections do not filter referral visuals.** Clicking a bar or slice in
    the exception visuals filters only exception-based visuals, by design.
- **Number and date display:** these follow the Windows regional settings of the
  computer that renders the report. The saved screenshots use Indian digit grouping
  (`1,47,750` = 147,750) and `DD-MM-YYYY` slicer dates. The values are unaffected.
- **Matrix totals:** row subtotals are on, and the Total row matches the cards.

### Page 1: Referral Overview

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+-------+-------+-------+-------+-------+-------+
| Total |Conver-| Conv. |Leakage|Median |Median |   KPI cards
|Referr.|  ted  | Rate  | Rate  |Days to|Days to|
|       |       |       |       |Sched. |1st App|
+-------+-------+-------+-------+-------+-------+
| Provider v    | Service Category v | Date |--| |   slicers
+-----------------------+-----------------------+
| Monthly Referral      | Referrals by Service  |
| Volume (line)         | Category (bar)        |
+---------------+-------+-----------------------+
| Referral      | Service Category Performance  |
| Outcomes      | (matrix)                      |
| (donut)       |                               |
+---------------+-------------------------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Total Referrals | n/a | Total Referrals | 0, 0, 327, 168 | `#,0` |
| 2 | Card | Converted Referrals | n/a | Converted Referrals | 327, 0, 316, 168 | `#,0` |
| 3 | Card | Conversion Rate | n/a | Conversion Rate | 644, 0, 316, 168 | `0.0%` |
| 4 | Card | Leakage Rate | n/a | Leakage Rate | 960, 0, 316, 168 | `0.0%` |
| 5 | Card | Median Days to Schedule | n/a | Median Days to Schedule | 1276, 0, 316, 168 | `0.0` |
| 6 | Card | Median Days to First Appointment | n/a | Median Days to First Appointment | 1592, 0, 328, 168 | `0.0` |
| 7 | Slicer (Dropdown) | `Providers[provider_name]` | A–Z | Provider | 0, 167, 643, 75 | Filtered by the Service Category slicer |
| 8 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service category | 644, 167, 633, 76 | Filters the Provider slicer |
| 9 | Slicer (Between) | `Date[date]` | n/a | (no header) | 1276, 168, 644, 76 | Date range 2025-01-01 to 2025-12-31 |
| 10 | Line chart | X: `Date[year_month]`; Y: Total Referrals | `year_month`, ascending (by `year_month_sort`) | Monthly Referral Volume | 0, 242, 960, 404 | Smoothed line; the Y axis starts near the minimum (11K), not at 0 |
| 11 | Clustered bar chart | Y: `ServiceCategories[service_category_name]`; X: Total Referrals | Total Referrals, descending | Referrals by Service Category | 960, 244, 960, 403 | One color (blue); X axis starts at 0 |
| 12 | Donut chart | Legend: `Referrals[outcome]`; Values: Total Referrals | Total Referrals, descending | Referral Outcomes | 0, 647, 643, 433 | Detail labels show value and percent of total; the total (148K) is in the centre; theme palette colors from Step 7 |
| 13 | Matrix | Rows: `ServiceCategories[service_category_name]`; Values: Total Referrals, Conversion Rate, Leakage Rate, Median Days to Schedule, Median Days to First Appointment | Service category, A–Z | (none; known as Service Category Performance) | 643, 647, 1277, 433 | Row subtotals on (Total row) |

**Expected unsliced values (seed 42).** These cards must match `expected_kpis.json`:

| Card | Expected (seed 42) |
|---|---|
| Total Referrals | 147,750 |
| Converted Referrals | 106,864 |
| Conversion Rate | 72.3% |
| Leakage Rate | 26.1% |
| Median Days to Schedule | 5 |
| Median Days to First Appointment | 21 |

With the `0.0` format, the median cards show one decimal place (5.0 and 21.0).

The charts must show these values:

- **Monthly Referral Volume:** the points match `by_month`, from 13,055 in January to
  11,655 in December. October is the highest month, at 13,892, and February the lowest, at
  11,118.
- **Referrals by Service Category:**

  | Service category | Referrals |
  |---|---|
  | Orthopedics | 25,124 |
  | Cardiology | 23,684 |
  | Physical Therapy | 22,106 |
  | Behavioral Health | 17,772 |
  | Gastroenterology | 16,427 |
  | Dermatology | 14,745 |
  | Neurology | 14,728 |
  | General Surgery | 13,164 |

- **Referral Outcomes:** Converted 106,864 (72.33%), Leaked 38,594 (26.12%) and Active
  2,292 (1.55%). The total is 147,750, and no Unclassified slice appears.
- **Service Category Performance:**

  | Service category | Referrals | Conversion | Leakage | Median days to schedule | Median days to first appointment |
  |---|---|---|---|---|---|
  | Behavioral Health | 17,772 | 68.3% | 29.9% | 5.0 | 24.0 |
  | Cardiology | 23,684 | 74.3% | 24.6% | 5.0 | 20.0 |
  | Dermatology | 14,745 | 69.4% | 27.3% | 5.0 | 33.0 |
  | Gastroenterology | 16,427 | 72.7% | 25.4% | 5.0 | 26.0 |
  | General Surgery | 13,164 | 75.8% | 23.4% | 5.0 | 20.0 |
  | Neurology | 14,728 | 70.6% | 27.0% | 5.0 | 31.0 |
  | Orthopedics | 25,124 | 74.0% | 24.6% | 5.0 | 23.0 |
  | Physical Therapy | 22,106 | 72.2% | 27.3% | 5.0 | 13.0 |
  | **Total** | **147,750** | **72.3%** | **26.1%** | **5.0** | **21.0** |

### Page 2: Leakage & Service Performance

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+-----------+-----------+-----------+-----------+
|  Leaked   |  Leakage  |  Delayed  |  Delayed  |   KPI cards
| Referrals |   Rate    |Scheduling |Appointment|
+-----------+-----------+-----------+-----------+
| Facility v     | Service Category v | Urgency v |   slicers
+---------------+---------------+---------------+
| Top 15        | Leakage Rate  | Monthly       |
| Providers by  | by Service    | Referrals vs  |
| Leaked        | Category (bar)| Leakage(combo)|
| Referrals     +---------------+---------------+
| (bar)         | Provider Performance (matrix) |
|               |                               |
+---------------+-------------------------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Leaked Referrals | n/a | Leaked Referrals | 0, 0, 485, 168 | `#,0` |
| 2 | Card | Leakage Rate | n/a | Leakage Rate | 485, 0, 475, 168 | `0.0%` |
| 3 | Card | Delayed Scheduling Referrals | n/a | Delayed Scheduling Referrals | 960, 0, 473, 167 | `#,0` |
| 4 | Card | Delayed Appointment Referrals | n/a | Delayed Appointment Referrals | 1433, 0, 487, 167 | `#,0` |
| 5 | Slicer (Dropdown) | `Facilities[facility_name]` | A–Z | Facility | 0, 167, 644, 76 | Filters Providers, and so every referral visual |
| 6 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service category | 644, 167, 633, 76 | |
| 7 | Slicer (Dropdown) | `Referrals[urgency]` | A–Z | Urgency | 1277, 169, 643, 76 | |
| 8 | Clustered bar chart | Y: `Providers[provider_name]`; X: Leaked Referrals | Leaked Referrals, descending | Top 15 Providers by Leaked Referrals | 0, 243, 644, 837 | Visual-level filter: **Top N = 15 by Leaked Referrals**, for readability with 132 providers. The matrix lists all providers |
| 9 | Clustered bar chart | Y: `ServiceCategories[service_category_name]`; X: Leakage Rate | Leakage Rate, descending | Leakage Rate by Service Category | 644, 243, 633, 419 | X axis `0%`–`30%`, starting at 0 |
| 10 | Line and clustered column chart | X: `Date[year_month]`; Column Y: Total Referrals; Line Y: Leaked Referrals | `year_month`, ascending | Monthly Referrals vs Leakage | 1277, 243, 643, 419 | Legend on. The line uses a **secondary Y axis** (about 2,800–3,600), so the line's height is not on the column scale |
| 11 | Matrix | Rows: `Providers[provider_name]` (header renamed *Provider Performance*); Values: Total Referrals, Leaked Referrals, Conversion Rate, Leakage Rate, Median Days to Schedule | Provider, A–Z | (none; the row header reads Provider Performance) | 643, 647, 1277, 433 | Row subtotals on; 132 rows scroll; the Total row must match the cards |

**Expected unsliced values (seed 42):**

| Card | Expected (seed 42) |
|---|---|
| Leaked Referrals | 38,594 |
| Leakage Rate | 26.1% |
| Delayed Scheduling Referrals | 6,831 |
| Delayed Appointment Referrals | 58,388 |

The charts must show these values:

- **Top 15 Providers by Leaked Referrals**, in order:

  | Provider | Leaked referrals |
  |---|---|
  | Behavioral Health Provider 075 | 709 |
  | Behavioral Health Provider 076 | 698 |
  | Behavioral Health Provider 089 | 653 |
  | Behavioral Health Provider 090 | 653 |
  | Cardiology Provider 001 | 641 |
  | Cardiology Provider 002 | 598 |
  | Cardiology Provider 077 | 595 |
  | Cardiology Provider 078 | 595 |
  | Gastroenterology Provider 066 | 594 |
  | Gastroenterology Provider 013 | 563 |
  | Physical Therapy Provider 018 | 562 |
  | Orthopedics Provider 115 | 553 |
  | Gastroenterology Provider 065 | 545 |
  | Orthopedics Provider 049 | 541 |
  | Orthopedics Provider 113 | 540 |

  The 16th provider has 535, so no tie crosses the Top 15 cut-off.
- **Leakage Rate by Service Category:**

  | Service category | Leakage rate |
  |---|---|
  | Behavioral Health | 29.9% |
  | Dermatology | 27.3% |
  | Physical Therapy | 27.3% |
  | Neurology | 27.0% |
  | Gastroenterology | 25.4% |
  | Cardiology | 24.6% |
  | Orthopedics | 24.6% |
  | General Surgery | 23.4% |

- **Monthly Referrals vs Leakage:** the values match the `total_referrals` and
  `leaked_referrals` values under `by_month`. For example, January is 13,055 / 3,385,
  October is 13,892 / 3,596 and December is 11,655 / 3,228.
- **Provider Performance:**
  - The Total row reads 147,750 / 38,594 / 72.3% / 26.1% / 5.0.
  - The first rows, A–Z, are Behavioral Health Providers 019, 020, 021, 022, 075, 076,
    089, 090 and 108. For example, Provider 019 reads 1,274 / 320 / 73.3% / 25.1% / 5.0.
  - Behavioral Health Provider 108 works at an out-of-network facility, so its Median
    Days to Schedule is blank, not 0.

### Page 3: Turnaround Time & Data Quality

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+-----------+-----------+-----------+-----------+
|Median Days|Median Days|Referrals w|Data Qual. |   KPI cards
|to 1st Con.|to Schedule| DQ Issues |Exceptions |
+-----------+-----------+-----------+-----------+
| Date |-| | Service Cat v | Provider v | Source v | Urgency v |   slicers
+---------------+---------------+---------------+
| Primary       | Referral      | Data Quality  |
| Leakage       | Outcomes by   | Exceptions by |
| Reasons       | Urgency (100% | Issue Type    |
| (funnel)      | stacked col.) | (column)      |
+---------------+---------------+---------------+
| Turnaround Time by Service    | Data Quality  |
| Category (combo)              | Resolution    |
|                               | Status (donut)|
+-------------------------------+---------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Median Days to First Contact | n/a | Median Days to First Contact | 0, 0, 485, 168 | `0.0` |
| 2 | Card | Median Days to Schedule | n/a | Median Days to Schedule | 485, 0, 475, 168 | `0.0` |
| 3 | Card | Referrals with Data Quality Issues | n/a | Referrals with Data Quality Issues | 960, 0, 473, 167 | `#,0` |
| 4 | Card | Data Quality Exceptions | n/a | Data Quality Exceptions | 1433, 0, 487, 167 | `#,0` |
| 5 | Slicer (Between) | `Date[date]` | n/a | (no header) | 0, 167, 381, 76 | |
| 6 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service Category | 381, 167, 381, 76 | Filters the Provider slicer |
| 7 | Slicer (Dropdown) | `Providers[provider_name]` | A–Z | Provider | 763, 169, 381, 76 | |
| 8 | Slicer (Dropdown) | `Referrals[referral_source]` | A–Z | Referral Source | 1144, 167, 381, 76 | Includes *Unknown* (missing sources cleaned in Phase 2) |
| 9 | Slicer (Dropdown) | `Referrals[urgency]` | A–Z | Urgency | 1526, 167, 394, 76 | |
| 10 | Funnel | Category: `Referrals[primary_leakage_reason]`; Values: Leaked Referrals | Leaked Referrals, descending | Primary Leakage Reasons | 0, 244, 644, 496 | Data labels in thousands; the bottom label shows 19.5% of the top bar. Non-leaked referrals have a blank reason and no Leaked Referrals, so no "(Blank)" step appears |
| 11 | 100% stacked column chart | X: `Referrals[urgency]`; Y: Converted Referrals, Leaked Referrals, Active Referrals | Converted Referrals, descending | Referral Outcomes by Urgency | 644, 243, 644, 497 | Data labels show each share to two decimals; legend on |
| 12 | Clustered column chart | X: `DataQualityExceptions[issue_label]`; Y: Data Quality Exceptions | Data Quality Exceptions, descending | Data Quality Exceptions by Issue Type | 1289, 244, 631, 496 | One color (blue) |
| 13 | Line and clustered column chart | X: `ServiceCategories[service_category_name]`; Column Y: Median Days to First Appointment; Line Y: Median Days to First Contact, Median Days to Schedule | Median Days to First Appointment, descending | Turnaround Time by Service Category | 0, 750, 1289, 330 | Data labels on; legend on |
| 14 | Donut chart | Legend: `DataQualityExceptions[resolution_status]`; Values: Data Quality Exceptions | Data Quality Exceptions, descending | Data Quality Resolution Status | 1289, 750, 631, 330 | Detail labels show value and percent of total; the total (11K) is in the centre |

**Expected unsliced values (seed 42):**

| Card | Expected (seed 42) |
|---|---|
| Median Days to First Contact | 1 |
| Median Days to Schedule | 5 |
| Referrals with Data Quality Issues | 10,805 |
| Data Quality Exceptions | 11,116 |

The median cards show 1.0 and 5.0.

The charts must show these values:

- **Primary Leakage Reasons, largest first:**

  | Leakage reason | Referrals | Priority |
  |---|---|---|
  | Expired Before Completion | 11,111 | 2 |
  | External Outcome Missing | 8,399 | 1 |
  | Declined Before Scheduling | 7,742 | 5 |
  | No-Show Without Successful Follow-Up | 5,233 | 4 |
  | Cancelled Without Successful Rebooking | 3,942 | 3 |
  | Not Scheduled Within 30 Days | 2,167 | 6 |
  | **Total (matches Leaked Referrals)** | **38,594** | |

  The funnel is sorted by size, not by priority. The labels round to thousands (11K,
  8K, 8K, 5K, 4K, 2K), and 2,167 is 19.5% of 11,111.
- **Referral Outcomes by Urgency:**

  | Urgency | Converted | Leaked | Active |
  |---|---|---|---|
  | Routine | 71.97% | 26.06% | 1.97% |
  | Urgent | 73.13% | 26.35% | 0.52% |
  | Stat | 73.80% | 25.98% | 0.22% |

  These round to the Conversion and Leakage Rates under `by_urgency` in
  `expected_kpis.json`.
- **Data Quality Exceptions by Issue Type:**

  | Issue type | Exceptions |
  |---|---|
  | Missing referral source | 2,955 |
  | Duplicate referral record | 2,250 |
  | Missing first-contact date | 2,216 |
  | Missing closed date | 1,478 |
  | Missing receiving facility | 1,478 |
  | Open referral with closed date | 739 |
  | **Total** | **11,116** |

- **Turnaround Time by Service Category:**
  - the columns match the Median Days to First Appointment column of the Page 1 matrix,
    from Dermatology (33.0) down to Physical Therapy (13.0);
  - both lines are flat, at 1.0 (first contact) and 5.0 (schedule) for every category.
- **Data Quality Resolution Status:** Unresolved 6,649 (59.81%) and Resolved 4,467
  (40.19%), a total of 11,116.

## Step 10: Test the report

These are the test steps for Power BI Desktop. The
[verification checklist](POWER_BI_VERIFICATION_CHECKLIST.md) records which results
have been verified, and how.

1. **No slicer selections.** Every card matches `expected_kpis.json`, and every matrix
   Total row matches the cards.
2. **Test every slicer** on every page. Pick one value, check that the visuals change,
   then clear it.
3. **Service Category filters Provider.** On Page 1, select *Cardiology*. The Provider
   slicer must list only Cardiology providers, and the cards must show the Cardiology
   figures: 23,684 referrals, 74.3% conversion and 24.6% leakage.
4. **Facility filters through Providers.** On Page 2, select one facility. The cards and
   all four charts change, and the Provider Performance matrix lists only that
   facility's providers.
5. **Ordering.** Monthly axes run Jan 2025 → Dec 2025.
6. **Blank behavior.** Select an out-of-network provider, such as Behavioral Health
   Provider 108.
   - External referrals have no internal appointments, so on Page 1 the Median Days to
     Schedule and Median Days to First Appointment cards show "(Blank)", not 0. This is
     expected.
   - In the Page 2 Provider Performance matrix, that provider's Median Days to Schedule
     is blank.
   - No visual may show an error.
7. **Conversion plus leakage.** With no filters, the two rates add up to 98.4%, not
   100%. The remaining 1.6% is the 2,292 active referrals.

## Step 11: Save and take screenshots (completed)

1. All slicers were cleared, and the report was saved as
   `powerbi/healthcare_referral_leakage_dashboard.pbix`.
2. One full-page screenshot was taken of each page with no slicer selections, using
   **View > Fit to page**. The images are about 1,350 × 755 px, which is close to 16:9.
3. The images are saved with lower-case `.png` extensions, because Git and GitHub treat
   file names as case-sensitive:
   - `screenshots/powerbi_referral_overview.png`
   - `screenshots/powerbi_leakage_service_performance.png`
   - `screenshots/powerbi_turnaround_data_quality.png`
4. The verification checklist has been completed.

To retake a screenshot after a change, clear every slicer, use **View > Fit to page**,
capture the page with **Windows key + Shift + S** (Snipping Tool), and save it under the
same name.

## Design reused from the earlier portfolio dashboard

The page design follows the author's earlier healthcare dashboard, so the two portfolio
projects look consistent. No data, measures, values or report file were copied.

**Reused:**
- **Palette and theme structure:** primary blue `#2F6DB5`, teal `#1A8A7D`, orange
  `#D97B29`, light blue `#7FA7D9` and navy `#1B2A41` titles.
- **Text:** Segoe UI and Segoe UI Semibold, at the same sizes (callout 24, titles 12,
  labels 10).
- **Visual style:** white visuals on a `#F4F6F8` page, with no borders or shadows.
- **Page size:** a custom 1920 × 1080 canvas (16:9), set manually on each page, with
  Fit to page.
- **Page structure:**
  - a full-width KPI card row at the top;
  - a full-width slicer row below it;
  - visuals tiled edge to edge below the slicers.

**Adapted for this project:**
- **Content:** page titles, slicers, all measures and all chart content are specific to
  referral leakage.
- **Card counts:** Page 1 uses six cards, and Pages 2 and 3 use four.
- **Charts:** a donut and a funnel replace bar charts where they read more clearly.
