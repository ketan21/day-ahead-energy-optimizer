# Build from the repository root:
#   docker build -f addon/Dockerfile -t ghcr.io/ketan21/daeo:2.0.0 .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAEO_DATA_DIR=/data \
    DAEO_HOST=0.0.0.0 \
    DAEO_PORT=8099

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir .

COPY addon/run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099
CMD ["/run.sh"]
