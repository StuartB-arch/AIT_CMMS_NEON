#!/usr/bin/env python3
"""
Test script for PostgreSQL database operations
Tests all major database functions to ensure migration from SQLite3 to PostgreSQL is successful
"""

import psycopg2
from datetime import datetime
import sys

# Database configuration (same as in AIT_CMMS_REV3.py)
DB_CONFIG = {
    'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_2Nm6hyPVWiIH',
    'sslmode': 'require'
}

def test_connection():
    """Test database connection"""
    print("\n" + "=" * 60)
    print("TEST 1: Database Connection")
    print("=" * 60)
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            sslmode=DB_CONFIG.get('sslmode', 'require')
        )
        print("✅ Successfully connected to Neon PostgreSQL database")
        return conn
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return None

def test_tables_exist(conn):
    """Test if all required tables exist"""
    print("\n" + "=" * 60)
    print("TEST 2: Table Existence")
    print("=" * 60)

    required_tables = [
        'equipment',
        'pm_completions',
        'weekly_pm_schedules',
        'corrective_maintenance',
        'work_orders',
        'parts_inventory',
        'mro_inventory',
        'cannot_find_assets',
        'run_to_failure_assets',
        'pm_templates',
        'default_pm_checklist',
        'mro_stock_transactions'
    ]

    cursor = conn.cursor()
    all_exist = True

    for table in required_tables:
        try:
            cursor.execute(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = %s
                )
            """, (table,))
            exists = cursor.fetchone()[0]

            if exists:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"✅ Table '{table}' exists with {count} records")
            else:
                print(f"❌ Table '{table}' does NOT exist")
                all_exist = False
        except Exception as e:
            print(f"❌ Error checking table '{table}': {e}")
            all_exist = False

    return all_exist

def test_equipment_crud(conn):
    """Test CRUD operations on equipment table"""
    print("\n" + "=" * 60)
    print("TEST 3: Equipment Table CRUD Operations")
    print("=" * 60)

    cursor = conn.cursor()
    test_passed = True

    # Test INSERT
    try:
        test_bfm = f"TEST_BFM_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        cursor.execute("""
            INSERT INTO equipment (
                bfm_equipment_no, description, monthly_pm, annual_pm, status
            ) VALUES (%s, %s, %s, %s, %s)
        """, (test_bfm, "Test Equipment", True, True, "Active"))
        conn.commit()
        print(f"✅ INSERT: Successfully created equipment {test_bfm}")
    except Exception as e:
        print(f"❌ INSERT failed: {e}")
        test_passed = False
        return test_passed

    # Test SELECT
    try:
        cursor.execute("SELECT * FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
        result = cursor.fetchone()
        if result:
            print(f"✅ SELECT: Successfully retrieved equipment {test_bfm}")
        else:
            print(f"❌ SELECT: Could not find equipment {test_bfm}")
            test_passed = False
    except Exception as e:
        print(f"❌ SELECT failed: {e}")
        test_passed = False

    # Test UPDATE
    try:
        cursor.execute("""
            UPDATE equipment
            SET description = %s
            WHERE bfm_equipment_no = %s
        """, ("Updated Test Equipment", test_bfm))
        conn.commit()

        cursor.execute("SELECT description FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
        new_desc = cursor.fetchone()[0]
        if new_desc == "Updated Test Equipment":
            print(f"✅ UPDATE: Successfully updated equipment {test_bfm}")
        else:
            print(f"❌ UPDATE: Description not updated correctly")
            test_passed = False
    except Exception as e:
        print(f"❌ UPDATE failed: {e}")
        test_passed = False

    # Test DELETE
    try:
        cursor.execute("DELETE FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
        conn.commit()

        cursor.execute("SELECT * FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
        result = cursor.fetchone()
        if result is None:
            print(f"✅ DELETE: Successfully deleted equipment {test_bfm}")
        else:
            print(f"❌ DELETE: Equipment {test_bfm} still exists")
            test_passed = False
    except Exception as e:
        print(f"❌ DELETE failed: {e}")
        test_passed = False

    return test_passed

def test_mro_inventory(conn):
    """Test MRO inventory operations"""
    print("\n" + "=" * 60)
    print("TEST 4: MRO Inventory Operations")
    print("=" * 60)

    cursor = conn.cursor()
    test_passed = True

    try:
        test_part = f"TEST_PART_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Test INSERT
        cursor.execute("""
            INSERT INTO mro_inventory (
                name, part_number, engineering_system, unit_of_measure,
                quantity_in_stock, minimum_stock, location
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, ("Test Part", test_part, "Mechanical", "EA", 10.0, 5.0, "Test Location"))
        conn.commit()
        print(f"✅ INSERT: Successfully created MRO part {test_part}")

        # Test SELECT
        cursor.execute("SELECT * FROM mro_inventory WHERE part_number = %s", (test_part,))
        result = cursor.fetchone()
        if result:
            print(f"✅ SELECT: Successfully retrieved MRO part {test_part}")
        else:
            print(f"❌ SELECT: Could not find MRO part {test_part}")
            test_passed = False

        # Test UPDATE
        cursor.execute("""
            UPDATE mro_inventory
            SET quantity_in_stock = %s
            WHERE part_number = %s
        """, (20.0, test_part))
        conn.commit()
        print(f"✅ UPDATE: Successfully updated MRO part {test_part}")

        # Test transaction logging
        cursor.execute("""
            INSERT INTO mro_stock_transactions (
                part_number, transaction_type, quantity, technician_name, notes
            ) VALUES (%s, %s, %s, %s, %s)
        """, (test_part, "Add", 10.0, "Test Technician", "Test transaction"))
        conn.commit()
        print(f"✅ Transaction logging: Successfully logged transaction for {test_part}")

        # Cleanup
        cursor.execute("DELETE FROM mro_stock_transactions WHERE part_number = %s", (test_part,))
        cursor.execute("DELETE FROM mro_inventory WHERE part_number = %s", (test_part,))
        conn.commit()
        print(f"✅ CLEANUP: Successfully cleaned up test data")

    except Exception as e:
        print(f"❌ MRO inventory test failed: {e}")
        test_passed = False
        # Try to cleanup even if test failed
        try:
            cursor.execute("DELETE FROM mro_stock_transactions WHERE part_number = %s", (test_part,))
            cursor.execute("DELETE FROM mro_inventory WHERE part_number = %s", (test_part,))
            conn.commit()
        except:
            pass

    return test_passed

