"""Higgsfield CLI helpers for the HTTP service."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CREDS = Path.home() / ".config" / "higgsfield" / "credentials.json"


class HiggsfieldError(RuntimeError):
    pass


def credentials_path() -> Path:
    override = os.getenv("HIGGSFIELD_CREDENTIALS_PATH")
    return Path(override).expanduser() if override else DEFAULT_CREDS


def which_higgsfield() -> str:
    path = shutil.which("higgsfield")
    if not path:
        raise HiggsfieldError("higgsfield CLI not found on PATH")
    return path


def _run(args: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise HiggsfieldError(f"{' '.join(args)} failed: {detail}")
    return proc.stdout


def write_credentials(data: dict[str, Any] | str) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data if isinstance(data, dict) else json.loads(data)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def load_credentials_from_env() -> dict[str, Any] | None:
    file_path = os.getenv("HIGGSFIELD_CREDENTIALS_FILE", "").strip()
    raw = os.getenv("HIGGSFIELD_CREDENTIALS", "").strip()
    if file_path:
        return json.loads(Path(file_path).expanduser().read_text(encoding="utf-8"))
    if raw:
        return json.loads(raw)
    return None


def load_credentials_from_secrets_manager() -> dict[str, Any] | None:
    secret_id = os.getenv("HIGGSFIELD_SECRET_ARN", "").strip() or os.getenv(
        "HIGGSFIELD_SECRET_NAME", ""
    ).strip()
    if not secret_id:
        return None
    try:
        import boto3
    except ImportError as exc:
        raise HiggsfieldError(
            "boto3 is required for Secrets Manager. pip install boto3"
        ) from exc

    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION"))
    resp = client.get_secret_value(SecretId=secret_id)
    body = resp.get("SecretString") or ""
    return json.loads(body)


def persist_credentials_to_secrets_manager(data: dict[str, Any]) -> None:
    secret_id = os.getenv("HIGGSFIELD_SECRET_ARN", "").strip() or os.getenv(
        "HIGGSFIELD_SECRET_NAME", ""
    ).strip()
    if not secret_id:
        return
    import boto3

    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION"))
    client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(data))


def ensure_workspace() -> str | None:
    workspace_id = os.getenv("HIGGSFIELD_WORKSPACE_ID", "").strip()
    if not workspace_id:
        return None
    _run([which_higgsfield(), "workspace", "set", workspace_id], timeout=60)
    return workspace_id


def account_status() -> dict[str, Any]:
    out = _run([which_higgsfield(), "account", "status", "--json"], timeout=60)
    return json.loads(out)


def refresh_auth() -> dict[str, Any]:
    """Inject credentials, force CLI to touch the API (refresh if needed), persist."""
    creds = load_credentials_from_secrets_manager()
    if creds is None:
        creds = load_credentials_from_env()
    if creds is None and credentials_path().exists():
        creds = json.loads(credentials_path().read_text(encoding="utf-8"))
    if creds is None:
        raise HiggsfieldError(
            "No credentials found. Set HIGGSFIELD_CREDENTIALS_FILE, "
            "HIGGSFIELD_CREDENTIALS, or HIGGSFIELD_SECRET_NAME"
        )

    write_credentials(creds)
    workspace_id = ensure_workspace()
    status = account_status()

    # CLI may have rotated tokens on disk — persist back.
    if credentials_path().exists():
        fresh = json.loads(credentials_path().read_text(encoding="utf-8"))
        write_credentials(fresh)
        # Keep local file mirror when using env file path
        file_path = os.getenv("HIGGSFIELD_CREDENTIALS_FILE", "").strip()
        if file_path:
            Path(file_path).expanduser().write_text(
                json.dumps(fresh, indent=2) + "\n", encoding="utf-8"
            )
        persist_credentials_to_secrets_manager(fresh)
        creds = fresh

    return {
        "ok": True,
        "workspace_id": workspace_id,
        "account": status,
        "expires_at": creds.get("expires_at"),
        "auth_version": creds.get("auth_version"),
    }


def list_avatars(size: int = 100, custom_only: bool = False) -> list[dict[str, Any]]:
    ensure_workspace()
    out = _run(
        [
            which_higgsfield(),
            "marketing-studio",
            "avatars",
            "list",
            "--json",
            "--size",
            str(size),
        ]
    )
    items = json.loads(out)
    if not isinstance(items, list):
        items = items.get("items") or items.get("data") or []
    if custom_only:
        items = [a for a in items if a.get("type") == "custom"]
    return items


def list_products(limit: int = 50) -> list[dict[str, Any]]:
    ensure_workspace()
    out = _run(
        [
            which_higgsfield(),
            "marketing-studio",
            "products",
            "list",
            "--json",
            "--limit",
            str(limit),
        ]
    )
    items = json.loads(out)
    if not isinstance(items, list):
        items = items.get("items") or items.get("data") or []
    return items
