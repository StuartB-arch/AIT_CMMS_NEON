#!/usr/bin/env python3
"""
Database Cleanup Utility - Remove Number Prefixes from Checklist Items
This script cleans up existing PM template checklist items that have accumulated
number prefixes due to the duplication bug. It should be run once after deploying
the fix to AIT_CMMS_REV3.py.
"""

import json
import re
import psycopg2
from database_utils import db_pool

def strip_checklist_numbers(text):
    """
    Strip ALL leading number prefixes from checklist items.
    This is the same function added to AIT_CMMS_REV3.py.
    """
    if not text or not isinstance(text, str):
        return text

    # Remove all leading patterns of "number. " (one or more)
    cleaned = re.sub(r'^(\d+\.\s*)+', '', text.strip())
    return cleaned.strip()

def cleanup_pm_template_checklists():
    """
    Clean up all checklist items in pm_templates table by removing
    any leading number prefixes.
    """
    print("=" * 70)
    print("PM Template Checklist Cleanup Utility")
    print("=" * 70)
    print("\nThis utility will:")
    print("1. Scan all PM templates in the database")
    print("2. Remove any leading number prefixes from checklist items")
    print("3. Update the database with cleaned data")
    print("\nNOTE: This is safe to run multiple times.\n")

    response = input("Do you want to proceed? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Operation cancelled.")
        return

    try:
        # Get connection from pool
        conn = db_pool.get_connection()
        cursor = conn.cursor()

        # Fetch all PM templates
        cursor.execute('''
            SELECT id, bfm_equipment_no, template_name, checklist_items
            FROM pm_templates
            WHERE checklist_items IS NOT NULL
        ''')

        templates = cursor.fetchall()
        print(f"\nFound {len(templates)} templates to process...\n")

        updated_count = 0
        unchanged_count = 0

        for template_id, bfm_no, template_name, checklist_json in templates:
            try:
                # Parse checklist items
                checklist_items = json.loads(checklist_json) if checklist_json else []

                if not checklist_items:
                    continue

                # Clean each item
                cleaned_items = []
                items_changed = False

                for item in checklist_items:
                    cleaned_item = strip_checklist_numbers(item)
                    cleaned_items.append(cleaned_item)

                    # Check if this item was changed
                    if cleaned_item != item:
                        items_changed = True
                        print(f"  [{bfm_no}] {template_name}:")
                        print(f"    Before: '{item}'")
                        print(f"    After:  '{cleaned_item}'")

                # Update database if changes were made
                if items_changed:
                    cursor.execute('''
                        UPDATE pm_templates
                        SET checklist_items = %s, updated_date = CURRENT_TIMESTAMP
                        WHERE id = %s
                    ''', (json.dumps(cleaned_items), template_id))

                    updated_count += 1
                else:
                    unchanged_count += 1

            except Exception as e:
                print(f"  ERROR processing template {template_id} ({bfm_no} - {template_name}): {e}")
                continue

        # Commit changes
        conn.commit()

        print("\n" + "=" * 70)
        print(f"Cleanup completed successfully!")
        print(f"  Templates updated: {updated_count}")
        print(f"  Templates unchanged (already clean): {unchanged_count}")
        print("=" * 70)

        cursor.close()
        db_pool.return_connection(conn)

    except Exception as e:
        print(f"\nERROR: Database operation failed: {e}")
        print("Rolling back changes...")
        if conn:
            conn.rollback()
        raise

def preview_changes():
    """
    Preview what changes would be made without actually updating the database.
    """
    print("=" * 70)
    print("PM Template Checklist Cleanup - PREVIEW MODE")
    print("=" * 70)
    print("\nShowing what would be changed (no database updates)...\n")

    try:
        conn = db_pool.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, bfm_equipment_no, template_name, checklist_items
            FROM pm_templates
            WHERE checklist_items IS NOT NULL
        ''')

        templates = cursor.fetchall()
        print(f"Found {len(templates)} templates\n")

        would_update = 0
        already_clean = 0

        for template_id, bfm_no, template_name, checklist_json in templates:
            try:
                checklist_items = json.loads(checklist_json) if checklist_json else []

                if not checklist_items:
                    continue

                items_changed = False

                for item in checklist_items:
                    cleaned_item = strip_checklist_numbers(item)

                    if cleaned_item != item:
                        if not items_changed:
                            print(f"[{bfm_no}] {template_name}:")
                        items_changed = True
                        print(f"  '{item}' -> '{cleaned_item}'")

                if items_changed:
                    would_update += 1
                    print()
                else:
                    already_clean += 1

            except Exception as e:
                print(f"ERROR reading template {template_id}: {e}\n")
                continue

        print("=" * 70)
        print(f"Preview Summary:")
        print(f"  Would update: {would_update} templates")
        print(f"  Already clean: {already_clean} templates")
        print("=" * 70)

        cursor.close()
        db_pool.return_connection(conn)

    except Exception as e:
        print(f"\nERROR: {e}")
        raise

if __name__ == "__main__":
    print("\nPM Template Checklist Cleanup Utility")
    print("\nOptions:")
    print("  1. Preview changes (safe - no database updates)")
    print("  2. Run cleanup (updates database)")
    print("  3. Exit")

    choice = input("\nEnter choice (1-3): ").strip()

    if choice == "1":
        preview_changes()
    elif choice == "2":
        cleanup_pm_template_checklists()
    else:
        print("Exiting...")
