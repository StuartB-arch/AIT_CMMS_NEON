# KPI Dashboard System - User Guide

## Overview

The KPI Dashboard System is a comprehensive management tool integrated into the AIT CMMS application. It provides managers with the ability to track, calculate, and report on 17 key performance indicators (KPIs) defined in the 2025 KPI framework.

## Access Control

**IMPORTANT:** The KPI Dashboard is **ONLY visible to users with Manager role**. Technicians will not see this tab.

- ✅ **Managers**: Full access to KPI Dashboard
- ❌ **Technicians**: No access to KPI data

## Features

### 1. **KPI Overview Dashboard**
- View all 17 KPIs at a glance
- Color-coded status indicators:
  - 🟢 **Green** = Passing (meets acceptance criteria)
  - 🔴 **Red** = Failing (does not meet criteria)
  - 🟡 **Yellow** = Pending data input
- Summary cards showing:
  - Total KPIs tracked
  - Number passing
  - Number failing
  - Number pending data input

### 2. **Automatic KPI Calculations**

The following KPIs are **automatically calculated** from the CMMS database:

| KPI Name | Calculation Source | Formula |
|----------|-------------------|---------|
| **Preventive Maintenance Adherence** | PM Schedules & Completions | (Completed PMs / Scheduled PMs) × 100% |
| **WO Opened vs Closed** | Corrective Maintenance records | Count of open vs closed CMs |
| **WO Backlog** | Open CMs | Total open CMs / CMs raised in month |
| **WO Age Profile** | CM age tracking | Number of CMs over 60 days old |

### 3. **Manual Data Input**

The following KPIs require **manual data entry** each month:

1. **FR1 (Injury Frequency Rate)**
   - Accident count (sick leave > 24h)
   - Hours worked
   - Formula: (Accidents / Hours) × 1,000,000

2. **Near Miss**
   - Number of near miss reports

3. **TTR (Time to Repair) Adherence**
   - P1/P2 assets fixed within target time
   - Total P1/P2 asset failures

4. **MTBF (Mean Time Between Failure)**
   - Operating hours for P1/P2 assets
   - Failure counts

5. **Technical Availability Adherence**
   - P1 assets meeting >95% availability
   - Total P1 assets

6. **MRT (Mean Response Time)**
   - Total response time in minutes
   - Number of work orders

7. **Non-Conformances Raised**
   - Count of NCs raised

8. **Non-Conformances Closed**
   - NCs closed on time
   - Total NCs due

9. **Mean Time to Deliver a Quote**
   - Total quote delivery time (hours)
   - Number of quotes

10. **Purchaser Satisfaction**
    - Satisfaction score (0-100)

11. **Top Breakdown Analysis**
    - Text field for Pareto analysis

12. **Purchaser Monthly Process Confirmation**
    - Confirmation score percentage

## How to Use

### Step 1: Access the KPI Dashboard

1. Log in to AIT CMMS as a **Manager**
2. Navigate to the **"📊 KPI Dashboard"** tab
3. Click **"Open KPI Dashboard"** button

### Step 2: Select Measurement Period

1. Use the period dropdown to select the month you want to view/update
2. The dashboard defaults to the current month

### Step 3: Calculate Automatic KPIs

1. Click **"📊 Calculate Auto KPIs"** button
2. The system will:
   - Calculate PM Adherence from schedules
   - Calculate WO statistics from CM records
   - Calculate WO backlog and age profile
   - Save results to database

### Step 4: Enter Manual Data

1. Go to the **"📝 Manual Data Input"** tab
2. Select a KPI from the dropdown
3. The form will show:
   - KPI description and formula
   - Target/acceptance criteria
   - Input fields for required data
4. Enter the data values
5. Click **"💾 Save Data"**
6. Click **"🧮 Calculate KPI"** to compute the result

### Step 5: Export Reports

1. Go to the **"📄 Export Reports"** tab
2. Select export period:
   - Current Period
   - Last 3 Months
   - Last 6 Months
   - Last 12 Months
3. Choose export format:
   - **📄 Export to PDF** - Professional report for presentations
   - **📊 Export to Excel** - Spreadsheet for further analysis

## KPI Definitions

### Function F1 - Safety

| KPI | Description | Target |
|-----|-------------|--------|
| FR1 | Injury frequency rate | 0 |
| Near Miss | Near miss reporting | Track monthly |

### Function F2.1 - Maintenance Performance

