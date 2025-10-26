"""
Database Utilities for Multi-User Support
Provides connection pooling, optimistic concurrency control, and transaction management
"""

import psycopg2
from psycopg2 import pool, extras
from contextlib import contextmanager
from datetime import datetime
import threading
import hashlib


class DatabaseConnectionPool:
    """Manages PostgreSQL connection pool for concurrent users"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one pool exists"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize connection pool if not already initialized"""
        if not hasattr(self, 'pool'):
            self.pool = None
            self.config = None

    def initialize(self, db_config, min_conn=2, max_conn=10):
        """
        Initialize the connection pool

        Args:
            db_config: Dictionary with connection parameters
            min_conn: Minimum number of connections to maintain
            max_conn: Maximum number of connections allowed
        """
        if self.pool is None:
            self.config = db_config
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                min_conn,
                max_conn,
                host=db_config['host'],
                port=db_config['port'],
                database=db_config['database'],
                user=db_config['user'],
                password=db_config['password'],
                sslmode=db_config.get('sslmode', 'require')
            )
            print(f"Connection pool initialized: {min_conn}-{max_conn} connections")

    def get_connection(self):
        """Get a connection from the pool"""
        if self.pool is None:
            raise Exception("Connection pool not initialized. Call initialize() first.")
        return self.pool.getconn()

    def return_connection(self, conn):
        """Return a connection to the pool"""
        if self.pool:
            self.pool.putconn(conn)

    def close_all(self):
        """Close all connections in the pool"""
        if self.pool:
            self.pool.closeall()
            self.pool = None
            print("Connection pool closed")

    @contextmanager
    def get_cursor(self, commit=True):
        """
        Context manager for database operations

        Args:
            commit: Whether to commit automatically on success

        Yields:
            cursor: Database cursor

        Example:
            with pool.get_cursor() as cursor:
                cursor.execute("SELECT * FROM equipment")
                data = cursor.fetchall()
        """
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=extras.DictCursor)
            yield cursor
            if commit:
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            if cursor:
                cursor.close()
            self.return_connection(conn)


class OptimisticConcurrencyControl:
    """Handles optimistic locking for concurrent updates"""

    @staticmethod
    def check_version(cursor, table, record_id, expected_version, id_column='id'):
        """
        Check if the record version matches expected version

        Args:
            cursor: Database cursor
            table: Table name
            record_id: Record ID
            expected_version: Expected version number
            id_column: Name of the ID column

        Returns:
            tuple: (success: bool, current_version: int, message: str)
        """
        cursor.execute(
            f"SELECT version FROM {table} WHERE {id_column} = %s FOR UPDATE",
            (record_id,)
        )
        result = cursor.fetchone()

        if not result:
            return False, None, f"Record not found in {table}"

        current_version = result[0] if isinstance(result, tuple) else result['version']

        if current_version != expected_version:
            return False, current_version, (
                f"Conflict detected: Record was modified by another user. "
                f"Expected version {expected_version}, found {current_version}."
            )

        return True, current_version, "Version check passed"

    @staticmethod
    def increment_version(cursor, table, record_id, id_column='id'):
        """
        Increment the version number of a record

        Args:
            cursor: Database cursor
            table: Table name
            record_id: Record ID
            id_column: Name of the ID column
        """
        cursor.execute(
            f"""
            UPDATE {table}
            SET version = version + 1,
                updated_date = CURRENT_TIMESTAMP
            WHERE {id_column} = %s
            """,
            (record_id,)
        )


