"""Entry point when running as a module: python -m sentinel."""
import logging
import uvicorn
from sentinel.server import app


class _PingFilter(logging.Filter):
    """Suppress uvicorn access log entries for /ping health checks."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /ping" not in record.getMessage()


if __name__ == "__main__":
    # Attach filter before uvicorn starts so it takes effect from the first request.
    logging.getLogger("uvicorn.access").addFilter(_PingFilter())
    uvicorn.run(app, host="0.0.0.0", port=9000)
