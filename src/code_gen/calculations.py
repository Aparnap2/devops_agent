"""Metrics calculation utilities.

Provides functions for calculating SRE metrics.
"""

from datetime import datetime, timezone
from typing import Any


def parse_iso_time(time_str: str) -> datetime:
    """Parse ISO format time string."""
    if "T" not in time_str:
        # Simple time format (e.g., "10:30:00")
        today = datetime.now(timezone.utc).date()
        parts = time_str.split(":")
        return datetime(
            today.year, today.month, today.day,
            int(parts[0]), int(parts[1]),
            int(parts[2]) if len(parts) > 2 else 0,
            tzinfo=timezone.utc,
        )
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))


def calculate_mttr(incidents: list[dict[str, str]]) -> float:
    """Calculate Mean Time To Resolution.

    Args:
        incidents: List of incidents with start_time and end_time

    Returns:
        MTTR in minutes
    """
    if not incidents:
        return 0.0

    total_minutes = 0.0

    for incident in incidents:
        start = parse_iso_time(incident["start_time"])
        end = parse_iso_time(incident["end_time"])
        duration = (end - start).total_seconds() / 60  # minutes
        total_minutes += duration

    return total_minutes / len(incidents)


def calculate_mtta(alerts: list[dict[str, str]]) -> float:
    """Calculate Mean Time To Acknowledge.

    Args:
        alerts: List of alerts with alert_time and detection_time

    Returns:
        MTTA in minutes
    """
    if not alerts:
        return 0.0

    total_minutes = 0.0

    for alert in alerts:
        alert_time = parse_iso_time(alert["alert_time"])
        detection_time = parse_iso_time(alert["detection_time"])
        duration = (detection_time - alert_time).total_seconds() / 60
        total_minutes += duration

    return total_minutes / len(alerts)


def calculate_availability(
    uptime_seconds: float,
    downtime_seconds: float,
) -> float:
    """Calculate availability percentage.

    Args:
        uptime_seconds: Total uptime in seconds
        downtime_seconds: Total downtime in seconds

    Returns:
        Availability as percentage (0-100)
    """
    total = uptime_seconds + downtime_seconds
    if total == 0:
        return 100.0

    return (uptime_seconds / total) * 100


def calculate_risk_score(
    severity_weight: float = 0.4,
    impact_weight: float = 0.3,
    likelihood_weight: float = 0.2,
    vulnerability_weight: float = 0.1,
) -> float:
    """Calculate weighted risk score.

    Args:
        severity_weight: Weight for severity (0-1)
        impact_weight: Weight for impact (0-1)
        likelihood_weight: Weight for likelihood (0-1)
        vulnerability_weight: Weight for vulnerability (0-1)

    Returns:
        Weighted risk score (0-1)
    """
    return (
        severity_weight +
        impact_weight +
        likelihood_weight +
        vulnerability_weight
    )


def calculate_change_failure_rate(
    deployments_total: int,
    deployments_failed: int,
) -> float:
    """Calculate change failure rate.

    Args:
        deployments_total: Total deployments
        deployments_failed: Failed deployments

    Returns:
        Failure rate as percentage
    """
    if deployments_total == 0:
        return 0.0
    return (deployments_failed / deployments_total) * 100


def calculate_error_budget(
    target_availability: float,
    actual_availability: float,
) -> float:
    """Calculate error budget remaining.

    Args:
        target_availability: Target availability percentage
        actual_availability: Actual achieved availability

    Returns:
        Error budget remaining as percentage
    """
    error_budget = target_availability - actual_availability
    return max(0.0, error_budget)


def calculate_throughput(
    total_requests: int,
    time_period_hours: float,
) -> float:
    """Calculate requests per hour.

    Args:
        total_requests: Total number of requests
        time_period_hours: Time period in hours

    Returns:
        Requests per hour
    """
    if time_period_hours == 0:
        return 0.0
    return total_requests / time_period_hours


def calculate_latency_percentile(
    latencies: list[float],
    percentile: float = 95,
) -> float:
    """Calculate latency at specified percentile.

    Args:
        latencies: List of latency measurements
        percentile: Percentile to calculate (0-100)

    Returns:
        Latency at percentile
    """
    if not latencies:
        return 0.0

    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * percentile / 100)
    return sorted_latencies[min(index, len(sorted_latencies) - 1)]


def calculate_sli_score(
    successful_requests: int,
    total_requests: int,
) -> float:
    """Calculate SLI (Service Level Indicator) score.

    Args:
        successful_requests: Number of successful requests
        total_requests: Total number of requests

    Returns:
        SLI score as percentage
    """
    if total_requests == 0:
        return 100.0
    return (successful_requests / total_requests) * 100


def calculate_incident_frequency(
    incident_count: int,
    time_period_days: int,
) -> float:
    """Calculate incidents per day.

    Args:
        incident_count: Number of incidents
        time_period_days: Time period in days

    Returns:
        Incidents per day
    """
    if time_period_days == 0:
        return 0.0
    return incident_count / time_period_days
