# Phase 8: one image with the API + the frontend pages, talking to SQL Server through ODBC Driver 18.
# Build from the repository root:   docker build -f backend/Dockerfile -t assessify .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FLASK_ENV=production PORT=8000 DB_DRIVER="ODBC Driver 18 for SQL Server"

# Microsoft ODBC Driver 18 (needed by pyodbc to reach SQL Server / Azure SQL)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gnupg \
      unixodbc \
 && curl --proto '=https' --tlsv1.2 -fsS https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
    > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
# requirements.lock = exact versions + hashes (made from requirements.txt with pip-compile, see docs/DEPLOY.md).
# Wheels only: no package can run its own setup code while the image is built.
COPY backend/requirements.lock .
RUN pip install --no-cache-dir --only-binary :all: --require-hashes -r requirements.lock

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
RUN rm -rf tests .env && useradd --create-home --uid 10001 assessify
USER assessify

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"
# Database tables are created / upgraded on start, then the production server runs: gunicorn with
# WEB_CONCURRENCY processes x 8 threads (load test: 4 processes served 300 candidates with a 56 ms median answer save).
# Each process keeps its own wrong-login counters, so the login limits are per process.
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "flask --app run db upgrade && exec gunicorn -w $WEB_CONCURRENCY --threads 8 -b 0.0.0.0:$PORT --keep-alive 30 --timeout 120 --access-logfile - run:app"]
