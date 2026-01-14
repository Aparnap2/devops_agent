"""Chart generation utilities for incident reports.

Generates matplotlib chart code for visualizing data.
"""

import textwrap
from typing import Any


class ChartGenerator:
    """Generates matplotlib chart code."""

    def generate_timeline_chart(
        self,
        events: list[dict[str, str]],
        title: str = "Incident Timeline",
    ) -> str:
        """Generate timeline scatter chart.

        Args:
            events: List of events with time and event name
            title: Chart title

        Returns:
            Complete Python code string
        """
        events_json = [
            {"time": e["time"], "event": e["event"]}
            for e in events
        ]

        return textwrap.dedent(f'''
            """Generate incident timeline chart"""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from datetime import datetime
            import json
            import base64
            from io import BytesIO

            events = {events_json}
            title = "{title}"

            # Parse times and create y positions
            times = [datetime.fromisoformat(e["time"].replace("Z", "+00:00")) for e in events]
            labels = [e["event"] for e in events]
            y_pos = list(range(len(times)))

            plt.figure(figsize=(12, max(4, len(times) * 0.8)))
            plt.scatter(times, y_pos, s=200, c='steelblue', zorder=5)

            # Add labels
            for i, (t, label) in enumerate(zip(times, labels)):
                plt.annotate(label, (t, i), xytext=(10, 0),
                           textcoords='offset points',
                           va='center', fontsize=10)

            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.yticks([])
            plt.title(title, fontsize=14, fontweight='bold')
            plt.xlabel('Time')
            plt.grid(True, alpha=0.3)

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            output = {{
                "title": title,
                "image_base64": img_base64,
                "event_count": len(events),
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_severity_distribution(
        self,
        critical: int = 0,
        high: int = 0,
        medium: int = 0,
        low: int = 0,
        title: str = "Incidents by Severity",
    ) -> str:
        """Generate severity distribution pie chart.

        Args:
            critical: Count of critical incidents
            high: Count of high incidents
            medium: Count of medium incidents
            low: Count of low incidents
            title: Chart title

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate severity distribution chart"""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import json
            import base64
            from io import BytesIO

            data = [{critical}, {high}, {medium}, {low}]
            labels = ['Critical', 'High', 'Medium', 'Low']
            colors = ['#dc2626', '#f97316', '#eab308', '#22c55e']
            title = "{title}"

            plt.figure(figsize=(8, 8))
            wedges, texts, autotexts = plt.pie(
                data, labels=labels, colors=colors,
                autopct='%1.1f%%', startangle=90
            )
            plt.setp(autotexts, size=10, weight="bold", color="white")
            plt.title(title, fontsize=14, fontweight='bold')

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            output = {{
                "title": title,
                "image_base64": img_base64,
                "distribution": dict(zip(labels, data)),
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_risk_trend(
        self,
        dates: list[str],
        scores: list[float],
        title: str = "Risk Score Trend",
    ) -> str:
        """Generate risk trend line chart.

        Args:
            dates: List of date strings
            scores: List of risk scores (0-1)
            title: Chart title

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate risk trend chart"""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from datetime import datetime
            import json
            import base64
            from io import BytesIO

            dates = {dates}
            scores = {scores}
            title = "{title}"

            # Parse dates
            x = [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in dates]

            plt.figure(figsize=(10, 5))
            plt.plot(x, scores, marker='o', linewidth=2, color='#ef4444')
            plt.fill_between(x, scores, alpha=0.2, color='#ef4444')

            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            plt.title(title, fontsize=14, fontweight='bold')
            plt.xlabel('Date')
            plt.ylabel('Risk Score')
            plt.ylim(0, 1)
            plt.grid(True, alpha=0.3)

            # Add threshold line
            plt.axhline(y=0.4, color='orange', linestyle='--', label='Warning')
            plt.axhline(y=0.6, color='red', linestyle='--', label='Critical')
            plt.legend()

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            output = {{
                "title": title,
                "image_base64": img_base64,
                "avg_score": sum(scores) / len(scores),
            }}
            print(json.dumps(output))
        ''').strip()

    def generate_response_time_chart(
        self,
        time_periods: list[str],
        mttr_values: list[float],
        title: str = "MTTR Trend",
    ) -> str:
        """Generate MTTR trend chart.

        Args:
            time_periods: Time period labels
            mttr_values: MTTR values in minutes
            title: Chart title

        Returns:
            Complete Python code string
        """
        return textwrap.dedent(f'''
            """Generate MTTR trend chart"""
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import json
            import base64
            from io import BytesIO

            periods = {time_periods}
            mttr = {mttr_values}
            title = "{title}"

            plt.figure(figsize=(10, 5))
            bars = plt.bar(periods, mttr, color='#3b82f6', alpha=0.7)

            # Add value labels
            for bar, val in zip(bars, mttr):
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        f'{val}m', ha='center', fontsize=10)

            plt.title(title, fontsize=14, fontweight='bold')
            plt.xlabel('Time Period')
            plt.ylabel('MTTR (minutes)')
            plt.grid(True, alpha=0.3, axis='y')

            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode('utf-8')

            output = {{
                "title": title,
                "image_base64": img_base64,
                "avg_mttr": sum(mttr) / len(mttr),
            }}
            print(json.dumps(output))
        ''').strip()
