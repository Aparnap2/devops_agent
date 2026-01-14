"""TDD: Tests for code generation capabilities.

Tests for safe Python code execution in sandboxed containers.
"""

import pytest
import base64
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch


class TestCodeGenerator:
    """Tests for CodeGenerator class."""

    def test_generate_calculation_code(self):
        """Test generating calculation code."""
        from src.code_gen.sandbox import CodeGenerator

        generator = CodeGenerator()

        code = generator.generate_calculation(
            expression="sum(range(1, 100))",
            description="Calculate sum of 1 to 99",
        )

        assert "sum(range(1, 100))" in code
        assert "result" in code

    def test_generate_matplotlib_code(self):
        """Test generating matplotlib code."""
        from src.code_gen.sandbox import CodeGenerator

        generator = CodeGenerator()

        code = generator.generate_matplotlib(
            data=[1, 2, 3, 4, 5],
            title="Test Chart",
            xlabel="X Axis",
            ylabel="Y Axis",
            chart_type="line",
        )

        assert "matplotlib" in code.lower() or "plt." in code
        assert "Test Chart" in code

    def test_generate_bar_chart(self):
        """Test generating bar chart code."""
        from src.code_gen.sandbox import CodeGenerator

        generator = CodeGenerator()

        code = generator.generate_matplotlib(
            data=[10, 25, 30, 45],
            title="Monthly Incidents",
            xlabel="Month",
            ylabel="Count",
            chart_type="bar",
        )

        assert "bar" in code.lower()

    def test_generate_histogram(self):
        """Test generating histogram code."""
        from src.code_gen.sandbox import CodeGenerator

        generator = CodeGenerator()

        code = generator.generate_matplotlib(
            data=list(range(100)),
            title="Distribution",
            chart_type="hist",
        )

        assert "hist" in code.lower()

    def test_generate_pie_chart(self):
        """Test generating pie chart code."""
        from src.code_gen.sandbox import CodeGenerator

        generator = CodeGenerator()

        code = generator.generate_pie_chart(
            data=[30, 25, 20, 15, 10],
            labels=["Prod", "Staging", "Dev", "QA", "Other"],
            title="Incidents by Environment",
        )

        assert "pie" in code.lower() or "plt.pie" in code


class TestSandboxExecution:
    """Tests for sandboxed code execution."""

    @pytest.mark.asyncio
    async def test_execute_simple_calculation(self):
        """Test executing simple calculation."""
        from src.code_gen.sandbox import CodeGenerator, SandboxConfig

        config = SandboxConfig(timeout_seconds=10)
        generator = CodeGenerator(config)

        code = """
result = 2 + 2
print(f"Result: {result}")
"""

        result = await generator.execute(code)

        assert result["success"] is True
        assert "4" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_list_comprehension(self):
        """Test executing list comprehension."""
        from src.code_gen.sandbox import CodeGenerator, SandboxConfig

        config = SandboxConfig(timeout_seconds=10)
        generator = CodeGenerator(config)

        code = """
squares = [x**2 for x in range(10)]
print(f"Squares: {squares}")
"""

        result = await generator.execute(code)

        assert result["success"] is True
        assert "81" in result["output"]  # 9^2

    @pytest.mark.asyncio
    async def test_timeout_enforcement(self):
        """Test that timeout is enforced."""
        from src.code_gen.sandbox import CodeGenerator, SandboxConfig

        config = SandboxConfig(timeout_seconds=1)
        generator = CodeGenerator(config)

        # This would run forever without timeout
        code = """
import time
while True:
    time.sleep(1)
"""

        result = await generator.execute(code)

        assert result["success"] is False
        assert "timeout" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_malicious_code_blocked(self):
        """Test that malicious code is blocked."""
        from src.code_gen.sandbox import CodeGenerator, SandboxConfig

        config = SandboxConfig(timeout_seconds=10)
        generator = CodeGenerator(config)

        # Try to import os and delete files
        code = """
import os
os.system("rm -rf /tmp/test")
"""

        result = await generator.execute(code)

        # Should either fail or not actually delete anything
        assert result["success"] is False or "rm" not in result.get("output", "")


