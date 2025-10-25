#!/usr/bin/env python3
"""
MRO Inventory Module Validation Script
Tests all MRO inventory functions and database operations
"""

import psycopg2
from datetime import datetime
import sys
import os

# Database configuration (same as in AIT_CMMS_REV3.py)
DB_CONFIG = {
    'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_2Nm6hyPVWiIH',
    'sslmode': 'require'
}

class TestResults:
    """Track test results"""
    def __init__(self):
        self.tests = {}

    def add(self, test_name, passed, message=""):
        self.tests[test_name] = {'passed': passed, 'message': message}

    def summary(self):
        total = len(self.tests)
        passed = sum(1 for t in self.tests.values() if t['passed'])
        return total, passed, total - passed

def test_database_connection():
    """Test 1: Database Connection"""
    print("\n" + "=" * 80)
    print("TEST 1: Database Connection to PostgreSQL (Neon)")
    print("=" * 80)

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
        print(f"   Host: {DB_CONFIG['host']}")
        print(f"   Database: {DB_CONFIG['database']}")
        return conn, True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return None, False

def test_mro_tables_exist(conn):
    """Test 2: MRO Tables Existence"""
    print("\n" + "=" * 80)
    print("TEST 2: MRO Tables Existence")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    # Check mro_inventory table
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'mro_inventory'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("SELECT COUNT(*) FROM mro_inventory")
            count = cursor.fetchone()[0]
            print(f"✅ Table 'mro_inventory' exists with {count} records")
            results.add('mro_inventory_table', True, f"{count} records")
        else:
            print(f"❌ Table 'mro_inventory' does NOT exist")
            results.add('mro_inventory_table', False, "Table missing")
    except Exception as e:
        print(f"❌ Error checking mro_inventory table: {e}")
        results.add('mro_inventory_table', False, str(e))

    # Check mro_stock_transactions table
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'mro_stock_transactions'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("SELECT COUNT(*) FROM mro_stock_transactions")
            count = cursor.fetchone()[0]
            print(f"✅ Table 'mro_stock_transactions' exists with {count} records")
            results.add('mro_stock_transactions_table', True, f"{count} records")
        else:
            print(f"❌ Table 'mro_stock_transactions' does NOT exist")
            results.add('mro_stock_transactions_table', False, "Table missing")
    except Exception as e:
        print(f"❌ Error checking mro_stock_transactions table: {e}")
        results.add('mro_stock_transactions_table', False, str(e))

    # Check cm_parts_used table (for parts integration with CM)
    try:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'cm_parts_used'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("SELECT COUNT(*) FROM cm_parts_used")
            count = cursor.fetchone()[0]
            print(f"✅ Table 'cm_parts_used' exists with {count} records")
            results.add('cm_parts_used_table', True, f"{count} records")
        else:
            print(f"⚠️  Table 'cm_parts_used' does not exist (may need to be created)")
            results.add('cm_parts_used_table', False, "Table missing - may be optional")
    except Exception as e:
        print(f"⚠️  Error checking cm_parts_used table: {e}")
        results.add('cm_parts_used_table', False, str(e))

    return results