class AuditLogger:
    """Logs all database changes for audit trail"""

    @staticmethod
    def log(cursor, user_name, action, table_name, record_id, old_values=None, new_values=None, notes=None):
        """
        Log a database action

        Args:
            cursor: Database cursor
            user_name: Name of user performing action
            action: Action type (INSERT, UPDATE, DELETE, etc.)
            table_name: Table being modified
            record_id: ID of record being modified
            old_values: Dictionary of old values (for UPDATE)
            new_values: Dictionary of new values (for INSERT/UPDATE)
            notes: Additional notes
        """
        cursor.execute(
            """
            INSERT INTO audit_log
            (user_name, action, table_name, record_id, old_values, new_values, notes, action_timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (user_name, action, table_name, record_id, str(old_values), str(new_values), notes)
        )


class UserManager:
    """Manages user authentication and sessions"""

    @staticmethod
    def hash_password(password):
        """Hash a password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(password, hashed_password):
        """Verify a password against its hash"""
        return UserManager.hash_password(password) == hashed_password

    @staticmethod
    def authenticate(cursor, username, password):
        """
        Authenticate a user

        Args:
            cursor: Database cursor
            username: Username
            password: Password (plain text)

        Returns:
            dict: User info if authenticated, None otherwise
        """
        cursor.execute(
            """
            SELECT id, username, full_name, role, password_hash, is_active
            FROM users
            WHERE username = %s
            """,
            (username,)
        )
        user = cursor.fetchone()

        if not user:
            return None

        # Convert to dict if it's a tuple or list
        if isinstance(user, (tuple, list)):
            user = {
                'id': user[0],
                'username': user[1],
                'full_name': user[2],
                'role': user[3],
                'password_hash': user[4],
                'is_active': user[5]
            }

        if not user['is_active']:
            return None

        if not UserManager.verify_password(password, user['password_hash']):
            return None

        # Don't return password hash
        del user['password_hash']
        return user

    @staticmethod
    def create_session(cursor, user_id, username):
        """
        Create a new user session

        Args:
            cursor: Database cursor
            user_id: User ID
            username: Username

        Returns:
            int: Session ID
        """
        cursor.execute(
            """
            INSERT INTO user_sessions
            (user_id, username, login_time, last_activity, is_active)
            VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, TRUE)
            RETURNING id
            """,
            (user_id, username)
        )
        session_id = cursor.fetchone()[0]
        return session_id

    @staticmethod
    def update_session_activity(cursor, session_id):
        """Update session last activity time"""
        cursor.execute(
            """
            UPDATE user_sessions
            SET last_activity = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (session_id,)
        )

    @staticmethod
    def end_session(cursor, session_id):
        """End a user session"""
        cursor.execute(
            """
            UPDATE user_sessions
            SET logout_time = CURRENT_TIMESTAMP, is_active = FALSE
            WHERE id = %s
            """,
            (session_id,)
        )

    @staticmethod
    def get_active_sessions(cursor):
        """Get all active sessions"""
        cursor.execute(
            """
            SELECT s.id, s.user_id, s.username, u.full_name, u.role,
                   s.login_time, s.last_activity
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.is_active = TRUE
            ORDER BY s.login_time DESC
            """
        )
        return cursor.fetchall()


class TransactionManager:
    """Manages database transactions with retry logic"""

    @staticmethod
    @contextmanager
    def transaction(pool, max_retries=3):
        """
        Context manager for transactions with retry logic

        Args:
            pool: DatabaseConnectionPool instance
            max_retries: Maximum number of retry attempts for deadlocks

        Yields:
            cursor: Database cursor
        """
        conn = None
        cursor = None
        retries = 0

        while retries < max_retries:
            try:
                conn = pool.get_connection()
                cursor = conn.cursor(cursor_factory=extras.DictCursor)

                yield cursor

                conn.commit()
                break

            except psycopg2.extensions.TransactionRollbackError:
                # Serialization failure or deadlock - retry
                if conn:
                    conn.rollback()
                retries += 1
                if retries >= max_retries:
                    raise Exception(f"Transaction failed after {max_retries} retries")
                print(f"Deadlock detected, retrying... (attempt {retries}/{max_retries})")

            except Exception as e:
                if conn:
                    conn.rollback()
                raise e

            finally:
                if cursor:
                    cursor.close()
                if conn:
                    pool.return_connection(conn)


# Global pool instance
db_pool = DatabaseConnectionPool()
