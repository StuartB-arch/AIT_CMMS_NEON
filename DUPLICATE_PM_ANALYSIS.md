# DUPLICATE PM GENERATION ANALYSIS

## Date: October 28, 2025
## Issue: PMs are being generated multiple times, even for equipment completed last week

---

## FINDINGS FROM DATABASE ANALYSIS

### Evidence of Duplicates

1. **Multiple schedules for same equipment across weeks:**
   - BFM 20243323: Scheduled 3 times (weeks 9/22, 9/29, 10/13) - NEVER completed
   - BFM 20245033: Scheduled 3 times (weeks 9/22, 9/29, 10/13) - Completed on 10/13
   - Found 10+ Monthly PMs with duplicate schedules

2. **Equipment scheduled despite PM type being DISABLED:**
   - BFM 20243323: monthly_pm = 0 (disabled) but was scheduled anyway

3. **No prevention of re-scheduling uncompleted PMs:**
   - Equipment scheduled in week 9/22 (not completed) → scheduled again in 9/29 → scheduled again in 10/13

---

## ROOT CAUSES

### **CRITICAL BUG #1: No Check for Existing Uncompleted Schedules**

**Location:** `generate_weekly_schedule()` lines 641-727

**Problem:**
- When generating a new week's schedule, the system does NOT check if equipment is already scheduled in a PREVIOUS week with status='Scheduled' (uncompleted)
- This causes equipment to be scheduled week after week, creating massive backlogs

**Example:**
```
Week 1: BFM 20243323 scheduled → technician doesn't complete it
Week 2: System schedules BFM 20243323 AGAIN (doesn't see week 1's uncompleted schedule)
Week 3: System schedules BFM 20243323 AGAIN (doesn't see week 1 or 2's uncompleted schedules)
```

**Fix Required:**
Add check for uncompleted schedules from previous weeks in eligibility checker.

---

### **CRITICAL BUG #2: Schedule Deletion Happens BEFORE Validation**

**Location:** `generate_weekly_schedule()` lines 658-662

**Problem:**
```python
# Line 658-662: Deletes ALL schedules for the week
cursor.execute(
    'DELETE FROM weekly_pm_schedules WHERE week_start_date = %s',
    (week_start_str,)
)

# Line 683: Loads scheduled PMs AFTER deletion (cache is empty!)
self.completion_repo.bulk_load_scheduled(week_start)

# Line 320-322: Checks "already scheduled" but cache was loaded AFTER deletion
scheduled_pms = self.completion_repo.get_scheduled_pms(week_start, equipment.bfm_no)
if any(s['pm_type'] == pm_type.value for s in scheduled_pms):
    return PMEligibilityResult(PMStatus.CONFLICTED, f"Already scheduled for this week")
```

**Result:** The "already scheduled" check is completely ineffective because the schedule was deleted before checking.

**Fix Required:**
- Load scheduled PMs BEFORE deletion
- Warn user if regenerating a week with completed PMs
- Consider UPDATE instead of DELETE+INSERT

---

### **CRITICAL BUG #3: No Safeguard Against Re-Generating Completed Weeks**

**Problem:**
If a user accidentally clicks "Generate Weekly Schedule" for a week that already has COMPLETED PMs:
1. System deletes ALL schedules (including completed ones)
2. System checks if equipment is eligible based on pm_completions
3. Equipment that was completed in that week may be scheduled again if enough time has passed

**Fix Required:**
Add warning dialog before regenerating weeks with completions.

---

### **BUG #4: The 30-Day Minimum Interval May Not Catch Same-Week Duplicates**

**Location:** `_check_due_date()` lines 366-446, `_get_minimum_interval()` lines 327-332

**Current Logic:**
```python
min_interval = 30  # Monthly PMs: minimum 30 days between completions
if days_since < min_interval:
    return PMEligibilityResult(PMStatus.RECENTLY_COMPLETED, ...)
```

**Problem:**
- If equipment completed on Monday (day 1 of week)
- And user regenerates schedule on Friday (day 5 of week)
- Only 4 days have passed, so it SHOULD be blocked
- BUT if pm_completions table was not updated, eligibility checker uses equipment table
- Equipment table's last_monthly_pm might be from PREVIOUS month

