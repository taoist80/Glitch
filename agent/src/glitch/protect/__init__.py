"""UniFi Protect integration package.

Provides tools and infrastructure for integrating with UniFi Protect cameras,
including event processing, entity recognition, anomaly detection, and alerting.

Modules:
    config     - Credential and config loading (env/SSM/Secrets Manager)
    client     - Async Protect API client
    db         - asyncpg connection pool and schema init
    recognition - LLaVA prompts and entity feature extraction
    event_processor - Async queue + worker pool for real-time processing
    tracking   - Cross-camera entity tracking
    privacy    - Data retention, export, and deletion
    webhook    - Incoming Protect webhook handler
"""
