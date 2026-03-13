"""One-shot Lambda to create sentinel_iam DB user and grant privileges.

Run once via CLI, passing master credentials in the event payload:
    aws lambda invoke --function-name glitch-fix-sentinel-iam \
      --payload '{"username":"glitch","password":"<MASTER_PASSWORD>"}' \
      /tmp/fix-response.json

This avoids needing Secrets Manager access (which requires internet/NAT/VPC endpoint).
"""

import json
import logging
import os
import ssl

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROTECT_DB_HOST = os.environ['PROTECT_DB_HOST']
PROTECT_DB_PORT = int(os.environ.get('PROTECT_DB_PORT', '5432'))
PROTECT_DB_NAME = os.environ.get('PROTECT_DB_NAME', 'glitch_protect')


def handler(event, context):
    import pg8000.native as pg

    username = event.get('username')
    password = event.get('password')
    if not username or not password:
        return {"statusCode": 400, "body": "Pass {\"username\": \"...\", \"password\": \"...\"} in the event"}

    logger.info("Connecting to %s:%s/%s as %s", PROTECT_DB_HOST, PROTECT_DB_PORT, PROTECT_DB_NAME, username)

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    conn = pg.Connection(
        user=username,
        password=password,
        host=PROTECT_DB_HOST,
        port=PROTECT_DB_PORT,
        database=PROTECT_DB_NAME,
        ssl_context=ssl_ctx,
    )

    results = []

    # Create extensions required by schema.sql (must be done by master/rds_superuser)
    for ext in ('vector', 'pg_trgm'):
        try:
            conn.run(f"CREATE EXTENSION IF NOT EXISTS {ext}")
            results.append(f"Extension {ext} ready")
            logger.info("Extension %s ready", ext)
        except Exception as e:
            results.append(f"Extension {ext} failed: {e}")
            logger.warning("Extension %s failed: %s", ext, e)

    # Apply schema.sql (all DDL uses IF NOT EXISTS, safe to re-run)
    try:
        import pathlib
        schema_path = pathlib.Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            schema_sql = schema_path.read_text()
            # pg8000 native .run() executes one statement at a time
            statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
            for stmt in statements:
                lines = [l for l in stmt.split('\n') if l.strip() and not l.strip().startswith('--')]
                if lines:
                    conn.run(stmt)
            results.append(f"Schema applied ({len(statements)} statements)")
            logger.info("Schema applied (%d statements)", len(statements))
        else:
            results.append("schema.sql not found in Lambda package")
            logger.warning("schema.sql not found")
    except Exception as e:
        results.append(f"Schema application failed: {e}")
        logger.warning("Schema application failed: %s", e)

    # Create/verify sentinel_iam (read-write, used by agent runtime)
    rows = conn.run("SELECT rolname FROM pg_roles WHERE rolname = 'sentinel_iam'")
    if rows:
        results.append("sentinel_iam already exists")
        logger.info("sentinel_iam already exists")
    else:
        conn.run("CREATE USER sentinel_iam")
        conn.run("GRANT rds_iam TO sentinel_iam")
        results.append("Created sentinel_iam with rds_iam")
        logger.info("Created sentinel_iam")

    conn.run("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sentinel_iam")
    conn.run("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sentinel_iam")
    conn.run("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO sentinel_iam")
    conn.run("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO sentinel_iam")
    results.append("Granted ALL PRIVILEGES to sentinel_iam")
    logger.info("Granted privileges to sentinel_iam")

    # Create/verify glitch_iam (read-only, used by protect-query Lambda)
    rows = conn.run("SELECT rolname FROM pg_roles WHERE rolname = 'glitch_iam'")
    if rows:
        results.append("glitch_iam already exists")
        logger.info("glitch_iam already exists")
    else:
        conn.run("CREATE USER glitch_iam")
        conn.run("GRANT rds_iam TO glitch_iam")
        results.append("Created glitch_iam with rds_iam")
        logger.info("Created glitch_iam")

    conn.run("GRANT SELECT ON ALL TABLES IN SCHEMA public TO glitch_iam")
    conn.run("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO glitch_iam")
    results.append("Granted SELECT to glitch_iam")
    logger.info("Granted SELECT privileges to glitch_iam")

    # auri_memory requires INSERT (store_memory) and DELETE (participant_upsert)
    # from the protect-query Lambda (glitch_iam), since it is the VPC bridge for
    # Auri memory writes from the PUBLIC-mode runtime.
    try:
        conn.run("GRANT INSERT, DELETE ON TABLE auri_memory TO glitch_iam")
        results.append("Granted INSERT, DELETE on auri_memory to glitch_iam")
        logger.info("Granted INSERT, DELETE on auri_memory to glitch_iam")
    except Exception as e:
        results.append(f"auri_memory grant skipped (table may not exist yet): {e}")
        logger.warning("auri_memory grant: %s", e)

    rows = conn.run("SELECT rolname FROM pg_roles WHERE rolname = 'sentinel_iam'")
    results.append(f"Verification: sentinel_iam exists = {bool(rows)}")
    rows = conn.run("SELECT rolname FROM pg_roles WHERE rolname = 'glitch_iam'")
    results.append(f"Verification: glitch_iam exists = {bool(rows)}")

    conn.close()
    return {"statusCode": 200, "body": json.dumps({"results": results})}
