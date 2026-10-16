# Power BI Dashboard Build Guide

> **Synthetic data only.** The dashboard shows computer-generated data. It does not
> describe real patients, providers or facilities, and it is for portfolio and educational
> use only, not for clinical decision-making. Put this notice on every page.

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

**Status:** Phase 4A (this guide and its data) is complete. The report itself is built in
Phase 4B. The `.pbix` file and the screenshots do not exist yet.

| You will use | File |
|---|---|
| Six data tables | `powerbi/data/*.csv` |
| Model specification | [POWER_BI_DATA_MODEL.md](POWER_BI_DATA_MODEL.md) |
| Column types and meanings | [DATA_DICTIONARY.md](DATA_DICTIONARY.md) |
| DAX measures (20) | [dax_measures.txt](dax_measures.txt) |
| Theme | [healthcare_referral_theme.json](healthcare_referral_theme.json) |
| Reference values | [expected_kpis.json](expected_kpis.json) |
| Report you will create (Phase 4B) | `powerbi/healthcare_referral_leakage_dashboard.pbix` |
| Screenshots you will take (Phase 4B) | `screenshots/powerbi_referral_overview.png`, `screenshots/powerbi_leakage_service_performance.png`, `screenshots/powerbi_turnaround_data_quality.png` |

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
It only supplies a palette in order. Set the outcome colors **manually** on each visual
that uses `Referrals[outcome]`, under **Format visual > Visual > Columns / Bars / Slices >
Colors**:

| Outcome | Color | Hex |
|---|---|---|
| Converted | Green | `#2E7D4F` |
| Active | Blue | `#2F6DB5` |
| Leaked | Red-orange | `#C8553D` |
| Unknown / Unclassified | Gray | `#8A939E` (no seed-42 referral is Unclassified) |

Use the same pairing wherever both series appear, such as Conversion Rate and Leakage
Rate, or Total Referrals and Leaked Referrals:
- Conversion Rate: green;
- Leakage Rate and Leaked Referrals: red-orange;
- Total Referrals: blue.

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

## Step 9: Build the three report pages

### Settings for every page

- **Canvas: custom 1920 × 1080 px on every page.** This is the same canvas as the
  earlier portfolio dashboard, and it keeps the 16:9 aspect ratio.
  - **Set it by hand on each page.** Select an empty part of the canvas, then go to
    **Format page > Canvas settings**, set **Type: Custom**, **Width: 1920** and
    **Height: 1080**, and set **Vertical alignment: Top**.
  - **New pages start at the default 16:9 size,** so repeat this for all three pages.
  - **The theme file does not set page dimensions.** It controls only colors, text and
    visual styles.
  - **View > Page view > Fit to page** shows the whole page while you build it.
- **Positions:** the positions below are *x, y, width, height* in pixels on the
  1920 × 1080 canvas. Set them under **Format > General > Properties**.
- **Grid:**
  - a 20 px margin on every side and 16 px between visuals;
  - content runs from x = 20 to x = 1900 and from y = 20 to y = 1060;
  - no visual overlaps another.
- **Layout order (top to bottom):**
  1. a full-width row of KPI cards (`y = 20`, height 140);
  2. a row of slicers (`y = 176`, height 76);
  3. the charts (`y = 268` to `y = 1016`);
  4. a one-line notice at the bottom (`y = 1032`, height 28).
- **Notice:** a text box at `20, 1032, 1880, 28` saying *"Synthetic data for a portfolio
  project. Not real patients, providers or facilities. Not for clinical use."*
- **Cards:** use the **Card** visual, with the category label on.
- **Slicers:** each page's slicers filter only that page; do not sync slicers between
  pages.
  - **Provider:** a Dropdown on `Providers[provider_name]` with search on, because there
    are 132 providers.
  - **Service Category:** a Dropdown on `ServiceCategories[service_category_name]`.
  - **Referral Date:** a *Between* slider on `Date[date]`.
  - **Multiple selections:** Provider and Service Category allow multi-select, with
    "Select all" on.
- **Interactions:** keep the default **filter** interactions. Selecting a slicer value or
  a bar filters the other visuals on the page.
  - **Service Category filters Provider.** Selecting a category shortens the Provider
    slicer list to that category's providers.
  - **Selecting a provider does not shorten the category list.** This is expected with
    single-direction relationships.
  - **The exceptions chart filters nothing else.** Clicking a bar in *Data-Quality
    Exceptions by Issue Type* filters only that chart's table. Exception filters do not
    flow back to referrals, by design.
