"""Demo application for SRE Agent testing.

A simple Flask app with health endpoints for chaos testing.
"""

import logging
import os
import random
import time
from datetime import datetime

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simulate stateful behavior
request_count = 0
start_time = datetime.utcnow()


@app.route("/health")
def health():
    """Liveness probe endpoint."""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()}), 200


@app.route("/ready")
def ready():
    """Readiness probe endpoint."""
    # Simulate startup delay
    uptime = (datetime.utcnow() - start_time).seconds
    if uptime < 5:
        return jsonify({"status": "not_ready", "uptime": uptime}), 503

    return jsonify({"status": "ready", "uptime": uptime}), 200


@app.route("/")
def index():
    """Main endpoint."""
    global request_count
    request_count += 1
    return jsonify({
        "message": "SRE Agent Demo App",
        "request_count": request_count,
        "version": os.getenv("APP_VERSION", "1.0.0"),
    })


@app.route("/api/users")
def users():
    """Simulate API endpoint."""
    # Simulate variable latency
    latency = random.uniform(0.01, 0.1)
    time.sleep(latency)

    return jsonify({
        "users": [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ],
        "latency_ms": int(latency * 1000),
    })


@app.route("/api/heavy")
def heavy():
    """Simulate memory-intensive endpoint for OOM testing."""
    size_mb = request.args.get("size", 10, type=int)

    # Cap at 100MB to prevent accidental issues
    size_mb = min(size_mb, 100)

    # Allocate memory
    data = bytearray(size_mb * 1024 * 1024)
    logger.info(f"Allocated {size_mb}MB of memory")

    return jsonify({"allocated_mb": size_mb})


@app.route("/api/error")
def error():
    """Simulate error endpoint for testing."""
    error_rate = request.args.get("rate", 50, type=int)

    if random.randint(1, 100) <= error_rate:
        logger.error("Simulated error occurred")
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({"status": "ok"})


@app.route("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    metrics = f"""
# HELP demo_requests_total Total number of requests
# TYPE demo_requests_total counter
demo_requests_total {request_count}

# HELP demo_uptime_seconds Uptime in seconds
# TYPE demo_uptime_seconds gauge
demo_uptime_seconds {(datetime.utcnow() - start_time).seconds}

# HELP demo_app_info Application info
# TYPE demo_app_info gauge
demo_app_info{{version="{os.getenv('APP_VERSION', '1.0.0')}"}} 1
"""
    return metrics, 200, {"Content-Type": "text/plain"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
