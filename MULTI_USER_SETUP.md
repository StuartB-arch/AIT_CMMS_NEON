# Multi-User Support Setup Guide

## Overview

The AIT CMMS system has been upgraded to support **3-5 concurrent users** with the following features:

- **Database Connection Pooling**: Efficient management of PostgreSQL connections
- **User Authentication**: Database-backed user accounts with hashed passwords
- **Session Tracking**: Monitor active users and their activity
- **Audit Logging**: Complete trail of all database changes
- **Optimistic Concurrency Control**: Prevent data conflicts between users
- **Role-Based Access**: Manager and Technician roles with different permissions

## Installation Steps

### Step 1: Run the Migration Script

The migration script will set up all required tables and create default users.

```bash
cd /home/user/AIT_CMMS_NEON
python3 migrate_multiuser.py
```

This will create:
- `users` table - User accounts and authentication
- `user_sessions` table - Active session tracking
- `audit_log` table - Complete change history
- Version columns in all existing tables
- Performance indexes

### Step 2: Default User Accounts

The migration creates the following accounts:

**Manager Account:**
- Username: `manager`
- Password: `AIT2584`
- Full Access: All system functions

**Technician Accounts:**
- Mark Michaels: username=`mmichaels`, password=`mmichaels`
- Jerone Bosarge: username=`jbosarge`, password=`jbosarge`
- Jon Hymel: username=`jhymel`, password=`jhymel`
- Nick Whisenant: username=`nwhisenant`, password=`nwhisenant`
- James Dunnam: username=`jdunnam`, password=`jdunnam`
- Wayne Dunnam: username=`wdunnam`, password=`wdunnam`
- Nate Williams: username=`nwilliams`, password=`nwilliams`
- Rey Marikit: username=`rmarikit`, password=`rmarikit`
- Ronald Houghs: username=`rhoughs`, password=`rhoughs`

**IMPORTANT:** All users should change their passwords after first login!

## Key Features

### 1. Connection Pooling

The system maintains a pool of 2-10 database connections that are shared among users:

- **Minimum Connections:** 2 (always available)
- **Maximum Connections:** 10 (supports up to 10 concurrent operations)
- **Automatic Management:** Connections are returned to the pool after use
- **Thread-Safe:** Designed for concurrent access

### 2. User Authentication

Users log in with username and password:

```python
# Authentication happens against the database
with db_pool.get_cursor() as cursor:
    user = UserManager.authenticate(cursor, username, password)
```

Passwords are hashed using SHA-256 (never stored in plain text).

### 3. Session Tracking

Each login creates a session record:

```python
# Session is created on login
session_id = UserManager.create_session(cursor, user_id, username)

# Session is ended on logout
UserManager.end_session(cursor, session_id)
```

Managers can view all active sessions through the User Management interface.

### 4. Audit Logging

All database changes are logged:

```python
AuditLogger.log(
    cursor,
    user_name="Manager",
    action="UPDATE",
    table_name="equipment",
    record_id="BFM-001",
    old_values={"status": "Active"},
    new_values={"status": "Inactive"},
    notes="Equipment retired"
)
```

### 5. Optimistic Concurrency Control

Prevents conflicts when multiple users edit the same record:

```python
# Check version before updating
success, current_version, message = OptimisticConcurrencyControl.check_version(
    cursor, 'equipment', record_id, expected_version
)

if success:
    # Perform update
    cursor.execute("UPDATE equipment SET ... WHERE id = %s", (record_id,))
    OptimisticConcurrencyControl.increment_version(cursor, 'equipment', record_id)
else:
    # Show conflict message to user
    messagebox.showwarning("Conflict", message)
```

## User Management (Manager Only)

Managers have access to user management functions:

### Adding a New User

1. Click "User Management" (new button for managers)
2. Click "Add User"
3. Fill in user details:
   - Username (must be unique)
   - Full name
   - Email (optional)
   - Role (Manager or Technician)
   - Password
   - Notes (optional)
4. Click "Save"

### Editing a User

1. Select user from list
2. Click "Edit User"
3. Modify details as needed
4. Can reset password
5. Can activate/deactivate user
6. Click "Save"

### Viewing Active Sessions

1. Click "View Sessions"
2. See all currently logged-in users
3. Shows login time and last activity

## Database Schema Changes

### New Tables

**users:**
```sql
- id (SERIAL PRIMARY KEY)
- username (TEXT UNIQUE)
- password_hash (TEXT)
- full_name (TEXT)
- role (TEXT: 'Manager' or 'Technician')
- email (TEXT)
- is_active (BOOLEAN)
- created_date (TIMESTAMP)
- updated_date (TIMESTAMP)
- last_login (TIMESTAMP)
- created_by (TEXT)
- notes (TEXT)
```

