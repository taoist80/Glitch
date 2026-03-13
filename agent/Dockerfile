FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DOCKER_CONTAINER=1

COPY requirements.txt .
RUN uv pip install -r requirements.txt

# OTEL instrumentation for AgentCore Runtime metrics/traces
RUN uv pip install aws-opentelemetry-distro==0.12.2

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY src/glitch/ /app/glitch/
COPY src/main.py /app/main.py
COPY skills/ /app/skills/
COPY SOUL.md /app/SOUL.md
COPY poet-soul.md /app/poet-soul.md
COPY auri.md /app/auri.md

EXPOSE 8080

# AgentCore observability: ADOT auto-instrumentation sends OTEL traces/metrics to CloudWatch.
# See https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
CMD ["opentelemetry-instrument", "python", "-m", "main"]
