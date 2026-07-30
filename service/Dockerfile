FROM node:22-bookworm-slim

# Higgsfield CLI (Go binary via npm package)
RUN npm i -g @higgsfield/cli@latest \
  && apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ca-certificates curl jq \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.txt /app/service/requirements.txt
RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --no-cache-dir -r /app/service/requirements.txt

COPY service /app/service
COPY ensure_higgsfield_auth.py /app/ensure_higgsfield_auth.py

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    REFRESH_CRON="0 6 * * *"

EXPOSE 8080

CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8080"]
