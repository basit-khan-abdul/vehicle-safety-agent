# Dockerfile — scaffold stub.
#
# There is no application to run yet (Day 1: scaffold only). This file exists so
# the deployment story is wired from the start; it will build the backend once
# backend/ has real code. Do not expect a working image yet.

FROM python:3.11-slim

WORKDIR /app

# Dependency install + source COPY steps land here once backend/ has real code, e.g.:
#   COPY pyproject.toml uv.lock ./
#   RUN pip install uv && uv sync --frozen
#   COPY backend/ ./backend/

CMD ["python", "-c", "print('vehicle-safety-agent: scaffold only — no app yet')"]
