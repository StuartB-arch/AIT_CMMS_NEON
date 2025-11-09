#!/usr/bin/env python3
"""
Executive Summary Report Generator
Creates comprehensive, presentation-ready reports with charts and visual insights
Perfect for corporate presentations and stakeholder meetings
"""

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, PageBreak, FrameBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from PIL import Image
import io
import os
import tempfile

# Set professional style
sns.set_style("whitegrid")
sns.set_palette("husl")
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = '#f8f9fa'


class ExecutiveReportGenerator:
    """Generate executive-level PDF reports with charts and insights"""

    def __init__(self, db_connection):
        """Initialize with database connection"""
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
        self.temp_chart_files = []

    def generate_executive_summary(self, output_filename=None, period_months=3):
        """Generate comprehensive executive summary report"""

        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"AIT_CMMS_Executive_Summary_{timestamp}.pdf"

        # Create PDF document
        doc = SimpleDocTemplate(
            output_filename,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )

        story = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=28,
            textColor=rl_colors.HexColor('#2B2D42'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=18,
            textColor=rl_colors.HexColor('#2E86AB'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        )

        subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=styles['Heading3'],
            fontSize=14,
            textColor=rl_colors.HexColor('#2B2D42'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )

        # Title Page
        story.append(Spacer(1, 1.5*inch))
        story.append(Paragraph("AIT CMMS", title_style))
        story.append(Paragraph("EXECUTIVE SUMMARY REPORT", title_style))
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph(
            f"Maintenance Management Performance",
            ParagraphStyle('subtitle', parent=styles['Normal'], fontSize=16,
                          alignment=TA_CENTER, textColor=rl_colors.HexColor('#666666'))
        ))
        story.append(Spacer(1, 0.2*inch))
        story.append(Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y')}",
            ParagraphStyle('date', parent=styles['Normal'], fontSize=12,
                          alignment=TA_CENTER, textColor=rl_colors.HexColor('#999999'))
        ))
        story.append(PageBreak())

        # Executive Summary Section
        story.append(Paragraph("EXECUTIVE SUMMARY", heading_style))
        story.append(Spacer(1, 0.2*inch))

        summary_text = self._generate_executive_summary_text(period_months)
        for paragraph in summary_text:
            story.append(Paragraph(paragraph, styles['Normal']))
            story.append(Spacer(1, 0.1*inch))

        story.append(Spacer(1, 0.3*inch))

        # Key Metrics Dashboard
        story.append(Paragraph("KEY PERFORMANCE INDICATORS", heading_style))
        story.append(Spacer(1, 0.1*inch))

        kpi_table = self._create_kpi_summary_table()
        if kpi_table:
            story.append(kpi_table)
            story.append(Spacer(1, 0.3*inch))

        story.append(PageBreak())

        # Equipment Performance Section
        story.append(Paragraph("EQUIPMENT PERFORMANCE ANALYSIS", heading_style))
        story.append(Spacer(1, 0.2*inch))

        # Equipment status chart
        equipment_chart = self._create_equipment_status_chart()
        if equipment_chart:
            story.append(RLImage(equipment_chart, width=6*inch, height=4*inch))
            story.append(Spacer(1, 0.2*inch))

        equipment_summary = self._get_equipment_summary()
        story.append(Paragraph(equipment_summary, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))

        story.append(PageBreak())

        # PM Performance Section
        story.append(Paragraph("PREVENTIVE MAINTENANCE PERFORMANCE", heading_style))
        story.append(Spacer(1, 0.2*inch))

        # PM completion trend chart
        pm_trend_chart = self._create_pm_trend_chart(period_months)
        if pm_trend_chart:
            story.append(RLImage(pm_trend_chart, width=6.5*inch, height=4*inch))
            story.append(Spacer(1, 0.2*inch))

        pm_summary = self._get_pm_performance_summary(period_months)
        story.append(Paragraph(pm_summary, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))

        story.append(PageBreak())

        # Work Order Management Section
        story.append(Paragraph("CORRECTIVE MAINTENANCE OVERVIEW", heading_style))
        story.append(Spacer(1, 0.2*inch))

        # CM priority distribution chart
        cm_chart = self._create_cm_distribution_chart()
        if cm_chart:
            story.append(RLImage(cm_chart, width=6.5*inch, height=4*inch))
            story.append(Spacer(1, 0.2*inch))

        cm_summary = self._get_cm_summary()
        story.append(Paragraph(cm_summary, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))

        story.append(PageBreak())

        # Technician Performance Section
        story.append(Paragraph("TECHNICIAN PERFORMANCE", heading_style))
        story.append(Spacer(1, 0.2*inch))

        # Technician workload chart
        tech_chart = self._create_technician_performance_chart()
        if tech_chart:
            story.append(RLImage(tech_chart, width=6.5*inch, height=4*inch))
            story.append(Spacer(1, 0.2*inch))

        tech_summary = self._get_technician_summary()
        story.append(Paragraph(tech_summary, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))

        story.append(PageBreak())

        # Recommendations Section
        story.append(Paragraph("RECOMMENDATIONS & ACTION ITEMS", heading_style))
        story.append(Spacer(1, 0.2*inch))

        recommendations = self._generate_recommendations()
        for rec in recommendations:
            story.append(Paragraph(f"• {rec}", styles['Normal']))
            story.append(Spacer(1, 0.1*inch))

        # Build PDF
        doc.build(story)

        # Cleanup temp files
        self._cleanup_temp_files()

        return output_filename

    def _generate_executive_summary_text(self, period_months):
        """Generate executive summary text"""
        try:
            cursor = self.conn.cursor()

            # Get key metrics
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            total_equipment = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(*) FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '%s months'
            ''', (period_months,))
            total_pms = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
            open_cms = cursor.fetchone()[0]

            cursor.execute('''
                SELECT
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END)::float /
                    NULLIF(COUNT(*)::float, 0) * 100
                FROM weekly_pm_schedules
                WHERE week_start_date >= CURRENT_DATE - INTERVAL '%s months'
            ''', (period_months,))
            result = cursor.fetchone()
            completion_rate = result[0] if result[0] else 0

            paragraphs = [
                f"<b>Overview:</b> This report provides a comprehensive analysis of the AIT Computerized Maintenance Management System (CMMS) performance over the past {period_months} months, demonstrating enterprise-level maintenance operations and key achievements.",

                f"<b>Equipment Portfolio:</b> The facility currently maintains {total_equipment:,} active equipment assets, ensuring operational continuity across all production areas.",

                f"<b>Preventive Maintenance:</b> {total_pms:,} preventive maintenance tasks have been successfully completed in the reporting period, with an overall PM completion rate of {completion_rate:.1f}%, demonstrating strong adherence to maintenance schedules.",

                f"<b>Work Order Management:</b> Currently tracking {open_cms:,} open corrective maintenance work orders, with continuous monitoring and prioritization to minimize equipment downtime.",

                "<b>Performance Excellence:</b> The CMMS system demonstrates SAP-level capabilities with comprehensive tracking, automated scheduling, predictive analytics, and real-time reporting features."
            ]

            return paragraphs

        except Exception as e:
            print(f"Error generating summary text: {e}")
            return ["Error generating summary."]

    def _create_kpi_summary_table(self):
        """Create KPI summary table"""
        try:
            cursor = self.conn.cursor()

            # Get key metrics
            metrics = []

            # PM Completion Rate
            cursor.execute('''
                SELECT
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END)::float /
                    NULLIF(COUNT(*)::float, 0) * 100
                FROM weekly_pm_schedules
                WHERE week_start_date >= CURRENT_DATE - INTERVAL '3 months'
            ''')
            pm_rate = cursor.fetchone()[0] or 0
            metrics.append(["PM Completion Rate", f"{pm_rate:.1f}%", "✓" if pm_rate >= 85 else "⚠"])

            # Equipment Availability
            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM equipment")
            total = cursor.fetchone()[0]
            availability = (active / total * 100) if total > 0 else 0
            metrics.append(["Equipment Availability", f"{availability:.1f}%", "✓" if availability >= 95 else "⚠"])

            # Response Time
            cursor.execute('''
                SELECT AVG(labor_hours + labor_minutes/60.0)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '3 months'
            ''')
            avg_hours = cursor.fetchone()[0] or 0
            metrics.append(["Avg Labor Hours/PM", f"{avg_hours:.1f}h", "✓" if avg_hours <= 4 else "⚠"])

            # Open Work Orders
            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
            open_wo = cursor.fetchone()[0]
            metrics.append(["Open Work Orders", str(open_wo), "✓" if open_wo < 50 else "⚠"])

            # Inventory Value
            cursor.execute("SELECT SUM(quantity_in_stock * unit_price) FROM mro_stock WHERE status = 'Active'")
            inv_value = cursor.fetchone()[0] or 0
            metrics.append(["MRO Inventory Value", f"${inv_value:,.0f}", "📊"])

            # Create table
            data = [["Metric", "Value", "Status"]] + metrics

            table = Table(data, colWidths=[3*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#2E86AB')),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), rl_colors.HexColor('#f8f9fa')),
                ('GRID', (0, 0), (-1, -1), 1, rl_colors.HexColor('#dee2e6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor('#f8f9fa')])
            ]))

            return table

        except Exception as e:
            print(f"Error creating KPI table: {e}")
            return None

    def _create_equipment_status_chart(self):
        """Create equipment status pie chart"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT status, COUNT(*) FROM equipment
                GROUP BY status ORDER BY COUNT(*) DESC
            ''')
            data = cursor.fetchall()

            if not data:
                return None

            labels = [row[0] for row in data]
            sizes = [row[1] for row in data]

            fig, ax = plt.subplots(figsize=(8, 6))
            colors_list = [self.color_scheme['success'], self.color_scheme['warning'],
                          self.color_scheme['danger'], self.color_scheme['info']]

            wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                               colors=colors_list, startangle=90,
                                               textprops={'fontsize': 12})

            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
                autotext.set_fontsize(13)

            ax.set_title('Equipment Status Distribution', fontsize=16, fontweight='bold', pad=20)

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            plt.savefig(temp_file.name, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            self.temp_chart_files.append(temp_file.name)
            return temp_file.name

        except Exception as e:
            print(f"Error creating equipment chart: {e}")
            return None

    def _create_pm_trend_chart(self, months):
        """Create PM completion trend chart"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT
                    DATE_TRUNC('month', completion_date::date) as month,
                    COUNT(*) as completions
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '%s months'
                GROUP BY DATE_TRUNC('month', completion_date::date)
                ORDER BY month
            ''', (months,))

            data = cursor.fetchall()

            if not data:
                return None

            months_list = [row[0].strftime('%b %Y') for row in data]
            completions = [row[1] for row in data]

            fig, ax = plt.subplots(figsize=(10, 6))

            ax.plot(months_list, completions, marker='o', linewidth=3,
                   markersize=10, color=self.color_scheme['primary'])
            ax.fill_between(range(len(months_list)), completions, alpha=0.3,
                           color=self.color_scheme['primary'])

            ax.set_title('PM Completion Trend', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('Month', fontsize=12, fontweight='bold')
            ax.set_ylabel('Completions', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=45, ha='right')

            # Add value labels
            for i, v in enumerate(completions):
                ax.text(i, v, str(v), ha='center', va='bottom', fontweight='bold', fontsize=10)

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            plt.savefig(temp_file.name, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            self.temp_chart_files.append(temp_file.name)
            return temp_file.name

        except Exception as e:
            print(f"Error creating PM trend chart: {e}")
            return None

    def _create_cm_distribution_chart(self):
        """Create CM priority distribution chart"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT priority, status, COUNT(*) FROM corrective_maintenance
                GROUP BY priority, status
                ORDER BY
                    CASE priority
                        WHEN 'Critical' THEN 1
                        WHEN 'High' THEN 2
                        WHEN 'Medium' THEN 3
                        WHEN 'Low' THEN 4
                    END
            ''')

            data = cursor.fetchall()

            if not data:
                return None

            df = pd.DataFrame(data, columns=['Priority', 'Status', 'Count'])
            pivot_df = df.pivot(index='Priority', columns='Status', values='Count').fillna(0)

            fig, ax = plt.subplots(figsize=(10, 6))

            pivot_df.plot(kind='bar', stacked=True, ax=ax,
                         color=[self.color_scheme['warning'], self.color_scheme['success']],
                         width=0.7)

            ax.set_title('Work Orders by Priority & Status', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('Priority', fontsize=12, fontweight='bold')
            ax.set_ylabel('Count', fontsize=12, fontweight='bold')
            ax.legend(title='Status', loc='upper right', framealpha=0.9)
            ax.grid(axis='y', alpha=0.3)
            plt.xticks(rotation=0)

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            plt.savefig(temp_file.name, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            self.temp_chart_files.append(temp_file.name)
            return temp_file.name

        except Exception as e:
            print(f"Error creating CM distribution chart: {e}")
            return None

    def _create_technician_performance_chart(self):
        """Create technician performance bar chart"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT
                    technician_name,
                    COUNT(*) as total_pms
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '3 months'
                GROUP BY technician_name
                ORDER BY total_pms DESC
                LIMIT 10
            ''')

            data = cursor.fetchall()

            if not data:
                return None

            technicians = [row[0] for row in data]
            completions = [row[1] for row in data]

            fig, ax = plt.subplots(figsize=(10, 6))

            bars = ax.barh(technicians, completions, color=self.color_scheme['primary'])

            # Add value labels
            for i, (bar, value) in enumerate(zip(bars, completions)):
                ax.text(value, i, f' {int(value)}', va='center', fontweight='bold', fontsize=11)

            ax.set_title('Technician Performance (Last 3 Months)', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('PM Completions', fontsize=12, fontweight='bold')
            ax.set_ylabel('Technician', fontsize=12, fontweight='bold')
            ax.grid(axis='x', alpha=0.3)

            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            plt.savefig(temp_file.name, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            self.temp_chart_files.append(temp_file.name)
            return temp_file.name

        except Exception as e:
            print(f"Error creating technician chart: {e}")
            return None

    def _get_equipment_summary(self):
        """Get equipment summary text"""
        try:
            cursor = self.conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM equipment WHERE status = 'Active'")
            active = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM equipment WHERE monthly_pm = 1")
            monthly = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM equipment WHERE annual_pm = 1")
            annual = cursor.fetchone()[0]

            return f"<b>Equipment Status:</b> Currently managing {active:,} active equipment assets. {monthly:,} assets require monthly preventive maintenance, and {annual:,} assets are on annual maintenance schedules. All equipment is tracked with unique BFM identifiers ensuring complete traceability and maintenance history."

        except Exception as e:
            return "Equipment summary unavailable."

    def _get_pm_performance_summary(self, months):
        """Get PM performance summary"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT COUNT(*) FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '%s months'
            ''', (months,))
            total = cursor.fetchone()[0]

            cursor.execute('''
                SELECT AVG(labor_hours + labor_minutes/60.0)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '%s months'
            ''', (months,))
            avg_time = cursor.fetchone()[0] or 0

            return f"<b>PM Performance:</b> {total:,} preventive maintenance tasks completed in the past {months} months with an average labor time of {avg_time:.1f} hours per PM. Consistent PM execution ensures equipment reliability and minimizes unplanned downtime. The system features automated PM scheduling with technician workload balancing."

        except Exception as e:
            return "PM summary unavailable."

    def _get_cm_summary(self):
        """Get CM summary text"""
        try:
            cursor = self.conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open'")
            open_cm = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Completed'")
            closed = cursor.fetchone()[0]

            cursor.execute('''
                SELECT priority, COUNT(*) FROM corrective_maintenance
                WHERE status = 'Open'
                GROUP BY priority
                ORDER BY CASE priority
                    WHEN 'Critical' THEN 1
                    WHEN 'High' THEN 2
                    WHEN 'Medium' THEN 3
                    WHEN 'Low' THEN 4
                END
                LIMIT 1
            ''')
            top_priority = cursor.fetchone()
            top_text = f" {top_priority[1]} {top_priority[0]} priority items" if top_priority else ""

            return f"<b>Work Order Management:</b> {open_cm:,} open corrective maintenance work orders currently tracked, with {closed:,} successfully completed work orders. Priority-based workflow ensures critical issues are addressed immediately.{top_text} require attention. Full integration with parts inventory enables efficient maintenance execution."

        except Exception as e:
            return "CM summary unavailable."

    def _get_technician_summary(self):
        """Get technician summary text"""
        try:
            cursor = self.conn.cursor()

            cursor.execute('''
                SELECT COUNT(DISTINCT technician_name)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '3 months'
            ''')
            tech_count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT technician_name, COUNT(*)
                FROM pm_completions
                WHERE completion_date >= CURRENT_DATE - INTERVAL '3 months'
                GROUP BY technician_name
                ORDER BY COUNT(*) DESC
                LIMIT 1
            ''')
            top_tech = cursor.fetchone()
            top_text = f" {top_tech[0]} leads with {top_tech[1]} completions." if top_tech else ""

            return f"<b>Workforce Performance:</b> {tech_count} active technicians contributing to maintenance operations over the past quarter.{top_text} The system provides workload balancing, performance tracking, and skill-based PM assignment to optimize workforce utilization and ensure quality maintenance execution."

        except Exception as e:
            return "Technician summary unavailable."

    def _generate_recommendations(self):
        """Generate actionable recommendations based on data"""
        recommendations = []

        try:
            cursor = self.conn.cursor()

            # Check low PM completion rate
            cursor.execute('''
                SELECT
                    COUNT(CASE WHEN status = 'Completed' THEN 1 END)::float /
                    NULLIF(COUNT(*)::float, 0) * 100
                FROM weekly_pm_schedules
                WHERE week_start_date >= CURRENT_DATE - INTERVAL '1 month'
            ''')
            pm_rate = cursor.fetchone()[0] or 0

            if pm_rate < 85:
                recommendations.append("<b>PM Completion:</b> Current PM completion rate is below target (85%). Recommend reviewing technician schedules and resource allocation.")

            # Check open work orders
            cursor.execute("SELECT COUNT(*) FROM corrective_maintenance WHERE status = 'Open' AND priority IN ('Critical', 'High')")
            high_priority = cursor.fetchone()[0]

            if high_priority > 10:
                recommendations.append(f"<b>Critical Work Orders:</b> {high_priority} high-priority work orders require immediate attention. Recommend prioritizing critical equipment maintenance.")

            # Check inventory
            cursor.execute("SELECT COUNT(*) FROM mro_stock WHERE status = 'Active' AND quantity_in_stock <= minimum_stock")
            low_stock = cursor.fetchone()[0]

            if low_stock > 0:
                recommendations.append(f"<b>Inventory Management:</b> {low_stock} parts are at or below minimum stock levels. Recommend inventory replenishment to prevent maintenance delays.")

            # General recommendations
            recommendations.append("<b>Continuous Improvement:</b> Implement predictive maintenance analytics to transition from reactive to proactive maintenance strategies.")
            recommendations.append("<b>Training:</b> Continue workforce development programs to ensure technicians maintain expertise in latest equipment and maintenance techniques.")
            recommendations.append("<b>Technology:</b> Leverage CMMS mobile capabilities for real-time field updates and enhanced maintenance documentation.")

        except Exception as e:
            print(f"Error generating recommendations: {e}")
            recommendations.append("Continue monitoring key performance indicators and maintaining high equipment reliability standards.")

        return recommendations

    def _cleanup_temp_files(self):
        """Clean up temporary chart files"""
        for filepath in self.temp_chart_files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Error removing temp file {filepath}: {e}")

        self.temp_chart_files = []


def generate_executive_report(db_connection, output_file=None):
    """Generate executive report - convenience function"""
    generator = ExecutiveReportGenerator(db_connection)
    return generator.generate_executive_summary(output_file)
