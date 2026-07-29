# HipAAsynth REST API container.
#
# Builds an image that installs the (stdlib-only core) hipaasynth package and runs
# the REST API (hipaasynth/api.py) as the entrypoint. The API is pure standard
# library, so the image needs no compiled/native dependencies.
#
#   docker build -t hipaasynth-api .
#   docker run --rm -p 8000:8000 hipaasynth-api
#   curl http://localhost:8000/health
#
# Optional export formats that need extras (e.g. format=parquet -> pyarrow) are NOT
# installed by default to keep the image lean; the API returns a clean 400 telling
# the caller to install the extra. To bake one in, change the install line to
# `pip install --no-cache-dir '.[parquet]'`.
FROM python:3.11-slim

# Predictable, quiet Python in a container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy only what the wheel build needs (pyproject + package + readme/license),
# so the layer cache is not busted by unrelated repo churn.
COPY pyproject.toml README.md LICENSE.md ./
COPY hipaasynth ./hipaasynth

# Install the package itself (hatchling build backend, declared in pyproject).
RUN pip install --no-cache-dir .

# Run as a non-root user — this is a network-facing service.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Liveness: hit the API's own /health endpoint using only the stdlib (no curl in
# the slim image).
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

# Bind to 0.0.0.0 so the API is reachable from outside the container. Additional
# flags (e.g. --max-count) can be appended to `docker run ... <flags>`.
ENTRYPOINT ["python", "-m", "hipaasynth.api"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
