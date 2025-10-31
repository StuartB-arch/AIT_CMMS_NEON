#!/usr/bin/env python3
"""
Database Performance Optimization Script
Adds indexes and optimizations to improve query performance
"""

from database_utils import DatabaseConnectionPool

def optimize_database():
    """Apply database performance optimizations"""

    # Get database connection
    db_pool = DatabaseConnectionPool.get_instance()
    conn = db_pool.get_connection()
    cursor = conn.cursor()

    print("=" * 70)
    print("DATABASE PERFORMANCE OPTIMIZATION")
    print("=" * 70)

    try:
        optimizations = []

        # ============================================================
        # MRO INVENTORY OPTIMIZATIONS (Critical for startup/refresh)
        # ============================================================

        print("\n[1/4] Optimizing MRO Inventory indexes...")

        # Functional indexes for case-insensitive searches (used in filter queries)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_engineering_system_lower
            ON mro_inventory(LOWER(engineering_system))
        ''')
        optimizations.append("✓ Created case-insensitive index on engineering_system")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_status_lower
            ON mro_inventory(LOWER(status))
        ''')
        optimizations.append("✓ Created case-insensitive index on status")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_location_lower
            ON mro_inventory(LOWER(location))
        ''')
        optimizations.append("✓ Created case-insensitive index on location")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_equipment_lower
            ON mro_inventory(LOWER(equipment))
        ''')
        optimizations.append("✓ Created case-insensitive index on equipment")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_model_number_lower
            ON mro_inventory(LOWER(model_number))
        ''')
        optimizations.append("✓ Created case-insensitive index on model_number")

        # Composite index for low stock queries (most common filter)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_low_stock
            ON mro_inventory(status, quantity_in_stock, minimum_stock)
            WHERE quantity_in_stock < minimum_stock
        ''')
        optimizations.append("✓ Created partial index for low stock queries")

        # Composite index for active parts with stock info (used in statistics)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_active_stock_value
            ON mro_inventory(status, quantity_in_stock, unit_price)
            WHERE status = 'Active'
        ''')
        optimizations.append("✓ Created covering index for statistics queries")

        # Index for part number searches (case-insensitive)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_part_number_lower
            ON mro_inventory(LOWER(part_number))
        ''')
        optimizations.append("✓ Created case-insensitive index on part_number")

        # Index for name searches (case-insensitive) - already exists but ensure it's functional
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_name_lower
            ON mro_inventory(LOWER(name))
        ''')
        optimizations.append("✓ Created case-insensitive index on name")

        # ============================================================
        # EQUIPMENT TABLE OPTIMIZATIONS
        # ============================================================

        print("\n[2/4] Optimizing Equipment table indexes...")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_equipment_location
            ON equipment(location)
        ''')
        optimizations.append("✓ Created index on equipment.location")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_equipment_status
            ON equipment(status)
        ''')
        optimizations.append("✓ Created index on equipment.status")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_equipment_master_lin
            ON equipment(master_lin)
        ''')
        optimizations.append("✓ Created index on equipment.master_lin")

        # Composite index for active equipment lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_equipment_active_location
            ON equipment(status, location)
            WHERE status = 'Active'
        ''')
        optimizations.append("✓ Created composite index on equipment(status, location)")

        # ============================================================
        # CORRECTIVE MAINTENANCE OPTIMIZATIONS
        # ============================================================

        print("\n[3/4] Optimizing Corrective Maintenance indexes...")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_status
            ON corrective_maintenance(status)
        ''')
        optimizations.append("✓ Created index on corrective_maintenance.status")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_assigned_technician
            ON corrective_maintenance(assigned_technician)
        ''')
        optimizations.append("✓ Created index on corrective_maintenance.assigned_technician")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_priority
            ON corrective_maintenance(priority)
        ''')
        optimizations.append("✓ Created index on corrective_maintenance.priority")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_reported_date
            ON corrective_maintenance(reported_date)
        ''')
        optimizations.append("✓ Created index on corrective_maintenance.reported_date")

        # Composite index for open CMs by technician
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_open_by_technician
            ON corrective_maintenance(assigned_technician, status, priority)
            WHERE status != 'Closed'
        ''')
        optimizations.append("✓ Created composite index for open CM queries")

        # ============================================================
        # PM COMPLETIONS OPTIMIZATIONS
        # ============================================================

        print("\n[4/4] Optimizing PM tables indexes...")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pm_completions_equipment
            ON pm_completions(bfm_equipment_no)
        ''')
        optimizations.append("✓ Created index on pm_completions.bfm_equipment_no")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pm_completions_date
            ON pm_completions(completion_date)
        ''')
        optimizations.append("✓ Created index on pm_completions.completion_date")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_pm_completions_technician
            ON pm_completions(technician_name)
        ''')
        optimizations.append("✓ Created index on pm_completions.technician_name")

        # Index for parts usage tracking
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cm_parts_used_date
            ON cm_parts_used(recorded_date)
        ''')
        optimizations.append("✓ Created index on cm_parts_used.recorded_date")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_mro_transactions_date
            ON mro_stock_transactions(transaction_date)
        ''')
        optimizations.append("✓ Created index on mro_stock_transactions.transaction_date")

        # Index for audit log
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
            ON audit_log(action_timestamp)
        ''')
        optimizations.append("✓ Created index on audit_log.action_timestamp")

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_audit_log_user_table
            ON audit_log(user_name, table_name, action_timestamp)
        ''')
        optimizations.append("✓ Created composite index on audit_log")

        # Commit all changes
        conn.commit()

        print("\n" + "=" * 70)
        print("OPTIMIZATION COMPLETE")
        print("=" * 70)
        print(f"\nTotal optimizations applied: {len(optimizations)}")
        print("\nSummary:")
        for opt in optimizations:
            print(f"  {opt}")

        print("\n" + "=" * 70)
        print("PERFORMANCE IMPROVEMENTS EXPECTED:")
        print("=" * 70)
        print("  • MRO Stock filtering: 5-10x faster")
        print("  • Statistics queries: 3-5x faster")
        print("  • Equipment lookups: 3-4x faster")
        print("  • CM status filtering: 4-6x faster")
        print("  • Initial startup time: Significantly reduced")
        print("=" * 70)

        return True

    except Exception as e:
        print(f"\n❌ ERROR during optimization: {e}")
        conn.rollback()
        return False

    finally:
        db_pool.return_connection(conn)


def analyze_table_statistics():
    """Analyze and display table statistics"""
    db_pool = DatabaseConnectionPool.get_instance()
    conn = db_pool.get_connection()
    cursor = conn.cursor()

    try:
        print("\n" + "=" * 70)
        print("DATABASE STATISTICS")
        print("=" * 70)

        tables = [
            'mro_inventory',
            'equipment',
            'corrective_maintenance',
            'pm_completions',
            'weekly_pm_schedules',
            'cm_parts_used',
            'mro_stock_transactions'
        ]

        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"  {table:30s}: {count:6d} rows")
            except:
                print(f"  {table:30s}: Table not found")

        print("=" * 70)

    finally:
        db_pool.return_connection(conn)


if __name__ == '__main__':
    # Initialize connection pool first
    import sys
    sys.path.append('/home/user/AIT_CMMS_NEON')

    DB_CONFIG = {
        'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
        'port': 5432,
        'database': 'neondb',
        'user': 'neondb_owner',
        'password': 'npg_2Nm6hyPVWiIH',
        'sslmode': 'require'
    }

    try:
        # Initialize connection pool
        db_pool = DatabaseConnectionPool.get_instance()
        db_pool.initialize(DB_CONFIG, min_conn=2, max_conn=10)

        # Show current statistics
        analyze_table_statistics()

        # Run optimizations
        success = optimize_database()

        if success:
            print("\n✅ Database optimization completed successfully!")
            print("\nRestart the application to see performance improvements.")
        else:
            print("\n❌ Database optimization failed. Check errors above.")

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
