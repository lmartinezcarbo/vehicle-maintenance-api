FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

# The runtime names the port (Render injects $PORT); 8000 stays the
# default so local docker compose needs no change. exec keeps uvicorn as
# PID 1: without it the shell would swallow SIGTERM and every shutdown
# would end in SIGKILL after the grace period.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}