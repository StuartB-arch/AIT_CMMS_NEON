# PostgreSQL Migration Plan - Remove SQLite3 and SharePoint

## Overview
This document outlines the migration from SQLite3/SharePoint backup system to using only PostgreSQL (Neon) database.

## Current State
- Primary database: PostgreSQL (Neon Cloud Database)
- SQLite3: Used only for backup/restore operations with SharePoint
- SharePoint: Used for cloud backup and data synchronization

## Target State
- Single database: PostgreSQL (Neon) only
- No SharePoint dependencies
- All data stored and managed in Neon PostgreSQL

## Changes Required

### 1. AIT_CMMS_REV3.py Changes

#### Remove Functions (Lines to Delete/Modify):
- `get_sharepoint_backup_path()` - Line 2941
- `sync_database_on_startup()` - Line 2919
- `sharepoint_only_backup()` - Line 3185
- `cleanup_old_backups()` - Line 3228
- `cleanup_local_backups()` - Line 3262
- `manual_sync_from_sharepoint()` - Line 3097
- `sync_database_before_init()` - Line 5084
- `process_sharepoint_excel_file()` - Line 8383
- `show_sharepoint_data_preview()` - Line 8412
- `connect_to_sharepoint_direct()` - Line 8607
- `auto_pull_from_sharepoint()` - Line 8919
- `get_latest_sharepoint_backup()` - Line 14283
- `show_closing_sync_dialog()` - Lines 1453, 14469

#### SQLite3 References to Remove:
- Line 2590: `backup_conn = sqlite3.connect(filepath)`
- Line 2785: `self.conn = sqlite3.connect(current_db_path)`
- Line 2830: `self.conn = sqlite3.connect('ait_cmms_database.db')`
- Line 3210: `self.conn = sqlite3.connect(db_file)`
- Line 3224: `self.conn = sqlite3.connect('ait_cmms_database.db')`
- Line 14692-14693: SQLite connections for merge operations

#### __init__ Method Updates (Line 4709):
- Remove: `self.backup_sync_dir = self.get_sharepoint_backup_path()`
- Remove: `database_synced = self.sync_database_before_init()`
- Remove: `self.sync_database_on_startup()`
- Remove: `self.cleanup_local_backups()`
- Remove: `self.sharepoint_file_modified_time`

#### UI Elements to Remove:
- SharePoint sync button
- Manual sync menu items
- SharePoint backup status messages

### 2. mro_stock_module.py Changes

#### Line 8: Already commented out
```python
#import sqlite3  # Already commented out
```

#### Line 471: Change Exception Type
```python
# OLD:
except sqlite3.IntegrityError:
    messagebox.showerror("Error", "Part number already exists!")

# NEW:
except Exception as e:
    if 'unique constraint' in str(e).lower() or 'duplicate' in str(e).lower():
        messagebox.showerror("Error", "Part number already exists!")
    else:
        raise
```

### 3. requirements.txt Changes

#### Add:
```
psycopg2-binary>=2.9.0
```

#### Current:
```
pandas>=1.3.3
reportlab>=3.6.8
```

### 4. Files to Remove (if they exist):
- `ait_cmms_database.db` (SQLite database file)
- `ait_cmms_database_local_backup.db`
- Any backup files matching `ait_cmms_backup_*.db`

## Testing Plan

### 1. Database Connection Test
- Verify PostgreSQL connection works
- Check all tables are created correctly
- Verify indexes are in place

### 2. CRUD Operations Test
- Equipment table: Create, Read, Update, Delete
- PM Completions: Insert and query
- Corrective Maintenance: All operations
- MRO Inventory: All operations

### 3. Integration Tests
- Login flow
- PM scheduling
- PM completion recording
- CM management
- MRO stock management
- Parts integration with CM

### 4. Performance Test
- Query response times
- Bulk insert operations
- Report generation

## Rollback Plan
If issues arise:
1. Restore from Git: `git checkout <previous-commit>`
2. Database is already in PostgreSQL, no database rollback needed
3. Re-enable SharePoint sync if absolutely necessary

## Migration Steps
1. ✅ Document all changes
2. ⏳ Remove SharePoint functions
3. ⏳ Remove SQLite3 references
4. ⏳ Update exception handling
5. ⏳ Update requirements.txt
6. ⏳ Test all functionality
7. ⏳ Commit and push changes
