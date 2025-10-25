"""
Database Migration Script for Multi-User Support
Adds version columns, creates user management tables, and migrates existing data
"""

import psycopg2
from database_utils import UserManager


class MultiUserMigration:
    """Handles database migration for multi-user support"""

    def __init__(self, db_config):
        self.db_config = db_config
        self.conn = None

    def connect(self):
        """Connect to the database"""
        self.conn = psycopg2.connect(
            host=self.db_config['host'],
            port=self.db_config['port'],
            database=self.db_config['database'],
            user=self.db_config['user'],
            password=self.db_config['password'],
            sslmode=self.db_config.get('sslmode', 'require')
        )
        self.conn.autocommit = False
        print("Connected to database successfully")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print("Database connection closed")

    def migrate(self):
        """Run all migration steps"""
        try:
            self.connect()
            cursor = self.conn.cursor()

            print("\n" + "=" * 60)
            print("Starting Multi-User Migration")
            print("=" * 60 + "\n")

            # Step 1: Create new tables
            self.create_users_table(cursor)
            self.create_sessions_table(cursor)
            self.create_audit_log_table(cursor)

            # Step 2: Add version columns to existing tables
            self.add_version_columns(cursor)

            # Step 3: Create default users
            self.create_default_users(cursor)

            # Step 4: Create indexes for performance
            self.create_indexes(cursor)

            self.conn.commit()
            print("\n" + "=" * 60)
            print("Migration completed successfully!")
            print("=" * 60 + "\n")

        except Exception as e:
            print(f"\nERROR during migration: {e}")
            if self.conn:
                self.conn.rollback()
            raise
        finally:
            self.close()

    def create_users_table(self, cursor):
        """Create users table for authentication"""
        print("Creating users table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('Manager', 'Technician')),
                email TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                created_by TEXT,
                notes TEXT
            )
        ''')
        print("  ✓ Users table created")

    def create_sessions_table(self, cursor):
        """Create user_sessions table for session tracking"""
        print("Creating user_sessions table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                logout_time TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                session_data TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        print("  ✓ User sessions table created")

    def create_audit_log_table(self, cursor):
        """Create audit_log table for tracking all changes"""
        print("Creating audit_log table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                user_name TEXT NOT NULL,
                action TEXT NOT NULL,
                table_name TEXT NOT NULL,
                record_id TEXT,
                old_values TEXT,
                new_values TEXT,
                notes TEXT,
                action_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  ✓ Audit log table created")

    def add_version_columns(self, cursor):
        """Add version columns to existing tables for optimistic locking"""
        print("\nAdding version columns to existing tables...")

        tables = [
            'equipment',
            'pm_completions',
            'weekly_pm_schedules',
            'corrective_maintenance',
            'work_orders',
            'parts_inventory',
            'mro_stock',
            'cannot_find_assets',
            'run_to_failure_assets'
        ]

        for table in tables:
            try:
                # Check if version column already exists
                cursor.execute(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = 'version'
                """)

                if cursor.fetchone() is None:
                    # Add version column
                    cursor.execute(f'''
                        ALTER TABLE {table}
                        ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1 NOT NULL
                    ''')
                    print(f"  ✓ Added version column to {table}")
                else:
                    print(f"  ✓ Version column already exists in {table}")

                # Ensure updated_date column exists
                cursor.execute(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = 'updated_date'
                """)

                if cursor.fetchone() is None:
                    cursor.execute(f'''
                        ALTER TABLE {table}
                        ADD COLUMN IF NOT EXISTS updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ''')
                    print(f"  ✓ Added updated_date column to {table}")

            except Exception as e:
                print(f"  ⚠ Warning for {table}: {e}")
                # Continue with other tables

    def create_default_users(self, cursor):
        """Create default users from hardcoded technician list"""
        print("\nCreating default users...")

        # Manager account
        manager_password = UserManager.hash_password("AIT2584")
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, created_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING
        """, ('manager', manager_password, 'AIT Manager', 'Manager', 'System'))
        print("  ✓ Manager account created (username: manager, password: AIT2584)")

        # Technician accounts
        technicians = [
            "Mark Michaels", "Jerone Bosarge", "Jon Hymel", "Nick Whisenant",
            "James Dunnam", "Wayne Dunnam", "Nate Williams", "Rey Marikit", "Ronald Houghs"
        ]

        for tech_name in technicians:
            # Create username from full name (e.g., "Mark Michaels" -> "mmichaels")
            name_parts = tech_name.lower().split()
            username = name_parts[0][0] + name_parts[-1] if len(name_parts) > 1 else name_parts[0]

            # Default password is username
            password_hash = UserManager.hash_password(username)

            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, created_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (username) DO NOTHING
            """, (username, password_hash, tech_name, 'Technician', 'System'))

        print(f"  ✓ Created {len(technicians)} technician accounts")
        print("  ℹ Default password for technicians is their username")

    def create_indexes(self, cursor):
        """Create database indexes for performance"""
        print("\nCreating performance indexes...")

        indexes = [
            # Users indexes
            ("idx_users_username", "users", "username"),
            ("idx_users_role", "users", "role"),

            # Sessions indexes
            ("idx_sessions_user_id", "user_sessions", "user_id"),
            ("idx_sessions_active", "user_sessions", "is_active"),

            # Audit log indexes
            ("idx_audit_user", "audit_log", "user_name"),
            ("idx_audit_table", "audit_log", "table_name"),
            ("idx_audit_timestamp", "audit_log", "action_timestamp"),

            # Version columns for quick lookups
            ("idx_equipment_version", "equipment", "version"),
            ("idx_cm_version", "corrective_maintenance", "version"),
        ]

        for index_name, table_name, column_name in indexes:
            try:
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON {table_name} ({column_name})
                """)
                print(f"  ✓ Created index {index_name}")
            except Exception as e:
                print(f"  ⚠ Warning creating {index_name}: {e}")


def main():
    """Main migration function"""
    # Database configuration
    DB_CONFIG = {
        'host': 'ep-tiny-paper-ad8glt26-pooler.c-2.us-east-1.aws.neon.tech',
        'port': 5432,
        'database': 'neondb',
        'user': 'neondb_owner',
        'password': 'npg_2Nm6hyPVWiIH',
        'sslmode': 'require'
    }

    # Run migration
    migration = MultiUserMigration(DB_CONFIG)
    migration.migrate()

    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print("\nNew Tables Created:")
    print("  • users - User authentication and management")
    print("  • user_sessions - Active user session tracking")
    print("  • audit_log - Complete audit trail of all changes")
    print("\nColumns Added:")
    print("  • version - Added to all data tables for concurrency control")
    print("  • updated_date - Timestamp tracking for all tables")
    print("\nDefault Users Created:")
    print("  • Manager: username='manager', password='AIT2584'")
    print("  • Technicians: username from name, password=username")
    print("    (e.g., Mark Michaels: username='mmichaels', password='mmichaels')")
    print("\nNext Steps:")
    print("  1. Test login with new credentials")
    print("  2. Run the updated application")
    print("  3. Have users change their passwords after first login")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