| KPI | Description | Target |
|-----|-------------|--------|
| TTR Adherence | Time to repair adherence | P1 <2h, P2 <4h, P3 <10h, P4 <24h |
| MTBF | Mean time between failure | P1 >80h, P2 >40h |
| Technical Availability | Asset availability % | P1 >95% |
| MRT | Mean response time | P1 <15min, P2 <1h, P3 <3h, P4 <4h |
| WO Opened vs Closed | Work order balance | ≤40 open WOs |
| WO Backlog | Open work orders | <10% of monthly WOs |
| WO Age Profile | Age of open WOs | None >60 days |

### Function F2.2 - Preventive Maintenance

| KPI | Description | Target |
|-----|-------------|--------|
| PM Adherence | PM completion rate | >95% |

### Function F4 - Quality & Satisfaction

| KPI | Description | Target |
|-----|-------------|--------|
| Top Breakdown | Breakdown analysis | Pareto tracking |
| Monthly Confirmation | Process confirmation | >90% |
| Purchaser Satisfaction | Customer satisfaction | High score |
| NC Raised | Non-conformances raised | 0 |
| NC Closed | NC closure rate | 100% on time |

### Function F7.1 - Response Time

| KPI | Description | Target |
|-----|-------------|--------|
| Quote Delivery Time | Time to deliver quote | <48 hours |

## Database Structure

The KPI system uses four database tables:

1. **kpi_definitions** - KPI metadata and formulas
2. **kpi_manual_data** - Manual data inputs by period
3. **kpi_results** - Calculated KPI values and status
4. **kpi_exports** - Export history tracking

## Monthly Workflow

### Recommended Monthly Process:

**Week 1 of New Month:**
1. Review previous month's KPI results
2. Export previous month to PDF for records
3. Identify areas needing improvement

**Week 2:**
1. Collect manual data from operations:
   - Safety records (accidents, near misses)
   - Response times
   - Non-conformances
   - Customer satisfaction surveys
2. Enter manual data into dashboard

**Week 3:**
1. Calculate all KPIs (auto + manual)
2. Review results for completeness
3. Verify calculations are correct

**Week 4:**
1. Generate final reports
2. Export to PDF for management review
3. Export to Excel for trending analysis
4. Present results in management meeting

## Troubleshooting

### Dashboard Won't Open

**Issue:** "KPI Dashboard requires PyQt5" error

**Solution:**
```bash
pip install PyQt5
```

### Missing Auto-Calculated KPIs

**Issue:** Some KPIs show "Pending Data"

**Possible Causes:**
- No PM schedules created for the period
- No corrective maintenance records for the period
- Database not initialized properly

**Solution:**
1. Ensure PM schedules are generated for the month
2. Check that CMs are being entered
3. Click "Calculate Auto KPIs" again

### Manual KPI Won't Calculate

**Issue:** "No manual data entered for this period" error

**Solution:**
1. Go to Manual Data Input tab
2. Select the KPI
3. Enter ALL required fields
4. Click Save Data
5. Then click Calculate KPI

### Export Fails

**Issue:** PDF or Excel export produces error

**Possible Causes:**
- No data for selected period
- File permissions issue

**Solution:**
1. Ensure KPIs are calculated for the period
2. Choose a writable location
3. Close any open files with the same name

## Technical Details

### File Structure

```
AIT_CMMS_NEON/
├── kpi_database_migration.py   # Database schema and migration
├── kpi_manager.py               # KPI calculation engine
├── kpi_ui.py                    # PyQt5 dashboard interface
├── KPI_2025.xlsx                # Original KPI definitions
├── test_kpi_system.py           # Test script
└── AIT_CMMS_REV3.py            # Main app (KPI integration)
```

### Dependencies

- **PyQt5** - Dashboard UI
- **reportlab** - PDF generation
- **openpyxl** - Excel export
- **psycopg2** - PostgreSQL database
- **datetime** - Date handling

### Database Tables

All tables are created automatically on first manager login.

## Support

For issues or questions:
1. Check this README first
2. Review the KPI_2025.xlsx file for formula details
3. Run test_kpi_system.py to verify database setup
4. Check database connection settings

## Version History

- **v1.0** (2025) - Initial release
  - 17 KPIs from 2025 framework
  - Automatic and manual calculations
  - PDF and Excel export
  - Manager-only access control

---

**© 2025 AIT CMMS - Computerized Maintenance Management System**