def test_mro_table_schema(conn):
    """Test 3: MRO Table Schema Validation"""
    print("\n" + "=" * 80)
    print("TEST 3: MRO Table Schema Validation")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    # Expected columns for mro_inventory
    expected_columns = [
        'id', 'name', 'part_number', 'model_number', 'equipment', 'engineering_system',
        'unit_of_measure', 'quantity_in_stock', 'unit_price', 'minimum_stock',
        'supplier', 'location', 'rack', 'row', 'bin', 'picture_1_path',
        'picture_2_path', 'notes', 'last_updated', 'created_date', 'status'
    ]

    try:
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'mro_inventory'
            ORDER BY ordinal_position
        """)

        columns = cursor.fetchall()
        column_names = [col[0] for col in columns]

        print(f"\n📋 Found {len(columns)} columns in mro_inventory table:")
        for col_name, data_type, nullable in columns:
            print(f"   - {col_name:20} {data_type:15} {'NULL' if nullable == 'YES' else 'NOT NULL'}")

        # Check for missing columns
        missing = set(expected_columns) - set(column_names)
        if missing:
            print(f"\n⚠️  Missing columns: {missing}")
            results.add('mro_inventory_schema', False, f"Missing: {missing}")
        else:
            print(f"\n✅ All expected columns present")
            results.add('mro_inventory_schema', True, "All columns present")

    except Exception as e:
        print(f"❌ Error checking schema: {e}")
        results.add('mro_inventory_schema', False, str(e))

    return results

def test_mro_add_part(conn):
    """Test 4: Add MRO Part"""
    print("\n" + "=" * 80)
    print("TEST 4: Add MRO Part Function")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    test_part_number = f"TEST_MRO_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        # Insert test part
        cursor.execute('''
            INSERT INTO mro_inventory (
                name, part_number, model_number, equipment, engineering_system,
                unit_of_measure, quantity_in_stock, unit_price, minimum_stock,
                supplier, location, rack, row, bin, notes, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            "Test Bearing Assembly",
            test_part_number,
            "MODEL-123",
            "Conveyor Belt A",
            "Mechanical",
            "EA",
            25.0,
            145.50,
            10.0,
            "ABC Supplies Inc",
            "Warehouse A",
            "R-12",
            "Row-3",
            "Bin-45",
            "Test part for validation",
            "Active"
        ))

        conn.commit()
        print(f"✅ Successfully added test part: {test_part_number}")

        # Verify insertion
        cursor.execute("SELECT * FROM mro_inventory WHERE part_number = %s", (test_part_number,))
        result = cursor.fetchone()

        if result:
            print(f"✅ Part verified in database")
            print(f"   Part Number: {result[2]}")
            print(f"   Name: {result[1]}")
            print(f"   Quantity: {result[7]} {result[6]}")
            print(f"   Location: {result[11]}")
            results.add('add_part', True, f"Added {test_part_number}")
        else:
            print(f"❌ Part not found after insertion")
            results.add('add_part', False, "Verification failed")

        return results, test_part_number

    except Exception as e:
        print(f"❌ Failed to add part: {e}")
        results.add('add_part', False, str(e))
        return results, None

def test_mro_update_part(conn, part_number):
    """Test 5: Update MRO Part"""
    print("\n" + "=" * 80)
    print("TEST 5: Update MRO Part Function")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    if not part_number:
        print("⚠️  Skipping - no test part available")
        results.add('update_part', False, "No test part")
        return results

    try:
        # Update the test part
        new_quantity = 50.0
        new_price = 175.00
        new_location = "Warehouse B"

        cursor.execute('''
            UPDATE mro_inventory SET
                quantity_in_stock = %s,
                unit_price = %s,
                location = %s,
                last_updated = %s
            WHERE part_number = %s
        ''', (new_quantity, new_price, new_location,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S'), part_number))

        conn.commit()
        print(f"✅ Successfully updated part: {part_number}")

        # Verify update
        cursor.execute("SELECT quantity_in_stock, unit_price, location FROM mro_inventory WHERE part_number = %s",
                      (part_number,))
        result = cursor.fetchone()

        if result:
            qty, price, location = result
            if qty == new_quantity and price == new_price and location == new_location:
                print(f"✅ Update verified:")
                print(f"   Quantity: {qty}")
                print(f"   Price: ${price}")
                print(f"   Location: {location}")
                results.add('update_part', True, "Update successful")
            else:
                print(f"❌ Update verification failed")
                results.add('update_part', False, "Values don't match")
        else:
            print(f"❌ Part not found after update")
            results.add('update_part', False, "Part not found")

    except Exception as e:
        print(f"❌ Failed to update part: {e}")
        results.add('update_part', False, str(e))

    return results

def test_mro_stock_transaction(conn, part_number):
    """Test 6: Stock Transaction Function"""
    print("\n" + "=" * 80)
    print("TEST 6: Stock Transaction Function")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    if not part_number:
        print("⚠️  Skipping - no test part available")
        results.add('stock_transaction', False, "No test part")
        return results

    try:
        # Get current stock
        cursor.execute("SELECT quantity_in_stock FROM mro_inventory WHERE part_number = %s",
                      (part_number,))
        current_stock = cursor.fetchone()[0]
        print(f"📊 Current stock: {current_stock}")

        # Add stock transaction
        transaction_qty = 10.0
        cursor.execute('''
            INSERT INTO mro_stock_transactions (
                part_number, transaction_type, quantity, technician_name,
                work_order, notes
            ) VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            part_number,
            "Add",
            transaction_qty,
            "Test Technician",
            "WO-12345",
            "Test stock addition"
        ))

        # Update stock
        new_stock = current_stock + transaction_qty
        cursor.execute('''
            UPDATE mro_inventory
            SET quantity_in_stock = %s, last_updated = %s
            WHERE part_number = %s
        ''', (new_stock, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), part_number))

        conn.commit()
        print(f"✅ Stock transaction logged and stock updated")

        # Verify transaction
        cursor.execute("""
            SELECT transaction_type, quantity, technician_name
            FROM mro_stock_transactions
            WHERE part_number = %s
            ORDER BY transaction_date DESC
            LIMIT 1
        """, (part_number,))

        trans = cursor.fetchone()
        if trans:
            print(f"✅ Transaction verified:")
            print(f"   Type: {trans[0]}")
            print(f"   Quantity: {trans[1]}")
            print(f"   Technician: {trans[2]}")

            # Verify stock updated
            cursor.execute("SELECT quantity_in_stock FROM mro_inventory WHERE part_number = %s",
                          (part_number,))
            updated_stock = cursor.fetchone()[0]
            print(f"   New Stock: {updated_stock}")

            if updated_stock == new_stock:
                results.add('stock_transaction', True, "Transaction successful")
            else:
                results.add('stock_transaction', False, "Stock not updated correctly")
        else:
            print(f"❌ Transaction not logged")
            results.add('stock_transaction', False, "Transaction not found")

    except Exception as e:
        print(f"❌ Stock transaction failed: {e}")
        results.add('stock_transaction', False, str(e))

    return results

def test_mro_search_filter(conn):
    """Test 7: Search and Filter Functions"""
    print("\n" + "=" * 80)
    print("TEST 7: Search and Filter Functions")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    try:
        # Test search by name
        cursor.execute("""
            SELECT COUNT(*) FROM mro_inventory
            WHERE LOWER(name) LIKE %s
        """, ('%bearing%',))
        bearing_count = cursor.fetchone()[0]
        print(f"✅ Search by name (bearing): {bearing_count} results")
        results.add('search_by_name', True, f"{bearing_count} results")

        # Test filter by engineering system
        cursor.execute("""
            SELECT engineering_system, COUNT(*)
            FROM mro_inventory
            GROUP BY engineering_system
        """)
        systems = cursor.fetchall()
        print(f"\n✅ Filter by Engineering System:")
        for system, count in systems:
            print(f"   - {system or 'N/A'}: {count} parts")
        results.add('filter_by_system', True, f"{len(systems)} systems")

        # Test low stock filter
        cursor.execute("""
            SELECT COUNT(*) FROM mro_inventory
            WHERE quantity_in_stock < minimum_stock
        """)
        low_stock_count = cursor.fetchone()[0]
        print(f"\n✅ Low stock filter: {low_stock_count} items below minimum")
        results.add('low_stock_filter', True, f"{low_stock_count} items")

        # Test status filter
        cursor.execute("""
            SELECT status, COUNT(*)
            FROM mro_inventory
            GROUP BY status
        """)
        statuses = cursor.fetchall()
        print(f"\n✅ Filter by Status:")
        for status, count in statuses:
            print(f"   - {status}: {count} parts")
        results.add('filter_by_status', True, f"{len(statuses)} statuses")

    except Exception as e:
        print(f"❌ Search/filter test failed: {e}")
        results.add('search_filter', False, str(e))

    return results

def test_mro_inventory_stats(conn):
    """Test 8: Inventory Statistics"""
    print("\n" + "=" * 80)
    print("TEST 8: Inventory Statistics")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    try:
        # Total parts count
        cursor.execute("SELECT COUNT(*) FROM mro_inventory WHERE status = 'Active'")
        total_parts = cursor.fetchone()[0]
        print(f"✅ Total Active Parts: {total_parts}")

        # Total inventory value
        cursor.execute("SELECT SUM(quantity_in_stock * unit_price) FROM mro_inventory WHERE status = 'Active'")
        total_value = cursor.fetchone()[0] or 0
        print(f"✅ Total Inventory Value: ${total_value:,.2f}")

        # Low stock count
        cursor.execute("""
            SELECT COUNT(*) FROM mro_inventory
            WHERE quantity_in_stock < minimum_stock AND status = 'Active'
        """)
        low_stock = cursor.fetchone()[0]
        print(f"✅ Low Stock Items: {low_stock}")

        # Average unit price
        cursor.execute("SELECT AVG(unit_price) FROM mro_inventory WHERE status = 'Active'")
        avg_price = cursor.fetchone()[0] or 0
        print(f"✅ Average Unit Price: ${avg_price:.2f}")

        results.add('inventory_stats', True, f"{total_parts} parts, ${total_value:,.2f} value")

    except Exception as e:
        print(f"❌ Statistics test failed: {e}")
        results.add('inventory_stats', False, str(e))

    return results

def test_mro_indexes(conn):
    """Test 9: Database Indexes"""
    print("\n" + "=" * 80)
    print("TEST 9: Database Indexes")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'mro_inventory'
        """)

        indexes = cursor.fetchall()
        if indexes:
            print(f"✅ Found {len(indexes)} indexes on mro_inventory:")
            for idx_name, idx_def in indexes:
                print(f"   - {idx_name}")
            results.add('indexes', True, f"{len(indexes)} indexes")
        else:
            print(f"⚠️  No indexes found (may impact performance)")
            results.add('indexes', False, "No indexes")

    except Exception as e:
        print(f"❌ Index check failed: {e}")
        results.add('indexes', False, str(e))

    return results