- **Visual titles:** under *Format visual > General > Title*, type the title shown in
  the tables.
- **Sorting:** set each sort from the visual's **More options (…) > Sort axis**.
- **Matrix totals:** turn on **Row subtotals**. The Total row must match the cards.

### Page 1: Referral Overview

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+--------+--------+--------+--------+--------+--------+
| Total  |Convert-| Conv.  |Leakage | Median | Median |   KPI cards
|Referral|  ed    |  Rate  |  Rate  |Days to |Days to |
|        |        |        |        |Schedule|1st Appt|
+--------+--------+--------+--------+--------+--------+
| Provider v        | Service Category v | Date |----| |   slicers
+-------------------+---------------------------------+
| Referrals by      | Service Category KPIs (matrix)  |
| Outcome (column)  +----------------+----------------+
|                   | Referrals by   | Monthly        |
|                   | Service        | Referral       |
|                   | Category (bar) | Volume (line)  |
+-------------------+----------------+----------------+
| Synthetic-data notice                                |
+-----------------------------------------------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Total Referrals | n/a | Total Referrals | 20, 20, 300, 140 | `#,0` |
| 2 | Card | Converted Referrals | n/a | Converted Referrals | 336, 20, 300, 140 | `#,0` |
| 3 | Card | Conversion Rate | n/a | Conversion Rate | 652, 20, 300, 140 | `0.0%` |
| 4 | Card | Leakage Rate | n/a | Leakage Rate | 968, 20, 300, 140 | `0.0%` |
| 5 | Card | Median Days to Schedule | n/a | Median Days to Schedule | 1284, 20, 300, 140 | `0.0` |
| 6 | Card | Median Days to First Appointment | n/a | Median Days to First Appointment | 1600, 20, 300, 140 | `0.0` |
| 7 | Slicer (Dropdown) | `Providers[provider_name]` | A–Z | Provider | 20, 176, 616, 76 | Search on; filtered by the Service Category slicer |
| 8 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service Category | 652, 176, 616, 76 | Filters the Provider slicer |
| 9 | Slicer (Between) | `Date[date]` | n/a | Referral Date | 1284, 176, 616, 76 | Date range 2025-01-01 to 2025-12-31 |
| 10 | Clustered column chart | Y: Total Referrals; X: `Referrals[outcome]` | Total Referrals, descending | Referrals by Outcome | 20, 268, 616, 748 | Data labels `#,0`; outcome colors from Step 7 |
| 11 | Matrix | Rows: `ServiceCategories[service_category_name]`; Values: Total Referrals, Conversion Rate, Leakage Rate, Median Days to Schedule, Delayed Scheduling Referrals | Total Referrals, descending | Service Category KPIs | 652, 268, 1248, 300 | Row subtotals on (Total row) |
| 12 | Clustered bar chart | X: Total Referrals; Y: `ServiceCategories[service_category_name]` | Total Referrals, descending | Referrals by Service Category | 652, 584, 616, 432 | Data labels on; one color (blue) |
| 13 | Line chart | Y: Total Referrals; X: `Date[year_month]` | `year_month`, ascending | Monthly Referral Volume | 1284, 584, 616, 432 | Markers on; Y axis starts at 0 |

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

- **Referrals by Outcome:** Converted 106,864; Leaked 38,594; Active 2,292. The total is
  147,750. No Unclassified bar appears.
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

- **Service Category KPIs:** the rows match `by_service_category` in
  `expected_kpis.json`. Leakage Rate runs from 23.4% (General Surgery) to 29.9%
  (Behavioral Health). The Total row reads 147,750 / 72.3% / 26.1% / 5.0 / 6,831.
- **Monthly Referral Volume:** the points match `by_month`, from 13,055 in January to
  11,655 in December. October is the highest month, at 13,892.

