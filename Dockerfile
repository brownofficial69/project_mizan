FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md mizan_core.py index.html ./
COPY mizan ./mizan
COPY web ./web
COPY results ./results
RUN pip install ".[api]" && useradd --system --uid 10001 mizan
USER mizan

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

# Scale by running more containers; each is stateless. WEB_CONCURRENCY sets workers per container.
CMD ["sh", "-c", "uvicorn mizan.api:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers"]
