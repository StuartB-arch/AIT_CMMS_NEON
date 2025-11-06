"""
User Management Interface for Managers
Allows managers to create, edit, and deactivate users
"""

import tkinter as tk
from tkinter import ttk, messagebox
from database_utils import db_pool, UserManager, AuditLogger


class UserManagementDialog:
    """Dialog for managing users (Manager access only)"""

    def __init__(self, parent, current_user):
        self.parent = parent
        self.current_user = current_user
        self.dialog = None
        self.tree = None

    def show(self):
        """Show the user management dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("User Management")
        self.dialog.geometry("800x600")
        self.dialog.transient(self.parent)

        # Header
        header_frame = ttk.Frame(self.dialog)
        header_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(header_frame, text="User Management",
                font=('Arial', 14, 'bold')).pack(side='left')

        # Buttons
        ttk.Button(header_frame, text="Add User",
                command=self.add_user).pack(side='right', padx=5)
        ttk.Button(header_frame, text="Edit User",
                command=self.edit_user).pack(side='right', padx=5)
        ttk.Button(header_frame, text="Delete User",
                command=self.delete_user).pack(side='right', padx=5)
        ttk.Button(header_frame, text="View Sessions",
                command=self.view_sessions).pack(side='right', padx=5)

        # User list
        list_frame = ttk.Frame(self.dialog)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Create treeview
        columns = ('ID', 'Username', 'Full Name', 'Role', 'Active', 'Last Login', 'Created')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings')

        # Define headings
        self.tree.heading('ID', text='ID')
        self.tree.heading('Username', text='Username')
        self.tree.heading('Full Name', text='Full Name')
        self.tree.heading('Role', text='Role')
        self.tree.heading('Active', text='Active')
        self.tree.heading('Last Login', text='Last Login')
        self.tree.heading('Created', text='Created')

        # Column widths
        self.tree.column('ID', width=50)
        self.tree.column('Username', width=120)
        self.tree.column('Full Name', width=150)
        self.tree.column('Role', width=100)
        self.tree.column('Active', width=60)
        self.tree.column('Last Login', width=150)
        self.tree.column('Created', width=150)

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Load users
        self.load_users()

        # Close button
        ttk.Button(self.dialog, text="Close",
                command=self.dialog.destroy).pack(pady=10)

    def load_users(self):
        """Load all users from database"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            with db_pool.get_cursor() as cursor:
                cursor.execute("""
                    SELECT id, username, full_name, role, is_active,
                           last_login, created_date
                    FROM users
                    ORDER BY created_date DESC
                """)

                for row in cursor.fetchall():
                    values = (
                        row['id'],
                        row['username'],
                        row['full_name'],
                        row['role'],
                        'Yes' if row['is_active'] else 'No',
                        str(row['last_login']) if row['last_login'] else 'Never',
                        str(row['created_date'])
                    )
                    self.tree.insert('', 'end', values=values)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load users: {e}")

    def add_user(self):
        """Show dialog to add a new user"""
        dialog = tk.Toplevel(self.dialog)
        dialog.title("Add User")
        dialog.geometry("400x350")
        dialog.transient(self.dialog)

        # Form
        form_frame = ttk.Frame(dialog, padding=20)
        form_frame.pack(fill='both', expand=True)

        # Username
        ttk.Label(form_frame, text="Username:").grid(row=0, column=0, sticky='w', pady=5)
        username_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=username_var, width=30).grid(row=0, column=1, pady=5)

        # Full Name
        ttk.Label(form_frame, text="Full Name:").grid(row=1, column=0, sticky='w', pady=5)
        fullname_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=fullname_var, width=30).grid(row=1, column=1, pady=5)

        # Email
        ttk.Label(form_frame, text="Email:").grid(row=2, column=0, sticky='w', pady=5)
        email_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=email_var, width=30).grid(row=2, column=1, pady=5)

        # Role
        ttk.Label(form_frame, text="Role:").grid(row=3, column=0, sticky='w', pady=5)
        role_var = tk.StringVar(value='Technician')
        role_combo = ttk.Combobox(form_frame, textvariable=role_var,
                                values=['Manager', 'Technician'],
                                state='readonly', width=28)
        role_combo.grid(row=3, column=1, pady=5)

        # Password
        ttk.Label(form_frame, text="Password:").grid(row=4, column=0, sticky='w', pady=5)
        password_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=password_var, show='*', width=30).grid(row=4, column=1, pady=5)

        # Confirm Password
        ttk.Label(form_frame, text="Confirm Password:").grid(row=5, column=0, sticky='w', pady=5)
        confirm_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=confirm_var, show='*', width=30).grid(row=5, column=1, pady=5)

        # Notes
        ttk.Label(form_frame, text="Notes:").grid(row=6, column=0, sticky='nw', pady=5)
        notes_text = tk.Text(form_frame, width=30, height=3)
        notes_text.grid(row=6, column=1, pady=5)

        def save_user():
            username = username_var.get().strip()
            fullname = fullname_var.get().strip()
            email = email_var.get().strip()
            role = role_var.get()
            password = password_var.get()
            confirm = confirm_var.get()
            notes = notes_text.get('1.0', 'end-1c').strip()

            # Validation
            if not username or not fullname or not password:
                messagebox.showerror("Error", "Username, full name, and password are required")
                return

            if password != confirm:
                messagebox.showerror("Error", "Passwords do not match")
                return

            if len(password) < 4:
                messagebox.showerror("Error", "Password must be at least 4 characters")
                return

            try:
                with db_pool.get_cursor() as cursor:
                    # Check if username exists
                    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                    if cursor.fetchone():
                        messagebox.showerror("Error", "Username already exists")
                        return

                    # Create user
                    password_hash = UserManager.hash_password(password)
                    cursor.execute("""
                        INSERT INTO users
                        (username, password_hash, full_name, email, role, created_by, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (username, password_hash, fullname, email, role, self.current_user, notes))

                    # Log the action
                    AuditLogger.log(cursor, self.current_user, 'INSERT', 'users', username,
                                notes=f"Created new {role} user: {fullname}")

                messagebox.showinfo("Success", f"User '{username}' created successfully")
                dialog.destroy()
                self.load_users()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to create user: {e}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=20, pady=20)

        ttk.Button(button_frame, text="Save", command=save_user).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

    def edit_user(self):
        """Edit selected user"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a user to edit")
            return

        user_id = self.tree.item(selected[0])['values'][0]

        # Fetch user details
        try:
            with db_pool.get_cursor() as cursor:
                cursor.execute("""
                    SELECT username, full_name, email, role, is_active, notes
                    FROM users
                    WHERE id = %s
                """, (user_id,))
                user = cursor.fetchone()

                if not user:
                    messagebox.showerror("Error", "User not found")
                    return

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load user: {e}")
            return

        # Edit dialog
        dialog = tk.Toplevel(self.dialog)
        dialog.title("Edit User")
        dialog.geometry("400x400")
        dialog.transient(self.dialog)

        form_frame = ttk.Frame(dialog, padding=20)
        form_frame.pack(fill='both', expand=True)

        # Username (read-only)
        ttk.Label(form_frame, text="Username:").grid(row=0, column=0, sticky='w', pady=5)
        ttk.Label(form_frame, text=user['username'], font=('Arial', 10, 'bold')).grid(row=0, column=1, sticky='w', pady=5)

        # Full Name
        ttk.Label(form_frame, text="Full Name:").grid(row=1, column=0, sticky='w', pady=5)
        fullname_var = tk.StringVar(value=user['full_name'])
        ttk.Entry(form_frame, textvariable=fullname_var, width=30).grid(row=1, column=1, pady=5)

        # Email
        ttk.Label(form_frame, text="Email:").grid(row=2, column=0, sticky='w', pady=5)
        email_var = tk.StringVar(value=user['email'] or '')
        ttk.Entry(form_frame, textvariable=email_var, width=30).grid(row=2, column=1, pady=5)

        # Role
        ttk.Label(form_frame, text="Role:").grid(row=3, column=0, sticky='w', pady=5)
        role_var = tk.StringVar(value=user['role'])
        ttk.Combobox(form_frame, textvariable=role_var,
                    values=['Manager', 'Technician'],
                    state='readonly', width=28).grid(row=3, column=1, pady=5)

        # Active
        ttk.Label(form_frame, text="Active:").grid(row=4, column=0, sticky='w', pady=5)
        active_var = tk.BooleanVar(value=user['is_active'])
        ttk.Checkbutton(form_frame, variable=active_var).grid(row=4, column=1, sticky='w', pady=5)

        # Reset Password
        ttk.Label(form_frame, text="New Password:").grid(row=5, column=0, sticky='w', pady=5)
        password_var = tk.StringVar()
        ttk.Entry(form_frame, textvariable=password_var, show='*', width=30).grid(row=5, column=1, pady=5)
        ttk.Label(form_frame, text="(leave blank to keep current)", font=('Arial', 8)).grid(row=6, column=1, sticky='w')

        # Notes
        ttk.Label(form_frame, text="Notes:").grid(row=7, column=0, sticky='nw', pady=5)
        notes_text = tk.Text(form_frame, width=30, height=3)
        notes_text.insert('1.0', user['notes'] or '')
        notes_text.grid(row=7, column=1, pady=5)

        def save_changes():
            try:
                with db_pool.get_cursor() as cursor:
                    # Update user
                    updates = []
                    params = []

                    updates.append("full_name = %s")
                    params.append(fullname_var.get().strip())

                    updates.append("email = %s")
                    params.append(email_var.get().strip())

                    updates.append("role = %s")
                    params.append(role_var.get())

                    updates.append("is_active = %s")
                    params.append(active_var.get())

                    updates.append("notes = %s")
                    params.append(notes_text.get('1.0', 'end-1c').strip())

                    # Update password if provided
                    new_password = password_var.get()
                    if new_password:
                        updates.append("password_hash = %s")
                        params.append(UserManager.hash_password(new_password))

                    updates.append("updated_date = CURRENT_TIMESTAMP")
                    params.append(user_id)

                    query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
                    cursor.execute(query, params)

                    # Log the action
                    AuditLogger.log(cursor, self.current_user, 'UPDATE', 'users', str(user_id),
                                notes=f"Updated user: {user['username']}")

                messagebox.showinfo("Success", "User updated successfully")
                dialog.destroy()
                self.load_users()

            except Exception as e:
                messagebox.showerror("Error", f"Failed to update user: {e}")

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side='bottom', fill='x', padx=20, pady=20)

        ttk.Button(button_frame, text="Save", command=save_changes).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='right', padx=5)

    def delete_user(self):
        """Delete selected user"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a user to delete")
            return

        user_id = self.tree.item(selected[0])['values'][0]
        username = self.tree.item(selected[0])['values'][1]
        role = self.tree.item(selected[0])['values'][3]

        # Confirm deletion
        result = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete user '{username}' ({role})?\n\n"
            "This action cannot be undone and will:\n"
            "- Remove the user from the system\n"
            "- End any active sessions\n"
            "- Preserve audit trail entries\n\n"
            "Note: For safety, consider deactivating the user instead "
            "(via Edit User).",
            icon='warning'
        )

        if not result:
            return

        # Prevent self-deletion
        if username == self.current_user:
            messagebox.showerror("Error", "You cannot delete your own account")
            return

        try:
            with db_pool.get_cursor() as cursor:
                # Log the deletion before deleting the user
                AuditLogger.log(cursor, self.current_user, 'DELETE', 'users', str(user_id),
                            notes=f"Deleted user: {username} ({role})")

                # Delete all sessions for this user first (to avoid foreign key constraint)
                cursor.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))

                # Now delete the user
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))

                # Check if deletion was successful
                if cursor.rowcount == 0:
                    messagebox.showerror("Error", "User not found or already deleted")
                    return

            messagebox.showinfo("Success", f"User '{username}' has been deleted successfully")
            self.load_users()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete user: {e}")

    def view_sessions(self):
        """View active user sessions"""
        dialog = tk.Toplevel(self.dialog)
        dialog.title("Active User Sessions")
        dialog.geometry("800x400")
        dialog.transient(self.dialog)

        # Header
        ttk.Label(dialog, text="Active User Sessions",
                font=('Arial', 12, 'bold')).pack(pady=10)

        # Session list
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ('Session ID', 'User', 'Full Name', 'Role', 'Login Time', 'Last Activity')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings')

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=130)

        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Load sessions
        try:
            with db_pool.get_cursor() as cursor:
                sessions = UserManager.get_active_sessions(cursor)

                for session in sessions:
                    tree.insert('', 'end', values=(
                        session['id'],
                        session['username'],
                        session['full_name'],
                        session['role'],
                        str(session['login_time']),
                        str(session['last_activity'])
                    ))

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load sessions: {e}")

        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
