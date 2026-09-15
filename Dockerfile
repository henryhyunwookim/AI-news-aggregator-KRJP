FROM python:3.11-slim

# Ensure logs are streamed to Cloud Logging
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/

# Copy local credentials/env files if present during local/private builds.
# Trailing wildcards ensure 'docker build' succeeds cleanly even if these git-ignored files are absent.
# Security Note: For public image registries, avoid baking secrets into images;
# inject configuration via environment variables or Google Cloud Secret Manager instead.
COPY credentials.json* token.json* .env* ./

# Add /app to PYTHONPATH so we can import 'src' as a package
ENV PYTHONPATH=/app

# Run the web service on container startup using gunicorn
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "src.app:app"]