**Fix Required:**
Ensure pm_completions table is ALWAYS used as source of truth.

---

## BUSINESS REQUIREMENTS (from user)

1. **PM Generation Order:**
   - First schedule P1, P2, P3 assets based on last date of inspection
   - Then generate PMs for rest of assets ONLY IF P1/P2/P3 monthly AND annuals completed

2. **No Duplicates:**
   - Each asset should only be scheduled ONCE until completed
   - Cannot schedule same PM type twice within minimum interval (30 days monthly, 365 days annual)

3. **CANNOT FINDS have NO PM schedules:**
   - Equipment with status='Missing' must be excluded
   - Equipment in cannot_find_assets table must be excluded

4. **Each asset has EITHER:**
   - Monthly AND Annual PM, OR
   - Just Annual PM

---

## CURRENT vs REQUIRED BEHAVIOR

### Current (BUGGY):
1. User clicks "Generate Weekly Schedule" for week 10/13
2. System DELETES all schedules for 10/13
3. System checks equipment eligibility
4. Equipment scheduled in week 10/6 (uncompleted) gets scheduled AGAIN for 10/13
5. Result: Equipment has 2 active schedules (10/6 and 10/13)

### Required (FIXED):
1. User clicks "Generate Weekly Schedule" for week 10/13
2. System checks if week 10/13 already has completions → warns user
3. System checks for uncompleted schedules from PREVIOUS weeks
4. Equipment already scheduled in week 10/6 (uncompleted) is SKIPPED for 10/13
5. Only equipment that needs scheduling (based on last completion date) is scheduled
6. P1/P2/P3 equipment prioritized first
7. Result: No duplicates, only one active schedule per equipment

---

## REQUIRED FIXES

### Fix #1: Add Check for Uncompleted Schedules from Previous Weeks
**File:** AIT_CMMS_REV3.py
**Function:** `PMEligibilityChecker.check_eligibility()` line 251
**Add:** Check for existing schedules with status='Scheduled' before current week

### Fix #2: Warn Before Deleting Schedules with Completions
**File:** AIT_CMMS_REV3.py
**Function:** `PMSchedulingService.generate_weekly_schedule()` line 641
**Add:** Check for completed PMs before deletion, show warning dialog

### Fix #3: Load Scheduled PMs BEFORE Deletion
**File:** AIT_CMMS_REV3.py
**Function:** `PMSchedulingService.generate_weekly_schedule()` line 683
**Move:** Bulk load scheduled PMs BEFORE the DELETE statement

### Fix #4: Add Method to Get Uncompleted Schedules
**File:** AIT_CMMS_REV3.py
**Class:** `CompletionRecordRepository`
**Add:** New method `get_uncompleted_schedules(equipment_bfm, pm_type, before_week)`

### Fix #5: Verify Business Rule - P1/P2/P3 Priority with Gating
**File:** AIT_CMMS_REV3.py
**Function:** `PMAssignmentGenerator.generate_assignments()` line 479
**Add:** Check if P1/P2/P3 monthly AND annuals are completed before scheduling others

---

## IMPLEMENTATION PLAN

1. Add new method to CompletionRecordRepository to get uncompleted schedules
2. Add check in PMEligibilityChecker for uncompleted schedules from previous weeks
3. Move bulk_load_scheduled() to BEFORE the DELETE statement
4. Add warning dialog in generate_weekly_schedule() for weeks with completions
5. Add business rule enforcement for P1/P2/P3 gating (if confirmed by user)

---

## TEST CASES

After fix, verify:
1. Equipment scheduled in week N (uncompleted) is NOT scheduled again in week N+1
2. Equipment completed in week N is NOT scheduled in week N (if regenerated)
3. Equipment completed 7 days ago is NOT scheduled (blocked by 30-day minimum)
4. Equipment with monthly_pm=0 is NEVER scheduled for monthly PM
5. P1/P2/P3 equipment is scheduled FIRST with highest priority
6. Regenerating a week with completions shows warning
7. No duplicate schedules appear in weekly_pm_schedules table
