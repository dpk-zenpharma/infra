#!/bin/bash
# =============================================================================
# Initialize Database Schemas
#
# Creates per-service PostgreSQL schemas in the RDS database.
# Runs a temporary pod inside the EKS cluster to reach the private RDS instance.
#
# Usage:
#   ./scripts/init-database.sh
#
# Prerequisites:
#   - kubectl configured to talk to your EKS cluster
#   - RDS instance running and accessible from the cluster
#   - db-init/01-schemas.sql exists in the gitops repo
# =============================================================================

set -e

GREEN="\033[0;32m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

log()  { echo -e "${GREEN}[OK]  $1${NC}"; }
info() { echo -e "${CYAN}      $1${NC}"; }
die()  { echo -e "${RED}[ERR] $1${NC}" >&2; exit 1; }

# ── Collect inputs ──────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Zen Pharma — Database Schema Initializer"
echo "============================================"
echo ""

# RDS endpoint
if [ -z "$RDS_ENDPOINT" ]; then
  echo -n "  RDS endpoint (e.g., pharma-dev-postgres.xxx.us-east-1.rds.amazonaws.com): "
  read RDS_ENDPOINT
fi
[ -z "$RDS_ENDPOINT" ] && die "RDS endpoint is required."

# Database password
if [ -z "$DB_PASSWORD" ]; then
  echo -n "  Database password: "
  read -s DB_PASSWORD
  echo ""
fi
[ -z "$DB_PASSWORD" ] && die "Database password is required."

# Namespace
NAMESPACE="${NAMESPACE:-dev}"

# SQL file path
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
SQL_FILE="${PROJECT_ROOT}/gitops/db-init/01-schemas.sql"

if [ ! -f "$SQL_FILE" ]; then
  SQL_FILE="${SCRIPT_DIR}/../db-init/01-schemas.sql"
fi

if [ ! -f "$SQL_FILE" ]; then
  die "SQL file not found. Expected at: ${PROJECT_ROOT}/gitops/db-init/01-schemas.sql"
fi

echo ""
echo "  ----- Configuration -----"
echo "  RDS endpoint : $RDS_ENDPOINT"
echo "  Namespace    : $NAMESPACE"
echo "  SQL file     : $SQL_FILE"
echo "  ---------------------------"
echo ""
echo -n "  Proceed? [Y/n]: "
read CONFIRM
CONFIRM="${CONFIRM:-Y}"
[ "$CONFIRM" != "Y" ] && [ "$CONFIRM" != "y" ] && echo "Aborted." && exit 0
echo ""

# ── Ensure namespace exists ─────────────────────────────────────────────────

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
log "Namespace '$NAMESPACE' ready."

# ── Clean up any leftover pg-client pod ─────────────────────────────────────

kubectl delete pod pg-client -n "$NAMESPACE" --ignore-not-found > /dev/null 2>&1

# ── Start temporary postgres pod ────────────────────────────────────────────

info "Starting temporary PostgreSQL client pod..."
kubectl run pg-client --restart=Never --image=postgres:17 -n "$NAMESPACE" \
  --env="PGPASSWORD=$DB_PASSWORD" -- sleep 3600 > /dev/null

info "Waiting for pod to be ready..."
kubectl wait --for=condition=Ready pod/pg-client -n "$NAMESPACE" --timeout=60s > /dev/null
log "Pod 'pg-client' is running."

# ── Copy SQL file into the pod ──────────────────────────────────────────────

info "Copying SQL file into pod..."
kubectl cp "$SQL_FILE" pg-client:/tmp/01-schemas.sql -n "$NAMESPACE"
log "SQL file copied."

# ── Run the SQL ─────────────────────────────────────────────────────────────

info "Running schema initialization..."
kubectl exec pg-client -n "$NAMESPACE" -- psql \
  -h "$RDS_ENDPOINT" \
  -U pharmaadmin \
  -d pharmadb \
  -f /tmp/01-schemas.sql

log "Schema SQL executed."

# ── Verify ──────────────────────────────────────────────────────────────────

echo ""
info "Verifying schemas..."
kubectl exec pg-client -n "$NAMESPACE" -- psql \
  -h "$RDS_ENDPOINT" \
  -U pharmaadmin \
  -d pharmadb \
  -c '\dn'

# ── Clean up ────────────────────────────────────────────────────────────────

echo ""
info "Cleaning up temporary pod..."
kubectl delete pod pg-client -n "$NAMESPACE" > /dev/null
log "Pod deleted."

echo ""
log "Database initialization complete."
echo ""
