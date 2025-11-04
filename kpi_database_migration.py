"""
KPI Database Migration Script
Creates tables for 2025 KPI tracking and management
"""

import psycopg2
from database_utils import DatabaseConnectionPool


def create_kpi_tables(cursor):
    """Create KPI-related database tables"""

    # Table 1: KPI Definitions (from Excel file)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kpi_definitions (
            id SERIAL PRIMARY KEY,
            function_code TEXT NOT NULL,
            kpi_name TEXT NOT NULL UNIQUE,
            description TEXT,
            formula TEXT,
            acceptance_criteria TEXT,
            frequency TEXT,
            data_source TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_date TIMESTAMP
        )
    """)

    # Table 2: KPI Manual Data Input (for missing data that needs manual entry)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kpi_manual_data (
            id SERIAL PRIMARY KEY,
            kpi_name TEXT NOT NULL,
            measurement_period TEXT NOT NULL,  -- e.g., '2025-01', 'Q1-2025'
            data_field TEXT NOT NULL,  -- e.g., 'accident_count', 'hours_worked'
            data_value NUMERIC,
            data_text TEXT,
            notes TEXT,
            entered_by TEXT,
            entered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (kpi_name) REFERENCES kpi_definitions(kpi_name) ON DELETE CASCADE,
            UNIQUE(kpi_name, measurement_period, data_field)
        )
    """)

    # Table 3: KPI Calculated Results (stores final KPI values)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kpi_results (
            id SERIAL PRIMARY KEY,
            kpi_name TEXT NOT NULL,
            measurement_period TEXT NOT NULL,  -- e.g., '2025-01', 'Q1-2025'
            calculated_value NUMERIC,
            calculated_text TEXT,
            target_value NUMERIC,
            meets_criteria BOOLEAN,
            calculation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            calculated_by TEXT,
            notes TEXT,
            FOREIGN KEY (kpi_name) REFERENCES kpi_definitions(kpi_name) ON DELETE CASCADE,
            UNIQUE(kpi_name, measurement_period)
        )
    """)

    # Table 4: KPI Export History
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kpi_exports (
            id SERIAL PRIMARY KEY,
            export_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            export_period TEXT,
            export_type TEXT,  -- 'PDF', 'Excel'
            exported_by TEXT,
            file_name TEXT,
            kpi_count INTEGER,
            notes TEXT
        )
    """)

    print("✓ KPI tables created successfully")


def insert_kpi_definitions(cursor):
    """Insert KPI definitions from the Excel file"""

    kpi_data = [
        ('F1', 'FR1', 'Injury frequency rate',
         'number Accident (with sick leave > 24h) / nb hours worked x 1,000,000',
         '0', 'Monthly but rolling KPI measured on 12 last months', 'Supplier Own Record'),

        ('F1', 'Near Miss', 'Near miss (hazardous situations which might generate an accident) to report is the basis for solid safety management in undustry (birds pyramid)',
         'N/A', 'Raise when near miss identified', 'Monthly', 'Supplier own record'),

        ('F2.1', 'TTR (Time to Repair) Adherence',
         'Time to Repair Adherence, KPI which measures the adherence to a fixed time required to troubleshoot and a repair failed equipment',
         '(number of maintenance Andons with time to repair within 2 hours / number of maintenance received) x 100%',
         'P1 asset <2hours P2 asset <4hours P3 asset <10hours P4 asset <24hours',
         'Monthly', 'Maintenance provider'),

        ('F2.1', 'MTBF Mean Time Between Failure', 'Average time between asset breakdown',
         'MTBF= Total operating time / Number of work order with operations disruption',
         'P1 assets >80hours P2 assets >40hours', 'Monthly', 'Maintenance provider'),

        ('F2.1', 'Technical Availability Adherence',
         'Technical availability for asset "x" is the percentage of planned production time without unexpected downtime due to maintenance needs',
         '(nb of assets with Technical Availability reached / nb of assets) x 100%',
         'P1 Critical assets >95% just for P1 Assets', 'Monthly', 'Maintenance provider'),

        ('F2.1', 'MRT (Mean Response Time)',
         'Time from a maintenance request to time of response being the time when the maintenance workforce arrives at the asset',
         'Sum (response time)/ number of work order with operations disruption',
         'P1 asset <15 minutes P2 assets < 1 hour P3 assets <3 hour P4 assets < 4 hours',
         'Monthly', 'Maintenance provider'),

        ('F2.1', 'WO opened vs WO closed',
         'number of WO opened in a month vs number of WO closed in the same month',
         'number of WO open vs number of WO closed',
         'No >40 open WO', 'Monthly', 'Maintenance provider'),

        ('F2.1', 'WO Backlog', 'Number of WO open at a point in time',
         'Total of WO open', '<10% of the WO raised in a month', 'Monthly', 'Maintenance provider'),

        ('F2.1', 'WO age profile', 'Age of open WO',
         'Age of work order', 'Nb of WO to exceed 60 days', 'Monthly', 'Maintenance provider'),

        ('F2.2', 'Preventive Maintenance Adherence',
         'Adherence to preventive maintenance work orders scheduled',
         '(number of WO completed / number of WO scheduled) x 100%',
         '>95%', 'Monthly', 'Maintenance provider'),

        ('F4.2', 'Top Breakdown', 'Top Break Down Analysis',
         'NA', 'Pareto of failure on critical assets and recurring disruption',
         'Monthly', 'Maintenance provider'),

        ('F4.3', 'Purchaser Monthly process Confirmation', 'Monthly go look see routine result',
         'NA', 'Score of >90% all actions tracked and resolved within 1 week',
         'Monthly', 'Maintenance provider'),

        ('F4 and all functions', 'Purchaser satisfaction', 'Customer Satisfaction Survey',
         'Yearly satisfaction survey', '1/year', 'Quarterly', 'local'),

        ('All Functions', 'Non Conformances raised', 'Number of Non Conformances raised',
         'NC Count', '0', 'Monthly', 'Local'),

        ('All functions', 'Non Conformances closed',
         'Number of Non Comformance fixed and closed within the contractual timeframe',
         'NC closed before due date count', '100% closed in contractual timeframe',
         'Monthly', 'Contractual'),

        ('F7.1', 'Mean Time to Deliver a Quote',
         'Mean time to deliver a quote for standard requests',
         'Average of lead-time hit for each request', '<48 hours by criticality',
         'Monthly', 'Maintenance provider'),
    ]

    for kpi in kpi_data:
        cursor.execute("""
            INSERT INTO kpi_definitions
            (function_code, kpi_name, description, formula, acceptance_criteria, frequency, data_source)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (kpi_name) DO NOTHING
        """, kpi)

    print(f"✓ Inserted {len(kpi_data)} KPI definitions")


def migrate_kpi_database():
    """Main migration function"""
    try:
        # Get database connection
        pool = DatabaseConnectionPool()

        # Check if pool is initialized, if not, we need connection info
        if pool.pool is None:
            print("Error: Database connection pool not initialized.")
            print("Please run this migration from within the main application or initialize the pool first.")
            return False

        conn = pool.get_connection()
        cursor = conn.cursor()

        print("Starting KPI database migration...")

        # Create tables
        create_kpi_tables(cursor)

        # Insert KPI definitions
        insert_kpi_definitions(cursor)

        # Commit changes
        conn.commit()

        print("\n✓ KPI database migration completed successfully!")

        # Cleanup
        cursor.close()
        pool.return_connection(conn)

        return True

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        if conn:
            conn.rollback()
        return False


if __name__ == "__main__":
    print("This script should be run from within the main application.")
    print("Import and call migrate_kpi_database() after initializing the connection pool.")
