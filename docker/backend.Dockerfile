# Palimind backend — multi-stage build (CPU inference; Ollama runs separately)
FROM python:3.12-slim AS builder

WORKDIR /build
COPY packages/backend/pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip

# Runtime image
FROM python:3.12-slim

# EasyOCR needs libgl1 + libglib2.0; tini for proper signal handling
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PALIMIND_PORT=8000

WORKDIR /app
COPY packages/backend/pyproject.toml ./
COPY packages/backend/palimind ./palimind
RUN pip install --no-cache-dir .

# Non-root
RUN useradd --create-home palimind && mkdir -p /data/.palimind && chown -R palimind /data /app
USER palimind
ENV HOME=/data
WORKDIR /data

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status<500 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "palimind.api_server:app", "--host", "0.0.0.0", "--port", "8000"]
