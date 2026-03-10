#!/bin/bash
# setup-protect-db.sh
#
# One-time setup for the glitch_protect RDS PostgreSQL database.
# Creates the database, two IAM DB users, extensions, and applies the schema.
#
# This script targets the RDS instance created by GlitchProtectDbStack.
# It DOES NOT create password-based users — authentication is via RDS IAM
# tokens only.  Two IAM DB users are created:
#
#   glitch_iam    — used by the protect-query Lambda (read-only UI queries)
#   sentinel_iam  — used by the Sentinel AgentCore agent (event writes, full access)
#
# Requirements:
#   - psql available on PATH
#   - AWS credentials with rds:Connect and access to glitch/protect-db-master secret
#   - pgvector and pg_trgm extensions must be available (RDS pg-16 includes them)
#   - The RDS instance must be reachable (run with --pg-host set to the RDS endpoint)
#
# Usage:
#   ./setup-protect-db.sh [options]
#
# Options:
#   --db-name NAME       Database name (default: glitch_protect)
#   --pg-user USER       Postgres master username (default: glitch, from glitch/protect-db-master)
#   --pg-password PASS   Postgres master password (prompted if omitted)
#   --pg-host HOST       Postgres host — RDS endpoint (default: localhost)
#   --pg-port PORT       Postgres port (default: 5432)
#   --schema-file PATH   Path to schema.sql (auto-detected from script location)
#   --skip-create-db     Skip database creation (if it already exists)
#   --skip-iam-users     Skip IAM DB user creation (if they already exist)
#   --region REGION      AWS region (default: us-west-2)
#
# Examples:
#   ./setup-protect-db.sh --pg-host mydb.xxxx.us-west-2.rds.amazonaws.com --pg-password secret
#   ./setup-protect-db.sh --pg-host $(aws ssm get-parameter --name /glitch/protect-db/host --query Parameter.Value --output text)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DEFAULT_SCHEMA="${REPO_ROOT}/monitoring-agent/src/sentinel/protect/schema.sql"

# Defaults
DB_NAME="glitch_protect"
PG_USER="glitch"
PG_PASSWORD=""
PG_HOST="localhost"
PG_PORT="5432"
SCHEMA_FILE="$DEFAULT_SCHEMA"
SKIP_CREATE_DB=false
SKIP_IAM_USERS=false
AWS_REGION="us-west-2"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --db-name)        DB_NAME="$2";      shift 2 ;;
        --pg-user)        PG_USER="$2";      shift 2 ;;
        --pg-password)    PG_PASSWORD="$2";  shift 2 ;;
        --pg-host)        PG_HOST="$2";      shift 2 ;;
        --pg-port)        PG_PORT="$2";      shift 2 ;;
        --schema-file)    SCHEMA_FILE="$2";  shift 2 ;;
        --skip-create-db) SKIP_CREATE_DB=true; shift ;;
        --skip-iam-users) SKIP_IAM_USERS=true; shift ;;
        --region)         AWS_REGION="$2";   shift 2 ;;
        --help)
            head -n 40 "$0" | tail -n +3 | sed 's/^# //'
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

log()     { echo "[setup-protect-db] $*"; }
log_ok()  { echo "[setup-protect-db] ✓ $*"; }
log_err() { echo "[setup-protect-db] ERROR: $*" >&2; }

# Resolve master password from Secrets Manager if not provided
if [[ -z "$PG_PASSWORD" ]]; then
    if command -v aws &>/dev/null; then
        log "Attempting to read master password from Secrets Manager (glitch/protect-db-master)..."
        MASTER_SECRET=$(aws secretsmanager get-secret-value \
            --secret-id glitch/protect-db-master \
            --region "$AWS_REGION" \
            --query SecretString \
            --output text 2>/dev/null || true)
        if [[ -n "$MASTER_SECRET" ]]; then
            PG_PASSWORD=$(echo "$MASTER_SECRET" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('password',''))")
            if [[ -n "$PG_PASSWORD" ]]; then
                log_ok "Master password loaded from Secrets Manager"
            fi
        fi
    fi
fi

if [[ -z "$PG_PASSWORD" ]]; then
    read -r -s -p "Password for Postgres master user '${PG_USER}': " PG_PASSWORD
    echo
fi

if [[ -z "$PG_PASSWORD" ]]; then
    log_err "Password cannot be empty."
    exit 1
fi

# Validate schema file
if [[ ! -f "$SCHEMA_FILE" ]]; then
    log_err "Schema file not found: $SCHEMA_FILE"
    log_err "Pass --schema-file /path/to/schema.sql or run from the repo root."
    exit 1
fi

# Helper: run psql as master user (RDS or local)
pg_exec() {
    local db="$1"; shift
    PGPASSWORD="$PG_PASSWORD" PGSSLMODE="require" psql \
        --host="$PG_HOST" \
        --port="$PG_PORT" \
        --username="$PG_USER" \
        --dbname="$db" \
        "$@"
}