**user_sessions:**
```sql
- id (SERIAL PRIMARY KEY)
- user_id (INTEGER)
- username (TEXT)
- login_time (TIMESTAMP)
- logout_time (TIMESTAMP)
- last_activity (TIMESTAMP)
- is_active (BOOLEAN)
- session_data (TEXT)
```

**audit_log:**
```sql
- id (SERIAL PRIMARY KEY)
- user_name (TEXT)
- action (TEXT: INSERT, UPDATE, DELETE, etc.)
- table_name (TEXT)
- record_id (TEXT)
- old_values (TEXT)
- new_values (TEXT)
- notes (TEXT)
- action_timestamp (TIMESTAMP)
```

### Modified Tables

All existing tables now have:
- `version` (INTEGER) - For optimistic locking
- `updated_date` (TIMESTAMP) - Last modification time

## Configuration

### Database Configuration

Located in `AIT_CMMS_REV3.py`:

```python
DB_CONFIG = {
    'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_2Nm6hyPVWiIH',
    'sslmode': 'require'
}
```

### Connection Pool Settings

```python
# In database_utils.py
db_pool.initialize(DB_CONFIG, min_conn=2, max_conn=10)
```

Adjust `max_conn` based on expected concurrent users:
- 3-5 users: max_conn=10 (recommended)
- 5-10 users: max_conn=15
- 10+ users: max_conn=20

## Testing Multi-User Support

### Test Scenario 1: Concurrent Logins

1. Open the application on 3 different computers
2. Log in with different users simultaneously
3. Verify all users can access their respective functions

### Test Scenario 2: Concurrent Edits

1. Two users open the same equipment record
2. User A makes changes and saves
3. User B tries to save changes
4. System should detect the conflict (version mismatch)
5. User B should be prompted to refresh and retry

### Test Scenario 3: Session Management

1. Manager logs in
2. Navigate to User Management > View Sessions
3. Verify all active sessions are displayed
4. Close a user's application
5. Refresh session view - closed session should show logout time

## Troubleshooting

### Issue: "Connection pool not initialized"

**Solution:** Ensure `init_database()` is called before any database operations.

### Issue: "Too many connections"

**Solution:** Increase `max_conn` in connection pool initialization, or check for connection leaks.

### Issue: "Version conflict" errors

**Solution:** This is normal when two users edit the same record. The second user should:
1. Note their changes
2. Refresh the record
3. Reapply their changes
4. Save again

### Issue: Users can't log in

**Solution:**
1. Check if migration was run successfully
2. Verify user exists in database: `SELECT * FROM users WHERE username = 'xxx'`
3. Try resetting password through manager account
4. Check user is active: `is_active = TRUE`

### Issue: Audit log growing too large

**Solution:** Implement periodic archival:
```sql
-- Archive old audit logs (older than 90 days)
DELETE FROM audit_log WHERE action_timestamp < NOW() - INTERVAL '90 days';
```

## Performance Considerations

### Recommended Limits

- **Concurrent Users:** 3-5 (optimal), up to 10 (maximum)
- **Connection Pool:** 2-10 connections
- **PostgreSQL Max Connections:** Default 100 (sufficient for 10 users)

### Monitoring

Check active connections:
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'neondb';
```

Check active sessions:
```sql
SELECT * FROM user_sessions WHERE is_active = TRUE;
```

View recent audit activity:
```sql
SELECT * FROM audit_log ORDER BY action_timestamp DESC LIMIT 50;
```

## Security Recommendations

1. **Change Default Passwords:** All users should change passwords after first login
2. **Use Strong Passwords:** Minimum 8 characters, mix of letters and numbers
3. **Regular Password Updates:** Change passwords every 90 days
4. **Deactivate Unused Accounts:** Don't delete, just set `is_active = FALSE`
5. **Monitor Audit Logs:** Review regularly for suspicious activity
6. **Backup Database:** Regular backups of PostgreSQL database

## Migration Rollback

If you need to revert the migration:

```sql
-- Drop new tables
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS user_sessions;
DROP TABLE IF EXISTS users;

-- Remove version columns (if needed)
ALTER TABLE equipment DROP COLUMN IF EXISTS version;
ALTER TABLE corrective_maintenance DROP COLUMN IF EXISTS version;
-- Repeat for other tables...
```

**WARNING:** This will delete all user accounts and audit history!

## Support

For issues or questions:
1. Check this documentation
2. Review error messages in application console
3. Check PostgreSQL logs
4. Contact system administrator

## Summary

The multi-user upgrade provides:
- ✅ Support for 3-5 concurrent users
- ✅ Secure authentication with hashed passwords
- ✅ Connection pooling for efficiency
- ✅ Session tracking
- ✅ Complete audit trail
- ✅ Conflict detection and resolution
- ✅ User management interface

**Next Steps:**
1. Run migration script
2. Test with default accounts
3. Create additional users as needed
4. Have all users change their passwords
5. Train users on new login process
