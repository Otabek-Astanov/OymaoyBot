FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --gid 10001 bot \
    && useradd --uid 10001 --gid bot --no-create-home --shell /usr/sbin/nologin bot

COPY --chown=root:root . .
RUN mkdir -p /app/data /app/media /app/secrets \
    && chown -R bot:bot /app/data /app/media
USER 10001:10001
CMD ["python", "run_all.py"]