### Page 2: Leakage and Service Performance

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+------------+------------+------------+------------+
|  Leaked    |  Leakage   |  Delayed   |  Delayed   |   KPI cards
| Referrals  |   Rate     | Scheduling |Appointment |
+------------+------------+------------+------------+
| Provider v        | Service Category v | Date |----| |   slicers
+-------------------------+---------------------------+
| Leakage Rate by         | Leakage Rate by           |
| Provider (bar, top 15)  | Service Category (bar)    |
+-------------------------+---------------------------+
| Monthly Referrals vs    | Provider Performance      |
| Leaked Referrals (combo)| (matrix)                  |
+-------------------------+---------------------------+
| Synthetic-data notice                                |
+-----------------------------------------------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Leaked Referrals | n/a | Leaked Referrals | 20, 20, 458, 140 | `#,0` |
| 2 | Card | Leakage Rate | n/a | Leakage Rate | 494, 20, 458, 140 | `0.0%` |
| 3 | Card | Delayed Scheduling Referrals | n/a | Delayed Scheduling Referrals | 968, 20, 458, 140 | `#,0` |
| 4 | Card | Delayed Appointment Referrals | n/a | Delayed Appointment Referrals | 1442, 20, 458, 140 | `#,0` |
| 5 | Slicer (Dropdown) | `Providers[provider_name]` | A–Z | Provider | 20, 176, 616, 76 | Same settings as Page 1 |
| 6 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service Category | 652, 176, 616, 76 | Same settings as Page 1 |
| 7 | Slicer (Between) | `Date[date]` | n/a | Referral Date | 1284, 176, 616, 76 | Same settings as Page 1 |
| 8 | Clustered bar chart | X: Leakage Rate; Y: `Providers[provider_name]`; Tooltips: Total Referrals, Leaked Referrals | Leakage Rate, descending | Leakage Rate by Provider | 20, 268, 932, 400 | Data labels `0.0%`; X axis starts at 0; red-orange bars. Visual-level filter: **Top N = 15 by Leakage Rate**, for readability with 132 providers. The matrix lists all providers |
| 9 | Clustered bar chart | X: Leakage Rate; Y: `ServiceCategories[service_category_name]`; Tooltips: Total Referrals, Leaked Referrals | Leakage Rate, descending | Leakage Rate by Service Category | 968, 268, 932, 400 | Data labels `0.0%`; X axis starts at 0; red-orange bars |
| 10 | Line and clustered column chart | Column Y: Total Referrals; Line Y: Leaked Referrals; X: `Date[year_month]` | `year_month`, ascending | Monthly Referrals versus Leaked Referrals | 20, 684, 932, 332 | Legend on; turn **off** the secondary Y axis so both share one scale; columns blue, line red-orange |
| 11 | Matrix | Rows: `Providers[provider_name]`; Values: Total Referrals, Converted Referrals, Leaked Referrals, Conversion Rate, Leakage Rate, Median Days to First Appointment | Leakage Rate, descending | Provider Performance | 968, 684, 932, 332 | Row subtotals on; 132 rows scroll; the Total row must match the cards |

**Expected unsliced values (seed 42):**

| Card | Expected (seed 42) |
|---|---|
| Leaked Referrals | 38,594 |
| Leakage Rate | 26.1% |
| Delayed Scheduling Referrals | 6,831 |
| Delayed Appointment Referrals | 58,388 |

The charts must show these values:

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

- **Monthly Referrals versus Leaked Referrals:** the values match the
  `total_referrals` and `leaked_referrals` values under `by_month`. For example,
  January is 13,055 / 3,385 and December is 11,655 / 3,228.
- **Provider Performance:** the Total row reads 147,750 / 106,864 / 38,594 / 72.3% /
  26.1% / 21.0.

### Page 3: Turnaround Time and Data Quality

Canvas: custom 1920 × 1080. Wireframe (1920 × 1080):

```
+------------+------------+------------+------------+
|  Active    |Median Days |Referrals w/|Referrals w/|   KPI cards
| Referrals  |to 1st Cont.| DQ Issues  | Duplicates |
+------------+------------+------------+------------+
| Date |---| | Service Cat v | Provider v | Source v | Urgency v |   slicers
+-------------------------+---------------------------+
| Leakage Reasons (bar)   | Conversion and Leakage    |
|                         | Rate by Urgency (column)  |
+----------------+--------+-------+-------------------+
| Referrals by   | Data-Quality   | Referrals by      |
| Referral Source| Exceptions by  | Insurance Type    |
| (column)       | Issue Type(bar)| (pie)             |
+----------------+----------------+-------------------+
| Synthetic-data notice                                |
+-----------------------------------------------------+
```