def test_pm_operations(conn):
    """Test PM completion operations"""
    print("\n" + "=" * 60)
    print("TEST 5: PM Completion Operations")
    print("=" * 60)

    cursor = conn.cursor()
    test_passed = True

    try:
        # First, get or create a test equipment
        test_bfm = f"TEST_PM_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        cursor.execute("""
            INSERT INTO equipment (
                bfm_equipment_no, description, monthly_pm, status
            ) VALUES (%s, %s, %s, %s)
        """, (test_bfm, "Test PM Equipment", True, "Active"))
        conn.commit()

        # Test PM completion insert
        cursor.execute("""
            INSERT INTO pm_completions (
                bfm_equipment_no, pm_type, technician_name, completion_date, labor_hours
            ) VALUES (%s, %s, %s, %s, %s)
        """, (test_bfm, "Monthly", "Test Technician", datetime.now().strftime('%Y-%m-%d'), 2.5))
        conn.commit()
        print(f"✅ INSERT: Successfully created PM completion for {test_bfm}")

        # Test retrieval
        cursor.execute("""
            SELECT * FROM pm_completions WHERE bfm_equipment_no = %s
        """, (test_bfm,))
        result = cursor.fetchone()
        if result:
            print(f"✅ SELECT: Successfully retrieved PM completion")
        else:
            print(f"❌ SELECT: Could not find PM completion")
            test_passed = False

        # Cleanup
        cursor.execute("DELETE FROM pm_completions WHERE bfm_equipment_no = %s", (test_bfm,))
        cursor.execute("DELETE FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
        conn.commit()
        print(f"✅ CLEANUP: Successfully cleaned up test data")

    except Exception as e:
        print(f"❌ PM operations test failed: {e}")
        test_passed = False
        # Try to cleanup
        try:
            cursor.execute("DELETE FROM pm_completions WHERE bfm_equipment_no = %s", (test_bfm,))
            cursor.execute("DELETE FROM equipment WHERE bfm_equipment_no = %s", (test_bfm,))
            conn.commit()
        except:
            pass

    return test_passed

def test_corrective_maintenance(conn):
    """Test corrective maintenance operations"""
    print("\n" + "=" * 60)
    print("TEST 6: Corrective Maintenance Operations")
    print("=" * 60)

    cursor = conn.cursor()
    test_passed = True

    try:
        test_cm = f"TEST_CM_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Test CM insert
        cursor.execute("""
            INSERT INTO corrective_maintenance (
                cm_number, description, priority, status, reported_by, reported_date
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (test_cm, "Test CM", "High", "Open", "Test User", datetime.now().strftime('%Y-%m-%d')))
        conn.commit()
        print(f"✅ INSERT: Successfully created CM {test_cm}")

        # Test retrieval
        cursor.execute("SELECT * FROM corrective_maintenance WHERE cm_number = %s", (test_cm,))
        result = cursor.fetchone()
        if result:
            print(f"✅ SELECT: Successfully retrieved CM {test_cm}")
        else:
            print(f"❌ SELECT: Could not find CM {test_cm}")
            test_passed = False

        # Cleanup
        cursor.execute("DELETE FROM corrective_maintenance WHERE cm_number = %s", (test_cm,))
        conn.commit()
        print(f"✅ CLEANUP: Successfully cleaned up test data")

    except Exception as e:
        print(f"❌ CM operations test failed: {e}")
        test_passed = False
        try:
            cursor.execute("DELETE FROM corrective_maintenance WHERE cm_number = %s", (test_cm,))
            conn.commit()
        except:
            pass

    return test_passed

def run_all_tests():
    """Run all database tests"""
    print("\n" + "=" * 80)
    print("POSTGRESQL DATABASE MIGRATION TEST SUITE")
    print("Testing migration from SQLite3 to PostgreSQL (Neon)")
    print("=" * 80)

    results = {
        'Connection': False,
        'Tables': False,
        'Equipment CRUD': False,
        'MRO Inventory': False,
        'PM Operations': False,
        'CM Operations': False
    }

    # Test 1: Connection
    conn = test_connection()
    if conn:
        results['Connection'] = True

        # Test 2: Tables
        results['Tables'] = test_tables_exist(conn)

        # Test 3: Equipment CRUD
        results['Equipment CRUD'] = test_equipment_crud(conn)

        # Test 4: MRO Inventory
        results['MRO Inventory'] = test_mro_inventory(conn)

        # Test 5: PM Operations
        results['PM Operations'] = test_pm_operations(conn)

        # Test 6: CM Operations
        results['CM Operations'] = test_corrective_maintenance(conn)

        # Close connection
        conn.close()
        print("\n✅ Database connection closed")

    # Print summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<50} {status}")

    total_tests = len(results)
    passed_tests = sum(1 for p in results.values() if p)

    print("\n" + "=" * 80)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print("=" * 80)

    if passed_tests == total_tests:
        print("\n🎉 ALL TESTS PASSED! PostgreSQL migration successful!")
        return 0
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test(s) failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
