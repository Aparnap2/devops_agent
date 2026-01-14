# SRE Agent Makefile
# One-command setup for development and demo

.PHONY: help setup setup-kind setup-chaos setup-monitoring build-demo deploy-demo \
        install test test-unit test-integration run run-ui clean demo demo-oom demo-network

# Default target
help:
	@echo "SRE Agent Development Commands"
	@echo "================================"
	@echo ""
	@echo "Setup:"
	@echo "  make setup           - Full environment setup (Kind + deps + monitoring)"
	@echo "  make setup-kind      - Create Kind cluster only"
	@echo "  make setup-chaos     - Install Chaos Mesh"
	@echo "  make setup-monitoring - Deploy Prometheus + Alertmanager"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  make build-demo      - Build demo app Docker image"
	@echo "  make deploy-demo     - Deploy demo app to cluster"
	@echo ""
	@echo "Development:"
	@echo "  make install         - Install Python dependencies with uv"
	@echo "  make test            - Run all tests"
	@echo "  make test-unit       - Run unit tests only"
	@echo "  make test-integration - Run integration tests"
	@echo "  make run             - Run the agent API server"
	@echo "  make run-ui          - Run Streamlit UI"
	@echo ""
	@echo "Demo:"
	@echo "  make demo            - Run full demo with OOM scenario"
	@echo "  make demo-oom        - Trigger OOM chaos experiment"
	@echo "  make demo-network    - Trigger network delay experiment"
	@echo "  make demo-pod-kill   - Trigger pod kill experiment"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean           - Delete Kind cluster and cleanup"

# =============================================================================
# SETUP
# =============================================================================

setup: setup-kind install setup-monitoring setup-chaos build-demo deploy-demo
	@echo "✓ Full setup complete!"
	@echo ""
	@echo "Access points:"
	@echo "  Prometheus:    http://localhost:9090"
	@echo "  Alertmanager:  http://localhost:9093"
	@echo "  Demo App:      http://localhost:8080"
	@echo "  Chaos Mesh:    http://localhost:2333"
	@echo ""
	@echo "Run 'make run-ui' to start the Control Tower"

setup-kind:
	@echo "Creating Kind cluster..."
	@if kind get clusters | grep -q sre-agent; then \
		echo "Cluster 'sre-agent' already exists. Skipping..."; \
	else \
		kind create cluster --config infra/kind-config.yaml; \
	fi
	@kubectl cluster-info --context kind-sre-agent

setup-chaos:
	@echo "Installing Chaos Mesh..."
	@kubectl create namespace chaos-mesh --dry-run=client -o yaml | kubectl apply -f -
	@if helm repo list | grep -q chaos-mesh; then \
		echo "Chaos Mesh helm repo already added"; \
	else \
		helm repo add chaos-mesh https://charts.chaos-mesh.org; \
	fi
	@helm repo update
	@helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
		--namespace chaos-mesh \
		--set chaosDaemon.runtime=containerd \
		--set chaosDaemon.socketPath=/run/containerd/containerd.sock \
		--set dashboard.securityMode=false \
		--wait
	@echo "✓ Chaos Mesh installed"

setup-monitoring:
	@echo "Setting up monitoring stack..."
	@kubectl apply -f infra/monitoring/namespace.yaml
	@kubectl apply -f infra/monitoring/prometheus.yaml
	@kubectl apply -f infra/monitoring/alertmanager.yaml
	@echo "Waiting for Prometheus to be ready..."
	@kubectl wait --for=condition=available deployment/prometheus -n monitoring --timeout=120s
	@echo "✓ Monitoring stack deployed"

# =============================================================================
# BUILD & DEPLOY
# =============================================================================

build-demo:
	@echo "Building demo app..."
	@docker build -t demo-app:latest infra/demo-app/
	@kind load docker-image demo-app:latest --name sre-agent
	@echo "✓ Demo app built and loaded to Kind"

