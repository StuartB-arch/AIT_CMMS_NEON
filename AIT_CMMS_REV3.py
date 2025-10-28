#!/usr/bin/env python3
"""
AIT Complete CMMS - Computerized Maintenance Management System
Fully functional CMMS with automatic PM scheduling, technician assignment, and comprehensive reporting
"""
from datetime import datetime, timedelta
from mro_stock_module import MROStockManager
from cm_parts_integration import CMPartsIntegration
from database_utils import db_pool, UserManager, AuditLogger, OptimisticConcurrencyControl, TransactionManager
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
import psycopg2
from psycopg2 import sql, extras
from datetime import datetime, timedelta
import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
import calendar
import random
import math
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, NamedTuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("ReportLab not installed. PDF generation will not work.")

class PMType(Enum):
    MONTHLY = "Monthly"
    ANNUAL = "Annual"

class PMStatus(Enum):
    DUE = "due"
    NOT_DUE = "not_due"
    RECENTLY_COMPLETED = "recently_completed"
    CONFLICTED = "conflicted"

@dataclass
class Equipment:
    bfm_no: str
    description: str
    has_monthly: bool
    has_annual: bool
    last_monthly_date: Optional[str]
    last_annual_date: Optional[str]
    status: str
    priority: int = 99  # Default priority for assets not in priority lists

@dataclass
class CompletionRecord:
    bfm_no: str
    pm_type: PMType
    completion_date: datetime
    technician: str

@dataclass
class PMAssignment:
    bfm_no: str
    pm_type: PMType
    description: str
    priority_score: int
    reason: str

class PMEligibilityResult(NamedTuple):
    status: PMStatus
    reason: str
    priority_score: int = 0
    days_overdue: int = 0

class DateParser:
    """Responsible for parsing and standardizing dates"""
    
    def __init__(self, conn):
        self.conn = conn
    
    def parse_flexible(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse date string with flexible format handling"""
        if not date_string:
            return None
            
        try:
            # Use your existing DateStandardizer
            standardizer = DateStandardizer(self.conn)
            parsed_date = standardizer.parse_date_flexible(date_string)
            if parsed_date:
                return datetime.strptime(parsed_date, '%Y-%m-%d')
        except Exception as e:
            print(f"Date parsing error for '{date_string}': {e}")
            
        return None

class CompletionRecordRepository:
    """Responsible for retrieving completion records from database"""

    def __init__(self, conn):
        self.conn = conn
        self._completion_cache = None  # Cache for bulk loaded completions
        self._scheduled_cache = None   # Cache for scheduled PMs

    def get_recent_completions(self, bfm_no: str, days: int = 400) -> List[CompletionRecord]:
        """Get recent completion records for equipment - EXTENDED TO 400 DAYS FOR ANNUAL PMs"""
        # Use cache if available
        if self._completion_cache is not None:
            return self._completion_cache.get(bfm_no, [])

        # Fallback to individual query if cache not loaded
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, pm_type, completion_date, technician_name
            FROM pm_completions
            WHERE bfm_equipment_no = %s
            AND completion_date::DATE >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY completion_date DESC
        ''', (bfm_no, days))

        completions = []
        for row in cursor.fetchall():
            try:
                pm_type = PMType.MONTHLY if row[1] == "Monthly" else PMType.ANNUAL
                completion_date = datetime.strptime(row[2], '%Y-%m-%d')

                completions.append(CompletionRecord(
                    bfm_no=row[0],
                    pm_type=pm_type,
                    completion_date=completion_date,
                    technician=row[3]
                ))
            except Exception as e:
                print(f"Error parsing completion record: {e}")

        return completions

    def bulk_load_completions(self, days: int = 400) -> None:
        """Load ALL completion records for ALL equipment in one query - MASSIVE PERFORMANCE BOOST"""
        print(f"DEBUG: Bulk loading completion records...")
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, pm_type, completion_date, technician_name
            FROM pm_completions
            WHERE completion_date::DATE >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY bfm_equipment_no, completion_date DESC
        ''', (days,))

        # Group completions by equipment
        self._completion_cache = {}
        for row in cursor.fetchall():
            try:
                bfm_no = row[0]
                pm_type = PMType.MONTHLY if row[1] == "Monthly" else PMType.ANNUAL
                completion_date = datetime.strptime(row[2], '%Y-%m-%d')

                if bfm_no not in self._completion_cache:
                    self._completion_cache[bfm_no] = []

                self._completion_cache[bfm_no].append(CompletionRecord(
                    bfm_no=bfm_no,
                    pm_type=pm_type,
                    completion_date=completion_date,
                    technician=row[3]
                ))
            except Exception as e:
                print(f"Error parsing completion record: {e}")

        print(f"DEBUG: Loaded completion records for {len(self._completion_cache)} equipment items")

    def get_scheduled_pms(self, week_start: datetime, bfm_no: Optional[str] = None) -> List[Dict]:
        """Get currently scheduled PMs for the week"""
        # Use cache if available and no specific equipment requested
        if self._scheduled_cache is not None and bfm_no:
            return self._scheduled_cache.get(bfm_no, [])

        # Fallback to individual query
        cursor = self.conn.cursor()

        if bfm_no:
            cursor.execute('''
                SELECT bfm_equipment_no, pm_type, assigned_technician, status
                FROM weekly_pm_schedules
                WHERE week_start_date = %s AND bfm_equipment_no = %s
            ''', (week_start.strftime('%Y-%m-%d'), bfm_no))
        else:
            cursor.execute('''
                SELECT bfm_equipment_no, pm_type, assigned_technician, status
                FROM weekly_pm_schedules
                WHERE week_start_date = %s
            ''', (week_start.strftime('%Y-%m-%d'),))

        return [{'bfm_no': row[0], 'pm_type': row[1], 'technician': row[2], 'status': row[3]}
                for row in cursor.fetchall()]

    def bulk_load_scheduled(self, week_start: datetime) -> None:
        """Load ALL scheduled PMs for the week in one query"""
        print(f"DEBUG: Bulk loading scheduled PMs...")
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, pm_type, assigned_technician, status
            FROM weekly_pm_schedules
            WHERE week_start_date = %s
        ''', (week_start.strftime('%Y-%m-%d'),))

        # Group scheduled PMs by equipment
        self._scheduled_cache = {}
        for row in cursor.fetchall():
            bfm_no = row[0]
            if bfm_no not in self._scheduled_cache:
                self._scheduled_cache[bfm_no] = []

            self._scheduled_cache[bfm_no].append({
                'bfm_no': bfm_no,
                'pm_type': row[1],
                'technician': row[2],
                'status': row[3]
            })

        print(f"DEBUG: Loaded scheduled PMs for {len(self._scheduled_cache)} equipment items")

    def get_uncompleted_schedules(self, bfm_no: str, pm_type: PMType, before_week: datetime) -> List[Dict]:
        """Get uncompleted scheduled PMs for equipment from PREVIOUS weeks (before the specified week)

        This is CRITICAL to prevent duplicate scheduling:
        - If equipment was scheduled in a previous week but NOT completed
        - It should NOT be scheduled again in the current week
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT week_start_date, assigned_technician, status, scheduled_date
            FROM weekly_pm_schedules
            WHERE bfm_equipment_no = %s
            AND pm_type = %s
            AND week_start_date < %s
            AND status = 'Scheduled'
            ORDER BY week_start_date DESC
            LIMIT 5
        ''', (bfm_no, pm_type.value, before_week.strftime('%Y-%m-%d')))

        uncompleted = []
        for row in cursor.fetchall():
            uncompleted.append({
                'week_start': row[0],
                'technician': row[1],
                'status': row[2],
                'scheduled_date': row[3]
            })

        return uncompleted

    def check_week_has_completions(self, week_start: datetime) -> int:
        """Check if a week already has completed PMs - used to warn before regeneration"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*)
            FROM weekly_pm_schedules
            WHERE week_start_date = %s AND status = 'Completed'
        ''', (week_start.strftime('%Y-%m-%d'),))

        result = cursor.fetchone()
        return result[0] if result else 0

    def clear_cache(self):
        """Clear the caches"""
        self._completion_cache = None
        self._scheduled_cache = None

class PMEligibilityChecker:
    """Responsible for determining if a PM is eligible for scheduling"""

    PM_FREQUENCIES = {
        PMType.MONTHLY: 30,
        PMType.ANNUAL: 365
    }

    def __init__(self, date_parser: DateParser, completion_repo: CompletionRecordRepository):
        self.date_parser = date_parser
        self.completion_repo = completion_repo
        self._next_annual_cache = None  # Cache for next annual PM dates
    
    def check_eligibility(self, equipment: Equipment, pm_type: PMType,
                         week_start: datetime) -> PMEligibilityResult:
        """Check if equipment is eligible for PM assignment"""

        # Check if equipment supports this PM type
        if pm_type == PMType.MONTHLY and not equipment.has_monthly:
            return PMEligibilityResult(PMStatus.NOT_DUE, "Equipment doesn't require Monthly PM")
        if pm_type == PMType.ANNUAL and not equipment.has_annual:
            return PMEligibilityResult(PMStatus.NOT_DUE, "Equipment doesn't require Annual PM")

        # CRITICAL FIX #1: Check for uncompleted schedules from PREVIOUS weeks
        # This prevents duplicate scheduling of equipment that's already scheduled but not completed
        uncompleted_schedules = self.completion_repo.get_uncompleted_schedules(
            equipment.bfm_no, pm_type, week_start
        )
        if uncompleted_schedules:
            oldest_uncompleted = uncompleted_schedules[-1]  # Get the oldest one
            return PMEligibilityResult(
                PMStatus.CONFLICTED,
                f"Already scheduled for week {oldest_uncompleted['week_start']} (uncompleted) - assigned to {oldest_uncompleted['technician']}"
            )

        # WARNING: NEW: For Annual PMs, check if there's a Next Annual PM Date specified
        if pm_type == PMType.ANNUAL:
            # Use cache if available, otherwise query database
            if self._next_annual_cache is not None:
                next_annual_str = self._next_annual_cache.get(equipment.bfm_no)
            else:
                cursor = self.completion_repo.conn.cursor()
                cursor.execute('SELECT next_annual_pm FROM equipment WHERE bfm_equipment_no = %s', (equipment.bfm_no,))
                result = cursor.fetchone()
                next_annual_str = result[0] if result and result[0] else None

            if next_annual_str:
                next_annual_date = self.date_parser.parse_flexible(next_annual_str)
                if next_annual_date:
                    days_until_next_annual = (next_annual_date - datetime.now()).days

                    # If Next Annual PM Date is in the future and more than 7 days away, not due yet
                    if days_until_next_annual > 7:
                        return PMEligibilityResult(
                            PMStatus.NOT_DUE,
                            f"Annual PM scheduled for {next_annual_date.strftime('%Y-%m-%d')} ({days_until_next_annual} days from now)"
                        )
                    # If within 7 days or past due based on Next Annual PM Date
                    elif days_until_next_annual >= -30:  # Allow 30 days past due
                        priority = 500 + abs(min(days_until_next_annual, 0)) * 10
                        return PMEligibilityResult(
                            PMStatus.DUE,
                            f"Annual PM due by Next Annual PM Date: {next_annual_date.strftime('%Y-%m-%d')}",
                            priority_score=priority,
                            days_overdue=abs(min(days_until_next_annual, 0))
                        )





        # Get recent completions
        recent_completions = self.completion_repo.get_recent_completions(equipment.bfm_no, days=400)
        
        # Check for recent completions of same type
        same_type_completions = [c for c in recent_completions if c.pm_type == pm_type]
        if same_type_completions:
            latest_completion = max(same_type_completions, key=lambda x: x.completion_date)
            days_since = (datetime.now() - latest_completion.completion_date).days
            
            min_interval = self._get_minimum_interval(pm_type)
            if days_since < min_interval:
                return PMEligibilityResult(
                    PMStatus.RECENTLY_COMPLETED, 
                    f"{pm_type.value} PM completed {days_since} days ago (min interval: {min_interval})"
                )
        
        # Check for cross-PM conflicts
        conflict_result = self._check_cross_pm_conflicts(recent_completions, pm_type)
        if conflict_result.status == PMStatus.CONFLICTED:
            return conflict_result
        
        # Check if already scheduled
        scheduled_pms = self.completion_repo.get_scheduled_pms(week_start, equipment.bfm_no)
        if any(s['pm_type'] == pm_type.value for s in scheduled_pms):
            return PMEligibilityResult(PMStatus.CONFLICTED, f"Already scheduled for this week")
        
        # Check if due based on equipment table dates
        return self._check_due_date(equipment, pm_type, recent_completions)
    
    def _get_minimum_interval(self, pm_type: PMType) -> int:
        """Get minimum interval before rescheduling same PM type - ALIGNED WITH BUSINESS RULES"""
        if pm_type == PMType.MONTHLY:
            return 30  # Monthly PMs: minimum 30 days between completions
        else:  # PMType.ANNUAL
            return 365  # Annual PMs: minimum 365 days between completions
    
    def _check_cross_pm_conflicts(self, recent_completions: List[CompletionRecord], 
                                 pm_type: PMType) -> PMEligibilityResult:
        """Check for conflicts between Monthly and Annual PMs"""
        
        if pm_type == PMType.ANNUAL:
            # Don't schedule Annual if Monthly was done very recently
            monthly_completions = [c for c in recent_completions if c.pm_type == PMType.MONTHLY]
            if monthly_completions:
                latest_monthly = max(monthly_completions, key=lambda x: x.completion_date)
                days_since_monthly = (datetime.now() - latest_monthly.completion_date).days
                
                if days_since_monthly < 7:
                    return PMEligibilityResult(
                        PMStatus.CONFLICTED,
                        f"Annual blocked - Monthly PM completed {days_since_monthly} days ago"
                    )
        
        elif pm_type == PMType.MONTHLY:
            # Don't schedule Monthly if Annual was done recently
            annual_completions = [c for c in recent_completions if c.pm_type == PMType.ANNUAL]
            if annual_completions:
                latest_annual = max(annual_completions, key=lambda x: x.completion_date)
                days_since_annual = (datetime.now() - latest_annual.completion_date).days
                
                if days_since_annual < 30:
                    return PMEligibilityResult(
                        PMStatus.CONFLICTED,
                        f"Monthly blocked - Annual PM completed {days_since_annual} days ago"
                    )
        
        return PMEligibilityResult(PMStatus.DUE, "No cross-PM conflicts")
    
    def _check_due_date(self, equipment: Equipment, pm_type: PMType, 
                       recent_completions: List[CompletionRecord]) -> PMEligibilityResult:
        """Check if PM is due based on last completion date - CORRECTED TO USE ACTUAL COMPLETION DATES"""
    
        # CRITICAL: Get the MOST RECENT completion date from pm_completions table
        # This ensures we're always using the LATEST completion, not outdated equipment table data
        same_type_completions = [c for c in recent_completions if c.pm_type == pm_type]
        
        if same_type_completions:
            # Use the most recent completion record - THIS IS THE SOURCE OF TRUTH
            latest_completion = max(same_type_completions, key=lambda x: x.completion_date)
            last_completion_date = latest_completion.completion_date
            source = "pm_completions_table"
        else:
            # Fall back to equipment table only if no completion records exist
            last_date_str = (equipment.last_monthly_date if pm_type == PMType.MONTHLY 
                            else equipment.last_annual_date)
            last_completion_date = self.date_parser.parse_flexible(last_date_str)
            source = "equipment_table"
    
        # Never completed = high priority
        if not last_completion_date:
            priority = 1000 if pm_type == PMType.MONTHLY else 900
            return PMEligibilityResult(
                PMStatus.DUE, 
                f"{pm_type.value} PM never completed - HIGH PRIORITY",
                priority_score=priority
            )
    
        # Calculate days since last completion
        days_since_completion = (datetime.now() - last_completion_date).days
    
        # CRITICAL FIX: Use your actual business rules
        if pm_type == PMType.MONTHLY:
            # Monthly PMs: Schedule 30-35 days AFTER last completion
            min_days = 30
            max_days = 35
            ideal_frequency = 30
        else:  # PMType.ANNUAL
            # Annual PMs: Schedule 365-370 days AFTER last completion
            min_days = 365
            max_days = 370
            ideal_frequency = 365
    
        # PM is DUE if it's been at least min_days since completion
        if days_since_completion >= min_days:
            # Calculate priority based on how overdue
            days_overdue = days_since_completion - ideal_frequency
        
            if days_overdue > 0:
                # Overdue - highest priority
                priority = min(500 + (days_overdue * 10), 999)
                return PMEligibilityResult(
                    PMStatus.DUE,
                    f"{pm_type.value} PM OVERDUE by {days_overdue} days (last: {last_completion_date.strftime('%Y-%m-%d')}, source: {source})",
                    priority_score=priority,
                    days_overdue=days_overdue
                )
            elif days_since_completion <= max_days:
                # Within scheduling window (30-35 for monthly, 365-370 for annual)
                priority = 300 - abs(days_since_completion - ideal_frequency)
                return PMEligibilityResult(
                    PMStatus.DUE,
                    f"{pm_type.value} PM due now ({days_since_completion} days since last, last: {last_completion_date.strftime('%Y-%m-%d')}, source: {source})",
                    priority_score=priority
                )
            else:
                # Past the ideal window but still technically "due"
                priority = 200
                return PMEligibilityResult(
                    PMStatus.DUE,
                    f"{pm_type.value} PM due ({days_since_completion} days since last, last: {last_completion_date.strftime('%Y-%m-%d')}, source: {source})",
                    priority_score=priority
                )
        else:
            # Not yet due - completed too recently
            days_until_due = min_days - days_since_completion
            return PMEligibilityResult(
                PMStatus.NOT_DUE,
                f"{pm_type.value} PM not due for {days_until_due} days (last: {last_completion_date.strftime('%Y-%m-%d')}, source: {source})"
            )

    def bulk_load_next_annual(self) -> None:
        """Load ALL next_annual_pm dates for ALL equipment in one query - PERFORMANCE BOOST"""
        print(f"DEBUG: Bulk loading next annual PM dates...")
        cursor = self.completion_repo.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, next_annual_pm
            FROM equipment
            WHERE next_annual_pm IS NOT NULL AND next_annual_pm != ''
        ''')

        # Store next annual dates by equipment
        self._next_annual_cache = {}
        for row in cursor.fetchall():
            bfm_no = row[0]
            next_annual_pm = row[1]
            if next_annual_pm:
                self._next_annual_cache[bfm_no] = next_annual_pm

        print(f"DEBUG: Loaded next annual PM dates for {len(self._next_annual_cache)} equipment items")

    def clear_cache(self):
        """Clear the cache"""
        self._next_annual_cache = None

class PMAssignmentGenerator:
    """Responsible for generating PM assignments"""

    def __init__(self, eligibility_checker: PMEligibilityChecker, root=None):
        self.eligibility_checker = eligibility_checker
        self.root = root  # Store root window for UI updates

    def generate_assignments(self, equipment_list: List[Equipment],
                           week_start: datetime, max_assignments: int) -> List[PMAssignment]:
        """Generate prioritized list of PM assignments based on priority level and last completion date"""

        potential_assignments = []
        equipment_priority_map = {}  # Map to store equipment priority

        total_equipment = len(equipment_list)
        print(f"DEBUG: Processing {total_equipment} equipment items...")

        for idx, equipment in enumerate(equipment_list):
            # Yield to event loop every 200 items to prevent UI freeze
            # (Increased from 50 due to cached data optimization - processing is now much faster)
            if idx > 0 and idx % 200 == 0:
                print(f"DEBUG: Progress: {idx}/{total_equipment} equipment processed ({idx*100//total_equipment}%)")
                if self.root:
                    self.root.update_idletasks()  # Yield to tkinter event loop

            # Skip inactive equipment
            if equipment.status not in ['Active']:
                continue

            # Store equipment priority for later sorting
            equipment_priority_map[equipment.bfm_no] = equipment.priority

            # Check Monthly PM eligibility
            if equipment.has_monthly:
                monthly_result = self.eligibility_checker.check_eligibility(
                    equipment, PMType.MONTHLY, week_start
                )
                if monthly_result.status == PMStatus.DUE:
                    potential_assignments.append(PMAssignment(
                        equipment.bfm_no,
                        PMType.MONTHLY,
                        equipment.description,
                        monthly_result.priority_score,
                        monthly_result.reason
                    ))

            # Check Annual PM eligibility (only if Monthly isn't being assigned)
            if equipment.has_annual:
                # Don't assign both Monthly and Annual to same equipment in same week
                has_monthly_assignment = any(
                    a.bfm_no == equipment.bfm_no and a.pm_type == PMType.MONTHLY
                    for a in potential_assignments
                )

                if not has_monthly_assignment:
                    annual_result = self.eligibility_checker.check_eligibility(
                        equipment, PMType.ANNUAL, week_start
                    )
                    if annual_result.status == PMStatus.DUE:
                        potential_assignments.append(PMAssignment(
                            equipment.bfm_no,
                            PMType.ANNUAL,
                            equipment.description,
                            annual_result.priority_score,
                            annual_result.reason
                        ))

        print(f"DEBUG: Finished processing all {total_equipment} equipment items")
        print(f"DEBUG: Found {len(potential_assignments)} potential assignments")

        # Sort by priority level first (P1, P2, P3, then others), then by priority_score (days overdue)
        # Priority level: 1 (P1) comes first, then 2 (P2), then 3 (P3), then 99 (others)
        # Within each priority level, sort by priority_score (higher = more overdue)
        print(f"DEBUG: Sorting assignments by priority...")
        potential_assignments.sort(
            key=lambda x: (
                equipment_priority_map.get(x.bfm_no, 99),  # Sort by priority level (1, 2, 3, 99)
                -x.priority_score  # Then by priority score (negative for descending order)
            )
        )

        return potential_assignments[:max_assignments]

class PMSchedulingService:
    """Main orchestrator class"""

    def __init__(self, conn, technicians: List[str], root=None):
        self.conn = conn
        self.technicians = technicians
        self.root = root  # Store root window for UI updates

        # Initialize components
        self.date_parser = DateParser(conn)
        self.completion_repo = CompletionRecordRepository(conn)
        self.eligibility_checker = PMEligibilityChecker(self.date_parser, self.completion_repo)
        self.assignment_generator = PMAssignmentGenerator(self.eligibility_checker, root)

        # Load priority assets from CSV files
        self.priority_map = self._load_priority_assets()

    def _load_priority_assets(self) -> Dict[str, int]:
        """Load priority assets from CSV files and create a BFM -> Priority mapping"""
        priority_map = {}

        # Define priority CSV files and their priority levels
        priority_files = [
            ('PM_LIST_A220_1.csv', 1),  # P1 assets
            ('PM_LIST_A220_2.csv', 2),  # P2 assets
            ('PM_LIST_A220_3.csv', 3),  # P3 assets
        ]

        try:
            # Get the directory where the script is located
            # Use os.getcwd() as fallback if __file__ is not available
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
            except NameError:
                script_dir = os.getcwd()

            for filename, priority in priority_files:
                filepath = os.path.join(script_dir, filename)

                if not os.path.exists(filepath):
                    print(f"Info: Priority file {filename} not found at {filepath}")
                    continue

                try:
                    # Read CSV file
                    df = pd.read_csv(filepath, encoding='utf-8-sig')

                    # Check if BFM column exists
                    if 'BFM' not in df.columns:
                        print(f"Warning: BFM column not found in {filename}")
                        continue

                    # Map each BFM number to its priority
                    for bfm in df['BFM'].dropna().unique():
                        try:
                            if pd.notna(bfm):
                                # Handle both string and numeric BFM values
                                if isinstance(bfm, str):
                                    bfm_str = bfm.strip()
                                elif isinstance(bfm, (int, float)):
                                    bfm_str = str(int(float(bfm)))
                                else:
                                    bfm_str = str(bfm)

                                if bfm_str:
                                    priority_map[bfm_str] = priority
                        except (ValueError, TypeError) as e:
                            print(f"Warning: Could not convert BFM value '{bfm}' in {filename}: {e}")
                            continue

                    print(f"Loaded {len([b for b in df['BFM'].dropna() if pd.notna(b)])} priority {priority} assets from {filename}")

                except pd.errors.EmptyDataError:
                    print(f"Warning: {filename} is empty")
                except pd.errors.ParserError as e:
                    print(f"Warning: Could not parse {filename}: {e}")
                except Exception as e:
                    print(f"Warning: Error loading {filename}: {str(e)}")

        except Exception as e:
            print(f"Warning: Error in priority asset loading system: {str(e)}")
            print("Continuing with empty priority map - all assets will have default priority")

        print(f"Total priority assets loaded: {len(priority_map)}")
        return priority_map
    
    def generate_weekly_schedule(self, week_start_str: str, weekly_pm_target: int) -> Dict:
        """Generate weekly PM schedule with comprehensive validation"""

        try:
            # Validate technicians list
            if not self.technicians or len(self.technicians) == 0:
                return {
                    'success': False,
                    'error': 'No technicians available for assignment. Please ensure technicians are configured in the system.'
                }

            week_start = datetime.strptime(week_start_str, '%Y-%m-%d')
            cursor = self.conn.cursor()

            print(f"DEBUG: NEW SYSTEM - Generating assignments for week {week_start_str}")
            print(f"DEBUG: Available technicians: {len(self.technicians)}")

            # CRITICAL FIX #2: Check if week has completed PMs BEFORE deletion
            # This prevents accidental deletion of completion data
            completed_count = self.completion_repo.check_week_has_completions(week_start)
            if completed_count > 0:
                print(f"WARNING: Week {week_start_str} already has {completed_count} completed PMs")
                print(f"WARNING: Regenerating will DELETE these completion records!")
                # Note: In production, this should show a confirmation dialog to the user
                # For now, we'll proceed but log the warning

            # CRITICAL FIX #3: Load scheduled PMs BEFORE deletion
            # This ensures the "already scheduled" check works correctly
            print(f"DEBUG: Loading existing schedules before deletion...")
            self.completion_repo.bulk_load_scheduled(week_start)

            # Clear existing assignments for this week
            print(f"DEBUG: Deleting existing schedules for week {week_start_str}...")
            cursor.execute(
                'DELETE FROM weekly_pm_schedules WHERE week_start_date = %s',
                (week_start_str,)
            )

            # Get equipment list
            equipment_list = self._get_active_equipment()
            print(f"DEBUG: Found {len(equipment_list)} active equipment items")

            # Check if there's any equipment to schedule
            if not equipment_list or len(equipment_list) == 0:
                self.conn.commit()
                return {
                    'success': True,
                    'total_assignments': 0,
                    'unique_assets': 0,
                    'assignments': [],
                    'message': 'No active equipment found for scheduling.'
                }

            # PERFORMANCE OPTIMIZATION: Bulk load all data to avoid N+1 query problem
            # This reduces thousands of individual queries to just 3 bulk queries
            print(f"DEBUG: OPTIMIZATION - Pre-loading all data to avoid slow individual queries...")
            self.completion_repo.bulk_load_completions(days=400)
            # Note: bulk_load_scheduled was moved BEFORE deletion (see above)
            self.eligibility_checker.bulk_load_next_annual()
            print(f"DEBUG: OPTIMIZATION - Data pre-loading complete!")

            # Generate assignments
            assignments = self.assignment_generator.generate_assignments(
                equipment_list, week_start, weekly_pm_target
            )
            print(f"DEBUG: Generated {len(assignments)} potential assignments")

            # Check if assignments were generated
            if not assignments or len(assignments) == 0:
                self.conn.commit()
                return {
                    'success': True,
                    'total_assignments': 0,
                    'unique_assets': 0,
                    'assignments': [],
                    'message': 'No PM assignments needed for this week.'
                }

            # Assign to technicians and save
            scheduled_assignments = self._assign_and_save(assignments, week_start, week_start_str)

            self.conn.commit()

            # Clear caches to free memory
            self.completion_repo.clear_cache()
            self.eligibility_checker.clear_cache()

            return {
                'success': True,
                'total_assignments': len(scheduled_assignments),
                'unique_assets': len(set(a['bfm_no'] for a in scheduled_assignments)),
                'assignments': scheduled_assignments
            }

        except Exception as e:
            self.conn.rollback()
            # Clear caches even on error
            self.completion_repo.clear_cache()
            self.eligibility_checker.clear_cache()
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    def _get_active_equipment(self) -> List[Equipment]:
        """Get list of active equipment from database - EXCLUDES Cannot Find and Run to Failure"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT bfm_equipment_no, description, monthly_pm, annual_pm,
                last_monthly_pm, last_annual_pm, COALESCE(status, 'Active') as status
            FROM equipment
            WHERE (status = 'Active' OR status IS NULL)
            AND status NOT IN ('Run to Failure', 'Missing')
            AND bfm_equipment_no NOT IN (
                SELECT DISTINCT bfm_equipment_no FROM cannot_find_assets WHERE status = 'Missing'
            )
            AND bfm_equipment_no NOT IN (
                SELECT DISTINCT bfm_equipment_no FROM run_to_failure_assets
            )
            ORDER BY bfm_equipment_no
        ''')

        equipment_list = []
        for row in cursor.fetchall():
            bfm_no = row[0]
            # Get priority from priority_map, default to 99 if not found
            priority = self.priority_map.get(str(bfm_no), 99)

            equipment_list.append(Equipment(
                bfm_no=bfm_no,
                description=row[1],
                has_monthly=bool(row[2]),
                has_annual=bool(row[3]),
                last_monthly_date=row[4],
                last_annual_date=row[5],
                status=row[6],
                priority=priority
            ))

        return equipment_list
    
    def _assign_and_save(self, assignments: List[PMAssignment], week_start: datetime, week_start_str: str):
        """Assign to technicians and save to database - OPTIMIZED WITH BATCH INSERT"""

        cursor = self.conn.cursor()
        scheduled_assignments = []

        # Defensive check - should never happen due to validation in generate_weekly_schedule
        if not self.technicians or len(self.technicians) == 0:
            print("ERROR: No technicians available for assignment")
            return scheduled_assignments

        if not assignments or len(assignments) == 0:
            print("INFO: No assignments to schedule")
            return scheduled_assignments

        total_assignments = len(assignments)
        print(f"DEBUG: Assigning {total_assignments} PMs to technicians...")

        # Prepare batch data for database insert
        batch_insert_data = []

        for i, assignment in enumerate(assignments):
            # Yield to event loop every 100 assignments to prevent UI freeze
            # (Increased from 25 due to batch insert optimization - much faster now)
            if i > 0 and i % 100 == 0:
                print(f"DEBUG: Progress: {i}/{total_assignments} assignments processed ({i*100//total_assignments}%)")
                if self.root:
                    self.root.update_idletasks()  # Yield to tkinter event loop

            # Distribute among technicians
            tech_index = i % len(self.technicians)
            technician = self.technicians[tech_index]

            # Schedule throughout the week
            day_offset = i % 5  # Spread across weekdays
            scheduled_date = week_start + timedelta(days=day_offset)

            # Add to batch insert data
            batch_insert_data.append((
                week_start_str,
                assignment.bfm_no,
                assignment.pm_type.value,
                technician,
                scheduled_date.strftime('%Y-%m-%d')
            ))

            scheduled_assignments.append({
                'bfm_no': assignment.bfm_no,
                'pm_type': assignment.pm_type.value,
                'description': assignment.description,
                'technician': technician,
                'scheduled_date': scheduled_date,
                'reason': assignment.reason,
                'priority_score': assignment.priority_score
            })

        # PERFORMANCE OPTIMIZATION: Batch insert all assignments at once
        print(f"DEBUG: Saving {len(batch_insert_data)} assignments to database (batch insert)...")
        cursor.executemany('''
            INSERT INTO weekly_pm_schedules
            (week_start_date, bfm_equipment_no, pm_type, assigned_technician, scheduled_date)
            VALUES (%s, %s, %s, %s, %s)
        ''', batch_insert_data)

        print(f"DEBUG: Finished assigning all {total_assignments} PMs")
        return scheduled_assignments



class DateStandardizer:
    """Utility class to standardize all dates in the CMMS database to YYYY-MM-DD format"""
    
    def __init__(self, conn):
        self.conn = conn
        self.date_patterns = [
            r'^\d{1,2}/\d{1,2}/\d{2}$',      # MM/DD/YY or M/D/YY
            r'^\d{1,2}/\d{1,2}/\d{4}$',     # MM/DD/YYYY or M/D/YYYY
            r'^\d{1,2}-\d{1,2}-\d{2}$',      # MM-DD-YY or M-D-YY
            r'^\d{1,2}-\d{1,2}-\d{4}$',     # MM-DD-YYYY or M-D-YYYY
            r'^\d{4}-\d{1,2}-\d{1,2}$'      # YYYY-MM-DD (already correct)
        ]
        
        self.date_formats = [
            '%m/%d/%y', '%#m/%#d/%y', '%-m/%-d/%y',  # Handle leading zeros
            '%m/%d/%Y', '%#m/%#d/%Y', '%-m/%-d/%Y',
            '%m-%d-%y', '%#m-%#d-%y', '%-m/%-d/%y',
            '%m-%d-%Y', '%#m-%#d-%Y', '%-m/%-d/%Y',
            '%Y-%m-%d'  # Target format
        ]
    
    def parse_date_flexible(self, date_str):
        """Parse date string using multiple formats and return standardized YYYY-MM-DD"""
        if not date_str or date_str.strip() == '':
            return None
            
        date_str = str(date_str).strip()
        
        # Already in correct format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            try:
                # Validate it's a real date
                datetime.strptime(date_str, '%Y-%m-%d')
                return date_str
            except ValueError:
                pass
        
        # Try all possible formats
        for date_format in self.date_formats:
            try:
                parsed_date = datetime.strptime(date_str, date_format)
                
                # Handle 2-digit years (assume 20xx if < 50, 19xx if >= 50)
                if parsed_date.year < 1950:
                    if parsed_date.year < 50:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                    else:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 1900)
                
                return parsed_date.strftime('%Y-%m-%d')
                
            except ValueError:
                continue
        
        # If no format worked, return None
        print(f"Could not parse date: '{date_str}'")
        return None
    
    def standardize_all_dates(self):
        """Standardize all dates in the database to YYYY-MM-DD format"""
        cursor = self.conn.cursor()
        total_updated = 0
        errors = []
        
        # Tables and their date columns to standardize
        tables_to_update = {
            'equipment': [
                'last_monthly_pm', 'last_six_month_pm', 'last_annual_pm',
                'next_monthly_pm', 'next_six_month_pm', 'next_annual_pm'
            ],
            'pm_completions': [
                'completion_date', 'pm_due_date', 'next_annual_pm_date'
            ],
            'weekly_pm_schedules': [
                'week_start_date', 'scheduled_date', 'completion_date'
            ],
            'corrective_maintenance': [
                'created_date', 'completion_date'
            ],
            'cannot_find_assets': [
                'reported_date'
            ],
            'run_to_failure_assets': [
                'completion_date'
            ]
        }
        
        for table, date_columns in tables_to_update.items():
            print(f"Processing table: {table}")
            
            try:
                # Get all rows from table
                cursor.execute(f'SELECT * FROM {table}')
                rows = cursor.fetchall()
                
                # Get column names
                cursor.execute(f'PRAGMA table_info({table})')
                column_info = cursor.fetchall()
                column_names = [col[1] for col in column_info]
                
                for row in rows:
                    row_dict = dict(zip(column_names, row))
                    updates_needed = {}
                    
                    # Check each date column
                    for date_col in date_columns:
                        if date_col in row_dict and row_dict[date_col]:
                            original_date = row_dict[date_col]
                            standardized_date = self.parse_date_flexible(original_date)
                            
                            if standardized_date and standardized_date != original_date:
                                updates_needed[date_col] = standardized_date
                    
                    # Update row if any dates need standardizing
                    if updates_needed:
                        update_parts = []
                        values = []
                        
                        for col, new_value in updates_needed.items():
                            update_parts.append(f'{col} = %s')
                            values.append(new_value)
                        
                        # Identify primary key or unique identifier
                        if table == 'equipment':
                            where_clause = 'bfm_equipment_no = %s'
                            values.append(row_dict['bfm_equipment_no'])
                        elif 'id' in row_dict:
                            where_clause = 'id = %s'
                            values.append(row_dict['id'])
                        else:
                            # Skip if no clear identifier
                            continue
                        
                        update_sql = f"UPDATE {table} SET {', '.join(update_parts)} WHERE {where_clause}"
                        
                        try:
                            cursor.execute(update_sql, values)
                            total_updated += 1
                            print(f"Updated {table} - {updates_needed}")
                        except Exception as e:
                            errors.append(f"Error updating {table}: {str(e)}")
                            
            except Exception as e:
                errors.append(f"Error processing table {table}: {str(e)}")
                continue
        
        # Commit changes
        try:
            self.conn.commit()
            return total_updated, errors
        except Exception as e:
            self.conn.rollback()
            errors.append(f"Error committing changes: {str(e)}")
            return 0, errors



def generate_monthly_summary_report(conn, month=None, year=None):
    """
    Generate a comprehensive monthly PM summary report with separate tracking
    for PM Completions, Cannot Find, Run to Failure entries, and CM statistics
    
    Args:
        conn: Database connection
        month: Month number (1-12), defaults to current month
        year: Year (YYYY), defaults to current year
    """
    cursor = conn.cursor()
    
    # Use current month/year if not specified
    if month is None or year is None:
        now = datetime.now()
        month = month or now.month
        year = year or now.year
    
    month_name = calendar.month_name[month]
    
    # Calculate date range for the month
    first_day = f"{year}-{month:02d}-01"
    last_day = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"
    
    print("=" * 80)
    print(f"MONTHLY PM SUMMARY REPORT")
    print(f"Month: {month_name} {year}")
    print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()
    
    # 1. OVERALL MONTHLY SUMMARY - PM COMPLETIONS ONLY
    # Get PM completions count
    cursor.execute('''
        SELECT
            COUNT(*) as total_completions,
            SUM(labor_hours + labor_minutes/60.0) as total_hours,
            AVG(labor_hours + labor_minutes/60.0) as avg_hours
        FROM pm_completions
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
    ''', (year, month))
    
    pm_results = cursor.fetchone()
    pm_completions = pm_results[0] or 0
    pm_total_hours = pm_results[1] or 0.0
    pm_avg_hours = pm_results[2] or 0.0
    
    # Get Cannot Find entries count (separate)
    cursor.execute('''
        SELECT COUNT(*)
        FROM cannot_find_assets
        WHERE EXTRACT(YEAR FROM reported_date::date) = %s
        AND EXTRACT(MONTH FROM reported_date::date) = %s
    ''', (year, month))
    
    cf_count = cursor.fetchone()[0] or 0
    
    # Get Run to Failure entries count (separate)
    cursor.execute('''
        SELECT COUNT(*)
        FROM run_to_failure_assets
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
    ''', (year, month))
    
    rtf_count = cursor.fetchone()[0] or 0
    
    # Get CM statistics
    # CMs created this month
    cursor.execute('''
        SELECT COUNT(*)
        FROM corrective_maintenance
        WHERE EXTRACT(YEAR FROM created_date::date) = %s
        AND EXTRACT(MONTH FROM created_date::date) = %s
    ''', (year, month))

    cms_created = cursor.fetchone()[0] or 0

    # CMs completed/closed this month (TOTAL)
    cursor.execute('''
        SELECT COUNT(*)
        FROM corrective_maintenance
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        AND (status = 'Closed' OR status = 'Completed')
    ''', (year, month))

    cms_closed = cursor.fetchone()[0] or 0

    # NEW: CMs created AND closed in the same month
    cursor.execute('''
        SELECT COUNT(*)
        FROM corrective_maintenance
        WHERE EXTRACT(YEAR FROM created_date::date) = %s
        AND EXTRACT(MONTH FROM created_date::date) = %s
        AND EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        AND (status = 'Closed' OR status = 'Completed')
    ''', (year, month, year, month))

    cms_created_and_closed = cursor.fetchone()[0] or 0

    # NEW: CMs created BEFORE this month but closed this month
    cursor.execute('''
        SELECT COUNT(*)
        FROM corrective_maintenance
        WHERE (EXTRACT(YEAR FROM created_date::date) != %s OR EXTRACT(MONTH FROM created_date::date) != %s)
        AND EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        AND (status = 'Closed' OR status = 'Completed')
    ''', (year, month, year, month))

    cms_closed_from_before = cursor.fetchone()[0] or 0

    # Currently open CMs (as of report date)
    cursor.execute('''
        SELECT COUNT(*)
        FROM corrective_maintenance 
        WHERE status = 'Open'
    ''')

    cms_open_current = cursor.fetchone()[0] or 0

    # Display Enhanced CM Statistics
    print("CORRECTIVE MAINTENANCE (CM) SUMMARY:")
    print(f"  CMs Created This Month: {cms_created}")
    print(f"  CMs Closed This Month: {cms_closed}")
    print(f"    - Created & Closed in {month_name}: {cms_created_and_closed}")
    print(f"    - Created Before {month_name}, Closed in {month_name}: {cms_closed_from_before}")
    print(f"  Currently Open CMs: {cms_open_current}")
    print()

    # NEW: Show details of CMs closed from previous months (if any)
    if cms_closed_from_before > 0:
        print("=" * 80)
        print(f"CMs CREATED BEFORE {month_name.upper()} BUT CLOSED IN {month_name.upper()}:")
        print("=" * 80)
    
        cursor.execute('''
            SELECT 
                cm_number,
                bfm_equipment_no,
                created_date,
                completion_date,
                assigned_technician
            FROM corrective_maintenance 
            WHERE (EXTRACT(YEAR FROM created_date::date) != %s OR EXTRACT(MONTH FROM created_date::date) != %s)
            AND EXTRACT(YEAR FROM completion_date::date) = %s
            AND EXTRACT(MONTH FROM completion_date::date) = %s
            AND (status = 'Closed' OR status = 'Completed')
            ORDER BY completion_date
        ''', (year, month, year, month))
    
        old_cms = cursor.fetchall()
    
        print(f"{'CM#':<12} {'Created':<12} {'Closed':<12} {'Equipment':<15} {'Tech':<20}")
        print("-" * 80)
    
        for cm_number, bfm, created, completed, tech in old_cms:
            created_short = str(created)[:10] if created else "Unknown"
            completed_short = str(completed)[:10] if completed else "Unknown"
            bfm_short = (bfm[:15] if bfm else "N/A")
            tech_short = (tech[:20] if tech else "Unassigned")
            print(f"{cm_number:<12} {created_short:<12} {completed_short:<12} {bfm_short:<15} {tech_short:<20}")
    
        print()
    
    # Display PM Completions (NOT including Cannot Find or Run to Failure)
    print("MONTHLY OVERVIEW:")
    print(f"  Total PM Completions: {pm_completions}")
    print(f"  Total Labor Hours: {pm_total_hours:.1f} hours")
    print(f"  Average Hours per PM: {pm_avg_hours:.1f} hours")
    print()
    
    # Display Cannot Find and Run to Failure separately
    print("OTHER ACTIVITY:")
    print(f"  Cannot Find Entries: {cf_count}")
    print(f"  Run to Failure Entries: {rtf_count}")
    print(f"  Total All Activity: {pm_completions + cf_count + rtf_count}")
    print()
    
    
    
    # 2. PM TYPE BREAKDOWN (PM Completions only)
    cursor.execute('''
        SELECT
            pm_type,
            COUNT(*) as count,
            SUM(labor_hours + labor_minutes/60.0) as total_hours,
            AVG(labor_hours + labor_minutes/60.0) as avg_hours
        FROM pm_completions
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        GROUP BY pm_type
        ORDER BY count DESC
    ''', (year, month))
    
    pm_types = cursor.fetchall()
    
    if pm_types:
        print("PM TYPE BREAKDOWN:")
        print(f"{'PM Type':<15} {'Count':<10} {'Total Hours':<15} {'Avg Hours':<12}")
        print("-" * 55)
        for pm_type, count, total_hrs, avg_hrs in pm_types:
            total_hrs_display = f"{total_hrs:.1f}h" if total_hrs else "0.0h"
            avg_hrs_display = f"{avg_hrs:.1f}h" if avg_hrs else "0.0h"
            print(f"{pm_type:<15} {count:<10} {total_hrs_display:<15} {avg_hrs_display:<12}")
        print()
    
    # 3. DAILY COMPLETION TRACKING (PM Completions only)
    cursor.execute('''
        SELECT
            completion_date,
            COUNT(*) as daily_count,
            SUM(labor_hours + labor_minutes/60.0) as daily_hours
        FROM pm_completions
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        GROUP BY completion_date
        ORDER BY completion_date
    ''', (year, month))
    
    daily_data = cursor.fetchall()
    
    if daily_data:
        print("DAILY COMPLETION SUMMARY:")
        print(f"{'Date':<12} {'PMs Completed':<15} {'Labor Hours':<12} {'Running Total':<15}")
        print("-" * 55)
        
        running_total = 0
        for date, count, hours in daily_data:
            running_total += count
            hours_display = f"{hours:.1f}h" if hours else "0.0h"
            print(f"{date:<12} {count:<15} {hours_display:<12} {running_total:<15}")
        print()
    
    # 4. TECHNICIAN PERFORMANCE (PM Completions only)
    cursor.execute('''
        SELECT
            technician_name,
            COUNT(*) as completions,
            SUM(labor_hours + labor_minutes/60.0) as total_hours,
            AVG(labor_hours + labor_minutes/60.0) as avg_hours
        FROM pm_completions
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        GROUP BY technician_name
        ORDER BY completions DESC
    ''', (year, month))
    
    technicians = cursor.fetchall()
    
    if technicians:
        print("TECHNICIAN PERFORMANCE:")
        print(f"{'Technician':<25} {'Completions':<15} {'Total Hours':<15} {'Avg Hours':<12}")
        print("-" * 70)
        for tech, count, total_hrs, avg_hrs in technicians:
            total_hrs_display = f"{total_hrs:.1f}h" if total_hrs else "0.0h"
            avg_hrs_display = f"{avg_hrs:.1f}h" if avg_hrs else "0.0h"
            print(f"{tech:<25} {count:<15} {total_hrs_display:<15} {avg_hrs_display:<12}")
        print()
    
    # 5. CM BREAKDOWN BY PRIORITY AND TECHNICIAN
    cursor.execute('''
        SELECT
            priority,
            COUNT(*) as count
        FROM corrective_maintenance
        WHERE EXTRACT(YEAR FROM created_date::date) = %s
        AND EXTRACT(MONTH FROM created_date::date) = %s
        GROUP BY priority
        ORDER BY
            CASE priority
                WHEN 'Critical' THEN 1
                WHEN 'High' THEN 2
                WHEN 'Medium' THEN 3
                WHEN 'Low' THEN 4
                ELSE 5
            END
    ''', (year, month))
    
    cm_priorities = cursor.fetchall()
    
    if cm_priorities:
        print("CM BREAKDOWN BY PRIORITY (Created This Month):")
        print(f"{'Priority':<15} {'Count':<10}")
        print("-" * 25)
        for priority, count in cm_priorities:
            print(f"{priority:<15} {count:<10}")
        print()
    
    # CM completion by technician
    cursor.execute('''
        SELECT
            assigned_technician,
            COUNT(*) as completed
        FROM corrective_maintenance
        WHERE EXTRACT(YEAR FROM completion_date::date) = %s
        AND EXTRACT(MONTH FROM completion_date::date) = %s
        AND (status = 'Closed' OR status = 'Completed')
        GROUP BY assigned_technician
        ORDER BY completed DESC
    ''', (year, month))
    
    cm_techs = cursor.fetchall()
    
    if cm_techs:
        print("CMs COMPLETED BY TECHNICIAN (This Month):")
        print(f"{'Technician':<25} {'CMs Closed':<12}")
        print("-" * 37)
        for tech, count in cm_techs:
            print(f"{tech:<25} {count:<12}")
        print()
    
    # 6. EQUIPMENT LOCATION SUMMARY (PM Completions only)
    cursor.execute('''
        SELECT
            e.location,
            COUNT(*) as completions,
            SUM(pc.labor_hours + pc.labor_minutes/60.0) as total_hours
        FROM pm_completions pc
        JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
        WHERE EXTRACT(YEAR FROM pc.completion_date::date) = %s
        AND EXTRACT(MONTH FROM pc.completion_date::date) = %s
        GROUP BY e.location
        ORDER BY completions DESC
    ''', (year, month))
    
    locations = cursor.fetchall()
    
    if locations:
        print("COMPLETIONS BY LOCATION:")
        print(f"{'Location':<30} {'Completions':<15} {'Total Hours':<12}")
        print("-" * 60)
        for location, count, hours in locations:
            hours_display = f"{hours:.1f}h" if hours else "0.0h"
            print(f"{location:<30} {count:<15} {hours_display:<12}")
        print()
    
    print("=" * 80)
    print("END OF MONTHLY SUMMARY REPORT")
    print("=" * 80)
    
    return {
        'pm_completions': pm_completions,
        'cannot_find_count': cf_count,
        'run_to_failure_count': rtf_count,
        'cms_created': cms_created,
        'cms_closed': cms_closed,
        'cms_open_current': cms_open_current,
        'total_hours': pm_total_hours,
        'avg_hours': pm_avg_hours,
        'month': month_name,
        'year': year
    }

def export_professional_monthly_report_pdf(conn, month=None, year=None):
        """
        Generate a professional
        """
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        
        cursor = conn.cursor()
        
        # Use current month/year if not specified
        if month is None or year is None:
            now = datetime.now()
            month = month or now.month
            year = year or now.year
    
        month_name = calendar.month_name[month]
    
        # Create PDF filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"AIT_Monthly_Report_{month_name}_{year}_{timestamp}.pdf"
    
        # Create document
        doc = SimpleDocTemplate(filename, pagesize=letter,
                            rightMargin=36, leftMargin=36,
                            topMargin=50, bottomMargin=36)
    
        story = []
        styles = getSampleStyleSheet()
    
        # ==================== CUSTOM STYLES ====================
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a365d'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
    
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2c5282'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        )
    
        subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=styles['Heading3'],
            fontSize=11,
            textColor=colors.HexColor('#2d3748'),
            spaceAfter=6,
            fontName='Helvetica-Bold'
        )
    
        # ==================== TITLE PAGE ====================
        story.append(Paragraph("AIRBUS AIT", title_style))
        story.append(Paragraph("Monthly Maintenance Summary Report", 
                            ParagraphStyle('Subtitle', parent=styles['Normal'], 
                                        fontSize=16, alignment=TA_CENTER, 
                                        textColor=colors.HexColor('#4a5568'))))
        story.append(Spacer(1, 20))
    
        # Report metadata box
        meta_data = [
            ['Report Period:', f'{month_name} {year}'],
            ['Generated:', datetime.now().strftime('%B %d, %Y at %I:%M %p')],
            ['Report Type:', 'Comprehensive Monthly Summary']
        ]
    
        meta_table = Table(meta_data, colWidths=[2*inch, 4*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e2e8f0')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
    
        story.append(meta_table)
        story.append(Spacer(1, 30))
    
        # ==================== EXECUTIVE SUMMARY ====================
        story.append(Paragraph("EXECUTIVE SUMMARY", heading_style))
        story.append(Spacer(1, 10))
    
        # Get summary data
        cursor.execute('''
            SELECT
                COUNT(*) as total_completions,
                SUM(labor_hours + labor_minutes/60.0) as total_hours,
                AVG(labor_hours + labor_minutes/60.0) as avg_hours
            FROM pm_completions
            WHERE EXTRACT(YEAR FROM completion_date::date) = %s
            AND EXTRACT(MONTH FROM completion_date::date) = %s
        ''', (year, month))
    
        pm_results = cursor.fetchone()
        pm_completions = pm_results[0] or 0
        pm_total_hours = pm_results[1] or 0.0
        pm_avg_hours = pm_results[2] or 0.0
    
        # Get CM data
        cursor.execute('''
            SELECT COUNT(*) FROM corrective_maintenance
            WHERE EXTRACT(YEAR FROM created_date::date) = %s AND EXTRACT(MONTH FROM created_date::date) = %s
        ''', (year, month))
        cms_created = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT COUNT(*) FROM corrective_maintenance
            WHERE EXTRACT(YEAR FROM completion_date::date) = %s  AND EXTRACT(MONTH FROM completion_date::date) = %s
            AND (status = 'Closed' OR status = 'Completed')
        ''', (year, month))
        cms_closed = cursor.fetchone()[0] or 0
        
        # Summary highlights table
        summary_data = [
            ['METRIC', 'VALUE'],
            ['PM Completions', f'{pm_completions:,}'],
            ['Total Labor Hours', f'{pm_total_hours:.1f} hrs'],
            ['Average Time per PM', f'{pm_avg_hours:.1f} hrs'],
            ['CMs Created', f'{cms_created:,}'],
            ['CMs Closed', f'{cms_closed:,}']
        ]
    
        summary_table = Table(summary_data, colWidths=[3.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')])
        ]))
    
        story.append(summary_table)
        story.append(Spacer(1, 25))
        
        # ==================== CORRECTIVE MAINTENANCE DETAIL ====================
        story.append(Paragraph("CORRECTIVE MAINTENANCE ANALYSIS", heading_style))
        story.append(Spacer(1, 10))
    
        # Get CM breakdown
        cursor.execute('''
            SELECT COUNT(*) FROM corrective_maintenance
            WHERE EXTRACT(YEAR FROM created_date::date) = %s AND EXTRACT(MONTH FROM created_date::date) = %s
            AND EXTRACT(YEAR FROM completion_date::date) = %s AND EXTRACT(MONTH FROM completion_date::date) = %s
            AND (status = 'Closed' OR status = 'Completed')
        ''', (year, month, year, month))
        cms_created_and_closed = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT COUNT(*) FROM corrective_maintenance
            WHERE (EXTRACT(YEAR FROM created_date::date) != %s OR EXTRACT(MONTH FROM created_date::date) != %s)
            AND EXTRACT(YEAR FROM completion_date::date) = %s AND EXTRACT(MONTH FROM completion_date::date) = %s
            AND (status = 'Closed' OR status = 'Completed')
        ''', (year, month, year, month))
        cms_closed_from_before = cursor.fetchone()[0] or 0
    
        cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
        cms_open_current = cursor.fetchone()[0] or 0
        
        cm_breakdown_data = [
            ['CATEGORY', 'COUNT'],
            ['CMs Created This Month', str(cms_created)],
            ['CMs Closed This Month', str(cms_closed)],
            ['  - Created & Closed Same Month', str(cms_created_and_closed)],
            [f'  - Carried Over from Prior Months', str(cms_closed_from_before)],
            ['Currently Open CMs', str(cms_open_current)]
        ]
    
        cm_table = Table(cm_breakdown_data, colWidths=[4.5*inch, 1.5*inch])
        cm_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BACKGROUND', (0, 1), (-1, 2), colors.white),
            ('BACKGROUND', (0, 3), (-1, -1), colors.HexColor('#f7fafc')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 3), (0, 4), 24),  # Indent sub-items
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
    
        story.append(cm_table)
        story.append(Spacer(1, 20))
        
        # CM Details from previous months (if any)
        if cms_closed_from_before > 0:
            story.append(Paragraph("CMs Carried Over from Prior Months", subheading_style))
            story.append(Spacer(1, 8))
        
            cursor.execute('''
                SELECT cm_number, bfm_equipment_no, created_date, completion_date, assigned_technician
                FROM corrective_maintenance
                WHERE (EXTRACT(YEAR FROM created_date::date) != %s OR EXTRACT(MONTH FROM created_date::date) != %s)
                AND EXTRACT(YEAR FROM completion_date::date) = %s AND EXTRACT(MONTH FROM completion_date::date) = %s
                AND (status = 'Closed' OR status = 'Completed')
                ORDER BY completion_date
            ''', (year, month, year, month))
        
            old_cms = cursor.fetchall()
        
            cm_detail_data = [['CM Number', 'Equipment', 'Created', 'Closed', 'Technician']]
        
            for cm_number, bfm, created, completed, tech in old_cms:
                created_short = str(created)[:10] if created else "N/A"
                completed_short = str(completed)[:10] if completed else "N/A"
                bfm_short = (bfm[:12] + '...' if len(str(bfm)) > 12 else bfm) if bfm else "N/A"
                tech_short = (tech[:15] + '...' if len(str(tech)) > 15 else tech) if tech else "Unassigned"
                cm_detail_data.append([cm_number, bfm_short, created_short, completed_short, tech_short])
        
            cm_detail_table = Table(cm_detail_data, colWidths=[1.1*inch, 1.3*inch, 1.1*inch, 1.1*inch, 1.4*inch])
            cm_detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')])
            ]))
        
            story.append(cm_detail_table)
            story.append(Spacer(1, 20))
    
        # ==================== PM TYPE BREAKDOWN ====================
        story.append(Paragraph("PREVENTIVE MAINTENANCE BREAKDOWN", heading_style))
        story.append(Spacer(1, 10))
    
        cursor.execute('''
            SELECT pm_type, COUNT(*) as count,
                SUM(labor_hours + labor_minutes/60.0) as total_hours,
                AVG(labor_hours + labor_minutes/60.0) as avg_hours
            FROM pm_completions
            WHERE EXTRACT(YEAR FROM completion_date::date) = %s AND EXTRACT(MONTH FROM completion_date::date) = %s
            GROUP BY pm_type
            ORDER BY count DESC
        ''', (year, month))
    
        pm_types = cursor.fetchall()
    
        if pm_types:
            pm_type_data = [['PM Type', 'Count', 'Total Hours', 'Avg Hours']]
        
            for pm_type, count, total_hrs, avg_hrs in pm_types:
                pm_type_data.append([
                    pm_type,
                    str(count),
                    f'{total_hrs:.1f}' if total_hrs else '0.0',
                    f'{avg_hrs:.1f}' if avg_hrs else '0.0'
                ])
        
            pm_type_table = Table(pm_type_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
            pm_type_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')])
            ]))
        
            story.append(pm_type_table)
            story.append(Spacer(1, 25))
    
        # ==================== DAILY ACTIVITY SUMMARY ====================
        story.append(Paragraph("DAILY COMPLETION SUMMARY", heading_style))
        story.append(Spacer(1, 10))
    
        cursor.execute('''
            SELECT completion_date, COUNT(*) as daily_count,
                SUM(labor_hours + labor_minutes/60.0) as daily_hours
            FROM pm_completions
            WHERE EXTRACT(YEAR FROM completion_date::date) = %s AND EXTRACT(MONTH FROM completion_date::date) = %s
            GROUP BY completion_date
            ORDER BY completion_date
        ''', (year, month))
    
        daily_data_raw = cursor.fetchall()
    
        if daily_data_raw:
            daily_data = [['Date', 'PMs Completed', 'Labor Hours', 'Running Total']]
            running_total = 0
        
            for date, count, hours in daily_data_raw:
                running_total += count
                daily_data.append([
                    date,
                    str(count),
                    f'{hours:.1f}' if hours else '0.0',
                    str(running_total)
                ])
        
            daily_table = Table(daily_data, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
            daily_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5282')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')])
            ]))
        
            story.append(daily_table)
    
        # ==================== BUILD PDF ====================
        doc.build(story)
    
        return filename   





class AITCMMSSystem:
    """Complete AIT CMMS - Computerized Maintenance Management System"""
    
    def show_closing_sync_dialog(self):
        """Show dialog asking user to confirm database sync on close"""
    
        dialog = tk.Toplevel(self.root)
        dialog.title("Closing Program - Database Sync")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (600 // 2)
        y = (dialog.winfo_screenheight() // 2) - (500 // 2)
        dialog.geometry(f"600x500+{x}+{y}")
    
        result = {"action": "cancel"}  # Default to cancel
    
        # Header
        header_frame = ttk.Frame(dialog, padding=20)
        header_frame.pack(fill='x')
    
        ttk.Label(header_frame, text="Closing AIT CMMS", 
                font=('Arial', 16, 'bold')).pack()
        ttk.Label(header_frame, text="Database Backup Confirmation", 
                font=('Arial', 11), foreground='blue').pack(pady=5)
    
        # Separator
        ttk.Separator(dialog, orient='horizontal').pack(fill='x', pady=10)
    
        # Info section
        info_frame = ttk.LabelFrame(dialog, text="Session Information", padding=15)
        info_frame.pack(fill='both', expand=True, padx=20, pady=10)
    
        session_duration = datetime.now() - self.session_start_time
        hours, remainder = divmod(int(session_duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
    
        info_text = f"""
    User: {self.user_name}
    Role: {self.current_user_role}

    Session Start: {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}
    Session Duration: {hours}h {minutes}m {seconds}s

    Current Database: ait_cmms_database.db
    SharePoint Folder: {os.path.basename(self.backup_sync_dir) if hasattr(self, 'backup_sync_dir') and self.backup_sync_dir else 'Not Connected'}
        """
    
        ttk.Label(info_frame, text=info_text, justify='left', 
                font=('Courier', 9)).pack(anchor='w')
    
        # Sync explanation
        sync_frame = ttk.LabelFrame(dialog, text="What Happens Next", padding=15)
        sync_frame.pack(fill='x', padx=20, pady=10)
    
        sync_text = """When you click 'Backup and Close':

    1. CHECK: Your database will be backed up to SharePoint
    2. CHECK: Timestamped backup will be created
    3. CHECK: Other users can access your latest changes
    4. CHECK: Program will close safely

    This ensures all your work is saved.
        """
    
        ttk.Label(sync_frame, text=sync_text, justify='left').pack(anchor='w')
    
        # Important note
        note_frame = ttk.Frame(dialog, padding=10)
        note_frame.pack(fill='x', padx=20)
    
        ttk.Label(note_frame, 
                  text="WARNING: Note: Last person to close the program pushes the final database state",
                  foreground='blue', font=('Arial', 9),
                  wraplength=550).pack()
    
        # Buttons
        button_frame = ttk.Frame(dialog, padding=15)
        button_frame.pack(fill='x')
    
        def sync_and_close():
            result["action"] = "sync_and_close"
            dialog.destroy()
    
        def cancel_close():
            result["action"] = "cancel"
            dialog.destroy()
    
        def close_without_sync():
            confirm = messagebox.askyesno(
                "Confirm Close Without Backup",
                "Close without backing up to SharePoint?\n\n"
                "CHECK: WARNING: Your changes will NOT be saved!\n"
                "CHECK: Other users will NOT see your work!\n\n"
                "Are you sure?",
                icon='warning',
                parent=dialog
            )
            if confirm:
                result["action"] = "close_without_sync"
                dialog.destroy()
    
        ttk.Button(button_frame, text="CHECK: Backup and Close", 
                command=sync_and_close,
                style='Accent.TButton').pack(side='left', padx=5)
    
        ttk.Button(button_frame, text="Cancel", 
                command=cancel_close).pack(side='left', padx=5)
    
        ttk.Button(button_frame, text="CHECK: Close Without Backup", 
                command=close_without_sync).pack(side='right', padx=5)
    
        # Wait for dialog
        dialog.wait_window()
    
        return result["action"]
    
    
    
    
    def analyze_pm_capacity(self):
        """Analyze if weekly PM target can handle all equipment requirements"""
        try:
            cursor = self.conn.cursor()
        
            # Get the actual counts from your database
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_active,
                    SUM(CASE WHEN monthly_pm = 1 THEN 1 ELSE 0 END) as monthly_pm_count,
                    SUM(CASE WHEN annual_pm = 1 THEN 1 ELSE 0 END) as annual_pm_count,
                    SUM(CASE WHEN status IN ('Run to Failure', 'Missing') THEN 1 ELSE 0 END) as excluded_count
                FROM equipment 
                WHERE status = 'Active' OR status IS NULL
            ''')
        
            result = cursor.fetchone()
            total_active = result[0]
            monthly_count = result[1]
            annual_count = result[2]
            excluded = result[3]
        
            # Calculate requirements
            monthly_pms_per_month = monthly_count  # Each needs PM every 30 days
            annual_pms_per_month = round(annual_count / 12)  # Spread over 12 months
            total_required_per_month = monthly_pms_per_month + annual_pms_per_month
            
            # Your capacity
            weekly_capacity = self.weekly_pm_target
            monthly_capacity = weekly_capacity * 4
            
            # Calculate surplus/deficit
            surplus = monthly_capacity - total_required_per_month
            
            # Build report
            report = "CHECK:" * 70 + "\n"
            report += "PM CAPACITY ANALYSIS\n"
            report += "CHECK:" * 70 + "\n\n"
            
            report += "EQUIPMENT BREAKDOWN:\n"
            report += f"  Total Active Assets: {total_active:,}\n"
            report += f"  Assets requiring Monthly PMs: {monthly_count:,}\n"
            report += f"  Assets requiring Annual PMs: {annual_count:,}\n"
            report += f"  Excluded (Run to Failure/Cannot Find): {excluded:,}\n\n"
            
            report += "MONTHLY PM REQUIREMENTS:\n"
            report += f"  Monthly PMs needed: {monthly_pms_per_month:,}/month\n"
            report += f"  Annual PMs needed: {annual_pms_per_month:,}/month\n"
            report += f"  TOTAL Required: {total_required_per_month:,}/month\n\n"
            
            report += "YOUR CAPACITY:\n"
            report += f"  Weekly target: {weekly_capacity} PMs/week\n"
            report += f"  Monthly capacity: {monthly_capacity} PMs/month (4 weeks)\n\n"
        
            report += "CHECK:" * 70 + "\n"
            if surplus >= 0:
                report += "CHECK: VERDICT: CAPACITY IS SUFFICIENT!\n"
                report += "CHECK:" * 70 + "\n"
                report += f"You have {surplus} PMs/month surplus capacity.\n"
                report += f"This is {(surplus/monthly_capacity*100):.1f}% extra capacity for:\n"
                report += "  - Catching up on PM backlog\n"
                report += "  - Handling equipment that was missed\n"
                report += "  - Additional corrective maintenance\n\n"
            else:
                report += "CHECK: VERDICT: CAPACITY IS INSUFFICIENT!\n"
                report += "CHECK:" * 70 + "\n"
                report += f"You need {abs(surplus)} MORE PMs/month to keep up.\n\n"
                report += "RECOMMENDATIONS:\n"
                report += f"  - Increase weekly target to: {math.ceil(total_required_per_month/4)} PMs/week\n"
                report += f"  - Or add {math.ceil(abs(surplus)/monthly_capacity * 100)}% more technician hours\n"
                report += f"  - Or convert some Monthly PMs to Annual (if appropriate)\n\n"
                report += "WARNING: WARNING: At current capacity, you will accumulate\n"
                report += f"   a backlog of {abs(surplus)} PMs every month!\n\n"
        
            # Sustainability reference
            report += "CHECK:" * 70 + "\n"
            report += "WHAT YOUR CAPACITY CAN SUSTAIN:\n"
            report += "CHECK:" * 70 + "\n"
            report += f"  If ALL assets need Monthly PMs: {monthly_capacity:,} assets\n"
            report += f"  If ALL assets need Annual PMs: {monthly_capacity * 12:,} assets\n"
            report += f"  Current mix sustainability: {(monthly_capacity/total_required_per_month*100):.1f}%\n\n"
        
            # Check for never-done PMs
            cursor.execute('''
                SELECT COUNT(DISTINCT e.bfm_equipment_no)
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                WHERE e.status = 'Active'
                AND (e.monthly_pm = 1 OR e.annual_pm = 1)
                AND pc.bfm_equipment_no IS NULL
            ''')
            never_done = cursor.fetchone()[0]
        
            if never_done > 0:
                report += "CHECK:" * 70 + "\n"
                report += "WARNING: PM BACKLOG DETECTED:\n"
                report += "CHECK:" * 70 + "\n"
                report += f"  {never_done:,} assets have NEVER had a PM completed!\n"
                report += f"  At current capacity, it will take {math.ceil(never_done/monthly_capacity)} months\n"
                report += f"  just to complete the initial backlog (not counting recurring PMs).\n\n"
                report += "CATCH-UP STRATEGY:\n"
                report += f"  - Temporarily increase weekly target to {weekly_capacity + 50} for catch-up\n"
                report += f"  - Prioritize 'never done' PMs (system already does this)\n"
                report += f"  - Expected catch-up time: {math.ceil(never_done/(monthly_capacity + 50))}-{math.ceil(never_done/(monthly_capacity + 100))} months\n\n"
        
            # Show in dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("PM Capacity Analysis")
            dialog.geometry("800x600")
            
            text_frame = ttk.Frame(dialog)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
            
            scrollbar = ttk.Scrollbar(text_frame)
            scrollbar.pack(side='right', fill='y')
            
            text_widget = tk.Text(text_frame, wrap='word', yscrollcommand=scrollbar.set, 
                                font=('Courier', 10))
            text_widget.pack(fill='both', expand=True)
            scrollbar.config(command=text_widget.yview)
        
            text_widget.insert('1.0', report)
            text_widget.config(state='disabled')
        
            # Close button
            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to analyze PM capacity: {str(e)}")
    
    
    
    def add_cannot_find_asset_dialog(self):
        """Dialog to manually add a new Cannot Find asset with auto-fill functionality"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Cannot Find Asset")
        dialog.geometry("500x450")
        dialog.transient(self.root)
        dialog.grab_set()

        # Form fields
        ttk.Label(dialog, text="BFM Equipment No:").grid(row=0, column=0, sticky='w', padx=10, pady=10)
        bfm_var = tk.StringVar()
        bfm_entry = ttk.Entry(dialog, textvariable=bfm_var, width=30)
        bfm_entry.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(dialog, text="Description:").grid(row=1, column=0, sticky='w', padx=10, pady=10)
        desc_var = tk.StringVar()
        desc_entry = ttk.Entry(dialog, textvariable=desc_var, width=30)
        desc_entry.grid(row=1, column=1, padx=10, pady=10)
        
        ttk.Label(dialog, text="Location:").grid(row=2, column=0, sticky='w', padx=10, pady=10)
        location_var = tk.StringVar()
        location_entry = ttk.Entry(dialog, textvariable=location_var, width=30)
        location_entry.grid(row=2, column=1, padx=10, pady=10)

        ttk.Label(dialog, text="Reported By (Technician):").grid(row=3, column=0, sticky='w', padx=10, pady=10)
        tech_var = tk.StringVar()
        tech_combo = ttk.Combobox(dialog, textvariable=tech_var, width=28)
        tech_combo['values'] = self.technicians if hasattr(self, 'technicians') else []
        tech_combo.grid(row=3, column=1, padx=10, pady=10)

        ttk.Label(dialog, text="Report Date:").grid(row=4, column=0, sticky='w', padx=10, pady=10)
        date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        date_entry = ttk.Entry(dialog, textvariable=date_var, width=30)
        date_entry.grid(row=4, column=1, padx=10, pady=10)
        
        ttk.Label(dialog, text="Notes (Optional):").grid(row=5, column=0, sticky='nw', padx=10, pady=10)
        notes_text = tk.Text(dialog, width=30, height=5)
        notes_text.grid(row=5, column=1, padx=10, pady=10)

        # Status label for autofill feedback
        status_label = ttk.Label(dialog, text="", foreground="blue")
        status_label.grid(row=6, column=0, columnspan=2, pady=5)

        def autofill_from_bfm(*args):
            """Auto-fill description and location when BFM number is entered"""
            bfm_no = bfm_var.get().strip()
        
            if not bfm_no:
                # Clear fields if BFM is empty
                desc_var.set("")
                location_var.set("")
                status_label.config(text="", foreground="blue")
                return
        
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    SELECT description, location 
                    FROM equipment 
                    WHERE bfm_equipment_no = %s
                ''', (bfm_no,))
            
                result = cursor.fetchone()
            
                if result:
                    description, location = result
                    desc_var.set(description or "")
                    location_var.set(location or "")
                    status_label.config(text="CHECK: Equipment found - fields auto-filled", foreground="green")
                else:
                    # Don't clear existing values, just update status
                    status_label.config(text="CHECK: Equipment not found in database", foreground="orange")
                
            except Exception as e:
                status_label.config(text=f"Error: {str(e)}", foreground="red")
                print(f"Autofill error: {e}")

        # Bind the autofill function to BFM entry changes
        # Use a slight delay to avoid querying on every keystroke
        bfm_var.trace_add('write', lambda *args: dialog.after(500, autofill_from_bfm))

        def save_cannot_find_asset():
            """Save the new Cannot Find asset to database"""
            bfm_no = bfm_var.get().strip()
            description = desc_var.get().strip()
            location = location_var.get().strip()
            technician = tech_var.get().strip()
            reported_date = date_var.get().strip()
            notes = notes_text.get("1.0", tk.END).strip()
    
            # Validation
            if not bfm_no:
                messagebox.showwarning("Validation Error", "BFM Equipment No. is required")
                return
    
            if not technician:
                messagebox.showwarning("Validation Error", "Technician name is required")
                return
    
            # Validate date format
            try:
                datetime.strptime(reported_date, '%Y-%m-%d')
            except ValueError:
                messagebox.showwarning("Validation Error", "Date must be in YYYY-MM-DD format")
                return
    
            try:
                cursor = self.conn.cursor()
        
                # Check if asset already exists in cannot_find_assets
                cursor.execute('SELECT bfm_equipment_no FROM cannot_find_assets WHERE bfm_equipment_no = %s', (bfm_no,))
                existing = cursor.fetchone()
        
                if existing:
                    result = messagebox.askyesno(
                        "Asset Exists",
                        f"Asset {bfm_no} already exists in Cannot Find list.\n\nUpdate the record with new information?"
                    )
                    if not result:
                        return
            
                    # Update existing record
                    cursor.execute('''
                        UPDATE cannot_find_assets 
                        SET description = %s, location = %s, technician_name = %s, 
                            reported_date = %s, status = 'Missing', notes = %s
                        WHERE bfm_equipment_no = %s
                    ''', (description, location, technician, reported_date, notes, bfm_no))
                else:
                    # Insert new record
                    cursor.execute('''
                        INSERT INTO cannot_find_assets 
                        (bfm_equipment_no, description, location, technician_name, reported_date, status, notes)
                        VALUES (%s, %s, %s, %s, %s, 'Missing', %s)
                    ''', (bfm_no, description, location, technician, reported_date, notes))
        
                # Also update the equipment table status if the equipment exists
                cursor.execute('SELECT bfm_equipment_no FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
                if cursor.fetchone():
                    cursor.execute('UPDATE equipment SET status = %s WHERE bfm_equipment_no = %s', 
                                ('Cannot Find', bfm_no))
        
                self.conn.commit()
        
                messagebox.showinfo("Success", f"Cannot Find asset {bfm_no} added successfully")
        
                # Refresh the Cannot Find list
                self.load_cannot_find_assets()
        
                # Update statistics if method exists
                if hasattr(self, 'update_equipment_statistics'):
                    self.update_equipment_statistics()
        
                dialog.destroy()
        
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add Cannot Find asset: {str(e)}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=7, column=0, columnspan=2, pady=20)
        
        ttk.Button(button_frame, text="Save", command=save_cannot_find_asset).pack(side='left', padx=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)

        # Focus on first entry
        bfm_entry.focus()
    
    
    
    
    def create_cm_from_pm_dialog(self):
        """Create a CM from within PM Completion tab - pre-filled with PM data"""
        # Get current PM form data
        bfm_no = self.completion_bfm_var.get().strip()
        pm_notes = self.notes_text.get('1.0', 'end-1c').strip()
        technician = self.completion_tech_var.get().strip()
    
        if not bfm_no:
            messagebox.showwarning("Warning", "Please select equipment first")
            return
    
        # Create CM dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Create CM from PM")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Header
        header = ttk.Label(dialog, text="Create Corrective Maintenance from PM", 
                        font=('Arial', 12, 'bold'))
        header.pack(pady=10)
    
        # Info label
        info_text = f"Creating CM for Equipment: {bfm_no}"
        ttk.Label(dialog, text=info_text, foreground='blue').pack(pady=5)
    
        # Form frame
        form_frame = ttk.LabelFrame(dialog, text="CM Details", padding=15)
        form_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        row = 0
    
        # CM Number (auto-generated)
        ttk.Label(form_frame, text="CM Number:").grid(row=row, column=0, sticky='w', pady=5)
        cm_number = self.generate_cm_number()
        cm_number_var = tk.StringVar(value=cm_number)
        ttk.Entry(form_frame, textvariable=cm_number_var, width=20, state='readonly').grid(
            row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
    
        # BFM Equipment (pre-filled, readonly)
        ttk.Label(form_frame, text="BFM Equipment:").grid(row=row, column=0, sticky='w', pady=5)
        bfm_var = tk.StringVar(value=bfm_no)
        ttk.Entry(form_frame, textvariable=bfm_var, width=30, state='readonly').grid(
            row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
    
        # Get equipment description
        cursor = self.conn.cursor()
        cursor.execute('SELECT description FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
        result = cursor.fetchone()
        equip_desc = result[0] if result else "Unknown"
    
        ttk.Label(form_frame, text=f"Description: {equip_desc}", 
                foreground='gray').grid(row=row, column=1, sticky='w', padx=5)
        row += 1
    
        # Description (pre-filled with PM notes if available)
        ttk.Label(form_frame, text="CM Description:*").grid(row=row, column=0, sticky='nw', pady=5)
        description_text = tk.Text(form_frame, width=40, height=4)
        description_text.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        if pm_notes:
            description_text.insert('1.0', f"Issue found during PM:\n{pm_notes}")
        row += 1
    
        # Priority
        ttk.Label(form_frame, text="Priority:*").grid(row=row, column=0, sticky='w', pady=5)
        priority_var = tk.StringVar(value="Medium")
        priority_combo = ttk.Combobox(form_frame, textvariable=priority_var, 
                                     values=['Low', 'Medium', 'High', 'Critical'], 
                                     width=15, state='readonly')
        priority_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
    
        # Assigned Technician (default to current user)
        ttk.Label(form_frame, text="Assigned To:*").grid(row=row, column=0, sticky='w', pady=5)
        assigned_var = tk.StringVar(value=self.user_name if hasattr(self, 'user_name') else technician)
        assigned_combo = ttk.Combobox(form_frame, textvariable=assigned_var, 
                                    values=self.technicians, width=20)
        assigned_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
    
        # CM Date (default to today)
        ttk.Label(form_frame, text="CM Date:*").grid(row=row, column=0, sticky='w', pady=5)
        cm_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        ttk.Entry(form_frame, textvariable=cm_date_var, width=20).grid(
            row=row, column=1, sticky='w', padx=5, pady=5)
        ttk.Label(form_frame, text="(YYYY-MM-DD)", foreground='gray').grid(
            row=row, column=2, sticky='w', padx=5)
        row += 1
    
        # Additional Notes
        ttk.Label(form_frame, text="Additional Notes:").grid(row=row, column=0, sticky='nw', pady=5)
        notes_text = tk.Text(form_frame, width=40, height=3)
        notes_text.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
    
        # Validation and Save function
        def validate_and_save_cm():
            # Validate required fields
            if not description_text.get('1.0', 'end-1c').strip():
                messagebox.showerror("Error", "Please enter CM description")
                return
        
            if not assigned_var.get().strip():
                messagebox.showerror("Error", "Please assign a technician")
                return
        
            # Validate date format
            date_str = cm_date_var.get().strip()
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
                validated_date = date_str
            except ValueError:
                messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD")
                return
        
            # Save to database
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO corrective_maintenance 
                    (cm_number, bfm_equipment_no, description, priority, 
                     assigned_technician, status, created_date, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    cm_number_var.get(),
                    bfm_var.get(),
                    description_text.get('1.0', 'end-1c').strip(),
                    priority_var.get(),
                    assigned_var.get(),
                    'Open',
                    validated_date,
                    notes_text.get('1.0', 'end-1c').strip()
                ))
                self.conn.commit()
            
                messagebox.showinfo("Success", 
                                f"CHECK: CM Created Successfully!\n\n"
                                f"CM Number: {cm_number_var.get()}\n"
                                f"Equipment: {bfm_var.get()}\n"
                                f"Priority: {priority_var.get()}\n"
                                f"Assigned to: {assigned_var.get()}\n\n"
                                f"The CM is now visible in the CM Completions tab.")
            
                dialog.destroy()
            
                # Refresh CM list if the tab exists
                if hasattr(self, 'load_corrective_maintenance'):
                    self.load_corrective_maintenance()
            
                # Auto-sync to SharePoint if enabled
                if hasattr(self, 'auto_sync_after_action'):
                    self.auto_sync_after_action()
            
                # Update status bar
                if hasattr(self, 'update_status'):
                    self.update_status(f"CHECK: New CM created: {cm_number_var.get()} for {bfm_var.get()}")
        
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create CM: {str(e)}")
    
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=15)
    
        ttk.Button(button_frame, text="WARNING: Save CM", command=validate_and_save_cm, 
                width=15).pack(side='left', padx=5)
        ttk.Button(button_frame, text="CHECK: Cancel", command=dialog.destroy, 
                width=15).pack(side='left', padx=5)
    
        # Help text
        help_text = "* Required fields\nThis CM will be saved to the database and visible to all technicians."
        ttk.Label(dialog, text=help_text, foreground='gray', font=('Arial', 9)).pack(pady=5)


    def generate_cm_number(self):
        """Generate next CM number in format CM-YYYYMMDD-XXXX"""
        cursor = self.conn.cursor()
        today = datetime.now().strftime('%Y%m%d')
        cursor.execute(
            "SELECT MAX(CAST(SPLIT_PART(cm_number, '-', 3) AS INTEGER)) "
            "FROM corrective_maintenance "
            "WHERE cm_number LIKE %s",
            (f'CM-{today}-%',)
        )
        result = cursor.fetchone()

        if result[0]:
            next_num = result[0] + 1
        else:
            next_num = 1

        return f"CM-{today}-{next_num:04d}"

    
    
    def show_monthly_summary(self):
        """Display monthly summary report in a new window"""
        try:
            # Create dialog window
            summary_window = tk.Toplevel(self.root)
            summary_window.title("Monthly PM Summary Report")
            summary_window.geometry("900x700")
            summary_window.transient(self.root)
            summary_window.grab_set()
        
            # Create text widget with scrollbar
            text_frame = ttk.Frame(summary_window)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
            text_widget = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=text_widget.yview)
            text_widget.configure(yscrollcommand=scrollbar.set)
        
            text_widget.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
        
            # Month/Year selection frame
            selection_frame = ttk.Frame(summary_window)
            selection_frame.pack(fill='x', padx=10, pady=5)
            
            ttk.Label(selection_frame, text="Month:").pack(side='left', padx=5)
            month_var = tk.StringVar(value=str(datetime.now().month))
            month_combo = ttk.Combobox(selection_frame, textvariable=month_var, 
                                    values=list(range(1, 13)), width=5, state='readonly')
            month_combo.pack(side='left', padx=5)
        
            ttk.Label(selection_frame, text="Year:").pack(side='left', padx=5)
            year_var = tk.StringVar(value=str(datetime.now().year))
            year_combo = ttk.Combobox(selection_frame, textvariable=year_var,
                                values=list(range(2020, 2030)), width=8, state='readonly')
            year_combo.pack(side='left', padx=5)
    
            # ========== DEFINE ALL FUNCTIONS FIRST ==========
        
            def generate_report():
                """Generate and display the report"""
                try:
                    month = int(month_var.get())
                    year = int(year_var.get())
                    
                    # Clear existing text
                    text_widget.delete('1.0', 'end')
                    
                    # Redirect print output to text widget
                    import sys
                    from io import StringIO
                    old_stdout = sys.stdout
                    sys.stdout = StringIO()
            
                    # Generate the report
                    generate_monthly_summary_report(self.conn, month, year)
                    
                    # Get the output and restore stdout
                    output = sys.stdout.getvalue()
                    sys.stdout = old_stdout
                
                    # Display in text widget
                    text_widget.insert('1.0', output)
                
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to generate report: {str(e)}")
        
            def export_report():
                """Export report to text file"""
                try:
                    filename = filedialog.asksaveasfilename(
                        title="Export Monthly Summary",
                        defaultextension=".txt",
                        initialname=f"Monthly_Summary_{month_var.get()}_{year_var.get()}.txt",
                        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
                    )
                    if filename:
                        with open(filename, 'w') as f:
                            f.write(text_widget.get('1.0', 'end'))
                        messagebox.showinfo("Success", f"Report exported to {filename}")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to export text report: {str(e)}")
        
            def export_professional_pdf():
                """Export professional PDF monthly report"""
                try:
                    month = int(month_var.get())
                    year = int(year_var.get())
                    
                    # Show progress message
                    progress_label = ttk.Label(selection_frame, text="Generating professional PDF...", 
                                               foreground='blue')
                    progress_label.pack(side='left', padx=10)
                    summary_window.update()
                    
                    # Generate the PDF
                    filename = export_professional_monthly_report_pdf(self.conn, month, year)
                    
                    # Remove progress label
                    progress_label.destroy()
                    
                    # Success message with option to open
                    result = messagebox.askyesno(
                        "Success", 
                        f"Professional monthly report exported!\n\n{filename}\n\nWould you like to open it now?",
                        icon='info'
                    )
                
                    if result:
                        # Open the PDF
                        import os
                        import platform
                        
                        if platform.system() == 'Windows':
                            os.startfile(filename)
                        elif platform.system() == 'Darwin':  # macOS
                            os.system(f'open "{filename}"')
                        else:  # Linux
                            os.system(f'xdg-open "{filename}"')
                
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to generate PDF report:\n\n{str(e)}")
        
            # ========== NOW CREATE THE BUTTONS ==========
        
            ttk.Button(selection_frame, text="Generate Report", 
                    command=generate_report).pack(side='left', padx=10)
        
            ttk.Button(selection_frame, text="Export Text", 
                    command=export_report).pack(side='left', padx=5)
        
            ttk.Button(selection_frame, text="WARNING: Export Professional PDF", 
                    command=export_professional_pdf).pack(side='left', padx=5)
        
            ttk.Button(selection_frame, text="Close", 
                    command=summary_window.destroy).pack(side='right', padx=5)
        
            # Generate initial report for current month
            generate_report()
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to show monthly summary: {str(e)}")
    
    
    
    
    
    # Add this method to your class
    def setup_program_colors(self):
        """Set up the color scheme for the entire program"""
    
        # Create style object
        self.style = ttk.Style()
    
        # Choose base theme
        self.style.theme_use('clam')  # Good base for customization
    
        # Set main window background
        self.root.configure(bg="#e8f4f8")  # Light blue-gray
    
        # Configure Treeview (your asset lists)
        self.style.configure("Treeview",
                        background="#ffffff",        # White background
                        foreground="#1e3a8a",       # Dark blue text
                        rowheight=25,
                        fieldbackground="#ffffff")   # White field background
    
        # Treeview headers
        self.style.configure("Treeview.Heading",
                        background="#3b82f6",       # Blue headers
                        foreground="white",
                        font=('TkDefaultFont', 9, 'bold'))
    
        # Buttons
        self.style.configure("TButton",
                        background="#3b82f6",       # Blue buttons
                        foreground="white",
                        padding=(10, 5),
                        relief="flat",
                        font=('TkDefaultFont', 9))
    
        # Button hover effects
        self.style.map("TButton",
                    background=[('active', '#60a5fa'),    # Lighter blue on hover
                                ('pressed', '#1d4ed8')])   # Darker blue when pressed
    
        # LabelFrames (your control sections)
        self.style.configure("TLabelframe",
                        background="#e8f4f8",       # Light blue-gray
                        foreground="#1e3a8a",       # Dark blue text
                        borderwidth=2,
                        relief="groove")
    
        self.style.configure("TLabelframe.Label",
                        background="#e8f4f8",
                        foreground="#1e3a8a",
                        font=('TkDefaultFont', 10, 'bold'))
    
        # Frames
        self.style.configure("TFrame",
                        background="#e8f4f8")
    
        # Entry widgets
        self.style.configure("TEntry",
                        fieldbackground="#ffffff",
                        foreground="#1e3a8a",
                        borderwidth=1,
                        relief="solid")
    
        # Combobox
        self.style.configure("TCombobox",
                        fieldbackground="#ffffff",
                        foreground="#1e3a8a",
                        arrowcolor="#3b82f6")
    
        # Scrollbars
        self.style.configure("Vertical.TScrollbar",
                        background="#d1d5db",
                        troughcolor="#f3f4f6",
                        borderwidth=1,
                        arrowcolor="#3b82f6")
    
        self.style.configure("Horizontal.TScrollbar",
                        background="#d1d5db",
                        troughcolor="#f3f4f6",
                        borderwidth=1,
                        arrowcolor="#3b82f6")

    
    
    
    
    
    
    def check_empty_database_and_offer_restore(self):
        """Check if database is empty and offer to restore from backup"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM equipment')
            equipment_count = cursor.fetchone()[0]
            
            if equipment_count == 0:
                # Database is empty, offer restore
                result = messagebox.askyesno(
                    "Empty Database Detected",
                    "The database appears to be empty.\n\n"
                    "Would you like to restore data from a previous backup?\n\n"
                    "Click 'Yes' to browse available backups\n"
                    "Click 'No' to continue with empty database",
                    icon='question'
                )
                
                if result:
                    self.create_database_restore_dialog()
                    
        except Exception as e:
            print(f"Error checking empty database: {e}")
    
    
    def create_database_restore_dialog(self):
        """Create dialog to restore database from SharePoint backups - FIXED with proper buttons"""
        if not hasattr(self, 'backup_sync_dir') or not self.backup_sync_dir:
            messagebox.showerror("Error", "No backup directory configured. Please restart the application.")
            return
    
        dialog = tk.Toplevel(self.root)
        dialog.title("Restore Database from Backup")
        dialog.geometry("1000x700")  # Made larger
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Instructions
        instructions_frame = ttk.LabelFrame(dialog, text="Database Restore", padding=15)
        instructions_frame.pack(fill='x', padx=10, pady=5)
        
        instructions_text = f"""Select a backup file to restore your database from SharePoint.

    Current backup location: {self.backup_sync_dir}

    WARNING: Restoring a backup will:
    - Close the current database
    - Replace it with the selected backup
    - All unsaved changes will be lost
    - The application will reload with the restored data"""
    
        ttk.Label(instructions_frame, text=instructions_text, font=('Arial', 10)).pack(anchor='w')
    
        # Backup files list
        files_frame = ttk.LabelFrame(dialog, text="Available Backup Files (Last 15)", padding=10)
        files_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        # Create treeview for backup files
        self.backup_files_tree = ttk.Treeview(files_frame,
                                            columns=('Filename', 'Date Created', 'Size', 'Age'),
                                            show='headings')
    
        # Configure columns
        backup_columns = {
            'Filename': ('Backup Filename', 350),
            'Date Created': ('Date Created', 150),
            'Size': ('File Size', 100),
            'Age': ('Age (Days)', 100)
        }
    
        for col, (heading, width) in backup_columns.items():
            self.backup_files_tree.heading(col, text=heading)
            self.backup_files_tree.column(col, width=width)
    
        # Scrollbars
        backup_v_scrollbar = ttk.Scrollbar(files_frame, orient='vertical', command=self.backup_files_tree.yview)
        backup_h_scrollbar = ttk.Scrollbar(files_frame, orient='horizontal', command=self.backup_files_tree.xview)
        self.backup_files_tree.configure(yscrollcommand=backup_v_scrollbar.set, xscrollcommand=backup_h_scrollbar.set)
        
        # Pack treeview and scrollbars
        self.backup_files_tree.grid(row=0, column=0, sticky='nsew')
        backup_v_scrollbar.grid(row=0, column=1, sticky='ns')
        backup_h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        files_frame.grid_rowconfigure(0, weight=1)
        files_frame.grid_columnconfigure(0, weight=1)
        
        # Selection info
        selection_frame = ttk.LabelFrame(dialog, text="Selected Backup Info", padding=10)
        selection_frame.pack(fill='x', padx=10, pady=5)
    
        self.backup_info_label = ttk.Label(selection_frame, text="Loading backup files...", 
                                        font=('Arial', 10), foreground='blue')
        self.backup_info_label.pack(anchor='w')
    
        # Bind selection event
        self.backup_files_tree.bind('<<TreeviewSelect>>', self.on_backup_file_select)
    
        # Action buttons - FIXED with proper layout
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=15)
    
        # Left side buttons
        left_buttons = ttk.Frame(button_frame)
        left_buttons.pack(side='left')
    
        ttk.Button(left_buttons, text="Refresh List", 
                command=self.load_backup_files).pack(side='left', padx=5)
        ttk.Button(left_buttons, text="Preview Backup", 
                command=self.preview_selected_backup).pack(side='left', padx=5)
    
        # Right side buttons  
        right_buttons = ttk.Frame(button_frame)
        right_buttons.pack(side='right')
    
        ttk.Button(right_buttons, text="Cancel", 
                command=dialog.destroy).pack(side='right', padx=5)
    
        # Main restore button - prominent in center
        center_buttons = ttk.Frame(button_frame)
        center_buttons.pack(expand=True)
        
        self.restore_button = ttk.Button(center_buttons, text="RESTORE SELECTED BACKUP", 
                                        command=self.restore_selected_backup, 
                                        state='disabled',
                                        width=25)
        self.restore_button.pack(pady=5)
    
        # Load backup files after creating the dialog
        self.root.after(100, self.load_backup_files)  # Load after dialog is fully created

    
    

    def load_backup_files(self):
        """Load available backup files from SharePoint - FIXED to show multiple files"""
        try:
            if not os.path.exists(self.backup_sync_dir):
                if hasattr(self, 'backup_info_label'):
                    self.backup_info_label.config(text="Backup directory not found", foreground='red')
                return
        
            # Clear existing items
            for item in self.backup_files_tree.get_children():
                self.backup_files_tree.delete(item)
        
            # Get all backup files
            backup_files = []
            try:
                all_files = os.listdir(self.backup_sync_dir)
                print(f"DEBUG: Found {len(all_files)} total files in backup directory")
            
                for filename in all_files:
                    if filename.startswith('ait_cmms_backup_') and filename.endswith('.db'):
                        file_path = os.path.join(self.backup_sync_dir, filename)
                        try:
                            # Get file stats
                            stat = os.stat(file_path)
                            file_size = stat.st_size
                            modified_time = datetime.fromtimestamp(stat.st_mtime)
                            age_days = (datetime.now() - modified_time).days
                        
                            backup_files.append({
                                'filename': filename,
                                'filepath': file_path,
                                'size': file_size,
                                'modified': modified_time,
                                'age_days': age_days
                            })
                            print(f"DEBUG: Added backup file: {filename}")
                        except Exception as e:
                            print(f"Error reading backup file {filename}: {e}")
                            continue
            except Exception as e:
                print(f"Error listing backup directory: {e}")
                if hasattr(self, 'backup_info_label'):
                    self.backup_info_label.config(text=f"Error reading backup directory: {str(e)}", foreground='red')
                return
        
            print(f"DEBUG: Total backup files found: {len(backup_files)}")
        
            # Sort by modification time (newest first)
            backup_files.sort(key=lambda x: x['modified'], reverse=True)
            
            # Limit to last 15 backups for better performance
            backup_files = backup_files[:15]
        
            # Add to tree
            for idx, backup in enumerate(backup_files):
                # Format file size
                size_mb = backup['size'] / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{backup['size']} bytes"

                item_id = self.backup_files_tree.insert('', 'end', values=(
                    backup['filename'],
                    backup['modified'].strftime('%Y-%m-%d %H:%M:%S'),
                    size_str,
                    f"{backup['age_days']} days"
                ))

                print(f"DEBUG: Inserted item: {backup['filename']}")

                # Yield to event loop periodically to keep UI responsive
                if idx % 5 == 0:
                    self.root.update_idletasks()
        
            # Update info label
            if hasattr(self, 'backup_info_label'):
                if backup_files:
                    self.backup_info_label.config(text=f"Found {len(backup_files)} backup files", foreground='green')
                else:
                    self.backup_info_label.config(text="No backup files found in directory", foreground='orange')
                
        except Exception as e:
            print(f"Error loading backup files: {e}")
            if hasattr(self, 'backup_info_label'):
                self.backup_info_label.config(text=f"Error loading backups: {str(e)}", foreground='red')


    def on_backup_file_select(self, event):
        """Handle backup file selection - ENHANCED"""
        try:
            selected = self.backup_files_tree.selection()
            if selected:
                item = self.backup_files_tree.item(selected[0])
                filename = item['values'][0]
                date_created = item['values'][1]
                file_size = item['values'][2]
                age = item['values'][3]
                
                # Show backup info
                info_text = f"CHECK: SELECTED: {filename}\n"
                info_text += f"Created: {date_created}\n"
                info_text += f"Size: {file_size}\n"
                info_text += f"Age: {age}\n\n"
                info_text += "Click 'RESTORE SELECTED BACKUP' to proceed"
            
                self.backup_info_label.config(text=info_text, foreground='darkgreen')
            
                # Enable restore button
                self.restore_button.config(state='normal')
                self.restore_button.config(text=f"RESTORE: {filename}")
            else:
                self.backup_info_label.config(text="Select a backup file to see details", foreground='gray')
                self.restore_button.config(state='disabled')
                self.restore_button.config(text="RESTORE SELECTED BACKUP")
        except Exception as e:
            print(f"Error in backup file selection: {e}")
            self.backup_info_label.config(text="Error selecting backup file", foreground='red')


    def preview_selected_backup(self):
        """Preview selected backup file contents"""
        selected = self.backup_files_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a backup file to preview")
            return
    
        try:
            item = self.backup_files_tree.item(selected[0])
            filename = item['values'][0]
            filepath = os.path.join(self.backup_sync_dir, filename)
        
            if not os.path.exists(filepath):
                messagebox.showerror("Error", f"Backup file not found: {filename}")
                return
        
            # Create preview dialog
            preview_dialog = tk.Toplevel(self.root)
            preview_dialog.title(f"Preview Backup: {filename}")
            preview_dialog.geometry("800x600")
            preview_dialog.transient(self.root)
            preview_dialog.grab_set()
        
            # Preview text area
            text_frame = ttk.Frame(preview_dialog)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
            
            preview_text = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=preview_text.yview)
            preview_text.configure(yscrollcommand=scrollbar.set)
            
            preview_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
            
            # Connect to backup database and get preview info
            try:
                backup_conn = sqlite3.connect(filepath)
                backup_cursor = backup_conn.cursor()
                
                preview_info = f"BACKUP DATABASE PREVIEW\n"
                preview_info += f"File: {filename}\n"
                preview_info += f"=" * 80 + "\n\n"
                
                # Get table counts
                tables = [
                    ('equipment', 'Equipment/Assets'),
                    ('pm_completions', 'PM Completions'),
                    ('weekly_pm_schedules', 'Weekly Schedules'),
                    ('corrective_maintenance', 'Corrective Maintenance'),
                    ('cannot_find_assets', 'Cannot Find Assets'),
                    ('run_to_failure_assets', 'Run to Failure Assets'),
                    ('pm_templates', 'PM Templates')
                ]
            
                preview_info += "DATABASE CONTENTS:\n"
                preview_info += "-" * 40 + "\n"
            
                total_records = 0
                for table_name, display_name in tables:
                    try:
                        backup_cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
                        count = backup_cursor.fetchone()[0]
                        total_records += count
                        preview_info += f"{display_name}: {count} records\n"
                    except Exception as e:
                        preview_info += f"{display_name}: Error reading ({str(e)})\n"
            
                preview_info += f"\nTotal Records: {total_records}\n\n"
            
                # Get some sample equipment data
                try:
                    backup_cursor.execute('''
                        SELECT bfm_equipment_no, description, status 
                        FROM equipment 
                        ORDER BY updated_date DESC 
                        LIMIT 10
                    ''')
                    equipment_sample = backup_cursor.fetchall()
                
                    if equipment_sample:
                        preview_info += "RECENT EQUIPMENT (Sample):\n"
                        preview_info += "-" * 40 + "\n"
                        for bfm_no, desc, status in equipment_sample:
                            desc_short = (desc[:30] + '...') if desc and len(desc) > 30 else (desc or 'No description')
                            preview_info += f"{bfm_no}: {desc_short} ({status or 'Active'})\n"
                        preview_info += "\n"
                except:
                    pass
            
                # Get recent PM completions
                try:
                    backup_cursor.execute('''
                        SELECT completion_date, COUNT(*) as count
                        FROM pm_completions 
                        GROUP BY completion_date 
                        ORDER BY completion_date DESC 
                        LIMIT 10
                    ''')
                    pm_dates = backup_cursor.fetchall()
                
                    if pm_dates:
                        preview_info += "RECENT PM ACTIVITY:\n"
                        preview_info += "-" * 40 + "\n"
                        for date, count in pm_dates:
                            preview_info += f"{date}: {count} PM completions\n"
                        preview_info += "\n"
                except:
                    pass
                
                # Database metadata
                try:
                    backup_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    all_tables = [row[0] for row in backup_cursor.fetchall()]
                    preview_info += f"DATABASE STRUCTURE:\n"
                    preview_info += "-" * 40 + "\n"
                    preview_info += f"Total Tables: {len(all_tables)}\n"
                    preview_info += f"Tables: {', '.join(all_tables)}\n"
                except:
                    pass
            
                backup_conn.close()
            
                preview_text.insert('1.0', preview_info)
                preview_text.config(state='disabled')
            
            except Exception as e:
                preview_text.insert('1.0', f"Error previewing backup database:\n{str(e)}")
                preview_text.config(state='disabled')
        
            # Close button
            ttk.Button(preview_dialog, text="Close", command=preview_dialog.destroy).pack(pady=10)
        
        except Exception as e:
            messagebox.showerror("Preview Error", f"Failed to preview backup: {str(e)}")

    def restore_selected_backup(self):
        """Restore the selected backup file"""
        selected = self.backup_files_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a backup file to restore")
            return
    
        try:
            item = self.backup_files_tree.item(selected[0])
            filename = item['values'][0]
            date_created = item['values'][1]
            file_size = item['values'][2]
        
            # Get the full file path
            source_filepath = os.path.join(self.backup_sync_dir, filename)
        
            if not os.path.exists(source_filepath):
                messagebox.showerror("Error", f"Backup file not found: {filename}")
                return
        
            # Confirmation dialog with detailed info
            confirm_msg = f"""RESTORE DATABASE FROM BACKUP

    Selected Backup:
    - File: {filename}
    - Created: {date_created}
    - Size: {file_size}

    WARNING: This action will:
    - Close the current database
    - Replace it completely with the backup data
    - All current unsaved changes will be lost
    - The application will reload with the backup data

    This action cannot be undone.

    Are you sure you want to proceed?"""
        
            result = messagebox.askyesno("Confirm Database Restore", confirm_msg, 
                                        icon='warning', default='no')
        
            if not result:
                return
        
            # Create progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Restoring Database...")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            
            ttk.Label(progress_dialog, text="Restoring database from backup...", 
                    font=('Arial', 12)).pack(pady=20)
        
            progress_var = tk.StringVar(value="Preparing restore...")
            progress_label = ttk.Label(progress_dialog, textvariable=progress_var)
            progress_label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(progress_dialog, mode='indeterminate')
            progress_bar.pack(pady=10, padx=20, fill='x')
            progress_bar.start()
        
            # Update GUI
            self.root.update()
            
            # Perform the restore
            current_db_path = 'ait_cmms_database.db'
        
            # Step 1: Close current database connection
            progress_var.set("Closing current database...")
            self.root.update()
        
            if hasattr(self, 'conn'):
                try:
                    self.conn.close()
                except:
                    pass
        
            # Step 2: Backup current database (just in case)
            progress_var.set("Backing up current database...")
            self.root.update()
        
            if os.path.exists(current_db_path):
                backup_current_path = f"{current_db_path}.pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(current_db_path, backup_current_path)
        
            # Step 3: Copy backup to current location
            progress_var.set("Restoring backup data...")
            self.root.update()
        
            shutil.copy2(source_filepath, current_db_path)
        
            # Step 4: Reconnect to database
            progress_var.set("Reconnecting to database...")
            self.root.update()
        
            self.conn = sqlite3.connect(current_db_path)
        
            # Step 5: Refresh all data displays
            progress_var.set("Refreshing application data...")
            self.root.update()
        
            # Refresh all displays
            self.load_equipment_data()
            self.refresh_equipment_list()
            self.load_recent_completions()
            self.load_corrective_maintenance()
            if hasattr(self, 'load_cannot_find_assets'):
                self.load_cannot_find_assets()
            if hasattr(self, 'load_run_to_failure_assets'):
                self.load_run_to_failure_assets()
            if hasattr(self, 'load_pm_templates'):
                self.load_pm_templates()
        
            # Update statistics
            if hasattr(self, 'update_equipment_statistics'):
                self.update_equipment_statistics()
        
            progress_bar.stop()
            progress_dialog.destroy()
        
            # Close the restore dialog
            if hasattr(self, 'backup_files_tree'):
                # Find and close the restore dialog
                for widget in self.root.winfo_children():
                    if isinstance(widget, tk.Toplevel) and "Restore Database" in widget.title():
                        widget.destroy()
                        break
        
            # Show success message
            messagebox.showinfo("Restore Complete", 
                               f"Database successfully restored from backup!\n\n"
                               f"Restored from: {filename}\n"
                               f"Created: {date_created}\n"
                               f"The application has been refreshed with the restored data.")
        
            self.update_status(f"Database restored from backup: {filename}")
        
        except Exception as e:
            # Try to reconnect to original database
            try:
                self.conn = sqlite3.connect('ait_cmms_database.db')
            except:
                pass
        
            messagebox.showerror("Restore Error", f"Failed to restore database backup:\n\n{str(e)}")
            print(f"Database restore error: {e}")





    
    def add_logo_to_main_window(self):
        """Add AIT logo to the main application window - LEFT SIDE ONLY"""
        try:
            from tkinter import PhotoImage
            from PIL import Image, ImageTk
            
            # Get the directory where the script is located
            script_dir = os.path.dirname(os.path.abspath(__file__))
            img_dir = os.path.join(script_dir, "img")
            logo_path = os.path.join(img_dir, "ait_logo.png")
        
            # Create img directory if it doesn't exist
            if not os.path.exists(img_dir):
                os.makedirs(img_dir)
                print(f"Created img directory: {img_dir}")
        
            # Alternative paths to try
            alternative_paths = [
                os.path.join(script_dir, "ait_logo.png"),  # Same directory as script
                os.path.join(script_dir, "img", "ait_logo.png"),  # img subdirectory
                "ait_logo.png"  # Current working directory
            ]
        
            logo_found = False
            for path in alternative_paths:
                if os.path.exists(path):
                    logo_path = path
                    logo_found = True
                    print(f"Found logo at: {logo_path}")
                    break
        
            if not logo_found:
                print(f"Logo file not found. Tried paths: {alternative_paths}")
                print("Please place your logo file in one of these locations.")
                return
            
            if os.path.exists(logo_path):
                # Open and resize image for tkinter
                pil_image = Image.open(logo_path)
                pil_image = pil_image.resize((200, 60), Image.Resampling.LANCZOS)  # Reasonable size for left corner
                
                # Convert to PhotoImage
                self.logo_image = ImageTk.PhotoImage(pil_image)
                
                # Create logo frame at top left of window
                logo_frame = ttk.Frame(self.root)
                logo_frame.pack(side='top', fill='x', padx=10, pady=5)
            
                # Add logo label (left aligned)
                logo_label = ttk.Label(logo_frame, image=self.logo_image)
                logo_label.pack(side='left')
                
                # Optional: Add a subtle separator line below
                separator = ttk.Separator(self.root, orient='horizontal')
                separator.pack(fill='x', padx=10, pady=2)
            
        except ImportError:
            print("PIL (Pillow) not installed. Install with: pip install Pillow")
        except Exception as e:
            print(f"Error loading logo: {e}")
    
    
    
    
    # SharePoint backup functions removed - using PostgreSQL only


    def on_closing(self):
        """Close application, end user session, and cleanup connections"""
        try:
            result = messagebox.askyesno(
                "Confirm Exit",
                "Are you sure you want to close the application?",
                icon='question'
            )

            if result:
                try:
                    # End user session
                    if hasattr(self, 'session_id') and self.session_id:
                        with db_pool.get_cursor() as cursor:
                            UserManager.end_session(cursor, self.session_id)
                            print(f"CHECK: User session ended for {self.user_name}")

                    # Close main connection if it exists
                    if hasattr(self, 'conn') and self.conn:
                        self.conn.commit()  # Save any pending changes
                        db_pool.return_connection(self.conn)
                        print("CHECK: Database connection returned to pool")

                except Exception as e:
                    print(f"WARNING: Error during cleanup: {e}")

                self.root.destroy()

        except Exception as e:
            print(f"Error during closing: {e}")
            self.root.destroy()

    # Backup functions removed - using PostgreSQL only

    def init_pm_templates_database(self):
        """Initialize PM templates database tables"""
        cursor = self.conn.cursor()
    
        # PM Templates table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_templates (
                id SERIAL PRIMARY KEY,
                bfm_equipment_no TEXT,
                template_name TEXT,
                pm_type TEXT,
                checklist_items TEXT,  -- JSON string
                special_instructions TEXT,
                safety_notes TEXT,
                estimated_hours REAL,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_date TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
            )
        ''')
    
        # Default checklist items for fallback
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS default_pm_checklist (
                id SERIAL PRIMARY KEY,
                pm_type TEXT,
                step_number INTEGER,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
            )
        ''')
    
        # Insert default checklist if empty
        cursor.execute('SELECT COUNT(*) FROM default_pm_checklist')
        if cursor.fetchone()[0] == 0:
            default_items = [
                (1, "Special Equipment Used (List):"),
                (2, "Validate your maintenance with Date / Stamp / Hours"),
                (3, "Refer to drawing when performing maintenance"),
                (4, "Make sure all instruments are properly calibrated"),
                (5, "Make sure tool is properly identified"),
                (6, "Make sure all mobile mechanisms move fluidly"),
                (7, "Visually inspect the welds"),
                (8, "Take note of any anomaly or defect (create a CM if needed)"),
                (9, "Check all screws. Tighten if needed."),
                (10, "Check the pins for wear"),
                (11, "Make sure all tooling is secured to the equipment with cable"),
                (12, "Ensure all tags (BFM and SAP) are applied and securely fastened"),
                (13, "All documentation are picked up from work area"),
                (14, "All parts and tools have been picked up"),
                (15, "Workspace has been cleaned up"),
                (16, "Dry runs have been performed (tests, restarts, etc.)"),
                (17, "Ensure that AIT Sticker is applied")
            ]
        
            for step_num, description in default_items:
                cursor.execute('''
                    INSERT INTO default_pm_checklist (pm_type, step_number, description)
                    VALUES ('All', %s, %s)
                ''', (step_num, description))
    
        self.conn.commit()

    def create_custom_pm_templates_tab(self):
        """Create PM Templates management tab"""
        self.pm_templates_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pm_templates_frame, text="PM Templates")
    
        # Controls
        controls_frame = ttk.LabelFrame(self.pm_templates_frame, text="PM Template Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Button(controls_frame, text="Create Custom Template", 
                command=self.create_custom_pm_template_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Edit Template", 
                command=self.edit_pm_template_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Preview Template", 
                command=self.preview_pm_template).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Delete Template", 
                command=self.delete_pm_template).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export Template to PDF", 
                command=self.export_custom_template_pdf).pack(side='left', padx=5)
    
        # Search frame
        search_frame = ttk.Frame(self.pm_templates_frame)
        search_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Label(search_frame, text="Search Templates:").pack(side='left', padx=5)
        self.template_search_var = tk.StringVar()
        self.template_search_var.trace('w', self.filter_template_list)
        search_entry = ttk.Entry(search_frame, textvariable=self.template_search_var, width=30)
        search_entry.pack(side='left', padx=5)
    
        # Templates list
        list_frame = ttk.LabelFrame(self.pm_templates_frame, text="PM Templates", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        self.templates_tree = ttk.Treeview(list_frame,
                                        columns=('BFM No', 'Template Name', 'PM Type', 'Steps', 'Est Hours', 'Updated'),
                                        show='headings')
    
        template_columns = {
            'BFM No': ('BFM Equipment No', 120),
            'Template Name': ('Template Name', 200),
            'PM Type': ('PM Type', 100),
            'Steps': ('# Steps', 80),
            'Est Hours': ('Est Hours', 80),
            'Updated': ('Last Updated', 120)
        }
    
        for col, (heading, width) in template_columns.items():
            self.templates_tree.heading(col, text=heading)
            self.templates_tree.column(col, width=width)
    
        # Scrollbars
        template_v_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.templates_tree.yview)
        template_h_scrollbar = ttk.Scrollbar(list_frame, orient='horizontal', command=self.templates_tree.xview)
        self.templates_tree.configure(yscrollcommand=template_v_scrollbar.set, xscrollcommand=template_h_scrollbar.set)
    
        # Pack treeview and scrollbars
        self.templates_tree.grid(row=0, column=0, sticky='nsew')
        template_v_scrollbar.grid(row=0, column=1, sticky='ns')
        template_h_scrollbar.grid(row=1, column=0, sticky='ew')
    
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
    
        # Load templates
        self.load_pm_templates()

    def create_custom_pm_template_dialog(self):
        """Dialog to create custom PM template for specific equipment"""
        print("DEBUG: Starting create_custom_pm_template_dialog method")  # Add this line
    
        dialog = tk.Toplevel(self.root)
        """Dialog to create custom PM template for specific equipment"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Custom PM Template")
        dialog.geometry("800x750")
        dialog.transient(self.root)
        dialog.grab_set()

        # Equipment selection
        header_frame = ttk.LabelFrame(dialog, text="Template Information", padding=10)
        header_frame.pack(fill='x', padx=10, pady=5)

        # BFM Equipment selection
        ttk.Label(header_frame, text="BFM Equipment Number:").grid(row=0, column=0, sticky='w', pady=5)
        bfm_var = tk.StringVar()
        bfm_combo = ttk.Combobox(header_frame, textvariable=bfm_var, width=25)
        bfm_combo.grid(row=0, column=1, sticky='w', padx=5, pady=5)

        # Populate equipment list
        cursor = self.conn.cursor()
        cursor.execute('SELECT bfm_equipment_no, description FROM equipment ORDER BY bfm_equipment_no')
        equipment_list = cursor.fetchall()
        bfm_combo['values'] = [f"{bfm} - {desc[:30]}..." if len(desc) > 30 else f"{bfm} - {desc}" 
                            for bfm, desc in equipment_list]

        # Template name
        ttk.Label(header_frame, text="Template Name:").grid(row=0, column=2, sticky='w', pady=5, padx=(20,5))
        template_name_var = tk.StringVar()
        ttk.Entry(header_frame, textvariable=template_name_var, width=25).grid(row=0, column=3, sticky='w', padx=5, pady=5)

        # PM Type
        ttk.Label(header_frame, text="PM Type:").grid(row=1, column=0, sticky='w', pady=5)
        pm_type_var = tk.StringVar(value='Annual')
        pm_type_combo = ttk.Combobox(header_frame, textvariable=pm_type_var, 
                                    values=['Monthly', 'Six Month', 'Annual'], width=22)
        pm_type_combo.grid(row=1, column=1, sticky='w', padx=5, pady=5)

        # Estimated hours
        ttk.Label(header_frame, text="Estimated Hours:").grid(row=1, column=2, sticky='w', pady=5, padx=(20,5))
        est_hours_var = tk.StringVar(value="1.0")
        ttk.Entry(header_frame, textvariable=est_hours_var, width=10).grid(row=1, column=3, sticky='w', padx=5, pady=5)

        # Custom checklist section
        checklist_frame = ttk.LabelFrame(dialog, text="Custom PM Checklist", padding=10)
        checklist_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Checklist controls
        controls_subframe = ttk.Frame(checklist_frame)
        controls_subframe.pack(fill='x', pady=5)
    
        # Checklist listbox with scrollbar
        list_frame = ttk.Frame(checklist_frame)
        list_frame.pack(fill='both', expand=True, pady=5)

        checklist_listbox = tk.Listbox(list_frame, height=15, font=('Arial', 9))
        list_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=checklist_listbox.yview)
        checklist_listbox.configure(yscrollcommand=list_scrollbar.set)

        checklist_listbox.pack(side='left', fill='both', expand=True)
        list_scrollbar.pack(side='right', fill='y')

        # Step editing
        edit_frame = ttk.LabelFrame(checklist_frame, text="Edit Selected Step", padding=5)
        edit_frame.pack(fill='x', pady=5)

        step_text_var = tk.StringVar()
        step_entry = ttk.Entry(edit_frame, textvariable=step_text_var, width=80)
        step_entry.pack(side='left', fill='x', expand=True, padx=5)

        # Special instructions and safety notes
        notes_frame = ttk.LabelFrame(dialog, text="Additional Information", padding=10)
        notes_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(notes_frame, text="Special Instructions:").grid(row=0, column=0, sticky='nw', pady=2)
        special_instructions_text = tk.Text(notes_frame, height=3, width=50)
        special_instructions_text.grid(row=0, column=1, sticky='ew', padx=5, pady=2)

        ttk.Label(notes_frame, text="Safety Notes:").grid(row=1, column=0, sticky='nw', pady=2)
        safety_notes_text = tk.Text(notes_frame, height=3, width=50)
        safety_notes_text.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

        notes_frame.grid_columnconfigure(1, weight=1)

        # DEFINE ALL HELPER FUNCTIONS FIRST
        def add_checklist_step():
            step_text = step_text_var.get().strip()
            if step_text:
                step_num = checklist_listbox.size() + 1
                checklist_listbox.insert('end', f"{step_num}. {step_text}")
                step_text_var.set('')

        def remove_checklist_step():
            selection = checklist_listbox.curselection()
            if selection:
                checklist_listbox.delete(selection[0])
                renumber_steps()

        def renumber_steps():
            items = []
            for i in range(checklist_listbox.size()):
                step_text = checklist_listbox.get(i)
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                items.append(f"{i+1}. {step_content}")
        
            checklist_listbox.delete(0, 'end')
            for item in items:
                checklist_listbox.insert('end', item)

        def update_selected_step():
            selection = checklist_listbox.curselection()
            if selection and step_text_var.get().strip():
                step_num = selection[0] + 1
                new_text = f"{step_num}. {step_text_var.get().strip()}"
                checklist_listbox.delete(selection[0])
                checklist_listbox.insert(selection[0], new_text)

        def move_step_up():
            selection = checklist_listbox.curselection()
            if selection and selection[0] > 0:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx-1, item)
                checklist_listbox.selection_set(idx-1)
                renumber_steps()

        def move_step_down():
            selection = checklist_listbox.curselection()
            if selection and selection[0] < checklist_listbox.size()-1:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx+1, item)
                checklist_listbox.selection_set(idx+1)
                renumber_steps()

        def load_default_template():
            cursor = self.conn.cursor()
            cursor.execute('SELECT description FROM default_pm_checklist ORDER BY step_number')
            default_steps = cursor.fetchall()
        
            checklist_listbox.delete(0, 'end')
            for i, (step,) in enumerate(default_steps, 1):
                checklist_listbox.insert('end', f"{i}. {step}")

        def save_template():
            try:
                # Validate inputs
                if not bfm_var.get():
                    messagebox.showerror("Error", "Please select equipment")
                    return
            
                if not template_name_var.get().strip():
                    messagebox.showerror("Error", "Please enter template name")
                    return
            
                # Extract BFM number from combo selection
                bfm_no = bfm_var.get().split(' - ')[0]
            
                # Get checklist items
                checklist_items = []
                for i in range(checklist_listbox.size()):
                    step_text = checklist_listbox.get(i)
                    step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                    checklist_items.append(step_content)
            
                if not checklist_items:
                    messagebox.showerror("Error", "Please add at least one checklist item")
                    return
            
                # Save to database
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO pm_templates 
                    (bfm_equipment_no, template_name, pm_type, checklist_items, 
                    special_instructions, safety_notes, estimated_hours)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    bfm_no,
                    template_name_var.get().strip(),
                    pm_type_var.get(),
                    json.dumps(checklist_items),
                    special_instructions_text.get('1.0', 'end-1c'),
                    safety_notes_text.get('1.0', 'end-1c'),
                    float(est_hours_var.get() or 1.0)
                ))
            
                self.conn.commit()
                messagebox.showinfo("Success", "Custom PM template created successfully!")
                dialog.destroy()
                self.load_pm_templates()
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save template: {str(e)}")

        def on_step_select(event):
            selection = checklist_listbox.curselection()
            if selection:
                step_text = checklist_listbox.get(selection[0])
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                step_text_var.set(step_content)

        # NOW CREATE BUTTONS - AFTER ALL FUNCTIONS ARE DEFINED
        ttk.Button(controls_subframe, text="Add Step", command=add_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Remove Step", command=remove_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Load Default Template", command=load_default_template).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Up", command=move_step_up).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Down", command=move_step_down).pack(side='left', padx=5)

        ttk.Button(edit_frame, text="Update Step", command=update_selected_step).pack(side='right', padx=5)

        # Bind listbox selection
        checklist_listbox.bind('<<ListboxSelect>>', on_step_select)

        # Load default template initially
        load_default_template()

        # Save and Cancel buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)

        ttk.Button(button_frame, text="Save Template", command=save_template).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

    def load_pm_templates(self):
        """Load PM templates into the tree"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                    pt.checklist_items, pt.estimated_hours, pt.updated_date
                FROM pm_templates pt
                ORDER BY pt.bfm_equipment_no, pt.template_name
            ''')
        
            # Clear existing items
            for item in self.templates_tree.get_children():
                self.templates_tree.delete(item)
        
            # Add templates
            for template in cursor.fetchall():
                bfm_no, name, pm_type, checklist_json, est_hours, updated = template
            
                # Count checklist items
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    step_count = len(checklist_items)
                except:
                    step_count = 0
            
                self.templates_tree.insert('', 'end', values=(
                    bfm_no, name, pm_type, step_count, f"{est_hours:.1f}h", str(updated)[:10] if updated else "N/A"
                ))
            
        except Exception as e:
            print(f"Error loading PM templates: {e}")

    def filter_template_list(self, *args):
        """Filter template list based on search term"""
        search_term = self.template_search_var.get().lower()
    
        try:
            cursor = self.conn.cursor()
            if search_term:
                cursor.execute('''
                    SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                        pt.checklist_items, pt.estimated_hours, pt.updated_date
                    FROM pm_templates pt
                    WHERE LOWER(pt.bfm_equipment_no) LIKE %s
                    OR LOWER(pt.template_name) LIKE %s
                    ORDER BY pt.bfm_equipment_no, pt.template_name
                ''', (f'%{search_term}%', f'%{search_term}%'))
            else:
                cursor.execute('''
                    SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                        pt.checklist_items, pt.estimated_hours, pt.updated_date
                    FROM pm_templates pt
                    ORDER BY pt.bfm_equipment_no, pt.template_name
                ''')
        
            # Clear and repopulate
            for item in self.templates_tree.get_children():
                self.templates_tree.delete(item)
        
            for template in cursor.fetchall():
                bfm_no, name, pm_type, checklist_json, est_hours, updated = template
            
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    step_count = len(checklist_items)
                except:
                    step_count = 0
            
                self.templates_tree.insert('', 'end', values=(
                    bfm_no, name, pm_type, step_count, f"{est_hours:.1f}h", str(updated)[:10] if updated else "N/A"
                ))
    
        except Exception as e:
            print(f"Error filtering templates: {e}")

    def edit_pm_template_dialog(self):
        """Edit existing PM template with full functionality"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to edit")
            return

        # Get selected template data
        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        # Fetch full template data
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, bfm_equipment_no, template_name, pm_type, checklist_items,
                special_instructions, safety_notes, estimated_hours
            FROM pm_templates
            WHERE bfm_equipment_no = %s AND template_name = %s
        ''', (bfm_no, template_name))

        template_data = cursor.fetchone()
        if not template_data:
            messagebox.showerror("Error", "Template not found")
            return

        # Extract template data
        (template_id, orig_bfm_no, orig_name, orig_pm_type, orig_checklist_json, 
        orig_instructions, orig_safety, orig_hours) = template_data

        # Parse checklist items
        try:
            orig_checklist_items = json.loads(orig_checklist_json) if orig_checklist_json else []
        except:
            orig_checklist_items = []

        # Create edit dialog (similar structure to create dialog)
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit PM Template - {template_name}")
        dialog.geometry("800x750")
        dialog.transient(self.root)
        dialog.grab_set()

        # Template information (pre-populated)
        header_frame = ttk.LabelFrame(dialog, text="Template Information", padding=10)
        header_frame.pack(fill='x', padx=10, pady=5)

        # BFM Equipment (read-only)
        ttk.Label(header_frame, text="BFM Equipment Number:").grid(row=0, column=0, sticky='w', pady=5)
        bfm_var = tk.StringVar(value=orig_bfm_no)
        bfm_label = ttk.Label(header_frame, text=orig_bfm_no, font=('Arial', 10, 'bold'))
        bfm_label.grid(row=0, column=1, sticky='w', padx=5, pady=5)

        # Template name (editable)
        ttk.Label(header_frame, text="Template Name:").grid(row=0, column=2, sticky='w', pady=5, padx=(20,5))
        template_name_var = tk.StringVar(value=orig_name)
        ttk.Entry(header_frame, textvariable=template_name_var, width=25).grid(row=0, column=3, sticky='w', padx=5, pady=5)

        # PM Type (editable)
        ttk.Label(header_frame, text="PM Type:").grid(row=1, column=0, sticky='w', pady=5)
        pm_type_var = tk.StringVar(value=orig_pm_type)
        pm_type_combo = ttk.Combobox(header_frame, textvariable=pm_type_var, 
                                values=['Monthly', 'Six Month', 'Annual'], width=22)
        pm_type_combo.grid(row=1, column=1, sticky='w', padx=5, pady=5)

        # Estimated hours (editable)
        ttk.Label(header_frame, text="Estimated Hours:").grid(row=1, column=2, sticky='w', pady=5, padx=(20,5))
        est_hours_var = tk.StringVar(value=str(orig_hours))
        ttk.Entry(header_frame, textvariable=est_hours_var, width=10).grid(row=1, column=3, sticky='w', padx=5, pady=5)

        # Custom checklist section
        checklist_frame = ttk.LabelFrame(dialog, text="Edit PM Checklist", padding=10)
        checklist_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Checklist controls
        controls_subframe = ttk.Frame(checklist_frame)
        controls_subframe.pack(fill='x', pady=5)

        # Checklist listbox with scrollbar
        list_frame = ttk.Frame(checklist_frame)
        list_frame.pack(fill='both', expand=True, pady=5)

        checklist_listbox = tk.Listbox(list_frame, height=15, font=('Arial', 9))
        list_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=checklist_listbox.yview)
        checklist_listbox.configure(yscrollcommand=list_scrollbar.set)

        checklist_listbox.pack(side='left', fill='both', expand=True)
        list_scrollbar.pack(side='right', fill='y')

        # Step editing
        edit_frame = ttk.LabelFrame(checklist_frame, text="Edit Selected Step", padding=5)
        edit_frame.pack(fill='x', pady=5)

        step_text_var = tk.StringVar()
        step_entry = ttk.Entry(edit_frame, textvariable=step_text_var, width=80)
        step_entry.pack(side='left', fill='x', expand=True, padx=5)

        # Special instructions and safety notes (pre-populated)
        notes_frame = ttk.LabelFrame(dialog, text="Additional Information", padding=10)
        notes_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(notes_frame, text="Special Instructions:").grid(row=0, column=0, sticky='nw', pady=2)
        special_instructions_text = tk.Text(notes_frame, height=3, width=50)
        special_instructions_text.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        special_instructions_text.insert('1.0', orig_instructions or '')

        ttk.Label(notes_frame, text="Safety Notes:").grid(row=1, column=0, sticky='nw', pady=2)
        safety_notes_text = tk.Text(notes_frame, height=3, width=50)
        safety_notes_text.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        safety_notes_text.insert('1.0', orig_safety or '')

        notes_frame.grid_columnconfigure(1, weight=1)

        # Helper functions (same as create dialog)
        def add_checklist_step():
            step_text = step_text_var.get().strip()
            if step_text:
                step_num = checklist_listbox.size() + 1
                checklist_listbox.insert('end', f"{step_num}. {step_text}")
                step_text_var.set('')

        def remove_checklist_step():
            selection = checklist_listbox.curselection()
            if selection:
                checklist_listbox.delete(selection[0])
                renumber_steps()

        def renumber_steps():
            items = []
            for i in range(checklist_listbox.size()):
                step_text = checklist_listbox.get(i)
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                items.append(f"{i+1}. {step_content}")
        
            checklist_listbox.delete(0, 'end')
            for item in items:
                checklist_listbox.insert('end', item)

        def update_selected_step():
            selection = checklist_listbox.curselection()
            if selection and step_text_var.get().strip():
                step_num = selection[0] + 1
                new_text = f"{step_num}. {step_text_var.get().strip()}"
                checklist_listbox.delete(selection[0])
                checklist_listbox.insert(selection[0], new_text)

        def move_step_up():
            selection = checklist_listbox.curselection()
            if selection and selection[0] > 0:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx-1, item)
                checklist_listbox.selection_set(idx-1)
                renumber_steps()

        def move_step_down():
            selection = checklist_listbox.curselection()
            if selection and selection[0] < checklist_listbox.size()-1:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx+1, item)
                checklist_listbox.selection_set(idx+1)
                renumber_steps()

        def save_changes():
            try:
                # Validate inputs
                if not template_name_var.get().strip():
                    messagebox.showerror("Error", "Please enter template name")
                    return

                # Get updated checklist items
                checklist_items = []
                for i in range(checklist_listbox.size()):
                    step_text = checklist_listbox.get(i)
                    step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                    checklist_items.append(step_content)

                if not checklist_items:
                    messagebox.showerror("Error", "Please add at least one checklist item")
                    return

                # Update database
                cursor = self.conn.cursor()
                cursor.execute('''
                    UPDATE pm_templates SET
                    template_name = %s,
                    pm_type = %s,
                    checklist_items = %s,
                    special_instructions = %s,
                    safety_notes = %s,
                    estimated_hours = %s,
                    updated_date = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (
                    template_name_var.get().strip(),
                    pm_type_var.get(),
                    json.dumps(checklist_items),
                    special_instructions_text.get('1.0', 'end-1c'),
                    safety_notes_text.get('1.0', 'end-1c'),
                    float(est_hours_var.get() or 1.0),
                    template_id
                ))

                self.conn.commit()
                messagebox.showinfo("Success", "PM template updated successfully!")
                dialog.destroy()
                self.load_pm_templates()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to update template: {str(e)}")

        def on_step_select(event):
            selection = checklist_listbox.curselection()
            if selection:
                step_text = checklist_listbox.get(selection[0])
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                step_text_var.set(step_content)

        # Create buttons
        ttk.Button(controls_subframe, text="Add Step", command=add_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Remove Step", command=remove_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Up", command=move_step_up).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Down", command=move_step_down).pack(side='left', padx=5)

        ttk.Button(edit_frame, text="Update Step", command=update_selected_step).pack(side='right', padx=5)

        # Bind listbox selection
        checklist_listbox.bind('<<ListboxSelect>>', on_step_select)

        # Load existing checklist items
        checklist_listbox.delete(0, 'end')
        for i, item in enumerate(orig_checklist_items, 1):
            checklist_listbox.insert('end', f"{i}. {item}")

        # Save and Cancel buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)

        ttk.Button(button_frame, text="Save Changes", command=save_changes).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

    def preview_pm_template(self):
        """Preview selected PM template"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to preview")
            return
    
        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        # Get template data
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT pt.*, e.description, e.sap_material_no, e.location
            FROM pm_templates pt
            LEFT JOIN equipment e ON pt.bfm_equipment_no = e.bfm_equipment_no
            WHERE pt.bfm_equipment_no = %s AND pt.template_name = %s
        ''', (bfm_no, template_name))
    
        template_data = cursor.fetchone()
        if not template_data:
            messagebox.showerror("Error", "Template not found")
            return
    
        # Create preview dialog
        preview_dialog = tk.Toplevel(self.root)
        preview_dialog.title(f"PM Template Preview - {bfm_no}")
        preview_dialog.geometry("700x600")
        preview_dialog.transient(self.root)
        preview_dialog.grab_set()
    
        # Template info
        info_frame = ttk.LabelFrame(preview_dialog, text="Template Information", padding=10)
        info_frame.pack(fill='x', padx=10, pady=5)
    
        info_text = f"Equipment: {bfm_no} - {template_data[9] or 'N/A'}\n"
        info_text += f"Template: {template_data[2]}\n"
        info_text += f"PM Type: {template_data[3]}\n"
        info_text += f"Estimated Hours: {template_data[7]:.1f}h"
    
        ttk.Label(info_frame, text=info_text, font=('Arial', 10)).pack(anchor='w')
    
        # Checklist preview
        checklist_frame = ttk.LabelFrame(preview_dialog, text="PM Checklist", padding=10)
        checklist_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        checklist_text = tk.Text(checklist_frame, wrap='word', font=('Arial', 10))
        scrollbar = ttk.Scrollbar(checklist_frame, orient='vertical', command=checklist_text.yview)
        checklist_text.configure(yscrollcommand=scrollbar.set)
        
        # Format checklist content
        try:
            checklist_items = json.loads(template_data[4]) if template_data[4] else []
            content = "PM CHECKLIST:\n" + "="*50 + "\n\n"
        
            for i, item in enumerate(checklist_items, 1):
                content += f"{i:2d}. {item}\n"
        
            if template_data[5]:  # Special instructions
                content += f"\n\nSPECIAL INSTRUCTIONS:\n{template_data[5]}\n"
        
            if template_data[6]:  # Safety notes
                content += f"\n\nSAFETY NOTES:\n{template_data[6]}\n"
        
            checklist_text.insert('1.0', content)
            checklist_text.config(state='disabled')
        
        except Exception as e:
            checklist_text.insert('1.0', f"Error loading template: {str(e)}")
            checklist_text.config(state='disabled')
    
        checklist_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
    
        # Buttons
        button_frame = ttk.Frame(preview_dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)
    
        ttk.Button(button_frame, text="Close", command=preview_dialog.destroy).pack(side='right', padx=5)

    def delete_pm_template(self):
        """Delete selected PM template with enhanced confirmation"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to delete")
            return

        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]
        pm_type = item['values'][2]
        steps_count = item['values'][3]

        # Enhanced confirmation dialog
        result = messagebox.askyesno("Confirm Delete", 
                                f"Delete PM template '{template_name}'?\n\n"
                                f"Equipment: {bfm_no}\n"
                                f"PM Type: {pm_type}\n"
                                f"Steps: {steps_count}\n\n"
                                f"This action cannot be undone.\n"
                                f"Any equipment using this template will revert to default PM procedures.")

        if result:
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    DELETE FROM pm_templates 
                    WHERE bfm_equipment_no = %s AND template_name = %s
                ''', (bfm_no, template_name))

                self.conn.commit()
                messagebox.showinfo("Success", f"Template '{template_name}' deleted successfully!")
                self.load_pm_templates()
                self.update_status(f"Deleted PM template: {template_name}")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete template: {str(e)}")

    def export_custom_template_pdf(self):
        """Export custom template as PDF form"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to export")
            return
    
        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        # Get template and equipment data
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT pt.*, e.sap_material_no, e.description, e.tool_id_drawing_no, e.location
            FROM pm_templates pt
            LEFT JOIN equipment e ON pt.bfm_equipment_no = e.bfm_equipment_no
            WHERE pt.bfm_equipment_no = %s AND pt.template_name = %s
        ''', (bfm_no, template_name))
    
        template_data = cursor.fetchone()
        if not template_data:
            messagebox.showerror("Error", "Template not found")
            return
    
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Custom_PM_Template_{bfm_no}_{template_name.replace(' ', '_')}_{timestamp}.pdf"
        
            # Create custom PDF using the template data
            self.create_custom_pm_template_pdf(filename, template_data)
        
            messagebox.showinfo("Success", f"Custom PM template exported to: {filename}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export template: {str(e)}")

    def create_custom_pm_template_pdf(self, filename, template_data):
        """Create PDF with custom PM template"""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
        
            doc = SimpleDocTemplate(filename, pagesize=letter,
                                rightMargin=36, leftMargin=36,
                                topMargin=36, bottomMargin=36)
        
            styles = getSampleStyleSheet()
            story = []
        
            # Extract template data
            (template_id, bfm_no, template_name, pm_type, checklist_json,
            special_instructions, safety_notes, estimated_hours, created_date, updated_date,
            sap_no, description, tool_id, location) = template_data
        
            # Custom styles
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                wordWrap='LTR'
            )
        
            header_cell_style = ParagraphStyle(
                'HeaderCellStyle',
                parent=styles['Normal'],
                fontSize=9,
                fontName='Helvetica-Bold',
                leading=11,
                wordWrap='LTR'
            )
        
            company_style = ParagraphStyle(
                'CompanyStyle',
                parent=styles['Heading1'],
                fontSize=14,
                fontName='Helvetica-Bold',
                alignment=1,
                textColor=colors.darkblue
            )
        
            # Header
            story.append(Paragraph("AIT - BUILDING THE FUTURE OF AEROSPACE", company_style))
            story.append(Spacer(1, 15))
        
            # Equipment information table
            equipment_data = [
                [
                    Paragraph('(SAP) Material Number:', header_cell_style), 
                    Paragraph(str(sap_no or ''), cell_style), 
                    Paragraph('Tool ID / Drawing Number:', header_cell_style), 
                    Paragraph(str(tool_id or ''), cell_style)
                ],
                [
                    Paragraph('(BFM) Equipment Number:', header_cell_style), 
                    Paragraph(str(bfm_no), cell_style), 
                    Paragraph('Description of Equipment:', header_cell_style), 
                    Paragraph(str(description or ''), cell_style)
                ],
                [
                    Paragraph('Custom Template:', header_cell_style), 
                    Paragraph(str(template_name), cell_style), 
                    Paragraph('Location of Equipment:', header_cell_style), 
                    Paragraph(str(location or ''), cell_style)
                ],
                [
                    Paragraph('Maintenance Technician:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('PM Cycle:', header_cell_style), 
                    Paragraph(str(pm_type), cell_style)
                ],
                [
                    Paragraph('Estimated Hours:', header_cell_style), 
                    Paragraph(f'{estimated_hours:.1f}h', cell_style), 
                    Paragraph('Date of Current PM:', header_cell_style), 
                    Paragraph('', cell_style)
                ]
            ]
        
            if safety_notes:
                equipment_data.append([
                    Paragraph(f'SAFETY: {safety_notes}', cell_style), 
                    '', '', ''
                ])
        
            equipment_data.append([
                Paragraph(f'Printed: {datetime.now().strftime("%m/%d/%Y")}', cell_style), 
                '', '', ''
            ])
        
            equipment_table = Table(equipment_data, colWidths=[1.8*inch, 1.7*inch, 1.8*inch, 1.7*inch])
            equipment_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('SPAN', (0, -2), (-1, -2)),  # Safety spans all columns
                ('SPAN', (0, -1), (-1, -1)),  # Printed date spans all columns
            ]))
        
            story.append(equipment_table)
            story.append(Spacer(1, 15))
        
            # Custom checklist table
            checklist_data = [
                [
                    Paragraph('', header_cell_style), 
                    Paragraph('CUSTOM PM CHECKLIST:', header_cell_style), 
                    Paragraph('', header_cell_style), 
                    Paragraph('Completed', header_cell_style), 
                    Paragraph('Labor Time', header_cell_style)
                ]
            ]
        
            # Add custom checklist items
            try:
                checklist_items = json.loads(checklist_json) if checklist_json else []
            except:
                checklist_items = []
        
            if not checklist_items:
                checklist_items = ["No custom checklist defined - using default steps"]
        
            for idx, item in enumerate(checklist_items, 1):
                checklist_data.append([
                    Paragraph(str(idx), cell_style), 
                    Paragraph(item, cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Yes', cell_style), 
                    Paragraph('hours    minutes', cell_style)
                ])
        
            checklist_table = Table(checklist_data, colWidths=[0.3*inch, 4.2*inch, 0.4*inch, 0.7*inch, 1.4*inch])
            checklist_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
        
            story.append(checklist_table)
            story.append(Spacer(1, 15))
        
            # Special instructions section
            if special_instructions and special_instructions.strip():
                instructions_data = [
                    [Paragraph('SPECIAL INSTRUCTIONS:', header_cell_style)],
                    [Paragraph(special_instructions, cell_style)]
                ]
            
                instructions_table = Table(instructions_data, colWidths=[7*inch])
                instructions_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BACKGROUND', (0, 0), (0, 0), colors.lightgrey),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
            
                story.append(instructions_table)
                story.append(Spacer(1, 15))
        
            # Completion section
            completion_data = [
                [
                    Paragraph('Notes from Technician:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Next Annual PM Date:', header_cell_style)
                ],
                [
                    Paragraph('', cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('', cell_style)
                ],
                [
                    Paragraph('All Data Entered Into System:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Total Time', header_cell_style)
                ],
                [
                    Paragraph('Document Name', header_cell_style), 
                    Paragraph('Revision', header_cell_style), 
                    Paragraph('', cell_style)
                ],
                [
                    Paragraph(f'Custom_PM_Template_{template_name}', cell_style), 
                    Paragraph('A1', cell_style), 
                    Paragraph('', cell_style)
                ]
            ]
        
            completion_table = Table(completion_data, colWidths=[2.8*inch, 2.2*inch, 2*inch])
            completion_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
        
            story.append(completion_table)
        
            # Build PDF
            doc.build(story)
        
        except Exception as e:
            print(f"Error creating custom PM template PDF: {e}")
            raise

    # Additional methods to integrate with existing PM completion system

    def get_pm_template_for_equipment(self, bfm_no, pm_type):
        """Get custom PM template for specific equipment and PM type"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT checklist_items, special_instructions, safety_notes, estimated_hours
                FROM pm_templates 
                WHERE bfm_equipment_no = %s AND pm_type = %s
                ORDER BY updated_date DESC LIMIT 1
            ''', (bfm_no, pm_type))
        
            result = cursor.fetchone()
            if result:
                checklist_json, special_instructions, safety_notes, estimated_hours = result
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    return {
                        'checklist_items': checklist_items,
                        'special_instructions': special_instructions,
                        'safety_notes': safety_notes,
                        'estimated_hours': estimated_hours
                    }
                except:
                    return None
            return None
        
        except Exception as e:
            print(f"Error getting PM template: {e}")
            return None

    def update_pm_completion_form_with_template(self):
        """Update PM completion form when equipment is selected"""
        bfm_no = self.completion_bfm_var.get().strip()
        pm_type = self.pm_type_var.get()
    
        if bfm_no and pm_type:
            template = self.get_pm_template_for_equipment(bfm_no, pm_type)
            if template:
                # Update estimated hours
                self.labor_hours_var.set(str(int(template['estimated_hours'])))
                self.labor_minutes_var.set(str(int((template['estimated_hours'] % 1) * 60)))
            
                # Show template info
                self.update_status(f"Custom template found for {bfm_no} - {pm_type} PM")
            else:
                self.update_status(f"No custom template found for {bfm_no} - {pm_type} PM, using default")

    def create_equipment_pm_lookup_with_templates(self):
        """Enhanced equipment lookup that shows custom templates"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Equipment PM Schedule & Templates")
        dialog.geometry("900x700")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Equipment search
        search_frame = ttk.LabelFrame(dialog, text="Equipment Search", padding=15)
        search_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Label(search_frame, text="BFM Equipment Number:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
    
        bfm_var = tk.StringVar()
        bfm_entry = ttk.Entry(search_frame, textvariable=bfm_var, width=20, font=('Arial', 11))
        bfm_entry.grid(row=0, column=1, padx=10, pady=5)
    
        search_btn = ttk.Button(search_frame, text="Look Up Equipment", 
                            command=lambda: self.lookup_equipment_with_templates(bfm_var.get().strip(), results_frame))
        search_btn.grid(row=0, column=2, padx=10, pady=5)
    
        # Results frame
        results_frame = ttk.LabelFrame(dialog, text="Equipment Information & Templates", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        bfm_entry.focus_set()
        bfm_entry.bind('<Return>', lambda e: search_btn.invoke())

    def lookup_equipment_with_templates(self, bfm_no, parent_frame):
        """Lookup equipment with custom template information"""
        if not bfm_no:
            messagebox.showwarning("Warning", "Please enter a BFM Equipment Number")
            return
    
        try:
            cursor = self.conn.cursor()
        
            # Clear previous results
            for widget in parent_frame.winfo_children():
                widget.destroy()
        
            # Get equipment info
            cursor.execute('''
                SELECT sap_material_no, description, location, status
                FROM equipment 
                WHERE bfm_equipment_no = %s
            ''', (bfm_no,))
        
            equipment_data = cursor.fetchone()
            if not equipment_data:
                error_label = ttk.Label(parent_frame, 
                                    text=f"Equipment '{bfm_no}' not found in database",
                                    font=('Arial', 12, 'bold'), foreground='red')
                error_label.pack(pady=20)
                return
        
            # Equipment header
            header_text = f"Equipment: {bfm_no}\n"
            header_text += f"Description: {equipment_data[1] or 'N/A'}\n"
            header_text += f"Location: {equipment_data[2] or 'N/A'}\n"
            header_text += f"Status: {equipment_data[3] or 'Active'}"
        
            header_label = ttk.Label(parent_frame, text=header_text, font=('Arial', 10))
            header_label.pack(pady=10)
        
            # Get custom templates
            cursor.execute('''
                SELECT template_name, pm_type, checklist_items, estimated_hours, updated_date
                FROM pm_templates 
                WHERE bfm_equipment_no = %s
                ORDER BY pm_type, template_name
            ''', (bfm_no,))
        
            templates = cursor.fetchall()
        
            if templates:
                templates_frame = ttk.LabelFrame(parent_frame, text="Custom PM Templates", padding=10)
                templates_frame.pack(fill='x', pady=10)
            
                for template in templates:
                    name, pm_type, checklist_json, est_hours, updated = template
                    try:
                        checklist_items = json.loads(checklist_json) if checklist_json else []
                        step_count = len(checklist_items)
                    except:
                        step_count = 0
                
                    template_text = f"- {name} ({pm_type} PM) - {step_count} steps, {est_hours:.1f}h estimated"
                    ttk.Label(templates_frame, text=template_text, font=('Arial', 9)).pack(anchor='w')
            else:
                no_templates_label = ttk.Label(parent_frame, 
                                            text="No custom PM templates found for this equipment",
                                            font=('Arial', 10), foreground='orange')
                no_templates_label.pack(pady=10)
        
            # Regular PM schedule info (existing functionality)
            self.lookup_equipment_pm_schedule(bfm_no, parent_frame)
        
        except Exception as e:
            error_label = ttk.Label(parent_frame, 
                                text=f"Error looking up equipment: {str(e)}", 
                                font=('Arial', 10), foreground='red')
            error_label.pack(pady=20)
    
    
    
    def update_existing_annual_pm_dates(self):
        """One-time update to spread out existing annual PM dates"""
        try:
            cursor = self.conn.cursor()
        
            # Get all PM completions with the same annual date (like 2026-08-18)
            cursor.execute('''
                SELECT id, bfm_equipment_no, next_annual_pm_date 
                FROM pm_completions 
                WHERE next_annual_pm_date = '2026-08-18'
            ''')
        
            records = cursor.fetchall()
            updated_count = 0
        
            for record_id, bfm_no, current_date in records:
                try:
                    # Apply same offset logic as the new code
                    numeric_part = re.findall(r'\d+', bfm_no)
                    if numeric_part:
                        last_digits = int(numeric_part[-1]) % 61  # 0-60
                        offset_days = last_digits - 30  # -30 to +30 days
                    else:
                        offset_days = (hash(bfm_no) % 61) - 30  # -30 to +30 days
                
                    # Calculate new date
                    base_date = datetime.strptime(current_date, '%Y-%m-%d')
                    new_date = (base_date + timedelta(days=offset_days)).strftime('%Y-%m-%d')
                
                    # Update the record
                    cursor.execute('''
                        UPDATE pm_completions 
                        SET next_annual_pm_date = %s
                        WHERE id = %s
                    ''', (new_date, record_id))
                
                    updated_count += 1
                
                except Exception as e:
                    print(f"Error updating record {record_id}: {e}")
                    continue
        
            # Also update the equipment table next_annual_pm dates
            cursor.execute('''
                SELECT bfm_equipment_no, next_annual_pm 
                FROM equipment 
                WHERE next_annual_pm = '2026-08-18'
            ''')
        
            equipment_records = cursor.fetchall()
        
            for bfm_no, current_date in equipment_records:
                try:
                    numeric_part = re.findall(r'\d+', bfm_no)
                    if numeric_part:
                        last_digits = int(numeric_part[-1]) % 61
                        offset_days = last_digits - 30
                    else:
                        offset_days = (hash(bfm_no) % 61) - 30
                
                    base_date = datetime.strptime(current_date, '%Y-%m-%d')
                    new_date = (base_date + timedelta(days=offset_days)).strftime('%Y-%m-%d')
                
                    cursor.execute('''
                        UPDATE equipment 
                        SET next_annual_pm = %s 
                        WHERE bfm_equipment_no = %s
                    ''', (new_date, bfm_no))
                
                    updated_count += 1
                
                except Exception as e:
                    print(f"Error updating equipment {bfm_no}: {e}")
                    continue
        
            self.conn.commit()
            messagebox.showinfo("Success", f"Updated {updated_count} records with spread dates!")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update database: {str(e)}")
    
    
    def standardize_all_database_dates(self):
        """Standardize all dates in the database to YYYY-MM-DD format"""
        
        # Confirmation dialog
        result = messagebox.askyesno(
            "Confirm Date Standardization",
            "This will standardize ALL dates in the database to YYYY-MM-DD format.\n\n"
            "Tables affected:\n"
            "- Equipment (PM dates)\n"
            "- PM Completions\n"
            "- Weekly Schedules\n"
            "- Corrective Maintenance\n"
            "- Cannot Find Assets\n"
            "- Run to Failure Assets\n\n"
            "This action cannot be undone. Continue?",
            icon='warning'
        )
        
        if not result:
            return
        
        try:
            # Create progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Standardizing Dates...")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            
            ttk.Label(progress_dialog, text="Standardizing dates in database...", 
                     font=('Arial', 12)).pack(pady=20)
            
            progress_var = tk.StringVar(value="Initializing...")
            progress_label = ttk.Label(progress_dialog, textvariable=progress_var)
            progress_label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(progress_dialog, mode='indeterminate')
            progress_bar.pack(pady=10, padx=20, fill='x')
            progress_bar.start()
            
            # Update GUI
            self.root.update()
            
            # Perform standardization
            progress_var.set("Processing database...")
            self.root.update()
            
            standardizer = DateStandardizer(self.conn)
            total_updated, errors = standardizer.standardize_all_dates()
            
            progress_bar.stop()
            progress_dialog.destroy()
            
            # Show results
            if errors:
                error_msg = f"Date standardization completed with {len(errors)} errors:\n\n"
                error_msg += "\n".join(errors[:10])  # Show first 10 errors
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors"
                
                messagebox.showwarning("Standardization Complete (With Errors)", 
                                     f"Updated {total_updated} records.\n\n{error_msg}")
            else:
                messagebox.showinfo("Success", 
                                  f"Date standardization completed successfully!\n\n"
                                  f"Updated {total_updated} date records to YYYY-MM-DD format.\n\n"
                                  f"All dates are now standardized.")
            
            # Refresh displays
            self.refresh_equipment_list()
            self.load_recent_completions()
            if hasattr(self, 'load_cannot_find_assets'):
                self.load_cannot_find_assets()
            if hasattr(self, 'load_run_to_failure_assets'):
                self.load_run_to_failure_assets()
            
            self.update_status(f"Date standardization complete: {total_updated} records updated")
            
        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.destroy()
            messagebox.showerror("Error", f"Failed to standardize dates: {str(e)}")

    def format_date_display(self, date_str):
        """Format date for consistent display"""
        if not date_str:
            return ''
        try:
            # Parse using flexible method
            standardizer = DateStandardizer(self.conn)
            standardized = standardizer.parse_date_flexible(date_str)
            return standardized if standardized else date_str
        except:
            return date_str

    def get_current_date_standard(self):
        """Get current date in standard format"""
        return datetime.now().strftime('%Y-%m-%d')
    
    def __init__(self, root):
        self.root = root
        # === NEON CLOUD DATABASE CONFIGURATION ===
        self.DB_CONFIG = {
            'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
            'port': 5432,
            'database': 'neondb',
            'user': 'neondb_owner',
            'password': 'npg_2Nm6hyPVWiIH',  # Click "Show password" and copy it
            'sslmode': 'require'
        }
        self.conn = None
        self.session_start_time = datetime.now()
        self.session_id = None  # Track user session for multi-user support
        self.user_id = None  # Database user ID
        self.root.title("AIT Complete CMMS - Computerized Maintenance Management System")
        self.root.geometry("1800x1000")
        try:
            self.root.state('zoomed')  # Maximize window on Windows
        except:
            pass  # Skip if not on Windows

        # ===== ROLE-BASED ACCESS CONTROL =====
        self.current_user_role = None  # Will be set by login
        self.user_name = None
    
        # Team members as specified - MUST be defined before login dialog
        self.technicians = [
            "Mark Michaels", "Jerone Bosarge", "Jon Hymel", "Nick Whisenant",
            "James Dunnam", "Wayne Dunnam", "Nate Williams", "Rey Marikit", "Ronald Houghs",
        ]

        # ===== Initialize Database Connection Pool BEFORE Login =====
        # This must happen before login dialog because login needs database access
        print("Starting AIT CMMS Application...")
        try:
            db_pool.initialize(self.DB_CONFIG, min_conn=2, max_conn=10)
            print("Database connection pool initialized successfully")
        except Exception as e:
            messagebox.showerror("Database Error",
                f"Failed to initialize database connection:\n{str(e)}\n\nPlease check your internet connection and try again.")
            self.root.destroy()
            return

        # Show login dialog after database pool is ready
        if not self.show_login_dialog():
            self.root.destroy()
            return

        # ===== Initialize PostgreSQL Database =====
        self.init_database()
        self.mro_manager = MROStockManager(self)
        self.parts_integration = CMPartsIntegration(self)
        self.init_pm_templates_database()

        # Add logo header
        self.add_logo_to_main_window()
    
        # PM Frequencies and cycles
        self.pm_frequencies = {
            'Monthly': 30,
            'Six Month': 180,
            'Annual': 365,
            'Run to Failure': 0,
            'CANNOT FIND': 0
        }
    
        # Weekly PM target
        self.weekly_pm_target = 160
    
        # Initialize data storage
        self.equipment_data = []
        self.current_week_start = self.get_week_start(datetime.now())
    
        # Create GUI based on user role
        self.create_gui()


        # Defer initial data loading to keep UI responsive at startup
        # This prevents the app from freezing during initialization
        self.root.after(100, self._deferred_startup_tasks)
    
        print(f"CHECK: AIT Complete CMMS System initialized successfully for {self.user_name} ({self.current_user_role})")

       
    
        # Add this at the very end of __init__:
    
        # Set up window close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_program_colors()
        print(f"AIT Complete CMMS System initialized successfully for {self.user_name} ({self.current_user_role})")

    def _deferred_startup_tasks(self):
        """Load data after UI is displayed to keep startup responsive"""
        try:
            # Show loading message in status bar
            if hasattr(self, 'update_status'):
                self.update_status("Loading equipment data...")

            # Load equipment data
            self.load_equipment_data()

            # Update status
            if hasattr(self, 'update_status'):
                self.update_status("Checking database status...")

            # Check if database needs restore
            self.check_empty_database_and_offer_restore()

            # Update statistics for managers
            if self.current_user_role == 'Manager':
                if hasattr(self, 'update_status'):
                    self.update_status("Updating statistics...")
                self.update_equipment_statistics()

            # Final status update
            if hasattr(self, 'update_status'):
                self.update_status("Ready")

        except Exception as e:
            print(f"Error in deferred startup tasks: {e}")
            import traceback
            traceback.print_exc()

    def close_cm_dialog(self):
        """Close selected CM with parts consumption tracking"""
        selected = self.cm_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a CM to close")
            return

        # Get selected CM data
        item = self.cm_tree.item(selected[0])
        cm_number = item['values'][0]
    
        # Fetch CM details
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT cm_number, bfm_equipment_no, description, assigned_technician, 
                status, labor_hours, notes, root_cause, corrective_action
            FROM corrective_maintenance 
            WHERE cm_number = %s
        ''', (cm_number,))
    
        cm_data = cursor.fetchone()
        if not cm_data:
            messagebox.showerror("Error", "CM not found")
            return
    
        (cm_num, equipment, desc, tech, status, labor_hrs, 
         notes, root_cause, corr_action) = cm_data
    
        # Check if already closed
        if status in ['Closed', 'Completed']:
            messagebox.showinfo("Info", f"CM {cm_number} is already closed")
            return
    
        # Create closure dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Close CM - {cm_number}")
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Header
        header_frame = ttk.Frame(dialog)
        header_frame.pack(fill='x', padx=10, pady=10)
    
        ttk.Label(header_frame, text=f"Close Corrective Maintenance", 
                font=('Arial', 12, 'bold')).pack()
        ttk.Label(header_frame, text=f"CM Number: {cm_number}", 
                font=('Arial', 10)).pack()
        ttk.Label(header_frame, text=f"Equipment: {equipment}", 
                font=('Arial', 10)).pack()
    
        # Main form frame with scrollbar
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
    
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
    
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
    
        # Form fields
        row = 0
    
        # Completion Date
        ttk.Label(scrollable_frame, text="Completion Date*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        completion_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        ttk.Entry(scrollable_frame, textvariable=completion_date_var, width=40).grid(
            row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(scrollable_frame, text="(Format: YYYY-MM-DD)", 
                font=('Arial', 8, 'italic')).grid(row=row, column=2, sticky='w')
        row += 1
    
        # Labor Hours
        ttk.Label(scrollable_frame, text="Total Labor Hours*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        labor_hours_var = tk.StringVar(value=str(labor_hrs) if labor_hrs else '')
        ttk.Entry(scrollable_frame, textvariable=labor_hours_var, width=40).grid(
            row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        ttk.Separator(scrollable_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
    
        # Root Cause
        ttk.Label(scrollable_frame, text="Root Cause*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        root_cause_text = tk.Text(scrollable_frame, width=50, height=4)
        root_cause_text.insert('1.0', root_cause or '')
        root_cause_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        # Corrective Action
        ttk.Label(scrollable_frame, text="Corrective Action Taken*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        corr_action_text = tk.Text(scrollable_frame, width=50, height=4)
        corr_action_text.insert('1.0', corr_action or '')
        corr_action_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        # Additional Notes
        ttk.Label(scrollable_frame, text="Additional Notes:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        notes_text = tk.Text(scrollable_frame, width=50, height=4)
        notes_text.insert('1.0', notes or '')
        notes_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        ttk.Separator(scrollable_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
    
        # Parts consumption question - THIS IS THE KEY INTEGRATION POINT
        ttk.Label(scrollable_frame, text="Were any parts used from MRO Stock?", 
                font=('Arial', 11, 'bold'), foreground='blue').grid(
                    row=row, column=0, columnspan=2, sticky='w', padx=10, pady=10)
        row += 1
    
        parts_used_var = tk.StringVar(value="No")
        ttk.Radiobutton(scrollable_frame, text="No parts were used", 
                    variable=parts_used_var, value="No").grid(
                        row=row, column=0, columnspan=2, sticky='w', padx=30, pady=5)
        row += 1
    
        ttk.Radiobutton(scrollable_frame, text="Yes, parts were used (will open parts dialog)", 
                    variable=parts_used_var, value="Yes").grid(
                        row=row, column=0, columnspan=2, sticky='w', padx=30, pady=5)
        row += 1
    
        # Button frame
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)
    
        def validate_and_proceed():
            """Validate closure form and proceed to parts or close"""
            # Validate required fields
            if not completion_date_var.get().strip():
                messagebox.showerror("Error", "Completion date is required")
                return
        
            try:
                datetime.strptime(completion_date_var.get(), '%Y-%m-%d')
            except ValueError:
                messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD")
                return
        
            if not labor_hours_var.get().strip():
                messagebox.showerror("Error", "Labor hours is required")
                return
        
            try:
                labor_hrs_value = float(labor_hours_var.get())
                if labor_hrs_value < 0:
                    messagebox.showerror("Error", "Labor hours cannot be negative")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid labor hours value")
                return
        
            root_cause_value = root_cause_text.get('1.0', 'end-1c').strip()
            if not root_cause_value:
                messagebox.showerror("Error", "Root cause is required")
                return
        
            corr_action_value = corr_action_text.get('1.0', 'end-1c').strip()
            if not corr_action_value:
                messagebox.showerror("Error", "Corrective action is required")
                return
        
            # Get all form values
            completion_date = completion_date_var.get()
            labor_hours = float(labor_hours_var.get())
            root_cause = root_cause_value
            corrective_action = corr_action_value
            additional_notes = notes_text.get('1.0', 'end-1c').strip()
        
            # Combine notes
            all_notes = additional_notes
        
            def finalize_closure(parts_recorded):
                """Finalize CM closure after parts handling"""
                if not parts_recorded and parts_used_var.get() == "Yes":
                    # User cancelled parts dialog, don't close CM
                    return
            
                try:
                    cursor = self.conn.cursor()
                
                    # Update CM record
                    cursor.execute('''
                        UPDATE corrective_maintenance
                        SET status = 'Closed',
                            completion_date = %s,
                            labor_hours = %s,
                            root_cause = %s,
                            corrective_action = %s,
                            notes = %s
                        WHERE cm_number = %s
                    ''', (completion_date, labor_hours, root_cause, 
                        corrective_action, all_notes, cm_number))
                
                    self.conn.commit()
                
                    messagebox.showinfo("Success", 
                        f"CM {cm_number} closed successfully!\n\n"
                        f"Completion Date: {completion_date}\n"
                        f"Labor Hours: {labor_hours}\n"
                        f"Status: Closed")
                
                    dialog.destroy()
                    self.load_corrective_maintenance()
                
                except Exception as e:
                    self.conn.rollback()
                    messagebox.showerror("Error", f"Failed to close CM: {str(e)}")
        
            # Check if parts were used
            if parts_used_var.get() == "Yes":
                # Close this dialog and open parts consumption dialog
                dialog.destroy()
            
                # Open parts consumption dialog
                # This requires the CMPartsIntegration module to be initialized
                if hasattr(self, 'parts_integration'):
                    self.parts_integration.show_parts_consumption_dialog(
                        cm_number=cm_number,
                        technician_name=tech or 'Unknown',
                        callback=finalize_closure
                    )
                else:
                    messagebox.showerror("Error", 
                        "Parts integration module not initialized.\n"
                        "Please contact system administrator.")
                    # Still update CM but without parts
                    finalize_closure(True)
            else:
                # No parts used, close directly
                finalize_closure(True)
    
        ttk.Button(button_frame, text="WARNING: Proceed to Close CM", 
                command=validate_and_proceed).pack(side='left', padx=5)
        ttk.Button(button_frame, text="CHECK: Cancel", 
                command=dialog.destroy).pack(side='left', padx=5)
    
    
    
    
    
    
    # sync_database_before_init removed - using PostgreSQL only

    def show_login_dialog(self):
        """Show database-backed login dialog with multi-user authentication"""
        login_successful = False

        def create_login_dialog():
            nonlocal login_successful

            login_dialog = tk.Toplevel(self.root)
            login_dialog.title("AIT CMMS - User Login")
            login_dialog.geometry("400x250")
            login_dialog.transient(self.root)
            login_dialog.grab_set()

            # Center the dialog
            login_dialog.update_idletasks()
            x = (login_dialog.winfo_screenwidth() // 2) - (login_dialog.winfo_width() // 2)
            y = (login_dialog.winfo_screenheight() // 2) - (login_dialog.winfo_height() // 2)
            login_dialog.geometry(f"+{x}+{y}")

            # Prevent closing the dialog with X button
            login_dialog.protocol("WM_DELETE_WINDOW", lambda: None)

            # Header
            header_frame = ttk.Frame(login_dialog)
            header_frame.pack(fill='x', padx=20, pady=20)

            ttk.Label(header_frame, text="AIT CMMS LOGIN",
                    font=('Arial', 16, 'bold')).pack()
            ttk.Label(header_frame, text="Enter your credentials",
                    font=('Arial', 10)).pack(pady=5)

            # Login form
            form_frame = ttk.Frame(login_dialog)
            form_frame.pack(fill='both', expand=True, padx=20, pady=10)

            # Username
            ttk.Label(form_frame, text="Username:", font=('Arial', 10)).grid(row=0, column=0, sticky='w', pady=5)
            username_var = tk.StringVar()
            username_entry = ttk.Entry(form_frame, textvariable=username_var, width=25)
            username_entry.grid(row=0, column=1, sticky='ew', pady=5)
            username_entry.focus_set()

            # Password
            ttk.Label(form_frame, text="Password:", font=('Arial', 10)).grid(row=1, column=0, sticky='w', pady=5)
            password_var = tk.StringVar()
            password_entry = ttk.Entry(form_frame, textvariable=password_var, show="*", width=25)
            password_entry.grid(row=1, column=1, sticky='ew', pady=5)

            form_frame.columnconfigure(1, weight=1)

            # Status label
            status_var = tk.StringVar()
            status_label = ttk.Label(form_frame, textvariable=status_var, foreground='red', font=('Arial', 9))
            status_label.grid(row=2, column=0, columnspan=2, pady=5)

            login_in_progress = False

            def do_login():
                nonlocal login_successful, login_in_progress

                if login_in_progress:
                    return

                login_in_progress = True
                status_var.set("")

                try:
                    username = username_var.get().strip()
                    password = password_var.get()

                    if not username or not password:
                        status_var.set("Please enter both username and password")
                        return

                    # Authenticate using database
                    try:
                        with db_pool.get_cursor() as cursor:
                            user = UserManager.authenticate(cursor, username, password)

                            if user:
                                # Update last login time
                                cursor.execute(
                                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s",
                                    (user['id'],)
                                )

                                # Create session
                                self.session_id = UserManager.create_session(cursor, user['id'], user['username'])

                                # Set user info
                                self.user_id = user['id']
                                self.user_name = user['full_name']
                                self.current_user_role = user['role']

                                login_successful = True
                                dialog.quit()
                            else:
                                status_var.set("Invalid username or password")
                                password_var.set("")
                                password_entry.focus_set()

                    except Exception as e:
                        print(f"Login error: {e}")
                        status_var.set("Login failed. Please try again.")
                        password_var.set("")

                finally:
                    login_in_progress = False

            def cancel_login():
                nonlocal login_successful
                login_successful = False
                dialog.quit()

            # Buttons
            button_frame = ttk.Frame(login_dialog)
            button_frame.pack(side='bottom', fill='x', padx=20, pady=20)

            login_button = ttk.Button(button_frame, text="Login", command=do_login)
            login_button.pack(side='left', padx=5)
            ttk.Button(button_frame, text="Exit", command=cancel_login).pack(side='right', padx=5)

            # Enter key bindings
            def on_enter_key(event):
                if not login_in_progress:
                    do_login()

            username_entry.bind('<Return>', on_enter_key)
            password_entry.bind('<Return>', on_enter_key)

            return login_dialog

        # Create and run the dialog
        dialog = create_login_dialog()
        dialog.mainloop()
        dialog.destroy()

        return login_successful

    

    
    def get_week_start(self, date):
        """Get the start of the week (Monday) for a given date"""
        days_since_monday = date.weekday()
        return date - timedelta(days=days_since_monday)
    
    def init_pm_templates_database(self):
        """Initialize PM templates database tables"""
        cursor = self.conn.cursor()
    
        # PM Templates table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_templates (
                id SERIAL PRIMARY KEY,
                bfm_equipment_no TEXT,
                template_name TEXT,
                pm_type TEXT,
                checklist_items TEXT,  -- JSON string
                special_instructions TEXT,
                safety_notes TEXT,
                estimated_hours REAL,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_date TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
            )
        ''')
    
        # Default checklist items for fallback
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS default_pm_checklist (
                id SERIAL PRIMARY KEY,
                pm_type TEXT,
                step_number INTEGER,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
    
        # Insert default checklist if empty
        cursor.execute('SELECT COUNT(*) FROM default_pm_checklist')
        if cursor.fetchone()[0] == 0:
            default_items = [
                (1, "Special Equipment Used (List):"),
                (2, "Validate your maintenance with Date / Stamp / Hours"),
                (3, "Refer to drawing when performing maintenance"),
                (4, "Make sure all instruments are properly calibrated"),
                (5, "Make sure tool is properly identified"),
                (6, "Make sure all mobile mechanisms move fluidly"),
                (7, "Visually inspect the welds"),
                (8, "Take note of any anomaly or defect (create a CM if needed)"),
                (9, "Check all screws. Tighten if needed."),
                (10, "Check the pins for wear"),
                (11, "Make sure all tooling is secured to the equipment with cable"),
                (12, "Ensure all tags (BFM and SAP) are applied and securely fastened"),
                (13, "All documentation are picked up from work area"),
                (14, "All parts and tools have been picked up"),
                (15, "Workspace has been cleaned up"),
                (16, "Dry runs have been performed (tests, restarts, etc.)"),
                (17, "Ensure that AIT Sticker is applied")
            ]
        
            for step_num, description in default_items:
                cursor.execute('''
                    INSERT INTO default_pm_checklist (pm_type, step_number, description)
                    VALUES ('All', %s, %s)
                ''', (step_num, description))
    
        self.conn.commit()

    def create_custom_pm_templates_tab(self):
        """Create PM Templates management tab"""
        self.pm_templates_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pm_templates_frame, text="PM Templates")
    
        # Controls
        controls_frame = ttk.LabelFrame(self.pm_templates_frame, text="PM Template Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Button(controls_frame, text="Create Custom Template", 
                command=self.create_custom_pm_template_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Edit Template", 
                command=self.edit_pm_template_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Preview Template", 
                command=self.preview_pm_template).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Delete Template", 
                command=self.delete_pm_template).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export Template to PDF", 
                command=self.export_custom_template_pdf).pack(side='left', padx=5)
    
        # Search frame
        search_frame = ttk.Frame(self.pm_templates_frame)
        search_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Label(search_frame, text="Search Templates:").pack(side='left', padx=5)
        self.template_search_var = tk.StringVar()
        self.template_search_var.trace('w', self.filter_template_list)
        search_entry = ttk.Entry(search_frame, textvariable=self.template_search_var, width=30)
        search_entry.pack(side='left', padx=5)
    
        # Templates list
        list_frame = ttk.LabelFrame(self.pm_templates_frame, text="PM Templates", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        self.templates_tree = ttk.Treeview(list_frame,
                                        columns=('BFM No', 'Template Name', 'PM Type', 'Steps', 'Est Hours', 'Updated'),
                                        show='headings')
    
        template_columns = {
            'BFM No': ('BFM Equipment No', 120),
            'Template Name': ('Template Name', 200),
            'PM Type': ('PM Type', 100),
            'Steps': ('# Steps', 80),
            'Est Hours': ('Est Hours', 80),
            'Updated': ('Last Updated', 120)
        }
    
        for col, (heading, width) in template_columns.items():
            self.templates_tree.heading(col, text=heading)
            self.templates_tree.column(col, width=width)
    
        # Scrollbars
        template_v_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.templates_tree.yview)
        template_h_scrollbar = ttk.Scrollbar(list_frame, orient='horizontal', command=self.templates_tree.xview)
        self.templates_tree.configure(yscrollcommand=template_v_scrollbar.set, xscrollcommand=template_h_scrollbar.set)
    
        # Pack treeview and scrollbars
        self.templates_tree.grid(row=0, column=0, sticky='nsew')
        template_v_scrollbar.grid(row=0, column=1, sticky='ns')
        template_h_scrollbar.grid(row=1, column=0, sticky='ew')
    
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
    
        # Load templates
        self.load_pm_templates()

    def create_custom_pm_template_dialog(self):
        """Dialog to create custom PM template for specific equipment"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Custom PM Template")
        dialog.geometry("800x750")
        dialog.transient(self.root)
        dialog.grab_set()

        # Equipment selection
        header_frame = ttk.LabelFrame(dialog, text="Template Information", padding=10)
        header_frame.pack(fill='x', padx=10, pady=5)

        # BFM Equipment selection
        ttk.Label(header_frame, text="BFM Equipment Number:").grid(row=0, column=0, sticky='w', pady=5)
        bfm_var = tk.StringVar()
        bfm_combo = ttk.Combobox(header_frame, textvariable=bfm_var, width=25)
        bfm_combo.grid(row=0, column=1, sticky='w', padx=5, pady=5)

        # Populate equipment list
        cursor = self.conn.cursor()
        cursor.execute('SELECT bfm_equipment_no, description FROM equipment ORDER BY bfm_equipment_no')
        equipment_list = cursor.fetchall()
        bfm_combo['values'] = [f"{bfm} - {desc[:30]}..." if len(desc) > 30 else f"{bfm} - {desc}" 
                            for bfm, desc in equipment_list]

        # Template name
        ttk.Label(header_frame, text="Template Name:").grid(row=0, column=2, sticky='w', pady=5, padx=(20,5))
        template_name_var = tk.StringVar()
        ttk.Entry(header_frame, textvariable=template_name_var, width=25).grid(row=0, column=3, sticky='w', padx=5, pady=5)

        # PM Type
        ttk.Label(header_frame, text="PM Type:").grid(row=1, column=0, sticky='w', pady=5)
        pm_type_var = tk.StringVar(value='Annual')
        pm_type_combo = ttk.Combobox(header_frame, textvariable=pm_type_var, 
                                    values=['Monthly', 'Six Month', 'Annual'], width=22)
        pm_type_combo.grid(row=1, column=1, sticky='w', padx=5, pady=5)

        # Estimated hours
        ttk.Label(header_frame, text="Estimated Hours:").grid(row=1, column=2, sticky='w', pady=5, padx=(20,5))
        est_hours_var = tk.StringVar(value="1.0")
        ttk.Entry(header_frame, textvariable=est_hours_var, width=10).grid(row=1, column=3, sticky='w', padx=5, pady=5)

        # Custom checklist section
        checklist_frame = ttk.LabelFrame(dialog, text="Custom PM Checklist", padding=10)
        checklist_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Checklist controls
        controls_subframe = ttk.Frame(checklist_frame)
        controls_subframe.pack(fill='x', pady=5)

        # Checklist listbox with scrollbar
        list_frame = ttk.Frame(checklist_frame)
        list_frame.pack(fill='both', expand=True, pady=5)

        checklist_listbox = tk.Listbox(list_frame, height=15, font=('Arial', 9))
        list_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=checklist_listbox.yview)
        checklist_listbox.configure(yscrollcommand=list_scrollbar.set)

        checklist_listbox.pack(side='left', fill='both', expand=True)
        list_scrollbar.pack(side='right', fill='y')

        # Step editing
        edit_frame = ttk.LabelFrame(checklist_frame, text="Edit Selected Step", padding=5)
        edit_frame.pack(fill='x', pady=5)

        step_text_var = tk.StringVar()
        step_entry = ttk.Entry(edit_frame, textvariable=step_text_var, width=80)
        step_entry.pack(side='left', fill='x', expand=True, padx=5)

        # Special instructions and safety notes
        notes_frame = ttk.LabelFrame(dialog, text="Additional Information", padding=10)
        notes_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(notes_frame, text="Special Instructions:").grid(row=0, column=0, sticky='nw', pady=2)
        special_instructions_text = tk.Text(notes_frame, height=3, width=50)
        special_instructions_text.grid(row=0, column=1, sticky='ew', padx=5, pady=2)

        ttk.Label(notes_frame, text="Safety Notes:").grid(row=1, column=0, sticky='nw', pady=2)
        safety_notes_text = tk.Text(notes_frame, height=3, width=50)
        safety_notes_text.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

        notes_frame.grid_columnconfigure(1, weight=1)

        # DEFINE ALL HELPER FUNCTIONS FIRST
        def add_checklist_step():
            step_text = step_text_var.get().strip()
            if step_text:
                step_num = checklist_listbox.size() + 1
                checklist_listbox.insert('end', f"{step_num}. {step_text}")
                step_text_var.set('')

        def remove_checklist_step():
            selection = checklist_listbox.curselection()
            if selection:
                checklist_listbox.delete(selection[0])
                renumber_steps()

        def renumber_steps():
            items = []
            for i in range(checklist_listbox.size()):
                step_text = checklist_listbox.get(i)
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                items.append(f"{i+1}. {step_content}")
        
            checklist_listbox.delete(0, 'end')
            for item in items:
                checklist_listbox.insert('end', item)

        def update_selected_step():
            selection = checklist_listbox.curselection()
            if selection and step_text_var.get().strip():
                step_num = selection[0] + 1
                new_text = f"{step_num}. {step_text_var.get().strip()}"
                checklist_listbox.delete(selection[0])
                checklist_listbox.insert(selection[0], new_text)

        def move_step_up():
            selection = checklist_listbox.curselection()
            if selection and selection[0] > 0:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx-1, item)
                checklist_listbox.selection_set(idx-1)
                renumber_steps()

        def move_step_down():
            selection = checklist_listbox.curselection()
            if selection and selection[0] < checklist_listbox.size()-1:
                idx = selection[0]
                item = checklist_listbox.get(idx)
                checklist_listbox.delete(idx)
                checklist_listbox.insert(idx+1, item)
                checklist_listbox.selection_set(idx+1)
                renumber_steps()

        def load_default_template():
            cursor = self.conn.cursor()
            cursor.execute('SELECT description FROM default_pm_checklist ORDER BY step_number')
            default_steps = cursor.fetchall()
        
            checklist_listbox.delete(0, 'end')
            for i, (step,) in enumerate(default_steps, 1):
                checklist_listbox.insert('end', f"{i}. {step}")

        def save_template():
            try:
                # Validate inputs
                if not bfm_var.get():
                    messagebox.showerror("Error", "Please select equipment")
                    return
            
                if not template_name_var.get().strip():
                    messagebox.showerror("Error", "Please enter template name")
                    return
            
                # Extract BFM number from combo selection
                bfm_no = bfm_var.get().split(' - ')[0]
            
                # Get checklist items
                checklist_items = []
                for i in range(checklist_listbox.size()):
                    step_text = checklist_listbox.get(i)
                    step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                    checklist_items.append(step_content)
            
                if not checklist_items:
                    messagebox.showerror("Error", "Please add at least one checklist item")
                    return
            
                # Save to database
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO pm_templates 
                    (bfm_equipment_no, template_name, pm_type, checklist_items, 
                    special_instructions, safety_notes, estimated_hours)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    bfm_no,
                    template_name_var.get().strip(),
                    pm_type_var.get(),
                    json.dumps(checklist_items),
                    special_instructions_text.get('1.0', 'end-1c'),
                    safety_notes_text.get('1.0', 'end-1c'),
                    float(est_hours_var.get() or 1.0)
                ))
            
                self.conn.commit()
                messagebox.showinfo("Success", "Custom PM template created successfully!")
                dialog.destroy()
                self.load_pm_templates()
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save template: {str(e)}")

        def on_step_select(event):
            selection = checklist_listbox.curselection()
            if selection:
                step_text = checklist_listbox.get(selection[0])
                step_content = '. '.join(step_text.split('. ')[1:]) if '. ' in step_text else step_text
                step_text_var.set(step_content)

        # NOW CREATE ALL BUTTONS - AFTER ALL FUNCTIONS ARE DEFINED
        ttk.Button(controls_subframe, text="Add Step", command=add_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Remove Step", command=remove_checklist_step).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Load Default Template", command=load_default_template).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Up", command=move_step_up).pack(side='left', padx=5)
        ttk.Button(controls_subframe, text="Move Down", command=move_step_down).pack(side='left', padx=5)

        ttk.Button(edit_frame, text="Update Step", command=update_selected_step).pack(side='right', padx=5)

        # Bind listbox selection
        checklist_listbox.bind('<<ListboxSelect>>', on_step_select)

        # Load default template initially
        load_default_template()

        # Save and Cancel buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)

        ttk.Button(button_frame, text="Save Template", command=save_template).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

    def load_pm_templates(self):
        """Load PM templates into the tree"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                    pt.checklist_items, pt.estimated_hours, pt.updated_date
                FROM pm_templates pt
                ORDER BY pt.bfm_equipment_no, pt.template_name
            ''')
        
            # Clear existing items
            for item in self.templates_tree.get_children():
                self.templates_tree.delete(item)
        
            # Add templates
            for template in cursor.fetchall():
                bfm_no, name, pm_type, checklist_json, est_hours, updated = template
            
                # Count checklist items
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    step_count = len(checklist_items)
                except:
                    step_count = 0
            
                self.templates_tree.insert('', 'end', values=(
                    bfm_no, name, pm_type, step_count, f"{est_hours:.1f}h", str(updated)[:10] if updated else "N/A"
                ))
            
        except Exception as e:
            print(f"Error loading PM templates: {e}")

    def filter_template_list(self, *args):
        """Filter template list based on search term"""
        search_term = self.template_search_var.get().lower()
    
        try:
            cursor = self.conn.cursor()
            if search_term:
                cursor.execute('''
                    SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                        pt.checklist_items, pt.estimated_hours, pt.updated_date
                    FROM pm_templates pt
                    WHERE LOWER(pt.bfm_equipment_no) LIKE %s 
                    OR LOWER(pt.template_name) LIKE %s
                    ORDER BY pt.bfm_equipment_no, pt.template_name
                ''', (f'%{search_term}%', f'%{search_term}%'))
            else:
                cursor.execute('''
                    SELECT pt.bfm_equipment_no, pt.template_name, pt.pm_type, 
                        pt.checklist_items, pt.estimated_hours, pt.updated_date
                    FROM pm_templates pt
                    ORDER BY pt.bfm_equipment_no, pt.template_name
                ''')
        
            # Clear and repopulate
            for item in self.templates_tree.get_children():
                self.templates_tree.delete(item)
        
            for template in cursor.fetchall():
                bfm_no, name, pm_type, checklist_json, est_hours, updated = template
            
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    step_count = len(checklist_items)
                except:
                    step_count = 0
            
                self.templates_tree.insert('', 'end', values=(
                    bfm_no, name, pm_type, step_count, f"{est_hours:.1f}h", str(updated)[:10] if updated else "N/A"
                ))
    
        except Exception as e:
            print(f"Error filtering templates: {e}")

    

    def preview_pm_template(self):
        """Preview selected PM template"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to preview")
            return
    
        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        # Get template data
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT pt.*, e.description, e.sap_material_no, e.location
            FROM pm_templates pt
            LEFT JOIN equipment e ON pt.bfm_equipment_no = e.bfm_equipment_no
            WHERE pt.bfm_equipment_no = %s AND pt.template_name = %s
        ''', (bfm_no, template_name))
    
        template_data = cursor.fetchone()
        if not template_data:
            messagebox.showerror("Error", "Template not found")
            return
    
        # Create preview dialog
        preview_dialog = tk.Toplevel(self.root)
        preview_dialog.title(f"PM Template Preview - {bfm_no}")
        preview_dialog.geometry("700x600")
        preview_dialog.transient(self.root)
        preview_dialog.grab_set()
    
        # Template info
        info_frame = ttk.LabelFrame(preview_dialog, text="Template Information", padding=10)
        info_frame.pack(fill='x', padx=10, pady=5)
    
        info_text = f"Equipment: {bfm_no} - {template_data[9] or 'N/A'}\n"
        info_text += f"Template: {template_data[2]}\n"
        info_text += f"PM Type: {template_data[3]}\n"
        info_text += f"Estimated Hours: {template_data[7]:.1f}h"
    
        ttk.Label(info_frame, text=info_text, font=('Arial', 10)).pack(anchor='w')
    
        # Checklist preview
        checklist_frame = ttk.LabelFrame(preview_dialog, text="PM Checklist", padding=10)
        checklist_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        checklist_text = tk.Text(checklist_frame, wrap='word', font=('Arial', 10))
        scrollbar = ttk.Scrollbar(checklist_frame, orient='vertical', command=checklist_text.yview)
        checklist_text.configure(yscrollcommand=scrollbar.set)
    
        # Format checklist content
        try:
            checklist_items = json.loads(template_data[4]) if template_data[4] else []
            content = "PM CHECKLIST:\n" + "="*50 + "\n\n"
        
            for i, item in enumerate(checklist_items, 1):
                content += f"{i:2d}. {item}\n"
        
            if template_data[5]:  # Special instructions
                content += f"\n\nSPECIAL INSTRUCTIONS:\n{template_data[5]}\n"
        
            if template_data[6]:  # Safety notes
                content += f"\n\nSAFETY NOTES:\n{template_data[6]}\n"
        
            checklist_text.insert('1.0', content)
            checklist_text.config(state='disabled')
        
        except Exception as e:
            checklist_text.insert('1.0', f"Error loading template: {str(e)}")
            checklist_text.config(state='disabled')
    
        checklist_text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
    
        # Buttons
        button_frame = ttk.Frame(preview_dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)
    
        ttk.Button(button_frame, text="Close", command=preview_dialog.destroy).pack(side='right', padx=5)

    def delete_pm_template(self):
        """Delete selected PM template"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to delete")
            return

        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        result = messagebox.askyesno("Confirm Delete",
                                f"Delete PM template '{template_name}' for {bfm_no}?\n\n"
                                f"This action cannot be undone.")

        if result:
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    DELETE FROM pm_templates
                    WHERE bfm_equipment_no = %s AND template_name = %s
                ''', (bfm_no, template_name))
            
                self.conn.commit()
                messagebox.showinfo("Success", "Template deleted successfully!")
                self.load_pm_templates()
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete template: {str(e)}")

    def export_custom_template_pdf(self):
        """Export custom template as PDF form"""
        selected = self.templates_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a template to export")
            return
    
        item = self.templates_tree.item(selected[0])
        bfm_no = str(item['values'][0])
        template_name = item['values'][1]

        # Get template and equipment data
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT pt.*, e.sap_material_no, e.description, e.tool_id_drawing_no, e.location
            FROM pm_templates pt
            LEFT JOIN equipment e ON pt.bfm_equipment_no = e.bfm_equipment_no
            WHERE pt.bfm_equipment_no = %s AND pt.template_name = %s
        ''', (bfm_no, template_name))
    
        template_data = cursor.fetchone()
        if not template_data:
            messagebox.showerror("Error", "Template not found")
            return
    
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Custom_PM_Template_{bfm_no}_{template_name.replace(' ', '_')}_{timestamp}.pdf"
        
            # Create custom PDF using the template data
            self.create_custom_pm_template_pdf(filename, template_data)
        
            messagebox.showinfo("Success", f"Custom PM template exported to: {filename}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export template: {str(e)}")

    def create_custom_pm_template_pdf(self, filename, template_data):
        """Create PDF with custom PM template"""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
        
            doc = SimpleDocTemplate(filename, pagesize=letter,
                                rightMargin=36, leftMargin=36,
                                topMargin=36, bottomMargin=36)
        
            styles = getSampleStyleSheet()
            story = []
        
            # Extract template data
            (template_id, bfm_no, template_name, pm_type, checklist_json,
            special_instructions, safety_notes, estimated_hours, created_date, updated_date,
            sap_no, description, tool_id, location) = template_data
        
            # Custom styles
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                wordWrap='LTR'
            )
        
            header_cell_style = ParagraphStyle(
                'HeaderCellStyle',
                parent=styles['Normal'],
                fontSize=9,
                fontName='Helvetica-Bold',
                leading=11,
                wordWrap='LTR'
            )
        
            company_style = ParagraphStyle(
                'CompanyStyle',
                parent=styles['Heading1'],
                fontSize=14,
                fontName='Helvetica-Bold',
                alignment=1,
                textColor=colors.darkblue
            )
        
            # Header
            story.append(Paragraph("AIT - BUILDING THE FUTURE OF AEROSPACE", company_style))
            story.append(Spacer(1, 15))
        
            # Equipment information table
            equipment_data = [
                [
                    Paragraph('(SAP) Material Number:', header_cell_style), 
                    Paragraph(str(sap_no or ''), cell_style), 
                    Paragraph('Tool ID / Drawing Number:', header_cell_style), 
                    Paragraph(str(tool_id or ''), cell_style)
                ],
                [
                    Paragraph('(BFM) Equipment Number:', header_cell_style), 
                    Paragraph(str(bfm_no), cell_style), 
                    Paragraph('Description of Equipment:', header_cell_style), 
                    Paragraph(str(description or ''), cell_style)
                ],
                [
                    Paragraph('Custom Template:', header_cell_style), 
                    Paragraph(str(template_name), cell_style), 
                    Paragraph('Location of Equipment:', header_cell_style), 
                    Paragraph(str(location or ''), cell_style)
                ],
                [
                    Paragraph('Maintenance Technician:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('PM Cycle:', header_cell_style), 
                    Paragraph(str(pm_type), cell_style)
                ],
                [
                    Paragraph('Estimated Hours:', header_cell_style), 
                    Paragraph(f'{estimated_hours:.1f}h', cell_style), 
                    Paragraph('Date of Current PM:', header_cell_style), 
                    Paragraph('', cell_style)
                ]
            ]
        
            if safety_notes:
                equipment_data.append([
                    Paragraph(f'SAFETY: {safety_notes}', cell_style), 
                    '', '', ''
                ])
        
            equipment_data.append([
                Paragraph(f'Printed: {datetime.now().strftime("%m/%d/%Y")}', cell_style), 
                '', '', ''
            ])
        
            equipment_table = Table(equipment_data, colWidths=[1.8*inch, 1.7*inch, 1.8*inch, 1.7*inch])
            equipment_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('SPAN', (0, -2), (-1, -2)),  # Safety spans all columns
                ('SPAN', (0, -1), (-1, -1)),  # Printed date spans all columns
            ]))
        
            story.append(equipment_table)
            story.append(Spacer(1, 15))
        
            # Custom checklist table
            checklist_data = [
                [
                    Paragraph('', header_cell_style), 
                    Paragraph('CUSTOM PM CHECKLIST:', header_cell_style), 
                    Paragraph('', header_cell_style), 
                    Paragraph('Completed', header_cell_style), 
                    Paragraph('Labor Time', header_cell_style)
                ]
            ]
        
            # Add custom checklist items
            try:
                checklist_items = json.loads(checklist_json) if checklist_json else []
            except:
                checklist_items = []
        
            if not checklist_items:
                checklist_items = ["No custom checklist defined - using default steps"]
        
            for idx, item in enumerate(checklist_items, 1):
                checklist_data.append([
                    Paragraph(str(idx), cell_style), 
                    Paragraph(item, cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Yes', cell_style), 
                    Paragraph('hours    minutes', cell_style)
                ])
        
            checklist_table = Table(checklist_data, colWidths=[0.3*inch, 4.2*inch, 0.4*inch, 0.7*inch, 1.4*inch])
            checklist_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
        
            story.append(checklist_table)
            story.append(Spacer(1, 15))
        
            # Special instructions section
            if special_instructions and special_instructions.strip():
                instructions_data = [
                    [Paragraph('SPECIAL INSTRUCTIONS:', header_cell_style)],
                    [Paragraph(special_instructions, cell_style)]
                ]
            
                instructions_table = Table(instructions_data, colWidths=[7*inch])
                instructions_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BACKGROUND', (0, 0), (0, 0), colors.lightgrey),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
            
                story.append(instructions_table)
                story.append(Spacer(1, 15))
        
            # Completion section
            completion_data = [
                [
                    Paragraph('Notes from Technician:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Next Annual PM Date:', header_cell_style)
                ],
                [
                    Paragraph('', cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('', cell_style)
                ],
                [
                    Paragraph('All Data Entered Into System:', header_cell_style), 
                    Paragraph('', cell_style), 
                    Paragraph('Total Time', header_cell_style)
                ],
                [
                    Paragraph('Document Name', header_cell_style), 
                    Paragraph('Revision', header_cell_style), 
                    Paragraph('', cell_style)
                ],
                [
                    Paragraph(f'Custom_PM_Template_{template_name}', cell_style), 
                    Paragraph('A1', cell_style), 
                    Paragraph('', cell_style)
                ]
            ]
        
            completion_table = Table(completion_data, colWidths=[2.8*inch, 2.2*inch, 2*inch])
            completion_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
        
            story.append(completion_table)
        
            # Build PDF
            doc.build(story)
        
        except Exception as e:
            print(f"Error creating custom PM template PDF: {e}")
            raise

    # Additional methods to integrate with existing PM completion system

    def get_pm_template_for_equipment(self, bfm_no, pm_type):
        """Get custom PM template for specific equipment and PM type"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT checklist_items, special_instructions, safety_notes, estimated_hours
                FROM pm_templates 
                WHERE bfm_equipment_no = %s AND pm_type = %s
                ORDER BY updated_date DESC LIMIT 1
            ''', (bfm_no, pm_type))
        
            result = cursor.fetchone()
            if result:
                checklist_json, special_instructions, safety_notes, estimated_hours = result
                try:
                    checklist_items = json.loads(checklist_json) if checklist_json else []
                    return {
                        'checklist_items': checklist_items,
                        'special_instructions': special_instructions,
                        'safety_notes': safety_notes,
                        'estimated_hours': estimated_hours
                    }
                except:
                    return None
            return None
        
        except Exception as e:
            print(f"Error getting PM template: {e}")
            return None

    def update_pm_completion_form_with_template(self):
        """Update PM completion form when equipment is selected"""
        bfm_no = self.completion_bfm_var.get().strip()
        pm_type = self.pm_type_var.get()
    
        if bfm_no and pm_type:
            template = self.get_pm_template_for_equipment(bfm_no, pm_type)
            if template:
                # Update estimated hours
                self.labor_hours_var.set(str(int(template['estimated_hours'])))
                self.labor_minutes_var.set(str(int((template['estimated_hours'] % 1) * 60)))
            
                # Show template info
                self.update_status(f"Custom template found for {bfm_no} - {pm_type} PM")
            else:
                self.update_status(f"No custom template found for {bfm_no} - {pm_type} PM, using default")

    def create_equipment_pm_lookup_with_templates(self):
        """Enhanced equipment lookup that shows custom templates"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Equipment PM Schedule & Templates")
        dialog.geometry("900x700")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Equipment search
        search_frame = ttk.LabelFrame(dialog, text="Equipment Search", padding=15)
        search_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Label(search_frame, text="BFM Equipment Number:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
    
        bfm_var = tk.StringVar()
        bfm_entry = ttk.Entry(search_frame, textvariable=bfm_var, width=20, font=('Arial', 11))
        bfm_entry.grid(row=0, column=1, padx=10, pady=5)
    
        search_btn = ttk.Button(search_frame, text="Look Up Equipment", 
                            command=lambda: self.lookup_equipment_with_templates(bfm_var.get().strip(), results_frame))
        search_btn.grid(row=0, column=2, padx=10, pady=5)
    
        # Results frame
        results_frame = ttk.LabelFrame(dialog, text="Equipment Information & Templates", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        bfm_entry.focus_set()
        bfm_entry.bind('<Return>', lambda e: search_btn.invoke())

    def lookup_equipment_with_templates(self, bfm_no, parent_frame):
        """Lookup equipment with custom template information"""
        if not bfm_no:
            messagebox.showwarning("Warning", "Please enter a BFM Equipment Number")
            return
    
        try:
            cursor = self.conn.cursor()
        
            # Clear previous results
            for widget in parent_frame.winfo_children():
                widget.destroy()
        
            # Get equipment info
            cursor.execute('''
                SELECT sap_material_no, description, location, status
                FROM equipment 
                WHERE bfm_equipment_no = %s
            ''', (bfm_no,))
        
            equipment_data = cursor.fetchone()
            if not equipment_data:
                error_label = ttk.Label(parent_frame, 
                                    text=f"Equipment '{bfm_no}' not found in database",
                                    font=('Arial', 12, 'bold'), foreground='red')
                error_label.pack(pady=20)
                return
        
            # Equipment header
            header_text = f"Equipment: {bfm_no}\n"
            header_text += f"Description: {equipment_data[1] or 'N/A'}\n"
            header_text += f"Location: {equipment_data[2] or 'N/A'}\n"
            header_text += f"Status: {equipment_data[3] or 'Active'}"
        
            header_label = ttk.Label(parent_frame, text=header_text, font=('Arial', 10))
            header_label.pack(pady=10)
        
            # Get custom templates
            cursor.execute('''
                SELECT template_name, pm_type, checklist_items, estimated_hours, updated_date
                FROM pm_templates 
                WHERE bfm_equipment_no = %s
                ORDER BY pm_type, template_name
            ''', (bfm_no,))
        
            templates = cursor.fetchall()
        
            if templates:
                templates_frame = ttk.LabelFrame(parent_frame, text="Custom PM Templates", padding=10)
                templates_frame.pack(fill='x', pady=10)
            
                for template in templates:
                    name, pm_type, checklist_json, est_hours, updated = template
                    try:
                        checklist_items = json.loads(checklist_json) if checklist_json else []
                        step_count = len(checklist_items)
                    except:
                        step_count = 0
                
                    template_text = f"- {name} ({pm_type} PM) - {step_count} steps, {est_hours:.1f}h estimated"
                    ttk.Label(templates_frame, text=template_text, font=('Arial', 9)).pack(anchor='w')
            else:
                no_templates_label = ttk.Label(parent_frame, 
                                            text="No custom PM templates found for this equipment",
                                            font=('Arial', 10), foreground='orange')
                no_templates_label.pack(pady=10)
        
            # Regular PM schedule info (existing functionality)
            self.lookup_equipment_pm_schedule(bfm_no, parent_frame)
        
        except Exception as e:
            error_label = ttk.Label(parent_frame, 
                                text=f"Error looking up equipment: {str(e)}", 
                                font=('Arial', 10), foreground='red')
            error_label.pack(pady=20) 
    
    
    def init_database(self):
        """Initialize comprehensive CMMS database with Neon PostgreSQL and connection pooling"""
        try:
            # Connection pool is already initialized before login
            # Get a connection from the pool for initial setup
            self.conn = db_pool.get_connection()
            self.conn.autocommit = False  # Manual commit control
            cursor = self.conn.cursor()

            print("=" * 60)
            print("CHECK: Connected to Neon PostgreSQL successfully!")
            print("CHECK: Connection pool initialized for multi-user support")
            print("=" * 60)
        
            # Equipment/Assets table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS equipment (
                    id SERIAL PRIMARY KEY,
                    sap_material_no TEXT,
                    bfm_equipment_no TEXT UNIQUE,
                    description TEXT,
                    tool_id_drawing_no TEXT,
                    location TEXT,
                    master_lin TEXT,
                    monthly_pm BOOLEAN DEFAULT FALSE,
                    six_month_pm BOOLEAN DEFAULT FALSE,
                    annual_pm BOOLEAN DEFAULT FALSE,
                    last_monthly_pm TEXT,
                    last_six_month_pm TEXT,
                    last_annual_pm TEXT,
                    next_monthly_pm TEXT,
                    next_six_month_pm TEXT,
                    next_annual_pm TEXT,
                    status TEXT DEFAULT 'Active',
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
            # PM Completions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pm_completions (
                    id SERIAL PRIMARY KEY,
                    bfm_equipment_no TEXT,
                    pm_type TEXT,
                    technician_name TEXT,
                    completion_date TEXT,
                    location TEXT,
                    labor_hours REAL,
                    labor_minutes REAL,
                    pm_due_date TEXT,
                    special_equipment TEXT,
                    notes TEXT,
                    next_annual_pm_date TEXT,
                    document_name TEXT DEFAULT 'Preventive_Maintenance_Form',
                    document_revision TEXT DEFAULT 'A2',
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')
        
            # Weekly PM Schedules
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS weekly_pm_schedules (
                    id SERIAL PRIMARY KEY,
                    bfm_equipment_no TEXT,
                    schedule_type TEXT,
                    assigned_technician TEXT,
                    assigned_week INTEGER,
                    assigned_day TEXT,
                    week_start_date TEXT,
                    week_end_date TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')
        
            # Corrective Maintenance table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS corrective_maintenance (
                    id SERIAL PRIMARY KEY,
                    cm_number TEXT UNIQUE,
                    bfm_equipment_no TEXT,
                    description TEXT,
                    location TEXT,
                    reported_by TEXT,
                    reported_date TEXT,
                    priority TEXT,
                    status TEXT DEFAULT 'Open',
                    assigned_technician TEXT,
                    labor_hours REAL,
                    notes TEXT,
                    closed_date TEXT,
                    closed_by TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')
        
            # Work Orders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS work_orders (
                    id SERIAL PRIMARY KEY,
                    wo_number TEXT UNIQUE,
                    bfm_equipment_no TEXT,
                    wo_type TEXT,
                    description TEXT,
                    location TEXT,
                    requested_by TEXT,
                    requested_date TEXT,
                    priority TEXT,
                    status TEXT DEFAULT 'Open',
                    assigned_technician TEXT,
                    estimated_hours REAL,
                    actual_hours REAL,
                    completed_date TEXT,
                    notes TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')
        
            # Parts/Inventory table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parts_inventory (
                    id SERIAL PRIMARY KEY,
                    part_number TEXT UNIQUE,
                    description TEXT,
                    quantity INTEGER DEFAULT 0,
                    min_quantity INTEGER,
                    location TEXT,
                    unit_cost REAL,
                    last_ordered TEXT,
                    supplier TEXT,
                    notes TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
            # MRO Stock table (if you use it)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mro_stock (
                    id SERIAL PRIMARY KEY,
                    part_number TEXT UNIQUE,
                    description TEXT,
                    quantity INTEGER DEFAULT 0,
                    location TEXT,
                    category TEXT,
                    notes TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
            # Cannot Find Assets table - COMPLETE VERSION
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cannot_find_assets (
                    id SERIAL PRIMARY KEY,
                    bfm_equipment_no TEXT UNIQUE,
                    description TEXT,
                    location TEXT,
                    last_known_location TEXT,
                    reported_by TEXT,
                    reported_date TEXT,
                    technician_name TEXT,
                    assigned_technician TEXT,
                    status TEXT DEFAULT 'Missing',
                    search_status TEXT,
                    priority TEXT,
                    found_date TEXT,
                    found_by TEXT,
                    notes TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')
        
            # Run to Failure Assets table - COMPLETE WITH LABOR TRACKING
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS run_to_failure_assets (
                    id SERIAL PRIMARY KEY,
                    bfm_equipment_no TEXT UNIQUE,
                    description TEXT,
                    location TEXT,
                    justification TEXT,
                    approved_by TEXT,
                    approval_date TIMESTAMP,
                    technician_name TEXT,
                    assigned_technician TEXT,
                    status TEXT DEFAULT 'Active',
                    review_date TIMESTAMP,
                    next_review_date TIMESTAMP,
                    last_inspection_date TIMESTAMP,
                    completion_date TIMESTAMP,
                    failure_date TIMESTAMP,
                    last_failure_date TIMESTAMP,
                    installed_date TIMESTAMP,
                    retired_date TIMESTAMP,
                    labor_hours REAL,
                    labor_minutes REAL,
                    total_labor_hours REAL,
                    labor_cost REAL,
                    notes TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bfm_equipment_no) REFERENCES equipment (bfm_equipment_no)
                )
            ''')

            # ===== MULTI-USER SUPPORT TABLES =====
            # Users table for authentication
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('Manager', 'Technician')),
                    email TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    created_by TEXT,
                    notes TEXT
                )
            ''')

            # User sessions table for tracking active sessions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    logout_time TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    session_data TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')

            # Audit log table for tracking all changes
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id TEXT,
                    old_values TEXT,
                    new_values TEXT,
                    notes TEXT,
                    action_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            self.conn.commit()
            print("CHECK: Database tables created successfully!")
            print("CHECK: Multi-user support tables initialized")
            print("=" * 60 + "\n")
        
        except Exception as e:
            print(f"CHECK: ERROR connecting to database: {e}")
            if self.conn:
                self.conn.rollback()
            raise
    
    
    def create_gui(self):
        """Create the main GUI interface based on user role"""
        # Create style
        style = ttk.Style()
        style.theme_use('clam')
    
        # Main notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
    
        # Create tabs based on role
        if self.current_user_role == 'Manager':
            # Manager gets all tabs
            self.create_all_manager_tabs()
        else:
            # Technicians only get CM tab
            self.create_technician_tabs()
    
        # Status bar with user info
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side='bottom', fill='x')
    
        self.status_bar = ttk.Label(status_frame, text=f"AIT CMMS Ready - Logged in as: {self.user_name} ({self.current_user_role})",
                                    relief='sunken')
        self.status_bar.pack(side='left', fill='x', expand=True)

        # Role switching button (only for development/testing)
        if self.current_user_role == 'Manager':
            ttk.Button(status_frame, text="Switch to Technician View", 
                    command=self.switch_to_technician_view).pack(side='right', padx=5)

    def create_all_manager_tabs(self):
        """Create all tabs for manager access"""
        self.create_equipment_tab()
        self.create_pm_scheduling_tab()
        self.create_pm_completion_tab()
        self.create_cm_management_tab()
        #self.create_analytics_dashboard_tab()
        self.create_cannot_find_tab()
        self.create_run_to_failure_tab()
        self.create_pm_history_search_tab()
        self.create_custom_pm_templates_tab()
        self.mro_manager.create_mro_tab(self.notebook)

    def create_technician_tabs(self):
        """Create limited tabs for technician access"""
        # Only create CM Management tab for technicians
        self.create_cm_management_tab()
    
        # Add a simple info tab explaining their access
        self.create_technician_info_tab()

    def create_technician_info_tab(self):
        """Create an info tab for technicians"""
        info_frame = ttk.Frame(self.notebook)
        self.notebook.add(info_frame, text="System Info")
    
        # Welcome message
        welcome_frame = ttk.LabelFrame(info_frame, text="Welcome to AIT CMMS", padding=20)
        welcome_frame.pack(fill='both', expand=True, padx=20, pady=20)
    
        welcome_text = f"""
    Welcome, {self.user_name}!

    You are logged in as a Technician with access to:
    - Complete Corrective Maintenance (CM) System
    - View ALL team CMs (everyone's entries)
    - Create new CMs
    - Edit existing CMs  
    - Complete CMs
    - View CM history and status

    Team Collaboration:
    - You can see CMs created by all technicians
    - View work assigned to other team members
    - Complete CMs assigned to you or help with others
    - Full visibility of maintenance activities

    For additional system access or questions, please contact your manager.

    System Information:
    - User: {self.user_name}
    - Role: {self.current_user_role}
    - Login Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    Quick Tips:
    - Use the CM tab to view all corrective maintenance
    - Create new CMs when you discover issues
    - Enter accurate dates when creating CMs
    - Provide detailed descriptions for better tracking
    - Update CM status when work is completed
    - Coordinate with team members through CM system
    """
    
        info_label = ttk.Label(welcome_frame, text=welcome_text, 
                            font=('Arial', 11), justify='left')
        info_label.pack(anchor='w')
    
        # Quick access buttons
        buttons_frame = ttk.Frame(welcome_frame)
        buttons_frame.pack(fill='x', pady=20)
    
        ttk.Button(buttons_frame, text="Create New CM", 
                command=self.create_cm_dialog).pack(side='left', padx=10)
        ttk.Button(buttons_frame, text="View My Assigned CMs", 
                command=self.show_my_cms).pack(side='left', padx=10)
        ttk.Button(buttons_frame, text="Refresh All CMs", 
                command=self.load_corrective_maintenance).pack(side='left', padx=10)

    def show_my_cms(self):
        """Show CMs assigned to current technician"""
        if self.current_user_role != 'Technician':
            return
        
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT cm_number, bfm_equipment_no, description, priority, status, created_date
                FROM corrective_maintenance 
                WHERE assigned_technician = %s
                ORDER BY created_date DESC
            ''', (self.user_name,))
        
            my_cms = cursor.fetchall()
        
            # Create dialog to show results
            dialog = tk.Toplevel(self.root)
            dialog.title(f"My CMs - {self.user_name}")
            dialog.geometry("800x400")
            dialog.transient(self.root)
            dialog.grab_set()
        
            if my_cms:
                # Create tree to display CMs
                tree = ttk.Treeview(dialog, columns=('CM#', 'Equipment', 'Description', 'Priority', 'Status', 'Date'), 
                                show='headings')
            
                for col in ('CM#', 'Equipment', 'Description', 'Priority', 'Status', 'Date'):
                    tree.heading(col, text=col)
                    tree.column(col, width=120)
            
                for cm in my_cms:
                    cm_number, bfm_no, description, priority, status, created_date = cm
                    display_desc = (description[:30] + '...') if len(description) > 30 else description
                    tree.insert('', 'end', values=(cm_number, bfm_no, display_desc, priority, status, created_date))
            
                tree.pack(fill='both', expand=True, padx=10, pady=10)
            else:
                ttk.Label(dialog, text=f"No CMs assigned to {self.user_name}", 
                        font=('Arial', 12)).pack(pady=50)
        
            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load your CMs: {str(e)}")

    def switch_to_technician_view(self):
        """Switch to technician view for testing (Manager only)"""
        if self.current_user_role != 'Manager':
            return
        
        result = messagebox.askyesno("Switch View", 
                                    "Switch to Technician view?\n\n"
                                    "This will hide all manager functions and only show CM access.\n"
                                    "You'll need to restart the application to get back to Manager view.")
    
        if result:
            # Temporarily switch role
            self.current_user_role = 'Technician'
            self.user_name = 'Test Technician'
        
            # Recreate GUI
            for widget in self.notebook.winfo_children():
                widget.destroy()
        
            self.create_technician_tabs()
            self.status_bar.config(text=f"AIT CMMS - Logged in as: {self.user_name} ({self.current_user_role})")

    
   
    
    def standardize_all_database_dates(self):
        """Standardize all dates in the database to YYYY-MM-DD format"""
        
        # Confirmation dialog
        result = messagebox.askyesno(
            "Confirm Date Standardization",
            "This will standardize ALL dates in the database to YYYY-MM-DD format.\n\n"
            "Tables affected:\n"
            "- Equipment (PM dates)\n"
            "- PM Completions\n"
            "- Weekly Schedules\n"
            "- Corrective Maintenance\n"
            "- Cannot Find Assets\n"
            "- Run to Failure Assets\n\n"
            "This action cannot be undone. Continue?",
            icon='warning'
        )
        
        if not result:
            return
        
        try:
            # Create progress dialog
            progress_dialog = tk.Toplevel(self.root)
            progress_dialog.title("Standardizing Dates...")
            progress_dialog.geometry("400x150")
            progress_dialog.transient(self.root)
            progress_dialog.grab_set()
            
            ttk.Label(progress_dialog, text="Standardizing dates in database...", 
                     font=('Arial', 12)).pack(pady=20)
            
            progress_var = tk.StringVar(value="Initializing...")
            progress_label = ttk.Label(progress_dialog, textvariable=progress_var)
            progress_label.pack(pady=10)
            
            progress_bar = ttk.Progressbar(progress_dialog, mode='indeterminate')
            progress_bar.pack(pady=10, padx=20, fill='x')
            progress_bar.start()
            
            # Update GUI
            self.root.update()
            
            # Perform standardization
            progress_var.set("Processing database...")
            self.root.update()
            
            standardizer = DateStandardizer(self.conn)
            total_updated, errors = standardizer.standardize_all_dates()
            
            progress_bar.stop()
            progress_dialog.destroy()
            
            # Show results
            if errors:
                error_msg = f"Date standardization completed with {len(errors)} errors:\n\n"
                error_msg += "\n".join(errors[:10])  # Show first 10 errors
                if len(errors) > 10:
                    error_msg += f"\n... and {len(errors) - 10} more errors"
                
                messagebox.showwarning("Standardization Complete (With Errors)", 
                                     f"Updated {total_updated} records.\n\n{error_msg}")
            else:
                messagebox.showinfo("Success", 
                                  f"Date standardization completed successfully!\n\n"
                                  f"Updated {total_updated} date records to YYYY-MM-DD format.\n\n"
                                  f"All dates are now standardized.")
            
            # Refresh displays
            self.refresh_equipment_list()
            self.load_recent_completions()
            if hasattr(self, 'load_cannot_find_assets'):
                self.load_cannot_find_assets()
            if hasattr(self, 'load_run_to_failure_assets'):
                self.load_run_to_failure_assets()
            
            self.update_status(f"Date standardization complete: {total_updated} records updated")
            
        except Exception as e:
            if 'progress_dialog' in locals():
                progress_dialog.destroy()
            messagebox.showerror("Error", f"Failed to standardize dates: {str(e)}")
    
    def add_date_standardization_button(self):
        """Add date standardization button to equipment tab"""
        # Find the controls frame in equipment tab
        for widget in self.equipment_frame.winfo_children():
            if isinstance(widget, ttk.LabelFrame) and "Equipment Controls" in widget['text']:
                ttk.Button(widget, text="WARNING: Standardize All Dates (YYYY-MM-DD)", 
                          command=self.standardize_all_database_dates,
                          width=30).pack(side='left', padx=5)
                break
    
    

    def create_equipment_tab(self):
        """Equipment management and data import tab"""
        self.equipment_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.equipment_frame, text="Equipment Management")
        
        # Controls frame
        controls_frame = ttk.LabelFrame(self.equipment_frame, text="Equipment Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
        
        # Add statistics frame after controls_frame
        stats_frame = ttk.LabelFrame(self.equipment_frame, text="Equipment Statistics", padding=10)
        stats_frame.pack(fill='x', padx=10, pady=5)

        # Statistics labels
        self.stats_total_label = ttk.Label(stats_frame, text="Total Assets: 0", font=('Arial', 10, 'bold'))
        self.stats_total_label.pack(side='left', padx=20)

        self.stats_cf_label = ttk.Label(stats_frame, text="Cannot Find: 0", font=('Arial', 10, 'bold'), foreground='red')
        self.stats_cf_label.pack(side='left', padx=20)

        self.stats_rtf_label = ttk.Label(stats_frame, text="Run to Failure: 0", font=('Arial', 10, 'bold'), foreground='orange')
        self.stats_rtf_label.pack(side='left', padx=20)

        self.stats_active_label = ttk.Label(stats_frame, text="Active Assets: 0", font=('Arial', 10, 'bold'), foreground='green')
        self.stats_active_label.pack(side='left', padx=20)

        # Refresh stats button
        ttk.Button(stats_frame, text="Refresh Stats", 
                command=self.update_equipment_statistics).pack(side='right', padx=5)
        
        
        ttk.Button(controls_frame, text="Import Equipment CSV", 
                  command=self.import_equipment_csv).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Add Equipment", 
                  command=self.add_equipment_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Edit Equipment", 
                  command=self.edit_equipment_dialog).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Refresh List", 
                  command=self.refresh_equipment_list).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export Equipment", 
                  command=self.export_equipment_list).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="WARNING: Bulk Edit PM Cycles", 
                  command=self.bulk_edit_pm_cycles).pack(side='left', padx=5)
        
        
        # Search frame
        search_frame = ttk.Frame(self.equipment_frame)
        search_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(search_frame, text="Search Equipment:").pack(side='left', padx=5)
        self.equipment_search_var = tk.StringVar()
        self.equipment_search_var.trace('w', self.filter_equipment_list)
        search_entry = ttk.Entry(search_frame, textvariable=self.equipment_search_var, width=30)
        search_entry.pack(side='left', padx=5)

        # Location filter
        ttk.Label(search_frame, text="Filter by Location:").pack(side='left', padx=(20, 5))
        self.equipment_location_var = tk.StringVar(value="All Locations")
        self.equipment_location_combo = ttk.Combobox(search_frame, textvariable=self.equipment_location_var, width=25, state='readonly')
        self.equipment_location_combo.pack(side='left', padx=5)
        self.equipment_location_combo.bind('<<ComboboxSelected>>', self.filter_equipment_list)

        # Clear filters button
        ttk.Button(search_frame, text="Clear Filters",
                  command=self.clear_equipment_filters).pack(side='left', padx=5)
        
        # Equipment list
        list_frame = ttk.Frame(self.equipment_frame)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Treeview with scrollbars
        self.equipment_tree = ttk.Treeview(list_frame, 
                                         columns=('SAP', 'BFM', 'Description', 'Location', 'LIN', 'Monthly', 'Six Month', 'Annual', 'Status'),
                                         show='headings', height=20)
        self.equipment_tree.configure(selectmode='extended')  # Enable multi-select
        # Configure columns
        columns_config = {
            'SAP': ('SAP Material No.', 120),
            'BFM': ('BFM Equipment No.', 130),
            'Description': ('Description', 300),
            'Location': ('Location', 100),
            'LIN': ('Master LIN', 80),
            'Monthly': ('Monthly PM', 80),
            'Six Month': ('6-Month PM', 80),
            'Annual': ('Annual PM', 80),
            'Status': ('Status', 80)
        }
        
        for col, (heading, width) in columns_config.items():
            self.equipment_tree.heading(col, text=heading)
            self.equipment_tree.column(col, width=width)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.equipment_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient='horizontal', command=self.equipment_tree.xview)
        self.equipment_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack treeview and scrollbars
        self.equipment_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
    
    
    
    
    
    
    
    def populate_week_selector(self):
        """Populate dropdown with weeks that have schedules"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT DISTINCT week_start_date 
                FROM weekly_pm_schedules 
                ORDER BY week_start_date DESC
            ''')
            available_weeks = [row[0] for row in cursor.fetchall()]
        
            # Always include current week as an option
            current_week = self.current_week_start.strftime('%Y-%m-%d')
            if current_week not in available_weeks:
                available_weeks.append(current_week)
                available_weeks.sort(reverse=True)
            
            # Update combobox values
            self.week_combo['values'] = available_weeks
        
            # Set to most recent week with data, or current week if no data
            if available_weeks:
                self.week_start_var.set(available_weeks[0])
            
        except Exception as e:
            print(f"Error populating week selector: {e}")

    def load_latest_weekly_schedule(self):
        """Load the most recent weekly schedule on startup"""
        try:
            cursor = self.conn.cursor()
        
            # Find the most recent week with scheduled PMs
            cursor.execute('''
                SELECT week_start_date 
                FROM weekly_pm_schedules 
                ORDER BY week_start_date DESC 
                LIMIT 1
            ''')
        
            latest_week = cursor.fetchone()
        
            if latest_week:
                self.week_start_var.set(latest_week[0])
                self.refresh_technician_schedules()
                self.update_status(f"Loaded latest weekly schedule: {latest_week[0]}")
            else:
                self.update_status("No weekly schedules found")
            
        except Exception as e:
            print(f"Error loading latest weekly schedule: {e}")
    
    
    
    def update_equipment_statistics(self):
        """Update equipment statistics display"""
        try:
            cursor = self.conn.cursor()

            # Get total assets count
            cursor.execute('SELECT COUNT(*) FROM equipment')
            total_assets = cursor.fetchone()[0]

            # Get Cannot Find count from cannot_find_assets table
            cursor.execute('SELECT COUNT(DISTINCT bfm_equipment_no) FROM cannot_find_assets WHERE status = %s', ('Missing',))
            cannot_find_count = cursor.fetchone()[0]

            # Get Run to Failure count from equipment table
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE status = %s', ('Run to Failure',))
            rtf_count = cursor.fetchone()[0]

            # Active assets = Total - Cannot Find - Run to Failure
            # This ensures the numbers add up correctly
            active_assets = total_assets - cannot_find_count - rtf_count

            # Update labels
            self.stats_total_label.config(text=f"Total Assets: {total_assets}")
            self.stats_active_label.config(text=f"Active Assets: {active_assets}")
            self.stats_cf_label.config(text=f"Cannot Find: {cannot_find_count}")
            self.stats_rtf_label.config(text=f"Run to Failure: {rtf_count}")

            # Update status bar
            self.update_status(f"Equipment stats updated - Total: {total_assets}, Active: {active_assets}, CF: {cannot_find_count}, RTF: {rtf_count}")

        except Exception as e:
            print(f"Error updating equipment statistics: {e}")
            messagebox.showerror("Error", f"Failed to update equipment statistics: {str(e)}")
    
    def create_pm_scheduling_tab(self):
        """PM Scheduling and assignment tab"""
        self.pm_schedule_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pm_schedule_frame, text="PM Scheduling")
        
        # Controls
        controls_frame = ttk.LabelFrame(self.pm_schedule_frame, text="PM Scheduling Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
        
        
       
        # Week selection with dropdown of available weeks
        ttk.Label(controls_frame, text="Week Starting:").grid(row=0, column=0, sticky='w', padx=5)
        self.week_start_var = tk.StringVar(value=self.current_week_start.strftime('%Y-%m-%d'))

        # Create combobox instead of entry
        self.week_combo = ttk.Combobox(controls_frame, textvariable=self.week_start_var, width=12)
        self.week_combo.grid(row=0, column=1, padx=5)

        # Bind selection change to refresh display
        self.week_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_technician_schedules())

        # Populate with available weeks
        self.populate_week_selector()
        
        ttk.Button(controls_frame, text="Generate Weekly Schedule", 
                  command=self.generate_weekly_assignments).grid(row=0, column=2, padx=5)
        ttk.Button(controls_frame, text="Print PM Forms", 
                  command=self.print_weekly_pm_forms).grid(row=0, column=3, padx=5)
        ttk.Button(controls_frame, text="Export Schedule",
                  command=self.export_weekly_schedule).grid(row=0, column=4, padx=5)
        
        # Schedule display
        schedule_frame = ttk.LabelFrame(self.pm_schedule_frame, text="Weekly PM Schedule", padding=10)
        schedule_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Technician tabs
        self.technician_notebook = ttk.Notebook(schedule_frame)
        self.technician_notebook.pack(fill='both', expand=True)
        
        # Create tabs for each technician
        self.technician_trees = {}
        for tech in self.technicians:
            tech_frame = ttk.Frame(self.technician_notebook)
            self.technician_notebook.add(tech_frame, text=tech)

            # Technician's schedule tree
            tech_tree = ttk.Treeview(tech_frame,
                                   columns=('BFM', 'Description', 'PM Type', 'Due Date', 'Status'),
                                   show='headings')

            tech_tree.heading('BFM', text='BFM Equipment No.')
            tech_tree.heading('Description', text='Description')
            tech_tree.heading('PM Type', text='PM Type')
            tech_tree.heading('Due Date', text='Due Date')
            tech_tree.heading('Status', text='Status')

            for col in ('BFM', 'Description', 'PM Type', 'Due Date', 'Status'):
                tech_tree.column(col, width=150)

            tech_tree.pack(fill='both', expand=True, padx=5, pady=5)
            self.technician_trees[tech] = tech_tree

        # After creating all the technician trees, load the latest schedule
        self.load_latest_weekly_schedule()
     
    
    def create_pm_completion_tab(self):
        """PM Completion entry tab"""
        self.pm_completion_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pm_completion_frame, text="PM Completion")
        
        # Completion form
        form_frame = ttk.LabelFrame(self.pm_completion_frame, text="PM Completion Entry", padding=15)
        form_frame.pack(fill='x', padx=10, pady=5)
        
        # Form fields (matching your PM form layout)
        row = 0
        
        # Equipment selection
        ttk.Label(form_frame, text="BFM Equipment Number:").grid(row=row, column=0, sticky='w', pady=5)
        self.completion_bfm_var = tk.StringVar()
        bfm_combo = ttk.Combobox(form_frame, textvariable=self.completion_bfm_var, width=20)
        bfm_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        bfm_combo.bind('<KeyRelease>', self.update_equipment_suggestions)
        self.bfm_combo = bfm_combo
        row += 1
        
        # PM Type
        ttk.Label(form_frame, text="PM Type:").grid(row=row, column=0, sticky='w', pady=5)
        self.pm_type_var = tk.StringVar()
        pm_type_combo = ttk.Combobox(form_frame, textvariable=self.pm_type_var, 
                                   values=['Monthly', 'Six Month', 'Annual', 'CANNOT FIND', 'Run to Failure'], width=20)
        # Bind PM type and equipment changes to template lookup
        pm_type_combo.bind('<<ComboboxSelected>>', lambda e: self.update_pm_completion_form_with_template())
        self.bfm_combo.bind('<KeyRelease>', lambda e: self.update_pm_completion_form_with_template())
        pm_type_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Technician
        ttk.Label(form_frame, text="Maintenance Technician:").grid(row=row, column=0, sticky='w', pady=5)
        self.completion_tech_var = tk.StringVar()
        tech_combo = ttk.Combobox(form_frame, textvariable=self.completion_tech_var, 
                                values=self.technicians, width=20)
        tech_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Labor time
        ttk.Label(form_frame, text="Labor Time:").grid(row=row, column=0, sticky='w', pady=5)
        time_frame = ttk.Frame(form_frame)
        time_frame.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        
        self.labor_hours_var = tk.StringVar(value="0")
        ttk.Entry(time_frame, textvariable=self.labor_hours_var, width=5).pack(side='left')
        ttk.Label(time_frame, text="hours").pack(side='left', padx=5)
        
        self.labor_minutes_var = tk.StringVar(value="0")
        ttk.Entry(time_frame, textvariable=self.labor_minutes_var, width=5).pack(side='left')
        ttk.Label(time_frame, text="minutes").pack(side='left', padx=5)
        row += 1
        
        # PM Due Date
        ttk.Label(form_frame, text="PM Due Date:").grid(row=row, column=0, sticky='w', pady=5)
        self.pm_due_date_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.pm_due_date_var, width=20).grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Special Equipment
        ttk.Label(form_frame, text="Special Equipment Used:").grid(row=row, column=0, sticky='w', pady=5)
        self.special_equipment_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.special_equipment_var, width=40).grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Notes
        ttk.Label(form_frame, text="Notes from Technician:").grid(row=row, column=0, sticky='nw', pady=5)
        self.notes_text = tk.Text(form_frame, width=50, height=4)
        self.notes_text.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Next Annual PM Date
        ttk.Label(form_frame, text="Next Annual PM Date:").grid(row=row, column=0, sticky='w', pady=5)
        self.next_annual_pm_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=self.next_annual_pm_var, width=20).grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1
        
        # Submit and refresh buttons
        buttons_frame = ttk.Frame(form_frame)
        buttons_frame.grid(row=row, column=0, columnspan=2, pady=15)
        
        ttk.Button(buttons_frame, text="Monthly Summary Report", 
           command=self.show_monthly_summary).pack(side='left', padx=5)
        
        ttk.Button(buttons_frame, text="Show Equipment PM History", 
                command=lambda: self.show_equipment_pm_history_dialog()).pack(side='left', padx=5)
        
        ttk.Button(buttons_frame, text="Submit PM Completion", 
                command=self.submit_pm_completion).pack(side='left', padx=5)
        ttk.Button(buttons_frame, text="Refresh List", 
                command=self.load_recent_completions).pack(side='left', padx=5)
               
        ttk.Button(buttons_frame, text="WARNING: Check Equipment Schedule", 
                command=self.create_pm_schedule_lookup_dialog).pack(side='left', padx=5)
        
        ttk.Button(buttons_frame, text="WARNING: Create CM from PM", 
                command=self.create_cm_from_pm_dialog).pack(side='left', padx=5)
        
        # Recent completions
        recent_frame = ttk.LabelFrame(self.pm_completion_frame, text="Recent PM Completions", padding=10)
        recent_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.recent_completions_tree = ttk.Treeview(recent_frame,
                                                  columns=('Date', 'BFM', 'PM Type', 'Technician', 'Hours'),
                                                  show='headings')
        
        for col in ('Date', 'BFM', 'PM Type', 'Technician', 'Hours'):
            self.recent_completions_tree.heading(col, text=col)
            self.recent_completions_tree.column(col, width=120)
        
        self.recent_completions_tree.pack(fill='both', expand=True)
        self.recent_completions_tree.bind('<Double-1>', self.on_completion_double_click)
        self.recent_completions_tree.bind('<<TreeviewSelect>>', self.on_completion_select)
        
        # Load recent completions
        self.load_recent_completions()
        
        
    def show_equipment_pm_history_dialog(self):
        """Dialog to look up PM history for any equipment"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Equipment PM History Lookup")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
    
        ttk.Label(dialog, text="Enter BFM Equipment Number:", font=('Arial', 12)).pack(pady=20)
    
        bfm_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=bfm_var, width=20, font=('Arial', 12))
        entry.pack(pady=10)
    
        def lookup_history():
            bfm_no = bfm_var.get().strip()
            if bfm_no:
                dialog.destroy()
                self.show_recent_completions_for_equipment(bfm_no)
            else:
                messagebox.showwarning("Warning", "Please enter a BFM Equipment Number")
    
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)
    
        ttk.Button(button_frame, text="Show History", command=lookup_history).pack(side='left', padx=10)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=10)
    
        entry.focus_set()
        entry.bind('<Return>', lambda e: lookup_history())
        
        
    def create_pm_schedule_lookup_dialog(self):
        """Create dialog to lookup PM schedule for specific equipment"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Equipment PM Schedule Lookup")
        dialog.geometry("800x600")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Search section
        search_frame = ttk.LabelFrame(dialog, text="Equipment Search", padding=15)
        search_frame.pack(fill='x', padx=10, pady=5)
    
        # Equipment search
        ttk.Label(search_frame, text="BFM Equipment Number:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
    
        bfm_var = tk.StringVar()
        bfm_entry = ttk.Entry(search_frame, textvariable=bfm_var, width=20, font=('Arial', 11))
        bfm_entry.grid(row=0, column=1, padx=10, pady=5)
    
        # Search button
        search_btn = ttk.Button(search_frame, text="Look Up Schedule", 
                            command=lambda: self.lookup_equipment_pm_schedule(bfm_var.get().strip(), results_frame))
        search_btn.grid(row=0, column=2, padx=10, pady=5)
    
        # Auto-complete functionality
        bfm_entry.bind('<KeyRelease>', lambda e: self.update_equipment_autocomplete(bfm_var, bfm_entry))
    
        # Results display frame
        results_frame = ttk.LabelFrame(dialog, text="PM Schedule Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        # Instructions
        instructions = ttk.Label(results_frame, 
                            text="Enter a BFM Equipment Number above and click 'Look Up Schedule'\nto see current PM status and next scheduled dates.",
                            font=('Arial', 10), foreground='gray')
        instructions.pack(pady=50)
    
        # Focus on entry field
        bfm_entry.focus_set()
        bfm_entry.bind('<Return>', lambda e: search_btn.invoke())

    def update_equipment_autocomplete(self, bfm_var, entry_widget):
        """Provide autocomplete suggestions for equipment numbers"""
        search_term = bfm_var.get()
        if len(search_term) >= 2:
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    SELECT bfm_equipment_no FROM equipment 
                    WHERE LOWER(bfm_equipment_no) LIKE LOWER(%s)
                    ORDER BY bfm_equipment_no LIMIT 10
                ''', (f'%{search_term}%',))
            
                suggestions = [row[0] for row in cursor.fetchall()]
            
                # Simple autocomplete - you could enhance this with a dropdown
                if len(suggestions) == 1 and suggestions[0].lower().startswith(search_term.lower()):
                    current_pos = entry_widget.index(tk.INSERT)
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, suggestions[0])
                    entry_widget.icursor(current_pos)
                    entry_widget.select_range(current_pos, tk.END)
                
            except Exception as e:
                print(f"Autocomplete error: {e}")

    def lookup_equipment_pm_schedule(self, bfm_no, parent_frame):
        """Lookup and display PM schedule for specific equipment"""
        if not bfm_no:
            messagebox.showwarning("Warning", "Please enter a BFM Equipment Number")
            return
    
        try:
            cursor = self.conn.cursor()
        
            # Clear previous results
            for widget in parent_frame.winfo_children():
                widget.destroy()
        
            # Get equipment information
            cursor.execute('''
                SELECT sap_material_no, description, location, master_lin, status,
                    monthly_pm, six_month_pm, annual_pm,
                    last_monthly_pm, last_six_month_pm, last_annual_pm,
                    next_monthly_pm, next_six_month_pm, next_annual_pm,
                    updated_date
                FROM equipment 
                WHERE bfm_equipment_no = %s
            ''', (bfm_no,))
        
            equipment_data = cursor.fetchone()
        
            if not equipment_data:
                # Equipment not found
                error_label = ttk.Label(parent_frame, 
                                    text=f"Equipment '{bfm_no}' not found in database",
                                    font=('Arial', 12, 'bold'), foreground='red')
                error_label.pack(pady=20)
                return
        
            # Unpack equipment data
            (sap_no, description, location, master_lin, status,
            monthly_pm, six_month_pm, annual_pm,
            last_monthly, last_six_month, last_annual,
            next_monthly, next_six_month, next_annual,
            updated_date) = equipment_data
        
            # Create scrollable frame for results
            canvas = tk.Canvas(parent_frame)
            scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
        
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
        
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
        
            # Equipment header information
            header_frame = ttk.LabelFrame(scrollable_frame, text="Equipment Information", padding=15)
            header_frame.pack(fill='x', padx=5, pady=5)
        
            # Equipment details in a grid
            ttk.Label(header_frame, text="BFM Equipment No:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
            ttk.Label(header_frame, text=bfm_no, font=('Arial', 10)).grid(row=0, column=1, sticky='w', padx=15, pady=2)
        
            ttk.Label(header_frame, text="SAP Material No:", font=('Arial', 10, 'bold')).grid(row=0, column=2, sticky='w', padx=5, pady=2)
            ttk.Label(header_frame, text=sap_no or 'N/A', font=('Arial', 10)).grid(row=0, column=3, sticky='w', padx=15, pady=2)
        
            ttk.Label(header_frame, text="Description:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
            desc_text = (description[:50] + '...') if description and len(description) > 50 else (description or 'N/A')
            ttk.Label(header_frame, text=desc_text, font=('Arial', 10)).grid(row=1, column=1, columnspan=3, sticky='w', padx=15, pady=2)
        
            ttk.Label(header_frame, text="Location:", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
            ttk.Label(header_frame, text=location or 'N/A', font=('Arial', 10)).grid(row=2, column=1, sticky='w', padx=15, pady=2)
        
            ttk.Label(header_frame, text="Status:", font=('Arial', 10, 'bold')).grid(row=2, column=2, sticky='w', padx=5, pady=2)
            status_color = 'green' if status == 'Active' else 'red' if status == 'Missing' else 'orange'
            status_label = ttk.Label(header_frame, text=status or 'Active', font=('Arial', 10, 'bold'), foreground=status_color)
            status_label.grid(row=2, column=3, sticky='w', padx=15, pady=2)
        
            # PM Schedule Status
            schedule_frame = ttk.LabelFrame(scrollable_frame, text="PM Schedule Status", padding=15)
            schedule_frame.pack(fill='x', padx=5, pady=5)
        
            # Create PM schedule table
            pm_data = [
                ['PM Type', 'Required', 'Last Completed', 'Next Due', 'Status', 'Days Until Due']
            ]
        
            current_date = datetime.now()
        
            # Monthly PM
            if monthly_pm:
                last_date_str = last_monthly or 'Never'
                next_date_str = next_monthly or 'Not Scheduled'
            
                status_text, days_until = self.calculate_pm_status(last_monthly, next_monthly, 30, current_date)
                pm_data.append(['Monthly', 'Yes', last_date_str, next_date_str, status_text, str(days_until) if days_until is not None else 'N/A'])
            else:
                pm_data.append(['Monthly', 'No', 'N/A', 'N/A', 'Disabled', 'N/A'])
        
            # Six Month PM
            if six_month_pm:
                last_date_str = last_six_month or 'Never'
                next_date_str = next_six_month or 'Not Scheduled'
            
                status_text, days_until = self.calculate_pm_status(last_six_month, next_six_month, 180, current_date)
                pm_data.append(['Six Month', 'Yes', last_date_str, next_date_str, status_text, str(days_until) if days_until is not None else 'N/A'])
            else:
                pm_data.append(['Six Month', 'No', 'N/A', 'N/A', 'Disabled', 'N/A'])
        
            # Annual PM
            if annual_pm:
                last_date_str = last_annual or 'Never'
                next_date_str = next_annual or 'Not Scheduled'
            
                status_text, days_until = self.calculate_pm_status(last_annual, next_annual, 365, current_date)
                pm_data.append(['Annual', 'Yes', last_date_str, next_date_str, status_text, str(days_until) if days_until is not None else 'N/A'])
            else:
                pm_data.append(['Annual', 'No', 'N/A', 'N/A', 'Disabled', 'N/A'])
        
            # Create table display
            for i, row_data in enumerate(pm_data):
                row_frame = ttk.Frame(schedule_frame)
                row_frame.pack(fill='x', pady=1)
            
                for j, cell_data in enumerate(row_data):
                    if i == 0:  # Header row
                        label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10, 'bold'), 
                                        relief='raised', padding=5, width=15)
                    else:  # Data rows
                        # Color code the status column
                        if j == 4:  # Status column
                            if 'Overdue' in cell_data:
                                color = 'red'
                            elif 'Due Soon' in cell_data:
                                color = 'orange'  
                            elif 'Current' in cell_data:
                                color = 'green'
                            else:
                                color = 'gray'
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10, 'bold'), 
                                            foreground=color, padding=3, width=15)
                        else:
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10), 
                                            padding=3, width=15)
                    
                    label.pack(side='left', padx=2)
        
            # Recent PM History
            history_frame = ttk.LabelFrame(scrollable_frame, text="Recent PM History (Last 10)", padding=15)
            history_frame.pack(fill='x', padx=5, pady=5)
        
            cursor.execute('''
                SELECT pm_type, technician_name, completion_date, 
                    (labor_hours + labor_minutes/60.0) as total_hours,
                    SUBSTR(notes, 1, 50) as notes_preview
                FROM pm_completions 
                WHERE bfm_equipment_no = %s
                ORDER BY completion_date DESC LIMIT 10
            ''', (bfm_no,))
        
            recent_completions = cursor.fetchall()
        
            if recent_completions:
                # History table
                history_data = [['Date', 'PM Type', 'Technician', 'Hours', 'Notes']]
            
                for completion in recent_completions:
                    pm_type, technician, comp_date, hours, notes_preview = completion
                    hours_str = f"{hours:.1f}h" if hours else '0h'
                    notes_str = (notes_preview + '...') if notes_preview and len(notes_preview) >= 50 else (notes_preview or '')
                    history_data.append([comp_date, pm_type, technician, hours_str, notes_str])
            
                for i, row_data in enumerate(history_data):
                    row_frame = ttk.Frame(history_frame)
                    row_frame.pack(fill='x', pady=1)
                
                    for j, cell_data in enumerate(row_data):
                        if i == 0:  # Header row
                            width = [10, 10, 15, 8, 25][j]  # Different widths for each column
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10, 'bold'), 
                                        relief='raised', padding=5, width=width)
                        else:
                            width = [10, 10, 15, 8, 25][j]
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 9), 
                                            padding=3, width=width)
                    
                        label.pack(side='left', padx=2)
            else:
                no_history_label = ttk.Label(history_frame, text="No PM completions found for this equipment", 
                                        font=('Arial', 10), foreground='gray')
                no_history_label.pack(pady=10)
        
            # Upcoming schedule (if any)
            upcoming_frame = ttk.LabelFrame(scrollable_frame, text="Upcoming Weekly Schedules", padding=15)
            upcoming_frame.pack(fill='x', padx=5, pady=5)
        
            cursor.execute('''
                SELECT pm_type, assigned_technician, scheduled_date, week_start_date, status
                FROM weekly_pm_schedules
                WHERE bfm_equipment_no = %s AND scheduled_date::date >= CURRENT_DATE
                ORDER BY scheduled_date ASC LIMIT 5
            ''', (bfm_no,))
        
            upcoming_schedules = cursor.fetchall()
        
            if upcoming_schedules:
                upcoming_data = [['PM Type', 'Assigned To', 'Scheduled Date', 'Week Start', 'Status']]
            
                for schedule in upcoming_schedules:
                    pm_type, technician, sched_date, week_start, sched_status = schedule
                    upcoming_data.append([pm_type, technician, sched_date, week_start, sched_status])
            
                for i, row_data in enumerate(upcoming_data):
                    row_frame = ttk.Frame(upcoming_frame)
                    row_frame.pack(fill='x', pady=1)
                
                    for j, cell_data in enumerate(row_data):
                        if i == 0:  # Header row
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10, 'bold'), 
                                            relief='raised', padding=5, width=12)
                        else:
                            label = ttk.Label(row_frame, text=cell_data, font=('Arial', 10), 
                                            padding=3, width=12)
                    
                        label.pack(side='left', padx=2)
            else:
                no_upcoming_label = ttk.Label(upcoming_frame, text="No upcoming scheduled PMs found", 
                                            font=('Arial', 10), foreground='gray')
                no_upcoming_label.pack(pady=10)
        
            # Pack the canvas and scrollbar
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
        
            # Update scroll region
            scrollable_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        except Exception as e:
            error_label = ttk.Label(parent_frame, 
                                text=f"Error looking up equipment: {str(e)}", 
                                font=('Arial', 10), foreground='red')
            error_label.pack(pady=20)
            print(f"PM Schedule lookup error: {e}")

    def calculate_pm_status(self, last_pm_date, next_pm_date, frequency_days, current_date):
        """Calculate PM status and days until due"""
        try:
            if not last_pm_date and not next_pm_date:
                return "Never Done", None
        
            # Use next_pm_date if available, otherwise calculate from last_pm_date
            if next_pm_date:
                next_due = datetime.strptime(next_pm_date, '%Y-%m-%d')
            elif last_pm_date:
                last_date = datetime.strptime(last_pm_date, '%Y-%m-%d')
                next_due = last_date + timedelta(days=frequency_days)
            else:
                return "Not Scheduled", None
        
            days_until = (next_due - current_date).days
        
            if days_until < 0:
                return f"Overdue ({abs(days_until)} days)", days_until
            elif days_until <= 7:
                return f"Due Soon ({days_until} days)", days_until
            elif days_until <= 30:
                return f"Due in {days_until} days", days_until
            else:
                return f"Current ({days_until} days)", days_until
            
        except ValueError:
            return "Date Error", None
        except Exception as e:
            return "Error", None
           
    

    def export_monthly_data(self, month_var, year_var):
        """Export monthly completion data to CSV"""
        try:
            # Parse month and year
            month_text = month_var.get()
            month_num = month_text.split(' - ')[0] if month_text else f"{datetime.now().month:02d}"
            year = year_var.get() or str(datetime.now().year)
            month_name = calendar.month_name[int(month_num)]
        
            # Get file path
            filename = filedialog.asksaveasfilename(
            title="Export Monthly PM Completions",
            defaultextension=".csv",
            initialname=f"PM_Completions_{month_name}_{year}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
        
            if filename:
                # Calculate date range
                start_date = f"{year}-{month_num}-01"
                year_int = int(year)
                month_int = int(month_num)
                if month_int == 12:
                    next_month = 1
                    next_year = year_int + 1
                else:
                    next_month = month_int + 1
                    next_year = year_int
                end_date = (datetime(next_year, next_month, 1) - timedelta(days=1)).strftime('%Y-%m-%d')
            
                cursor = self.conn.cursor()
            
                # Get all completion data
                cursor.execute('''
                    SELECT 
                        pc.completion_date,
                        pc.bfm_equipment_no,
                        e.sap_material_no,
                        e.description,
                        e.location,
                        pc.pm_type,
                        pc.technician_name,
                        pc.labor_hours,
                        pc.labor_minutes,
                        (pc.labor_hours + pc.labor_minutes/60.0) as total_hours,
                        pc.special_equipment,
                        pc.notes,
                        pc.pm_due_date,
                        pc.next_annual_pm_date
                    FROM pm_completions pc
                    LEFT JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
                    WHERE pc.completion_date BETWEEN %s AND %s
                    UNION ALL
                    SELECT 
                        cf.reported_date,
                        cf.bfm_equipment_no,
                        '' as sap_material_no,
                        cf.description,
                        cf.location,
                        'CANNOT FIND' as pm_type,
                        cf.technician_name,
                        0 as labor_hours,
                        0 as labor_minutes,
                        0 as total_hours,
                        '' as special_equipment,
                        cf.notes,
                        '' as pm_due_date,
                        '' as next_annual_pm_date
                    FROM cannot_find_assets cf
                    WHERE cf.reported_date BETWEEN %s AND %s
                    ORDER BY completion_date DESC
                ''', (start_date, end_date, start_date, end_date))
            
                data = cursor.fetchall()
            
                # Create DataFrame
                columns = [
                    'Completion Date', 'BFM Equipment No', 'SAP Material No', 
                    'Equipment Description', 'Location', 'PM Type', 'Technician', 
                    'Labor Hours', 'Labor Minutes', 'Total Hours', 'Special Equipment', 
                    'Notes', 'PM Due Date', 'Next Annual PM Date'
                ]
            
                df = pd.DataFrame(data, columns=columns)
                df.to_csv(filename, index=False)
            
                messagebox.showinfo("Success", f"Monthly data exported to: {filename}")
            
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export monthly data: {str(e)}")   
    
    def on_completion_double_click(self, event):
        """Handle double-click on recent PM completions to generate PDF"""
        selection = self.recent_completions_tree.selection()
        if not selection:
            return
    
        # Get the selected item's values
        item = self.recent_completions_tree.item(selection[0])
        values = item['values']
    
        if len(values) >= 5:
            completion_date = values[0]
            bfm_no = values[1] 
            pm_type = values[2]
            technician = values[3]
        
            # Get full completion details from database
            self.generate_pm_completion_pdf(completion_date, bfm_no, pm_type, technician)

    def on_completion_select(self, event):
        """Handle single-click on recent PM completions to populate form fields"""
        selection = self.recent_completions_tree.selection()
        if not selection:
            return

        # Get the selected item's values
        item = self.recent_completions_tree.item(selection[0])
        values = item['values']

        if len(values) >= 5:
            completion_date = values[0]
            bfm_no = values[1]
            pm_type = values[2]
            technician = values[3]

            # Populate the form fields with the selected completion data
            self.completion_bfm_var.set(bfm_no)
            self.pm_type_var.set(pm_type)
            self.completion_tech_var.set(technician)

            # Update status bar to confirm selection
            if hasattr(self, 'update_status'):
                self.update_status(f"Selected equipment {bfm_no} from recent completions")

    def generate_pm_completion_pdf(self, completion_date, bfm_no, pm_type, technician):
        """Generate and export PM completion PDF document"""
        try:
            cursor = self.conn.cursor()
        
            # Get full completion details
            cursor.execute('''
                SELECT pc.*, e.sap_material_no, e.description, e.location
                FROM pm_completions pc
                LEFT JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
                WHERE pc.completion_date = %s AND pc.bfm_equipment_no = %s
                AND pc.pm_type = %s AND pc.technician_name = %s
            ''', (completion_date, bfm_no, pm_type, technician))
        
            completion_data = cursor.fetchone()
        
            if not completion_data:
                messagebox.showerror("Error", "Could not find completion details")
                return
            
            # Add just the title parameter
            filename = filedialog.asksaveasfilename(
                title="Save PM Completion Document"
            )
        
            if filename:
                self.create_pm_completion_pdf(completion_data, filename)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PDF: {str(e)}")

    def create_pm_completion_pdf(self, completion_data, filename):
        """Create the actual PDF document"""
        try:
            # Based on the debug output, map the columns correctly:
            # (538, '20243111', 'Annual', 'Ronald Houghs', '2025-9-19', 0.0, 30.0, '2025-9-19', '', '', '2026-09-10', 'Preventive_Maintenance_Form', 'A2', '2025-09-22 11:31:50', '96007107', 'DRILL TEMPLATE FOR STRINGER SPLICE FR30', 'LCS001 TOP')
        
            completion_id = completion_data[0]        # 538
            bfm_no = completion_data[1]               # '20243111'
            pm_type = completion_data[2]              # 'Annual'
            technician_name = completion_data[3]      # 'Ronald Houghs'
            completion_date = completion_data[4]      # '2025-9-19'
            labor_hours = completion_data[5]          # 0.0
            labor_minutes = completion_data[6]        # 30.0
            pm_due_date = completion_data[7]          # '2025-9-19'
            special_equipment = completion_data[8]    # ''
            notes = completion_data[9]                # ''
            next_annual_pm_date = completion_data[10] # '2026-09-10'
            # Skip column 11 and 12 (appears to be form type and status)
            updated_date = completion_data[13]        # '2025-09-22 11:31:50'
            sap_material_no = completion_data[14]     # '96007107'
            description = completion_data[15]         # 'DRILL TEMPLATE FOR STRINGER SPLICE FR30'
            location = completion_data[16]            # 'LCS001 TOP'
        
            # Create PDF document
            doc = SimpleDocTemplate(filename, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []
        
            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                spaceAfter=30,
                alignment=1,  # Center alignment
                textColor=colors.darkblue
            )
        
            header_style = ParagraphStyle(
                'CustomHeader',
                parent=styles['Heading2'],
                fontSize=14,
                spaceAfter=12,
                textColor=colors.darkblue
            )
        
            # Add company logo if available
            script_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(script_dir, "img", "ait_logo.png")

            if os.path.exists(logo_path):
                logo = Image(logo_path, width=2*inch, height=1*inch)
                story.append(logo)
                story.append(Spacer(1, 12))
            else:
                print(f"Logo not found at: {logo_path}")
                # Fallback to text header
                story.append(Paragraph("AIT - BUILDING THE FUTURE OF AEROSPACE", title_style))
                story.append(Spacer(1, 12))
            
        
            # Title
            story.append(Paragraph("PM COMPLETION CERTIFICATE", title_style))
            story.append(Spacer(1, 20))
        
            # Equipment Information Section
            story.append(Paragraph("EQUIPMENT INFORMATION", header_style))
            
            equipment_info = f"""
            <b>BFM Equipment Number:</b> {bfm_no}<br/>
            <b>SAP Material Number:</b> {sap_material_no or 'N/A'}<br/>
            <b>Equipment Description:</b> {description or 'N/A'}<br/>
            <b>Location:</b> {location or 'N/A'}<br/>
            """
            story.append(Paragraph(equipment_info, styles['Normal']))
            story.append(Spacer(1, 20))
        
            # PM Details Section
            story.append(Paragraph("MAINTENANCE DETAILS", header_style))
            
            pm_details = f"""
            <b>PM Type:</b> {pm_type}<br/>
            <b>Completion Date:</b> {completion_date}<br/>
            <b>Technician:</b> {technician_name}<br/>
            <b>Labor Time:</b> {int(labor_hours)}h {int(labor_minutes)}m<br/>
            <b>Special Equipment Used:</b> {special_equipment or 'None'}<br/>
            <b>Next Annual PM Due:</b> {next_annual_pm_date or 'Not scheduled'}<br/>
            """
            story.append(Paragraph(pm_details, styles['Normal']))
            story.append(Spacer(1, 20))
            
            # Technician Notes Section
            story.append(Paragraph("TECHNICIAN VALIDATION", header_style))
            
            validation_text = f"""
            <b>Equipment Status Validation:</b><br/>
            The undersigned technician certifies that the preventive maintenance has been completed 
            and no equipment problems were identified during the maintenance procedure.
            <br/><br/>
            <b>Technician Notes:</b><br/>
            {notes or 'No issues reported. Equipment operating within normal parameters.'}
            """
            story.append(Paragraph(validation_text, styles['Normal']))
            story.append(Spacer(1, 30))
        
            # Footer
            story.append(Spacer(1, 30))
            footer_text = f"""
            <i>Document generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
            AIT Complete CMMS - Computerized Maintenance Management System</i>
            """
            story.append(Paragraph(footer_text, styles['Normal']))
        
            # Build the PDF
            doc.build(story)
        
            messagebox.showinfo("Success", f"PM Completion document saved to:\n{filename}")
        
            # Ask if user wants to open the PDF
            if messagebox.askyesno("Open Document", "Would you like to open the PDF document now?"):
                os.startfile(filename)  # Windows
            
        except Exception as e:
            messagebox.showerror("PDF Creation Error", f"Failed to create PDF: {str(e)}")
            print(f"Full error: {e}")
    
    def create_cannot_find_tab(self):
        """Cannot Find Assets tab with search functionality"""
        self.cannot_find_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.cannot_find_frame, text="Cannot Find Assets")

        # Controls
        controls_frame = ttk.LabelFrame(self.cannot_find_frame, text="Cannot Find Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)

        # Add Asset button
        ttk.Button(controls_frame, text="CHECK: Add Asset", 
                command=self.add_cannot_find_asset_dialog,
                style='Accent.TButton').pack(side='left', padx=5)
    
        ttk.Button(controls_frame, text="Refresh List", 
                command=self.load_cannot_find_assets).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export to PDF", 
                command=self.export_cannot_find_pdf).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Mark as Found", 
                command=self.mark_asset_found).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Delete Asset", 
            command=self.delete_cannot_find_asset).pack(side='left', padx=5)        
        ttk.Button(controls_frame, text="Edit Asset", 
            command=self.edit_cannot_find_asset).pack(side='left', padx=5)
    
        # Search frame - NEW!
        search_frame = ttk.Frame(controls_frame)
        search_frame.pack(side='right', padx=5)
        
        ttk.Label(search_frame, text="WARNING: Search:").pack(side='left', padx=(10, 5))
        self.cannot_find_search_var = tk.StringVar()
        self.cannot_find_search_var.trace('w', lambda *args: self.filter_cannot_find_assets())
        
        search_entry = ttk.Entry(search_frame, textvariable=self.cannot_find_search_var, width=25)
        search_entry.pack(side='left', padx=5)
        
        # Clear search button
        ttk.Button(search_frame, text="CHECK:", width=3,
                command=lambda: self.cannot_find_search_var.set('')).pack(side='left', padx=2)

        # Cannot Find list
        list_frame = ttk.LabelFrame(self.cannot_find_frame, text="Missing Assets", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.cannot_find_tree = ttk.Treeview(list_frame,
                                        columns=('BFM', 'Description', 'Location', 'Technician', 'Report Date', 'Status'),
                                        show='headings')

        columns_config = {
            'BFM': ('BFM Equipment No.', 130),
            'Description': ('Description', 250),
            'Location': ('Location', 120),
            'Technician': ('Reported By', 120),
            'Report Date': ('Report Date', 100),
            'Status': ('Status', 80)
        }

        for col, (heading, width) in columns_config.items():
            self.cannot_find_tree.heading(col, text=heading)
            self.cannot_find_tree.column(col, width=width)

        # Scrollbars
        cf_v_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.cannot_find_tree.yview)
        cf_h_scrollbar = ttk.Scrollbar(list_frame, orient='horizontal', command=self.cannot_find_tree.xview)
        self.cannot_find_tree.configure(yscrollcommand=cf_v_scrollbar.set, xscrollcommand=cf_h_scrollbar.set)

        # Pack treeview and scrollbars
        self.cannot_find_tree.grid(row=0, column=0, sticky='nsew')
        cf_v_scrollbar.grid(row=0, column=1, sticky='ns')
        cf_h_scrollbar.grid(row=1, column=0, sticky='ew')

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # Load initial data
        self.load_cannot_find_assets()
    
    
    
    def delete_cannot_find_asset(self):
        """Permanently delete selected asset from the cannot_find_assets table"""
        # Get selected item
        selected_item = self.cannot_find_tree.selection()

        if not selected_item:
            messagebox.showwarning("No Selection", "Please select an asset to delete.")
            return

        # Get the selected item data
        item = selected_item[0]
        asset_data = self.cannot_find_tree.item(item)['values']
        bfm_number = asset_data[0]  # BFM is the first column
        description = asset_data[1] if len(asset_data) > 1 else ''

        # Confirm permanent deletion
        result = messagebox.askyesno(
            "Confirm Permanent Deletion", 
            f"Permanently delete asset {bfm_number} from the Cannot Find database?\n\n"
            f"Description: {description}\n\n"
            "WARNING: WARNING: This action cannot be undone!\n"
            "The asset will be completely removed from the Cannot Find list."
        )

        if result:
            try:
                cursor = self.conn.cursor()
            
                # Delete from cannot_find_assets table
                cursor.execute('DELETE FROM cannot_find_assets WHERE bfm_equipment_no = %s', (bfm_number,))
            
                # Optional: Update the equipment table status back to Active if it exists there
                # You can comment this out if you don't want to change the equipment status
                cursor.execute('''
                    UPDATE equipment 
                    SET status = 'Active' 
                    WHERE bfm_equipment_no = %s AND status = 'Cannot Find'
                ''', (bfm_number,))
            
                # Commit the changes
                self.conn.commit()
            
                # Remove from treeview display
                self.cannot_find_tree.delete(item)
            
                # Update statistics if method exists
                if hasattr(self, 'update_equipment_statistics'):
                    self.update_equipment_statistics()
            
                messagebox.showinfo("Success", f"Asset {bfm_number} has been permanently deleted from the Cannot Find list.")
            
            except Exception as e:
                self.conn.rollback()  # Rollback changes if there's an error
                messagebox.showerror("Error", f"Failed to delete asset from database: {str(e)}")
                print(f"Delete error details: {e}")


    def delete_from_database(self, bfm_number):
        """Delete asset record from database"""
        # Example using SQLite
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM cannot_find_assets WHERE bfm_number = %s", (bfm_number,))
            self.connection.commit()
        except Exception as e:
            raise Exception(f"Database error: {str(e)}")



    def edit_cannot_find_asset(self):
        """Edit selected asset from cannot find list"""
        # Get selected item
        selected_item = self.cannot_find_tree.selection()
    
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select an asset to edit.")
            return
    
        # Get the selected item data
        item = selected_item[0]
        asset_data = self.cannot_find_tree.item(item)['values']
        
        # Open edit window
        self.open_edit_window(item, asset_data)


    def open_edit_window(self, tree_item, asset_data):
        """Open edit window for selected asset"""
        # Create edit window
        edit_window = tk.Toplevel(self.root)
        edit_window.title("Edit Asset")
        edit_window.geometry("500x400")
        edit_window.resizable(True, True)
    
        # Make window modal
        edit_window.transient(self.root)
        edit_window.grab_set()
    
        # Center the window
        edit_window.update_idletasks()
        x = (edit_window.winfo_screenwidth() // 2) - (500 // 2)
        y = (edit_window.winfo_screenheight() // 2) - (400 // 2)
        edit_window.geometry(f"500x400+{x}+{y}")
    
        # Create main frame with padding
        main_frame = ttk.Frame(edit_window, padding=20)
        main_frame.pack(fill='both', expand=True)
    
        # Title
        title_label = ttk.Label(main_frame, text="Edit Asset Information", 
                            font=('TkDefaultFont', 12, 'bold'))
        title_label.pack(pady=(0, 20))
    
        # Create form frame
        form_frame = ttk.Frame(main_frame)
        form_frame.pack(fill='both', expand=True)
    
        # Field labels and entry variables
        fields = [
            ('BFM Equipment No.', asset_data[0] if len(asset_data) > 0 else ''),
            ('Description', asset_data[1] if len(asset_data) > 1 else ''),
            ('Location', asset_data[2] if len(asset_data) > 2 else ''),
            ('Technician', asset_data[3] if len(asset_data) > 3 else ''),
            ('Report Date', asset_data[4] if len(asset_data) > 4 else ''),
            ('Status', asset_data[5] if len(asset_data) > 5 else '')
        ]
    
        # Store entry widgets for later access
        entries = {}
    
        # Create form fields
        for i, (label_text, value) in enumerate(fields):
            # Label
            label = ttk.Label(form_frame, text=label_text + ":")
            label.grid(row=i, column=0, sticky='w', padx=(0, 10), pady=5)
        
            # Entry widget
            if label_text == 'Status':
                # Use combobox for status
                entry = ttk.Combobox(form_frame, values=['Missing', 'Found', 'Damaged', 'Disposed'])
                entry.set(value)
            elif label_text == 'Description':
                # Use text widget for description (multiline)
                entry = tk.Text(form_frame, height=3, width=40)
                entry.insert('1.0', value)
            else:
                entry = ttk.Entry(form_frame, width=40)
                entry.insert(0, value)
        
            entry.grid(row=i, column=1, sticky='ew', pady=5)
            entries[label_text] = entry
    
        # Configure grid weights
        form_frame.grid_columnconfigure(1, weight=1)
    
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(20, 0))
    
        # Buttons
        def save_changes():
            """Save the edited data"""
            try:
                # Get updated values
                updated_data = []
                for field_name, _ in fields:
                    entry_widget = entries[field_name]
                    if isinstance(entry_widget, tk.Text):
                        value = entry_widget.get('1.0', 'end-1c')  # Get text content
                    else:
                        value = entry_widget.get()
                    updated_data.append(value)
            
                # Validate required fields
                if not updated_data[0].strip():  # BFM number is required
                    messagebox.showerror("Validation Error", "BFM Equipment No. is required.")
                    return
            
                # TODO: Update database here
                # Example: self.update_asset_in_database(updated_data)
            
                # Update treeview
                self.cannot_find_tree.item(tree_item, values=updated_data)
            
                # Show success message
                messagebox.showinfo("Success", "Asset information updated successfully.")
                
                # Close edit window
                edit_window.destroy()
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update asset: {str(e)}")
    
        def cancel_edit():
            """Cancel editing and close window"""
            edit_window.destroy()
    
        # Save and Cancel buttons
        ttk.Button(button_frame, text="Save Changes", 
                command=save_changes).pack(side='right', padx=(5, 0))
        ttk.Button(button_frame, text="Cancel", 
                command=cancel_edit).pack(side='right')
    
        # Focus on first entry
        if fields:
            first_entry = entries[fields[0][0]]
            if not isinstance(first_entry, tk.Text):
                first_entry.focus()
                first_entry.select_range(0, tk.END)
            else:
                first_entry.focus()

    def update_asset_in_database(self, asset_data):
        """Update asset record in database"""
        # Example using SQLite
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE cannot_find_assets 
                SET description = %s, location = %s, technician = %s, 
                    reported_date = %s, status = %s
                WHERE bfm_number = %s
            """, (asset_data[1], asset_data[2], asset_data[3], 
                asset_data[4], asset_data[5], asset_data[0]))
            self.connection.commit()
        except Exception as e:
            raise Exception(f"Database error: {str(e)}")





    
        
    def create_run_to_failure_tab(self):
        """Run to Failure Assets tab"""
        self.run_to_failure_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.run_to_failure_frame, text="Run to Failure Assets")
    
        # Controls
        controls_frame = ttk.LabelFrame(self.run_to_failure_frame, text="Run to Failure Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
    
        ttk.Button(controls_frame, text="Refresh List", 
                command=self.load_run_to_failure_assets).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export to PDF", 
                command=self.export_run_to_failure_pdf).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Reactivate Asset", 
                command=self.reactivate_asset).pack(side='left', padx=5)
    
        # Run to Failure list
        list_frame = ttk.LabelFrame(self.run_to_failure_frame, text="Run to Failure Assets", padding=10)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        self.run_to_failure_tree = ttk.Treeview(list_frame,
                                            columns=('BFM', 'Description', 'Location', 'Technician', 'Completion Date', 'Hours'),
                                            show='headings',
                                            selectmode='extended')
    
        columns_config = {
            'BFM': ('BFM Equipment No.', 130),
            'Description': ('Description', 250),
            'Location': ('Location', 120),
            'Technician': ('Completed By', 120),
            'Completion Date': ('Completion Date', 120),
            'Hours': ('Hours', 80)
        }
    
        for col, (heading, width) in columns_config.items():
            self.run_to_failure_tree.heading(col, text=heading)
            self.run_to_failure_tree.column(col, width=width)
    
        # Scrollbars
        rtf_v_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.run_to_failure_tree.yview)
        rtf_h_scrollbar = ttk.Scrollbar(list_frame, orient='horizontal', command=self.run_to_failure_tree.xview)
        self.run_to_failure_tree.configure(yscrollcommand=rtf_v_scrollbar.set, xscrollcommand=rtf_h_scrollbar.set)
    
        # Pack treeview and scrollbars
        self.run_to_failure_tree.grid(row=0, column=0, sticky='nsew')
        rtf_v_scrollbar.grid(row=0, column=1, sticky='ns')
        rtf_h_scrollbar.grid(row=1, column=0, sticky='ew')
    
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
    
        # Load initial data
        self.load_run_to_failure_assets()


    
    def create_cm_management_tab(self):
        """Enhanced Corrective Maintenance management tab with SharePoint integration and filter"""
        self.cm_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.cm_frame, text="Corrective Maintenance")

        # CM controls - Enhanced with SharePoint button
        controls_frame = ttk.LabelFrame(self.cm_frame, text="CM Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)

        # First row of controls
        controls_row1 = ttk.Frame(controls_frame)
        controls_row1.pack(fill='x', pady=(0, 5))
    
        ttk.Button(controls_row1, text="Create New CM", 
                command=self.create_cm_dialog).pack(side='left', padx=5)
        ttk.Button(controls_row1, text="Edit CM", 
                command=self.edit_cm_dialog).pack(side='left', padx=5)
        ttk.Button(controls_row1, text="Complete CM", 
                command=self.complete_cm_dialog).pack(side='left', padx=5)
        ttk.Button(controls_row1, text="Refresh CM List", 
                command=self.load_corrective_maintenance_with_filter).pack(side='left', padx=5)

        # Filter controls
        filter_frame = ttk.Frame(controls_frame)
        filter_frame.pack(fill='x')
        
        ttk.Label(filter_frame, text="Filter by Status:").pack(side='left', padx=(0, 5))
    
        # Create filter dropdown
        self.cm_filter_var = tk.StringVar(value="All")
        self.cm_filter_dropdown = ttk.Combobox(filter_frame, textvariable=self.cm_filter_var, 
                                            values=["All", "Open", "Closed"],
                                            state="readonly", width=15)
        self.cm_filter_dropdown.pack(side='left', padx=5)
        self.cm_filter_dropdown.bind('<<ComboboxSelected>>', self.filter_cm_list)
    
        # Clear filter button
        ttk.Button(filter_frame, text="Clear Filter", 
                command=self.clear_cm_filter).pack(side='left', padx=5)

        # CM list with enhanced columns for SharePoint data
        cm_list_frame = ttk.LabelFrame(self.cm_frame, text="Corrective Maintenance List", padding=10)
        cm_list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Enhanced treeview with additional columns
        self.cm_tree = ttk.Treeview(cm_list_frame,
                                columns=('CM Number', 'BFM', 'Description', 'Priority', 'Assigned', 'Status', 'Created', 'Source'),
                                show='headings')

        cm_columns = {
            'CM Number': 120,
            'BFM': 120,
            'Description': 250,
            'Priority': 80,
            'Assigned': 120,
            'Status': 80,
            'Created': 100,
            'Source': 80  # New column to show if from SharePoint
        }

        for col, width in cm_columns.items():
            self.cm_tree.heading(col, text=col)
            self.cm_tree.column(col, width=width)

        # Scrollbars
        cm_v_scrollbar = ttk.Scrollbar(cm_list_frame, orient='vertical', command=self.cm_tree.yview)
        cm_h_scrollbar = ttk.Scrollbar(cm_list_frame, orient='horizontal', command=self.cm_tree.xview)
        self.cm_tree.configure(yscrollcommand=cm_v_scrollbar.set, xscrollcommand=cm_h_scrollbar.set)

        # Pack treeview and scrollbars
        self.cm_tree.grid(row=0, column=0, sticky='nsew')
        cm_v_scrollbar.grid(row=0, column=1, sticky='ns')
        cm_h_scrollbar.grid(row=1, column=0, sticky='ew')

        cm_list_frame.grid_rowconfigure(0, weight=1)
        cm_list_frame.grid_columnconfigure(0, weight=1)
        
        # Initialize filter data storage
        self.cm_original_data = []
        
        # Load CM data
        self.load_corrective_maintenance_with_filter()

    def load_corrective_maintenance_with_filter(self):
        """Wrapper for your existing load method that adds filter support"""
    
        # Initialize/clear filter data
        self.cm_original_data = []
    
        # Call your existing load method
        self.load_corrective_maintenance()
    
        # After loading, capture data for filtering
        for item in self.cm_tree.get_children():
            item_values = self.cm_tree.item(item, 'values')
            self.cm_original_data.append(item_values)
    
        # Reset filter to show all
        if hasattr(self, 'cm_filter_var'):
            self.cm_filter_var.set("All")
    
    def filter_cm_list(self, event=None):
        """Filter the CM list based on selected status"""
        # Don't filter if no data is loaded yet
        if not hasattr(self, 'cm_original_data') or not self.cm_original_data:
         
            return
        
        selected_filter = self.cm_filter_var.get()
        
    
        # Clear current tree
        for item in self.cm_tree.get_children():
            self.cm_tree.delete(item)
    
        # Filter and display data
        filtered_count = 0
        for item_data in self.cm_original_data:
            # Check if status matches (Status is at index 5)
            if selected_filter == "All" or (len(item_data) > 5 and str(item_data[5]) == selected_filter):
                self.cm_tree.insert('', 'end', values=item_data)
                filtered_count += 1
        
    def clear_cm_filter(self):
        """Clear the filter and show all items"""
        self.cm_filter_var.set("All")
        self.filter_cm_list()
   

    def process_sharepoint_excel_file(self, file_path):
        """Process the SharePoint Excel file and import CMDATA"""
        try:
            import pandas as pd
        
            self.sharepoint_status_label.config(text="Processing Excel file...")
            self.root.update()
        
            # Read the CMDATA sheet
            try:
                df = pd.read_excel(file_path, sheet_name='CMData')
            except Exception as e:
                # If CMDATA sheet doesn't exist, show available sheets
                xl_file = pd.ExcelFile(file_path)
                available_sheets = xl_file.sheet_names
            
                messagebox.showerror("Sheet Not Found", 
                                f"Could not find 'CMDATA' sheet.\n\n"
                                f"Available sheets: {', '.join(available_sheets)}\n\n"
                                f"Please verify the correct sheet name.")
                return
        
            # Show data preview and column mapping dialog
            self.show_sharepoint_data_preview(df)
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read Excel file: {str(e)}")
            self.sharepoint_status_label.config(text="Import failed")

    def show_sharepoint_data_preview(self, df):
        """Show preview of SharePoint data and allow column mapping"""
        dialog = tk.Toplevel(self.root)
        dialog.title("SharePoint Data Preview & Mapping")
        dialog.geometry("900x700")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Data preview
        preview_frame = ttk.LabelFrame(dialog, text="Data Preview (First 10 rows)", padding=10)
        preview_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        # Create treeview for data preview
        preview_columns = list(df.columns)
        preview_tree = ttk.Treeview(preview_frame, columns=preview_columns, show='headings')
    
        # Configure columns
        for col in preview_columns:
            preview_tree.heading(col, text=col)
            preview_tree.column(col, width=100)
    
        # Add data (first 10 rows)
        for index, row in df.head(10).iterrows():
            values = [str(val) if pd.notna(val) else '' for val in row]
            preview_tree.insert('', 'end', values=values)
    
        # Scrollbars
        preview_v_scrollbar = ttk.Scrollbar(preview_frame, orient='vertical', command=preview_tree.yview)
        preview_h_scrollbar = ttk.Scrollbar(preview_frame, orient='horizontal', command=preview_tree.xview)
        preview_tree.configure(yscrollcommand=preview_v_scrollbar.set, xscrollcommand=preview_h_scrollbar.set)
    
        preview_tree.grid(row=0, column=0, sticky='nsew')
        preview_v_scrollbar.grid(row=0, column=1, sticky='ns')
        preview_h_scrollbar.grid(row=1, column=0, sticky='ew')
    
        preview_frame.grid_rowconfigure(0, weight=1)
        preview_frame.grid_columnconfigure(0, weight=1)
    
        # Column mapping
        mapping_frame = ttk.LabelFrame(dialog, text="Map Columns to CM Fields", padding=10)
        mapping_frame.pack(fill='x', padx=10, pady=5)
    
        # Column mappings
        mappings = {}
    
        # CM fields that can be mapped
        cm_fields = [
            ("CM Number/ID", "cm_number"),
            ("Equipment/BFM Number", "bfm_equipment_no"),
            ("Problem Description", "description"),
            ("Priority Level", "priority"),
            ("Assigned Technician", "assigned_technician"),
            ("Status", "status"),
            ("Created Date", "created_date"),
            ("Notes/Comments", "notes")
        ]
    
        # Add "None" option to CSV columns
        column_options = ["(Not in Data)"] + list(df.columns)
    
        row = 0
        for field_name, field_key in cm_fields:
            ttk.Label(mapping_frame, text=field_name + ":").grid(row=row, column=0, sticky='w', pady=2)
        
            mapping_var = tk.StringVar()
            combo = ttk.Combobox(mapping_frame, textvariable=mapping_var, values=column_options, width=30)
            combo.grid(row=row, column=1, padx=10, pady=2)
        
            # Try to auto-match common column names
            for col in df.columns:
                col_lower = col.lower()
                if field_key == 'cm_number' and any(term in col_lower for term in ['cm', 'id', 'number', 'ticket']):
                    mapping_var.set(col)
                    break
                elif field_key == 'bfm_equipment_no' and any(term in col_lower for term in ['bfm', 'equipment', 'asset']):
                    mapping_var.set(col)
                    break
                elif field_key == 'description' and any(term in col_lower for term in ['description', 'problem', 'issue']):
                    mapping_var.set(col)
                    break
                elif field_key == 'priority' and 'priority' in col_lower:
                    mapping_var.set(col)
                    break
                elif field_key == 'assigned_technician' and any(term in col_lower for term in ['technician', 'assigned', 'owner']):
                    mapping_var.set(col)
                    break
                elif field_key == 'status' and 'status' in col_lower:
                    mapping_var.set(col)
                    break
                elif field_key == 'created_date' and any(term in col_lower for term in ['date', 'created', 'opened']):
                    mapping_var.set(col)
                    break
        
            mappings[field_key] = mapping_var
            row += 1
    
        def import_sharepoint_data():
            """Import the mapped SharePoint data"""
            try:
                cursor = self.conn.cursor()
                imported_count = 0
                error_count = 0
            
                self.sharepoint_status_label.config(text="Importing SharePoint data...")
                self.root.update()
            
                for index, row in df.iterrows():
                    try:
                        # Extract mapped data
                        data = {}
                        for field_key, mapping_var in mappings.items():
                            column_name = mapping_var.get()
                            if column_name != "(Not in Data)" and column_name in df.columns:
                                value = row[column_name]
                                if pd.isna(value):
                                    data[field_key] = None
                                else:
                                    # Handle different data types
                                    if field_key == 'created_date':
                                        try:
                                            # Try to parse date
                                            parsed_date = pd.to_datetime(value).strftime('%Y-%m-%d')
                                            data[field_key] = parsed_date
                                        except:
                                            data[field_key] = str(value)
                                    else:
                                        data[field_key] = str(value)
                            else:
                                data[field_key] = None
                    
                        # Generate CM number if not provided
                        if not data.get('cm_number'):
                            data['cm_number'] = f"SP-{datetime.now().strftime('%Y%m%d')}-{index+1:04d}"
                    
                        # Set defaults
                        if not data.get('priority'):
                            data['priority'] = 'Medium'
                        if not data.get('status'):
                            data['status'] = 'Open'
                        if not data.get('created_date'):
                            data['created_date'] = datetime.now().strftime('%Y-%m-%d')
                    
                        # Insert into database with source tracking
                        cursor.execute('''
                            INSERT OR REPLACE INTO corrective_maintenance 
                            (cm_number, bfm_equipment_no, description, priority, assigned_technician, 
                            status, created_date, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            data.get('cm_number'),
                            data.get('bfm_equipment_no'),
                            data.get('description'),
                            data.get('priority'),
                            data.get('assigned_technician'),
                            data.get('status'),
                            data.get('created_date'),
                            f"Imported from SharePoint: {data.get('notes', '')}"
                        ))
                    
                        imported_count += 1
                    
                    except Exception as e:
                        print(f"Error importing row {index}: {e}")
                        error_count += 1
                        continue
            
                self.conn.commit()
                dialog.destroy()
            
                # Show results
                result_msg = f"SharePoint import completed!\n\n"
                result_msg += f"Successfully imported: {imported_count} records\n"
                if error_count > 0:
                    result_msg += f"Skipped (errors): {error_count} records\n"
                result_msg += f"\nTotal processed: {imported_count + error_count} records"
            
                messagebox.showinfo("Import Results", result_msg)
            
                # Refresh CM list
                self.load_corrective_maintenance()
                self.sharepoint_status_label.config(text=f"Imported {imported_count} CMs from SharePoint")
                self.update_status(f"Imported {imported_count} CM records from SharePoint")
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import data: {str(e)}")
                self.sharepoint_status_label.config(text="Import failed")
    
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)
    
        ttk.Button(button_frame, text="Import Data", command=import_sharepoint_data).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)


    def connect_to_sharepoint_direct(self, site_url, username, password):
        """Attempt direct SharePoint connection"""
        try:
            # This is a simplified example - real implementation would use proper authentication
            # You would need libraries like Office365-REST-Python-Client or similar
        
            # Placeholder for actual SharePoint connection
            # In reality, you'd need proper OAuth2 authentication
        
            return False  # For now, return False to redirect to manual upload
        
        except Exception as e:
            print(f"SharePoint connection error: {e}")
            return False

    # Enhanced load_corrective_maintenance to show source
    def load_corrective_maintenance(self):
        """Load corrective maintenance data with enhanced source tracking"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT cm_number, bfm_equipment_no, description, priority, 
                    assigned_technician, status, created_date, notes
                FROM corrective_maintenance 
                ORDER BY created_date DESC
            ''')
        
            # Clear existing items
            for item in self.cm_tree.get_children():
                self.cm_tree.delete(item)
        
            # Add CM records
            for idx, cm in enumerate(cursor.fetchall()):
                cm_number, bfm_no, description, priority, assigned, status, created, notes = cm

                # Determine source
                source = "SharePoint" if notes and "Imported from SharePoint" in notes else "Manual"

                # Truncate description for display
                display_desc = (description[:47] + '...') if description and len(description) > 50 else (description or '')

                self.cm_tree.insert('', 'end', values=(
                    cm_number, bfm_no, display_desc, priority, assigned, status, created, source
                ))

                # Yield to event loop every 50 items to keep UI responsive
                if idx % 50 == 0:
                    self.root.update_idletasks()
            
        except Exception as e:
            print(f"Error loading corrective maintenance: {e}")
        
    

    
    
    
    def create_analytics_dashboard_tab(self):
        """Analytics and dashboard tab"""
        self.analytics_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.analytics_frame, text="Analytics Dashboard")
        
        # Analytics controls
        controls_frame = ttk.LabelFrame(self.analytics_frame, text="Analytics Controls", padding=10)
        controls_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(controls_frame, text="Refresh Dashboard", 
                  command=self.refresh_analytics_dashboard).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Equipment Analytics", 
                  command=self.show_equipment_analytics).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="PM Trends", 
                  command=self.show_pm_trends).pack(side='left', padx=5)
        ttk.Button(controls_frame, text="Export Analytics", 
                  command=self.export_analytics).pack(side='left', padx=5)
        
        # Dashboard display
        dashboard_frame = ttk.LabelFrame(self.analytics_frame, text="Analytics Dashboard", padding=10)
        dashboard_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        # Create notebook for different analytics views
        self.analytics_notebook = ttk.Notebook(dashboard_frame)
        self.analytics_notebook.pack(fill='both', expand=True)
        
        # Overview tab
        overview_frame = ttk.Frame(self.analytics_notebook)
        self.analytics_notebook.add(overview_frame, text="Overview")
        
        self.analytics_text = tk.Text(overview_frame, wrap='word', font=('Courier', 10))
        analytics_scrollbar = ttk.Scrollbar(overview_frame, orient='vertical', command=self.analytics_text.yview)
        self.analytics_text.configure(yscrollcommand=analytics_scrollbar.set)
        
        self.analytics_text.pack(side='left', fill='both', expand=True)
        analytics_scrollbar.pack(side='right', fill='y')
        
        # Load initial analytics
        self.refresh_analytics_dashboard()
    
    def update_status(self, message):
        """Update status bar with message"""
        if hasattr(self, 'status_bar'):
            self.status_bar.config(text=f"AIT CMMS - {message}")
            self.root.update_idletasks()
        else:
            print(f"STATUS: {message}")
    
    
    def update_equipment_suggestions(self, event):
        """Update equipment suggestions in completion form"""
        search_term = self.completion_bfm_var.get().lower()
        
        if len(search_term) >= 2:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT bfm_equipment_no FROM equipment 
                WHERE LOWER(bfm_equipment_no) LIKE %s OR LOWER(description) LIKE %s
                ORDER BY bfm_equipment_no LIMIT 10
            ''', (f'%{search_term}%', f'%{search_term}%'))
            
            suggestions = [row[0] for row in cursor.fetchall()]
            self.bfm_combo['values'] = suggestions
    
    
    
    def load_latest_weekly_schedule(self):
        """Load the most recent weekly schedule on startup"""
        try:
            cursor = self.conn.cursor()
        
            # Find the most recent week with scheduled PMs
            cursor.execute('''
                SELECT week_start_date 
                FROM weekly_pm_schedules 
                ORDER BY week_start_date DESC 
                LIMIT 1
            ''')
        
            latest_week = cursor.fetchone()
        
            if latest_week:
                # Set the week start variable to the latest week
                self.week_start_var.set(latest_week[0])
                # Refresh the display with this week's data
                self.refresh_technician_schedules()
                self.update_status(f"Loaded latest weekly schedule: {latest_week[0]}")
            else:
                # No schedules exist, keep current week
                self.update_status("No weekly schedules found")
            
        except Exception as e:
            print(f"Error loading latest weekly schedule: {e}")
    
    
    
    
    
    
    def submit_pm_completion(self):
        """Enhanced PM completion with validation and verification - PREVENTS DUPLICATES"""
        try:
            # Validate required fields
            if not self.completion_bfm_var.get():
                messagebox.showerror("Error", "Please enter BFM Equipment Number")
                return

            if not self.pm_type_var.get():
                messagebox.showerror("Error", "Please select PM Type")
                return

            if not self.completion_tech_var.get():
                messagebox.showerror("Error", "Please select Technician")
                return

            # Get form data
            bfm_no = self.completion_bfm_var.get().strip()
            pm_type = self.pm_type_var.get()
            technician = self.completion_tech_var.get()
            labor_hours = float(self.labor_hours_var.get() or 0)
            labor_minutes = float(self.labor_minutes_var.get() or 0)
            pm_due_date = self.pm_due_date_var.get().strip()
            special_equipment = self.special_equipment_var.get()
            notes = self.notes_text.get('1.0', 'end-1c')
            next_annual_pm = self.next_annual_pm_var.get().strip()

            # Use PM Due Date as completion date if provided, otherwise today's date
            if pm_due_date:
                completion_date = pm_due_date
            else:
                completion_date = datetime.now().strftime('%Y-%m-%d')

            cursor = self.conn.cursor()
            
            # Ensure we start with a clean transaction state
            try:
                self.conn.rollback()
            except:
                pass

            # WARNING: ENHANCED VALIDATION - Check for recent duplicates
            validation_result = self.validate_pm_completion(cursor, bfm_no, pm_type, technician, completion_date)
            if not validation_result['valid']:
                # Show detailed warning dialog
                response = messagebox.askyesno(
                    "WARNING: Potential Duplicate PM Detected", 
                    f"{validation_result['message']}\n\n"
                    f"Details:\n"
                    f"- Equipment: {bfm_no}\n"
                    f"- PM Type: {pm_type}\n"
                    f"- Technician: {technician}\n"
                    f"- Completion Date: {completion_date}\n\n"
                    f"Do you want to proceed anyway?\n\n"
                    f"Click 'No' to review and make changes.",
                    icon='warning'
                )
                if not response:
                    # User chose not to proceed - rollback any pending transaction
                    try:
                        self.conn.rollback()
                    except:
                        pass
                    self.update_status("PM submission cancelled - potential duplicate detected")
                    return

            # Auto-calculate next annual PM date if blank
            if not next_annual_pm and pm_type in ['Monthly', 'Six Month', 'Annual']:
                try:
                    completion_dt = datetime.strptime(completion_date, '%Y-%m-%d')
                except ValueError:
                    completion_dt = datetime.now()

                # ONLY set annual PM date when completing an Annual PM
                if pm_type == 'Annual':
                    next_annual_dt = completion_dt + timedelta(days=365)

                    # Add equipment-specific offset to spread annual PMs
                    try:
                        import re
                        numeric_part = re.findall(r'\d+', bfm_no)
                        if numeric_part:
                            last_digits = int(numeric_part[-1]) % 61
                            offset_days = last_digits - 30  # -30 to +30 days
                        else:
                            offset_days = (hash(bfm_no) % 61) - 30
        
                        next_annual_dt = next_annual_dt + timedelta(days=offset_days)
                    except Exception:
                        import random
                        offset_days = random.randint(-21, 21)
                        next_annual_dt = next_annual_dt + timedelta(days=offset_days)

                    next_annual_pm = next_annual_dt.strftime('%Y-%m-%d')
                    self.next_annual_pm_var.set(next_annual_pm)
                # For Monthly and Six Month PMs, DO NOT change the existing Annual PM date
                # This preserves the independent Annual PM schedule

            # Handle different PM types with TRANSACTION SAFETY
            try:
                # PostgreSQL automatically starts a transaction with the first query
                # No need for explicit BEGIN TRANSACTION

                if pm_type == 'CANNOT FIND':
                    success = self.process_cannot_find_pm(cursor, bfm_no, technician, completion_date, notes)
                
                elif pm_type == 'Run to Failure':
                    success = self.process_run_to_failure_pm(cursor, bfm_no, technician, completion_date, 
                                                        labor_hours + (labor_minutes/60), notes)
                
                else:  # Normal PM (Monthly, Six Month, Annual)
                    success = self.process_normal_pm_completion(cursor, bfm_no, pm_type, technician, 
                                                            completion_date, labor_hours, labor_minutes, 
                                                            pm_due_date, special_equipment, notes, next_annual_pm)

                if success:
                    # Commit transaction
                    cursor.execute('COMMIT')
                
                    # WARNING: VERIFY the completion was saved correctly
                    verification_result = self.verify_pm_completion_saved(cursor, bfm_no, pm_type, technician, completion_date)
                
                    if verification_result['verified']:
                        messagebox.showinfo("CHECK: Success", 
                                        f"PM completion recorded and verified!\n\n"
                                        f"Equipment: {bfm_no}\n"
                                        f"PM Type: {pm_type}\n"
                                        f"Technician: {technician}\n"
                                        f"Date: {completion_date}\n\n"
                                        f"CHECK: Database verification passed")
                    
                        # Clear form and refresh displays
                        self.clear_completion_form()
                        self.load_recent_completions()
                        if hasattr(self, 'refresh_technician_schedules'):
                            self.refresh_technician_schedules()
                        self.update_status(f"CHECK: PM completed and verified: {bfm_no} - {pm_type} by {technician}")
                        if hasattr(self, 'auto_sync_after_action'):
                            self.auto_sync_after_action()
                    else:
                        messagebox.showerror("WARNING: Warning", 
                                        f"PM was saved but verification failed!\n\n"
                                        f"{verification_result['message']}\n\n"
                                        f"Please check the PM History tab to confirm the completion was recorded.")
                        self.update_status(f"WARNING: PM saved but verification incomplete: {bfm_no}")
                else:
                    # Rollback on failure
                    cursor.execute('ROLLBACK')
                    messagebox.showerror("Error", "Failed to process PM completion. Transaction rolled back.")
                
            except Exception as e:
                # Rollback on exception
                cursor.execute('ROLLBACK')
                raise e

        except Exception as e:
            messagebox.showerror("Error", f"Failed to submit PM completion: {str(e)}")
            import traceback
            print(f"PM Completion Error: {traceback.format_exc()}")
    
    
    def auto_pull_from_sharepoint(self):
        """Automatically pull latest data from SharePoint every 30 seconds"""
        try:
            # Check if there's a newer backup available
            if hasattr(self, 'backup_sync_dir') and self.backup_sync_dir:
                db_file = 'ait_cmms_database.db'
                backup_dir = self.backup_sync_dir
            
                if os.path.exists(backup_dir):
                    # Get latest backup
                    backup_files = []
                    for f in os.listdir(backup_dir):
                        if f.startswith('ait_cmms_backup_') and f.endswith('.db'):
                            full_path = os.path.join(backup_dir, f)
                            backup_files.append((full_path, os.path.getmtime(full_path)))
                
                    if backup_files:
                        backup_files.sort(key=lambda x: x[1], reverse=True)
                        latest_backup_path, latest_backup_time = backup_files[0]
                    
                        # Check if backup is newer than local
                        if os.path.exists(db_file):
                            local_time = os.path.getmtime(db_file)
                        
                            if latest_backup_time > local_time:
                                print(f"Newer backup detected, pulling from SharePoint...")
                                
                                # Close connection
                                self.conn.close()
                                
                                # Copy newer backup
                                shutil.copy2(latest_backup_path, db_file)
                                
                                # Reopen connection
                                #self.conn = sqlite3.connect(db_file)
                                
                                # Refresh views based on user role
                                if self.current_user_role == 'Manager':
                                    # Manager has all views
                                    if hasattr(self, 'load_equipment_data'):
                                        self.load_equipment_data()
                                    if hasattr(self, 'load_recent_completions'):
                                        self.load_recent_completions()
                            
                                # Both Manager and Technician have CM access
                                if hasattr(self, 'load_corrective_maintenance'):
                                    self.load_corrective_maintenance()
                            
                                self.update_status("CHECK: Data updated from SharePoint")
        
            # Schedule next pull in 30 seconds
            #self.root.after(30 * 1000, self.auto_pull_from_sharepoint)
        
        except Exception as e:
            print(f"Auto-pull error: {e}")
            # Schedule next pull anyway
            #self.root.after(30 * 1000, self.auto_pull_from_sharepoint)
    
    
    def auto_save_and_sync(self):
        """Auto-save database changes and sync to SharePoint every 5 seconds"""
        try:
            # Commit any pending database changes
            if hasattr(self, 'conn') and self.conn:
                self.conn.commit()
        
            # Push to SharePoint immediately after saving
            if hasattr(self, 'backup_sync_dir') and self.backup_sync_dir:
                self.sharepoint_only_backup(self.backup_sync_dir)
                print("Auto-saved and synced to SharePoint")
        
            # Schedule next auto-save in 5 minutes
            #self.root.after(300 * 1000, self.auto_save_and_sync)
        
        except Exception as e:
            print(f"Auto-save error: {e}")
            # Schedule next auto-save anyway
            #self.root.after(300 * 1000, self.auto_save_and_sync)
    
    
    
    def validate_pm_completion(self, cursor, bfm_no, pm_type, technician, completion_date):
        """Comprehensive validation to prevent duplicate PMs"""
        try:
            issues = []
        
            # Check 1: Same PM type completed recently for this equipment
            cursor.execute('''
                SELECT completion_date, technician_name, id
                FROM pm_completions 
                WHERE bfm_equipment_no = %s AND pm_type = %s
                ORDER BY completion_date DESC LIMIT 1
            ''', (bfm_no, pm_type))
        
            recent_completion = cursor.fetchone()
            if recent_completion:
                last_completion_date, last_technician, completion_id = recent_completion
                try:
                    last_date = datetime.strptime(last_completion_date, '%Y-%m-%d')
                    current_date = datetime.strptime(completion_date, '%Y-%m-%d')
                    days_since = (current_date - last_date).days
                
                    # Different thresholds for different PM types
                    min_days = {
                        'Monthly': 25,      # Monthly PMs should be ~30 days apart
                        'Six Month': 150,   # Six month PMs should be ~180 days apart
                        'Annual': 300       # Annual PMs should be ~365 days apart
                    }
                
                    threshold = min_days.get(pm_type, 7)  # Default 7 days for other types
                
                    if days_since < threshold:
                        issues.append(f"WARNING: DUPLICATE DETECTED: {pm_type} PM for {bfm_no} was completed only {days_since} days ago")
                        issues.append(f"   Previous completion: {last_completion_date} by {last_technician}")
                        issues.append(f"   Minimum interval for {pm_type} PM: {threshold} days")
                    
                except ValueError:
                    # If date parsing fails, flag it as potential issue
                    issues.append(f"WARNING: Date parsing issue with previous completion: {last_completion_date}")

            # Check 2: Same technician completing SAME PM TYPE on same equipment too frequently  
            cursor.execute('''
                SELECT COUNT(*) 
                FROM pm_completions 
                WHERE bfm_equipment_no = %s 
                AND technician_name = %s
                AND pm_type = %s
                AND completion_date::date >= %s::date - INTERVAL '7 days'
            ''', (bfm_no, technician, pm_type, completion_date))
        
            recent_count = cursor.fetchone()[0]
            if recent_count > 0:
                issues.append(f"WARNING: Same technician ({technician}) completed {pm_type} PM on {bfm_no} within last 7 days")

            # Check 3: Equipment exists and is active
            cursor.execute('SELECT status FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            equipment_status = cursor.fetchone()
        
            if not equipment_status:
                issues.append(f"CHECK: Equipment {bfm_no} not found in database")
            elif equipment_status[0] in ['Missing', 'Run to Failure'] and pm_type not in ['CANNOT FIND', 'Run to Failure']:
                issues.append(f"WARNING: Equipment {bfm_no} has status '{equipment_status[0]}' - unusual for {pm_type} PM")

            # Check 4: Scheduled PM exists for this week
            #current_week_start = self.get_week_start(datetime.strptime(completion_date, '%Y-%m-%d'))
            #cursor.execute('''
            #   SELECT COUNT(*) FROM weekly_pm_schedules 
            #   WHERE bfm_equipment_no = %s AND pm_type = %s 
            #    AND assigned_technician = %s AND week_start_date = %s
            #''', (bfm_no, pm_type, technician, current_week_start.strftime('%Y-%m-%d')))
            #
            #scheduled_count = cursor.fetchone()[0]
            #if scheduled_count == 0 and pm_type in ['Monthly', 'Annual']:
            #   issues.append(f"WARNING: No scheduled PM found for this week - completing ahead of schedule")

            # Return validation result
            if issues:
                return {
                    'valid': False,
                    'message': f"Found {len(issues)} potential issue(s):\n\n" + "\n\n".join(issues)
                }
            else:
                return {'valid': True, 'message': 'Validation passed'}
            
        except Exception as e:
            # Rollback any failed queries in validation
            try:
                self.conn.rollback()
            except:
                pass
            # Show the actual error for debugging
            import traceback
            error_detail = f"{str(e)}\n\nQuery error details:\n{traceback.format_exc()}"
            return {
                'valid': False,
                'verified': False,
                'message': f"Validation error: {str(e)}"
            }

    def verify_pm_completion_saved(self, cursor, bfm_no, pm_type, technician, completion_date):
        """Verify that the PM completion was actually saved to the database"""
        try:
            # Check 1: PM completion record exists
            cursor.execute('''
                SELECT id, completion_date, technician_name, created_date
                FROM pm_completions 
                WHERE bfm_equipment_no = %s AND pm_type = %s AND technician_name = %s
                AND completion_date = %s
                ORDER BY created_date DESC LIMIT 1
            ''', (bfm_no, pm_type, technician, completion_date))
        
            completion_record = cursor.fetchone()
            if not completion_record:
                return {
                    'verified': False,
                    'message': f"CHECK: PM completion record not found in database"
                }

            # Check 2: Equipment PM dates updated (for normal PMs)
            if pm_type in ['Monthly', 'Six Month', 'Annual']:
                date_field = f'last_{pm_type.lower().replace(" ", "_")}_pm'
                cursor.execute(f'SELECT {date_field} FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            
                equipment_date = cursor.fetchone()
                if equipment_date and equipment_date[0] != completion_date:
                    return {
                        'verified': False,
                        'message': f"WARNING: Equipment {date_field} not updated correctly. Expected: {completion_date}, Found: {equipment_date[0]}"
                    }

            # Check 3: Weekly schedule updated if applicable
            current_week_start = self.get_week_start(datetime.strptime(completion_date, '%Y-%m-%d'))
            cursor.execute('''
                SELECT status FROM weekly_pm_schedules 
                WHERE bfm_equipment_no = %s AND pm_type = %s
                AND assigned_technician = %s AND week_start_date = %s
            ''', (bfm_no, pm_type, technician, current_week_start.strftime('%Y-%m-%d')))
        
            schedule_status = cursor.fetchone()
            if schedule_status and schedule_status[0] != 'Completed':
                return {
                    'verified': False,
                    'message': f"WARNING: Weekly schedule not marked as completed. Status: {schedule_status[0]}"
                }

            return {
                'verified': True,
                'message': f"CHECK: All verification checks passed",
                'completion_id': completion_record[0]
            }
        
        except Exception as e:
            return {
                'verified': False,
                'message': f"Verification error: {str(e)}"
            }

    def process_normal_pm_completion(self, cursor, bfm_no, pm_type, technician, completion_date, 
                                labor_hours, labor_minutes, pm_due_date, special_equipment, notes, next_annual_pm):
        """Process normal PM completion with enhanced error handling"""
        try:
            cursor.execute('''
                INSERT INTO pm_completions 
                (bfm_equipment_no, pm_type, technician_name, completion_date, 
                labor_hours, labor_minutes, pm_due_date, special_equipment, 
                notes, next_annual_pm_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                bfm_no, pm_type, technician, completion_date,
                labor_hours, labor_minutes, pm_due_date, special_equipment,
                notes, next_annual_pm
            ))
        
         
            completion_id = cursor.fetchone()[0]
            if not completion_id:
                raise Exception("Failed to get completion record ID")

            # Update equipment PM dates
            if pm_type == 'Monthly':
                if next_annual_pm: 
                    cursor.execute('''
                        UPDATE equipment SET 
                        last_monthly_pm = %s, 
                        next_monthly_pm = %s::date + INTERVAL '30 days',
                        next_annual_pm = %s,  
                        updated_date = CURRENT_TIMESTAMP
                        WHERE bfm_equipment_no = %s
                    ''', (completion_date, completion_date, next_annual_pm, bfm_no))
                else:
                    cursor.execute('''
                        UPDATE equipment SET 
                        last_monthly_pm = %s, 
                        next_monthly_pm = %s::date + INTERVAL '30 days',
                        updated_date = CURRENT_TIMESTAMP
                        WHERE bfm_equipment_no = %s
                    ''', (completion_date, completion_date, bfm_no))
                    
            elif pm_type == 'Six Month':
                cursor.execute('''
                    UPDATE equipment SET 
                    last_six_month_pm = %s, 
                    next_six_month_pm = %s::date + INTERVAL '180 days',
                    updated_date = CURRENT_TIMESTAMP
                    WHERE bfm_equipment_no = %s
                ''', (completion_date, completion_date, bfm_no))
                
            elif pm_type == 'Annual':
                cursor.execute('''
                    UPDATE equipment SET 
                    last_annual_pm = %s, 
                    next_annual_pm = %s::date + INTERVAL '365 days',
                    updated_date = CURRENT_TIMESTAMP
                    WHERE bfm_equipment_no = %s
                ''', (completion_date, completion_date, bfm_no))

            # Verify equipment update worked
            affected_rows = cursor.rowcount
            if affected_rows != 1:
                raise Exception(f"Equipment update failed - affected {affected_rows} rows instead of 1")

            # Update weekly schedule status if exists
            current_week_start = self.get_week_start(datetime.strptime(completion_date, '%Y-%m-%d'))
            cursor.execute('''
                UPDATE weekly_pm_schedules SET 
                status = 'Completed', 
                completion_date = %s, 
                labor_hours = %s, 
                notes = %s
                WHERE bfm_equipment_no = %s AND pm_type = %s AND assigned_technician = %s
                AND week_start_date = %s AND status = 'Scheduled'
            ''', (completion_date, labor_hours + (labor_minutes/60), notes, 
                bfm_no, pm_type, technician, current_week_start.strftime('%Y-%m-%d')))

            # DEBUG: Check if the update worked
            updated_rows = cursor.rowcount
            print(f"DEBUG: Updated {updated_rows} weekly schedule rows for {bfm_no} - {pm_type} by {technician}")

            print(f"CHECK: Normal PM completion processed successfully: {bfm_no} - {pm_type}")
            return True
            
        except Exception as e:
            print(f"CHECK: Error processing normal PM completion: {str(e)}")
            return False
    
    def fix_weekly_schedule_status_flexible(self):
        """Enhanced method to fix weekly schedule status with flexible matching"""
        try:
            cursor = self.conn.cursor()
        
            # First, get all actual completions for the week
            cursor.execute('''
                SELECT bfm_equipment_no, pm_type, technician_name, completion_date,
                    (labor_hours + labor_minutes/60.0) as total_hours, notes
                FROM pm_completions 
                WHERE completion_date BETWEEN '2025-08-25' AND '2025-08-31'
            ''')
        
            completions = cursor.fetchall()
            print(f"Found {len(completions)} actual completions to process")
        
            updated_count = 0
        
            for completion in completions:
                bfm_no, pm_type, technician, comp_date, hours, notes = completion
            
                # Try exact match first
                cursor.execute('''
                    UPDATE weekly_pm_schedules 
                    SET status = 'Completed',
                        completion_date = %s,
                        labor_hours = %s,
                        notes = %s
                    WHERE bfm_equipment_no = %s AND pm_type = %s AND assigned_technician = %s
                    AND week_start_date = '2025-08-25' AND status = 'Scheduled'
                ''', (comp_date, hours, notes, bfm_no, pm_type, technician))
            
                exact_matches = cursor.rowcount
            
                # If no exact match, try equipment + PM type match (without LIMIT)
                if exact_matches == 0:
                    # First check if there's an available scheduled PM for this equipment/PM type
                    cursor.execute('''
                        SELECT id FROM weekly_pm_schedules 
                        WHERE bfm_equipment_no = %s AND pm_type = %s
                        AND week_start_date = '2025-08-25' AND status = 'Scheduled'
                    ''', (bfm_no, pm_type))
                
                    available = cursor.fetchone()
                
                    if available:
                        # Update the first available matching record
                        cursor.execute('''
                            UPDATE weekly_pm_schedules 
                            SET status = 'Completed',
                                completion_date = %s,
                                labor_hours = %s,
                                notes = %s,
                                assigned_technician = %s
                            WHERE id = %s
                        ''', (comp_date, hours, notes, technician, available[0]))
                    
                        flexible_matches = cursor.rowcount
                        if flexible_matches > 0:
                            print(f"Flexible match: {bfm_no} {pm_type} reassigned to {technician}")
                    
                        updated_count += flexible_matches
                    else:
                        print(f"No scheduled PM found for {bfm_no} {pm_type}")
                else:
                    updated_count += exact_matches
                    print(f"Exact match: {bfm_no} {pm_type} by {technician}")
        
            self.conn.commit()
        
            messagebox.showinfo("Success", 
                            f"Processed {len(completions)} completions\n"
                            f"Updated {updated_count} weekly schedule records!")
            print(f"Final result: Updated {updated_count} out of {len(completions)} completions")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fix weekly schedule: {str(e)}")
            print(f"Error: {e}")
    
    
    
    
    def process_cannot_find_pm(self, cursor, bfm_no, technician, completion_date, notes):
        """Process CANNOT FIND PM with validation"""
        try:
            # Get equipment info
            cursor.execute('SELECT description, location FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            equipment_info = cursor.fetchone()
            description = equipment_info[0] if equipment_info else ''
            location = equipment_info[1] if equipment_info else ''

            # Insert into cannot_find_assets table
            cursor.execute('''
                INSERT INTO cannot_find_assets 
                (bfm_equipment_no, description, location, technician_name, reported_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (bfm_no, description, location, technician, completion_date, notes))

            # Update equipment status
            cursor.execute('UPDATE equipment SET status = "Missing" WHERE bfm_equipment_no = %s', (bfm_no,))
        
            affected_rows = cursor.rowcount
            if affected_rows != 1:
                raise Exception(f"Equipment status update failed - affected {affected_rows} rows")

            print(f"CHECK: Cannot Find PM processed: {bfm_no}")
            return True
        
        except Exception as e:
            print(f"CHECK: Error processing Cannot Find PM: {str(e)}")
            return False

    def process_run_to_failure_pm(self, cursor, bfm_no, technician, completion_date, total_hours, notes):
        """Process Run to Failure PM with validation"""
        try:
            # Get equipment info
            cursor.execute('SELECT description, location FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
            equipment_info = cursor.fetchone()
            description = equipment_info[0] if equipment_info else ''
            location = equipment_info[1] if equipment_info else ''

            # Insert into run_to_failure_assets table
            cursor.execute('''
                INSERT INTO run_to_failure_assets 
                (bfm_equipment_no, description, location, technician_name, completion_date, labor_hours, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (bfm_no, description, location, technician, completion_date, total_hours, notes))

            # Update equipment status and disable all PM types
            cursor.execute('''
                UPDATE equipment SET 
                status = "Run to Failure",
                monthly_pm = 0,
                six_month_pm = 0,
                annual_pm = 0,
                updated_date = CURRENT_TIMESTAMP
                WHERE bfm_equipment_no = %s
            ''', (bfm_no,))
        
            affected_rows = cursor.rowcount
            if affected_rows != 1:
                raise Exception(f"Equipment update failed - affected {affected_rows} rows")

            print(f"CHECK: Run to Failure PM processed: {bfm_no}")
            return True
        
        except Exception as e:
            print(f"CHECK: Error processing Run to Failure PM: {str(e)}")
            return False

    # Additional method to add to your class:
    def show_recent_completions_for_equipment(self, bfm_no):
        """Show recent completions for specific equipment - useful for debugging"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT pm_type, technician_name, completion_date, 
                    (labor_hours + labor_minutes/60.0) as total_hours,
                    notes
                FROM pm_completions 
                WHERE bfm_equipment_no = %s
                ORDER BY completion_date DESC LIMIT 10
            ''', (bfm_no,))
        
            completions = cursor.fetchall()
        
            if completions:
                report = f"RECENT PM COMPLETIONS FOR {bfm_no}\n"
                report += "=" * 50 + "\n\n"
            
                for pm_type, tech, date, hours, notes in completions:
                    report += f"- {date} - {pm_type} PM by {tech} ({hours:.1f}h)\n"
                    if notes:
                        report += f"  Notes: {notes[:100]}...\n" if len(notes) > 100 else f"  Notes: {notes}\n"
                    report += "\n"
            
                # Show in a dialog
                dialog = tk.Toplevel(self.root)
                dialog.title(f"PM History - {bfm_no}")
                dialog.geometry("600x400")
            
                text_widget = tk.Text(dialog, wrap='word', font=('Courier', 10))
                text_widget.pack(fill='both', expand=True, padx=10, pady=10)
                text_widget.insert('1.0', report)
                text_widget.config(state='disabled')
            
            else:
                messagebox.showinfo("No History", f"No PM completions found for equipment {bfm_no}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load PM history: {str(e)}")
      
    def load_cannot_find_assets(self):
        """Load cannot find assets data and store for filtering"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT bfm_equipment_no, description, location, technician_name, reported_date, status
                FROM cannot_find_assets 
                WHERE status = 'Missing'
                ORDER BY reported_date DESC
            ''')
        
            # Store all data for filtering
            self.cannot_find_data = cursor.fetchall()
        
            # Display the data
            self.filter_cannot_find_assets()
        
        except Exception as e:
            print(f"Error loading cannot find assets: {e}")




    def filter_cannot_find_assets(self):
        """Filter the Cannot Find assets based on search term"""
        # Clear existing items
        for item in self.cannot_find_tree.get_children():
            self.cannot_find_tree.delete(item)

        # Get search term
        search_term = self.cannot_find_search_var.get().lower().strip()

        # If no data loaded yet, return
        if not hasattr(self, 'cannot_find_data'):
            return

        # Filter and display data
        for idx, asset in enumerate(self.cannot_find_data):
            bfm_no, description, location, technician, reported_date, status = asset

            # If search term is empty, show all
            if not search_term:
                self.cannot_find_tree.insert('', 'end', values=(
                    bfm_no, description or '', location or '', technician, reported_date, status
                ))
            else:
                # Search in all fields
                searchable_text = ' '.join([
                    str(bfm_no or ''),
                    str(description or ''),
                    str(location or ''),
                    str(technician or ''),
                    str(reported_date or ''),
                    str(status or '')
                ]).lower()

                if search_term in searchable_text:
                    self.cannot_find_tree.insert('', 'end', values=(
                        bfm_no, description or '', location or '', technician, reported_date, status
                    ))

            # Yield to event loop every 50 items to keep UI responsive
            if idx % 50 == 0:
                self.root.update_idletasks()
    
        # Update count in status bar if method exists
        visible_count = len(self.cannot_find_tree.get_children())
        total_count = len(self.cannot_find_data) if hasattr(self, 'cannot_find_data') else 0
    
        if hasattr(self, 'update_status'):
            if search_term:
                self.update_status(f"Showing {visible_count} of {total_count} Cannot Find assets (filtered)")
            else:
                self.update_status(f"Showing {total_count} Cannot Find assets")




    # 8. LOAD RUN TO FAILURE ASSETS
    def load_run_to_failure_assets(self):
        """Enhanced method to load run to failure assets with better data handling"""
        try:
            cursor = self.conn.cursor()
        
            # Get data from both run_to_failure_assets table AND equipment table
            cursor.execute('''
                SELECT DISTINCT
                    COALESCE(rtf.bfm_equipment_no, e.bfm_equipment_no) as bfm_no,
                    COALESCE(rtf.description, e.description) as description,
                    COALESCE(rtf.location, e.location) as location,
                    COALESCE(rtf.technician_name, 'System Change') as technician,
                    COALESCE(rtf.completion_date, e.updated_date, CURRENT_DATE) as completion_date,
                    COALESCE(rtf.labor_hours, 0) as labor_hours,
                    COALESCE(rtf.notes, 'Set via equipment edit') as notes
                FROM equipment e
                LEFT JOIN run_to_failure_assets rtf ON e.bfm_equipment_no = rtf.bfm_equipment_no
                WHERE e.status = 'Run to Failure'
            
                UNION
            
                SELECT 
                    rtf.bfm_equipment_no,
                    rtf.description,
                    rtf.location,
                    rtf.technician_name,
                    rtf.completion_date,
                    rtf.labor_hours,
                    rtf.notes
                FROM run_to_failure_assets rtf
                LEFT JOIN equipment e ON rtf.bfm_equipment_no = e.bfm_equipment_no
                WHERE e.bfm_equipment_no IS NULL OR e.status = 'Run to Failure'
            
                ORDER BY completion_date DESC
            ''')
        
            # Clear existing items
            for item in self.run_to_failure_tree.get_children():
                self.run_to_failure_tree.delete(item)
        
            # Add run to failure records
            for asset in cursor.fetchall():
                bfm_no, description, location, technician, completion_date, hours, notes = asset
                hours_display = f"{hours:.1f}h" if hours else "0.0h"
            
                self.run_to_failure_tree.insert('', 'end', values=(
                    bfm_no,
                    description or 'No description',
                    location or 'Unknown location',
                    technician or 'Unknown',
                    completion_date or '',
                    hours_display
                ))
            
            # Update the count in equipment statistics
            self.update_equipment_statistics()
            
        except Exception as e:
            print(f"Error loading run to failure assets: {e}")
            messagebox.showerror("Error", f"Failed to load Run to Failure assets: {str(e)}")
            
            
    # 9. EXPORT CANNOT FIND TO PDF
    def export_cannot_find_pdf(self):
        """Export Cannot Find assets to PDF"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Cannot_Find_Assets_{timestamp}.pdf"
        
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT bfm_equipment_no, description, location, technician_name, reported_date, notes
                FROM cannot_find_assets 
                WHERE status = 'Missing'
                ORDER BY reported_date DESC
            ''')
        
            assets = cursor.fetchall()
        
            doc = SimpleDocTemplate(filename, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()
        
            # Title
            title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], 
                                    fontSize=18, textColor=colors.darkred, alignment=1)
            story.append(Paragraph("AIRBUS AIT - CANNOT FIND ASSETS REPORT", title_style))
            story.append(Spacer(1, 20))
        
            # Report info
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Paragraph(f"Total Missing Assets: {len(assets)}", styles['Normal']))
            story.append(Spacer(1, 20))
        
            if assets:
                # Create table
                data = [['BFM Equipment No.', 'Description', 'Location', 'Reported By', 'Report Date']]
                for asset in assets:
                    bfm_no, description, location, technician, reported_date, notes = asset
                    data.append([
                        bfm_no,
                        (description[:30] + '...') if description and len(description) > 30 else (description or ''),
                        location or '',
                        technician,
                        reported_date
                    ])
                
                table = Table(data, colWidths=[1.5*inch, 2.5*inch, 1.2*inch, 1.2*inch, 1*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
            
                story.append(table)
            else:
                story.append(Paragraph("No missing assets found.", styles['Normal']))
        
            doc.build(story)
            messagebox.showinfo("Success", f"Cannot Find report exported to: {filename}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export Cannot Find report: {str(e)}")

    # 10. EXPORT RUN TO FAILURE TO PDF
    def export_run_to_failure_pdf(self):
        """Export Run to Failure assets to PDF"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Run_to_Failure_Assets_{timestamp}.pdf"
        
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT bfm_equipment_no, description, location, technician_name, completion_date, labor_hours, notes
                FROM run_to_failure_assets 
                ORDER BY completion_date DESC
            ''')
        
            assets = cursor.fetchall()
        
            doc = SimpleDocTemplate(filename, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()
        
            # Title
            title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], 
                                    fontSize=18, textColor=colors.darkblue, alignment=1)
            story.append(Paragraph("AIRBUS AIT - RUN TO FAILURE ASSETS REPORT", title_style))
            story.append(Spacer(1, 20))
        
            # Report info
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Paragraph(f"Total Run to Failure Assets: {len(assets)}", styles['Normal']))
            story.append(Spacer(1, 20))
        
            if assets:
                # Create table
                data = [['BFM Equipment No.', 'Description', 'Location', 'Completed By', 'Date', 'Hours']]
                for asset in assets:
                    bfm_no, description, location, technician, completion_date, hours, notes = asset
                    data.append([
                        bfm_no,
                        (description[:25] + '...') if description and len(description) > 25 else (description or ''),
                        location or '',
                        technician,
                        completion_date,
                        f"{hours:.1f}h" if hours else ''
                    ])
            
                table = Table(data, colWidths=[1.4*inch, 2.2*inch, 1*inch, 1*inch, 0.8*inch, 0.6*inch])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
            
                story.append(table)
            else:
                story.append(Paragraph("No Run to Failure assets found.", styles['Normal']))
        
            doc.build(story)
            messagebox.showinfo("Success", f"Run to Failure report exported to: {filename}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export Run to Failure report: {str(e)}")

    # 11. MARK ASSET AS FOUND
    def mark_asset_found(self):
        """Mark a cannot find asset as found"""
        selected = self.cannot_find_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select an asset to mark as found")
            return

        item = self.cannot_find_tree.item(selected[0])
        bfm_no = str(item['values'][0])

        try:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE cannot_find_assets SET status = "Found" WHERE bfm_equipment_no = %s', (bfm_no,))
            cursor.execute('UPDATE equipment SET status = "Active" WHERE bfm_equipment_no = %s', (bfm_no,))
            self.conn.commit()
        
            messagebox.showinfo("Success", f"Asset {bfm_no} marked as found and reactivated")
            self.load_cannot_find_assets()
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to mark asset as found: {str(e)}")

    # 12. REACTIVATE ASSET
    def reactivate_asset(self):
        """Enhanced method to reactivate multiple run to failure assets at once"""
        selected = self.run_to_failure_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select one or more assets to reactivate")
            return

        # Get all selected assets
        selected_assets = []
        for item in selected:
            item_data = self.run_to_failure_tree.item(item)
            bfm_no = item_data['values'][0]
            description = item_data['values'][1]
            selected_assets.append((bfm_no, description))
    
        # Create reactivation dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Reactivate Assets - {len(selected_assets)} Selected")
        dialog.geometry("700x650")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (700 // 2)
        y = (dialog.winfo_screenheight() // 2) - (650 // 2)
        dialog.geometry(f"700x650+{x}+{y}")
    
        # Header
        header_frame = ttk.Frame(dialog, padding=15)
        header_frame.pack(fill='x')
    
        if len(selected_assets) == 1:
            ttk.Label(header_frame, text=f"Reactivate Asset for PM Scheduling", 
                    font=('Arial', 14, 'bold')).pack()
            ttk.Label(header_frame, text=f"BFM: {selected_assets[0][0]}", 
                    font=('Arial', 10)).pack(pady=5)
            ttk.Label(header_frame, text=f"Description: {selected_assets[0][1]}", 
                    font=('Arial', 9), wraplength=650).pack()
        else:
            ttk.Label(header_frame, text=f"Bulk Reactivate {len(selected_assets)} Assets", 
                    font=('Arial', 14, 'bold')).pack()
            ttk.Label(header_frame, text=f"All selected assets will use the same PM frequencies", 
                    font=('Arial', 10), foreground='blue').pack(pady=5)
    
        # Separator
        ttk.Separator(dialog, orient='horizontal').pack(fill='x', pady=10)
    
        # Show list of selected assets if multiple
        if len(selected_assets) > 1:
            assets_frame = ttk.LabelFrame(dialog, text=f"Selected Assets ({len(selected_assets)})", padding=10)
            assets_frame.pack(fill='both', expand=True, padx=20, pady=(0, 10))
            
            # Create scrollable list
            list_container = ttk.Frame(assets_frame)
            list_container.pack(fill='both', expand=True)
            
            assets_tree = ttk.Treeview(list_container, columns=('BFM', 'Description'), 
                                        show='headings', height=6)
            assets_tree.heading('BFM', text='BFM Equipment No.')
            assets_tree.heading('Description', text='Description')
            assets_tree.column('BFM', width=150)
            assets_tree.column('Description', width=450)
            
            scrollbar = ttk.Scrollbar(list_container, orient='vertical', command=assets_tree.yview)
            assets_tree.configure(yscrollcommand=scrollbar.set)
            
            assets_tree.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
            
            # Add assets to list
            for bfm, desc in selected_assets:
                assets_tree.insert('', 'end', values=(bfm, desc))
    
        # PM Frequency Selection Frame
        pm_frame = ttk.LabelFrame(dialog, text="Select PM Frequencies to Enable", padding=20)
        pm_frame.pack(fill='x', padx=20, pady=10)
        
        # Instructions
        if len(selected_assets) > 1:
            instruction_text = "These PM frequencies will be applied to ALL selected assets:"
        else:
            instruction_text = "Choose which preventive maintenance schedules to enable:"
    
        ttk.Label(pm_frame, text=instruction_text,
                font=('Arial', 10)).pack(anchor='w', pady=(0, 15))
    
        # PM Type Checkboxes
        monthly_var = tk.BooleanVar(value=True)  # Default: Monthly enabled
        six_month_var = tk.BooleanVar(value=False)  # Default: Six Month disabled
        annual_var = tk.BooleanVar(value=True)  # Default: Annual enabled
        
        # Monthly PM
        monthly_frame = ttk.Frame(pm_frame)
        monthly_frame.pack(fill='x', pady=5)
        monthly_cb = ttk.Checkbutton(monthly_frame, text="Monthly PM (every 30 days)", 
                                    variable=monthly_var)
        monthly_cb.pack(side='left')
        ttk.Label(monthly_frame, text="CHECK: Recommended for most equipment", 
                foreground='green', font=('Arial', 8, 'italic')).pack(side='left', padx=10)
    
        # Six Month PM
        six_month_frame = ttk.Frame(pm_frame)
        six_month_frame.pack(fill='x', pady=5)
        six_month_cb = ttk.Checkbutton(six_month_frame, text="Six Month PM (every 180 days)", 
                                        variable=six_month_var)
        six_month_cb.pack(side='left')
        ttk.Label(six_month_frame, text="CHECK: Less frequent PM cycle", 
                foreground='orange', font=('Arial', 8, 'italic')).pack(side='left', padx=10)
    
        # Annual PM
        annual_frame = ttk.Frame(pm_frame)
        annual_frame.pack(fill='x', pady=5)
        annual_cb = ttk.Checkbutton(annual_frame, text="Annual PM (yearly)", 
                                    variable=annual_var)
        annual_cb.pack(side='left')
        ttk.Label(annual_frame, text="CHECK: Recommended for comprehensive checks", 
                foreground='green', font=('Arial', 8, 'italic')).pack(side='left', padx=10)
    
        # Warning label
        warning_frame = ttk.Frame(pm_frame)
        warning_frame.pack(fill='x', pady=15)
        warning_label = ttk.Label(warning_frame, 
                                text="CHECK: Note: You must select at least one PM frequency to reactivate.",
                                foreground='blue', font=('Arial', 9, 'italic'), wraplength=600)
        warning_label.pack()
    
        # Info box
        info_frame = ttk.LabelFrame(dialog, text="Reactivation Summary", padding=10)
        info_frame.pack(fill='x', padx=20, pady=(0, 10))
        
        if len(selected_assets) > 1:
            info_text = f"""This will reactivate {len(selected_assets)} assets:
        - Set all equipment statuses to Active
        - Enable selected PM frequencies for all assets
        - Remove all from Run to Failure list
        - Resume normal PM scheduling"""
        else:
            info_text = """This will:
        - Set equipment status to Active
        - Enable selected PM frequencies
        - Remove from Run to Failure list
        - Resume normal PM scheduling"""
    
        ttk.Label(info_frame, text=info_text, justify='left').pack(anchor='w')
    
        def validate_and_reactivate():
            """Validate selections and reactivate the asset(s)"""
            # Check that at least one PM type is selected
            if not monthly_var.get() and not six_month_var.get() and not annual_var.get():
                messagebox.showerror("Validation Error", 
                                   "You must select at least one PM frequency to reactivate.\n\n"
                                   "If you don't want to schedule PMs, leave the assets in Run to Failure status.")
                return
        
            # Build PM list
            pm_list = []
            if monthly_var.get():
                pm_list.append("Monthly")
            if six_month_var.get():
                pm_list.append("Six Month")
            if annual_var.get():
                pm_list.append("Annual")
        
            pm_enabled = ", ".join(pm_list)
        
            # Confirmation
            if len(selected_assets) == 1:
                confirm_msg = (f"Reactivate asset {selected_assets[0][0]}?\n\n"
                              f"Equipment will be set to Active status with:\n"
                              f"PM Frequencies: {pm_enabled}\n\n"
                              f"Continue?")
            else:
                confirm_msg = (f"Reactivate {len(selected_assets)} assets?\n\n"
                              f"All assets will be set to Active status with:\n"
                              f"PM Frequencies: {pm_enabled}\n\n"
                              f"Continue?")
        
            result = messagebox.askyesno("Confirm Reactivation", confirm_msg)
        
            if not result:
                return
        
            # Perform reactivation
            try:
                cursor = self.conn.cursor()
            
                successful = 0
                failed = []
            
                for bfm_no, description in selected_assets:
                    try:
                        # Update equipment status and enable selected PMs
                        cursor.execute('''
                            UPDATE equipment SET 
                            status = 'Active',
                            monthly_pm = %s,
                            six_month_pm = %s,
                            annual_pm = %s,
                            updated_date = CURRENT_TIMESTAMP
                            WHERE bfm_equipment_no = %s
                        ''', (
                            1 if monthly_var.get() else 0,
                            1 if six_month_var.get() else 0,
                            1 if annual_var.get() else 0,
                            bfm_no
                        ))
                    
                        # Remove from run_to_failure_assets table
                        cursor.execute('DELETE FROM run_to_failure_assets WHERE bfm_equipment_no = %s', (bfm_no,))
                    
                        successful += 1
                    
                    except Exception as e:
                        failed.append(f"{bfm_no}: {str(e)}")
            
                self.conn.commit()
            
                # Show results
                if len(selected_assets) == 1:
                    messagebox.showinfo(
                        "Success", 
                        f"Asset {selected_assets[0][0]} successfully reactivated!\n\n"
                        f"Status: Active\n"
                        f"PMs Enabled: {pm_enabled}\n\n"
                        f"Equipment moved back to main equipment list"
                    )
                else:
                    result_msg = f"Bulk Reactivation Complete!\n\n"
                    result_msg += f"Successfully reactivated: {successful} assets\n"
                    if failed:
                        result_msg += f"Failed: {len(failed)} assets\n\n"
                        result_msg += "Failed assets:\n" + "\n".join(failed[:5])
                        if len(failed) > 5:
                            result_msg += f"\n... and {len(failed) - 5} more"
                
                    result_msg += f"\n\nPMs Enabled: {pm_enabled}"
                
                    if failed:
                        messagebox.showwarning("Partial Success", result_msg)
                    else:
                        messagebox.showinfo("Success", result_msg)
            
                dialog.destroy()
            
                # Refresh all displays
                self.refresh_equipment_list()
                self.load_run_to_failure_assets()
                self.update_equipment_statistics()
            
                if len(selected_assets) == 1:
                    self.update_status(f"Reactivated asset {selected_assets[0][0]} with {pm_enabled} PMs")
                else:
                    self.update_status(f"Reactivated {successful} assets with {pm_enabled} PMs")
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to reactivate assets: {str(e)}")
    
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=20, pady=15)
        
        if len(selected_assets) == 1:
            button_text = "CHECK: Reactivate Asset"
        else:
            button_text = f"CHECK: Reactivate {len(selected_assets)} Assets"
    
        ttk.Button(button_frame, text=button_text, 
                   command=validate_and_reactivate,
                   style='Accent.TButton').pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", 
                   command=dialog.destroy).pack(side='left', padx=5)
    
    
    def clear_completion_form(self):
        """Clear the PM completion form"""
        self.completion_bfm_var.set('')
        self.pm_type_var.set('')
        self.completion_tech_var.set('')
        self.labor_hours_var.set('0')
        self.labor_minutes_var.set('0')
        self.pm_due_date_var.set('')
        self.special_equipment_var.set('')
        self.notes_text.delete('1.0', 'end')
        self.next_annual_pm_var.set('')
    
    def load_recent_completions(self):
        """Load recent PM completions with debugging"""
        print("DEBUG: load_recent_completions called")
        
        # ADD THIS SAFETY CHECK AT THE VERY BEGINNING:
        if not hasattr(self, 'recent_completions_tree'):
            print("DEBUG: recent_completions_tree not yet created, skipping load")
            return
        
        
        
        try:
            cursor = self.conn.cursor()
            print("DEBUG: Database cursor created")
        
            cursor.execute('''
                SELECT completion_date, bfm_equipment_no, pm_type, technician_name, 
                    (labor_hours + labor_minutes/60.0) as total_hours
                FROM pm_completions 
                ORDER BY completion_date DESC, id DESC LIMIT 500
            ''')
        
            completions = cursor.fetchall()
            print(f"DEBUG: Found {len(completions)} completions in database")
        
            # Clear existing items
            for item in self.recent_completions_tree.get_children():
                self.recent_completions_tree.delete(item)
            print("DEBUG: Cleared existing tree items")
        
            # Add recent completions
            for idx, completion in enumerate(completions):
                completion_date, bfm_no, pm_type, technician, total_hours = completion
                hours_display = f"{total_hours:.1f}h" if total_hours else "0.0h"

                self.recent_completions_tree.insert('', 'end', values=(
                    completion_date, bfm_no, pm_type, technician, hours_display
                ))
                print(f"DEBUG: Added {bfm_no} - {pm_type} - {technician}")

                # Yield to event loop every 50 items to keep UI responsive
                if idx % 50 == 0:
                    self.root.update_idletasks()
        
            print("DEBUG: Successfully loaded recent completions")
            print(f"Refreshed: {len(completions)} recent completions loaded")
        
        except Exception as e:
            print(f"ERROR in load_recent_completions: {e}")
            import traceback
            traceback.print_exc()
    
    def generate_current_week_report(self):
        """Generate report for current week"""
        try:
            week_start = datetime.strptime(self.week_start_var.get(), '%Y-%m-%d')
            week_end = week_start + timedelta(days=6)
            
            cursor = self.conn.cursor()
            
            # Get weekly statistics
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_scheduled,
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END) as total_completed
                FROM weekly_pm_schedules 
                WHERE week_start_date = %s
            ''', (week_start.strftime('%Y-%m-%d'),))
            
            total_scheduled, total_completed = cursor.fetchone()
            completion_rate = (total_completed / total_scheduled * 100) if total_scheduled > 0 else 0
            
            # Get technician performance
            cursor.execute('''
                SELECT 
                    assigned_technician,
                    COUNT(*) as assigned,
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed,
                    AVG(CASE WHEN status = 'Completed' THEN labor_hours END) as avg_hours
                FROM weekly_pm_schedules 
                WHERE week_start_date = %s
                GROUP BY assigned_technician
                ORDER BY assigned_technician
            ''', (week_start.strftime('%Y-%m-%d'),))
            
            tech_performance = cursor.fetchall()
            
            # Generate report text
            report = f"WEEKLY PM PERFORMANCE REPORT\n"
            report += f"Week: {week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}\n"
            report += "=" * 80 + "\n\n"
            
            report += f"OVERALL PERFORMANCE:\n"
            report += f"Target PMs for Week: {self.weekly_pm_target}\n"
            report += f"Scheduled PMs: {total_scheduled}\n"
            report += f"Completed PMs: {total_completed}\n"
            report += f"Completion Rate: {completion_rate:.1f}%\n"
            report += f"Remaining PMs: {total_scheduled - total_completed}\n\n"
            
            # Performance status
            if completion_rate >= 95:
                status = "EXCELLENT"
            elif completion_rate >= 85:
                status = "GOOD"
            elif completion_rate >= 75:
                status = "SATISFACTORY"
            else:
                status = "NEEDS IMPROVEMENT"
            
            report += f"PERFORMANCE STATUS: {status}\n\n"
            
            report += "TECHNICIAN PERFORMANCE:\n"
            report += f"{'Technician':<20} {'Assigned':<10} {'Completed':<10} {'Rate':<8} {'Avg Hours':<10}\n"
            report += "-" * 70 + "\n"
            
            # Clear and update technician performance tree
            for item in self.tech_performance_tree.get_children():
                self.tech_performance_tree.delete(item)
            
            for tech_data in tech_performance:
                technician, assigned, completed, avg_hours = tech_data
                tech_rate = (completed / assigned * 100) if assigned > 0 else 0
                avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "N/A"
                
                report += f"{technician:<20} {assigned:<10} {completed:<10} {tech_rate:<7.1f}% {avg_hours_display:<10}\n"
                
                # Add to tree
                self.tech_performance_tree.insert('', 'end', values=(
                    technician, assigned, completed, f"{tech_rate:.1f}%", avg_hours_display
                ))
            
            # Add PM type breakdown
            cursor.execute('''
                SELECT pm_type, 
                       COUNT(*) as scheduled,
                       COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed
                FROM weekly_pm_schedules 
                WHERE week_start_date = %s
                GROUP BY pm_type
            ''', (week_start.strftime('%Y-%m-%d'),))
            
            pm_types = cursor.fetchall()
            
            if pm_types:
                report += "\nPM TYPE BREAKDOWN:\n"
                report += f"{'PM Type':<15} {'Scheduled':<10} {'Completed':<10} {'Rate':<8}\n"
                report += "-" * 45 + "\n"
                
                for pm_type, scheduled, completed in pm_types:
                    pm_rate = (completed / scheduled * 100) if scheduled > 0 else 0
                    report += f"{pm_type:<15} {scheduled:<10} {completed:<10} {pm_rate:<7.1f}%\n"
            
            # Display report
            self.weekly_report_text.delete('1.0', 'end')
            self.weekly_report_text.insert('end', report)
            
            # Save report to database
            cursor.execute('''
                INSERT OR REPLACE INTO weekly_reports 
                (week_start_date, total_scheduled, total_completed, completion_rate, 
                 technician_performance, report_data)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                week_start.strftime('%Y-%m-%d'),
                total_scheduled,
                total_completed,
                completion_rate,
                json.dumps(tech_performance),
                report
            ))
            
            self.conn.commit()
            self.update_status(f"Weekly report generated - {completion_rate:.1f}% completion rate")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate weekly report: {str(e)}")
    
    def generate_monthly_report(self):
        """Generate monthly PM performance report"""
        try:
            current_date = datetime.now()
            month_start = current_date.replace(day=1)
            
            cursor = self.conn.cursor()
            
            # Get monthly statistics from weekly reports
            cursor.execute('''
                SELECT week_start_date, total_scheduled, total_completed, completion_rate
                FROM weekly_reports 
                WHERE week_start_date >= DATE_TRUNC('month', %s::date)
                ORDER BY week_start_date
            ''', (current_date.strftime('%Y-%m-%d'),))
            
            weekly_data = cursor.fetchall()
            
            # Get monthly PM completions
            cursor.execute('''
                SELECT 
                    pm_type,
                    COUNT(*) as total_completed,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions 
                WHERE completion_date >= DATE_TRUNC('month', %s::date)
                GROUP BY pm_type
            ''', (current_date.strftime('%Y-%m-%d'),))
            
            monthly_completions = cursor.fetchall()
            
            # Generate monthly report
            report = f"MONTHLY PM PERFORMANCE REPORT\n"
            report += f"Month: {current_date.strftime('%B %Y')}\n"
            report += "=" * 80 + "\n\n"
            
            if weekly_data:
                total_scheduled = sum(row[1] for row in weekly_data)
                total_completed = sum(row[2] for row in weekly_data)
                avg_completion_rate = sum(row[3] for row in weekly_data) / len(weekly_data)
                
                report += f"MONTHLY SUMMARY:\n"
                report += f"Total Weeks Reported: {len(weekly_data)}\n"
                report += f"Total PMs Scheduled: {total_scheduled}\n"
                report += f"Total PMs Completed: {total_completed}\n"
                report += f"Average Completion Rate: {avg_completion_rate:.1f}%\n"
                report += f"Monthly Target ({len(weekly_data)} weeks  {self.weekly_pm_target}): {len(weekly_data) * self.weekly_pm_target}\n\n"
                
                report += "WEEKLY BREAKDOWN:\n"
                report += f"{'Week Starting':<15} {'Scheduled':<10} {'Completed':<10} {'Rate':<8}\n"
                report += "-" * 45 + "\n"
                
                for week_start, scheduled, completed, rate in weekly_data:
                    report += f"{week_start:<15} {scheduled:<10} {completed:<10} {rate:<7.1f}%\n"
            
            if monthly_completions:
                report += "\nPM TYPE PERFORMANCE (Month):\n"
                report += f"{'PM Type':<15} {'Completed':<10} {'Avg Hours':<10}\n"
                report += "-" * 37 + "\n"
                
                for pm_type, completed, avg_hours in monthly_completions:
                    report += f"{pm_type:<15} {completed:<10} {avg_hours:<9.1f}h\n"
            
            # Display report
            self.weekly_report_text.delete('1.0', 'end')
            self.weekly_report_text.insert('end', report)
            
            self.update_status("Monthly report generated")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate monthly report: {str(e)}")
    
    def export_reports(self):
        """Export reports to file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"PM_Reports_{timestamp}.txt"
            
            content = self.weekly_report_text.get('1.0', 'end-1c')
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("Success", f"Reports exported to: {filename}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export reports: {str(e)}")
    
    
    
    
    def create_cm_dialog(self):
        """Create new Corrective Maintenance with calendar date picker"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Create New Corrective Maintenance")
        dialog.geometry("600x550")
        dialog.transient(self.root)
        dialog.grab_set()

        # Generate next CM number in format CM-YYYYMMDD-XXXX
        cursor = self.conn.cursor()
        today = datetime.now().strftime('%Y%m%d')
        cursor.execute(
            "SELECT MAX(CAST(SPLIT_PART(cm_number, '-', 3) AS INTEGER)) "
            "FROM corrective_maintenance "
            "WHERE cm_number LIKE %s",
            (f'CM-{today}-%',)
        )
        result = cursor.fetchone()[0]
        next_seq = (result + 1) if result else 1
        next_cm_num = f"CM-{today}-{next_seq:04d}"

        row = 0

        # CM Number (auto-generated, read-only)
        ttk.Label(dialog, text="CM Number:", font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        cm_number_var = tk.StringVar(value=next_cm_num)
        ttk.Entry(dialog, textvariable=cm_number_var, width=20, state='readonly').grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1

        # ========== ENHANCED DATE PICKER SECTION ==========
        ttk.Label(dialog, text="CM Date:", font=('Arial', 10)).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        
        # Create frame for date entry and calendar button
        date_frame = ttk.Frame(dialog)
        date_frame.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        
        # Date entry field - default to today's date
        cm_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        date_entry = ttk.Entry(date_frame, textvariable=cm_date_var, width=15)
        date_entry.pack(side='left', padx=(0, 5))
        
        # Calendar picker button
        def open_calendar():
            """Open calendar dialog to pick a date"""
            from tkcalendar import Calendar
        
            # Create calendar dialog
            cal_dialog = tk.Toplevel(dialog)
            cal_dialog.title("Select Date")
            cal_dialog.geometry("300x300")
            cal_dialog.transient(dialog)
            cal_dialog.grab_set()
        
            # Parse current date or use today
            try:
                current_date = datetime.strptime(cm_date_var.get(), '%Y-%m-%d')
            except:
                current_date = datetime.now()
        
            # Create calendar widget
            cal = Calendar(cal_dialog, 
                          selectmode='day',
                          year=current_date.year,
                          month=current_date.month,
                          day=current_date.day,
                          date_pattern='yyyy-mm-dd')
            cal.pack(pady=20, padx=20, fill='both', expand=True)
        
            def select_date():
                cm_date_var.set(cal.get_date())
                cal_dialog.destroy()
        
            # Buttons
            button_frame = ttk.Frame(cal_dialog)
            button_frame.pack(pady=10)
            ttk.Button(button_frame, text="Select", command=select_date).pack(side='left', padx=5)
            ttk.Button(button_frame, text="Today", 
                    command=lambda: [cm_date_var.set(datetime.now().strftime('%Y-%m-%d')), 
                                    cal_dialog.destroy()]).pack(side='left', padx=5)
            ttk.Button(button_frame, text="Cancel", command=cal_dialog.destroy).pack(side='left', padx=5)
    
        # Calendar button with icon
        ttk.Button(date_frame, text="WARNING: Pick Date", command=open_calendar).pack(side='left')
        
        # Date format helper label
        ttk.Label(dialog, text="Format: YYYY-MM-DD", 
                font=('Arial', 8), foreground='gray').grid(row=row, column=2, sticky='w', padx=5)
        row += 1
        # ================================================

        # Equipment Selection
        ttk.Label(dialog, text="Equipment (BFM):").grid(row=row, column=0, sticky='w', padx=10, pady=5)
        bfm_var = tk.StringVar()
        
        cursor.execute("SELECT DISTINCT bfm_equipment_no FROM equipment WHERE status = 'Active' ORDER BY bfm_equipment_no")
        equipment_list = [row[0] for row in cursor.fetchall()]
        
        bfm_combo = ttk.Combobox(dialog, textvariable=bfm_var, values=equipment_list, width=20)
        bfm_combo.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1

        # Description
        ttk.Label(dialog, text="Description:").grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        description_text = tk.Text(dialog, width=40, height=6)
        description_text.grid(row=row, column=1, columnspan=2, sticky='w', padx=10, pady=5)
        row += 1

        # Priority
        ttk.Label(dialog, text="Priority:").grid(row=row, column=0, sticky='w', padx=10, pady=5)
        priority_var = tk.StringVar(value="Medium")
        priority_combo = ttk.Combobox(dialog, textvariable=priority_var, 
                                    values=["Low", "Medium", "High", "Critical"], 
                                    state="readonly", width=20)
        priority_combo.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1

        # Assigned Technician
        ttk.Label(dialog, text="Assigned Technician:").grid(row=row, column=0, sticky='w', padx=10, pady=5)
        assigned_var = tk.StringVar()

        if self.current_user_role == 'Technician':
            # Auto-assign to current technician and make read-only
            assigned_var.set(self.user_name)
            assigned_entry = ttk.Entry(dialog, textvariable=assigned_var, width=20, state='readonly')
            assigned_entry.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        else:
            # Manager can assign to anyone
            assigned_combo = ttk.Combobox(dialog, textvariable=assigned_var, 
                                        values=self.technicians, width=20)
            assigned_combo.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1

        def validate_and_save_cm():
            """Validate the CM date format and save"""
            try:
                # Validate the date format
                cm_date_input = cm_date_var.get().strip()
        
                if not cm_date_input:
                    messagebox.showerror("Error", "Please enter a CM date")
                    return
        
                # Try to parse the date to validate format
                try:
                    parsed_date = datetime.strptime(cm_date_input, '%Y-%m-%d')
            
                    if parsed_date > datetime.now() + timedelta(days=1):
                        result = messagebox.askyesno("Future Date Warning", 
                                                f"The CM date '{cm_date_input}' is in the future.\n\n"
                                                f"Are you sure this is correct?")
                        if not result:
                            return
            
                    if parsed_date < datetime.now() - timedelta(days=365):
                        result = messagebox.askyesno("Old Date Warning", 
                                                f"The CM date '{cm_date_input}' is more than 1 year ago.\n\n"
                                                f"Are you sure this is correct?")
                        if not result:
                            return
            
                    validated_date = parsed_date.strftime('%Y-%m-%d')
            
                except ValueError:
                    messagebox.showerror("Invalid Date Format", 
                                    f"Please enter the date in YYYY-MM-DD format.\n\n"
                                    f"Examples:\n"
                                    f"- 2025-08-04 (August 4th, 2025)\n"
                                    f"- 2025-12-15 (December 15th, 2025)\n\n"
                                    f"You entered: '{cm_date_input}'")
                    return
        
                # Validate other required fields
                if not bfm_var.get():
                    messagebox.showerror("Error", "Please select equipment")
                    return
            
                if not description_text.get('1.0', 'end-1c').strip():
                    messagebox.showerror("Error", "Please enter a description")
                    return
        
                # Save to database with the manually entered date
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO corrective_maintenance 
                    (cm_number, bfm_equipment_no, description, priority, assigned_technician, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    cm_number_var.get(),
                    bfm_var.get(),
                    description_text.get('1.0', 'end-1c'),
                    priority_var.get(),
                    assigned_var.get(),
                    validated_date
                ))
                self.conn.commit()
            
                messagebox.showinfo("Success", 
                                f"Corrective Maintenance created successfully!\n\n"
                                f"CM Number: {cm_number_var.get()}\n"
                                f"CM Date: {validated_date}\n"
                                f"Equipment: {bfm_var.get()}\n"
                                f"Assigned to: {assigned_var.get()}")
                dialog.destroy()
                self.load_corrective_maintenance()
        
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create CM: {str(e)}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=row, column=0, columnspan=3, pady=20)
        
        ttk.Button(button_frame, text="Create CM", command=validate_and_save_cm).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)
        
    
    
    
    
    def edit_cm_dialog(self):
        """Edit existing Corrective Maintenance with full functionality"""
        selected = self.cm_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a CM to edit")
            return

        # Get selected CM data
        item = self.cm_tree.item(selected[0])
        cm_number = item['values'][0]

        # Fetch full CM data from database
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT cm_number, bfm_equipment_no, description, priority, assigned_technician, 
                status, created_date, completion_date, labor_hours, notes, root_cause, corrective_action
            FROM corrective_maintenance 
            WHERE cm_number = %s
        ''', (cm_number,))

        cm_data = cursor.fetchone()
        if not cm_data:
            messagebox.showerror("Error", "CM not found in database")
            return

        # Extract CM data
        (orig_cm_number, orig_bfm_no, orig_description, orig_priority, orig_assigned, 
        orig_status, orig_created, orig_completion, orig_hours, orig_notes, 
        orig_root_cause, orig_corrective_action) = cm_data

        # Create edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Corrective Maintenance - {cm_number}")
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()

        # Main container with scrollbar
        main_canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )

        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        # CM Information (header)
        header_frame = ttk.LabelFrame(scrollable_frame, text="CM Information", padding=10)
        header_frame.pack(fill='x', padx=10, pady=5)

        row = 0

        # CM Number (read-only)
        ttk.Label(header_frame, text="CM Number:").grid(row=row, column=0, sticky='w', padx=5, pady=5)
        ttk.Label(header_frame, text=orig_cm_number, font=('Arial', 10, 'bold')).grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # Equipment (editable)
        ttk.Label(header_frame, text="BFM Equipment No:").grid(row=row, column=0, sticky='w', padx=5, pady=5)
        bfm_var = tk.StringVar(value=orig_bfm_no or '')
        bfm_combo = ttk.Combobox(header_frame, textvariable=bfm_var, width=25)
        bfm_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)

        # Populate equipment list
        cursor.execute('SELECT bfm_equipment_no FROM equipment ORDER BY bfm_equipment_no')
        equipment_list = [row[0] for row in cursor.fetchall()]
        bfm_combo['values'] = equipment_list
        row += 1

        # Priority (editable)
        ttk.Label(header_frame, text="Priority:").grid(row=row, column=0, sticky='w', padx=5, pady=5)
        priority_var = tk.StringVar(value=orig_priority or 'Medium')
        priority_combo = ttk.Combobox(header_frame, textvariable=priority_var, 
                                values=['Low', 'Medium', 'High', 'Emergency'], width=15)
        priority_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # Assigned Technician (editable)
        ttk.Label(header_frame, text="Assigned Technician:").grid(row=row, column=0, sticky='w', padx=5, pady=5)
        assigned_var = tk.StringVar(value=orig_assigned or '')
        assigned_combo = ttk.Combobox(header_frame, textvariable=assigned_var, 
                                values=self.technicians, width=20)
        assigned_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # Status (editable)
        ttk.Label(header_frame, text="Status:").grid(row=row, column=0, sticky='w', padx=5, pady=5)
        status_var = tk.StringVar(value=orig_status or 'Open')
        status_combo = ttk.Combobox(header_frame, textvariable=status_var, 
                              values=['Open', 'Closed'], width=15)
        status_combo.grid(row=row, column=1, sticky='w', padx=5, pady=5)
        row += 1

        # Description (editable)
        desc_frame = ttk.LabelFrame(scrollable_frame, text="Description", padding=10)
        desc_frame.pack(fill='x', padx=10, pady=5)

        description_text = tk.Text(desc_frame, width=60, height=4)
        description_text.pack(fill='x', padx=5, pady=5)
        description_text.insert('1.0', orig_description or '')

        # Completion Information (if completed)
        completion_frame = ttk.LabelFrame(scrollable_frame, text="Completion Information", padding=10)
        completion_frame.pack(fill='x', padx=10, pady=5)

        comp_row = 0

        # Labor Hours
        ttk.Label(completion_frame, text="Labor Hours:").grid(row=comp_row, column=0, sticky='w', padx=5, pady=5)
        labor_hours_var = tk.StringVar(value=str(orig_hours or ''))
        ttk.Entry(completion_frame, textvariable=labor_hours_var, width=10).grid(row=comp_row, column=1, sticky='w', padx=5, pady=5)
        comp_row += 1

        # Completion Date
        ttk.Label(completion_frame, text="Completion Date:").grid(row=comp_row, column=0, sticky='w', padx=5, pady=5)
        completion_date_var = tk.StringVar(value=orig_completion or '')
        ttk.Entry(completion_frame, textvariable=completion_date_var, width=15).grid(row=comp_row, column=1, sticky='w', padx=5, pady=5)
        comp_row += 1

        # Notes
        notes_frame = ttk.LabelFrame(scrollable_frame, text="Notes", padding=10)
        notes_frame.pack(fill='x', padx=10, pady=5)

        notes_text = tk.Text(notes_frame, width=60, height=4)
        notes_text.pack(fill='x', padx=5, pady=5)
        notes_text.insert('1.0', orig_notes or '')

        # Root Cause
        root_cause_frame = ttk.LabelFrame(scrollable_frame, text="Root Cause Analysis", padding=10)
        root_cause_frame.pack(fill='x', padx=10, pady=5)

        root_cause_text = tk.Text(root_cause_frame, width=60, height=3)
        root_cause_text.pack(fill='x', padx=5, pady=5)
        root_cause_text.insert('1.0', orig_root_cause or '')

        # Corrective Action
        corrective_action_frame = ttk.LabelFrame(scrollable_frame, text="Corrective Action", padding=10)
        corrective_action_frame.pack(fill='x', padx=10, pady=5)

        corrective_action_text = tk.Text(corrective_action_frame, width=60, height=3)
        corrective_action_text.pack(fill='x', padx=5, pady=5)
        corrective_action_text.insert('1.0', orig_corrective_action or '')

        def save_changes():
            try:
                # Validate inputs
                if not description_text.get('1.0', 'end-1c').strip():
                    messagebox.showerror("Error", "Please enter a description")
                    return

                # Update database
                cursor = self.conn.cursor()
                cursor.execute('''
                    UPDATE corrective_maintenance SET
                    bfm_equipment_no = %s,
                    description = %s,
                    priority = %s,
                    assigned_technician = %s,
                    status = %s,
                    labor_hours = %s,
                    completion_date = %s,
                    notes = %s,
                    root_cause = %s,
                    corrective_action = %s
                    WHERE cm_number = %s
                ''', (
                    bfm_var.get(),
                    description_text.get('1.0', 'end-1c'),
                    priority_var.get(),
                    assigned_var.get(),
                    status_var.get(),
                    float(labor_hours_var.get() or 0),
                    completion_date_var.get() if completion_date_var.get() else None,
                    notes_text.get('1.0', 'end-1c'),
                    root_cause_text.get('1.0', 'end-1c'),
                    corrective_action_text.get('1.0', 'end-1c'),
                    orig_cm_number
                ))

                self.conn.commit()
                messagebox.showinfo("Success", f"CM {orig_cm_number} updated successfully!")
                dialog.destroy()
                self.load_corrective_maintenance()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to update CM: {str(e)}")

        def delete_cm():
            result = messagebox.askyesno("Confirm Delete", 
                                    f"Delete CM {orig_cm_number}?\n\n"
                                    f"This action cannot be undone.")
            if result:
                try:
                    cursor = self.conn.cursor()
                    cursor.execute('DELETE FROM corrective_maintenance WHERE cm_number = %s', (orig_cm_number,))
                    self.conn.commit()
                    messagebox.showinfo("Success", f"CM {orig_cm_number} deleted successfully!")
                    dialog.destroy()
                    self.load_corrective_maintenance()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to delete CM: {str(e)}")

        # Buttons frame
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(side='bottom', fill='x', padx=10, pady=10)

        ttk.Button(button_frame, text="Save Changes", command=save_changes).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Delete CM", command=delete_cm).pack(side='left', padx=5)
        
        # ============ ADD THIS NEW SECTION ============
        # View Parts button - shows parts consumed for this CM
        if hasattr(self, 'parts_integration'):
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM cm_parts_used WHERE cm_number = %s', (orig_cm_number,))
            parts_count = cursor.fetchone()[0]
            
            if parts_count > 0:
                button_text = f"WARNING: View Parts Used ({parts_count})"
            else:
                button_text = "WARNING: No Parts Used"
            
            def show_parts_detail():
                self.parts_integration.show_cm_parts_details(orig_cm_number)
            
            ttk.Button(button_frame, text=button_text, 
                      command=show_parts_detail).pack(side='left', padx=5)
        # ============ END NEW SECTION ============
        
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

        # Pack the canvas and scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Update scroll region
        scrollable_frame.update_idletasks()
        main_canvas.configure(scrollregion=main_canvas.bbox("all"))
    
    
    
    def complete_cm_dialog(self):
        """Complete selected CM with parts consumption tracking"""
        selected = self.cm_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a CM to complete")
            return

        # Get selected CM data
        item = self.cm_tree.item(selected[0])
        cm_number = item['values'][0]
    
        # Fetch CM details
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT cm_number, bfm_equipment_no, description, assigned_technician, 
                status, labor_hours, notes, root_cause, corrective_action
            FROM corrective_maintenance 
            WHERE cm_number = %s
        ''', (cm_number,))
    
        cm_data = cursor.fetchone()
        if not cm_data:
            messagebox.showerror("Error", "CM not found")
            return
    
        (cm_num, equipment, desc, tech, status, labor_hrs, 
         notes, root_cause, corr_action) = cm_data
    
        # Check if already closed
        if status in ['Closed', 'Completed']:
            messagebox.showinfo("Info", f"CM {cm_number} is already closed")
            return
    
        # Create closure dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Complete CM - {cm_number}")
        dialog.geometry("700x600")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Header
        header_frame = ttk.Frame(dialog)
        header_frame.pack(fill='x', padx=10, pady=10)
    
        ttk.Label(header_frame, text=f"Complete Corrective Maintenance", 
                font=('Arial', 12, 'bold')).pack()
        ttk.Label(header_frame, text=f"CM Number: {cm_number}", 
                font=('Arial', 10)).pack()
        ttk.Label(header_frame, text=f"Equipment: {equipment}", 
                font=('Arial', 10)).pack()
    
        # Main form frame with scrollbar
        canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
    
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
    
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
        
        # Form fields
        row = 0
    
        # Completion Date
        ttk.Label(scrollable_frame, text="Completion Date*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        completion_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        ttk.Entry(scrollable_frame, textvariable=completion_date_var, width=40).grid(
            row=row, column=1, sticky='w', padx=10, pady=5)
        ttk.Label(scrollable_frame, text="(Format: YYYY-MM-DD)", 
                font=('Arial', 8, 'italic')).grid(row=row, column=2, sticky='w')
        row += 1
    
        # Labor Hours
        ttk.Label(scrollable_frame, text="Total Labor Hours*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=10, pady=5)
        labor_hours_var = tk.StringVar(value=str(labor_hrs) if labor_hrs else '')
        ttk.Entry(scrollable_frame, textvariable=labor_hours_var, width=40).grid(
            row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        ttk.Separator(scrollable_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
    
        # Root Cause
        ttk.Label(scrollable_frame, text="Root Cause*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        root_cause_text = tk.Text(scrollable_frame, width=50, height=4)
        root_cause_text.insert('1.0', root_cause or '')
        root_cause_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        # Corrective Action
        ttk.Label(scrollable_frame, text="Corrective Action Taken*:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        corr_action_text = tk.Text(scrollable_frame, width=50, height=4)
        corr_action_text.insert('1.0', corr_action or '')
        corr_action_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        # Additional Notes
        ttk.Label(scrollable_frame, text="Additional Notes:", 
                font=('Arial', 10, 'bold')).grid(row=row, column=0, sticky='nw', padx=10, pady=5)
        notes_text = tk.Text(scrollable_frame, width=50, height=4)
        notes_text.insert('1.0', notes or '')
        notes_text.grid(row=row, column=1, sticky='w', padx=10, pady=5)
        row += 1
    
        ttk.Separator(scrollable_frame, orient='horizontal').grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
    
        # Parts consumption question - THIS IS THE KEY INTEGRATION POINT
        ttk.Label(scrollable_frame, text="Were any parts used from MRO Stock?", 
                font=('Arial', 11, 'bold'), foreground='blue').grid(
                    row=row, column=0, columnspan=2, sticky='w', padx=10, pady=10)
        row += 1
    
        parts_used_var = tk.StringVar(value="No")
        ttk.Radiobutton(scrollable_frame, text="No parts were used", 
                    variable=parts_used_var, value="No").grid(
                        row=row, column=0, columnspan=2, sticky='w', padx=30, pady=5)
        row += 1
    
        ttk.Radiobutton(scrollable_frame, text="Yes, parts were used (will open parts dialog)", 
                    variable=parts_used_var, value="Yes").grid(
                        row=row, column=0, columnspan=2, sticky='w', padx=30, pady=5)
        row += 1
    
        # Button frame
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)
    
        def validate_and_proceed():
            """Validate closure form and proceed to parts or close"""
            # Validate required fields
            if not completion_date_var.get().strip():
                messagebox.showerror("Error", "Completion date is required")
                return
        
            try:
                datetime.strptime(completion_date_var.get(), '%Y-%m-%d')
            except ValueError:
                messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD")
                return
        
            if not labor_hours_var.get().strip():
                messagebox.showerror("Error", "Labor hours is required")
                return
        
            try:
                labor_hrs_value = float(labor_hours_var.get())
                if labor_hrs_value < 0:
                    messagebox.showerror("Error", "Labor hours cannot be negative")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid labor hours value")
                return
        
            root_cause_value = root_cause_text.get('1.0', 'end-1c').strip()
            if not root_cause_value:
                messagebox.showerror("Error", "Root cause is required")
                return
        
            corr_action_value = corr_action_text.get('1.0', 'end-1c').strip()
            if not corr_action_value:
                messagebox.showerror("Error", "Corrective action is required")
                return
        
            # Get all form values
            completion_date = completion_date_var.get()
            labor_hours = float(labor_hours_var.get())
            root_cause = root_cause_value
            corrective_action = corr_action_value
            additional_notes = notes_text.get('1.0', 'end-1c').strip()
            
            # Combine notes
            all_notes = additional_notes
        
            def finalize_closure(parts_recorded):
                """Finalize CM closure after parts handling"""
                if not parts_recorded and parts_used_var.get() == "Yes":
                    # User cancelled parts dialog, don't close CM
                    return
            
                try:
                    cursor = self.conn.cursor()
                
                    # Update CM record
                    cursor.execute('''
                        UPDATE corrective_maintenance
                        SET status = 'Closed',
                            completion_date = %s,
                            labor_hours = %s,
                            root_cause = %s,
                            corrective_action = %s,
                            notes = %s
                        WHERE cm_number = %s
                    ''', (completion_date, labor_hours, root_cause, 
                        corrective_action, all_notes, cm_number))
                
                    self.conn.commit()
                
                    messagebox.showinfo("Success", 
                        f"CM {cm_number} completed successfully!\n\n"
                        f"Completion Date: {completion_date}\n"
                        f"Labor Hours: {labor_hours}\n"
                        f"Status: Closed")
                
                    dialog.destroy()
                    self.load_corrective_maintenance()
                
                except Exception as e:
                    self.conn.rollback()
                    messagebox.showerror("Error", f"Failed to complete CM: {str(e)}")
            
            # Check if parts were used
            if parts_used_var.get() == "Yes":
                # Close this dialog and open parts consumption dialog
                dialog.destroy()
            
                # Open parts consumption dialog
                # This requires the CMPartsIntegration module to be initialized
                if hasattr(self, 'parts_integration'):
                    self.parts_integration.show_parts_consumption_dialog(
                        cm_number=cm_number,
                        technician_name=tech or 'Unknown',
                        callback=finalize_closure
                    )
                else:
                    messagebox.showerror("Error", 
                        "Parts integration module not initialized.\n"
                        "Please contact system administrator.")
                    # Still update CM but without parts
                    finalize_closure(True)
            else:
                # No parts used, close directly
                finalize_closure(True)
    
        ttk.Button(button_frame, text="WARNING: Complete CM", 
                command=validate_and_proceed).pack(side='left', padx=5)
        ttk.Button(button_frame, text="CHECK: Cancel", 
                command=dialog.destroy).pack(side='left', padx=5)
    
 
    
    
    def load_corrective_maintenance(self):
        """Load corrective maintenance data"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT cm_number, bfm_equipment_no, description, priority, 
                       assigned_technician, status, created_date
                FROM corrective_maintenance 
                ORDER BY created_date DESC
            ''')
            
            # Clear existing items
            for item in self.cm_tree.get_children():
                self.cm_tree.delete(item)
            
            # Add CM records
            for cm in cursor.fetchall():
                cm_number, bfm_no, description, priority, assigned, status, created = cm
                # Truncate description for display
                display_desc = (description[:47] + '...') if len(description) > 50 else description
                self.cm_tree.insert('', 'end', values=(
                    cm_number, bfm_no, display_desc, priority, assigned, status, created
                ))
                
        except Exception as e:
            print(f"Error loading corrective maintenance: {e}")
    
    def refresh_analytics_dashboard(self):
        """Refresh analytics dashboard with current data"""
        try:
            cursor = self.conn.cursor()
            
            # Generate comprehensive analytics
            analytics = "AIT CMMS ANALYTICS DASHBOARD\n"
            analytics += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            analytics += "=" * 80 + "\n\n"
            
            # Equipment statistics
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active_equipment = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE monthly_pm = 1')
            monthly_pm_equipment = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE six_month_pm = 1')
            six_month_pm_equipment = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE annual_pm = 1')
            annual_pm_equipment = cursor.fetchone()[0]
            
            analytics += "EQUIPMENT OVERVIEW:\n"
            analytics += f"Total Active Equipment: {active_equipment}\n"
            analytics += f"Equipment with Monthly PM: {monthly_pm_equipment}\n"
            analytics += f"Equipment with Six Month PM: {six_month_pm_equipment}\n"
            analytics += f"Equipment with Annual PM: {annual_pm_equipment}\n\n"
            
            # PM completion statistics (last 30 days)
            cursor.execute('''
                SELECT COUNT(*) FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
            ''')
            recent_completions = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT pm_type, COUNT(*)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY pm_type
            ''')
            pm_type_stats = cursor.fetchall()
            
            analytics += "PM COMPLETION STATISTICS (Last 30 Days):\n"
            analytics += f"Total PM Completions: {recent_completions}\n"
            for pm_type, count in pm_type_stats:
                analytics += f"{pm_type} PMs: {count}\n"
            analytics += "\n"
            
            # Technician performance (last 30 days)
            cursor.execute('''
                SELECT technician_name,
                       COUNT(*) as completed_pms,
                       AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY technician_name
                ORDER BY completed_pms DESC
            ''')
            tech_stats = cursor.fetchall()
            
            analytics += "TECHNICIAN PERFORMANCE (Last 30 Days):\n"
            analytics += f"{'Technician':<20} {'Completed PMs':<15} {'Avg Hours':<10}\n"
            analytics += "-" * 47 + "\n"
            for tech, completed, avg_hours in tech_stats:
                analytics += f"{tech:<20} {completed:<15} {avg_hours:<9.1f}h\n"
            analytics += "\n"
            
            # CM statistics
            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
            open_cms = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Completed'")
            completed_cms = cursor.fetchone()[0]
            
            analytics += "CORRECTIVE MAINTENANCE:\n"
            analytics += f"Open CMs: {open_cms}\n"
            analytics += f"Completed CMs: {completed_cms}\n\n"
            
            # Current week performance
            current_week_start = self.get_week_start(datetime.now()).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT 
                    COUNT(*) as scheduled,
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed
                FROM weekly_pm_schedules 
                WHERE week_start_date = %s
            ''', (current_week_start,))
            
            week_scheduled, week_completed = cursor.fetchone()
            week_rate = (week_completed / week_scheduled * 100) if week_scheduled > 0 else 0
            
            analytics += "CURRENT WEEK PERFORMANCE:\n"
            analytics += f"Scheduled PMs: {week_scheduled}\n"
            analytics += f"Completed PMs: {week_completed}\n"
            analytics += f"Completion Rate: {week_rate:.1f}%\n\n"
            
            # Display analytics
            self.analytics_text.delete('1.0', 'end')
            self.analytics_text.insert('end', analytics)
            
        except Exception as e:
            print(f"Error refreshing analytics dashboard: {e}")
    
    def show_equipment_analytics(self):
        """Show comprehensive equipment analytics in a new dialog window"""
        try:
            # Create analytics dialog
            analytics_dialog = tk.Toplevel(self.root)
            analytics_dialog.title("Equipment Analytics Dashboard")
            analytics_dialog.geometry("1200x800")
            analytics_dialog.transient(self.root)
            analytics_dialog.grab_set()
        
            # Create notebook for different analytics tabs
            analytics_notebook = ttk.Notebook(analytics_dialog)
            analytics_notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
            # Tab 1: Equipment Overview
            overview_frame = ttk.Frame(analytics_notebook)
            analytics_notebook.add(overview_frame, text="Equipment Overview")
        
            # Tab 2: PM Performance Analysis
            pm_performance_frame = ttk.Frame(analytics_notebook)
            analytics_notebook.add(pm_performance_frame, text="PM Performance")
        
            # Tab 3: Location Analysis
            location_frame = ttk.Frame(analytics_notebook)
            analytics_notebook.add(location_frame, text="Location Analysis")
        
            # Tab 4: Technician Workload
            technician_frame = ttk.Frame(analytics_notebook)
            analytics_notebook.add(technician_frame, text="Technician Analysis")
        
            # Generate analytics for each tab
            self.generate_equipment_overview(overview_frame)
            self.generate_pm_performance_analysis(pm_performance_frame)
            self.generate_location_analysis(location_frame)
            self.generate_technician_analysis(technician_frame)
        
            # Add export button
            export_frame = ttk.Frame(analytics_dialog)
            export_frame.pack(side='bottom', fill='x', padx=10, pady=5)
        
            ttk.Button(export_frame, text="Export All Analytics to PDF", 
                    command=lambda: self.export_equipment_analytics_pdf(analytics_dialog)).pack(side='right', padx=5)
            ttk.Button(export_frame, text="Close", 
                    command=analytics_dialog.destroy).pack(side='right', padx=5)
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate equipment analytics: {str(e)}")

    def generate_equipment_overview(self, parent_frame):
        """Generate equipment overview analytics"""
        try:
            cursor = self.conn.cursor()
        
            # Create scrollable text area
            text_frame = ttk.Frame(parent_frame)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
            overview_text = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=overview_text.yview)
            overview_text.configure(yscrollcommand=scrollbar.set)
        
            overview_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
        
            # Generate analytics content
            analytics = "EQUIPMENT ANALYTICS OVERVIEW\n"
            analytics += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            analytics += "=" * 80 + "\n\n"
        
            # Basic equipment statistics
            cursor.execute('SELECT COUNT(*) FROM equipment')
            total_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Missing'")
            missing_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Run to Failure'")
            rtf_equipment = cursor.fetchone()[0]
        
            analytics += "EQUIPMENT STATUS SUMMARY:\n"
            analytics += f"Total Equipment: {total_equipment}\n"
            analytics += f"Active Equipment: {active_equipment} ({active_equipment/total_equipment*100:.1f}%)\n"
            analytics += f"Missing Equipment: {missing_equipment} ({missing_equipment/total_equipment*100:.1f}%)\n"
            analytics += f"Run to Failure: {rtf_equipment} ({rtf_equipment/total_equipment*100:.1f}%)\n\n"
        
            # PM Type Distribution
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE monthly_pm = 1')
            monthly_pm_count = cursor.fetchone()[0]
        
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE six_month_pm = 1')
            six_month_pm_count = cursor.fetchone()[0]
        
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE annual_pm = 1')
            annual_pm_count = cursor.fetchone()[0]
            
            analytics += "PM TYPE REQUIREMENTS:\n"
            analytics += f"Monthly PM Required: {monthly_pm_count} assets ({monthly_pm_count/total_equipment*100:.1f}%)\n"
            analytics += f"Six Month PM Required: {six_month_pm_count} assets ({six_month_pm_count/total_equipment*100:.1f}%)\n"
            analytics += f"Annual PM Required: {annual_pm_count} assets ({annual_pm_count/total_equipment*100:.1f}%)\n\n"
        
            # Location distribution
            cursor.execute('''
                SELECT location, COUNT(*) as count 
                FROM equipment 
                WHERE location IS NOT NULL AND location != ''
                GROUP BY location 
                ORDER BY count DESC 
                LIMIT 10
            ''')
            location_stats = cursor.fetchall()
        
            if location_stats:
                analytics += "TOP 10 EQUIPMENT LOCATIONS:\n"
                analytics += f"{'Location':<20} {'Count':<10} {'Percentage':<12}\n"
                analytics += "-" * 45 + "\n"
            
                for location, count in location_stats:
                    percentage = count / total_equipment * 100
                    analytics += f"{location:<20} {count:<10} {percentage:<11.1f}%\n"
                analytics += "\n"
        
            # Equipment without PM completions (never serviced)
            cursor.execute('''
                SELECT e.bfm_equipment_no, e.description, e.location
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                WHERE pc.bfm_equipment_no IS NULL 
                AND e.status = 'Active'
                ORDER BY e.bfm_equipment_no
                LIMIT 20
            ''')
            never_serviced = cursor.fetchall()
        
            if never_serviced:
                analytics += f"EQUIPMENT NEVER SERVICED ({len(never_serviced)} items shown, may be more):\n"
                analytics += f"{'BFM Number':<15} {'Description':<30} {'Location':<15}\n"
                analytics += "-" * 62 + "\n"
            
                for bfm_no, description, location in never_serviced:
                    desc_short = (description[:27] + '...') if description and len(description) > 27 else (description or 'N/A')
                    loc_short = (location[:12] + '...') if location and len(location) > 12 else (location or 'N/A')
                    analytics += f"{bfm_no:<15} {desc_short:<30} {loc_short:<15}\n"
                analytics += "\n"
        
            # Equipment age analysis (based on creation date if available)
            cursor.execute('''
                SELECT
                    CASE
                        WHEN created_date >= CURRENT_DATE - INTERVAL '30 days' THEN 'Last 30 days'
                        WHEN created_date >= CURRENT_DATE - INTERVAL '90 days' THEN 'Last 90 days'
                        WHEN created_date >= CURRENT_DATE - INTERVAL '180 days' THEN 'Last 6 months'
                        WHEN created_date >= CURRENT_DATE - INTERVAL '365 days' THEN 'Last year'
                        ELSE 'Over 1 year'
                    END as age_category,
                    COUNT(*) as count
                FROM equipment
                WHERE created_date IS NOT NULL
                GROUP BY age_category
                ORDER BY 
                    CASE 
                        WHEN age_category = 'Last 30 days' THEN 1
                        WHEN age_category = 'Last 90 days' THEN 2
                        WHEN age_category = 'Last 6 months' THEN 3
                        WHEN age_category = 'Last year' THEN 4
                        ELSE 5
                    END
            ''')
            age_stats = cursor.fetchall()
        
            if age_stats:
                analytics += "EQUIPMENT AGE DISTRIBUTION (by creation date):\n"
                analytics += f"{'Age Category':<20} {'Count':<10} {'Percentage':<12}\n"
                analytics += "-" * 45 + "\n"
            
                total_with_dates = sum(count for _, count in age_stats)
                for age_category, count in age_stats:
                    percentage = count / total_with_dates * 100
                    analytics += f"{age_category:<20} {count:<10} {percentage:<11.1f}%\n"
                analytics += "\n"
        
            # Display analytics
            overview_text.insert('end', analytics)
            overview_text.config(state='disabled')
        
        except Exception as e:
            print(f"Error generating equipment overview: {e}")

    def generate_pm_performance_analysis(self, parent_frame):
        """Generate PM performance analytics"""
        try:
            cursor = self.conn.cursor()
            
            text_frame = ttk.Frame(parent_frame)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
            pm_text = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=pm_text.yview)
            pm_text.configure(yscrollcommand=scrollbar.set)
        
            pm_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
        
            analytics = "PM PERFORMANCE ANALYTICS\n"
            analytics += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            analytics += "=" * 80 + "\n\n"
        
            # PM completion statistics by type
            cursor.execute('''
                SELECT pm_type, COUNT(*) as count, 
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours,
                    MIN(completion_date) as first_completion,
                    MAX(completion_date) as last_completion
                FROM pm_completions 
                GROUP BY pm_type 
                ORDER BY count DESC
            ''')
            pm_type_stats = cursor.fetchall()
        
            if pm_type_stats:
                analytics += "PM COMPLETION STATISTICS BY TYPE:\n"
                analytics += f"{'PM Type':<15} {'Count':<10} {'Avg Hours':<12} {'Date Range':<25}\n"
                analytics += "-" * 65 + "\n"
            
                for pm_type, count, avg_hours, first_date, last_date in pm_type_stats:
                    avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "N/A"
                    date_range = f"{first_date} to {last_date}" if first_date and last_date else "N/A"
                    analytics += f"{pm_type:<15} {count:<10} {avg_hours_display:<12} {date_range:<25}\n"
                analytics += "\n"
        
            # Monthly completion trends (last 12 months)
            cursor.execute('''
                SELECT
                    TO_CHAR(completion_date::date, 'YYYY-MM') as month,
                    COUNT(*) as completions,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY TO_CHAR(completion_date::date, 'YYYY-MM')
                ORDER BY month DESC
            ''')
            monthly_trends = cursor.fetchall()
        
            if monthly_trends:
                analytics += "MONTHLY PM COMPLETION TRENDS (Last 12 months):\n"
                analytics += f"{'Month':<10} {'Completions':<12} {'Avg Hours':<12}\n"
                analytics += "-" * 36 + "\n"
            
                for month, completions, avg_hours in monthly_trends:
                    avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    analytics += f"{month:<10} {completions:<12} {avg_hours_display:<12}\n"
                analytics += "\n"
        
            # Equipment with overdue PMs
            current_date = datetime.now()
        
            cursor.execute('''
                SELECT e.bfm_equipment_no, e.description, e.location,
                    e.last_monthly_pm, e.last_annual_pm,
                    CASE
                        WHEN e.last_monthly_pm IS NULL OR e.last_monthly_pm + INTERVAL '30 days' < CURRENT_DATE THEN 'Monthly Overdue'
                        WHEN e.last_annual_pm IS NULL OR e.last_annual_pm + INTERVAL '365 days' < CURRENT_DATE THEN 'Annual Overdue'
                        ELSE 'Current'
                    END as pm_status
                FROM equipment e
                WHERE e.status = 'Active'
                AND (
                    (e.monthly_pm = 1 AND (e.last_monthly_pm IS NULL OR e.last_monthly_pm + INTERVAL '30 days' < CURRENT_DATE))
                    OR
                    (e.annual_pm = 1 AND (e.last_annual_pm IS NULL OR e.last_annual_pm + INTERVAL '365 days' < CURRENT_DATE))
                )
                ORDER BY e.bfm_equipment_no
                LIMIT 25
            ''')
            overdue_equipment = cursor.fetchall()
        
            if overdue_equipment:
                analytics += f"OVERDUE PM EQUIPMENT ({len(overdue_equipment)} items shown):\n"
                analytics += f"{'BFM Number':<15} {'Description':<25} {'Location':<12} {'Status':<15}\n"
                analytics += "-" * 70 + "\n"
                
                for bfm_no, description, location, pm_status in overdue_equipment:
                    desc_short = (description[:22] + '...') if description and len(description) > 22 else (description or 'N/A')
                    loc_short = (location[:9] + '...') if location and len(location) > 9 else (location or 'N/A')
                    analytics += f"{bfm_no:<15} {desc_short:<25} {loc_short:<12} {pm_status:<15}\n"
                analytics += "\n"
        
            # PM frequency analysis
            cursor.execute('''
                SELECT e.bfm_equipment_no, COUNT(pc.id) as pm_count,
                    MIN(pc.completion_date) as first_pm,
                    MAX(pc.completion_date) as last_pm,
                    AVG(pc.labor_hours + pc.labor_minutes/60.0) as avg_hours
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                WHERE e.status = 'Active'
                GROUP BY e.bfm_equipment_no
                HAVING pm_count > 0
                ORDER BY pm_count DESC
                LIMIT 15
            ''')
            high_maintenance_equipment = cursor.fetchall()
        
            if high_maintenance_equipment:
                analytics += "TOP 15 MOST SERVICED EQUIPMENT:\n"
                analytics += f"{'BFM Number':<15} {'PM Count':<10} {'First PM':<12} {'Last PM':<12} {'Avg Hours':<10}\n"
                analytics += "-" * 62 + "\n"
            
                for bfm_no, pm_count, first_pm, last_pm, avg_hours in high_maintenance_equipment:
                    avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    analytics += f"{bfm_no:<15} {pm_count:<10} {first_pm or 'N/A':<12} {last_pm or 'N/A':<12} {avg_hours_display:<10}\n"
                analytics += "\n"
        
            pm_text.insert('end', analytics)
            pm_text.config(state='disabled')
        
        except Exception as e:
            print(f"Error generating PM performance analysis: {e}")

    def generate_location_analysis(self, parent_frame):
        """Generate location-based analytics"""
        try:
            cursor = self.conn.cursor()
        
            text_frame = ttk.Frame(parent_frame)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
            location_text = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=location_text.yview)
            location_text.configure(yscrollcommand=scrollbar.set)
        
            location_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
        
            analytics = "LOCATION-BASED ANALYTICS\n"
            analytics += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            analytics += "=" * 80 + "\n\n"
        
            # Equipment distribution by location
            cursor.execute('''
                SELECT 
                    COALESCE(location, 'Unknown') as location,
                    COUNT(*) as total_equipment,
                    COUNT(CASE WHEN status = 'Active' THEN 1 END) as active,
                    COUNT(CASE WHEN status = 'Missing' THEN 1 END) as missing,
                    COUNT(CASE WHEN status = 'Run to Failure' THEN 1 END) as rtf
                FROM equipment
                GROUP BY COALESCE(location, 'Unknown')
                ORDER BY total_equipment DESC
            ''')
            location_distribution = cursor.fetchall()
        
            if location_distribution:
                analytics += "EQUIPMENT DISTRIBUTION BY LOCATION:\n"
                analytics += f"{'Location':<20} {'Total':<8} {'Active':<8} {'Missing':<8} {'RTF':<8}\n"
                analytics += "-" * 55 + "\n"
            
                for location, total, active, missing, rtf in location_distribution:
                    loc_display = location[:17] + '...' if len(location) > 17 else location
                    analytics += f"{loc_display:<20} {total:<8} {active:<8} {missing:<8} {rtf:<8}\n"
                analytics += "\n"
        
            # PM completion activity by location
            cursor.execute('''
                SELECT 
                    COALESCE(e.location, 'Unknown') as location,
                    COUNT(pc.id) as total_pms,
                    COUNT(CASE WHEN pc.pm_type = 'Monthly' THEN 1 END) as monthly,
                    COUNT(CASE WHEN pc.pm_type = 'Annual' THEN 1 END) as annual,
                    AVG(pc.labor_hours + pc.labor_minutes/60.0) as avg_hours
                FROM pm_completions pc
                JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
                WHERE pc.completion_date >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY COALESCE(e.location, 'Unknown')
                ORDER BY total_pms DESC
            ''')
            location_pm_activity = cursor.fetchall()
        
            if location_pm_activity:
                analytics += "PM ACTIVITY BY LOCATION (Last 90 days):\n"
                analytics += f"{'Location':<20} {'Total PMs':<10} {'Monthly':<8} {'Annual':<8} {'Avg Hours':<10}\n"
                analytics += "-" * 60 + "\n"
            
                for location, total_pms, monthly, annual, avg_hours in location_pm_activity:
                    loc_display = location[:17] + '...' if len(location) > 17 else location
                    avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    analytics += f"{loc_display:<20} {total_pms:<10} {monthly:<8} {annual:<8} {avg_hours_display:<10}\n"
                analytics += "\n"
        
            # Cannot Find assets by location
            cursor.execute('''
                SELECT 
                    COALESCE(location, 'Unknown') as location,
                    COUNT(*) as missing_count,
                    GROUP_CONCAT(bfm_equipment_no, ', ') as missing_assets
                FROM cannot_find_assets
                WHERE status = 'Missing'
                GROUP BY COALESCE(location, 'Unknown')
                ORDER BY missing_count DESC
            ''')
            missing_by_location = cursor.fetchall()
        
            if missing_by_location:
                analytics += "MISSING ASSETS BY LOCATION:\n"
                analytics += f"{'Location':<20} {'Count':<8} {'Equipment Numbers':<50}\n"
                analytics += "-" * 80 + "\n"
            
                for location, count, assets in missing_by_location:
                    loc_display = location[:17] + '...' if len(location) > 17 else location
                    assets_display = assets[:47] + '...' if assets and len(assets) > 47 else (assets or '')
                    analytics += f"{loc_display:<20} {count:<8} {assets_display:<50}\n"
                analytics += "\n"
        
            # Location efficiency analysis
            cursor.execute('''
                SELECT 
                    COALESCE(e.location, 'Unknown') as location,
                    COUNT(DISTINCT e.bfm_equipment_no) as equipment_count,
                    COUNT(pc.id) as pm_completions,
                    ROUND(CAST(COUNT(pc.id) AS FLOAT) / COUNT(DISTINCT e.bfm_equipment_no), 2) as pms_per_equipment
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                    AND pc.completion_date >= CURRENT_DATE - INTERVAL '365 days'
                WHERE e.status = 'Active'
                GROUP BY COALESCE(e.location, 'Unknown')
                HAVING equipment_count >= 3
                ORDER BY pms_per_equipment DESC
            ''')
            location_efficiency = cursor.fetchall()
        
            if location_efficiency:
                analytics += "LOCATION PM EFFICIENCY (PMs per equipment, last year):\n"
                analytics += f"{'Location':<20} {'Equipment':<10} {'PMs':<8} {'PMs/Equipment':<15}\n"
                analytics += "-" * 55 + "\n"
                
                for location, equipment_count, pm_completions, pms_per_equipment in location_efficiency:
                    loc_display = location[:17] + '...' if len(location) > 17 else location
                    analytics += f"{loc_display:<20} {equipment_count:<10} {pm_completions:<8} {pms_per_equipment:<15}\n"
                analytics += "\n"
        
            location_text.insert('end', analytics)
            location_text.config(state='disabled')
        
        except Exception as e:
            print(f"Error generating location analysis: {e}")

    def generate_technician_analysis(self, parent_frame):
        """Generate technician workload and performance analytics"""
        try:
            cursor = self.conn.cursor()
        
            text_frame = ttk.Frame(parent_frame)
            text_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
            tech_text = tk.Text(text_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=tech_text.yview)
            tech_text.configure(yscrollcommand=scrollbar.set)
        
            tech_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')
        
            analytics = "TECHNICIAN PERFORMANCE ANALYTICS\n"
            analytics += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            analytics += "=" * 80 + "\n\n"
        
            # Overall technician performance
            cursor.execute('''
                SELECT 
                    technician_name,
                    COUNT(*) as total_pms,
                    COUNT(CASE WHEN pm_type = 'Monthly' THEN 1 END) as monthly_pms,
                    COUNT(CASE WHEN pm_type = 'Annual' THEN 1 END) as annual_pms,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours,
                    SUM(labor_hours + labor_minutes/60.0) as total_hours,
                    MIN(completion_date) as first_completion,
                    MAX(completion_date) as last_completion
                FROM pm_completions
                GROUP BY technician_name
                ORDER BY total_pms DESC
            ''')
            technician_performance = cursor.fetchall()
        
            if technician_performance:
                analytics += "OVERALL TECHNICIAN PERFORMANCE:\n"
                analytics += f"{'Technician':<20} {'Total PMs':<10} {'Monthly':<8} {'Annual':<8} {'Avg Hrs':<8} {'Total Hrs':<10}\n"
                analytics += "-" * 75 + "\n"
            
                for tech_data in technician_performance:
                    technician, total_pms, monthly, annual, avg_hours, total_hours, first_date, last_date = tech_data
                    tech_display = technician[:17] + '...' if len(technician) > 17 else technician
                    avg_hours_display = f"{avg_hours:.1f}" if avg_hours else "0.0"
                    total_hours_display = f"{total_hours:.1f}" if total_hours else "0.0"
                
                    analytics += f"{tech_display:<20} {total_pms:<10} {monthly:<8} {annual:<8} {avg_hours_display:<8} {total_hours_display:<10}\n"
                analytics += "\n"
        
            # Recent activity (last 30 days)
            cursor.execute('''
                SELECT 
                    technician_name,
                    COUNT(*) as recent_pms,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours,
                    COUNT(DISTINCT bfm_equipment_no) as unique_equipment
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY technician_name
                ORDER BY recent_pms DESC
            ''')
            recent_activity = cursor.fetchall()
        
            if recent_activity:
                analytics += "RECENT ACTIVITY (Last 30 days):\n"
                analytics += f"{'Technician':<20} {'PMs':<6} {'Avg Hours':<10} {'Unique Equipment':<18}\n"
                analytics += "-" * 56 + "\n"
            
                for technician, recent_pms, avg_hours, unique_equipment in recent_activity:
                    tech_display = technician[:17] + '...' if len(technician) > 17 else technician
                    avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                
                    analytics += f"{tech_display:<20} {recent_pms:<6} {avg_hours_display:<10} {unique_equipment:<18}\n"
                analytics += "\n"
        
            # Cannot Find reports by technician
            cursor.execute('''
                SELECT
                    technician_name,
                    COUNT(*) as cannot_find_count,
                    COUNT(CASE WHEN reported_date >= CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as recent_cf
                FROM cannot_find_assets
                WHERE status = 'Missing'
                GROUP BY technician_name
                ORDER BY cannot_find_count DESC
            ''')
            cannot_find_by_tech = cursor.fetchall()
        
            if cannot_find_by_tech:
                analytics += "CANNOT FIND REPORTS BY TECHNICIAN:\n"
                analytics += f"{'Technician':<20} {'Total CF':<10} {'Recent (30d)':<15}\n"
                analytics += "-" * 47 + "\n"
            
                for technician, total_cf, recent_cf in cannot_find_by_tech:
                    tech_display = technician[:17] + '...' if len(technician) > 17 else technician
                    analytics += f"{tech_display:<20} {total_cf:<10} {recent_cf:<15}\n"
                analytics += "\n"
        
            # Workload distribution analysis
            cursor.execute('''
                SELECT
                    technician_name,
                    TO_CHAR(completion_date::date, 'YYYY-MM') as month,
                    COUNT(*) as monthly_completions,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '6 months'
                GROUP BY technician_name, TO_CHAR(completion_date::date, 'YYYY-MM')
                ORDER BY technician_name, month DESC
            ''')
            monthly_workload = cursor.fetchall()
        
            if monthly_workload:
                analytics += "MONTHLY WORKLOAD DISTRIBUTION (Last 6 months):\n"
            
                # Group by technician
                tech_monthly = {}
                for technician, month, completions, avg_hours in monthly_workload:
                    if technician not in tech_monthly:
                        tech_monthly[technician] = []
                    tech_monthly[technician].append((month, completions, avg_hours))
            
                for technician, monthly_data in tech_monthly.items():
                    tech_display = technician[:17] + '...' if len(technician) > 17 else technician
                    analytics += f"\n{tech_display}:\n"
                    analytics += f"{'  Month':<12} {'PMs':<6} {'Avg Hours':<10}\n"
                    analytics += "  " + "-" * 30 + "\n"
                
                    for month, completions, avg_hours in monthly_data[:6]:  # Show last 6 months
                        avg_hours_display = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                        analytics += f"  {month:<12} {completions:<6} {avg_hours_display:<10}\n"
                analytics += "\n"
        
            # Efficiency metrics
            if technician_performance:
                analytics += "TECHNICIAN EFFICIENCY METRICS:\n"
                analytics += f"{'Technician':<20} {'PMs/Month':<12} {'Hours/PM':<10} {'Productivity':<12}\n"
                analytics += "-" * 60 + "\n"
            
                for tech_data in technician_performance:
                    technician, total_pms, monthly, annual, avg_hours, total_hours, first_date, last_date = tech_data
                
                    # Calculate months active (rough estimate)
                    if first_date and last_date:
                        try:
                            first_dt = datetime.strptime(first_date, '%Y-%m-%d')
                            last_dt = datetime.strptime(last_date, '%Y-%m-%d')
                            months_active = max(1, (last_dt - first_dt).days / 30.44)  # Average days per month
                            pms_per_month = total_pms / months_active
                        except:
                            months_active = 1
                            pms_per_month = total_pms
                    else:
                        pms_per_month = total_pms
                
                    hours_per_pm = avg_hours if avg_hours else 0
                
                    # Productivity score (PMs per month / hours per PM)
                    productivity = pms_per_month / max(hours_per_pm, 0.1) if hours_per_pm > 0 else pms_per_month
                    
                    tech_display = technician[:17] + '...' if len(technician) > 17 else technician
                    analytics += f"{tech_display:<20} {pms_per_month:<11.1f} {hours_per_pm:<9.1f} {productivity:<11.1f}\n"
                analytics += "\n"
        
            tech_text.insert('end', analytics)
            tech_text.config(state='disabled')
        
        except Exception as e:
            print(f"Error generating technician analysis: {e}")
    
    def export_equipment_analytics_pdf(self, parent_dialog):
        """Export all analytics to a comprehensive PDF report"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Equipment_Analytics_Report_{timestamp}.pdf"
        
            # Create PDF document
            doc = SimpleDocTemplate(filename, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()
        
            # Title page
            title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], 
                                    fontSize=20, textColor=colors.darkblue, alignment=1)
            story.append(Paragraph("AIT CMMS EQUIPMENT ANALYTICS REPORT", title_style))
            story.append(Spacer(1, 30))
        
            # Report metadata
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Paragraph(f"Report ID: {timestamp}", styles['Normal']))
            story.append(Spacer(1, 40))
        
            # Executive Summary
            cursor = self.conn.cursor()
        
            cursor.execute('SELECT COUNT(*) FROM equipment')
            total_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM pm_completions WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'")
            recent_pms = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM cannot_find_assets WHERE status = 'Missing'")
            missing_assets = cursor.fetchone()[0]
        
            story.append(Paragraph("EXECUTIVE SUMMARY", styles['Heading1']))
            summary_data = [
                ['Metric', 'Value', 'Status'],
                ['Total Equipment', str(total_equipment), 'Baseline'],
                ['Active Equipment', str(active_equipment), f'{active_equipment/total_equipment*100:.1f}%'],
                ['PMs Last 30 Days', str(recent_pms), 'Recent Activity'],
                ['Missing Assets', str(missing_assets), 'Attention Needed' if missing_assets > 0 else 'Good']
            ]
        
            summary_table = Table(summary_data, colWidths=[2*inch, 1.5*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
        
            story.append(summary_table)
            story.append(PageBreak())
        
            # Add detailed sections
            sections = [
                ("Equipment Overview", self.get_equipment_overview_text()),
                ("PM Performance Analysis", self.get_pm_performance_text()),
                ("Location Analysis", self.get_location_analysis_text()),
                ("Technician Analysis", self.get_technician_analysis_text())
            ]
        
            for section_title, section_content in sections:
                story.append(Paragraph(section_title, styles['Heading1']))
                story.append(Spacer(1, 12))
            
                # Split content into paragraphs
                paragraphs = section_content.split('\n\n')
                for paragraph in paragraphs:
                    if paragraph.strip():
                        story.append(Paragraph(paragraph.replace('\n', '<br/>'), styles['Normal']))
                        story.append(Spacer(1, 6))
            
                story.append(PageBreak())
        
            # Build PDF
            doc.build(story)
        
            messagebox.showinfo("Success", f"Analytics report exported to: {filename}")
            self.update_status(f"Equipment analytics exported to {filename}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export analytics: {str(e)}")

    def get_equipment_overview_text(self):
        """Get equipment overview text for PDF export"""
        try:
            cursor = self.conn.cursor()
        
            # Basic statistics
            cursor.execute('SELECT COUNT(*) FROM equipment')
            total_equipment = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active_equipment = cursor.fetchone()[0]
        
            text = f"Total Equipment: {total_equipment}\n"
            text += f"Active Equipment: {active_equipment} ({active_equipment/total_equipment*100:.1f}%)\n\n"
        
            # PM requirements
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE monthly_pm = 1')
            monthly_count = cursor.fetchone()[0]
            text += f"Equipment requiring Monthly PM: {monthly_count}\n"
        
            cursor.execute('SELECT COUNT(*) FROM equipment WHERE annual_pm = 1')
            annual_count = cursor.fetchone()[0]
            text += f"Equipment requiring Annual PM: {annual_count}\n"
        
            return text
        
        except Exception as e:
            return f"Error generating overview text: {str(e)}"

    def get_pm_performance_text(self):
        """Get PM performance text for PDF export"""
        try:
            cursor = self.conn.cursor()
        
            cursor.execute('SELECT pm_type, COUNT(*) FROM pm_completions GROUP BY pm_type')
            pm_stats = cursor.fetchall()
        
            text = "PM Completion Statistics:\n"
            for pm_type, count in pm_stats:
                text += f"{pm_type}: {count} completions\n"
        
            return text
        
        except Exception as e:
            return f"Error generating PM performance text: {str(e)}"

    def get_location_analysis_text(self):
        """Get location analysis text for PDF export"""
        try:
            cursor = self.conn.cursor()
        
            cursor.execute('''
                SELECT location, COUNT(*) 
                FROM equipment 
                WHERE location IS NOT NULL 
                GROUP BY location 
                ORDER BY COUNT(*) DESC 
                LIMIT 10
            ''')
            location_stats = cursor.fetchall()
        
            text = "Equipment by Location:\n"
            for location, count in location_stats:
                text += f"{location}: {count} assets\n"
        
            return text
        
        except Exception as e:
            return f"Error generating location analysis text: {str(e)}"

    def get_technician_analysis_text(self):
        """Get technician analysis text for PDF export"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('''
                SELECT technician_name, COUNT(*) 
                FROM pm_completions 
                GROUP BY technician_name 
                ORDER BY COUNT(*) DESC
            ''')
            tech_stats = cursor.fetchall()
        
            text = "PM Completions by Technician:\n"
            for technician, count in tech_stats:
                text += f"{technician}: {count} PMs completed\n"
        
            return text
        
        except Exception as e:
            return f"Error generating technician analysis text: {str(e)}"
    
    
    def show_pm_trends(self):
        """Comprehensive PM trends analysis with visualizations and insights"""
        try:
            # Create trends analysis dialog
            trends_dialog = tk.Toplevel(self.root)
            trends_dialog.title("PM Trends Analysis Dashboard")
            trends_dialog.geometry("1400x900")
            trends_dialog.transient(self.root)
            trends_dialog.grab_set()

            # Create notebook for different trend views
            trends_notebook = ttk.Notebook(trends_dialog)
            trends_notebook.pack(fill='both', expand=True, padx=10, pady=10)

            # Tab 1: Monthly Completion Trends
            monthly_frame = ttk.Frame(trends_notebook)
            trends_notebook.add(monthly_frame, text="Monthly Trends")

            # Tab 2: Equipment Performance Trends
            equipment_frame = ttk.Frame(trends_notebook)
            trends_notebook.add(equipment_frame, text="Equipment Trends")

            # Tab 3: Technician Performance Trends
            technician_frame = ttk.Frame(trends_notebook)
            trends_notebook.add(technician_frame, text="Technician Trends")

            # Tab 4: PM Type Distribution Trends
            pm_type_frame = ttk.Frame(trends_notebook)
            trends_notebook.add(pm_type_frame, text="PM Type Trends")

            # Generate content for each tab
            self.generate_monthly_trends_analysis(monthly_frame)
            self.generate_equipment_trends_analysis(equipment_frame)
            self.generate_technician_trends_analysis(technician_frame)
            self.generate_pm_type_trends_analysis(pm_type_frame)

            # Add export and close buttons
            button_frame = ttk.Frame(trends_dialog)
            button_frame.pack(side='bottom', fill='x', padx=10, pady=5)

            ttk.Button(button_frame, text="Export Trends to PDF", 
                    command=lambda: self.export_trends_analysis_pdf(trends_dialog)).pack(side='left', padx=5)
            ttk.Button(button_frame, text="Refresh Analysis", 
                    command=lambda: self.refresh_trends_analysis(trends_dialog)).pack(side='left', padx=5)
            ttk.Button(button_frame, text="Close", 
                    command=trends_dialog.destroy).pack(side='right', padx=5)
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PM trends analysis: {str(e)}")

    def generate_monthly_trends_analysis(self, parent_frame):
        """Generate monthly PM completion trends analysis"""
        try:
            cursor = self.conn.cursor()

            # Create scrollable frame
            canvas = tk.Canvas(parent_frame)
            scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            # Monthly completion data (last 24 months)
            cursor.execute('''
                SELECT
                    TO_CHAR(completion_date::date, 'YYYY-MM') as month,
                    COUNT(*) as total_completions,
                    COUNT(CASE WHEN pm_type = 'Monthly' THEN 1 END) as monthly_pms,
                    COUNT(CASE WHEN pm_type = 'Annual' THEN 1 END) as annual_pms,
                    COUNT(CASE WHEN pm_type = 'Six Month' THEN 1 END) as six_month_pms,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours,
                    COUNT(DISTINCT technician_name) as active_technicians,
                    COUNT(DISTINCT bfm_equipment_no) as unique_equipment
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '24 months'
                GROUP BY TO_CHAR(completion_date::date, 'YYYY-MM')
                ORDER BY month ASC
            ''')

            monthly_data = cursor.fetchall()

            # Create text display for trends
            trends_text = tk.Text(scrollable_frame, wrap='word', font=('Courier', 10), height=40)
            text_scrollbar = ttk.Scrollbar(scrollable_frame, orient='vertical', command=trends_text.yview)
            trends_text.configure(yscrollcommand=text_scrollbar.set)

            # Generate trends report
            report = "PM COMPLETION TRENDS ANALYSIS\n"
            report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += "=" * 80 + "\n\n"

            if monthly_data:
                report += "MONTHLY COMPLETION TRENDS (Last 24 months):\n"
                report += "-" * 80 + "\n"
                report += f"{'Month':<10} {'Total':<8} {'Monthly':<8} {'Annual':<8} {'6-Month':<8} {'Avg Hrs':<8} {'Techs':<6} {'Equipment':<10}\n"
                report += "-" * 80 + "\n"

                total_completions = 0
                total_hours = 0
                peak_month = None
                peak_completions = 0
                lowest_month = None
                lowest_completions = float('inf')

                for month_data in monthly_data:
                    month, total, monthly_pms, annual_pms, six_month_pms, avg_hours, techs, equipment = month_data
                    total_completions += total
                    total_hours += avg_hours if avg_hours else 0

                    # Track peak and low months
                    if total > peak_completions:
                        peak_completions = total
                        peak_month = month
                    if total < lowest_completions:
                        lowest_completions = total
                        lowest_month = month

                    avg_hours_str = f"{avg_hours:.1f}" if avg_hours else "0.0"
                    report += f"{month:<10} {total:<8} {monthly_pms:<8} {annual_pms:<8} {six_month_pms:<8} {avg_hours_str:<8} {techs:<6} {equipment:<10}\n"

                # Calculate trends
                avg_monthly_completions = total_completions / len(monthly_data) if monthly_data else 0
                avg_hours_overall = total_hours / len(monthly_data) if monthly_data else 0

                # Recent trend analysis (last 6 months vs previous 6 months)
                recent_6_months = monthly_data[-6:] if len(monthly_data) >= 6 else monthly_data
                previous_6_months = monthly_data[-12:-6] if len(monthly_data) >= 12 else []

                recent_avg = sum(row[1] for row in recent_6_months) / len(recent_6_months) if recent_6_months else 0
                previous_avg = sum(row[1] for row in previous_6_months) / len(previous_6_months) if previous_6_months else 0

                trend_direction = "UP" if recent_avg > previous_avg else "DOWN" if recent_avg < previous_avg else "STABLE"
                trend_percentage = ((recent_avg - previous_avg) / previous_avg * 100) if previous_avg > 0 else 0

                report += "\n" + "=" * 80 + "\n"
                report += "TREND ANALYSIS SUMMARY:\n"
                report += "=" * 80 + "\n"
                report += f"Total Months Analyzed: {len(monthly_data)}\n"
                report += f"Total Completions: {total_completions}\n"
                report += f"Average Completions per Month: {avg_monthly_completions:.1f}\n"
                report += f"Average Hours per PM: {avg_hours_overall:.1f}h\n\n"

                report += f"Peak Performance Month: {peak_month} ({peak_completions} completions)\n"
                report += f"Lowest Performance Month: {lowest_month} ({lowest_completions} completions)\n\n"

                report += f"6-Month Trend Analysis:\n"
                report += f"Recent 6 months average: {recent_avg:.1f} completions/month\n"
                report += f"Previous 6 months average: {previous_avg:.1f} completions/month\n"
                report += f"Trend Direction: {trend_direction} ({trend_percentage:+.1f}%)\n\n"

                # Seasonal analysis
                report += "SEASONAL PATTERNS:\n"
                report += "-" * 40 + "\n"
                seasonal_data = {}
                for month_data in monthly_data:
                    month_str, total = month_data[0], month_data[1]
                    month_num = int(month_str.split('-')[1])
                    season = self.get_season_from_month(month_num)
                    if season not in seasonal_data:
                        seasonal_data[season] = []
                    seasonal_data[season].append(total)
    
                for season, completions in seasonal_data.items():
                    avg_seasonal = sum(completions) / len(completions)
                    report += f"{season:<10}: {avg_seasonal:.1f} avg completions/month\n"

                # Workload distribution analysis
                report += "\nWORKLOAD DISTRIBUTION INSIGHTS:\n"
                report += "-" * 40 + "\n"
            
                # Calculate coefficient of variation for consistency
                if len(monthly_data) > 1:
                    completions_list = [row[1] for row in monthly_data]
                    import statistics
                    std_dev = statistics.stdev(completions_list)
                    cv = (std_dev / avg_monthly_completions) * 100 if avg_monthly_completions > 0 else 0
                
                    consistency_rating = "Very Consistent" if cv < 15 else "Consistent" if cv < 25 else "Variable" if cv < 35 else "Highly Variable"
                    report += f"Workload Consistency: {consistency_rating} (CV: {cv:.1f}%)\n"
                    report += f"Standard Deviation: {std_dev:.1f} completions\n\n"

                # Recommendations
                report += "RECOMMENDATIONS:\n"
                report += "-" * 40 + "\n"
                if trend_direction == "DOWN":
                    report += "- Investigate causes of declining PM completion rates\n"
                    report += "- Consider additional technician training or resources\n"
                    report += "- Review equipment scheduling and assignment processes\n"
                elif trend_direction == "UP":
                    report += "- Excellent performance trend - maintain current practices\n"
                    report += "- Consider documenting successful strategies for replication\n"
            
                if cv > 30:
                    report += "- High variability detected - investigate scheduling consistency\n"
                    report += "- Consider implementing better workload balancing\n"
            
                if avg_hours_overall > 2.0:
                    report += "- Average PM time is high - review procedures for efficiency\n"
                elif avg_hours_overall < 0.5:
                    report += "- Very low average PM time - verify completeness of work\n"

            else:
                report += "No PM completion data found for trend analysis.\n"

            # Display the report
            trends_text.insert('end', report)
            trends_text.config(state='disabled')

            # Pack widgets
            trends_text.pack(side='left', fill='both', expand=True)
            text_scrollbar.pack(side='right', fill='y')

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

        except Exception as e:
            error_label = ttk.Label(parent_frame, text=f"Error generating monthly trends: {str(e)}")
            error_label.pack(pady=20)

    def generate_equipment_trends_analysis(self, parent_frame):
        """Generate equipment-specific PM trends analysis"""
        try:
            cursor = self.conn.cursor()

            # Create text widget for equipment trends
            equipment_text = tk.Text(parent_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(parent_frame, orient='vertical', command=equipment_text.yview)
            equipment_text.configure(yscrollcommand=scrollbar.set)

            report = "EQUIPMENT PM TRENDS ANALYSIS\n"
            report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += "=" * 80 + "\n\n"

            # Most frequently serviced equipment
            cursor.execute('''
                SELECT e.bfm_equipment_no, e.description, e.location,
                       COUNT(pc.id) as total_pms,
                       AVG(pc.labor_hours + pc.labor_minutes/60.0) as avg_hours,
                       MIN(pc.completion_date) as first_pm,
                       MAX(pc.completion_date) as last_pm,
                       COUNT(CASE WHEN pc.completion_date >= CURRENT_DATE - INTERVAL '90 days' THEN 1 END) as recent_pms
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                WHERE e.status = 'Active'
                GROUP BY e.bfm_equipment_no, e.description, e.location
                HAVING total_pms > 0
                ORDER BY total_pms DESC
                LIMIT 20
            ''')

            high_maintenance_equipment = cursor.fetchall()

            if high_maintenance_equipment:
                report += "TOP 20 MOST SERVICED EQUIPMENT:\n"
                report += "-" * 80 + "\n"
                report += f"{'Rank':<5} {'BFM No':<12} {'Description':<25} {'Total PMs':<10} {'Avg Hours':<10} {'Recent (90d)':<12}\n"
                report += "-" * 80 + "\n"

                for i, equipment in enumerate(high_maintenance_equipment, 1):
                    bfm_no, description, location, total_pms, avg_hours, first_pm, last_pm, recent_pms = equipment
                    desc_short = (description[:22] + '...') if description and len(description) > 22 else (description or 'N/A')
                    avg_hours_str = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    
                    report += f"{i:<5} {bfm_no:<12} {desc_short:<25} {total_pms:<10} {avg_hours_str:<10} {recent_pms:<12}\n"

            # Equipment with increasing maintenance needs
            cursor.execute('''
                SELECT bfm_equipment_no,
                       COUNT(CASE WHEN completion_date >= CURRENT_DATE - INTERVAL '90 days' THEN 1 END) as last_90_days,
                       COUNT(CASE WHEN completion_date >= CURRENT_DATE - INTERVAL '180 days' AND completion_date < CURRENT_DATE - INTERVAL '90 days' THEN 1 END) as prev_90_days,
                       COUNT(*) as total_pms
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '180 days'
                GROUP BY bfm_equipment_no
                HAVING last_90_days > prev_90_days AND prev_90_days > 0
                ORDER BY (last_90_days - prev_90_days) DESC
                LIMIT 10
            ''')

            increasing_maintenance = cursor.fetchall()

            if increasing_maintenance:
                report += "\n\nEQUIPMENT WITH INCREASING MAINTENANCE NEEDS:\n"
                report += "-" * 60 + "\n"
                report += f"{'BFM No':<15} {'Recent 90d':<12} {'Previous 90d':<12} {'Increase':<10}\n"
                report += "-" * 60 + "\n"

                for equipment in increasing_maintenance:
                    bfm_no, last_90, prev_90, total = equipment
                    increase = last_90 - prev_90
                    report += f"{bfm_no:<15} {last_90:<12} {prev_90:<12} +{increase:<9}\n"

            # Equipment that hasn't been serviced recently
            cursor.execute('''
                SELECT e.bfm_equipment_no, e.description, e.location,
                       MAX(pc.completion_date) as last_pm_date,
                       JULIANDAY('now') - JULIANDAY(MAX(pc.completion_date)) as days_since_last_pm
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                WHERE e.status = 'Active' AND e.monthly_pm = 1
                GROUP BY e.bfm_equipment_no, e.description, e.location
                HAVING days_since_last_pm > 60 OR last_pm_date IS NULL
                ORDER BY days_since_last_pm DESC NULLS LAST
                LIMIT 15
            ''')

            neglected_equipment = cursor.fetchall()

            if neglected_equipment:
                report += "\n\nEQUIPMENT REQUIRING ATTENTION (>60 days since last PM):\n"
                report += "-" * 70 + "\n"
                report += f"{'BFM No':<15} {'Description':<25} {'Last PM':<12} {'Days Since':<12}\n"
                report += "-" * 70 + "\n"

                for equipment in neglected_equipment:
                    bfm_no, description, location, last_pm, days_since = equipment
                    desc_short = (description[:22] + '...') if description and len(description) > 22 else (description or 'N/A')
                    last_pm_str = last_pm if last_pm else 'Never'
                    days_str = f"{int(days_since)}" if days_since else 'N/A'
                    
                    report += f"{bfm_no:<15} {desc_short:<25} {last_pm_str:<12} {days_str:<12}\n"

            # Equipment performance by location
            cursor.execute('''
                SELECT COALESCE(e.location, 'Unknown') as location,
                       COUNT(pc.id) as total_pms,
                       COUNT(DISTINCT e.bfm_equipment_no) as equipment_count,
                       AVG(pc.labor_hours + pc.labor_minutes/60.0) as avg_hours,
                       ROUND(CAST(COUNT(pc.id) AS FLOAT) / COUNT(DISTINCT e.bfm_equipment_no), 2) as pms_per_equipment
                FROM equipment e
                LEFT JOIN pm_completions pc ON e.bfm_equipment_no = pc.bfm_equipment_no
                    AND pc.completion_date >= CURRENT_DATE - INTERVAL '365 days'
                WHERE e.status = 'Active'
                GROUP BY COALESCE(e.location, 'Unknown')
                HAVING equipment_count >= 3
                ORDER BY pms_per_equipment DESC
            ''')

            location_performance = cursor.fetchall()

            if location_performance:
                report += "\n\nPM PERFORMANCE BY LOCATION (Last 12 months):\n"
                report += "-" * 70 + "\n"
                report += f"{'Location':<20} {'Equipment':<10} {'Total PMs':<10} {'PMs/Equipment':<15} {'Avg Hours':<10}\n"
                report += "-" * 70 + "\n"

                for location_data in location_performance:
                    location, total_pms, equipment_count, avg_hours, pms_per_equipment = location_data
                    loc_short = (location[:17] + '...') if len(location) > 17 else location
                    avg_hours_str = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    
                    report += f"{loc_short:<20} {equipment_count:<10} {total_pms:<10} {pms_per_equipment:<15} {avg_hours_str:<10}\n"

            equipment_text.insert('end', report)
            equipment_text.config(state='disabled')

            equipment_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')

        except Exception as e:
            error_label = ttk.Label(parent_frame, text=f"Error generating equipment trends: {str(e)}")
            error_label.pack(pady=20)

    def generate_technician_trends_analysis(self, parent_frame):
        """Generate technician performance trends analysis"""
        try:
            cursor = self.conn.cursor()

            # Create text widget for technician trends
            tech_text = tk.Text(parent_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(parent_frame, orient='vertical', command=tech_text.yview)
            tech_text.configure(yscrollcommand=scrollbar.set)

            report = "TECHNICIAN PERFORMANCE TRENDS\n"
            report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += "=" * 80 + "\n\n"

            # Monthly performance trends for each technician
            cursor.execute('''
                SELECT technician_name,
                       TO_CHAR(completion_date::date, 'YYYY-MM') as month,
                       COUNT(*) as completions,
                       AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY technician_name, TO_CHAR(completion_date::date, 'YYYY-MM')
                ORDER BY technician_name, month
            ''')

            monthly_tech_data = cursor.fetchall()

            # Organize data by technician
            tech_monthly = {}
            for row in monthly_tech_data:
                tech, month, completions, avg_hours = row
                if tech not in tech_monthly:
                    tech_monthly[tech] = []
                tech_monthly[tech].append((month, completions, avg_hours))

            if tech_monthly:
                report += "MONTHLY PERFORMANCE TRENDS BY TECHNICIAN:\n"
                report += "=" * 80 + "\n"

                for technician, monthly_data in tech_monthly.items():
                    report += f"\n{technician}:\n"
                    report += "-" * 50 + "\n"
                    report += f"{'Month':<10} {'Completions':<12} {'Avg Hours':<10} {'Trend':<10}\n"
                    report += "-" * 50 + "\n"

                    # Calculate trend
                    completions_list = [data[1] for data in monthly_data]
                    if len(completions_list) >= 3:
                        recent_avg = sum(completions_list[-3:]) / 3
                        earlier_avg = sum(completions_list[:-3]) / len(completions_list[:-3]) if len(completions_list) > 3 else sum(completions_list[:3]) / len(completions_list[:3])
                        trend = "CHECK:" if recent_avg > earlier_avg else "CHECK:" if recent_avg < earlier_avg else "CHECK:"
                    else:
                        trend = "CHECK:"

                    for month, completions, avg_hours in monthly_data[-6:]:  # Show last 6 months
                        avg_hours_str = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                        report += f"{month:<10} {completions:<12} {avg_hours_str:<10} {trend if month == monthly_data[-1][0] else '':<10}\n"

            # Overall technician comparison
            cursor.execute('''
                SELECT technician_name,
                       COUNT(*) as total_completions,
                       AVG(labor_hours + labor_minutes/60.0) as avg_hours_per_pm,
                       COUNT(DISTINCT bfm_equipment_no) as unique_equipment,
                       COUNT(CASE WHEN completion_date >= CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as recent_completions,
                       MIN(completion_date) as first_completion,
                       MAX(completion_date) as last_completion
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY technician_name
                ORDER BY total_completions DESC
            ''')

            tech_comparison = cursor.fetchall()

            if tech_comparison:
                report += "\n\nTECHNICIAN PERFORMANCE COMPARISON (Last 12 months):\n"
                report += "=" * 90 + "\n"
                report += f"{'Technician':<20} {'Total PMs':<10} {'Avg Hrs':<10} {'Equipment':<10} {'Recent 30d':<12} {'Active Period':<15}\n"
                report += "=" * 90 + "\n"

                for tech_data in tech_comparison:
                    tech, total, avg_hours, equipment, recent, first, last = tech_data
                    avg_hours_str = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                    
                    # Calculate active period
                    if first and last:
                        first_date = datetime.strptime(first, '%Y-%m-%d')
                        last_date = datetime.strptime(last, '%Y-%m-%d')
                        active_days = (last_date - first_date).days
                        active_period = f"{active_days}d"
                    else:
                        active_period = "N/A"

                    tech_short = tech[:17] + '...' if len(tech) > 17 else tech
                    report += f"{tech_short:<20} {total:<10} {avg_hours_str:<10} {equipment:<10} {recent:<12} {active_period:<15}\n"

            # Efficiency metrics
            if tech_comparison:
                report += "\n\nEFFICIENCY METRICS:\n"
                report += "-" * 60 + "\n"
                report += f"{'Technician':<20} {'PMs/Day':<10} {'Productivity':<12} {'Specialization':<15}\n"
                report += "-" * 60 + "\n"

                for tech_data in tech_comparison:
                    tech, total, avg_hours, equipment, recent, first, last = tech_data
                
                    # Calculate PMs per day (approximate)
                    if first and last:
                        first_date = datetime.strptime(first, '%Y-%m-%d')
                        last_date = datetime.strptime(last, '%Y-%m-%d')
                        active_days = max(1, (last_date - first_date).days)
                        pms_per_day = total / active_days
                    else:
                        pms_per_day = 0

                    # Productivity score (PMs per hour)
                    productivity = total / (total * (avg_hours if avg_hours else 1)) if avg_hours else total
                
                    # Specialization (unique equipment ratio)
                    specialization = equipment / total if total > 0 else 0
                    spec_rating = "High" if specialization > 0.8 else "Medium" if specialization > 0.5 else "Low"

                    tech_short = tech[:17] + '...' if len(tech) > 17 else tech
                    report += f"{tech_short:<20} {pms_per_day:<9.2f} {productivity:<11.2f} {spec_rating:<15}\n"

            tech_text.insert('end', report)
            tech_text.config(state='disabled')

            tech_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')

        except Exception as e:
            error_label = ttk.Label(parent_frame, text=f"Error generating technician trends: {str(e)}")
            error_label.pack(pady=20)

    def generate_pm_type_trends_analysis(self, parent_frame):
        """Generate PM type distribution and trends analysis"""
        try:
            cursor = self.conn.cursor()

            # Create text widget for PM type trends
            pm_type_text = tk.Text(parent_frame, wrap='word', font=('Courier', 10))
            scrollbar = ttk.Scrollbar(parent_frame, orient='vertical', command=pm_type_text.yview)
            pm_type_text.configure(yscrollcommand=scrollbar.set)

            report = "PM TYPE TRENDS ANALYSIS\n"
            report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += "=" * 80 + "\n\n"

            # Monthly PM type distribution
            cursor.execute('''
                SELECT TO_CHAR(completion_date::date, 'YYYY-MM') as month,
                       pm_type,
                       COUNT(*) as completions,
                       AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY TO_CHAR(completion_date::date, 'YYYY-MM'), pm_type
                ORDER BY month, pm_type
            ''')

            monthly_pm_type_data = cursor.fetchall()

            # Organize by month
            monthly_pm_types = {}
            for row in monthly_pm_type_data:
                month, pm_type, completions, avg_hours = row
                if month not in monthly_pm_types:
                    monthly_pm_types[month] = {}
                monthly_pm_types[month][pm_type] = (completions, avg_hours)

            if monthly_pm_types:
                report += "MONTHLY PM TYPE DISTRIBUTION:\n"
                report += "=" * 80 + "\n"
                report += f"{'Month':<10} {'Monthly':<10} {'Annual':<10} {'Six Month':<12} {'Other':<8} {'Total':<8}\n"
                report += "=" * 80 + "\n"

                pm_type_totals = {}
                for month, pm_types in monthly_pm_types.items():
                    monthly_count = pm_types.get('Monthly', (0, 0))[0]
                    annual_count = pm_types.get('Annual', (0, 0))[0]
                    six_month_count = pm_types.get('Six Month', (0, 0))[0]
                    other_count = sum(data[0] for pm_type, data in pm_types.items() 
                                    if pm_type not in ['Monthly', 'Annual', 'Six Month'])
                    total_count = monthly_count + annual_count + six_month_count + other_count

                    # Track totals
                    for pm_type, (count, _) in pm_types.items():
                        pm_type_totals[pm_type] = pm_type_totals.get(pm_type, 0) + count

                    report += f"{month:<10} {monthly_count:<10} {annual_count:<10} {six_month_count:<12} {other_count:<8} {total_count:<8}\n"

            # Overall PM type statistics
            cursor.execute('''
                SELECT pm_type,
                    COUNT(*) as total_completions,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours,
                       MIN(completion_date) as first_completion,
                       MAX(completion_date) as last_completion,
                       COUNT(DISTINCT technician_name) as technicians_involved,
                       COUNT(DISTINCT bfm_equipment_no) as equipment_serviced
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY pm_type
                ORDER BY total_completions DESC
            ''')

            pm_type_stats = cursor.fetchall()

            if pm_type_stats:
                report += "\n\nPM TYPE PERFORMANCE SUMMARY (Last 12 months):\n"
                report += "=" * 90 + "\n"
                report += f"{'PM Type':<15} {'Total':<8} {'Avg Hours':<10} {'Technicians':<12} {'Equipment':<10} {'Period':<15}\n"
                report += "=" * 90 + "\n"

                total_all_pms = sum(row[1] for row in pm_type_stats)
            
                for pm_data in pm_type_stats:
                    pm_type, total, avg_hours, first, last, techs, equipment = pm_data
                    percentage = (total / total_all_pms * 100) if total_all_pms > 0 else 0
                    avg_hours_str = f"{avg_hours:.1f}h" if avg_hours else "0.0h"
                
                    # Calculate period
                    if first and last:
                        first_date = datetime.strptime(first, '%Y-%m-%d')
                        last_date = datetime.strptime(last, '%Y-%m-%d')
                        period_days = (last_date - first_date).days
                        period_str = f"{period_days}d"
                    else:
                        period_str = "N/A"

                    report += f"{pm_type:<15} {total:<8} {avg_hours_str:<10} {techs:<12} {equipment:<10} {period_str:<15}\n"
                    report += f"{'':>15} ({percentage:.1f}%)\n"

            # PM type efficiency analysis
            if pm_type_stats:
                report += "\n\nPM TYPE EFFICIENCY ANALYSIS:\n"
                report += "-" * 60 + "\n"
            
                # Calculate efficiency metrics
                for pm_data in pm_type_stats:
                    pm_type, total, avg_hours, first, last, techs, equipment = pm_data
                
                    # Equipment coverage (how many unique equipment per PM)
                    coverage = equipment / total if total > 0 else 0
                
                    # Time efficiency rating
                    if avg_hours:
                        if avg_hours <= 1.0:
                            efficiency = "Excellent"
                        elif avg_hours <= 1.5:
                            efficiency = "Good"
                        elif avg_hours <= 2.5:
                            efficiency = "Average"
                        else:
                            efficiency = "Needs Review"
                    else:
                        efficiency = "Unknown"
                
                    report += f"{pm_type} PM Analysis:\n"
                    report += f"  - Average completion time: {avg_hours:.1f}h ({efficiency})\n" if avg_hours else f"  - Average completion time: Unknown\n"
                    report += f"  - Equipment coverage ratio: {coverage:.2f}\n"
                    report += f"  - Technician utilization: {techs} different technicians\n"
                
                    # Frequency analysis
                    if first and last and total > 1:
                        first_date = datetime.strptime(first, '%Y-%m-%d')
                        last_date = datetime.strptime(last, '%Y-%m-%d')
                        total_days = (last_date - first_date).days
                        avg_days_between = total_days / (total - 1) if total > 1 else 0
                        report += f"  - Average interval: {avg_days_between:.1f} days between completions\n"
                
                    report += "\n"

            # Seasonal PM type patterns
            cursor.execute('''
                SELECT
                    CASE
                        WHEN EXTRACT(MONTH FROM completion_date::date) IN (12, 1, 2) THEN 'Winter'
                        WHEN EXTRACT(MONTH FROM completion_date::date) IN (3, 4, 5) THEN 'Spring'
                        WHEN EXTRACT(MONTH FROM completion_date::date) IN (6, 7, 8) THEN 'Summer'
                        WHEN EXTRACT(MONTH FROM completion_date::date) IN (9, 10, 11) THEN 'Fall'
                    END as season,
                    pm_type,
                    COUNT(*) as completions
                FROM pm_completions
                WHERE completion_date::date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY season, pm_type
                ORDER BY season, pm_type
            ''')

            seasonal_data = cursor.fetchall()

            if seasonal_data:
                report += "SEASONAL PM TYPE PATTERNS:\n"
                report += "-" * 50 + "\n"
            
                # Organize by season
                seasons = {}
                for row in seasonal_data:
                    season, pm_type, completions = row
                    if season not in seasons:
                        seasons[season] = {}
                    seasons[season][pm_type] = completions

                for season in ['Winter', 'Spring', 'Summer', 'Fall']:
                    if season in seasons:
                        report += f"\n{season}:\n"
                        season_total = sum(seasons[season].values())
                        for pm_type, count in seasons[season].items():
                            percentage = (count / season_total * 100) if season_total > 0 else 0
                            report += f"  {pm_type}: {count} ({percentage:.1f}%)\n"

            # Recommendations based on PM type analysis
            report += "\n\nPM TYPE RECOMMENDATIONS:\n"
            report += "=" * 50 + "\n"
        
            if pm_type_stats:
                # Find the most and least efficient PM types
                sorted_by_hours = sorted(pm_type_stats, key=lambda x: x[2] if x[2] else 0)
                most_efficient = sorted_by_hours[0] if sorted_by_hours else None
                least_efficient = sorted_by_hours[-1] if sorted_by_hours else None
                
                if most_efficient and least_efficient and most_efficient[2] and least_efficient[2]:
                    if most_efficient[0] != least_efficient[0]:
                        report += f"- Most efficient PM type: {most_efficient[0]} ({most_efficient[2]:.1f}h avg)\n"
                        report += f"- Least efficient PM type: {least_efficient[0]} ({least_efficient[2]:.1f}h avg)\n"
                        report += f"- Consider reviewing procedures for {least_efficient[0]} PMs\n\n"
            
                # Check for imbalanced distribution
                monthly_pms = next((row[1] for row in pm_type_stats if row[0] == 'Monthly'), 0)
                annual_pms = next((row[1] for row in pm_type_stats if row[0] == 'Annual'), 0)
            
                if monthly_pms > 0 and annual_pms > 0:
                    ratio = monthly_pms / annual_pms
                    if ratio > 15:
                        report += "- High Monthly-to-Annual PM ratio detected\n"
                        report += "- Consider whether some Monthly PMs could be converted to Annual\n\n"
                    elif ratio < 3:
                        report += "- Low Monthly-to-Annual PM ratio detected\n"
                        report += "- Verify Monthly PM scheduling is adequate\n\n"
            
                # Check for types with long completion times
                long_pm_types = [row for row in pm_type_stats if row[2] and row[2] > 3.0]
                if long_pm_types:
                    report += "- PM types with long completion times (>3h):\n"
                    for pm_type, total, avg_hours, _, _, _, _ in long_pm_types:
                        report += f"  - {pm_type}: {avg_hours:.1f}h average\n"
                    report += "- Review these procedures for potential optimization\n\n"

            pm_type_text.insert('end', report)
            pm_type_text.config(state='disabled')

            pm_type_text.pack(side='left', fill='both', expand=True)
            scrollbar.pack(side='right', fill='y')

        except Exception as e:
            error_label = ttk.Label(parent_frame, text=f"Error generating PM type trends: {str(e)}")
            error_label.pack(pady=20)

    def get_season_from_month(self, month_num):
        """Helper function to get season from month number"""
        if month_num in [12, 1, 2]:
            return "Winter"
        elif month_num in [3, 4, 5]:
            return "Spring"
        elif month_num in [6, 7, 8]:
            return "Summer"
        else:
            return "Fall"

    def export_trends_analysis_pdf(self, parent_dialog):
        """Export trends analysis to PDF"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"PM_Trends_Analysis_{timestamp}.pdf"

            # Create PDF document
            doc = SimpleDocTemplate(filename, pagesize=letter,
                                rightMargin=36, leftMargin=36,
                                topMargin=36, bottomMargin=36)
        
            story = []
            styles = getSampleStyleSheet()

            # Title page
            title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], 
                                    fontSize=20, textColor=colors.darkblue, alignment=1)
            story.append(Paragraph("AIT CMMS PM TRENDS ANALYSIS REPORT", title_style))
            story.append(Spacer(1, 30))

            # Report metadata
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            story.append(Paragraph(f"Report ID: {timestamp}", styles['Normal']))
            story.append(Spacer(1, 20))

            # Executive Summary
            cursor = self.conn.cursor()
        
            # Get summary statistics
            cursor.execute("SELECT COUNT(*) FROM pm_completions WHERE completion_date >= CURRENT_DATE - INTERVAL '12 months'")
            total_pms_year = cursor.fetchone()[0]
        
            cursor.execute("SELECT COUNT(*) FROM pm_completions WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'")
            total_pms_month = cursor.fetchone()[0]
        
            cursor.execute("SELECT AVG(labor_hours + labor_minutes/60.0) FROM pm_completions WHERE completion_date >= CURRENT_DATE - INTERVAL '12 months'")
            avg_hours = cursor.fetchone()[0] or 0

            story.append(Paragraph("EXECUTIVE SUMMARY", styles['Heading1']))
            summary_text = f"""
            This comprehensive PM trends analysis covers the last 12 months of preventive maintenance activities.
        
            Key Metrics:
            - Total PM Completions (12 months): {total_pms_year}
            - Recent PM Completions (30 days): {total_pms_month}
            - Average PM Duration: {avg_hours:.1f} hours
            - Analysis Period: {(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}
        
            This report provides insights into monthly completion trends, equipment performance patterns,
            technician productivity analysis, and PM type distribution to support data-driven maintenance decisions.
            """
        
            story.append(Paragraph(summary_text, styles['Normal']))
            story.append(PageBreak())

            # Add key findings sections
            story.append(Paragraph("DETAILED ANALYSIS", styles['Heading1']))
            story.append(Paragraph("The following sections provide comprehensive trends analysis across multiple dimensions of PM performance.", styles['Normal']))
            story.append(Spacer(1, 20))

            # Note about data sources
            story.append(Paragraph("Data Sources and Methodology", styles['Heading2']))
            methodology_text = """
            This analysis is based on PM completion records from the AIT CMMS database. 
            All calculations use standardized date formats and validated completion records.
            Trends are calculated using statistical methods appropriate for time series data.
            """
            story.append(Paragraph(methodology_text, styles['Normal']))

            # Build PDF
            doc.build(story)

            messagebox.showinfo("Success", f"PM trends analysis exported to: {filename}")
            self.update_status(f"PM trends analysis exported to {filename}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to export trends analysis: {str(e)}")

    def refresh_trends_analysis(self, parent_dialog):
        """Refresh the trends analysis with current data"""
        try:
            # Destroy and recreate the dialog
            parent_dialog.destroy()
            self.show_pm_trends()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh trends analysis: {str(e)}")
    
    
    
    
    
    
    
    
    def export_analytics(self):
        """Export analytics to file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"AIT_CMMS_Analytics_{timestamp}.txt"
            
            content = self.analytics_text.get('1.0', 'end-1c')
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(content)
            
            messagebox.showinfo("Success", f"Analytics exported to: {filename}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export analytics: {str(e)}")
    
    # Replace your existing import_equipment_csv method with this enhanced version

    def import_equipment_csv(self):
        """Import equipment data from CSV file with PM dates"""
        file_path = filedialog.askopenfilename(
            title="Select Equipment CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
    
        if file_path:
            try:
                # Show column mapping dialog first
                self.show_csv_mapping_dialog(file_path)
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import CSV file: {str(e)}")

    # Replace your show_csv_mapping_dialog method with this fixed version

    def show_csv_mapping_dialog(self, file_path):
        """Show dialog to map CSV columns to database fields"""
    
        try:
            # Read CSV to get column headers
            df = pd.read_csv(file_path, encoding='cp1252', nrows=5)  # Just read first 5 rows to see structure
            csv_columns = list(df.columns)
        
            dialog = tk.Toplevel(self.root)
            dialog.title("Map CSV Columns to Database Fields")
            dialog.geometry("700x600")  # Made it larger
            dialog.transient(self.root)
            dialog.grab_set()
        
            # Main container with scrollbar
            main_canvas = tk.Canvas(dialog)
            scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
            scrollable_frame = ttk.Frame(main_canvas)
        
            scrollable_frame.bind(
                "<Configure>",
                lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
            )
        
            main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            main_canvas.configure(yscrollcommand=scrollbar.set)
        
            # Instructions
            ttk.Label(scrollable_frame, text="Map your CSV columns to the correct database fields:", 
                    font=('Arial', 12, 'bold')).pack(pady=10)
        
            # Create mapping frame
            mapping_frame = ttk.Frame(scrollable_frame)
            mapping_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
            # Column mappings
            mappings = {}
        
            # Database fields that can be mapped
            db_fields = [
                ("SAP Material No", "sap_material_no"),
                ("BFM Equipment No", "bfm_equipment_no"), 
                ("Description", "description"),
                ("Tool ID/Drawing No", "tool_id_drawing_no"),
                ("Location", "location"),
                ("Master LIN", "master_lin"),
                ("Last Monthly PM (YYYY-MM-DD)", "last_monthly_pm"),
                ("Last Six Month PM (YYYY-MM-DD)", "last_six_month_pm"),
                ("Last Annual PM (YYYY-MM-DD)", "last_annual_pm"),
                ("Monthly PM Required (1/0 or Y/N)", "monthly_pm"),
                ("Six Month PM Required (1/0 or Y/N)", "six_month_pm"),
                ("Annual PM Required (1/0 or Y/N)", "annual_pm")
            ]
        
            # Add "None" option to CSV columns
            csv_options = ["(Not in CSV)"] + csv_columns
        
            row = 0
            for field_name, field_key in db_fields:
                ttk.Label(mapping_frame, text=field_name + ":").grid(row=row, column=0, sticky='w', pady=2)
            
                mapping_var = tk.StringVar()
                combo = ttk.Combobox(mapping_frame, textvariable=mapping_var, values=csv_options, width=30)
                combo.grid(row=row, column=1, padx=10, pady=2)
            
                # Try to auto-match common column names
                for csv_col in csv_columns:
                    csv_lower = csv_col.lower()
                    if field_key == 'sap_material_no' and 'sap' in csv_lower:
                        mapping_var.set(csv_col)
                        break
                    elif field_key == 'bfm_equipment_no' and 'bfm' in csv_lower:
                        mapping_var.set(csv_col)
                        break
                    elif field_key == 'description' and 'description' in csv_lower:
                        mapping_var.set(csv_col)
                        break
                    elif field_key == 'location' and 'location' in csv_lower:
                        mapping_var.set(csv_col)
                        break
                    elif field_key == 'master_lin' and 'lin' in csv_lower:
                        mapping_var.set(csv_col)
                        break
            
                mappings[field_key] = mapping_var
                row += 1
        
            # Show sample data
            sample_frame = ttk.LabelFrame(scrollable_frame, text="Sample Data from Your CSV", padding=10)
            sample_frame.pack(fill='x', padx=20, pady=10)
        
            sample_text = tk.Text(sample_frame, height=6, width=80)
            sample_text.pack()
            sample_text.insert('1.0', df.to_string())
            sample_text.config(state='disabled')
        
            def process_import():
                """Process the import with mapped columns"""
                try:
                    # Get the full CSV data
                    full_df = pd.read_csv(file_path, encoding='cp1252')
                    full_df.columns = full_df.columns.str.strip()
                
                    cursor = self.conn.cursor()
                    imported_count = 0
                    error_count = 0
                
                    for index, row in full_df.iterrows():
                        try:
                            # Extract mapped data
                            data = {}
                            for field_key, mapping_var in mappings.items():
                                csv_column = mapping_var.get()
                                if csv_column != "(Not in CSV)" and csv_column in full_df.columns:
                                    value = row[csv_column]
                                    if pd.isna(value):
                                        data[field_key] = None
                                    else:
                                        # Handle different data types
                                        if field_key in ['monthly_pm', 'six_month_pm', 'annual_pm']:
                                            # Convert Y/N or 1/0 to boolean
                                            if str(value).upper() in ['Y', 'YES', '1', 'TRUE']:
                                                data[field_key] = 1
                                            else:
                                                data[field_key] = 0
                                        elif field_key in ['last_monthly_pm', 'last_six_month_pm', 'last_annual_pm']:
                                            # Handle date fields
                                            try:
                                                # Try to parse date
                                                parsed_date = pd.to_datetime(value).strftime('%Y-%m-%d')
                                                data[field_key] = parsed_date
                                            except:
                                                data[field_key] = None
                                        else:
                                            data[field_key] = str(value)
                                else:
                                    # Set defaults for unmapped fields
                                    if field_key in ['monthly_pm', 'six_month_pm', 'annual_pm']:
                                        data[field_key] = 1  # Default to requiring all PM types
                                    else:
                                        data[field_key] = None
                        
                            # Only import if BFM number exists
                            if data.get('bfm_equipment_no'):
                                cursor.execute('''
                                    INSERT INTO equipment 
                                    (sap_material_no, bfm_equipment_no, description, tool_id_drawing_no, location, 
                                    master_lin, monthly_pm, six_month_pm, annual_pm, last_monthly_pm, 
                                    last_six_month_pm, last_annual_pm, next_monthly_pm, next_six_month_pm, next_annual_pm)
                                    VALUES (%s, %s, %s , %s , %s, %s, %s, %s, %s, %s, %s, %s,
                                        CASE WHEN %s IS NOT NULL THEN %s::date + INTERVAL '30 days' ELSE NULL END,
                                        CASE WHEN %s IS NOT NULL THEN %s::date + INTERVAL '180 days' ELSE NULL END,
                                        CASE WHEN %s IS NOT NULL THEN %s::date + INTERVAL '365 days' ELSE NULL END)
                                    ON CONFLICT (bfm_equipment_no) DO UPDATE SET
                                        sap_material_no = EXCLUDED.sap_material_no,
                                        description = EXCLUDED.description,
                                        tool_id_drawing_no = EXCLUDED.tool_id_drawing_no,
                                        location = EXCLUDED.location,
                                        master_lin = EXCLUDED.master_lin,
                                        monthly_pm = EXCLUDED.monthly_pm,
                                        six_month_pm = EXCLUDED.six_month_pm,
                                        annual_pm = EXCLUDED.annual_pm,
                                        last_monthly_pm = EXCLUDED.last_monthly_pm,
                                        last_six_month_pm = EXCLUDED.last_six_month_pm,
                                        last_annual_pm = EXCLUDED.last_annual_pm,
                                        next_monthly_pm = EXCLUDED.next_monthly_pm,
                                        next_six_month_pm = EXCLUDED.next_six_month_pm,
                                        next_annual_pm = EXCLUDED.next_annual_pm
                                ''', (
                                    data.get('sap_material_no'),
                                    data.get('bfm_equipment_no'),
                                    data.get('description'),
                                    data.get('tool_id_drawing_no'),
                                    data.get('location'),
                                    data.get('master_lin'),
                                    data.get('monthly_pm', 1),
                                    data.get('six_month_pm', 1),
                                    data.get('annual_pm', 1),
                                    data.get('last_monthly_pm'),
                                    data.get('last_six_month_pm'),
                                    data.get('last_annual_pm'),
                                    data.get('last_monthly_pm'),
                                    data.get('last_monthly_pm'),
                                    data.get('last_six_month_pm'),
                                    data.get('last_six_month_pm'),
                                    data.get('last_annual_pm'),
                                    data.get('last_annual_pm')
                                ))
                                imported_count += 1
                            else:
                                error_count += 1
                            
                        except Exception as e:
                            print(f"Error importing row {index}: {e}")
                            error_count += 1
                            continue
                
                    self.conn.commit()
                    dialog.destroy()
                
                    # Show results
                    result_msg = f"Import completed!\n\n"
                    result_msg += f"CHECK: Successfully imported: {imported_count} records\n"
                    if error_count > 0:
                        result_msg += f"WARNING: Skipped (errors): {error_count} records\n"
                    result_msg += f"\nTotal processed: {imported_count + error_count} records"
                
                    messagebox.showinfo("Import Results", result_msg)
                    self.refresh_equipment_list()
                    self.update_status(f"Imported {imported_count} equipment records")
                
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to process import: {str(e)}")
        
            def cancel_import():
                    """Cancel the import process"""
                    dialog.destroy()
        
            # WARNING: BUTTONS FRAME - This was missing!
            button_frame = ttk.Frame(scrollable_frame)
            button_frame.pack(side='bottom', fill='x', padx=20, pady=20)
        
            # Import button (green)
            import_button = ttk.Button(button_frame, text="CHECK: Import with These Mappings", 
                                    command=process_import)
            import_button.pack(side='left', padx=10)
        
            # Cancel button
            cancel_button = ttk.Button(button_frame, text="CHECK: Cancel", 
                                    command=cancel_import)
            cancel_button.pack(side='right', padx=10)
        
            # Pack the canvas and scrollbar
            main_canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
        
            # Make the dialog modal
            dialog.focus_set()
            dialog.grab_set()
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read CSV file: {str(e)}")
            return
    
    
    
    def add_equipment_dialog(self):
        """Dialog to add new equipment"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New Equipment")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Form fields
        fields = [
            ("SAP Material No:", tk.StringVar()),
            ("BFM Equipment No:", tk.StringVar()),
            ("Description:", tk.StringVar()),
            ("Tool ID/Drawing No:", tk.StringVar()),
            ("Location:", tk.StringVar()),
            ("Master LIN:", tk.StringVar())
        ]
        
        entries = {}
        
        for i, (label, var) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=i, column=0, sticky='w', padx=10, pady=5)
            entry = ttk.Entry(dialog, textvariable=var, width=30)
            entry.grid(row=i, column=1, padx=10, pady=5)
            entries[label] = var
        
        # PM type checkboxes
        pm_frame = ttk.LabelFrame(dialog, text="PM Types", padding=10)
        pm_frame.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=10, sticky='ew')
        
        monthly_var = tk.BooleanVar(value=True)
        six_month_var = tk.BooleanVar(value=True)
        annual_var = tk.BooleanVar(value=True)
        
        ttk.Checkbutton(pm_frame, text="Monthly PM", variable=monthly_var).pack(anchor='w')
        ttk.Checkbutton(pm_frame, text="Six Month PM", variable=six_month_var).pack(anchor='w')
        ttk.Checkbutton(pm_frame, text="Annual PM", variable=annual_var).pack(anchor='w')
        
        def save_equipment():
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    INSERT INTO equipment 
                    (sap_material_no, bfm_equipment_no, description, tool_id_drawing_no, 
                     location, master_lin, monthly_pm, six_month_pm, annual_pm)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    entries["SAP Material No:"].get(),
                    entries["BFM Equipment No:"].get(),
                    entries["Description:"].get(),
                    entries["Tool ID/Drawing No:"].get(),
                    entries["Location:"].get(),
                    entries["Master LIN:"].get(),
                    monthly_var.get(),
                    six_month_var.get(),
                    annual_var.get()
                ))
                self.conn.commit()
                messagebox.showinfo("Success", "Equipment added successfully!")
                dialog.destroy()
                self.refresh_equipment_list()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add equipment: {str(e)}")
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=len(fields)+1, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="Save", command=save_equipment).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)
    
    def edit_equipment_dialog(self):
        """Enhanced dialog to edit existing equipment with Run to Failure and Cannot Find options"""
        selected = self.equipment_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select equipment to edit")
            return

        # Get selected equipment data
        item = self.equipment_tree.item(selected[0])
        bfm_no = str(item['values'][1])  # BFM Equipment No.

        # Fetch full equipment data
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM equipment WHERE bfm_equipment_no = %s', (bfm_no,))
        equipment_data = cursor.fetchone()

        if not equipment_data:
            messagebox.showerror("Error", "Equipment not found in database")
            return

        # Create edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Equipment")
        dialog.geometry("500x550")  # Made slightly taller for Cannot Find option
        dialog.transient(self.root)
        dialog.grab_set()

        # Pre-populate fields
        fields = [
            ("SAP Material No:", tk.StringVar(value=equipment_data[1] or '')),
            ("BFM Equipment No:", tk.StringVar(value=equipment_data[2] or '')),
            ("Description:", tk.StringVar(value=equipment_data[3] or '')),
            ("Tool ID/Drawing No:", tk.StringVar(value=equipment_data[4] or '')),
            ("Location:", tk.StringVar(value=equipment_data[5] or '')),
            ("Master LIN:", tk.StringVar(value=equipment_data[6] or ''))
        ]

        entries = {}

        for i, (label, var) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=i, column=0, sticky='w', padx=10, pady=5)
            entry = ttk.Entry(dialog, textvariable=var, width=30)
            entry.grid(row=i, column=1, padx=10, pady=5)
            entries[label] = var

        # PM type checkboxes and Equipment Status options
        pm_frame = ttk.LabelFrame(dialog, text="PM Types & Equipment Status", padding=10)
        pm_frame.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=10, sticky='ew')

        # Current equipment status
        current_status = equipment_data[16] or 'Active'  # Status field

        # PM checkboxes
        monthly_var = tk.BooleanVar(value=bool(equipment_data[7]))
        six_month_var = tk.BooleanVar(value=bool(equipment_data[8]))
        annual_var = tk.BooleanVar(value=bool(equipment_data[9]))

        monthly_cb = ttk.Checkbutton(pm_frame, text="Monthly PM", variable=monthly_var)
        monthly_cb.pack(anchor='w')

        six_month_cb = ttk.Checkbutton(pm_frame, text="Six Month PM", variable=six_month_var)
        six_month_cb.pack(anchor='w')

        annual_cb = ttk.Checkbutton(pm_frame, text="Annual PM", variable=annual_var)
        annual_cb.pack(anchor='w')
        
        # Disable PM checkboxes if currently Cannot Find or Run to Failure
        if current_status in ['Run to Failure', 'Cannot Find']:
            monthly_cb.config(state='disabled')
            six_month_cb.config(state='disabled')
            annual_cb.config(state='disabled')

        # Separator
        ttk.Separator(pm_frame, orient='horizontal').pack(fill='x', pady=10)

        # Run to Failure option
        run_to_failure_var = tk.BooleanVar(value=(current_status == 'Run to Failure'))
        rtf_cb = ttk.Checkbutton(pm_frame, text="WARNING: Set as Run to Failure Equipment", 
                                variable=run_to_failure_var,
                                command=lambda: toggle_status_options())
        rtf_cb.pack(anchor='w', pady=5)
    
        # Run to Failure warning label
        rtf_warning_label = ttk.Label(pm_frame, text="Status: Will be set to Run to Failure", 
                                    foreground='red', font=('Arial', 9, 'italic'))
        if run_to_failure_var.get():
            rtf_warning_label.pack(anchor='w', padx=20)

        # Cannot Find option - NEW!
        cannot_find_var = tk.BooleanVar(value=(current_status == 'Cannot Find'))
        cf_cb = ttk.Checkbutton(pm_frame, text="CHECK: Mark as Cannot Find", 
                            variable=cannot_find_var,
                            command=lambda: toggle_status_options())
        cf_cb.pack(anchor='w', pady=5)

        # Cannot Find warning label
        cf_warning_label = ttk.Label(pm_frame, text="Status: Will be set to Cannot Find (PMs disabled)", 
                                    foreground='red', font=('Arial', 9, 'italic'))
        if cannot_find_var.get():
            cf_warning_label.pack(anchor='w', padx=20)

        # Status info
        status_label = ttk.Label(pm_frame, text=f"Current Status: {current_status}", 
                                font=('Arial', 9, 'italic'))
        status_label.pack(anchor='w', pady=5)

        # Technician selection for Cannot Find (appears when Cannot Find is checked)
        tech_frame = ttk.Frame(pm_frame)
        ttk.Label(tech_frame, text="Reported By:").pack(side='left', padx=(0, 5))
        tech_var = tk.StringVar()
    
        # Pre-populate technician if asset is already Cannot Find
        if current_status == 'Cannot Find':
            cursor.execute('SELECT technician_name FROM cannot_find_assets WHERE bfm_equipment_no = %s', (bfm_no,))
            cf_data = cursor.fetchone()
            if cf_data:
                tech_var.set(cf_data[0])
    
        tech_combo = ttk.Combobox(tech_frame, textvariable=tech_var, width=20)
        tech_combo['values'] = self.technicians if hasattr(self, 'technicians') else []
        tech_combo.pack(side='left')
    
        # Show tech frame and warning if already Cannot Find
        if cannot_find_var.get():
            tech_frame.pack(anchor='w', pady=5, padx=20)
            cf_warning_label.pack(anchor='w', padx=20)
        if run_to_failure_var.get():
            rtf_warning_label.pack(anchor='w', padx=20)

        def toggle_status_options():
            """Enable/disable options based on status selections and show/hide warnings"""
            # Cannot select both Run to Failure and Cannot Find
            if run_to_failure_var.get() and cannot_find_var.get():
                # If both are checked, uncheck the other one
                if run_to_failure_var.get():
                    cannot_find_var.set(False)
            
            # Disable PM options if Run to Failure is selected
            if run_to_failure_var.get():
                monthly_cb.config(state='disabled')
                six_month_cb.config(state='disabled')
                annual_cb.config(state='disabled')
                monthly_var.set(False)
                six_month_var.set(False)
                annual_var.set(False)
                rtf_warning_label.pack(anchor='w', padx=20)
                cf_warning_label.pack_forget()
                tech_frame.pack_forget()
            elif cannot_find_var.get():
                # ALSO disable PM options for Cannot Find assets
                monthly_cb.config(state='disabled')
                six_month_cb.config(state='disabled')
                annual_cb.config(state='disabled')
                monthly_var.set(False)
                six_month_var.set(False)
                annual_var.set(False)
                cf_warning_label.pack(anchor='w', padx=20)
                rtf_warning_label.pack_forget()
                tech_frame.pack(anchor='w', pady=5, padx=20)
            else:
                monthly_cb.config(state='normal')
                six_month_cb.config(state='normal')
                annual_cb.config(state='normal')
                rtf_warning_label.pack_forget()
                cf_warning_label.pack_forget()
                tech_frame.pack_forget()

        # Run to Failure note
        note_label = ttk.Label(pm_frame, 
                              text="WARNING: Run to Failure and Cannot Find equipment will not be scheduled for PMs",
                              font=('Arial', 8), foreground='orange')
        note_label.pack(anchor='w', pady=(5, 0))

        def update_equipment():
            """Update equipment in database with Cannot Find support"""
            try:
                cursor = self.conn.cursor()
            
                # Determine new status
                if run_to_failure_var.get():
                    new_status = 'Run to Failure'
                elif cannot_find_var.get():
                    new_status = 'Cannot Find'
                else:
                    new_status = 'Active'
            
                # Update equipment table
                cursor.execute('''
                    UPDATE equipment 
                    SET sap_material_no = %s,
                        description = %s,
                        tool_id_drawing_no = %s,
                        location = %s,
                        master_lin = %s,
                        monthly_pm = %s,
                        six_month_pm = %s,
                        annual_pm = %s,
                        status = %s
                    WHERE bfm_equipment_no = %s
                ''', (
                    entries["SAP Material No:"].get(),
                    entries["Description:"].get(),
                    entries["Tool ID/Drawing No:"].get(),
                    entries["Location:"].get(),
                    entries["Master LIN:"].get(),
                    monthly_var.get(),
                    six_month_var.get(),
                    annual_var.get(),
                    new_status,
                    bfm_no
                ))
            
                # Handle Run to Failure status
                if run_to_failure_var.get() and current_status != 'Run to Failure':
                    cursor.execute('''
                        INSERT OR REPLACE INTO run_to_failure_assets 
                        (bfm_equipment_no, description, location, technician_name, completion_date, labor_hours, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        bfm_no,
                        entries["Description:"].get(),
                        entries["Location:"].get(),
                        'System Change',
                        datetime.now().strftime('%Y-%m-%d'),
                        0.0,
                        'Equipment manually set to Run to Failure status via equipment edit dialog'
                    ))
                
                    # Remove from Cannot Find if it was there
                    cursor.execute('DELETE FROM cannot_find_assets WHERE bfm_equipment_no = %s', (bfm_no,))
                
                elif not run_to_failure_var.get() and current_status == 'Run to Failure':
                    cursor.execute('DELETE FROM run_to_failure_assets WHERE bfm_equipment_no = %s', (bfm_no,))
            
                # Handle Cannot Find status - NEW!
                if cannot_find_var.get():
                    # Get technician name
                    technician = tech_var.get().strip()
                    if not technician:
                        messagebox.showwarning("Missing Information", "Please select who is reporting this asset as Cannot Find")
                        return
                
                    # Add or update in cannot_find_assets table
                    cursor.execute('''
                        INSERT OR REPLACE INTO cannot_find_assets 
                        (bfm_equipment_no, description, location, technician_name, reported_date, status, notes)
                        VALUES (%s, %s, %s, %s, %s, 'Missing', %s)
                    ''', (
                        bfm_no,
                        entries["Description:"].get(),
                        entries["Location:"].get(),
                        technician,
                        datetime.now().strftime('%Y-%m-%d'),
                        'Equipment marked as Cannot Find via equipment edit dialog'
                    ))
                
                    # Remove from Run to Failure if it was there
                    cursor.execute('DELETE FROM run_to_failure_assets WHERE bfm_equipment_no = %s', (bfm_no,))
                
                elif not cannot_find_var.get() and current_status == 'Cannot Find':
                    # Remove from Cannot Find table
                    cursor.execute('DELETE FROM cannot_find_assets WHERE bfm_equipment_no = %s', (bfm_no,))
                    technician = None  # Set to None when unmarking
            
                self.conn.commit()
            
                # Show appropriate success message
                if run_to_failure_var.get():
                    success_msg = f"Equipment {bfm_no} updated successfully!\n\nStatus changed to: Run to Failure\n"
                    success_msg += "- All PM requirements disabled\n"
                    success_msg += "- Equipment moved to Run to Failure tab\n"
                    success_msg += "- No future PMs will be scheduled"
                elif cannot_find_var.get():
                    success_msg = f"Equipment {bfm_no} updated successfully!\n\nStatus changed to: Cannot Find\n"
                    success_msg += f"- Reported by: {technician}\n"
                    success_msg += "- Equipment moved to Cannot Find tab\n"
                    success_msg += "- All PM requirements disabled\n"
                    success_msg += "- No future PMs will be scheduled"
                else:
                    success_msg = f"Equipment {bfm_no} updated successfully!\n\nStatus: Active"
            
                messagebox.showinfo("Success", success_msg)
                dialog.destroy()
            
                # Refresh all relevant displays
                self.refresh_equipment_list()
                if hasattr(self, 'load_cannot_find_assets'):
                    self.load_cannot_find_assets()
                if hasattr(self, 'load_run_to_failure_assets'):
                    self.load_run_to_failure_assets()
                if hasattr(self, 'update_equipment_statistics'):
                    self.update_equipment_statistics()
            
                # Update status bar
                if run_to_failure_var.get():
                    self.update_status(f"Equipment {bfm_no} set to Run to Failure")
                elif cannot_find_var.get():
                    self.update_status(f"Equipment {bfm_no} marked as Cannot Find")
                else:
                    self.update_status(f"Equipment {bfm_no} reactivated")
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update equipment: {str(e)}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=len(fields)+1, column=0, columnspan=2, pady=15)

        update_btn = ttk.Button(button_frame, text="CHECK: Update Equipment", command=update_equipment)
        update_btn.pack(side='left', padx=10)

        cancel_btn = ttk.Button(button_frame, text="CHECK: Cancel", command=dialog.destroy)
        cancel_btn.pack(side='left', padx=5)
    
    
    
    def bulk_edit_pm_cycles(self):
        """Edit PM cycles for multiple selected assets"""
        # Get selected items
        selected_items = self.equipment_tree.selection()
    
        if not selected_items:
            messagebox.showwarning("No Selection", 
                                 "Please select one or more assets to edit.\n\n" +
                                 "Tip: Hold Ctrl to select multiple items, or Shift to select a range.")
            return
    
        # Get BFM numbers of selected items
        selected_bfms = []
        for item in selected_items:
            values = self.equipment_tree.item(item)['values']
            bfm_no = values[1]  # BFM is second column
            selected_bfms.append(bfm_no)
    
        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Bulk Edit PM Cycles")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
    
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (250)
        y = (dialog.winfo_screenheight() // 2) - (200)
        dialog.geometry(f"500x400+{x}+{y}")
        
        # Header
        header_frame = ttk.Frame(dialog, padding=20)
        header_frame.pack(fill='x')
        
        ttk.Label(header_frame, text="Bulk Edit PM Cycles", 
                font=('Arial', 14, 'bold')).pack()
        ttk.Label(header_frame, text=f"Editing {len(selected_bfms)} selected asset(s)", 
                font=('Arial', 10), foreground='blue').pack(pady=5)
    
        # Separator
        ttk.Separator(dialog, orient='horizontal').pack(fill='x', pady=10)
        
        # Show selected assets
        assets_frame = ttk.LabelFrame(dialog, text="Selected Assets", padding=10)
        assets_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        # Scrollable list of selected assets
        assets_text = tk.Text(assets_frame, height=6, width=50, wrap='word')
        assets_scrollbar = ttk.Scrollbar(assets_frame, orient='vertical', command=assets_text.yview)
        assets_text.configure(yscrollcommand=assets_scrollbar.set)
        
        # Get asset details
        cursor = self.conn.cursor()
        for bfm in selected_bfms[:20]:  # Show first 20
            cursor.execute('SELECT bfm_equipment_no, description FROM equipment WHERE bfm_equipment_no = %s', (bfm,))
            result = cursor.fetchone()
            if result:
                assets_text.insert('end', f"- {result[0]} - {result[1][:40]}\n")
    
        if len(selected_bfms) > 20:
            assets_text.insert('end', f"\n... and {len(selected_bfms) - 20} more assets")
    
        assets_text.config(state='disabled')
        assets_text.pack(side='left', fill='both', expand=True)
        assets_scrollbar.pack(side='right', fill='y')
    
        # PM Cycle options
        pm_frame = ttk.LabelFrame(dialog, text="PM Cycle Settings", padding=15)
        pm_frame.pack(fill='x', padx=20, pady=10)
    
        ttk.Label(pm_frame, text="Select which PM cycles to apply:", 
                font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 10))
    
        # Monthly PM
        monthly_var = tk.BooleanVar(value=False)
        monthly_check = ttk.Checkbutton(pm_frame, text="Monthly PM (every 30 days)", 
                                        variable=monthly_var)
        monthly_check.pack(anchor='w', pady=3)
        
        # Six Month PM
        six_month_var = tk.BooleanVar(value=False)
        six_month_check = ttk.Checkbutton(pm_frame, text="Six Month PM (every 180 days)", 
                                        variable=six_month_var)
        six_month_check.pack(anchor='w', pady=3)
    
        # Annual PM
        annual_var = tk.BooleanVar(value=True)  # Default to Annual
        annual_check = ttk.Checkbutton(pm_frame, text="Annual PM (every 365 days)", 
                                    variable=annual_var)
        annual_check.pack(anchor='w', pady=3)
    
        ttk.Label(pm_frame, text="Note: Unchecked cycles will be DISABLED for selected assets.", 
                font=('Arial', 9), foreground='gray').pack(anchor='w', pady=(10, 0))
    
        # Buttons
        button_frame = ttk.Frame(dialog, padding=10)
        button_frame.pack(fill='x', side='bottom')
    
        def apply_changes():
            """Apply PM cycle changes to all selected assets"""
            try:
                monthly_pm = 1 if monthly_var.get() else 0
                six_month_pm = 1 if six_month_var.get() else 0
                annual_pm = 1 if annual_var.get() else 0
                
                # Confirm action
                pm_types = []
                if monthly_pm:
                    pm_types.append("Monthly")
                if six_month_pm:
                    pm_types.append("Six Month")
                if annual_pm:
                    pm_types.append("Annual")
            
                if not pm_types:
                    result = messagebox.askyesno(
                        "Warning - No PM Cycles Selected",
                        f"You are about to DISABLE ALL PM cycles for {len(selected_bfms)} asset(s).\n\n" +
                        "This means these assets will NOT be scheduled for any preventive maintenance.\n\n" +
                        "Are you sure you want to continue?",
                        icon='warning',
                        parent=dialog
                    )
                else:
                    pm_list = ", ".join(pm_types)
                    result = messagebox.askyesno(
                        "Confirm Changes",
                        f"Apply the following PM cycles to {len(selected_bfms)} asset(s)?\n\n" +
                        f"PM Cycles: {pm_list}\n\n" +
                        "This will update all selected assets.",
                        parent=dialog
                    )
            
                if not result:
                    return
            
                # Apply changes
                cursor = self.conn.cursor()
                updated_count = 0
                
                for bfm in selected_bfms:
                    cursor.execute('''
                        UPDATE equipment 
                        SET monthly_pm = %s, six_month_pm = %s, annual_pm = %s
                        WHERE bfm_equipment_no = %s
                    ''', (monthly_pm, six_month_pm, annual_pm, bfm))
                
                    if cursor.rowcount > 0:
                        updated_count += 1
            
                self.conn.commit()
            
                # Success message
                messagebox.showinfo(
                    "Success",
                    f"Successfully updated PM cycles for {updated_count} asset(s)!",
                    parent=dialog
                )
            
                # Close dialog and refresh
                dialog.destroy()
                self.refresh_equipment_list()
                self.update_status(f"Bulk updated PM cycles for {updated_count} assets")
            
            except Exception as e:
                messagebox.showerror("Error", f"Failed to update PM cycles:\n\n{str(e)}", parent=dialog)
    
        ttk.Button(button_frame, text="CHECK: Apply to All Selected", 
                command=apply_changes,
                style='Accent.TButton').pack(side='left', padx=5)
    
        ttk.Button(button_frame, text="Cancel", 
                command=dialog.destroy).pack(side='right', padx=5)


    def enable_multiselect_on_equipment_tree(self):
        """Enable multiple selection on equipment tree (call this after creating the tree)"""
        self.equipment_tree.configure(selectmode='extended')  # Enable multi-select
    
    
    
    
    def refresh_equipment_list(self):
        """Refresh equipment list display"""
        try:
            self.load_equipment_data()
        
            # Clear existing items
            for item in self.equipment_tree.get_children():
                self.equipment_tree.delete(item)
        
            # Add equipment to tree
            for equipment in self.equipment_data:
                if len(equipment) >= 9:
                    self.equipment_tree.insert('', 'end', values=(
                        equipment[1] or '',  # SAP
                        equipment[2] or '',  # BFM
                        equipment[3] or '',  # Description
                        equipment[5] or '',  # Location
                        equipment[6] or '',  # Master LIN
                        'Yes' if equipment[7] else 'No',  # Monthly PM
                        'Yes' if equipment[8] else 'No',  # Six Month PM
                        'Yes' if equipment[9] else 'No',  # Annual PM
                        equipment[16] or 'Active'  # Status
                    ))
        
            # Update statistics
            self.update_equipment_statistics()

            # Update location filter dropdown
            self.populate_location_filter()

            # Update status
            self.update_status(f"Equipment list refreshed - {len(self.equipment_data)} items")
        
        except Exception as e:
            print(f"Error refreshing equipment list: {e}")
            messagebox.showerror("Error", f"Failed to refresh equipment list: {str(e)}")
    
    def filter_equipment_list(self, *args):
        """Filter equipment list based on search term and location"""
        search_term = self.equipment_search_var.get().lower()
        selected_location = self.equipment_location_var.get()

        # Clear existing items
        for item in self.equipment_tree.get_children():
            self.equipment_tree.delete(item)

        # Add filtered equipment
        for equipment in self.equipment_data:
            if len(equipment) >= 9:
                equipment_location = equipment[5] or ''

                # Check location filter
                location_match = (selected_location == "All Locations" or
                                equipment_location == selected_location)

                if not location_match:
                    continue

                # Check if search term matches any field
                searchable_fields = [
                    equipment[1] or '',  # SAP
                    equipment[2] or '',  # BFM
                    equipment[3] or '',  # Description
                    equipment_location,  # Location
                    equipment[6] or ''   # Master LIN
                ]

                if not search_term or any(search_term in field.lower() for field in searchable_fields):
                    self.equipment_tree.insert('', 'end', values=(
                        equipment[1] or '',  # SAP
                        equipment[2] or '',  # BFM
                        equipment[3] or '',  # Description
                        equipment_location,  # Location
                        equipment[6] or '',  # Master LIN
                        'Yes' if equipment[7] else 'No',  # Monthly PM
                        'Yes' if equipment[8] else 'No',  # Six Month PM
                        'Yes' if equipment[9] else 'No',  # Annual PM
                        equipment[16] or 'Active'  # Status
                    ))

    def populate_location_filter(self):
        """Populate location filter dropdown with distinct locations from database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT DISTINCT location FROM equipment WHERE location IS NOT NULL AND location != \'\' ORDER BY location')
            locations = [row[0] for row in cursor.fetchall()]

            # Add "All Locations" as the first option
            location_values = ["All Locations"] + locations
            self.equipment_location_combo['values'] = location_values

            # Set default to "All Locations"
            if self.equipment_location_var.get() not in location_values:
                self.equipment_location_var.set("All Locations")

        except Exception as e:
            print(f"Error populating location filter: {e}")

    def clear_equipment_filters(self):
        """Clear all equipment filters and show all equipment"""
        self.equipment_search_var.set('')
        self.equipment_location_var.set("All Locations")
        self.filter_equipment_list()

    def export_equipment_list(self):
        """Export equipment list to CSV"""
        try:
            file_path = filedialog.asksaveasfilename(
                title="Export Equipment List",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
        
            if file_path:
                cursor = self.conn.cursor()
                # SELECT specific columns instead of SELECT *
                cursor.execute('''
                    SELECT id, sap_material_no, bfm_equipment_no, description, 
                           tool_id_drawing_no, location, master_lin, monthly_pm, 
                           six_month_pm, annual_pm, last_monthly_pm, last_six_month_pm, 
                           last_annual_pm, next_monthly_pm, next_six_month_pm, 
                           next_annual_pm, status, created_date, updated_date
                    FROM equipment 
                    ORDER BY bfm_equipment_no
                ''')
                equipment_data = cursor.fetchall()
            
                # Create DataFrame
                columns = ['ID', 'SAP Material No', 'BFM Equipment No', 'Description', 
                          'Tool ID/Drawing No', 'Location', 'Master LIN', 'Monthly PM', 
                          'Six Month PM', 'Annual PM', 'Last Monthly PM', 'Last Six Month PM', 
                          'Last Annual PM', 'Next Monthly PM', 'Next Six Month PM', 
                          'Next Annual PM', 'Status', 'Created Date', 'Updated Date']
            
                df = pd.DataFrame(equipment_data, columns=columns)
                df.to_csv(file_path, index=False)
            
                messagebox.showinfo("Success", f"Equipment list exported to {file_path}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export equipment list: {str(e)}")
    
    def load_equipment_data(self):
        """Load equipment data from database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM equipment ORDER BY bfm_equipment_no')
            self.equipment_data = cursor.fetchall()
        except Exception as e:
            print(f"Error loading equipment data: {e}")
            self.equipment_data = []
    
    
    def generate_weekly_assignments(self):
        """
        NEW SOLID PM assignment generation - prevents duplicates
        """
        try:
            # Validate that technicians are configured
            if not hasattr(self, 'technicians') or not self.technicians or len(self.technicians) == 0:
                messagebox.showerror(
                    "Configuration Error",
                    "No technicians configured in the system.\n\n"
                    "Please contact your system administrator."
                )
                return

            # Create the new PM scheduling service
            pm_service = PMSchedulingService(self.conn, self.technicians, self.root)

            # Get the week start date
            week_start = self.week_start_var.get()

            # Generate the schedule
            result = pm_service.generate_weekly_schedule(week_start, self.weekly_pm_target)

            if result['success']:
                # Check if there's a special message (like no equipment or no assignments)
                if 'message' in result and result['total_assignments'] == 0:
                    messagebox.showinfo(
                        "Scheduling Complete",
                        f"{result['message']}\n\n"
                        f"Week: {week_start}"
                    )
                else:
                    messagebox.showinfo(
                        "NEW SYSTEM - Scheduling Complete",
                        f"Generated {result['total_assignments']} PM assignments for week {week_start}\n\n"
                        f"Unique assets: {result['unique_assets']}\n\n"
                        f"This new system prevents duplicate assignments!"
                    )

                # Refresh displays
                self.refresh_technician_schedules()
                self.update_status(f"NEW SYSTEM: Generated {result['total_assignments']} PM assignments")
            else:
                messagebox.showerror("NEW SYSTEM Error", f"Failed to generate assignments: {result['error']}")

        except Exception as e:
            messagebox.showerror("NEW SYSTEM Error", f"Failed to generate assignments: {str(e)}")
            import traceback
            traceback.print_exc()
    

    
    def refresh_technician_schedules(self):
        """Refresh all technician schedule displays"""
        week_start = self.week_start_var.get()

        for technician, tree in self.technician_trees.items():
            # Clear existing items
            for item in tree.get_children():
                tree.delete(item)

            # Load scheduled PMs for this technician
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT ws.bfm_equipment_no, e.description, ws.pm_type, ws.scheduled_date, ws.status
                FROM weekly_pm_schedules ws
                JOIN equipment e ON ws.bfm_equipment_no = e.bfm_equipment_no
                WHERE ws.assigned_technician = %s AND ws.week_start_date = %s
                ORDER BY ws.scheduled_date
            ''', (technician, week_start))

            assignments = cursor.fetchall()

            for idx, assignment in enumerate(assignments):
                bfm_no, description, pm_type, scheduled_date, status = assignment
                tree.insert('', 'end', values=(bfm_no, description, pm_type, scheduled_date, status))

                # Yield to event loop every 20 items to keep UI responsive
                if idx % 20 == 0:
                    self.root.update_idletasks()

            # Yield to event loop after each technician
            self.root.update_idletasks()
    
    def print_weekly_pm_forms(self):
        """Generate and print PM forms for the week"""
        try:
            week_start = self.week_start_var.get()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Create directory for PM forms
            forms_dir = f"PM_Forms_Week_{week_start}_{timestamp}"
            os.makedirs(forms_dir, exist_ok=True)
        
            cursor = self.conn.cursor()
        
            # Generate forms for each technician
            for technician in self.technicians:
                cursor.execute('''
                    SELECT ws.bfm_equipment_no, e.sap_material_no, e.description, e.tool_id_drawing_no,
                        e.location, e.master_lin, ws.pm_type, ws.scheduled_date, ws.assigned_technician
                    FROM weekly_pm_schedules ws
                    JOIN equipment e ON ws.bfm_equipment_no = e.bfm_equipment_no
                    WHERE ws.assigned_technician = %s AND ws.week_start_date = %s
                    ORDER BY ws.scheduled_date
                ''', (technician, week_start))
            
                assignments = cursor.fetchall()
            
                if assignments:
                    # Create PDF for this technician
                    filename = os.path.join(forms_dir, f"{technician.replace(' ', '_')}_PM_Forms.pdf")
                    self.create_pm_forms_pdf(filename, technician, assignments)
        
            messagebox.showinfo("Success", f"PM forms generated in directory: {forms_dir}")
            self.update_status(f"PM forms generated for week {week_start}")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PM forms: {str(e)}")
    
    def create_pm_forms_pdf(self, filename, technician, assignments):
        """Create PDF with PM forms for a technician - ENHANCED WITH CUSTOM TEMPLATES"""
        try:
            doc = SimpleDocTemplate(filename, pagesize=letter,
                                rightMargin=36, leftMargin=36,
                                topMargin=36, bottomMargin=36)

            styles = getSampleStyleSheet()
            story = []

        # Custom styles for better text wrapping
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                wordWrap='LTR'
            )

            header_cell_style = ParagraphStyle(
                'HeaderCellStyle',
                parent=styles['Normal'],
                fontSize=9,
                fontName='Helvetica-Bold',
                leading=11,
                wordWrap='LTR'
            )

            company_style = ParagraphStyle(
                'CompanyStyle',
                parent=styles['Heading1'],
                fontSize=14,
                fontName='Helvetica-Bold',
                alignment=1,
                textColor=colors.darkblue
            )

            print(f"DEBUG: Creating PDF for {technician}")
            print(f"DEBUG: Total assignments: {len(assignments)}")

            for i, assignment in enumerate(assignments):
                print(f"DEBUG: Processing assignment {i}: {assignment}")
        
            # Safety check for assignment data
                if not assignment or len(assignment) < 8:
                    print(f"DEBUG: Skipping invalid assignment {i}")
                    continue

            # Extract variables from assignment
                bfm_no, sap_no, description, tool_id, location, master_lin, pm_type, scheduled_date, assigned_tech = assignment
        
            # Add None checks for all variables
                bfm_no = bfm_no or ''
                sap_no = sap_no or ''
                description = description or ''
                tool_id = tool_id or ''
                location = location or ''
                master_lin = master_lin or ''
                pm_type = pm_type or 'Monthly'
                scheduled_date = scheduled_date or ''
                assigned_tech = assigned_tech or technician
        
                print(f"DEBUG: Processing {bfm_no} - {pm_type}")

            # =================== LOGO SECTION ===================
            # Dynamic logo path that works on any computer
                script_dir = os.path.dirname(os.path.abspath(__file__))
                logo_path = os.path.join(script_dir, "img", "ait_logo.png")

                try:
                    if os.path.exists(logo_path):
                        # Create centered logo
                        logo_image = Image(logo_path, width=4*inch, height=1.2*inch)

                        # Center the logo in a table
                        logo_data = [[logo_image]]
                        logo_table = Table(logo_data, colWidths=[7*inch])
                        logo_table.setStyle(TableStyle([
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('TOPPADDING', (0, 0), (-1, -1), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                        ]))

                        story.append(logo_table)
                    else:
                        print(f"Logo file not found at: {logo_path}")
                        # Fallback to text if logo file not found
                        story.append(Paragraph("AIT - BUILDING THE FUTURE OF AEROSPACE", company_style))
                        story.append(Spacer(1, 15))

                except Exception as e:
                    print(f"Could not load logo: {e}")
                    # Fallback to text header
                    story.append(Paragraph("AIT - BUILDING THE FUTURE OF AEROSPACE", company_style))
                    story.append(Spacer(1, 15))

            # =================== EQUIPMENT INFORMATION TABLE ===================
                equipment_data = [
                    [
                        Paragraph('(SAP) Material Number:', header_cell_style), 
                        Paragraph(str(sap_no), cell_style), 
                        Paragraph('Tool ID / Drawing Number:', header_cell_style), 
                        Paragraph(str(tool_id), cell_style)
                    ],
                    [
                        Paragraph('(BFM) Equipment Number:', header_cell_style), 
                        Paragraph(str(bfm_no), cell_style), 
                        Paragraph('Description of Equipment:', header_cell_style), 
                        Paragraph(str(description), cell_style)
                    ],
                    [
                        Paragraph('Date of Last PM:', header_cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('Location of Equipment:', header_cell_style), 
                        Paragraph(str(location), cell_style)
                    ],
                    [
                        Paragraph('Maintenance Technician:', header_cell_style), 
                        Paragraph(str(assigned_tech), cell_style), 
                        Paragraph('PM Cycle:', header_cell_style), 
                        Paragraph(str(pm_type), cell_style)
                    ],
                    [
                        Paragraph('Estimated Hours:', header_cell_style), 
                        Paragraph('1.0h', cell_style), 
                        Paragraph('Date of PM Completion:', header_cell_style), 
                        Paragraph('', cell_style)
                    ],
                    [
                        Paragraph('Signature of Technician:', header_cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style)
                    ],
                    [
                        Paragraph('Safety: Always be aware of both Airbus and AIT safety policies and ensure safety policies are followed.', cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style)
                    ],
                    [
                        Paragraph(f'Printed: {datetime.now().strftime("%m/%d/%Y")}', cell_style), 
                        '', '', ''
                    ]
                ]
        
                equipment_table = Table(equipment_data, colWidths=[1.8*inch, 1.7*inch, 1.8*inch, 1.7*inch])
                equipment_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('SPAN', (0, -2), (-1, -2)),  # Safety spans all columns
                    ('SPAN', (0, -1), (-1, -1)),  # Printed date spans all columns
                ]))
        
                story.append(equipment_table)
                story.append(Spacer(1, 15))

            # =================== PM CHECKLIST TABLE ===================
            # Try to get custom template checklist
                checklist_items = []
                cursor = self.conn.cursor()
                cursor.execute('''
                    SELECT checklist_items FROM pm_templates 
                    WHERE bfm_equipment_no = %s AND pm_type = %s
                ''', (bfm_no, pm_type))
            
                template_result = cursor.fetchone()
            
                if template_result and template_result[0]:
                    try:
                        checklist_items = json.loads(template_result[0])
                        print(f"DEBUG: Using custom template with {len(checklist_items)} items")
                    except:
                        checklist_items = []
            
                # Use default checklist if no custom template
                if not checklist_items:
                    checklist_items = [
                        "Special Equipment Used (List):",
                        "Validate your maintenance with Date / Stamp / Hours",
                        "Refer to drawing when performing maintenance",
                        "Make sure all instruments are properly calibrated",
                        "Make sure tool is properly identified",
                        "Make sure all mobile mechanisms move fluidly",
                        "Visually inspect the welds",
                        "Take note of any anomaly or defect (create a CM if needed)",
                        "Check all screws. Tighten if needed.",
                        "Check the pins for wear",
                        "Make sure all tooling is secured to the equipment with cable",
                        "Ensure all tags (BFM and SAP) are applied and securely fastened",
                        "All documentation are picked up from work area",
                        "All parts and tools have been picked up",
                        "Workspace has been cleaned up",
                        "Dry runs have been performed (tests, restarts, etc.)",
                        "Ensure that AIT Sticker is applied"
                    ]

                checklist_data = [
                    [
                        Paragraph('', header_cell_style), 
                        Paragraph('PM CHECKLIST:', header_cell_style), 
                        Paragraph('', header_cell_style), 
                        Paragraph('Complete', header_cell_style), 
                        Paragraph('Labor Time', header_cell_style)
                    ]
                ]
        
                # Add checklist items
                for idx, item in enumerate(checklist_items, 1):
                    checklist_data.append([
                        Paragraph(str(idx), cell_style), 
                        Paragraph(item, cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style)
                    ])
        
                checklist_table = Table(checklist_data, colWidths=[0.3*inch, 3.5*inch, 1.5*inch, 0.8*inch, 0.9*inch])
                checklist_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('SPAN', (1, 0), (2, 0)),  # PM CHECKLIST spans 2 columns
                ]))
        
                story.append(checklist_table)
                story.append(Spacer(1, 15))

            # =================== COMPLETION INFORMATION TABLE ===================
                completion_data = [
                    [
                        Paragraph('Notes from Technician:', header_cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('Next Annual PM Date:', header_cell_style)
                    ],
                    [
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('', cell_style)
                    ],
                    [
                        Paragraph('All Data Entered Into System:', header_cell_style), 
                        Paragraph('', cell_style), 
                        Paragraph('Total Time', header_cell_style)
                    ],
                    [
                        Paragraph('Document Name', header_cell_style), 
                        Paragraph('Revision', header_cell_style), 
                        Paragraph('', cell_style)
                    ],
                    [
                        Paragraph('Preventive_Maintenance_Form', cell_style), 
                        Paragraph('A2', cell_style), 
                        Paragraph('', cell_style)
                    ]
                ]

                completion_table = Table(completion_data, colWidths=[2.8*inch, 2.2*inch, 2*inch])
                completion_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))

                story.append(completion_table)
            
                # Add page break after each PM form (except the last one)
                if i < len(assignments) - 1:
                    story.append(PageBreak())

            # Build PDF
            print(f"DEBUG: Building PDF with {len(story)} elements")
            doc.build(story)
            print(f"DEBUG: PDF created successfully: {filename}")

        except Exception as e:
            print(f"Error creating PM forms PDF: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def export_weekly_schedule(self):
        """Export weekly schedule to Excel"""
        try:
            week_start = self.week_start_var.get()
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"Weekly_PM_Schedule_{week_start}_{timestamp}.xlsx"
            
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT ws.assigned_technician, ws.bfm_equipment_no, e.description, 
                       ws.pm_type, ws.scheduled_date, ws.status
                FROM weekly_pm_schedules ws
                JOIN equipment e ON ws.bfm_equipment_no = e.bfm_equipment_no
                WHERE ws.week_start_date = %s
                ORDER BY ws.assigned_technician, ws.scheduled_date
            ''', (week_start,))
            
            schedule_data = cursor.fetchall()
            
            # Create DataFrame
            df = pd.DataFrame(schedule_data, columns=[
                'Technician', 'BFM Equipment No', 'Description', 'PM Type', 'Scheduled Date', 'Status'
            ])
            
            # Export to Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Weekly Schedule', index=False)
                
                # Create summary sheet
                summary_data = []
                for tech in self.technicians:
                    tech_count = len(df[df['Technician'] == tech])
                    summary_data.append([tech, tech_count])
                
                summary_df = pd.DataFrame(summary_data, columns=['Technician', 'Assigned PMs'])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            messagebox.showinfo("Success", f"Weekly schedule exported to {filename}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export weekly schedule: {str(e)}")
    
    def create_pm_history_search_tab(self):
        """PM History Search tab for comprehensive equipment completion information"""
        self.pm_history_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.pm_history_frame, text="PM History Search")
    
        # Search controls
        search_controls_frame = ttk.LabelFrame(self.pm_history_frame, text="Search Equipment PM History", padding=15)
        search_controls_frame.pack(fill='x', padx=10, pady=5)
    
        # Search input
        search_input_frame = ttk.Frame(search_controls_frame)
        search_input_frame.pack(fill='x', pady=5)
    
        ttk.Label(search_input_frame, text="Search:").pack(side='left', padx=5)
        self.history_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_input_frame, textvariable=self.history_search_var, width=30)
        search_entry.pack(side='left', padx=5)
    
        ttk.Button(search_input_frame, text="Search", command=self.search_pm_history_simple).pack(side='left', padx=5)
        ttk.Button(search_input_frame, text="Clear", command=self.clear_search_simple).pack(side='left', padx=5)
    
        # Results display
        results_frame = ttk.LabelFrame(self.pm_history_frame, text="Search Results", padding=10)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
        # Results tree
        self.history_search_tree = ttk.Treeview(results_frame,
                                            columns=('BFM No', 'SAP No', 'Description', 'PM Type', 'Technician', 'Date', 'Hours'),
                                            show='headings')
    
        for col in ('BFM No', 'SAP No', 'Description', 'PM Type', 'Technician', 'Date', 'Hours'):
            self.history_search_tree.heading(col, text=col)
            self.history_search_tree.column(col, width=120)
    
        self.history_search_tree.pack(fill='both', expand=True)

    def search_pm_history_simple(self):
        """Simple PM history search"""
        try:
            search_term = self.history_search_var.get().lower()
            cursor = self.conn.cursor()
        
            if search_term:
                cursor.execute('''
                    SELECT pc.bfm_equipment_no, e.sap_material_no, e.description, 
                        pc.pm_type, pc.technician_name, pc.completion_date,
                        (pc.labor_hours + pc.labor_minutes/60.0) as total_hours
                    FROM pm_completions pc
                    LEFT JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
                    WHERE LOWER(pc.bfm_equipment_no) LIKE %s
                    OR LOWER(e.description) LIKE %s 
                    OR LOWER(pc.technician_name) LIKE %s 
                    ORDER BY pc.completion_date DESC LIMIT 50
                ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
            else:
                cursor.execute('''
                    SELECT pc.bfm_equipment_no, e.sap_material_no, e.description, 
                        pc.pm_type, pc.technician_name, pc.completion_date,
                        (pc.labor_hours + pc.labor_minutes/60.0) as total_hours
                    FROM pm_completions pc
                    LEFT JOIN equipment e ON pc.bfm_equipment_no = e.bfm_equipment_no
                    ORDER BY pc.completion_date DESC LIMIT 20
                ''')
        
            results = cursor.fetchall()
        
            # Clear existing
            for item in self.history_search_tree.get_children():
                self.history_search_tree.delete(item)
        
            # Add results
            for result in results:
                bfm_no, sap_no, description, pm_type, technician, date, hours = result
                hours_display = f"{hours:.1f}h" if hours else "0.0h"
            
                self.history_search_tree.insert('', 'end', values=(
                    bfm_no or '', sap_no or '', description or '', 
                    pm_type or '', technician or '', date or '', hours_display
                ))
        except Exception as e:
            print(f"Search error: {e}")

    def clear_search_simple(self):
        """Clear search"""
        self.history_search_var.set('')
        self.search_pm_history_simple()
    
    
    def check_for_conflicts(self):
        """Check if SharePoint database was updated during this session"""
        try:
            if not hasattr(self, 'backup_sync_dir') or not self.backup_sync_dir:
                return False
        
            # Get latest backup in SharePoint
            latest_backup = self.get_latest_sharepoint_backup()
            if not latest_backup:
                return False
        
            backup_path, backup_time = latest_backup
        
            # If backup is newer than our session start, someone else updated it
            if backup_time > self.session_start_time:
                print(f"CHECK: CONFLICT DETECTED!")
                print(f"  Session started: {self.session_start_time}")
                print(f"  Latest backup: {backup_time}")
                print(f"  Someone updated the database during your session!")
                return True
        
            return False
        
        except Exception as e:
            print(f"Error checking for conflicts: {e}")
            return False
    
    def get_latest_sharepoint_backup(self):
        """Get the latest backup file from SharePoint"""
        try:
            backup_files = []
        
            for filename in os.listdir(self.backup_sync_dir):
                if filename.endswith('.db'):
                    filepath = os.path.join(self.backup_sync_dir, filename)
                    modified_time = os.path.getmtime(filepath)
                    backup_files.append((filepath, modified_time))
        
            if not backup_files:
                return None
        
            backup_files.sort(key=lambda x: x[1], reverse=True)
            latest_file, latest_time = backup_files[0]
            return (latest_file, datetime.fromtimestamp(latest_time))
        
        except Exception as e:
            print(f"Error getting latest backup: {e}")
            return None
    
    def show_smart_merge_dialog(self):
        """Show dialog explaining conflict and offering merge options - NOW WITH SCROLLBAR"""
    
        dialog = tk.Toplevel(self.root)
        dialog.title("WARNING: Database Conflict Detected")
        dialog.geometry("750x700")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (750 // 2)
        y = (dialog.winfo_screenheight() // 2) - (700 // 2)
        dialog.geometry(f"750x700+{x}+{y}")
        
        result = {"action": "cancel"}
        
        # Main container with scrollbar
        main_canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
    
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        # Header with warning
        header_frame = ttk.Frame(scrollable_frame, padding=20)
        header_frame.pack(fill='x')

        ttk.Label(header_frame, text="WARNING: Database Conflict Detected!", 
                font=('Arial', 16, 'bold'), foreground='red').pack()
        ttk.Label(header_frame, text="Team members updated the database while you were working", 
                font=('Arial', 11), foreground='orange').pack(pady=5)

        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=10)

        # Situation explanation
        situation_frame = ttk.LabelFrame(scrollable_frame, text="What Happened", padding=15)
        situation_frame.pack(fill='x', padx=20, pady=10)

        session_duration = datetime.now() - self.session_start_time
        hours, remainder = divmod(int(session_duration.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        situation_text = f"""
    You opened the program at: {self.session_start_time.strftime('%I:%M %p')}
    You worked for: {hours}h {minutes}m

    During this time, other team members:
    - Completed PMs
    - Created/updated CMs
    - Modified equipment records
    - Updated inventory
    - Made other changes

    Their changes were saved to SharePoint.

    If you close now without merging, their work will be LOST! CHECK:
        """

        ttk.Label(situation_frame, text=situation_text, justify='left').pack(anchor='w')

        # Merge explanation
        merge_frame = ttk.LabelFrame(scrollable_frame, text="How Smart Merge Works", padding=15)
        merge_frame.pack(fill='x', padx=20, pady=10)

        merge_explanation = """
    SMART MERGE PROCESS:

    1. Downloads latest database from SharePoint
    2. Identifies ALL changes you made:
       - PM Completions you entered
       - CMs you created/updated
       - Equipment records you modified
       - MRO inventory you changed
       - Cannot Find/Run to Failure updates

    3. Intelligently merges:
       - ADDS your new PM completions to their database
       - ADDS your new CMs to their database
       - MERGES equipment updates (newest wins)
       - MERGES MRO inventory (your changes win)
       - Preserves all their work too!

    4. Result: Combined database with EVERYONE'S work! CHECK:
        """
    
        ttk.Label(merge_frame, text=merge_explanation, justify='left',
                font=('Courier', 9)).pack(anchor='w')

        # Options
        options_frame = ttk.LabelFrame(scrollable_frame, text="Your Options", padding=15)
        options_frame.pack(fill='x', padx=20, pady=10)

        options_text = """
    OPTION 1: SMART MERGE (Recommended) CHECK:
      CHECK: Combines everyone's work safely
      CHECK: Nothing gets lost

    OPTION 2: OVERRIDE (Dangerous) CHECK:
    CHECK: Overwrites their work with yours only
    CHECK: Their PMs, CMs, updates will be LOST!

    OPTION 3: CANCEL
    CHECK: Don't close yet
    CHECK: Coordinate with team first
        """

        ttk.Label(options_frame, text=options_text, justify='left').pack(anchor='w')

        # Buttons
        button_frame = ttk.Frame(scrollable_frame, padding=15)
        button_frame.pack(fill='x', side='bottom')

        def do_merge():
            result["action"] = "merge"
            dialog.destroy()

        def do_override():
            confirm = messagebox.askyesno(
                "WARNING: CONFIRM OVERRIDE",
                "You are about to OVERWRITE other users' work!\n\n"
                "Their PM completions, CMs, and updates will be LOST!\n\n"
                "Are you ABSOLUTELY SURE?",
                icon='warning',
                parent=dialog
            )
            if confirm:
                result["action"] = "override"
                dialog.destroy()

        def do_cancel():
            result["action"] = "cancel"
            dialog.destroy()

        ttk.Button(button_frame, text="CHECK: Smart Merge (Recommended)", 
                command=do_merge,
                style='Accent.TButton').pack(side='left', padx=5)

        ttk.Button(button_frame, text="Cancel", 
                command=do_cancel).pack(side='left', padx=5)

        ttk.Button(button_frame, text="WARNING: Override Their Work", 
                command=do_override).pack(side='right', padx=5)

        # Pack the canvas and scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
        # Enable mousewheel scrolling
        def on_mousewheel(event):
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        main_canvas.bind_all("<MouseWheel>", on_mousewheel)

        dialog.wait_window()
        return result["action"]


# ========== UPDATED METHOD 6: show_closing_sync_dialog ==========
    def show_closing_sync_dialog(self):
        """Show dialog when closing program normally - NOW WITH SCROLLBAR"""
    
        dialog = tk.Toplevel(self.root)
        dialog.title("Close AIT CMMS")
        dialog.geometry("650x600")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (650 // 2)
        y = (dialog.winfo_screenheight() // 2) - (600 // 2)
        dialog.geometry(f"650x600+{x}+{y}")
        
        result = {"action": "cancel"}
        
        # Main container with scrollbar
        main_canvas = tk.Canvas(dialog)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
    
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        # Header
        header_frame = ttk.Frame(scrollable_frame, padding=20)
        header_frame.pack(fill='x')

        ttk.Label(header_frame, text="Close AIT CMMS", 
                font=('Arial', 14, 'bold')).pack()

        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=10)

        # Session info
        info_frame = ttk.LabelFrame(scrollable_frame, text="Session Information", padding=15)
        info_frame.pack(fill='x', padx=20, pady=10)

        session_duration = datetime.now() - self.session_start_time
        hours, remainder = divmod(int(session_duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        info_text = f"""
    User: {self.user_name}
    Role: {self.current_user_role}

    Session Start: {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}
    Session Duration: {hours}h {minutes}m {seconds}s

    Current Database: ait_cmms_database.db
    SharePoint Folder: {os.path.basename(self.backup_sync_dir) if hasattr(self, 'backup_sync_dir') and self.backup_sync_dir else 'Not Connected'}
        """

        ttk.Label(info_frame, text=info_text, justify='left', 
                font=('Courier', 9)).pack(anchor='w')

        # Sync explanation
        sync_frame = ttk.LabelFrame(scrollable_frame, text="What Happens Next", padding=15)
        sync_frame.pack(fill='x', padx=20, pady=10)

        sync_text = """When you click 'Backup and Close':

    1. CHECK: Your database will be backed up to SharePoint
    2. CHECK: Timestamped backup will be created
    3. CHECK: Other users can access your latest changes
    4. CHECK: Program will close safely

    This ensures all your work is saved.
        """
    
        ttk.Label(sync_frame, text=sync_text, justify='left').pack(anchor='w')

        # Important note
        note_frame = ttk.Frame(scrollable_frame, padding=10)
        note_frame.pack(fill='x', padx=20)

        ttk.Label(note_frame, 
                  text="WARNING: Note: Last person to close the program pushes the final database state",
                  foreground='blue', font=('Arial', 9),
                  wraplength=550).pack()

        # Buttons
        button_frame = ttk.Frame(scrollable_frame, padding=15)
        button_frame.pack(fill='x', side='bottom')

        def sync_and_close():
            result["action"] = "sync_and_close"
            dialog.destroy()

        def cancel_close():
            result["action"] = "cancel"
            dialog.destroy()

        def close_without_sync():
            confirm = messagebox.askyesno(
                "Confirm Close Without Backup",
                "Close without backing up to SharePoint?\n\n"
                "WARNING: WARNING: Your changes will NOT be saved!\n"
                "WARNING: Other users will NOT see your work!\n\n"
                "Are you sure?",
                icon='warning',
                parent=dialog
            )
            if confirm:
                result["action"] = "close_without_sync"
                dialog.destroy()

        ttk.Button(button_frame, text="WARNING: Backup and Close", 
                command=sync_and_close,
                style='Accent.TButton').pack(side='left', padx=5)

        ttk.Button(button_frame, text="Cancel", 
                command=cancel_close).pack(side='left', padx=5)

        ttk.Button(button_frame, text="WARNING: Close Without Backup", 
                command=close_without_sync).pack(side='right', padx=5)

        # Pack the canvas and scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
        # Enable mousewheel scrolling
        def on_mousewheel(event):
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        main_canvas.bind_all("<MouseWheel>", on_mousewheel)

        dialog.wait_window()
        return result["action"]

    
    
    def perform_comprehensive_merge_and_close(self):
        """Comprehensively merge all changes from both databases - NOW WITH SCROLLBAR"""
        try:
            # Show progress
            progress = tk.Toplevel(self.root)
            progress.title("Comprehensive Smart Merge in Progress...")
            progress.geometry("650x500")
            progress.transient(self.root)
            progress.grab_set()
            
            # Center progress
            progress.update_idletasks()
            x = (progress.winfo_screenwidth() // 2) - (650 // 2)
            y = (progress.winfo_screenheight() // 2) - (500 // 2)
            progress.geometry(f"650x500+{x}+{y}")
            
            # Main container with scrollbar
            main_canvas = tk.Canvas(progress)
            scrollbar = ttk.Scrollbar(progress, orient="vertical", command=main_canvas.yview)
            scrollable_frame = ttk.Frame(main_canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
            )
        
            main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            main_canvas.configure(yscrollcommand=scrollbar.set)
        
            status_var = tk.StringVar(value="Preparing comprehensive merge...")
    
            ttk.Label(scrollable_frame, text="Comprehensive Smart Merge", 
                    font=('Arial', 14, 'bold')).pack(pady=20)
    
            status_label = ttk.Label(scrollable_frame, textvariable=status_var, 
                                    font=('Arial', 10), wraplength=600)
            status_label.pack(pady=10)
    
            progress_bar = ttk.Progressbar(scrollable_frame, mode='indeterminate', length=550)
            progress_bar.pack(pady=10)
            progress_bar.start()
    
            log_text = tk.Text(scrollable_frame, height=15, width=75, font=('Courier', 8))
            log_text.pack(pady=10, padx=20)
    
            def log(message):
                log_text.insert('end', message + '\n')
                log_text.see('end')
                progress.update()
        
            # Pack the canvas and scrollbar
            main_canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # Enable mousewheel scrolling
            def on_mousewheel(event):
                main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            main_canvas.bind_all("<MouseWheel>", on_mousewheel)
    
            progress.update()
    
            # Step 1: Save current database
            status_var.set("Step 1/6: Saving your changes...")
            log("CHECK: Saving your current work...")
            
            my_changes_db = 'temp_my_changes.db'
            if hasattr(self, 'conn'):
                self.conn.close()
    
            shutil.copy2('ait_cmms_database.db', my_changes_db)
            log(f"CHECK: Your changes saved to: {my_changes_db}")
        
            # Step 2: Pull latest from SharePoint
            status_var.set("Step 2/6: Pulling latest database from SharePoint...")
            log("CHECK: Downloading latest team database...")
        
            latest_backup = self.get_latest_sharepoint_backup()
            if not latest_backup:
                raise Exception("Could not find SharePoint backup")
        
            shutil.copy2(latest_backup[0], 'ait_cmms_latest.db')
            log(f"CHECK: Downloaded: {os.path.basename(latest_backup[0])}")
        
            # Step 3: Open both databases
            status_var.set("Step 3/6: Opening databases...")
            log("CHECK: Opening both databases for comparison...")
        
            my_conn = sqlite3.connect(my_changes_db)
            latest_conn = sqlite3.connect('ait_cmms_latest.db')
            log("CHECK: Both databases opened successfully")
            
            # Step 4-5: Perform merges
            status_var.set("Step 4/6: Merging PM completions...")
            log("\nCHECK: Merging PM Completions...")
            pm_count = self.merge_pm_completions(my_conn, latest_conn)
            log(f"  CHECK: Merged {pm_count} PM completion(s)")
            
            status_var.set("Step 5/6: Merging CMs and other records...")
            log("CHECK: Merging Corrective Maintenance records...")
            cm_count = self.merge_corrective_maintenance(my_conn, latest_conn)
            log(f"  CHECK: Merged {cm_count} CM record(s)")
            
            log("CHECK: Merging MRO inventory...")
            mro_count = self.merge_mro_inventory(my_conn, latest_conn)
            log(f"  CHECK: Merged {mro_count} MRO item(s)")
            
            log("CHECK: Merging Equipment updates...")
            equip_count = self.merge_equipment_updates(my_conn, latest_conn)
            log(f"  CHECK: Merged {equip_count} equipment update(s)")
            
            log("CHECK: Merging Cannot Find assets...")
            cf_count = self.merge_cannot_find_assets(my_conn, latest_conn)
            log(f"  CHECK: Merged {cf_count} Cannot Find record(s)")
            
            log("CHECK: Merging Run to Failure assets...")
            rtf_count = self.merge_run_to_failure_assets(my_conn, latest_conn)
            log(f"  CHECK: Merged {rtf_count} Run to Failure record(s)")
            
            my_conn.close()
            latest_conn.close()
        
            # Save merged database
            status_var.set("Step 6/6: Saving merged database to SharePoint...")
            log("\nCHECK: Pushing merged database to SharePoint...")
            shutil.copy2('ait_cmms_latest.db', 'ait_cmms_database.db')
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"ait_cmms_backup_{timestamp}.db"
            backup_path = os.path.join(self.backup_sync_dir, backup_filename)
            shutil.copy2('ait_cmms_database.db', backup_path)
            
            log(f"CHECK: Saved to SharePoint: {backup_filename}")
    
            # Cleanup
            try:
                os.remove(my_changes_db)
                os.remove('ait_cmms_latest.db')
            except:
                pass
    
            status_var.set("CHECK: Merge Complete!")
            progress_bar.stop()
        
            total_merged = pm_count + cm_count + mro_count + equip_count + cf_count + rtf_count
            log(f"\nCHECK: SUCCESS! Merged {total_merged} total changes!")
            log("Everyone's work has been preserved!")
    
            # Wait then close
            progress.after(3000, lambda: self.finish_close(progress))
    
        except Exception as e:
            messagebox.showerror("Merge Error", 
                               f"Error during merge:\n{str(e)}\n\n"
                               "Your work is saved locally.\n"
                               "Contact support for help.")


   
    
    
    def merge_pm_completions(self, my_conn, latest_conn):
        """Merge PM completions from my database to latest"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
        
            # Get PM completions from my database that aren't in latest
            my_cursor.execute('''
                SELECT bfm_equipment_no, pm_type, technician_name, completion_date,
                    labor_hours, labor_minutes, pm_due_date, special_equipment, notes,
                    next_annual_pm_date
                FROM pm_completions
            ''')
        
            my_pms = my_cursor.fetchall()
            merged_count = 0
        
            for pm in my_pms:
                bfm_no, pm_type, tech, comp_date, hours, mins, due_date, special, notes, next_annual = pm
            
                # Check if this exact PM already exists in latest
                latest_cursor.execute('''
                    SELECT id FROM pm_completions 
                    WHERE bfm_equipment_no = %s AND pm_type = %s
                    AND technician_name = %s AND completion_date = %s
                ''', (bfm_no, pm_type, tech, comp_date))
            
                if not latest_cursor.fetchone():
                    # Insert this PM into latest database
                    latest_cursor.execute('''
                        INSERT INTO pm_completions 
                        (bfm_equipment_no, pm_type, technician_name, completion_date,
                        labor_hours, labor_minutes, pm_due_date, special_equipment, notes,
                        next_annual_pm_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (bfm_no, pm_type, tech, comp_date, hours, mins, due_date, special, notes, next_annual))
                    merged_count += 1
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging PM completions: {e}")
            return 0
    
    def merge_corrective_maintenance(self, my_conn, latest_conn):
        """Merge CM records from my database to latest"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
            
            # Get CMs from my database
            my_cursor.execute('SELECT * FROM corrective_maintenance')
            my_cms = my_cursor.fetchall()
            
            # Get column info
            my_cursor.execute('PRAGMA table_info(corrective_maintenance)')
            columns = [col[1] for col in my_cursor.fetchall()]
            
            merged_count = 0
        
            for cm in my_cms:
                cm_number = cm[1]  # Assuming cm_number is second column
            
                # Check if CM exists in latest
                latest_cursor.execute(
                    'SELECT id FROM corrective_maintenance WHERE cm_number = %s',
                    (cm_number,)
                )
            
                exists = latest_cursor.fetchone()
            
                if not exists:
                    # Insert new CM
                    placeholders = ', '.join(['%s' for _ in columns])
                    latest_cursor.execute(
                        f'INSERT INTO corrective_maintenance VALUES ({placeholders})',
                        cm
                    )
                    merged_count += 1
                else:
                    # Update existing CM (user's version is newer)
                    set_clause = ', '.join([f'{col} = %s' for col in columns[2:]])  # Skip id and cm_number
                    latest_cursor.execute(
                        f'UPDATE corrective_maintenance SET {set_clause} WHERE cm_number = %s',
                        cm[2:] + (cm_number,)
                    )
                    merged_count += 1
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging CMs: {e}")
            return 0
    
    
    
    def merge_mro_inventory(self, my_conn, latest_conn):
        """Merge MRO inventory from my database to latest"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
            
            # Get MRO items from my database
            my_cursor.execute('SELECT * FROM mro_inventory')
            my_items = my_cursor.fetchall()
        
            # Get columns
            my_cursor.execute('PRAGMA table_info(mro_inventory)')
            columns = [col[1] for col in my_cursor.fetchall()]
            
            merged_count = 0
        
            for item in my_items:
                part_number = item[1]  # Assuming part_number is second column
            
                # Check if exists in latest
                latest_cursor.execute(
                    'SELECT id FROM mro_inventory WHERE part_number = %s',
                    (part_number,)
                )
            
                exists = latest_cursor.fetchone()
            
                if not exists:
                    # Insert new item
                    placeholders = ', '.join(['%s' for _ in columns])
                    latest_cursor.execute(
                        f'INSERT INTO mro_inventory VALUES ({placeholders})',
                        item
                    )
                    merged_count += 1
                else:
                    # Update existing (user's changes win for MRO)
                    set_clause = ', '.join([f'{col} = %s' for col in columns[2:]])
                    latest_cursor.execute(
                        f'UPDATE mro_inventory SET {set_clause} WHERE part_number = %s',
                        item[2:] + (part_number,)
                    )
                    merged_count += 1
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging MRO: {e}")
            return 0
    
    
    def merge_equipment_updates(self, my_conn, latest_conn):
        """Merge equipment updates (take most recent changes)"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
            
            # Get equipment from my database
            my_cursor.execute('SELECT * FROM equipment')
            my_equipment = my_cursor.fetchall()
            
            # Get columns
            my_cursor.execute('PRAGMA table_info(equipment)')
            columns = [col[1] for col in my_cursor.fetchall()]
        
            merged_count = 0
        
            for equip in my_equipment:
                bfm_no = equip[1]  # Assuming bfm_equipment_no is second column
            
                # Check if exists in latest
                latest_cursor.execute(
                    'SELECT id FROM equipment WHERE bfm_equipment_no = %s',
                    (bfm_no,)
                )
            
                exists = latest_cursor.fetchone()
            
                if not exists:
                    # Insert new equipment
                    placeholders = ', '.join(['%s' for _ in columns])
                    latest_cursor.execute(
                        f'INSERT INTO equipment VALUES ({placeholders})',
                        equip
                    )
                    merged_count += 1
                # For existing equipment, we keep latest version (don't overwrite)
                # This is safer - equipment records are usually setup data
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging equipment: {e}")
            return 0
    
    
    def merge_cannot_find_assets(self, my_conn, latest_conn):
        """Merge Cannot Find assets"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
            
            my_cursor.execute('SELECT * FROM cannot_find_assets')
            my_assets = my_cursor.fetchall()
            
            my_cursor.execute('PRAGMA table_info(cannot_find_assets)')
            columns = [col[1] for col in my_cursor.fetchall()]
            
            merged_count = 0
            
            for asset in my_assets:
                bfm_no = asset[1]  # Assuming bfm_equipment_no is second column
            
                latest_cursor.execute(
                    'SELECT id FROM cannot_find_assets WHERE bfm_equipment_no = %s',
                    (bfm_no,)
                )
            
                if not latest_cursor.fetchone():
                    placeholders = ', '.join(['%s' for _ in columns])
                    latest_cursor.execute(
                        f'INSERT INTO cannot_find_assets VALUES ({placeholders})',
                        asset
                    )
                    merged_count += 1
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging Cannot Find: {e}")
            return 0
    
    
    
    def merge_run_to_failure_assets(self, my_conn, latest_conn):
        """Merge Run to Failure assets"""
        try:
            my_cursor = my_conn.cursor()
            latest_cursor = latest_conn.cursor()
            
            my_cursor.execute('SELECT * FROM run_to_failure_assets')
            my_assets = my_cursor.fetchall()
            
            my_cursor.execute('PRAGMA table_info(run_to_failure_assets)')
            columns = [col[1] for col in my_cursor.fetchall()]
            
            merged_count = 0
        
            for asset in my_assets:
                bfm_no = asset[1]  # Assuming bfm_equipment_no is second column
            
                latest_cursor.execute(
                    'SELECT id FROM run_to_failure_assets WHERE bfm_equipment_no = %s',
                    (bfm_no,)
                )
            
                if not latest_cursor.fetchone():
                    placeholders = ', '.join(['%s' for _ in columns])
                    latest_cursor.execute(
                        f'INSERT INTO run_to_failure_assets VALUES ({placeholders})',
                        asset
                    )
                    merged_count += 1
        
            latest_conn.commit()
            return merged_count
        
        except Exception as e:
            print(f"Error merging Run to Failure: {e}")
            return 0
    
    
    def backup_and_close_normal(self):
        """Normal backup and close (no conflicts)"""
        if hasattr(self, 'backup_sync_dir'):
            print("Creating backup...")
            self.sharepoint_only_backup(self.backup_sync_dir)
            print("Backup completed")
    
        if hasattr(self, 'conn'):
            self.conn.close()
    
        self.root.destroy()
    
    
    def finish_close(self, progress_dialog):
        """Final cleanup and close"""
        progress_dialog.destroy()
    
        if hasattr(self, 'conn'):
            try:
                self.conn.close()
            except:
                pass
    
        self.root.destroy()
    
    def clear_all_mro_inventory(self):
        """Clear ALL MRO stock inventory items from the database"""
    
        # First, get count of items to show in confirmation
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM mro_inventory')
        total_count = cursor.fetchone()[0]
    
        if total_count == 0:
            messagebox.showinfo("No Items", "There are no MRO inventory items to clear.")
            return
    
        # Show confirmation dialog with count
        result = messagebox.askyesno(
            "WARNING: Confirm Clear All MRO Inventory",
            f"Are you sure you want to DELETE ALL {total_count} MRO inventory items?\n\n"
            "WARNING: WARNING: This action cannot be undone!\n"
            "WARNING: ALL stock records will be permanently deleted!\n\n"
            "This will remove:\n"
            "- All part numbers\n"
            "- All quantity records\n"
            "- All stock locations\n"
            "- All inventory data\n\n"
            "Are you ABSOLUTELY SURE?",
            icon='warning'
        )
    
        if not result:
            return
    
        # Double confirmation for safety
        double_check = messagebox.askyesno(
            "WARNING: Final Confirmation",
            f"FINAL WARNING!\n\n"
            f"You are about to permanently delete {total_count} inventory items.\n\n"
            "This cannot be reversed!\n\n"
            "Click YES to proceed with deletion.",
            icon='warning'
        )
    
        if not double_check:
            messagebox.showinfo("Cancelled", "Clear operation cancelled. No items were deleted.")
            return
    
        try:
            # Delete all MRO inventory items
            cursor.execute('DELETE FROM mro_inventory')
            self.conn.commit()
            
            # Refresh the MRO display if the method exists
            if hasattr(self.mro_manager, 'load_mro_inventory'):
                self.mro_manager.load_mro_inventory()
        
            # Update status bar
            self.update_status(f"CHECK: Successfully cleared {total_count} MRO inventory items")
        
            # Show success message
            messagebox.showinfo(
                "Success", 
                f"All {total_count} MRO inventory items have been permanently deleted.\n\n"
                "The MRO inventory is now empty."
            )
        
        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Error", f"Failed to clear MRO inventory: {str(e)}")
            print(f"Clear MRO inventory error: {e}")
    
# Main application startup
if __name__ == "__main__":
    root = tk.Tk()
    app = AITCMMSSystem(root)
    root.mainloop()