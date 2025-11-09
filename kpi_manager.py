"""
KPI Manager Module
Handles KPI calculations, data management, and reporting for 2025 KPIs
"""

import psycopg2
from psycopg2 import extras
from datetime import datetime, timedelta
from decimal import Decimal
import calendar


class KPIManager:
    """Manages KPI calculations and data"""

    def __init__(self, pool):
        """Initialize with database connection pool"""
        self.pool = pool

    def get_all_kpi_definitions(self):
        """Get all active KPI definitions"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT * FROM kpi_definitions
                WHERE is_active = TRUE
                ORDER BY function_code, kpi_name
            """)
            results = cursor.fetchall()
            cursor.close()
            return results
        finally:
            self.pool.return_connection(conn)

    def get_kpi_by_name(self, kpi_name):
        """Get specific KPI definition"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT * FROM kpi_definitions
                WHERE kpi_name = %s AND is_active = TRUE
            """, (kpi_name,))
            result = cursor.fetchone()
            cursor.close()
            return result
        finally:
            self.pool.return_connection(conn)

    def save_manual_data(self, kpi_name, measurement_period, data_field, data_value,
                        data_text=None, notes=None, entered_by=None):
        """Save manual data input for KPI calculation"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO kpi_manual_data
                (kpi_name, measurement_period, data_field, data_value, data_text, notes, entered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (kpi_name, measurement_period, data_field)
                DO UPDATE SET
                    data_value = EXCLUDED.data_value,
                    data_text = EXCLUDED.data_text,
                    notes = EXCLUDED.notes,
                    entered_by = EXCLUDED.entered_by,
                    entered_date = CURRENT_TIMESTAMP
            """, (kpi_name, measurement_period, data_field, data_value, data_text, notes, entered_by))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.pool.return_connection(conn)

    def get_manual_data(self, kpi_name, measurement_period):
        """Get manual data for a specific KPI and period"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT * FROM kpi_manual_data
                WHERE kpi_name = %s AND measurement_period = %s
                ORDER BY data_field
            """, (kpi_name, measurement_period))
            results = cursor.fetchall()
            cursor.close()
            return results
        finally:
            self.pool.return_connection(conn)

    def save_kpi_result(self, kpi_name, measurement_period, calculated_value,
                       calculated_text=None, target_value=None, meets_criteria=None,
                       calculated_by=None, notes=None):
        """Save calculated KPI result"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO kpi_results
                (kpi_name, measurement_period, calculated_value, calculated_text,
                 target_value, meets_criteria, calculated_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (kpi_name, measurement_period)
                DO UPDATE SET
                    calculated_value = EXCLUDED.calculated_value,
                    calculated_text = EXCLUDED.calculated_text,
                    target_value = EXCLUDED.target_value,
                    meets_criteria = EXCLUDED.meets_criteria,
                    calculated_by = EXCLUDED.calculated_by,
                    notes = EXCLUDED.notes,
                    calculation_date = CURRENT_TIMESTAMP
            """, (kpi_name, measurement_period, calculated_value, calculated_text,
                  target_value, meets_criteria, calculated_by, notes))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self.pool.return_connection(conn)

    def get_kpi_results(self, measurement_period=None, kpi_name=None):
        """Get KPI results, optionally filtered by period and/or KPI name"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)

            query = """
                SELECT r.*, d.function_code, d.description, d.acceptance_criteria, d.frequency
                FROM kpi_results r
                JOIN kpi_definitions d ON r.kpi_name = d.kpi_name
                WHERE 1=1
            """
            params = []

            if measurement_period:
                query += " AND r.measurement_period = %s"
                params.append(measurement_period)

            if kpi_name:
                query += " AND r.kpi_name = %s"
                params.append(kpi_name)

            query += " ORDER BY d.function_code, r.kpi_name, r.measurement_period DESC"

            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()
            return results
        finally:
            self.pool.return_connection(conn)

    # ==================== KPI CALCULATION METHODS ====================

    def calculate_pm_adherence(self, measurement_period, username=None):
        """
        Calculate Preventive Maintenance Adherence
        Formula: (number of WO completed / number of WO scheduled) x 100%
        Target: >95%
        """
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()

            # Parse period (format: YYYY-MM)
            year, month = map(int, measurement_period.split('-'))
            start_date = f"{year}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year}-{month:02d}-{last_day}"

            # Count scheduled PMs
            cursor.execute("""
                SELECT COUNT(*) FROM weekly_pm_schedules
                WHERE week_start_date::date >= %s::date AND week_start_date::date <= %s::date
            """, (start_date, end_date))
            scheduled = cursor.fetchone()[0]

            # Count completed PMs
            cursor.execute("""
                SELECT COUNT(*) FROM pm_completions
                WHERE completion_date::date >= %s::date AND completion_date::date <= %s::date
            """, (start_date, end_date))
            completed = cursor.fetchone()[0]

            cursor.close()

            # Calculate adherence
            if scheduled > 0:
                adherence = (completed / scheduled) * 100
                meets_criteria = adherence >= 95
            else:
                adherence = 0
                meets_criteria = None

            # Save result
            self.save_kpi_result(
                kpi_name='Preventive Maintenance Adherence',
                measurement_period=measurement_period,
                calculated_value=round(adherence, 2),
                calculated_text=f"{completed}/{scheduled} completed",
                target_value=95,
                meets_criteria=meets_criteria,
                calculated_by=username,
                notes=f"Scheduled: {scheduled}, Completed: {completed}"
            )

            return {
                'value': round(adherence, 2),
                'scheduled': scheduled,
                'completed': completed,
                'meets_criteria': meets_criteria
            }

        finally:
            self.pool.return_connection(conn)

    def calculate_wo_opened_vs_closed(self, measurement_period, username=None):
        """
        Calculate WO opened vs WO closed
        Formula: number of WO open vs number of WO closed
        Target: No >40 open WO
        """
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()

            # Parse period
            year, month = map(int, measurement_period.split('-'))
            start_date = f"{year}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year}-{month:02d}-{last_day}"

            # Count opened CMs
            cursor.execute("""
                SELECT COUNT(*) FROM corrective_maintenance
                WHERE reported_date::date >= %s::date AND reported_date::date <= %s::date
            """, (start_date, end_date))
            opened = cursor.fetchone()[0]

            # Count closed CMs
            cursor.execute("""
                SELECT COUNT(*) FROM corrective_maintenance
                WHERE closed_date::date >= %s::date AND closed_date::date <= %s::date
                AND closed_date IS NOT NULL
            """, (start_date, end_date))
            closed = cursor.fetchone()[0]

            # Count currently open
            cursor.execute("""
                SELECT COUNT(*) FROM corrective_maintenance
                WHERE closed_date IS NULL OR closed_date = ''
            """)
            currently_open = cursor.fetchone()[0]

            cursor.close()

            meets_criteria = currently_open <= 40

            # Save result
            self.save_kpi_result(
                kpi_name='WO opened vs WO closed',
                measurement_period=measurement_period,
                calculated_value=currently_open,
                calculated_text=f"Opened: {opened}, Closed: {closed}, Currently Open: {currently_open}",
                target_value=40,
                meets_criteria=meets_criteria,
                calculated_by=username,
                notes=f"Opened: {opened}, Closed: {closed}"
            )

            return {
                'opened': opened,
                'closed': closed,
                'currently_open': currently_open,
                'meets_criteria': meets_criteria
            }

        finally:
            self.pool.return_connection(conn)

    def calculate_wo_backlog(self, measurement_period, username=None):
        """
        Calculate WO Backlog
        Formula: Total of WO open
        Target: <10% of the WO raised in a month
        """
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()

            # Parse period
            year, month = map(int, measurement_period.split('-'))
            start_date = f"{year}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year}-{month:02d}-{last_day}"

            # Count WO raised this month
            cursor.execute("""
                SELECT COUNT(*) FROM corrective_maintenance
                WHERE reported_date::date >= %s::date AND reported_date::date <= %s::date
            """, (start_date, end_date))
            raised_this_month = cursor.fetchone()[0]

            # Count open WO
            cursor.execute("""
                SELECT COUNT(*) FROM corrective_maintenance
                WHERE closed_date IS NULL OR closed_date = ''
            """)
            open_wo = cursor.fetchone()[0]

            cursor.close()

            # Calculate percentage
            if raised_this_month > 0:
                backlog_pct = (open_wo / raised_this_month) * 100
                meets_criteria = backlog_pct < 10
            else:
                backlog_pct = 0
                meets_criteria = open_wo == 0

            # Save result
            self.save_kpi_result(
                kpi_name='WO Backlog',
                measurement_period=measurement_period,
                calculated_value=open_wo,
                calculated_text=f"{open_wo} open ({backlog_pct:.1f}% of {raised_this_month} raised)",
                target_value=raised_this_month * 0.1 if raised_this_month > 0 else 0,
                meets_criteria=meets_criteria,
                calculated_by=username,
                notes=f"Open: {open_wo}, Raised this month: {raised_this_month}"
            )

            return {
                'open_wo': open_wo,
                'raised_this_month': raised_this_month,
                'backlog_pct': round(backlog_pct, 2),
                'meets_criteria': meets_criteria
            }

        finally:
            self.pool.return_connection(conn)

    def calculate_wo_age_profile(self, measurement_period, username=None):
        """
        Calculate WO age profile
        Formula: Age of work order
        Target: Nb of WO to exceed 60 days
        """
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor()

            # Get all open WOs
            cursor.execute("""
                SELECT id, reported_date
                FROM corrective_maintenance
                WHERE closed_date IS NULL OR closed_date = ''
            """)
            open_wos = cursor.fetchall()

            cursor.close()

            # Calculate age for each
            now = datetime.now().date()
            over_60_days = 0
            ages = []

            for wo_id, report_date in open_wos:
                if report_date:
                    # Convert report_date to date object if it's not already
                    if isinstance(report_date, str):
                        try:
                            report_date = datetime.strptime(report_date, '%Y-%m-%d').date()
                        except:
                            try:
                                report_date = datetime.strptime(report_date, '%Y-%m-%d %H:%M:%S').date()
                            except:
                                continue
                    elif isinstance(report_date, datetime):
                        report_date = report_date.date()

                    age = (now - report_date).days
                    ages.append(age)
                    if age > 60:
                        over_60_days += 1

            avg_age = sum(ages) / len(ages) if ages else 0
            meets_criteria = over_60_days == 0

            # Save result
            self.save_kpi_result(
                kpi_name='WO age profile',
                measurement_period=measurement_period,
                calculated_value=over_60_days,
                calculated_text=f"{over_60_days} WOs over 60 days old (avg age: {avg_age:.1f} days)",
                target_value=0,
                meets_criteria=meets_criteria,
                calculated_by=username,
                notes=f"Total open WOs: {len(open_wos)}, Average age: {avg_age:.1f} days"
            )

            return {
                'over_60_days': over_60_days,
                'total_open': len(open_wos),
                'avg_age': round(avg_age, 1),
                'meets_criteria': meets_criteria
            }

        finally:
            self.pool.return_connection(conn)

    def calculate_all_auto_kpis(self, measurement_period, username=None):
        """Calculate all KPIs that can be auto-calculated from database"""
        results = {}

        try:
            print(f"Calculating PM Adherence for {measurement_period}...")
            results['pm_adherence'] = self.calculate_pm_adherence(measurement_period, username)
            print("✓ PM Adherence calculated")
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"✗ PM Adherence error: {error_msg}")
            results['pm_adherence'] = {'error': error_msg}

        try:
            print(f"Calculating WO Opened vs Closed for {measurement_period}...")
            results['wo_opened_closed'] = self.calculate_wo_opened_vs_closed(measurement_period, username)
            print("✓ WO Opened vs Closed calculated")
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"✗ WO Opened vs Closed error: {error_msg}")
            results['wo_opened_closed'] = {'error': error_msg}

        try:
            print(f"Calculating WO Backlog for {measurement_period}...")
            results['wo_backlog'] = self.calculate_wo_backlog(measurement_period, username)
            print("✓ WO Backlog calculated")
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"✗ WO Backlog error: {error_msg}")
            results['wo_backlog'] = {'error': error_msg}

        try:
            print(f"Calculating WO Age Profile for {measurement_period}...")
            results['wo_age_profile'] = self.calculate_wo_age_profile(measurement_period, username)
            print("✓ WO Age Profile calculated")
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"✗ WO Age Profile error: {error_msg}")
            results['wo_age_profile'] = {'error': error_msg}

        return results

    def get_kpis_needing_manual_data(self):
        """Get list of KPIs that require manual data input"""
        return [
            'FR1',
            'Near Miss',
            'TTR (Time to Repair) Adherence',
            'MTBF Mean Time Between Failure',
            'Technical Availability Adherence',
            'MRT (Mean Response Time)',
            'Top Breakdown',
            'Purchaser Monthly process Confirmation',
            'Purchaser satisfaction',
            'Non Conformances raised',
            'Non Conformances closed',
            'Mean Time to Deliver a Quote'
        ]

    def get_required_fields_for_kpi(self, kpi_name):
        """Get required manual input fields for a specific KPI"""
        fields = {
            'FR1': [
                {'field': 'accident_count', 'label': 'Number of Accidents (sick leave > 24h)', 'type': 'number'},
                {'field': 'hours_worked', 'label': 'Number of Hours Worked', 'type': 'number'}
            ],
            'Near Miss': [
                {'field': 'near_miss_count', 'label': 'Number of Near Miss Reports', 'type': 'number'}
            ],
            'TTR (Time to Repair) Adherence': [
                {'field': 'p1_within_target', 'label': 'P1 Assets Fixed Within 2 Hours', 'type': 'number'},
                {'field': 'p1_total', 'label': 'Total P1 Asset Failures', 'type': 'number'},
                {'field': 'p2_within_target', 'label': 'P2 Assets Fixed Within 4 Hours', 'type': 'number'},
                {'field': 'p2_total', 'label': 'Total P2 Asset Failures', 'type': 'number'}
            ],
            'MTBF Mean Time Between Failure': [
                {'field': 'p1_operating_hours', 'label': 'P1 Assets Total Operating Hours', 'type': 'number'},
                {'field': 'p1_failure_count', 'label': 'P1 Assets Failure Count', 'type': 'number'},
                {'field': 'p2_operating_hours', 'label': 'P2 Assets Total Operating Hours', 'type': 'number'},
                {'field': 'p2_failure_count', 'label': 'P2 Assets Failure Count', 'type': 'number'}
            ],
            'Technical Availability Adherence': [
                {'field': 'p1_assets_meeting_target', 'label': 'P1 Assets Meeting >95% Availability', 'type': 'number'},
                {'field': 'p1_total_assets', 'label': 'Total P1 Assets', 'type': 'number'}
            ],
            'MRT (Mean Response Time)': [
                {'field': 'total_response_time_minutes', 'label': 'Total Response Time (minutes)', 'type': 'number'},
                {'field': 'wo_count', 'label': 'Number of Work Orders', 'type': 'number'}
            ],
            'Non Conformances raised': [
                {'field': 'nc_count', 'label': 'Number of Non-Conformances Raised', 'type': 'number'}
            ],
            'Non Conformances closed': [
                {'field': 'nc_closed_on_time', 'label': 'Non-Conformances Closed On Time', 'type': 'number'},
                {'field': 'nc_total', 'label': 'Total Non-Conformances Due', 'type': 'number'}
            ],
            'Mean Time to Deliver a Quote': [
                {'field': 'total_quote_time_hours', 'label': 'Total Quote Delivery Time (hours)', 'type': 'number'},
                {'field': 'quote_count', 'label': 'Number of Quotes Requested', 'type': 'number'}
            ],
            'Purchaser satisfaction': [
                {'field': 'satisfaction_score', 'label': 'Satisfaction Score (0-100)', 'type': 'number'}
            ],
            'Top Breakdown': [
                {'field': 'breakdown_analysis', 'label': 'Breakdown Analysis (Pareto)', 'type': 'text'}
            ],
            'Purchaser Monthly process Confirmation': [
                {'field': 'confirmation_score', 'label': 'Confirmation Score (%)', 'type': 'number'}
            ]
        }
        return fields.get(kpi_name, [])

    def calculate_manual_kpi(self, kpi_name, measurement_period, username=None):
        """Calculate KPI from manual input data"""
        try:
            print(f"Calculating manual KPI: {kpi_name} for {measurement_period}...")
            manual_data = self.get_manual_data(kpi_name, measurement_period)

            if not manual_data:
                print(f"✗ No manual data found for {kpi_name}")
                return {'error': 'No manual data entered for this period'}

            print(f"Found {len(manual_data)} data fields for {kpi_name}")

            # Convert to dict for easier access
            data_dict = {row['data_field']: row['data_value'] or row['data_text'] for row in manual_data}
            print(f"Data fields: {list(data_dict.keys())}")
            print(f"Data values: {data_dict}")

            result = None
            meets_criteria = None
            calculated_text = None

            # Calculate based on KPI type
            if kpi_name == 'FR1':
                accidents = float(data_dict.get('accident_count') or 0)
                hours = float(data_dict.get('hours_worked') or 1)
                if hours > 0:
                    result = (accidents / hours) * 1_000_000
                    meets_criteria = result == 0
                    calculated_text = f"{accidents} accidents per {hours:,.0f} hours worked"

            elif kpi_name == 'Near Miss':
                result = float(data_dict.get('near_miss_count') or 0)
                calculated_text = f"{int(result)} near miss reports"
                meets_criteria = None  # No specific target

            elif kpi_name == 'TTR (Time to Repair) Adherence':
                p1_within = float(data_dict.get('p1_within_target') or 0)
                p1_total = float(data_dict.get('p1_total') or 1)
                if p1_total > 0:
                    result = (p1_within / p1_total) * 100
                    meets_criteria = result >= 95
                    calculated_text = f"{p1_within}/{p1_total} P1 assets within target"

            elif kpi_name == 'MTBF Mean Time Between Failure':
                p1_hours = float(data_dict.get('p1_operating_hours') or 0)
                p1_failures = float(data_dict.get('p1_failure_count') or 1)
                if p1_failures > 0:
                    result = p1_hours / p1_failures
                    meets_criteria = result > 80
                    calculated_text = f"{result:.1f} hours between failures (P1 assets)"

            elif kpi_name == 'Technical Availability Adherence':
                meeting = float(data_dict.get('p1_assets_meeting_target') or 0)
                total = float(data_dict.get('p1_total_assets') or 1)
                if total > 0:
                    result = (meeting / total) * 100
                    meets_criteria = result >= 95
                    calculated_text = f"{meeting}/{total} P1 assets meeting >95% availability"

            elif kpi_name == 'MRT (Mean Response Time)':
                total_time = float(data_dict.get('total_response_time_minutes') or 0)
                wo_count = float(data_dict.get('wo_count') or 1)
                if wo_count > 0:
                    result = total_time / wo_count
                    meets_criteria = result <= 15  # P1 target
                    calculated_text = f"{result:.1f} minutes average response time"

            elif kpi_name == 'Non Conformances raised':
                result = float(data_dict.get('nc_count') or 0)
                meets_criteria = result == 0
                calculated_text = f"{int(result)} non-conformances raised"

            elif kpi_name == 'Non Conformances closed':
                closed = float(data_dict.get('nc_closed_on_time') or 0)
                total = float(data_dict.get('nc_total') or 1)
                if total > 0:
                    result = (closed / total) * 100
                    meets_criteria = result == 100
                    calculated_text = f"{closed}/{total} closed on time"

            elif kpi_name == 'Mean Time to Deliver a Quote':
                total_hours = float(data_dict.get('total_quote_time_hours') or 0)
                quote_count = float(data_dict.get('quote_count') or 1)
                if quote_count > 0:
                    result = total_hours / quote_count
                    meets_criteria = result <= 48
                    calculated_text = f"{result:.1f} hours average delivery time"

            elif kpi_name == 'Purchaser satisfaction':
                result = float(data_dict.get('satisfaction_score') or 0)
                meets_criteria = result >= 90
                calculated_text = f"{result}% satisfaction score"

            elif kpi_name == 'Purchaser Monthly process Confirmation':
                result = float(data_dict.get('confirmation_score') or 0)
                meets_criteria = result >= 90
                calculated_text = f"{result}% confirmation score"

            elif kpi_name == 'Top Breakdown':
                calculated_text = data_dict.get('breakdown_analysis') or 'N/A'
                result = None

            # Save the result
            if result is not None or calculated_text:
                print(f"Saving KPI result: {kpi_name} = {result or calculated_text}")
                self.save_kpi_result(
                    kpi_name=kpi_name,
                    measurement_period=measurement_period,
                    calculated_value=result,
                    calculated_text=calculated_text,
                    meets_criteria=meets_criteria,
                    calculated_by=username
                )
                print(f"✓ {kpi_name} calculated successfully")

            return {
                'value': result,
                'text': calculated_text,
                'meets_criteria': meets_criteria
            }

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            print(f"✗ Error calculating {kpi_name}: {error_msg}")
            return {'error': error_msg}

    def get_all_kpis(self):
        """Get all KPI definitions with standardized format"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT
                    id,
                    kpi_name as name,
                    function_code as category,
                    calculation_method,
                    acceptance_criteria,
                    target_value
                FROM kpi_definitions
                WHERE is_active = TRUE
                ORDER BY function_code, kpi_name
            """)
            results = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in results]
        finally:
            self.pool.return_connection(conn)

    def get_period_results(self, period):
        """Get all KPI results for a specific period with detailed information"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT
                    r.id,
                    d.kpi_name,
                    d.function_code as category,
                    r.measurement_period as period,
                    r.calculated_value as value,
                    d.target_value as target,
                    CASE
                        WHEN r.meets_criteria = TRUE THEN 'Pass'
                        WHEN r.meets_criteria = FALSE THEN 'Fail'
                        ELSE 'Pending'
                    END as status,
                    r.calculated_text as notes,
                    r.updated_date
                FROM kpi_results r
                JOIN kpi_definitions d ON r.kpi_name = d.kpi_name
                WHERE r.measurement_period = %s
                AND d.is_active = TRUE
                ORDER BY d.function_code, d.kpi_name
            """, (period,))
            results = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in results]
        finally:
            self.pool.return_connection(conn)

    def get_kpi_trend(self, kpi_id, months=12):
        """Get KPI trend data for the last N months"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT
                    r.measurement_period as period,
                    r.calculated_value as value,
                    d.target_value as target,
                    CASE
                        WHEN r.meets_criteria = TRUE THEN 'Pass'
                        WHEN r.meets_criteria = FALSE THEN 'Fail'
                        ELSE 'Pending'
                    END as status
                FROM kpi_results r
                JOIN kpi_definitions d ON r.kpi_name = d.kpi_name
                WHERE d.id = %s
                AND r.measurement_period >= TO_CHAR(CURRENT_DATE - INTERVAL '%s months', 'YYYY-MM')
                ORDER BY r.measurement_period ASC
            """, (kpi_id, months))
            results = cursor.fetchall()
            cursor.close()
            return [dict(row) for row in results]
        finally:
            self.pool.return_connection(conn)

    def calculate_single_kpi(self, kpi_id, period):
        """Calculate a single KPI for a specific period"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
            cursor.execute("""
                SELECT kpi_name, calculation_method
                FROM kpi_definitions
                WHERE id = %s AND is_active = TRUE
            """, (kpi_id,))
            kpi = cursor.fetchone()
            cursor.close()

            if not kpi:
                return {'error': 'KPI not found'}

            if kpi['calculation_method'] == 'automatic':
                return self.calculate_kpi(kpi['kpi_name'], period)
            elif kpi['calculation_method'] == 'manual':
                return self.calculate_manual_kpi(kpi['kpi_name'], period)
            else:
                return {'error': 'Unknown calculation method'}
        finally:
            self.pool.return_connection(conn)

    def calculate_all_kpis(self, period):
        """Calculate all automatic KPIs for a period"""
        kpis = self.get_all_kpis()
        results = []

        for kpi in kpis:
            if kpi.get('calculation_method') == 'automatic':
                try:
                    result = self.calculate_kpi(kpi['name'], period)
                    results.append({
                        'kpi_name': kpi['name'],
                        'result': result
                    })
                except Exception as e:
                    print(f"Error calculating {kpi['name']}: {e}")

        return results

    def record_manual_data(self, kpi_id, period, value, notes, username):
        """Record manual KPI data"""
        conn = self.pool.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=extras.RealDictCursor)

            # Get KPI name
            cursor.execute("SELECT kpi_name FROM kpi_definitions WHERE id = %s", (kpi_id,))
            kpi = cursor.fetchone()

            if not kpi:
                raise Exception("KPI not found")

            kpi_name = kpi['kpi_name']

            # Record manual data
            # This is a simplified version - you may need to adjust based on your schema
            cursor.execute("""
                INSERT INTO kpi_manual_data (kpi_name, measurement_period, data_field, data_value, data_text, entered_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (kpi_name, measurement_period, data_field)
                DO UPDATE SET
                    data_value = EXCLUDED.data_value,
                    data_text = EXCLUDED.data_text,
                    entered_by = EXCLUDED.entered_by,
                    updated_date = CURRENT_TIMESTAMP
            """, (kpi_name, period, 'manual_value', value, notes, username))

            conn.commit()
            cursor.close()

        finally:
            self.pool.return_connection(conn)
