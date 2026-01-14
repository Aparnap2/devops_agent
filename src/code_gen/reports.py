"""Report generation utilities.

Generates code for rendering report sections.
"""

import textwrap
from typing import Any


class ReportGenerator:
    """Generates report rendering code."""

    def generate_summary_stats(
        self,
        metric: str,
        period: str = "last_7_days",
    ) -> str:
        """Generate summary statistics code.

        Args:
            metric: Metric name to summarize
            period: Time period

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate {metric} summary for {period}"""
            import json

            # Metrics data (would come from database)
            data = {{
                "metric": "{metric}",
                "period": "{period}",
                "current": 0,
                "previous": 0,
                "change_percent": 0.0,
            }}

            # Calculate statistics
            summary = {{
                "total": data["current"],
                "average": data["current"] / 7 if data["current"] > 0 else 0,
                "max": 0,
                "min": 0,
                "change_from_previous": data["change_percent"],
            }}

            output = {{
                "metric": "{metric}",
                "period": "{period}",
                "summary": summary,
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_comparison(
        self,
        current_value: float,
        previous_value: float,
        metric: str = "value",
    ) -> str:
        """Generate comparison code.

        Args:
            current_value: Current period value
            previous_value: Previous period value
            metric: Metric name

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate {metric} comparison"""
            import json

            current = {current_value}
            previous = {previous_value}
            metric = "{metric}"

            # Calculate change
            if previous > 0:
                change_percent = ((current - previous) / previous) * 100
            else:
                change_percent = 0.0

            # Determine trend
            if change_percent > 0:
                trend = "increase"
            elif change_percent < 0:
                trend = "decrease"
            else:
                trend = "no change"

            output = {{
                "metric": metric,
                "current": current,
                "previous": previous,
                "change_percent": round(change_percent, 2),
                "trend": trend,
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_table(
        self,
        data: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        """Generate table rendering code.

        Args:
            data: List of row data
            columns: Column names

        Returns:
            Complete Python code string
        """
        data_json = str(data).replace("'", '"')

        return textwrap.dedent(f'''
            """Generate data table"""
            import json

            data = {data_json}
            columns = {columns}

            # Build table
            table = {{
                "headers": columns,
                "rows": data,
                "row_count": len(data),
                "column_count": len(columns),
            }}

            # Calculate column totals for numeric columns
            totals = {{}}
            for col in columns:
                if data and isinstance(data[0].get(col), (int, float)):
                    totals[col] = sum(row.get(col, 0) for row in data)

            output = {{
                "table": table,
                "totals": totals,
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_kpi_section(
        self,
        kpis: list[dict[str, Any]],
    ) -> str:
        """Generate KPI section code.

        Args:
            kpis: List of KPI definitions

        Returns:
            Complete Python code string
        """
        kpis_json = str(kpis).replace("'", '"')

        return textwrap.dedent(f'''
            """Generate KPI dashboard section"""
            import json

            kpis = {kpis_json}

            # Calculate status for each KPI
            results = []
            for kpi in kpis:
                actual = kpi.get("actual", 0)
                target = kpi.get("target", 100)
                higher_is_better = kpi.get("higher_is_better", True)

                if higher_is_better:
                    status = "good" if actual >= target else "warning"
                    achievement = (actual / target * 100) if target > 0 else 0
                else:
                    status = "good" if actual <= target else "warning"
                    achievement = (target / actual * 100) if actual > 0 else 0

                results.append({{
                    "name": kpi["name"],
                    "actual": actual,
                    "target": target,
                    "status": status,
                    "achievement_percent": round(achievement, 1),
                }})

            output = {{
                "kpis": results,
                "all_good": all(r["status"] == "good" for r in results),
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_timeline_summary(
        self,
        phases: list[str],
        durations: list[float],
    ) -> str:
        """Generate incident timeline summary.

        Args:
            phases: Phase names
            durations: Duration in minutes for each phase

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate timeline summary"""
            import json

            phases = {phases}
            durations = {durations}

            # Build timeline data
            timeline = []
            cumulative = 0
            for phase, duration in zip(phases, durations):
                timeline.append({{
                    "phase": phase,
                    "duration_minutes": duration,
                    "cumulative_minutes": round(cumulative, 2),
                }})
                cumulative += duration

            total_duration = sum(durations)
            bottleneck = phases[durations.index(max(durations))] if durations else None

            output = {{
                "timeline": timeline,
                "total_duration_minutes": total_duration,
                "bottleneck_phase": bottleneck,
                "phase_count": len(phases),
            }}
            print(json.dumps(output))
        ''').strip()
