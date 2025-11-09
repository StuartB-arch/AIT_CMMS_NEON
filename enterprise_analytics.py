#!/usr/bin/env python3
"""
Enterprise-Level Analytics Module for AIT CMMS
Provides comprehensive data visualization with charts, graphs, and dashboards
Designed to compete with SAP-level reporting and analytics
"""

import matplotlib
matplotlib.use('TkAgg')  # Use TkAgg backend for Tkinter integration
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import seaborn as sns
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Dict, Tuple, Optional
import io
from PIL import Image
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors as rl_colors
from sklearn.linear_model import LinearRegression
from scipy import stats

# Set professional style
sns.set_style("whitegrid")
sns.set_palette("husl")
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = '#f8f9fa'
plt.rcParams['font.size'] = 10
plt.rcParams['font.family'] = 'sans-serif'

class EnterpriseAnalytics:
    """Enterprise-level analytics and visualization engine"""

    def __init__(self, db_connection):
        """Initialize enterprise analytics with database connection"""
        self.conn = db_connection
        self.color_scheme = {
            'primary': '#2E86AB',
            'success': '#06A77D',
            'warning': '#F77F00',
            'danger': '#D62828',
            'info': '#4EA8DE',
            'dark': '#2B2D42',
            'light': '#EDF2F4'
        }

    def create_executive_dashboard(self, parent_frame):
        """Create comprehensive executive dashboard with key metrics and charts"""

        # Clear parent frame
        for widget in parent_frame.winfo_children():
            widget.destroy()

        # Create main container with scrollbar
        canvas = tk.Canvas(parent_frame, bg='white')
        scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Title
        title_frame = ttk.Frame(scrollable_frame)
        title_frame.pack(fill='x', padx=20, pady=10)

        title_label = tk.Label(
            title_frame,
            text="EXECUTIVE DASHBOARD",
            font=('Arial', 24, 'bold'),
            fg=self.color_scheme['dark'],
            bg='white'
        )
        title_label.pack(side='left')

        date_label = tk.Label(
            title_frame,
            text=f"Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}",
            font=('Arial', 10),
            fg=self.color_scheme['info'],
            bg='white'
        )
        date_label.pack(side='right', padx=10)

        # KPI Cards Row
        kpi_frame = ttk.Frame(scrollable_frame)
        kpi_frame.pack(fill='x', padx=20, pady=10)

        self._create_kpi_cards(kpi_frame)

        # Charts Grid
        charts_frame = ttk.Frame(scrollable_frame)
        charts_frame.pack(fill='both', expand=True, padx=20, pady=10)

        # Row 1: PM Completion Trends and Equipment Status
        row1_frame = ttk.Frame(charts_frame)
        row1_frame.pack(fill='both', expand=True, pady=5)

        self._create_pm_completion_trend_chart(row1_frame, side='left')
        self._create_equipment_status_pie_chart(row1_frame, side='right')

        # Row 2: Technician Performance and CM Priority Distribution
        row2_frame = ttk.Frame(charts_frame)
        row2_frame.pack(fill='both', expand=True, pady=5)

        self._create_technician_performance_chart(row2_frame, side='left')
        self._create_cm_priority_distribution(row2_frame, side='right')

        # Row 3: PM Type Distribution and Location Heatmap
        row3_frame = ttk.Frame(charts_frame)
        row3_frame.pack(fill='both', expand=True, pady=5)

        self._create_pm_type_distribution(row3_frame, side='left')
        self._create_weekly_performance_chart(row3_frame, side='right')

        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _create_kpi_cards(self, parent_frame):
        """Create KPI cards showing key metrics"""
        try:
            cursor = self.conn.cursor()

            # Get key metrics
            # Active Equipment
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active_equipment = cursor.fetchone()[0]

            # PM Completion Rate (Last 30 days)
            cursor.execute('''
                SELECT COUNT(*) FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
            ''')
            recent_completions = cursor.fetchone()[0]

            # Open CMs
            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
            open_cms = cursor.fetchone()[0]

            # Avg Response Time (hours)
            cursor.execute('''
                SELECT AVG(labor_hours + labor_minutes/60.0)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
            ''')
            result = cursor.fetchone()
            avg_response = result[0] if result[0] else 0

            # Current Week Performance
            cursor.execute('''
                SELECT
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END)::float /
                    NULLIF(COUNT(*)::float, 0) * 100
                FROM weekly_pm_schedules
                WHERE week_start_date = (
                    SELECT MAX(week_start_date) FROM weekly_pm_schedules
                )
            ''')
            result = cursor.fetchone()
            week_completion_rate = result[0] if result[0] else 0

            # Parts Inventory Value
            cursor.execute('''
                SELECT SUM(quantity_in_stock * unit_price)
                FROM mro_stock
                WHERE status = 'Active'
            ''')
            result = cursor.fetchone()
            inventory_value = result[0] if result[0] else 0

            # Create KPI cards
            kpis = [
                ("Active Equipment", f"{active_equipment:,}", self.color_scheme['primary'], "🏭"),
                ("PM Completion (30d)", f"{recent_completions:,}", self.color_scheme['success'], "✓"),
                ("Open Work Orders", f"{open_cms:,}", self.color_scheme['warning'], "📋"),
                ("Avg Labor Hours", f"{avg_response:.1f}h", self.color_scheme['info'], "⏱"),
                ("Week Completion", f"{week_completion_rate:.1f}%", self.color_scheme['success'], "📊"),
                ("Inventory Value", f"${inventory_value:,.0f}", self.color_scheme['primary'], "💰")
            ]

            for i, (label, value, color, icon) in enumerate(kpis):
                card = tk.Frame(parent_frame, bg=color, relief='raised', borderwidth=2)
                card.grid(row=0, column=i, padx=5, pady=5, sticky='nsew')
                parent_frame.columnconfigure(i, weight=1)

                # Icon
                icon_label = tk.Label(card, text=icon, font=('Arial', 24), bg=color, fg='white')
                icon_label.pack(pady=(10, 0))

                # Value
                value_label = tk.Label(card, text=value, font=('Arial', 18, 'bold'), bg=color, fg='white')
                value_label.pack()

                # Label
                label_label = tk.Label(card, text=label, font=('Arial', 9), bg=color, fg='white')
                label_label.pack(pady=(0, 10))

        except Exception as e:
            print(f"Error creating KPI cards: {e}")

    def _create_pm_completion_trend_chart(self, parent_frame, side='left'):
        """Create PM completion trend line chart"""
        try:
            cursor = self.conn.cursor()

            # Get last 12 months of PM completions
            cursor.execute('''
                SELECT
                    DATE_TRUNC('month', completion_date::date) as month,
                    COUNT(*) as completions,
                    pm_type
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY DATE_TRUNC('month', completion_date::date), pm_type
                ORDER BY month
            ''')

            data = cursor.fetchall()

            if data:
                df = pd.DataFrame(data, columns=['Month', 'Completions', 'PM_Type'])
                df['Month'] = pd.to_datetime(df['Month'])

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                # Plot lines for each PM type
                for pm_type in df['PM_Type'].unique():
                    type_data = df[df['PM_Type'] == pm_type]
                    ax.plot(type_data['Month'], type_data['Completions'],
                           marker='o', linewidth=2, label=pm_type, markersize=6)

                ax.set_title('PM Completion Trends (12 Months)', fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('Month', fontsize=10)
                ax.set_ylabel('Completions', fontsize=10)
                ax.legend(loc='upper left', framealpha=0.9)
                ax.grid(True, alpha=0.3)
                fig.autofmt_xdate()
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating PM completion trend chart: {e}")

    def _create_equipment_status_pie_chart(self, parent_frame, side='right'):
        """Create equipment status distribution pie chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM equipment
                GROUP BY status
                ORDER BY count DESC
            ''')

            data = cursor.fetchall()

            if data:
                labels = [row[0] for row in data]
                sizes = [row[1] for row in data]

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                colors_list = [self.color_scheme['success'], self.color_scheme['warning'],
                              self.color_scheme['danger'], self.color_scheme['info']]

                wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                                   colors=colors_list, startangle=90,
                                                   textprops={'fontsize': 10})

                # Make percentage text bold
                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')
                    autotext.set_fontsize(11)

                ax.set_title('Equipment Status Distribution', fontsize=14, fontweight='bold', pad=15)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating equipment status pie chart: {e}")

    def _create_technician_performance_chart(self, parent_frame, side='left'):
        """Create technician performance bar chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    technician_name,
                    COUNT(*) as total_pms,
                    AVG(labor_hours + labor_minutes/60.0) as avg_hours
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY technician_name
                ORDER BY total_pms DESC
                LIMIT 10
            ''')

            data = cursor.fetchall()

            if data:
                technicians = [row[0] for row in data]
                completions = [row[1] for row in data]

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                bars = ax.barh(technicians, completions, color=self.color_scheme['primary'])

                # Add value labels on bars
                for i, (bar, value) in enumerate(zip(bars, completions)):
                    ax.text(value, i, f' {int(value)}', va='center', fontweight='bold')

                ax.set_title('Technician Performance (Last 30 Days)', fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('PM Completions', fontsize=10)
                ax.set_ylabel('Technician', fontsize=10)
                ax.grid(axis='x', alpha=0.3)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating technician performance chart: {e}")

    def _create_cm_priority_distribution(self, parent_frame, side='right'):
        """Create CM priority distribution stacked bar chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT priority, status, COUNT(*) as count
                FROM corrective_maintenance
                GROUP BY priority, status
                ORDER BY
                    CASE priority
                        WHEN 'Critical' THEN 1
                        WHEN 'High' THEN 2
                        WHEN 'Medium' THEN 3
                        WHEN 'Low' THEN 4
                    END,
                    status
            ''')

            data = cursor.fetchall()

            if data:
                df = pd.DataFrame(data, columns=['Priority', 'Status', 'Count'])
                pivot_df = df.pivot(index='Priority', columns='Status', values='Count').fillna(0)

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                pivot_df.plot(kind='bar', stacked=True, ax=ax,
                             color=[self.color_scheme['warning'], self.color_scheme['success']],
                             width=0.6)

                ax.set_title('CM Work Orders by Priority', fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('Priority', fontsize=10)
                ax.set_ylabel('Count', fontsize=10)
                ax.legend(title='Status', loc='upper right', framealpha=0.9)
                ax.grid(axis='y', alpha=0.3)
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating CM priority distribution chart: {e}")

    def _create_pm_type_distribution(self, parent_frame, side='left'):
        """Create PM type distribution donut chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    CASE
                        WHEN monthly_pm = 1 THEN 'Monthly'
                        WHEN six_month_pm = 1 THEN 'Six Month'
                        WHEN annual_pm = 1 THEN 'Annual'
                        ELSE 'None'
                    END as pm_type,
                    COUNT(*) as count
                FROM equipment
                WHERE status = 'Active'
                GROUP BY
                    CASE
                        WHEN monthly_pm = 1 THEN 'Monthly'
                        WHEN six_month_pm = 1 THEN 'Six Month'
                        WHEN annual_pm = 1 THEN 'Annual'
                        ELSE 'None'
                    END
            ''')

            data = cursor.fetchall()

            if data:
                labels = [row[0] for row in data]
                sizes = [row[1] for row in data]

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                colors_list = [self.color_scheme['primary'], self.color_scheme['info'],
                              self.color_scheme['success'], self.color_scheme['light']]

                wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                                   colors=colors_list, startangle=90,
                                                   pctdistance=0.85,
                                                   textprops={'fontsize': 10})

                # Draw circle in center for donut effect
                centre_circle = plt.Circle((0, 0), 0.70, fc='white')
                ax.add_artist(centre_circle)

                # Make percentage text bold
                for autotext in autotexts:
                    autotext.set_color('black')
                    autotext.set_fontweight('bold')
                    autotext.set_fontsize(10)

                ax.set_title('PM Type Requirements', fontsize=14, fontweight='bold', pad=15)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating PM type distribution chart: {e}")

    def _create_weekly_performance_chart(self, parent_frame, side='right'):
        """Create weekly performance trend chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    week_start_date,
                    COUNT(*) as scheduled,
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed
                FROM weekly_pm_schedules
                WHERE week_start_date >= CURRENT_DATE - INTERVAL '12 weeks'
                GROUP BY week_start_date
                ORDER BY week_start_date
            ''')

            data = cursor.fetchall()

            if data:
                weeks = [row[0] for row in data]
                scheduled = [row[1] for row in data]
                completed = [row[2] for row in data]
                completion_rate = [(c/s*100 if s > 0 else 0) for c, s in zip(completed, scheduled)]

                # Create figure
                fig = Figure(figsize=(6, 4), dpi=100)
                ax = fig.add_subplot(111)

                x = range(len(weeks))
                width = 0.35

                bars1 = ax.bar([i - width/2 for i in x], scheduled, width,
                              label='Scheduled', color=self.color_scheme['info'], alpha=0.8)
                bars2 = ax.bar([i + width/2 for i in x], completed, width,
                              label='Completed', color=self.color_scheme['success'], alpha=0.8)

                # Add completion rate line
                ax2 = ax.twinx()
                line = ax2.plot(x, completion_rate, color=self.color_scheme['danger'],
                               marker='o', linewidth=2, label='Completion %', markersize=6)
                ax2.set_ylabel('Completion Rate (%)', fontsize=10)
                ax2.set_ylim(0, 110)

                ax.set_title('Weekly PM Performance', fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('Week', fontsize=10)
                ax.set_ylabel('PM Count', fontsize=10)
                ax.set_xticks(x)
                ax.set_xticklabels([w.strftime('%m/%d') for w in weeks], rotation=45, ha='right')

                # Combine legends
                lines1, labels1 = ax.get_legend_handles_labels()
                lines2, labels2 = ax2.get_legend_handles_labels()
                ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9)

                ax.grid(axis='y', alpha=0.3)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating weekly performance chart: {e}")

    def create_predictive_analytics_dashboard(self, parent_frame):
        """Create predictive analytics dashboard with ML-based forecasts"""
        try:
            # Clear parent frame
            for widget in parent_frame.winfo_children():
                widget.destroy()

            # Create main container
            main_frame = ttk.Frame(parent_frame)
            main_frame.pack(fill='both', expand=True, padx=20, pady=20)

            # Title
            title_label = tk.Label(
                main_frame,
                text="PREDICTIVE ANALYTICS & FORECASTING",
                font=('Arial', 20, 'bold'),
                fg=self.color_scheme['dark'],
                bg='white'
            )
            title_label.pack(pady=(0, 20))

            # Create charts
            charts_frame = ttk.Frame(main_frame)
            charts_frame.pack(fill='both', expand=True)

            # Equipment Failure Prediction
            self._create_failure_prediction_chart(charts_frame)

            # Workload Forecast
            self._create_workload_forecast_chart(charts_frame)

        except Exception as e:
            print(f"Error creating predictive analytics dashboard: {e}")
            messagebox.showerror("Error", f"Failed to create predictive analytics: {str(e)}")

    def _create_failure_prediction_chart(self, parent_frame):
        """Create equipment failure prediction chart using historical data"""
        try:
            cursor = self.conn.cursor()

            # Get CM creation trends
            cursor.execute('''
                SELECT
                    DATE_TRUNC('week', reported_date::date) as week,
                    COUNT(*) as cm_count
                FROM corrective_maintenance
                WHERE reported_date >= CURRENT_DATE - INTERVAL '26 weeks'
                GROUP BY DATE_TRUNC('week', reported_date::date)
                ORDER BY week
            ''')

            data = cursor.fetchall()

            if len(data) > 4:  # Need enough data for prediction
                weeks = [row[0] for row in data]
                counts = [row[1] for row in data]

                # Prepare data for linear regression
                X = np.array(range(len(counts))).reshape(-1, 1)
                y = np.array(counts)

                # Train model
                model = LinearRegression()
                model.fit(X, y)

                # Predict next 4 weeks
                future_X = np.array(range(len(counts), len(counts) + 4)).reshape(-1, 1)
                predictions = model.predict(future_X)

                # Create figure
                fig = Figure(figsize=(12, 5), dpi=100)
                ax = fig.add_subplot(111)

                # Plot historical data
                ax.plot(range(len(counts)), counts, marker='o', linewidth=2,
                       label='Historical CM Count', color=self.color_scheme['primary'], markersize=6)

                # Plot predictions
                all_x = list(range(len(counts))) + list(range(len(counts), len(counts) + 4))
                all_y = list(counts) + list(predictions)
                ax.plot(range(len(counts) - 1, len(counts) + 4),
                       [counts[-1]] + list(predictions),
                       'r--', linewidth=2, label='Forecast', marker='s', markersize=6)

                # Add confidence interval
                residuals = y - model.predict(X)
                std_error = np.std(residuals)
                ax.fill_between(range(len(counts), len(counts) + 4),
                               predictions - 1.96 * std_error,
                               predictions + 1.96 * std_error,
                               alpha=0.2, color=self.color_scheme['danger'],
                               label='95% Confidence Interval')

                ax.set_title('Equipment Failure Prediction (Next 4 Weeks)',
                           fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('Week', fontsize=11)
                ax.set_ylabel('Corrective Maintenance Count', fontsize=11)
                ax.legend(loc='upper left', framealpha=0.9, fontsize=10)
                ax.grid(True, alpha=0.3)

                # Add trend indicator
                trend = "↑ INCREASING" if model.coef_[0] > 0 else "↓ DECREASING"
                trend_color = self.color_scheme['danger'] if model.coef_[0] > 0 else self.color_scheme['success']
                ax.text(0.02, 0.98, f"Trend: {trend}", transform=ax.transAxes,
                       fontsize=12, fontweight='bold', color=trend_color,
                       verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(fill='both', expand=True, pady=10)

        except Exception as e:
            print(f"Error creating failure prediction chart: {e}")

    def _create_workload_forecast_chart(self, parent_frame):
        """Create technician workload forecast"""
        try:
            cursor = self.conn.cursor()

            # Get upcoming scheduled PMs by technician
            cursor.execute('''
                SELECT
                    assigned_technician,
                    COUNT(*) as upcoming_pms
                FROM weekly_pm_schedules
                WHERE week_start_date >= CURRENT_DATE
                AND status = 'Scheduled'
                GROUP BY assigned_technician
                ORDER BY upcoming_pms DESC
            ''')

            data = cursor.fetchall()

            if data:
                technicians = [row[0] for row in data]
                workload = [row[1] for row in data]

                # Create figure
                fig = Figure(figsize=(12, 5), dpi=100)
                ax = fig.add_subplot(111)

                # Create color gradient based on workload
                colors_gradient = []
                max_load = max(workload) if workload else 1
                for load in workload:
                    if load / max_load > 0.75:
                        colors_gradient.append(self.color_scheme['danger'])
                    elif load / max_load > 0.5:
                        colors_gradient.append(self.color_scheme['warning'])
                    else:
                        colors_gradient.append(self.color_scheme['success'])

                bars = ax.barh(technicians, workload, color=colors_gradient)

                # Add value labels
                for i, (bar, value) in enumerate(zip(bars, workload)):
                    ax.text(value, i, f' {int(value)} PMs', va='center', fontweight='bold', fontsize=10)

                ax.set_title('Upcoming Workload Forecast by Technician',
                           fontsize=14, fontweight='bold', pad=15)
                ax.set_xlabel('Scheduled PMs', fontsize=11)
                ax.set_ylabel('Technician', fontsize=11)
                ax.grid(axis='x', alpha=0.3)

                # Add legend for colors
                from matplotlib.patches import Patch
                legend_elements = [
                    Patch(facecolor=self.color_scheme['success'], label='Low (<50%)'),
                    Patch(facecolor=self.color_scheme['warning'], label='Medium (50-75%)'),
                    Patch(facecolor=self.color_scheme['danger'], label='High (>75%)')
                ]
                ax.legend(handles=legend_elements, loc='lower right', framealpha=0.9, fontsize=10)

                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(fill='both', expand=True, pady=10)

        except Exception as e:
            print(f"Error creating workload forecast chart: {e}")

    def export_dashboard_to_pdf(self, dashboard_type='executive'):
        """Export dashboard with embedded charts to PDF"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                initialfile=f"AIT_CMMS_{dashboard_type}_Dashboard_{timestamp}.pdf"
            )

            if not filename:
                return

            # Create PDF
            doc = SimpleDocTemplate(filename, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()

            # Title
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=rl_colors.HexColor('#2B2D42'),
                spaceAfter=30,
                alignment=1  # Center
            )

            story.append(Paragraph(f"AIT CMMS {dashboard_type.upper()} DASHBOARD", title_style))
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}", styles['Normal']))
            story.append(Spacer(1, 0.5*inch))

            # Add charts as images
            # This would require saving matplotlib figures and embedding them
            # For now, add data tables

            cursor = self.conn.cursor()

            # Executive Summary Table
            cursor.execute('''
                SELECT
                    'Active Equipment' as metric,
                    COUNT(*)::text as value
                FROM equipment WHERE status = 'Active'
                UNION ALL
                SELECT
                    'Open Work Orders',
                    COUNT(*)::text
                FROM corrective_maintenance WHERE status = 'Open'
                UNION ALL
                SELECT
                    'PM Completions (30d)',
                    COUNT(*)::text
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '30 days'
            ''')

            data = [['Metric', 'Value']] + cursor.fetchall()

            table = Table(data, colWidths=[4*inch, 2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#2E86AB')),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), rl_colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, rl_colors.black)
            ]))

            story.append(table)

            # Build PDF
            doc.build(story)

            messagebox.showinfo("Success", f"Dashboard exported to:\n{filename}")

        except Exception as e:
            print(f"Error exporting dashboard to PDF: {e}")
            messagebox.showerror("Error", f"Failed to export dashboard: {str(e)}")

    def create_inventory_analytics(self, parent_frame):
        """Create MRO inventory analytics dashboard"""
        try:
            # Clear parent frame
            for widget in parent_frame.winfo_children():
                widget.destroy()

            # Create main container
            main_frame = ttk.Frame(parent_frame)
            main_frame.pack(fill='both', expand=True, padx=20, pady=20)

            # Title
            title_label = tk.Label(
                main_frame,
                text="MRO INVENTORY ANALYTICS",
                font=('Arial', 20, 'bold'),
                fg=self.color_scheme['dark'],
                bg='white'
            )
            title_label.pack(pady=(0, 20))

            # Create charts grid
            top_frame = ttk.Frame(main_frame)
            top_frame.pack(fill='both', expand=True)

            bottom_frame = ttk.Frame(main_frame)
            bottom_frame.pack(fill='both', expand=True)

            self._create_stock_levels_chart(top_frame, side='left')
            self._create_inventory_value_chart(top_frame, side='right')
            self._create_low_stock_alerts_chart(bottom_frame)

        except Exception as e:
            print(f"Error creating inventory analytics: {e}")

    def _create_stock_levels_chart(self, parent_frame, side='left'):
        """Create stock levels comparison chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    part_number,
                    name,
                    quantity_in_stock,
                    minimum_stock,
                    maximum_stock
                FROM mro_stock
                WHERE status = 'Active'
                AND (quantity_in_stock <= minimum_stock OR maximum_stock > 0)
                ORDER BY (quantity_in_stock::float / NULLIF(minimum_stock, 0)) ASC
                LIMIT 15
            ''')

            data = cursor.fetchall()

            if data:
                parts = [f"{row[0][:15]}" for row in data]
                current = [row[2] for row in data]
                minimum = [row[3] for row in data]
                maximum = [row[4] for row in data]

                # Create figure
                fig = Figure(figsize=(6, 5), dpi=100)
                ax = fig.add_subplot(111)

                x = np.arange(len(parts))
                width = 0.25

                ax.barh([i - width for i in x], current, width, label='Current',
                       color=self.color_scheme['primary'])
                ax.barh(x, minimum, width, label='Minimum',
                       color=self.color_scheme['warning'])
                ax.barh([i + width for i in x], maximum, width, label='Maximum',
                       color=self.color_scheme['success'])

                ax.set_ylabel('Part Number', fontsize=10)
                ax.set_xlabel('Quantity', fontsize=10)
                ax.set_title('Stock Levels - Critical Items', fontsize=12, fontweight='bold', pad=10)
                ax.set_yticks(x)
                ax.set_yticklabels(parts, fontsize=8)
                ax.legend(loc='lower right', framealpha=0.9)
                ax.grid(axis='x', alpha=0.3)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating stock levels chart: {e}")

    def _create_inventory_value_chart(self, parent_frame, side='right'):
        """Create inventory value distribution chart"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    equipment,
                    SUM(quantity_in_stock * unit_price) as total_value
                FROM mro_stock
                WHERE status = 'Active'
                AND equipment IS NOT NULL AND equipment != ''
                GROUP BY equipment
                ORDER BY total_value DESC
                LIMIT 10
            ''')

            data = cursor.fetchall()

            if data:
                equipment = [row[0][:20] for row in data]
                values = [float(row[1]) if row[1] else 0 for row in data]

                # Create figure
                fig = Figure(figsize=(6, 5), dpi=100)
                ax = fig.add_subplot(111)

                colors_gradient = plt.cm.Blues(np.linspace(0.4, 0.8, len(equipment)))
                bars = ax.bar(range(len(equipment)), values, color=colors_gradient)

                # Add value labels
                for bar, value in zip(bars, values):
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'${value:,.0f}',
                           ha='center', va='bottom', fontsize=8, fontweight='bold')

                ax.set_xlabel('Equipment Category', fontsize=10)
                ax.set_ylabel('Inventory Value ($)', fontsize=10)
                ax.set_title('Inventory Value by Equipment', fontsize=12, fontweight='bold', pad=10)
                ax.set_xticks(range(len(equipment)))
                ax.set_xticklabels(equipment, rotation=45, ha='right', fontsize=8)
                ax.grid(axis='y', alpha=0.3)
                fig.tight_layout()

                # Embed in Tkinter
                canvas = FigureCanvasTkAgg(fig, parent_frame)
                canvas.draw()
                canvas.get_tk_widget().pack(side=side, fill='both', expand=True, padx=5)

        except Exception as e:
            print(f"Error creating inventory value chart: {e}")

    def _create_low_stock_alerts_chart(self, parent_frame):
        """Create low stock alerts dashboard"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT
                    COUNT(*) as low_stock_count
                FROM mro_stock
                WHERE status = 'Active'
                AND quantity_in_stock <= minimum_stock
            ''')

            low_stock_count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT
                    COUNT(*) as out_of_stock
                FROM mro_stock
                WHERE status = 'Active'
                AND quantity_in_stock = 0
            ''')

            out_of_stock = cursor.fetchone()[0]

            # Create alert display
            alert_frame = tk.Frame(parent_frame, bg='white', relief='solid', borderwidth=2)
            alert_frame.pack(fill='both', expand=True, padx=5, pady=10)

            tk.Label(
                alert_frame,
                text="⚠ STOCK ALERTS",
                font=('Arial', 16, 'bold'),
                fg=self.color_scheme['danger'],
                bg='white'
            ).pack(pady=10)

            # Low stock alert
            low_stock_frame = tk.Frame(alert_frame, bg=self.color_scheme['warning'],
                                      relief='raised', borderwidth=2)
            low_stock_frame.pack(fill='x', padx=20, pady=5)

            tk.Label(
                low_stock_frame,
                text=str(low_stock_count),
                font=('Arial', 36, 'bold'),
                fg='white',
                bg=self.color_scheme['warning']
            ).pack()

            tk.Label(
                low_stock_frame,
                text="Items Below Minimum Stock",
                font=('Arial', 12),
                fg='white',
                bg=self.color_scheme['warning']
            ).pack()

            # Out of stock alert
            out_of_stock_frame = tk.Frame(alert_frame, bg=self.color_scheme['danger'],
                                         relief='raised', borderwidth=2)
            out_of_stock_frame.pack(fill='x', padx=20, pady=5)

            tk.Label(
                out_of_stock_frame,
                text=str(out_of_stock),
                font=('Arial', 36, 'bold'),
                fg='white',
                bg=self.color_scheme['danger']
            ).pack()

            tk.Label(
                out_of_stock_frame,
                text="Items Out of Stock",
                font=('Arial', 12),
                fg='white',
                bg=self.color_scheme['danger']
            ).pack(pady=(0, 10))

        except Exception as e:
            print(f"Error creating low stock alerts: {e}")


