"""Shared AWS utilities for Glitch tools.

Provides a single REGION constant, default botocore Config, and a lazy boto3
client factory to eliminate per-file boilerplate.
"""

import os
from typing import Any

import boto3
from botocore.config import Config

REGION: str = os.environ.get("AWS_REGION", "us-west-2")

# Default client config for short-latency API calls.
CLIENT_CONFIG = Config(
    connect_timeout=10,
    read_timeout=15,
    retries={"max_attempts": 2, "mode": "standard"},
)

# Long-timeout config for operations like CloudFormation drift detection (up to 60s).
CLIENT_CONFIG_LONG = Config(
    connect_timeout=10,
    read_timeout=120,
    retries={"max_attempts": 2, "mode": "standard"},
)

_clients: dict[str, Any] = {}


def get_client(service: str, config: Config = CLIENT_CONFIG) -> Any:
    """Return a cached boto3 client for the given service.

    Caches by service name with the default config. For non-default configs
    pass config explicitly and call boto3.client directly.
    """
    if service not in _clients:
        _clients[service] = boto3.client(service, region_name=REGION, config=config)
    return _clients[service]