def test_mro_delete_part(conn, part_number):
    """Test 10: Delete MRO Part"""
    print("\n" + "=" * 80)
    print("TEST 10: Delete MRO Part Function")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    if not part_number:
        print("⚠️  Skipping - no test part available")
        results.add('delete_part', False, "No test part")
        return results

    try:
        # First delete related transactions
        cursor.execute("DELETE FROM mro_stock_transactions WHERE part_number = %s", (part_number,))
        trans_deleted = cursor.rowcount
        print(f"✅ Deleted {trans_deleted} transaction(s)")

        # Delete the part
        cursor.execute("DELETE FROM mro_inventory WHERE part_number = %s", (part_number,))
        conn.commit()

        if cursor.rowcount > 0:
            print(f"✅ Successfully deleted part: {part_number}")

            # Verify deletion
            cursor.execute("SELECT * FROM mro_inventory WHERE part_number = %s", (part_number,))
            if cursor.fetchone() is None:
                print(f"✅ Deletion verified")
                results.add('delete_part', True, f"Deleted {part_number}")
            else:
                print(f"❌ Part still exists after deletion")
                results.add('delete_part', False, "Part not deleted")
        else:
            print(f"⚠️  Part not found for deletion")
            results.add('delete_part', False, "Part not found")

    except Exception as e:
        print(f"❌ Failed to delete part: {e}")
        results.add('delete_part', False, str(e))

    return results

