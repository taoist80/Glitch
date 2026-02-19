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
RUN uv pip install aws-opentelemetry-distro==0.12.2

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY src/ /app/src/
COPY SOUL.md /app/SOUL.md

EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "-m", "src.main"]
