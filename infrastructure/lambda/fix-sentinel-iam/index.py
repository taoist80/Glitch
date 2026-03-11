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

    rows = conn.run("SELECT rolname FROM pg_roles WHERE rolname = 'sentinel_iam'")
    results.append(f"Verification: sentinel_iam exists = {bool(rows)}")

    conn.close()
    return {"statusCode": 200, "body": json.dumps({"results": results})}