def test_foreign_key_constraints(conn):
    """Test 11: Foreign Key Constraints"""
    print("\n" + "=" * 80)
    print("TEST 11: Foreign Key Constraints")
    print("=" * 80)

    results = TestResults()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                tc.constraint_name,
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = 'mro_stock_transactions'
        """)

        fks = cursor.fetchall()
        if fks:
            print(f"✅ Found {len(fks)} foreign key constraint(s):")
            for constraint_name, table, column, foreign_table, foreign_column in fks:
                print(f"   - {table}.{column} -> {foreign_table}.{foreign_column}")
            results.add('foreign_keys', True, f"{len(fks)} constraints")
        else:
            print(f"⚠️  No foreign key constraints found")
            results.add('foreign_keys', False, "No constraints")

    except Exception as e:
        print(f"❌ Foreign key check failed: {e}")
        results.add('foreign_keys', False, str(e))

    return results

def run_all_mro_tests():
    """Run all MRO inventory validation tests"""
    print("\n" + "=" * 100)
    print("MRO INVENTORY MODULE VALIDATION TEST SUITE")
    print("Testing all MRO inventory functions and database operations")
    print("=" * 100)

    all_results = {}
    test_part_number = None

    # Test 1: Database Connection
    conn, success = test_database_connection()
    all_results['Database Connection'] = success

    if not conn:
        print("\n❌ Cannot proceed without database connection")
        return 1

    try:
        # Test 2: Tables Exist
        test_results = test_mro_tables_exist(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Table: {test_name}"] = result['passed']

        # Test 3: Table Schema
        test_results = test_mro_table_schema(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Schema: {test_name}"] = result['passed']

        # Test 4: Add Part
        test_results, test_part_number = test_mro_add_part(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Add: {test_name}"] = result['passed']

        # Test 5: Update Part
        test_results = test_mro_update_part(conn, test_part_number)
        for test_name, result in test_results.tests.items():
            all_results[f"Update: {test_name}"] = result['passed']

        # Test 6: Stock Transaction
        test_results = test_mro_stock_transaction(conn, test_part_number)
        for test_name, result in test_results.tests.items():
            all_results[f"Transaction: {test_name}"] = result['passed']

        # Test 7: Search and Filter
        test_results = test_mro_search_filter(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Search: {test_name}"] = result['passed']

        # Test 8: Statistics
        test_results = test_mro_inventory_stats(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Stats: {test_name}"] = result['passed']

        # Test 9: Indexes
        test_results = test_mro_indexes(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"Index: {test_name}"] = result['passed']

        # Test 10: Foreign Keys
        test_results = test_foreign_key_constraints(conn)
        for test_name, result in test_results.tests.items():
            all_results[f"FK: {test_name}"] = result['passed']

        # Test 11: Delete Part (cleanup)
        test_results = test_mro_delete_part(conn, test_part_number)
        for test_name, result in test_results.tests.items():
            all_results[f"Delete: {test_name}"] = result['passed']

    finally:
        conn.close()
        print("\n✅ Database connection closed")

    # Print final summary
    print("\n" + "=" * 100)
    print("VALIDATION TEST SUMMARY")
    print("=" * 100)

    passed_tests = 0
    failed_tests = 0

    for test_name, passed in sorted(all_results.items()):
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<70} {status}")
        if passed:
            passed_tests += 1
        else:
            failed_tests += 1

    total_tests = len(all_results)

    print("\n" + "=" * 100)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests} ({passed_tests/total_tests*100:.1f}%)")
    print(f"Failed: {failed_tests} ({failed_tests/total_tests*100:.1f}%)")
    print("=" * 100)

    if failed_tests == 0:
        print("\n🎉 ALL MRO INVENTORY TESTS PASSED!")
        print("✅ MRO Inventory module is fully operational")
        print("✅ Database connections are working correctly")
        return 0
    else:
        print(f"\n⚠️  {failed_tests} test(s) failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    exit_code = run_all_mro_tests()
    sys.exit(exit_code)
