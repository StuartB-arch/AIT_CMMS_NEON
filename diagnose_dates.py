#!/usr/bin/env python3
"""
Diagnose date format in corrective_maintenance table
"""
from database_utils import DatabaseConnectionPool

pool = DatabaseConnectionPool()
conn = pool.get_connection()
cursor = conn.cursor()

print("=" * 60)
print("DIAGNOSING CORRECTIVE MAINTENANCE DATE FORMATS")
print("=" * 60)

# Get sample of dates
cursor.execute("""
    SELECT id, cm_number, reported_date, closed_date, status
    FROM corrective_maintenance
    ORDER BY id DESC
    LIMIT 10
""")

results = cursor.fetchall()

print(f"\nFound {len(results)} recent CMs:")
print("-" * 60)

for row in results:
    cm_id, cm_number, reported_date, closed_date, status = row
    print(f"CM #{cm_number}")
    print(f"  Reported Date: '{reported_date}' (type: {type(reported_date)})")
    print(f"  Closed Date: '{closed_date}' (type: {type(closed_date)})")
    print(f"  Status: {status}")
    print()

# Check October 2025 data specifically
print("=" * 60)
print("CHECKING OCTOBER 2025 DATA")
print("=" * 60)

# Try different date formats
formats_to_try = [
    ("YYYY-MM format", "reported_date LIKE '2025-10%'"),
    ("MM/YYYY format", "reported_date LIKE '10/%/2025'"),
    ("Month name", "reported_date LIKE '%October%2025%'"),
    ("Any 2025", "reported_date LIKE '%2025%'"),
    ("Any 10/", "reported_date LIKE '10/%'"),
]

for format_name, query_condition in formats_to_try:
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM corrective_maintenance
        WHERE {query_condition}
    """)
    count = cursor.fetchone()[0]
    print(f"{format_name}: {count} records found")

# Check all open CMs
cursor.execute("""
    SELECT COUNT(*)
    FROM corrective_maintenance
    WHERE status = 'Open' OR closed_date IS NULL OR closed_date = ''
""")
open_count = cursor.fetchone()[0]
print(f"\nTotal Open CMs: {open_count}")

# Show some open CMs from October
cursor.execute("""
    SELECT cm_number, reported_date, status
    FROM corrective_maintenance
    WHERE (status = 'Open' OR closed_date IS NULL OR closed_date = '')
    AND reported_date LIKE '%2025%'
    LIMIT 5
""")
print("\nSample Open CMs:")
for row in cursor.fetchall():
    print(f"  {row[0]}: Reported {row[1]} - Status: {row[2]}")

cursor.close()
pool.return_connection(conn)
