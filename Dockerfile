FROM python:3.12-slim

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata and install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application source
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY sql/ ./sql/

# Create /data directory for the SQLite volume mount
RUN mkdir -p /data

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
