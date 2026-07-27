FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000
# Migrate + seed the gallery before serving, so `docker compose up` yields a
# working DB; the demo projects are bootstrapped when MINILP_BOOTSTRAP_DEMO=1
# (compose sets it). See entrypoint.sh.
CMD ["./entrypoint.sh"]
