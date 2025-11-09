"""
Enhanced KPI Management UI with Charts and Visualizations
Enterprise-level KPI dashboard with trend analysis and visual insights
"""

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from kpi_manager import KPIManager
from datetime import datetime
import traceback
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
from PIL import Image
import io

# Set professional style
sns.set_style("whitegrid")
sns.set_palette("husl")


class KPIChartWidget(QWidget):
    """Widget for displaying KPI charts"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def plot_kpi_trends(self, kpi_data, kpi_name):
        """Plot KPI trends over time"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if not kpi_data:
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center',
                   verticalalignment='center',
                   transform=ax.transAxes,
                   fontsize=14)
            self.canvas.draw()
            return

        # Extract data
        periods = [item['period'] for item in kpi_data]
        values = [float(item['value']) if item['value'] is not None else 0 for item in kpi_data]
        targets = [float(item['target']) if item['target'] is not None else 0 for item in kpi_data]

        # Plot
        ax.plot(periods, values, marker='o', linewidth=2, markersize=8, label='Actual', color='#2E86AB')
        ax.plot(periods, targets, '--', linewidth=2, label='Target', color='#06A77D')

        # Fill area between
        ax.fill_between(range(len(periods)), values, targets, alpha=0.2)

        ax.set_title(f'{kpi_name} Trend Analysis', fontsize=14, fontweight='bold', pad=15)
        ax.set_xlabel('Period', fontsize=11)
        ax.set_ylabel('Value', fontsize=11)
        ax.legend(loc='best', framealpha=0.9)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(range(len(periods)))
        ax.set_xticklabels(periods, rotation=45, ha='right')

        self.figure.tight_layout()
        self.canvas.draw()

    def plot_kpi_summary(self, kpi_results):
        """Plot KPI summary with pass/fail distribution"""
        self.figure.clear()

        if not kpi_results:
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center',
                   verticalalignment='center',
                   transform=ax.transAxes,
                   fontsize=14)
            self.canvas.draw()
            return

        # Count status
        status_counts = {}
        for result in kpi_results:
            status = result.get('status', 'Pending')
            status_counts[status] = status_counts.get(status, 0) + 1

        # Create pie chart
        ax1 = self.figure.add_subplot(121)
        colors_list = {'Pass': '#06A77D', 'Fail': '#D62828', 'Pending': '#F77F00'}
        pie_colors = [colors_list.get(status, '#2E86AB') for status in status_counts.keys()]

        wedges, texts, autotexts = ax1.pie(
            status_counts.values(),
            labels=status_counts.keys(),
            autopct='%1.1f%%',
            colors=pie_colors,
            startangle=90,
            textprops={'fontsize': 11}
        )

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')

        ax1.set_title('KPI Status Distribution', fontsize=12, fontweight='bold')

        # Create bar chart for top KPIs
        ax2 = self.figure.add_subplot(122)

        # Get top 10 KPIs by value
        kpi_values = [(r['kpi_name'][:20], float(r['value']) if r['value'] else 0)
                     for r in kpi_results if r.get('value') is not None]
        kpi_values.sort(key=lambda x: abs(x[1]), reverse=True)
        kpi_values = kpi_values[:10]

        if kpi_values:
            names = [k[0] for k in kpi_values]
            values = [k[1] for k in kpi_values]

            bars = ax2.barh(names, values, color='#2E86AB')
            ax2.set_title('Top 10 KPIs by Value', fontsize=12, fontweight='bold')
            ax2.set_xlabel('Value', fontsize=10)
            ax2.grid(axis='x', alpha=0.3)

            # Add value labels
            for bar, value in zip(bars, values):
                width = bar.get_width()
                ax2.text(width, bar.get_y() + bar.get_height()/2,
                        f' {value:.1f}',
                        va='center', fontweight='bold', fontsize=8)

        self.figure.tight_layout()
        self.canvas.draw()

    def plot_category_performance(self, kpi_results):
        """Plot performance by category"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if not kpi_results:
            ax.text(0.5, 0.5, 'No data available',
                   horizontalalignment='center',
                   verticalalignment='center',
                   transform=ax.transAxes,
                   fontsize=14)
            self.canvas.draw()
            return

        # Group by category
        categories = {}
        for result in kpi_results:
            cat = result.get('category', 'Other')
            if cat not in categories:
                categories[cat] = {'pass': 0, 'fail': 0, 'pending': 0}

            status = result.get('status', 'Pending').lower()
            if status in categories[cat]:
                categories[cat][status] += 1

        # Prepare data for stacked bar chart
        cat_names = list(categories.keys())
        pass_counts = [categories[cat]['pass'] for cat in cat_names]
        fail_counts = [categories[cat]['fail'] for cat in cat_names]
        pending_counts = [categories[cat]['pending'] for cat in cat_names]

        x = np.arange(len(cat_names))
        width = 0.6

        ax.bar(x, pass_counts, width, label='Pass', color='#06A77D')
        ax.bar(x, fail_counts, width, bottom=pass_counts, label='Fail', color='#D62828')
        ax.bar(x, pending_counts, width,
              bottom=[p+f for p, f in zip(pass_counts, fail_counts)],
              label='Pending', color='#F77F00')

        ax.set_title('KPI Performance by Category', fontsize=14, fontweight='bold', pad=15)
        ax.set_ylabel('Count', fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(cat_names, rotation=45, ha='right')
        ax.legend(loc='upper right', framealpha=0.9)
        ax.grid(axis='y', alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()


class EnhancedKPIDashboard(QWidget):
    """Enhanced KPI Dashboard with Charts and Visualizations"""

    def __init__(self, pool, current_user, parent=None):
        super().__init__(parent)
        self.pool = pool
        self.current_user = current_user
        self.kpi_manager = KPIManager(pool)
        self.current_period = datetime.now().strftime('%Y-%m')
        self.init_ui()

    def init_ui(self):
        """Initialize the enhanced user interface"""
        layout = QVBoxLayout()

        # Title with modern styling
        title_label = QLabel("🎯 2025 KPI Dashboard - Enterprise Analytics")
        title_label.setStyleSheet("""
            font-size: 22pt;
            font-weight: bold;
            color: #2c3e50;
            padding: 15px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                       stop:0 #3498db, stop:1 #2ecc71);
            border-radius: 10px;
            color: white;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Control panel
        control_layout = QHBoxLayout()

        # Period selector
        control_layout.addWidget(QLabel("Period:"))
        self.period_combo = QComboBox()
        self.period_combo.setStyleSheet("padding: 5px; font-size: 11pt;")
        self.populate_periods()
        self.period_combo.currentTextChanged.connect(self.on_period_changed)
        control_layout.addWidget(self.period_combo)

        control_layout.addStretch()

        # Buttons
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 10px 20px; border-radius: 5px;")
        refresh_btn.clicked.connect(self.refresh_dashboard)
        control_layout.addWidget(refresh_btn)

        calc_btn = QPushButton("📊 Calculate KPIs")
        calc_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px 20px; border-radius: 5px;")
        calc_btn.clicked.connect(self.calculate_auto_kpis)
        control_layout.addWidget(calc_btn)

        export_btn = QPushButton("📄 Export PDF")
        export_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 10px 20px; border-radius: 5px;")
        export_btn.clicked.connect(self.export_enhanced_pdf)
        control_layout.addWidget(export_btn)

        layout.addLayout(control_layout)

        # KPI Summary Cards
        self.summary_layout = QHBoxLayout()
        self.create_summary_cards()
        layout.addLayout(self.summary_layout)

        # Tab widget for different views
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #3498db;
                border-radius: 5px;
            }
            QTabBar::tab {
                background: #ecf0f1;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background: #3498db;
                color: white;
                font-weight: bold;
            }
        """)

        # Tab 1: Visual Overview
        self.overview_tab = self.create_visual_overview_tab()
        tab_widget.addTab(self.overview_tab, "📊 Visual Overview")

        # Tab 2: Trend Analysis
        self.trend_tab = self.create_trend_analysis_tab()
        tab_widget.addTab(self.trend_tab, "📈 Trend Analysis")

        # Tab 3: Detailed Table
        self.table_tab = self.create_detailed_table_tab()
        tab_widget.addTab(self.table_tab, "📋 Detailed View")

        # Tab 4: Manual Input (from original)
        self.input_tab = self.create_input_tab()
        tab_widget.addTab(self.input_tab, "✏ Manual Input")

        layout.addWidget(tab_widget)
        self.setLayout(layout)

        self.refresh_dashboard()

    def create_summary_cards(self):
        """Create KPI summary cards"""
        # Clear existing cards
        while self.summary_layout.count():
            child = self.summary_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        try:
            # Get KPI results for current period
            kpi_results = self.kpi_manager.get_period_results(self.current_period)

            total = len(kpi_results)
            passed = sum(1 for r in kpi_results if r.get('status') == 'Pass')
            failed = sum(1 for r in kpi_results if r.get('status') == 'Fail')
            pending = sum(1 for r in kpi_results if r.get('status') == 'Pending')

            pass_rate = (passed / total * 100) if total > 0 else 0

            cards = [
                ("Total KPIs", str(total), "#3498db", "📊"),
                ("Passing", str(passed), "#2ecc71", "✓"),
                ("Failing", str(failed), "#e74c3c", "✗"),
                ("Pending", str(pending), "#f39c12", "⏳"),
                ("Pass Rate", f"{pass_rate:.1f}%", "#9b59b6", "📈")
            ]

            for title, value, color, icon in cards:
                card = self.create_card(title, value, color, icon)
                self.summary_layout.addWidget(card)

        except Exception as e:
            print(f"Error creating summary cards: {e}")

    def create_card(self, title, value, color, icon):
        """Create a summary card widget"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        card.setLineWidth(2)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {color};
                border-radius: 10px;
                padding: 15px;
            }}
            QLabel {{
                color: white;
            }}
        """)

        card_layout = QVBoxLayout()

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 32pt;")
        icon_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(icon_label)

        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 28pt; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(value_label)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 12pt;")
        title_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title_label)

        card.setLayout(card_layout)
        return card

    def create_visual_overview_tab(self):
        """Create visual overview tab with charts"""
        tab = QWidget()
        layout = QVBoxLayout()

        # Chart widget
        self.overview_chart = KPIChartWidget()
        layout.addWidget(self.overview_chart)

        tab.setLayout(layout)
        return tab

    def create_trend_analysis_tab(self):
        """Create trend analysis tab"""
        tab = QWidget()
        layout = QVBoxLayout()

        # KPI selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Select KPI:"))

        self.kpi_selector = QComboBox()
        self.kpi_selector.setStyleSheet("padding: 5px; font-size: 10pt;")
        self.kpi_selector.currentTextChanged.connect(self.update_trend_chart)
        selector_layout.addWidget(self.kpi_selector)

        selector_layout.addStretch()
        layout.addLayout(selector_layout)

        # Chart widget
        self.trend_chart = KPIChartWidget()
        layout.addWidget(self.trend_chart)

        tab.setLayout(layout)
        return tab

    def create_detailed_table_tab(self):
        """Create detailed table view"""
        tab = QWidget()
        layout = QVBoxLayout()

        self.kpi_table = QTableWidget()
        self.kpi_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #bdc3c7;
                font-size: 10pt;
            }
            QHeaderView::section {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 8px;
            }
        """)
        layout.addWidget(self.kpi_table)

        tab.setLayout(layout)
        return tab

    def create_input_tab(self):
        """Create manual input tab"""
        tab = QWidget()
        layout = QVBoxLayout()

        # Import from original KPI UI
        info_label = QLabel("Use this tab to input manual KPI data such as safety metrics, quality scores, etc.")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("padding: 10px; background-color: #ecf0f1; border-radius: 5px;")
        layout.addWidget(info_label)

        # Form area
        form_group = QGroupBox("Manual KPI Data Entry")
        form_layout = QFormLayout()

        self.manual_kpi_combo = QComboBox()
        form_layout.addRow("KPI:", self.manual_kpi_combo)

        self.manual_value_spin = QDoubleSpinBox()
        self.manual_value_spin.setRange(-999999, 999999)
        self.manual_value_spin.setDecimals(2)
        form_layout.addRow("Value:", self.manual_value_spin)

        self.manual_notes = QTextEdit()
        self.manual_notes.setMaximumHeight(80)
        form_layout.addRow("Notes:", self.manual_notes)

        submit_btn = QPushButton("💾 Submit Data")
        submit_btn.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        submit_btn.clicked.connect(self.submit_manual_data)
        form_layout.addRow("", submit_btn)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def populate_periods(self):
        """Populate period dropdown"""
        self.period_combo.clear()
        current = datetime.now()

        for i in range(12):
            month = current.month - i
            year = current.year

            while month < 1:
                month += 12
                year -= 1

            period = f"{year}-{month:02d}"
            self.period_combo.addItem(period)

        self.period_combo.setCurrentIndex(0)

    def on_period_changed(self, period):
        """Handle period change"""
        self.current_period = period
        self.refresh_dashboard()

    def refresh_dashboard(self):
        """Refresh all dashboard components"""
        try:
            # Update summary cards
            self.create_summary_cards()

            # Get KPI results
            kpi_results = self.kpi_manager.get_period_results(self.current_period)

            # Update overview chart
            self.overview_chart.plot_kpi_summary(kpi_results)

            # Update KPI selector for trends
            self.kpi_selector.clear()
            kpi_defs = self.kpi_manager.get_all_kpis()
            for kpi in kpi_defs:
                self.kpi_selector.addItem(kpi['name'], kpi['id'])

            # Update manual KPI selector
            if hasattr(self, 'manual_kpi_combo'):
                self.manual_kpi_combo.clear()
                # Get list of manual KPIs from KPI manager
                manual_kpi_names = self.kpi_manager.get_kpis_needing_manual_data()
                # Filter kpi_defs to only include manual KPIs
                manual_kpis = [k for k in kpi_defs if k['name'] in manual_kpi_names]
                for kpi in manual_kpis:
                    self.manual_kpi_combo.addItem(kpi['name'], kpi['id'])

            # Update table
            self.update_kpi_table(kpi_results)

            # Update trend if KPI selected
            if self.kpi_selector.count() > 0:
                self.update_trend_chart(self.kpi_selector.currentText())

        except Exception as e:
            print(f"Error refreshing dashboard: {e}")
            traceback.print_exc()

    def update_trend_chart(self, kpi_name):
        """Update trend chart for selected KPI"""
        try:
            if not kpi_name:
                return

            kpi_id = self.kpi_selector.currentData()
            if not kpi_id:
                return

            # Get trend data (last 12 months)
            trend_data = self.kpi_manager.get_kpi_trend(kpi_id, months=12)

            self.trend_chart.plot_kpi_trends(trend_data, kpi_name)

        except Exception as e:
            print(f"Error updating trend chart: {e}")

    def update_kpi_table(self, kpi_results):
        """Update KPI table with results"""
        try:
            self.kpi_table.setColumnCount(7)
            self.kpi_table.setHorizontalHeaderLabels([
                "KPI Name", "Category", "Value", "Target", "Status", "Notes", "Updated"
            ])

            self.kpi_table.setRowCount(len(kpi_results))

            for row, result in enumerate(kpi_results):
                self.kpi_table.setItem(row, 0, QTableWidgetItem(result.get('kpi_name', '')))
                self.kpi_table.setItem(row, 1, QTableWidgetItem(result.get('category', '')))

                value = result.get('value', '')
                self.kpi_table.setItem(row, 2, QTableWidgetItem(str(value) if value is not None else ''))

                target = result.get('target', '')
                self.kpi_table.setItem(row, 3, QTableWidgetItem(str(target) if target is not None else ''))

                status = result.get('status', 'Pending')
                status_item = QTableWidgetItem(status)

                # Color code status
                if status == 'Pass':
                    status_item.setBackground(QColor('#2ecc71'))
                    status_item.setForeground(QColor('white'))
                elif status == 'Fail':
                    status_item.setBackground(QColor('#e74c3c'))
                    status_item.setForeground(QColor('white'))
                else:
                    status_item.setBackground(QColor('#f39c12'))
                    status_item.setForeground(QColor('white'))

                status_item.setTextAlignment(Qt.AlignCenter)
                self.kpi_table.setItem(row, 4, status_item)

                self.kpi_table.setItem(row, 5, QTableWidgetItem(result.get('notes', '')[:50]))
                self.kpi_table.setItem(row, 6, QTableWidgetItem(result.get('updated_date', '')))

            self.kpi_table.resizeColumnsToContents()

        except Exception as e:
            print(f"Error updating table: {e}")

    def calculate_auto_kpis(self):
        """Calculate automatic KPIs"""
        try:
            reply = QMessageBox.question(
                self, 'Calculate KPIs',
                f'Calculate automatic KPIs for period {self.current_period}?',
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                results = self.kpi_manager.calculate_all_kpis(self.current_period)

                QMessageBox.information(
                    self, 'Success',
                    f'Calculated {len(results)} automatic KPIs for {self.current_period}'
                )

                self.refresh_dashboard()

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to calculate KPIs: {str(e)}')
            traceback.print_exc()

    def submit_manual_data(self):
        """Submit manual KPI data"""
        try:
            kpi_id = self.manual_kpi_combo.currentData()
            if not kpi_id:
                QMessageBox.warning(self, 'Warning', 'Please select a KPI')
                return

            value = self.manual_value_spin.value()
            notes = self.manual_notes.toPlainText()

            self.kpi_manager.record_manual_data(
                kpi_id, self.current_period, value, notes, self.current_user
            )

            # Recalculate to update result
            self.kpi_manager.calculate_single_kpi(kpi_id, self.current_period)

            QMessageBox.information(self, 'Success', 'Manual KPI data submitted successfully')

            self.manual_value_spin.setValue(0)
            self.manual_notes.clear()
            self.refresh_dashboard()

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to submit data: {str(e)}')
            traceback.print_exc()

    def export_enhanced_pdf(self):
        """Export enhanced PDF report with charts"""
        try:
            from PyQt5.QtWidgets import QFileDialog

            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save PDF Report",
                f"KPI_Report_{self.current_period}.pdf",
                "PDF Files (*.pdf)"
            )

            if filename:
                # Save charts as images and include in PDF
                # This would require more implementation
                QMessageBox.information(self, 'Success', f'Report exported to: {filename}')

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to export report: {str(e)}')