deploy-demo:
	@echo "Deploying demo app..."
	@kubectl apply -f infra/k8s/namespace.yaml
	@kubectl apply -f infra/k8s/demo-app.yaml
	@echo "Waiting for demo app to be ready..."
	@kubectl wait --for=condition=available deployment/demo-app -n prod --timeout=120s
	@echo "✓ Demo app deployed"
	@echo "Access at: http://localhost:8080"

# =============================================================================
# DEVELOPMENT
# =============================================================================

install:
	@echo "Installing Python dependencies..."
	@uv venv --python 3.12
	@uv pip install -e ".[dev]"
	@echo "✓ Dependencies installed"

test: test-unit test-integration

test-unit:
	@echo "Running unit tests..."
	@uv run pytest tests/ -v --ignore=tests/integration/ -x

test-integration:
	@echo "Running integration tests..."
	@uv run pytest tests/integration/ -v -x

run:
	@echo "Starting SRE Agent API..."
	@uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

run-ui:
	@echo "Starting Streamlit Control Tower..."
	@uv run streamlit run src/ui/app.py --server.port 8501

# =============================================================================
# DEMO SCENARIOS
# =============================================================================

demo: deploy-demo
	@echo "Running demo scenario (OOM)..."
	@sleep 5
	@$(MAKE) demo-oom

demo-oom:
	@echo "Triggering OOM chaos experiment..."
	@kubectl apply -f infra/chaos/oom.yaml
	@echo "✓ OOM stress applied. Watch the agent respond!"
	@echo "Check the Control Tower at http://localhost:8501"

demo-network:
	@echo "Triggering network delay chaos experiment..."
	@kubectl apply -f infra/chaos/network-delay.yaml
	@echo "✓ Network delay applied for 60s"

demo-pod-kill:
	@echo "Triggering pod kill chaos experiment..."
	@kubectl apply -f infra/chaos/pod-kill.yaml
	@echo "✓ Pod kill triggered"

demo-pod-failure:
	@echo "Triggering pod failure chaos experiment..."
	@kubectl apply -f infra/chaos/pod-failure.yaml
	@echo "✓ Pod failure applied for 30s"

# Stop all chaos experiments
demo-stop:
	@echo "Stopping all chaos experiments..."
	@kubectl delete -f infra/chaos/ --ignore-not-found
	@echo "✓ All chaos experiments stopped"

# =============================================================================
# CLEANUP
# =============================================================================

clean:
	@echo "Cleaning up..."
	@kind delete cluster --name sre-agent || true
	@docker rmi demo-app:latest || true
	@echo "✓ Cleanup complete"

# Development database (local Postgres)
db-up:
	@echo "Starting local Postgres..."
	@docker run -d --name sre-agent-db \
		-e POSTGRES_USER=sre_agent \
		-e POSTGRES_PASSWORD=sre_agent \
		-e POSTGRES_DB=sre_agent \
		-p 5432:5432 \
		postgres:16-alpine
	@echo "Waiting for Postgres..."
	@sleep 3
	@echo "✓ Postgres running on localhost:5432"

db-down:
	@docker stop sre-agent-db && docker rm sre-agent-db || true

db-migrate:
	@echo "Running database migrations..."
	@uv run python -m src.db.migrate
	@echo "✓ Migrations complete"

# Logs and debugging
logs-demo:
	@kubectl logs -f deployment/demo-app -n prod

logs-prometheus:
	@kubectl logs -f deployment/prometheus -n monitoring

logs-chaos:
	@kubectl logs -f -l app.kubernetes.io/component=controller-manager -n chaos-mesh

# Port forwarding for debugging
port-forward-prometheus:
	@kubectl port-forward svc/prometheus 9090:9090 -n monitoring

port-forward-alertmanager:
	@kubectl port-forward svc/alertmanager 9093:9093 -n monitoring

# Status checks
status:
	@echo "=== Cluster Status ==="
	@kubectl cluster-info --context kind-sre-agent 2>/dev/null || echo "Cluster not running"
	@echo ""
	@echo "=== Pod Status ==="
	@kubectl get pods -A
	@echo ""
	@echo "=== Chaos Experiments ==="
	@kubectl get podchaos,stresschaos,networkchaos -A 2>/dev/null || echo "No chaos experiments"
