# Higgsfield bridge service (AWS-ready)

Small FastAPI service that:

1. Loads Higgsfield OAuth credentials (file / env / AWS Secrets Manager)
2. Refreshes auth on startup + once per day (cron)
3. Exposes HTTP endpoints to list Marketing Studio **avatars** and **products**

```text
Client ──HTTP──▶ FastAPI (ECS/Fargate)
                    │
                    ├─ daily refresh (APScheduler)
                    ├─ higgsfield CLI (avatars/products list)
                    └─ Secrets Manager (optional token store)
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness + last refresh metadata |
| `POST` | `/auth/refresh` | Force token/workspace refresh now |
| `GET` | `/account` | Credits / plan |
| `GET` | `/avatars?custom_only=true` | Avatars (filter custom) |
| `GET` | `/products` | Products in workspace |

Optional gate: set `SERVICE_API_KEY` and send header `x-api-key: ...`.

## Local run

```bash
# from repo root
source .venv/bin/activate
pip install -r service/requirements.txt

export HIGGSFIELD_CREDENTIALS_FILE="$PWD/.higgsfield_credentials.json"
export HIGGSFIELD_WORKSPACE_ID=your-workspace-uuid
# export SERVICE_API_KEY=dev-secret

uvicorn service.app:app --reload --port 8080
```

Examples:

```bash
curl -s localhost:8080/health | jq
curl -s -H "x-api-key: $SERVICE_API_KEY" 'localhost:8080/avatars?custom_only=true' | jq
curl -s -H "x-api-key: $SERVICE_API_KEY" localhost:8080/products | jq
curl -s -X POST -H "x-api-key: $SERVICE_API_KEY" localhost:8080/auth/refresh | jq
```

## Auth model (important)

Higgsfield Marketing Studio CLI has **no long-lived API key** yet
([cli#47](https://github.com/higgsfield-ai/cli/issues/47)).

Recommended production pattern for Google SSO accounts:

1. Human runs `higgsfield auth login` once
2. Store `credentials.json` (with `refresh_token`) in **AWS Secrets Manager**
3. Service injects credentials on boot + daily refresh
4. CLI refreshes `access_token` using `refresh_token`
5. Service writes the updated JSON back to Secrets Manager
6. When refresh eventually expires → alert + one manual re-login

Env vars:

| Var | Purpose |
|---|---|
| `HIGGSFIELD_CREDENTIALS_FILE` | Local credentials JSON path |
| `HIGGSFIELD_CREDENTIALS` | Inline JSON (dev only) |
| `HIGGSFIELD_SECRET_NAME` / `HIGGSFIELD_SECRET_ARN` | Secrets Manager secret |
| `HIGGSFIELD_WORKSPACE_ID` | Workspace UUID |
| `REFRESH_CRON` | Default `0 6 * * *` (06:00 UTC daily) |
| `SERVICE_API_KEY` | Optional API key for callers |
| `AWS_REGION` | Required when using Secrets Manager |

## Docker

```bash
docker build -f service/Dockerfile -t higgsfield-bridge .
docker run --rm -p 8080:8080 \
  -e HIGGSFIELD_CREDENTIALS_FILE=/secrets/credentials.json \
  -e HIGGSFIELD_WORKSPACE_ID=... \
  -e SERVICE_API_KEY=... \
  -v "$PWD/.higgsfield_credentials.json:/secrets/credentials.json:ro" \
  higgsfield-bridge
```

## AWS deployment sketch

### Option A — ECS Fargate service (always on)

1. Put credentials JSON in Secrets Manager (`higgsfield/credentials`)
2. Task role: `secretsmanager:GetSecretValue`, `PutSecretValue`
3. Task env:
   - `HIGGSFIELD_SECRET_NAME=higgsfield/credentials`
   - `HIGGSFIELD_WORKSPACE_ID=...`
   - `SERVICE_API_KEY=...`
   - `REFRESH_CRON=0 6 * * *`
4. ALB → target group → service `:8080`
5. Consumers call `/avatars` and `/products` with `x-api-key`

### Option B — EventBridge daily refresh job + small API

1. EventBridge rule `cron(0 6 * * ? *)` → ECS RunTask / Lambda container
2. Command: `python service/refresh_once.py`
3. Separate always-on API task (or Lambda+CLI image) for GET endpoints

Option A is simpler for a PoC.

## Limitations

- Relies on official `higgsfield` CLI inside the container (not the cloud `KEY:SECRET` platform API).
- Google SSO cannot be fully automated forever — refresh tokens eventually expire and need a human re-auth.
- Do not commit real credentials.
