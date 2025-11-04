#!/usr/bin/env python3
"""
Test script for KPI system
Verifies database migration, KPI calculations, and data input
"""

import sys
from database_utils import DatabaseConnectionPool
from kpi_database_migration import migrate_kpi_database
from kpi_manager import KPIManager
from datetime import datetime


def test_kpi_system():
    """Test KPI system functionality"""

    print("=" * 60)
    print("KPI SYSTEM TEST")
    print("=" * 60)
    print()

    # Get database connection pool
    pool = DatabaseConnectionPool()

    if pool.pool is None:
        print("❌ ERROR: Database connection pool not initialized.")
        print("   Please run this test from within the main application,")
        print("   or initialize the pool with database credentials first.")
        return False

    print("✓ Database connection pool ready")
    print()

    # Step 1: Run migration
    print("Step 1: Running KPI database migration...")
    try:
        migrate_kpi_database()
        print("✓ Migration completed successfully")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False
    print()

    # Step 2: Initialize KPI Manager
    print("Step 2: Initializing KPI Manager...")
    try:
        kpi_mgr = KPIManager(pool)
        print("✓ KPI Manager initialized")
    except Exception as e:
        print(f"❌ Failed to initialize KPI Manager: {e}")
        return False
    print()

    # Step 3: Get KPI definitions
    print("Step 3: Loading KPI definitions...")
    try:
        kpis = kpi_mgr.get_all_kpi_definitions()
        print(f"✓ Loaded {len(kpis)} KPI definitions:")
        for kpi in kpis:
            print(f"   - {kpi['function_code']}: {kpi['kpi_name']}")
    except Exception as e:
        print(f"❌ Failed to load KPI definitions: {e}")
        return False
    print()

    # Step 4: Test automatic KPI calculation
    print("Step 4: Testing automatic KPI calculations...")
    current_period = datetime.now().strftime('%Y-%m')
    print(f"   Calculation period: {current_period}")
    try:
        results = kpi_mgr.calculate_all_auto_kpis(current_period, 'test_user')
        print("✓ Auto KPI calculations completed:")
        for kpi_name, result in results.items():
            if 'error' in result:
                print(f"   ⚠ {kpi_name}: {result['error']}")
            else:
                print(f"   ✓ {kpi_name}: Success")
    except Exception as e:
        print(f"❌ Failed to calculate auto KPIs: {e}")
        import traceback
        traceback.print_exc()
        return False
    print()

    # Step 5: Test manual data input
    print("Step 5: Testing manual data input...")
    try:
        # Test entering FR1 data
        kpi_mgr.save_manual_data(
            kpi_name='FR1',
            measurement_period=current_period,
            data_field='accident_count',
            data_value=0,
            entered_by='test_user'
        )
        kpi_mgr.save_manual_data(
            kpi_name='FR1',
            measurement_period=current_period,
            data_field='hours_worked',
            data_value=10000,
            entered_by='test_user'
        )
        print("✓ Manual data saved for FR1")

        # Calculate FR1
        result = kpi_mgr.calculate_manual_kpi('FR1', current_period, 'test_user')
        print(f"✓ FR1 calculated: {result}")
    except Exception as e:
        print(f"❌ Failed manual data test: {e}")
        import traceback
        traceback.print_exc()
        return False
    print()

    # Step 6: Get results
    print("Step 6: Retrieving KPI results...")
    try:
        results = kpi_mgr.get_kpi_results(current_period)
        print(f"✓ Retrieved {len(results)} KPI results for {current_period}")
        if results:
            print("\n   Summary:")
            passing = sum(1 for r in results if r.get('meets_criteria') is True)
            failing = sum(1 for r in results if r.get('meets_criteria') is False)
            pending = len(kpis) - len(results)

            print(f"   - Total KPIs: {len(kpis)}")
            print(f"   - Calculated: {len(results)}")
            print(f"   - Passing: {passing}")
            print(f"   - Failing: {failing}")
            print(f"   - Pending: {pending}")
    except Exception as e:
        print(f"❌ Failed to retrieve results: {e}")
        import traceback
        traceback.print_exc()
        return False
    print()

    print("=" * 60)
    print("✓ ALL TESTS PASSED!")
    print("=" * 60)
    print()
    print("KPI System is ready for use!")
    print("Managers can now access the KPI Dashboard from the main application.")
    print()

    return True


if __name__ == "__main__":
    # This script requires database connection to be initialized
    print("This test script should be run after the database is initialized.")
    print("It will test the KPI system components.\n")

    # Import database config if available
    try:
        from AIT_CMMS_REV3 import get_db_config
        pool = DatabaseConnectionPool()
        pool.initialize(get_db_config())
        success = test_kpi_system()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Cannot run standalone test: {e}")
        print("\nTo test the KPI system:")
        print("1. Launch the main application (AIT_CMMS_REV3.py)")
        print("2. Log in as a manager")
        print("3. Navigate to the KPI Dashboard tab")
        sys.exit(1)
