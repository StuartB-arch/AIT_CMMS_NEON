"""
CM Parts Integration Module
Handles parts consumption tracking for Corrective Maintenance work orders
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime


class CMPartsIntegration:
    """Integration module for tracking parts consumption in CM work orders"""

    def __init__(self, parent):
        """Initialize with reference to parent CMMS application"""
        self.parent = parent
        self.conn = parent.conn

    def show_parts_consumption_dialog(self, cm_number, technician_name, callback=None):
        """
        Show dialog for recording parts consumed during corrective maintenance

        Args:
            cm_number: The CM work order number
            technician_name: Name of technician performing the work
            callback: Function to call when dialog is closed (receives success bool)
        """
        dialog = tk.Toplevel(self.parent.root)
        dialog.title(f"Parts Consumption - CM {cm_number}")

        # Make dialog responsive with better default size
        dialog.geometry("950x750")
        dialog.minsize(850, 700)  # Set minimum size to ensure all content is visible
        dialog.resizable(True, True)  # Allow resizing in both directions

        dialog.transient(self.parent.root)
        dialog.grab_set()

        # Create main canvas with scrollbar for entire dialog
        main_canvas = tk.Canvas(dialog, highlightthickness=0)
        main_scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        scrollable_frame = ttk.Frame(main_canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )

        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=main_scrollbar.set)

        # Enable mousewheel scrolling
        def on_mousewheel(event):
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        main_canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Header - more compact
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill='x', padx=10, pady=(10, 5))

        ttk.Label(header_frame, text=f"MRO Parts Consumption - CM {cm_number} - Technician: {technician_name}",
                 font=('Arial', 11, 'bold')).pack()
        ttk.Label(header_frame,
                 text="Select parts consumed from MRO stock during this corrective maintenance.",
                 font=('Arial', 9), foreground='gray').pack(pady=2)

        # Search frame - more compact
        search_frame = ttk.Frame(scrollable_frame)
        search_frame.pack(fill='x', padx=10, pady=(0, 5))

        ttk.Label(search_frame, text="Search:", font=('Arial', 10, 'bold')).pack(side='left', padx=5)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=50)
        search_entry.pack(side='left', padx=5)
        ttk.Label(search_frame, text="(by part number or description)",
                 font=('Arial', 9, 'italic'), foreground='gray').pack(side='left')

        # Parts list
        list_frame = ttk.LabelFrame(scrollable_frame, text="Available MRO Stock Parts")
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Add legend
        legend_frame = ttk.Frame(list_frame)
        legend_frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(legend_frame, text="Legend:", font=('Arial', 9, 'bold')).pack(side='left', padx=5)
        ttk.Label(legend_frame, text="● In Stock", foreground='black').pack(side='left', padx=5)
        ttk.Label(legend_frame, text="● Low Stock", foreground='orange').pack(side='left', padx=5)
        ttk.Label(legend_frame, text="● Out of Stock", foreground='gray',
                 font=('Arial', 9, 'italic')).pack(side='left', padx=5)

        # Scrollable tree view
        tree_scroll = ttk.Scrollbar(list_frame)
        tree_scroll.pack(side='right', fill='y')

        parts_tree = ttk.Treeview(list_frame,
                                  columns=('Part Number', 'Description', 'Location', 'Qty Available'),
                                  show='headings',
                                  yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=parts_tree.yview)

        parts_tree.heading('Part Number', text='Part Number')
        parts_tree.heading('Description', text='Description')
        parts_tree.heading('Location', text='Location')
        parts_tree.heading('Qty Available', text='Qty Available')

        parts_tree.column('Part Number', width=150)
        parts_tree.column('Description', width=350)
        parts_tree.column('Location', width=150)
        parts_tree.column('Qty Available', width=120)

        # Configure tags for visual indicators
        parts_tree.tag_configure('out_of_stock', foreground='gray', font=('Arial', 9, 'italic'))
        parts_tree.tag_configure('low_stock', foreground='orange')
        parts_tree.tag_configure('in_stock', foreground='black')

        parts_tree.pack(fill='both', expand=True, padx=5, pady=5)

        # Load available parts from MRO inventory (show all parts, including out of stock)
        all_parts_data = []
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT part_number, name, location, quantity_in_stock
                FROM mro_inventory
                WHERE status = 'Active'
                ORDER BY part_number
            ''')

            all_parts_data = cursor.fetchall()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load MRO inventory: {str(e)}")

        # Function to filter and display parts based on search
        def filter_parts(*args):
            """Filter parts list based on search term"""
            search_term = search_var.get().lower().strip()

            # Clear current items
            for item in parts_tree.get_children():
                parts_tree.delete(item)

            # Filter and display parts
            for part in all_parts_data:
                part_number = str(part[0]).lower()
                description = str(part[1]).lower()
                qty_available = float(part[3]) if part[3] else 0.0

                # Show part if search term is empty or matches part number or description
                if not search_term or search_term in part_number or search_term in description:
                    # Determine tag based on stock level
                    if qty_available <= 0:
                        tag = 'out_of_stock'
                    elif qty_available <= 5:  # Low stock threshold
                        tag = 'low_stock'
                    else:
                        tag = 'in_stock'

                    parts_tree.insert('', 'end', values=part, tags=(tag,))

        # Initial load of all parts
        filter_parts()

        # Bind search to filter function
        search_var.trace('w', filter_parts)

        # Consumption entry frame
        entry_frame = ttk.LabelFrame(scrollable_frame, text="Add Parts Consumed")
        entry_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(entry_frame, text="Selected Part:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        selected_part_label = ttk.Label(entry_frame, text="(Select a part from list above)",
                                        foreground='gray')
        selected_part_label.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        ttk.Label(entry_frame, text="Quantity Used:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        qty_var = tk.StringVar(value="1")
        qty_entry = ttk.Entry(entry_frame, textvariable=qty_var, width=20)
        qty_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        # Track consumed parts
        consumed_parts = []

        # Consumed parts list - reduced height for better space usage
        consumed_frame = ttk.LabelFrame(scrollable_frame, text="Parts to be Consumed")
        consumed_frame.pack(fill='x', padx=10, pady=5)

        # Add scrollbar for consumed parts
        consumed_scroll = ttk.Scrollbar(consumed_frame)
        consumed_scroll.pack(side='right', fill='y')

        consumed_tree = ttk.Treeview(consumed_frame,
                                     columns=('Part Number', 'Description', 'Qty Used'),
                                     show='headings',
                                     height=3,
                                     yscrollcommand=consumed_scroll.set)
        consumed_scroll.config(command=consumed_tree.yview)

        consumed_tree.heading('Part Number', text='Part Number')
        consumed_tree.heading('Description', text='Description')
        consumed_tree.heading('Qty Used', text='Qty Used')

        consumed_tree.column('Part Number', width=150)
        consumed_tree.column('Description', width=500)
        consumed_tree.column('Qty Used', width=100)

        consumed_tree.pack(fill='x', padx=5, pady=5)

        def on_part_select(event):
            """Update selected part label when user selects from available parts"""
            selection = parts_tree.selection()
            if selection:
                item = parts_tree.item(selection[0])
                values = item['values']
                part_num = values[0]
                desc = values[1]
                selected_part_label.config(text=f"{part_num} - {desc}", foreground='black')

        parts_tree.bind('<<TreeviewSelect>>', on_part_select)

        def add_consumed_part():
            """Add selected part to consumed list"""
            selection = parts_tree.selection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a part from the available parts list")
                return

            try:
                qty_used = float(qty_var.get())
                if qty_used <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than 0")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid quantity value")
                return

            item = parts_tree.item(selection[0])
            values = item['values']
            part_num = values[0]
            desc = values[1]
            qty_available = float(values[3])  # Convert to float for comparison

            if qty_available <= 0:
                messagebox.showerror("Part Out of Stock",
                                    f"Part {part_num} is currently out of stock.\n\n"
                                    f"Available quantity: {qty_available}\n"
                                    f"Please replenish stock before recording consumption.")
                return

            if qty_used > qty_available:
                messagebox.showerror("Insufficient Stock",
                                    f"Quantity used ({qty_used}) exceeds available quantity ({qty_available})\n\n"
                                    f"Part: {part_num}\n"
                                    f"Please adjust the quantity or replenish stock.")
                return

            # Check if part already added
            for existing in consumed_parts:
                if existing['part_number'] == part_num:
                    messagebox.showwarning("Warning",
                                          "This part is already in the consumed list. Remove it first if you need to change the quantity.")
                    return

            # Add to consumed list
            consumed_parts.append({
                'part_number': part_num,
                'description': desc,
                'quantity': qty_used
            })

            consumed_tree.insert('', 'end', values=(part_num, desc, qty_used))
            qty_var.set("1")  # Reset quantity
            messagebox.showinfo("Success", f"Added {part_num} to consumed parts list")

        def remove_consumed_part():
            """Remove selected part from consumed list"""
            selection = consumed_tree.selection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a part to remove from the consumed list")
                return

            item = consumed_tree.item(selection[0])
            part_num = item['values'][0]

            # Remove from list
            consumed_parts[:] = [p for p in consumed_parts if p['part_number'] != part_num]
            consumed_tree.delete(selection[0])

        # Buttons frame
        buttons_frame = ttk.Frame(entry_frame)
        buttons_frame.grid(row=2, column=0, columnspan=2, pady=10)

        ttk.Button(buttons_frame, text="Add to Consumed List",
                  command=add_consumed_part).pack(side='left', padx=5)
        ttk.Button(buttons_frame, text="Remove Selected",
                  command=remove_consumed_part).pack(side='left', padx=5)

        def save_and_close():
            """Save consumed parts to database and close dialog"""
            if not consumed_parts:
                response = messagebox.askyesno("Confirm",
                                              "No parts were added to the consumed list. Continue without recording parts?")
                if not response:
                    return
                main_canvas.unbind_all("<MouseWheel>")
                dialog.destroy()
                if callback:
                    callback(True)
                return

            try:
                cursor = self.conn.cursor()

                # Record each consumed part
                for part in consumed_parts:
                    # Get unit price for cost calculation
                    cursor.execute('''
                        SELECT unit_price FROM mro_inventory WHERE part_number = %s
                    ''', (part['part_number'],))
                    result = cursor.fetchone()
                    unit_price = float(result[0]) if result and result[0] else 0.0
                    total_cost = unit_price * part['quantity']

                    # Create transaction record
                    cursor.execute('''
                        INSERT INTO mro_stock_transactions
                        (part_number, transaction_type, quantity, technician_name, notes, transaction_date)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (
                        part['part_number'],
                        'Issue',
                        -part['quantity'],  # Negative for consumption
                        technician_name,
                        f"CM Work Order: {cm_number}",
                        datetime.now()
                    ))

                    # Record in cm_parts_used table for tracking and reporting
                    cursor.execute('''
                        INSERT INTO cm_parts_used
                        (cm_number, part_number, quantity_used, total_cost, recorded_date, recorded_by, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        cm_number,
                        part['part_number'],
                        part['quantity'],
                        total_cost,
                        datetime.now(),
                        technician_name,
                        f"Parts consumed during CM {cm_number}"
                    ))

                    # Update inventory quantity
                    cursor.execute('''
                        UPDATE mro_inventory
                        SET quantity_in_stock = quantity_in_stock - %s,
                            last_updated = %s
                        WHERE part_number = %s
                    ''', (part['quantity'], datetime.now(), part['part_number']))

                self.conn.commit()

                messagebox.showinfo("Success",
                                   f"Successfully recorded {len(consumed_parts)} part(s) consumed for CM {cm_number}")
                main_canvas.unbind_all("<MouseWheel>")
                dialog.destroy()

                if callback:
                    callback(True)

            except Exception as e:
                self.conn.rollback()
                messagebox.showerror("Error", f"Failed to record parts consumption: {str(e)}")
                if callback:
                    callback(False)

        def cancel_dialog():
            """Cancel without saving"""
            if consumed_parts:
                response = messagebox.askyesno("Confirm",
                                              "Parts have been added but not saved. Cancel without saving?")
                if not response:
                    return

            main_canvas.unbind_all("<MouseWheel>")
            dialog.destroy()
            if callback:
                callback(False)

        # Bottom buttons
        bottom_frame = ttk.Frame(scrollable_frame)
        bottom_frame.pack(fill='x', padx=10, pady=10)

        ttk.Button(bottom_frame, text="Save and Complete",
                  command=save_and_close).pack(side='left', padx=5)
        ttk.Button(bottom_frame, text="Cancel",
                  command=cancel_dialog).pack(side='left', padx=5)

        # Pack the canvas and scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.pack(side="right", fill="y")

        # Cleanup mousewheel binding when dialog closes
        def on_closing():
            main_canvas.unbind_all("<MouseWheel>")
            dialog.destroy()
            if callback:
                callback(False)

        dialog.protocol("WM_DELETE_WINDOW", on_closing)

        return dialog

    def show_cm_parts_details(self, cm_number):
        """
        Show read-only view of parts consumed for a specific CM

        Args:
            cm_number: The CM work order number to view parts for
        """
        dialog = tk.Toplevel(self.parent.root)
        dialog.title(f"Parts Used - CM {cm_number}")
        dialog.geometry("800x500")
        dialog.transient(self.parent.root)

        # Header
        header_frame = ttk.Frame(dialog)
        header_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(header_frame, text=f"Parts Consumed - CM {cm_number}",
                 font=('Arial', 12, 'bold')).pack()

        # Get parts data from database
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT
                    cp.part_number,
                    mi.name,
                    cp.quantity_used,
                    cp.total_cost,
                    cp.recorded_date,
                    cp.recorded_by,
                    cp.notes
                FROM cm_parts_used cp
                LEFT JOIN mro_inventory mi ON cp.part_number = mi.part_number
                WHERE cp.cm_number = %s
                ORDER BY cp.recorded_date DESC
            ''', (cm_number,))

            parts_data = cursor.fetchall()

            if not parts_data:
                ttk.Label(header_frame, text="No parts recorded for this CM",
                         font=('Arial', 10), foreground='gray').pack(pady=5)
            else:
                ttk.Label(header_frame, text=f"Total: {len(parts_data)} part(s)",
                         font=('Arial', 10), foreground='blue').pack(pady=2)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load parts data: {str(e)}")
            dialog.destroy()
            return

        # Parts list frame
        list_frame = ttk.LabelFrame(dialog, text="Parts Details")
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Create scrollable treeview
        tree_scroll = ttk.Scrollbar(list_frame)
        tree_scroll.pack(side='right', fill='y')

        columns = ('Part Number', 'Description', 'Qty Used', 'Cost', 'Date', 'Recorded By')
        parts_tree = ttk.Treeview(list_frame,
                                  columns=columns,
                                  show='headings',
                                  yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=parts_tree.yview)

        # Configure columns
        parts_tree.heading('Part Number', text='Part Number')
        parts_tree.heading('Description', text='Description')
        parts_tree.heading('Qty Used', text='Qty Used')
        parts_tree.heading('Cost', text='Total Cost')
        parts_tree.heading('Date', text='Date Recorded')
        parts_tree.heading('Recorded By', text='Recorded By')

        parts_tree.column('Part Number', width=120)
        parts_tree.column('Description', width=250)
        parts_tree.column('Qty Used', width=80)
        parts_tree.column('Cost', width=100)
        parts_tree.column('Date', width=150)
        parts_tree.column('Recorded By', width=100)

        # Populate with data
        total_cost = 0.0
        for part in parts_data:
            part_number = part[0]
            description = part[1] if part[1] else "N/A"
            qty_used = f"{part[2]:.2f}" if part[2] else "0"
            cost = part[3] if part[3] else 0.0
            total_cost += cost
            date_recorded = str(part[4])[:19] if part[4] else "N/A"
            recorded_by = part[5] if part[5] else "N/A"

            parts_tree.insert('', 'end', values=(
                part_number,
                description,
                qty_used,
                f"${cost:.2f}",
                date_recorded,
                recorded_by
            ))

        parts_tree.pack(fill='both', expand=True, padx=5, pady=5)

        # Summary frame
        summary_frame = ttk.Frame(dialog)
        summary_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(summary_frame, text=f"Total Cost: ${total_cost:.2f}",
                 font=('Arial', 11, 'bold')).pack(side='right', padx=10)

        # Close button
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)

        return dialog
