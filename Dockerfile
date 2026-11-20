# Worker, CLI und Freigabe-Cockpit in einem Image. Postgres läuft als eigener Dienst.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Abhängigkeiten zuerst (eigene Schicht, ändert sich selten)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY configs ./configs
COPY docs/spezifikation.md ./docs/spezifikation.md
RUN uv sync --locked --no-dev

# Nicht als root laufen; Daten und Läufe liegen in Volumes
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /app/runs \
    && chown app:app /app/data /app/runs
USER app

ENTRYPOINT ["invoice"]
CMD ["--help"]