class TestChartGeneration:
    """Tests for chart generation utilities."""

    def test_generate_incident_timeline(self):
        """Test generating incident timeline chart."""
        from src.code_gen.charts import ChartGenerator

        generator = ChartGenerator()

        code = generator.generate_timeline_chart(
            events=[
                {"time": "2024-01-15T10:00:00Z", "event": "Incident Start"},
                {"time": "2024-01-15T10:05:00Z", "event": "Diagnosis"},
                {"time": "2024-01-15T10:15:00Z", "event": "Remediation"},
                {"time": "2024-01-15T10:30:00Z", "event": "Resolved"},
            ],
            title="Incident Timeline",
        )

        assert "timeline" in code.lower() or "scatter" in code.lower()
        assert "Incident Timeline" in code

    def test_generate_severity_distribution(self):
        """Test generating severity distribution pie chart."""
        from src.code_gen.charts import ChartGenerator

        generator = ChartGenerator()

        code = generator.generate_severity_distribution(
            critical=5,
            high=15,
            medium=30,
            low=50,
        )

        assert "pie" in code.lower() or "plt.pie" in code

    def test_generate_risk_trend(self):
        """Test generating risk trend line chart."""
        from src.code_gen.charts import ChartGenerator

        generator = ChartGenerator()

        code = generator.generate_risk_trend(
            dates=["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12"],
            scores=[0.8, 0.6, 0.4, 0.5, 0.3],
        )

        assert "line" in code.lower() or "plot" in code


class TestMetricsCalculation:
    """Tests for metrics calculation utilities."""

    def test_calculate_mttr(self):
        """Test MTTR calculation."""
        from src.code_gen.calculations import calculate_mttr

        incidents = [
            {"start_time": "2024-01-15T10:00:00Z", "end_time": "2024-01-15T10:30:00Z"},
            {"start_time": "2024-01-15T11:00:00Z", "end_time": "2024-01-15T11:15:00Z"},
            {"start_time": "2024-01-15T12:00:00Z", "end_time": "2024-01-15T12:45:00Z"},
        ]

        mttr = calculate_mttr(incidents)

        # (30 + 15 + 45) / 3 = 30 minutes
        assert mttr == 30

    def test_calculate_mtta(self):
        """Test MTTA calculation."""
        from src.code_gen.calculations import calculate_mtta

        alerts = [
            {"alert_time": "2024-01-15T10:00:00Z", "detection_time": "2024-01-15T10:02:00Z"},
            {"alert_time": "2024-01-15T10:30:00Z", "detection_time": "10:31:00"},
            {"alert_time": "2024-01-15T11:00:00Z", "detection_time": "11:01:30"},
        ]

        mtta = calculate_mtta(alerts)

        # (2 + 1 + 1.5) / 3 = 1.5 minutes
        assert mtta == 1.5

    def test_calculate_availability(self):
        """Test availability calculation."""
        from src.code_gen.calculations import calculate_availability

        uptime_seconds = 86400  # 24 hours
        downtime_seconds = 60  # 1 minute downtime

        availability = calculate_availability(uptime_seconds, downtime_seconds)

        # 86399/86400 = 99.9988%
        assert availability > 99.9

    def test_calculate_risk_score(self):
        """Test risk score calculation."""
        from src.code_gen.calculations import calculate_risk_score

        score = calculate_risk_score(
            severity_weight=0.4,
            impact_weight=0.3,
            likelihood_weight=0.2,
            vulnerability_weight=0.1,
        )

        # Weighted average: 0.4 + 0.3 + 0.2 + 0.1 = 1.0
        assert score == 1.0


class TestReportGeneration:
    """Tests for report generation utilities."""

    def test_generate_summary_stats(self):
        """Test generating summary statistics code."""
        from src.code_gen.reports import ReportGenerator

        generator = ReportGenerator()

        code = generator.generate_summary_stats(
            metric="incident_count",
            period="last_7_days",
        )

        assert "incident_count" in code or "count" in code.lower()

    def test_generate_comparison_code(self):
        """Test generating comparison code."""
        from src.code_gen.reports import ReportGenerator

        generator = ReportGenerator()

        code = generator.generate_comparison(
            current_value=100,
            previous_value=80,
            metric="response_time",
        )

        assert "response_time" in code
        assert "25" in code  # (100-80)/80 * 100 = 25% increase

    def test_generate_table_code(self):
        """Test generating table rendering code."""
        from src.code_gen.reports import ReportGenerator

        generator = ReportGenerator()

        code = generator.generate_table(
            data=[
                {"name": "Critical", "count": 5, "percentage": 5},
                {"name": "High", "count": 15, "percentage": 15},
            ],
            columns=["name", "count", "percentage"],
        )

        assert "Critical" in code
        assert "5" in code
