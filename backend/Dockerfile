FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
# ffmpeg now, though nothing renders until M2, so the image a deployment pulls today is
# the image rendering will run in.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini entrypoint.sh ./
RUN mkdir -p /app/data/db
ENTRYPOINT ["./entrypoint.sh"]