| # | Visual type | Fields / measures | Sort | Title | Position | Format and interaction |
|---|---|---|---|---|---|---|
| 1 | Card | Active Referrals | n/a | Active Referrals | 20, 20, 458, 140 | `#,0` |
| 2 | Card | Median Days to First Contact | n/a | Median Days to First Contact | 494, 20, 458, 140 | `0.0` |
| 3 | Card | Referrals with Data Quality Issues | n/a | Referrals with Data Quality Issues | 968, 20, 458, 140 | `#,0` |
| 4 | Card | Referrals with Duplicate Records | n/a | Referrals with Duplicate Records | 1442, 20, 458, 140 | `#,0` |
| 5 | Slicer (Between) | `Date[date]` | n/a | Referral Date | 20, 176, 364, 76 | |
| 6 | Slicer (Dropdown) | `ServiceCategories[service_category_name]` | A–Z | Service Category | 400, 176, 363, 76 | Filters the Provider slicer |
| 7 | Slicer (Dropdown) | `Providers[provider_name]` | A–Z | Provider | 779, 176, 363, 76 | Search on |
| 8 | Slicer (Dropdown) | `Referrals[referral_source]` | A–Z | Referral Source | 1158, 176, 363, 76 | Includes *Unknown* (missing sources cleaned in Phase 2) |
| 9 | Slicer (Dropdown) | `Referrals[urgency]` | A–Z | Urgency | 1537, 176, 363, 76 | |
| 10 | Clustered bar chart | X: Leaked Referrals; Y: `Referrals[primary_leakage_reason]` | `primary_leakage_reason`, ascending (sorted by priority 1–6) | Leakage Reasons | 20, 268, 932, 370 | Data labels `#,0`; red-orange bars. Non-leaked referrals have a blank reason and no Leaked Referrals, so no "(Blank)" bar appears |
| 11 | Clustered column chart | Y: Conversion Rate, Leakage Rate; X: `Referrals[urgency]` | Urgency A–Z | Conversion and Leakage Rate by Urgency | 968, 268, 932, 370 | Data labels `0.0%`; Conversion green, Leakage red-orange; legend on |
| 12 | Clustered column chart | Y: Total Referrals; X: `Referrals[referral_source]` | Total Referrals, descending | Referrals by Referral Source | 20, 654, 616, 362 | Data labels on; blue |
| 13 | Clustered bar chart | X: Data Quality Exceptions; Y: `DataQualityExceptions[issue_label]` | Data Quality Exceptions, descending | Data-Quality Exceptions by Issue Type | 652, 654, 616, 362 | Data labels `#,0`. Clicking a bar filters only this visual's table |
| 14 | Pie chart | Values: Total Referrals; Legend: `Referrals[insurance_type]` | Total Referrals, descending | Referrals by Insurance Type | 1284, 654, 616, 362 | Detail labels: category and percent of total |

**Expected unsliced values (seed 42):**

| Card | Expected (seed 42) |
|---|---|
| Active Referrals | 2,292 |
| Median Days to First Contact | 1 |
| Referrals with Data Quality Issues | 10,805 |
| Referrals with Duplicate Records | 2,250 |

The charts must show these values:

- **Leakage Reasons, in priority order:**

  | Leakage reason | Referrals |
  |---|---|
  | External Outcome Missing | 8,399 |
  | Expired Before Completion | 11,111 |
  | Cancelled Without Successful Rebooking | 3,942 |
  | No-Show Without Successful Follow-Up | 5,233 |
  | Declined Before Scheduling | 7,742 |
  | Not Scheduled Within 30 Days | 2,167 |
  | **Total (matches Leaked Referrals)** | **38,594** |

- **Conversion and Leakage Rate by Urgency:**

  | Urgency | Conversion rate | Leakage rate |
  |---|---|---|
  | Routine | 72.0% | 26.1% |
  | Stat | 73.8% | 26.0% |
  | Urgent | 73.1% | 26.4% |

- **Referrals by Referral Source:**

  | Referral source | Referrals |
  |---|---|
  | Primary Care | 63,366 |
  | Specialist | 26,115 |
  | Emergency Department | 17,355 |
  | Hospital Discharge | 14,556 |
  | Urgent Care | 13,090 |
  | Patient Portal | 10,313 |
  | Unknown | 2,955 |

