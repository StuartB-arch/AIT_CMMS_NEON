# Quick Reference: Manual KPI Data Entry for October 2025

## How to Enter Each KPI

### 1. FR1 - Injury Frequency Rate (F1)
**Go to:** Manual Data Input → Select "FR1"
**Enter:**
- Number of Accidents (sick leave > 24h): `0` (or actual number)
- Number of Hours Worked: `10000` (estimate: ~40 hours/week × 4 weeks × 60 employees)

**Formula:** (Accidents / Hours) × 1,000,000
**Target:** 0 accidents

---

### 2. Near Miss (F1)
**Go to:** Manual Data Input → Select "Near Miss"
**Enter:**
- Number of Near Miss Reports: `5` (or actual number of reports filed)

**Target:** Track monthly (no specific number, but more is better for safety culture)

---

### 3. TTR (Time to Repair) Adherence (F2.1)
**Go to:** Manual Data Input → Select "TTR (Time to Repair) Adherence"
**Enter:**
- P1 Assets Fixed Within 2 Hours: `8`
- Total P1 Asset Failures: `10`
- P2 Assets Fixed Within 4 Hours: `15`
- Total P2 Asset Failures: `18`

**Formula:** (Fixed within target / Total failures) × 100%
**Target:** P1 <2h, P2 <4h, P3 <10h, P4 <24h

---

### 4. MTBF - Mean Time Between Failure (F2.1)
**Go to:** Manual Data Input → Select "MTBF Mean Time Between Failure"
**Enter:**
- P1 Assets Total Operating Hours: `720` (hours in October)
- P1 Assets Failure Count: `8`
- P2 Assets Total Operating Hours: `720`
- P2 Assets Failure Count: `15`

**Formula:** Operating Hours / Failure Count
**Target:** P1 >80 hours, P2 >40 hours

---

### 5. Technical Availability Adherence (F2.1)
**Go to:** Manual Data Input → Select "Technical Availability Adherence"
**Enter:**
- P1 Assets Meeting >95% Availability: `12`
- Total P1 Assets: `15`

**Formula:** (Assets meeting target / Total assets) × 100%
**Target:** >95% for P1 Critical Assets

---

### 6. MRT - Mean Response Time (F2.1)
**Go to:** Manual Data Input → Select "MRT (Mean Response Time)"
**Enter:**
- Total Response Time (minutes): `360` (sum of all response times)
- Number of Work Orders: `54` (use your October opened count)

**Formula:** Total time / WO count = Average
**Target:** P1 <15min, P2 <1h, P3 <3h, P4 <4h

---

### 7. Non-Conformances Raised (All Functions)
**Go to:** Manual Data Input → Select "Non Conformances raised"
**Enter:**
- Number of Non-Conformances Raised: `2` (or actual NC count)

**Target:** 0 (fewer is better)

---

### 8. Non-Conformances Closed (All Functions)
**Go to:** Manual Data Input → Select "Non Conformances closed"
**Enter:**
- Non-Conformances Closed On Time: `2`
- Total Non-Conformances Due: `2`

**Formula:** (Closed on time / Total due) × 100%
**Target:** 100% closed in contractual timeframe

---

### 9. Mean Time to Deliver a Quote (F7.1)
**Go to:** Manual Data Input → Select "Mean Time to Deliver a Quote"
**Enter:**
- Total Quote Delivery Time (hours): `96` (sum of all quote times)
- Number of Quotes Requested: `4`

**Formula:** Total hours / Quote count
**Target:** <48 hours by criticality

---

### 10. Purchaser Satisfaction (F4)
**Go to:** Manual Data Input → Select "Purchaser satisfaction"
**Enter:**
- Satisfaction Score (0-100): `92` (from survey results)

**Target:** High score (typically >90%)
**Frequency:** Quarterly survey

---

### 11. Monthly Process Confirmation (F4.3)
**Go to:** Manual Data Input → Select "Purchaser Monthly process Confirmation"
**Enter:**
- Confirmation Score (%): `95` (from monthly go-look-see audit)

**Formula:** Score from routine inspection
**Target:** >90% with all actions tracked and resolved within 1 week

---

### 12. Top Breakdown Analysis (F4.2)
**Go to:** Manual Data Input → Select "Top Breakdown"
**Enter:**
- Breakdown Analysis (Pareto): `Top failures: Pump bearing (8), Motor overload (5), Valve leak (3)`

**Target:** Pareto of failure on critical assets
**This is text entry** - describe your top recurring issues

---

## 📋 **Quick Data Entry Workflow**

For each KPI above:

1. **Go to KPI Dashboard** → Manual Data Input tab
2. **Select the KPI** from dropdown
3. **Review the KPI description and formula** (auto-displayed)
4. **Enter the required data** in the fields
5. **Click "Save Data"**
6. **Click "Calculate KPI"**
7. **Move to next KPI**

---

## ⚡ **Fastest Way to Complete All KPIs**

### Option 1: Use Sample Data (For Testing)
Use the sample numbers I provided above to quickly populate all KPIs and see the dashboard fully populated.

### Option 2: Use Real Data
Gather actual data from:
- Safety records (FR1, Near Miss)
- Maintenance logs (TTR, MTBF, MRT)
- Asset tracking (Technical Availability)
- Quality reports (Non-Conformances)
- Customer surveys (Satisfaction)

---

## 🎯 **What Happens After You Enter Data**

After entering data for each KPI and clicking "Calculate":

1. ✅ KPI appears in the **Overview** tab
2. ✅ Shows calculated value
3. ✅ Shows **Pass/Fail** status (green/red)
4. ✅ Counts toward your "Total KPIs" summary
5. ✅ Can be exported to PDF/Excel

---

## 📊 **Expected Final Dashboard**

After entering all 13 manual KPIs, your Overview tab will show:

```
Total KPIs: 17
Passing: 15  (example)
Failing: 2   (example)
Pending Data: 0
```

Plus a table with all 17 KPIs showing their calculated values and pass/fail status.

---

## 💡 **Pro Tips**

1. **Start with the easiest ones:**
   - FR1 (just 2 numbers)
   - Near Miss (1 number)
   - NC Raised/Closed (2-3 numbers)

2. **Group by data source:**
   - Safety KPIs: FR1, Near Miss
   - Maintenance KPIs: TTR, MTBF, MRT, Technical Availability
   - Quality KPIs: Non-Conformances
   - Customer KPIs: Satisfaction, Monthly Confirmation

3. **Use estimates if exact data unavailable:**
   - Better to have estimated KPIs than none
   - You can update with real data later

4. **Save as you go:**
   - Data is saved to database immediately
   - Can come back and calculate later

---

**Ready to start entering data? Let me know if you want me to walk you through any specific KPI!** 🚀
