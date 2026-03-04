FROM --platform=linux/arm64 python:3.10-slim

WORKDIR /app

# Install uv for fast package management
RUN pip install --no-cache-dir uv

# Copy requirements first for layer caching
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy source
COPY src/ ./src/
COPY SOUL.md .

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["opentelemetry-instrument", "python", "-m", "sentinel"]
