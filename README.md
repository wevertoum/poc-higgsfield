# poc-higgsfield

PoC CLI for **Higgsfield Marketing Studio**: create a custom avatar from a local image, register a product, and generate a UGC-style video — with headless auth suitable for automation.

## What this does

```text
reference image
    → upload
    → Marketing Studio custom avatar
    → Marketing Studio product
    → marketing_studio_video (mode: ugc)
    → download MP4 under output/higgsfield/
```

Official Marketing Studio docs/skills: [higgsfield-ai/skills](https://github.com/higgsfield-ai/skills) and the [Higgsfield CLI](https://higgsfield.ai/cli).

## Prerequisites

- Node.js 18+
- Python 3.11+
- `jq`, `curl`
- Higgsfield account with Marketing Studio access (paid / workspace credits)

```bash
npm i -g @higgsfield/cli
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only if using email/password Playwright fallback
```

## Auth (headless)

The official CLI uses **OAuth** (`higgsfield auth login`). There is **no long-lived API key** for Marketing Studio yet ([higgsfield-ai/cli#47](https://github.com/higgsfield-ai/cli/issues/47)).

This PoC bridges that with `ensure_higgsfield_auth.py`, which runs automatically before generation.

### Option A — credentials inject (recommended for Google SSO accounts)

1. Login once in a browser:

```bash
higgsfield auth login
```

2. Save the credentials file (gitignored):

```bash
cp ~/.config/higgsfield/credentials.json ./.higgsfield_credentials.json
```

3. Configure `.env` (see `.env.example`):

```env
HIGGSFIELD_CREDENTIALS_FILE=/absolute/path/to/poc-higgsfield/.higgsfield_credentials.json
HIGGSFIELD_WORKSPACE_ID=your-workspace-uuid
```

List workspaces:

```bash
higgsfield workspace list --json
```

### Option B — Playwright email/password

Only works if the account has **email + password** (not Google-only SSO).

```env
HIGGSFIELD_EMAIL=you@company.com
HIGGSFIELD_PASSWORD=...
HIGGSFIELD_WORKSPACE_ID=your-workspace-uuid
```

### Verify auth

```bash
python ensure_higgsfield_auth.py
higgsfield account status --json
```

## Project layout

| Path | Purpose |
|---|---|
| `generate_higgsfield.sh` | End-to-end Marketing Studio pipeline |
| `ensure_higgsfield_auth.py` | Inject credentials / refresh / Playwright OAuth |
| `prompt_higgsfield.txt` | UGC video brief (prompt) |
| `reference_assets/` | Local images used as avatar / product references |
| `.env.example` | Documented env vars (no secrets) |
| `output/higgsfield/` | Generated runs (gitignored) |

## Run

Put images in `reference_assets/`, then:

```bash
chmod +x generate_higgsfield.sh

# avatar + product from the same image
./generate_higgsfield.sh example.png --name "UGC Creator"

# separate product still
./generate_higgsfield.sh example.png --product-image example.1.png --name "UGC Creator"

# reuse ids from a previous run
./generate_higgsfield.sh example.png \
  --avatar-id <avatar_uuid> \
  --product-id <product_uuid>
```

### Useful flags

| Flag | Description |
|---|---|
| `--name` | Custom avatar name |
| `--product-image` | Filename in `reference_assets/` for the product |
| `--mode` | Marketing Studio mode (default: `ugc`) |
| `--duration` | Seconds (default: `15`) |
| `--resolution` | e.g. `720p` |
| `--aspect-ratio` | e.g. `9:16` |
| `--avatar-id` / `--product-id` | Skip create and reuse existing assets |
| `--prompt-file` | Override `prompt_higgsfield.txt` |

## Output

Each run creates a folder under `output/higgsfield/<name>_<timestamp>/` with:

- `avatar.json` / `product.json`
- `avatars.json` / `product_ids.json` (payloads passed to generate)
- `generate.json` (job response)
- `ugc_<mode>.mp4`
- `summary.json`

## Prompt

Edit `prompt_higgsfield.txt` for dialogue, motion, and product language. Marketing Studio generates the creative from this brief + avatar + product context.

## Security notes

- **Never commit** `.env`, `.higgsfield_credentials.json`, or `~/.config/higgsfield/credentials.json`
- Treat `access_token` / `refresh_token` as secrets; rotate if leaked
- Google SSO accounts: use Option A (credentials inject). Playwright password login will not work without a password set on the Clerk account

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Not authenticated` / `Session expired` | Re-run `higgsfield auth login`, refresh `.higgsfield_credentials.json` |
| `No workspace selected` | Set `HIGGSFIELD_WORKSPACE_ID` or `higgsfield workspace set <id>` |
| `--image-url is not exposed` | Current CLI expects `--image <upload_id>` only (already handled in the script) |
| `jq: Cannot index array with string "id"` | Create endpoints may return arrays; script parses both shapes |
| Playwright can't find password field | Account is Google-only → use credentials inject |

## License

Internal PoC / experimental.