- **Data-Quality Exceptions by Issue Type:**

  | Issue type | Exceptions |
  |---|---|
  | Missing referral source | 2,955 |
  | Duplicate referral record | 2,250 |
  | Missing first-contact date | 2,216 |
  | Missing receiving facility | 1,478 |
  | Missing closed date | 1,478 |
  | Open referral with closed date | 739 |
  | **Total** | **11,116** |

- **Referrals by Insurance Type:**

  | Insurance type | Referrals |
  |---|---|
  | Commercial | 70,501 |
  | Medicare | 38,441 |
  | Medicaid | 27,146 |
  | Self-Pay | 11,662 |

## Step 10: Test the report

Record each result in
[POWER_BI_VERIFICATION_CHECKLIST.md](POWER_BI_VERIFICATION_CHECKLIST.md).

1. **No slicer selections.** Every card matches `expected_kpis.json`, and every matrix
   Total row matches the cards.
2. **Test every slicer** on every page. Pick one value, check that the visuals change,
   then clear it.
3. **Service Category filters Provider.** Select *Cardiology*. The Provider slicer must
   list only Cardiology providers, and the cards must show the Cardiology figures:
   23,684 referrals, 74.3% conversion and 24.6% leakage.
4. **Ordering.**
   - Monthly axes run Jan 2025 → Dec 2025.
   - Leakage reasons run in priority order 1 → 6.
5. **Blank behavior.** On Page 2, select a provider at one of the two out-of-network
   facilities.
   - In the Provider Performance matrix, these are the providers whose Median Days to
     First Appointment is blank.
   - External referrals have no internal appointments, so on Page 1 the Median Days to
     Schedule and Median Days to First Appointment cards show "(Blank)" for that
     provider, not 0. This is expected.
   - No visual may show an error.
6. **Conversion plus leakage.** With no filters, the two rates add up to 98.4%, not
   100%. The remaining 1.6% is the 2,292 active referrals.

## Step 11: Save and take screenshots (Phase 4B)

1. Clear every slicer, then save the report as
   `powerbi/healthcare_referral_leakage_dashboard.pbix`.
2. Take one full-page screenshot of each page with no slicer selections:
   - first use **View > Fit to page**;
   - capture with **Windows key + Shift + S** (Snipping Tool).
3. Save the images as:
   - `screenshots/powerbi_referral_overview.png`
   - `screenshots/powerbi_leakage_service_performance.png`
   - `screenshots/powerbi_turnaround_data_quality.png`
4. Complete the verification checklist.

Only report the dashboard as complete once the `.pbix` file and the three screenshots
exist and the checklist is complete.

## Design reused from the earlier portfolio dashboard

The page design follows the author's earlier healthcare dashboard, so the two portfolio
projects look consistent. No data, measures, values or report file were copied.

**Reused:**
- **Palette and theme structure:** primary blue `#2F6DB5`, teal `#1A8A7D`, orange
  `#D97B29`, light blue `#7FA7D9` and navy `#1B2A41` titles.
- **Text:** Segoe UI and Segoe UI Semibold, at the same sizes (callout 24, titles 12,
  labels 10).
- **Visual style:** white visuals on a `#F4F6F8` page, with no borders or shadows.
- **Page size:** a custom 1920 × 1080 canvas (16:9), set manually on each page.
- **Page structure:**
  - a full-width KPI card row at the top;
  - a slicer row with two dropdowns on the left and a date-range slider on the right
    (Pages 1–2);
  - a five-slicer row on Page 3.
- **Per-page layouts:**
  - **Page 1:** a tall chart on the left, with a matrix above two charts on the right.
  - **Page 2:** two bar charts above a monthly combo chart and a matrix.
  - **Page 3:** two charts above three.

**Adapted for this project:**
- **Status colors:** these replace the earlier ones. Converted is green `#2E7D4F`, Active
  is blue, Leaked is red-orange `#C8553D`, and Unclassified is gray `#8A939E`. The green
  and red-orange are also the theme's `good` and `bad` colors.
- **Content:** page titles, slicers (Provider, Service Category, Referral Date, Referral
  Source, Urgency), all measures and all chart content are specific to referral leakage.
- **Card counts:** Pages 2 and 3 use four cards and Page 1 uses six.