def create_enterprise_dashboard_window(db_connection):
    """Create standalone enterprise dashboard window"""
    dashboard_window = tk.Toplevel()
    dashboard_window.title("AIT CMMS - Enterprise Analytics Dashboard")
    dashboard_window.geometry("1400x900")

    # Create notebook for different dashboards
    notebook = ttk.Notebook(dashboard_window)
    notebook.pack(fill='both', expand=True, padx=10, pady=10)

    # Initialize analytics engine
    analytics = EnterpriseAnalytics(db_connection)

    # Tab 1: Executive Dashboard
    exec_frame = ttk.Frame(notebook)
    notebook.add(exec_frame, text="Executive Dashboard")
    analytics.create_executive_dashboard(exec_frame)

    # Tab 2: Predictive Analytics
    pred_frame = ttk.Frame(notebook)
    notebook.add(pred_frame, text="Predictive Analytics")
    analytics.create_predictive_analytics_dashboard(pred_frame)

    # Tab 3: Inventory Analytics
    inv_frame = ttk.Frame(notebook)
    notebook.add(inv_frame, text="Inventory Analytics")
    analytics.create_inventory_analytics(inv_frame)

    # Export button
    button_frame = ttk.Frame(dashboard_window)
    button_frame.pack(side='bottom', fill='x', padx=10, pady=10)

    ttk.Button(
        button_frame,
        text="Export to PDF",
        command=analytics.export_dashboard_to_pdf
    ).pack(side='right', padx=5)

    ttk.Button(
        button_frame,
        text="Refresh All",
        command=lambda: refresh_all_dashboards(analytics, exec_frame, pred_frame, inv_frame)
    ).pack(side='right', padx=5)

    return dashboard_window


def refresh_all_dashboards(analytics, exec_frame, pred_frame, inv_frame):
    """Refresh all dashboard tabs"""
    analytics.create_executive_dashboard(exec_frame)
    analytics.create_predictive_analytics_dashboard(pred_frame)
    analytics.create_inventory_analytics(inv_frame)