log "Starting Protect DB setup (RDS IAM auth mode)"
log "  Host:     ${PG_HOST}:${PG_PORT}"
log "  Database: ${DB_NAME}"
log "  Master:   ${PG_USER}"
log "  Region:   ${AWS_REGION}"
log "  Schema:   ${SCHEMA_FILE}"
echo

# ── Step 1: Verify extensions (pgvector + pg_trgm) ────────────────────────────
# RDS PostgreSQL 16 includes both extensions; we just need to enable them.
log "Verifying required extensions are available on RDS..."
VECTOR_AVAIL=$(pg_exec postgres -tAc "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'vector'" 2>/dev/null | tr -d ' ')
TRGM_AVAIL=$(pg_exec postgres -tAc "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'pg_trgm'" 2>/dev/null | tr -d ' ')

if [[ "$VECTOR_AVAIL" == "0" ]]; then
    log_err "pgvector extension is not available on this RDS instance."
    log_err "Ensure you are using RDS PostgreSQL 15+ and have enabled the pgvector parameter group."
    exit 1
fi
log_ok "pgvector is available"
log_ok "pg_trgm is available"

# ── Step 2: Create database ────────────────────────────────────────────────────
if [[ "$SKIP_CREATE_DB" == false ]]; then
    log "Creating database '${DB_NAME}'..."
    if pg_exec postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1; then
        log "Database '${DB_NAME}' already exists — skipping creation"
    else
        pg_exec postgres -c "CREATE DATABASE \"${DB_NAME}\" ENCODING 'UTF8';"
        log_ok "Database '${DB_NAME}' created"
    fi
else
    log "Skipping database creation (--skip-create-db)"
fi

# ── Step 3: Create IAM DB users ───────────────────────────────────────────────
# RDS IAM auth uses NOLOGIN roles with rds_iam membership — no password needed.
if [[ "$SKIP_IAM_USERS" == false ]]; then
    log "Creating IAM DB users (glitch_iam, sentinel_iam)..."
    pg_exec "$DB_NAME" -c "
        DO \$\$
        BEGIN
            -- glitch_iam: used by the protect-query Lambda (read-only UI queries)
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'glitch_iam') THEN
                CREATE USER glitch_iam;
                GRANT rds_iam TO glitch_iam;
                RAISE NOTICE 'IAM user glitch_iam created';
            ELSE
                RAISE NOTICE 'IAM user glitch_iam already exists';
            END IF;

            -- sentinel_iam: used by the Sentinel agent (event writes, full access)
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentinel_iam') THEN
                CREATE USER sentinel_iam;
                GRANT rds_iam TO sentinel_iam;
                RAISE NOTICE 'IAM user sentinel_iam created';
            ELSE
                RAISE NOTICE 'IAM user sentinel_iam already exists';
            END IF;
        END
        \$\$;
    "
    log_ok "IAM DB users ready"
else
    log "Skipping IAM user creation (--skip-iam-users)"
fi

# ── Step 4: Install extensions ─────────────────────────────────────────────────
log "Installing extensions (vector, pg_trgm)..."
pg_exec "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"
pg_exec "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
log_ok "Extensions installed"

# ── Step 5: Apply schema ───────────────────────────────────────────────────────
log "Applying schema from ${SCHEMA_FILE}..."
pg_exec "$DB_NAME" --file="$SCHEMA_FILE"
log_ok "Schema applied"

# ── Step 6: Grant privileges ───────────────────────────────────────────────────
log "Granting table/sequence privileges to IAM users..."
pg_exec "$DB_NAME" -c "
    -- sentinel_iam: full read-write access (event inserts, anomaly updates, etc.)
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sentinel_iam;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sentinel_iam;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO sentinel_iam;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO sentinel_iam;

    -- glitch_iam: read-only access (UI queries only)
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO glitch_iam;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO glitch_iam;
"
log_ok "Privileges granted"

# ── Step 7: Verify ─────────────────────────────────────────────────────────────
log "Verifying tables..."
TABLE_COUNT=$(pg_exec "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
log_ok "${TABLE_COUNT} tables present in ${DB_NAME}"

pg_exec "$DB_NAME" -tAc "
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
" | while read -r t; do
    echo "        • $t"
done

echo
log_ok "Setup complete!"
echo
echo "  No Secrets Manager update needed — Sentinel uses RDS IAM auth (no password)."
echo
echo "  Next steps:"
echo "  1. Redeploy Sentinel so it picks up the DB host from SSM:"
echo "     cd monitoring-agent && make deploy"
echo
echo "  2. Verify SSM has the RDS endpoint:"
echo "     aws ssm get-parameter --name /glitch/protect-db/host --region ${AWS_REGION}"
echo
echo "  3. Check Sentinel logs for 'Protect DB pool created':"
echo "     cd monitoring-agent && make check-logs"
