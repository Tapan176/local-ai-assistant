"""Local-machine skills (files, launching apps). Disabled automatically when hosted (environment != local)."""

from __future__ import annotations

import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.agent.skill import SkillContext, SkillRegistry, schema

MAX_READ_BYTES = 100_000
MAX_WRITE_BYTES = 200_000


def workspace_root(ctx: SkillContext) -> Path:
    root = Path(ctx.settings.workspace_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(ctx: SkillContext, relative: str) -> Path:
    """Resolve ``relative`` inside the workspace sandbox; raise if it escapes (.., absolute paths, symlinks)."""
    root = workspace_root(ctx)
    target = (root / relative).resolve()
    if target != root and not target.is_relative_to(root):
        raise PermissionError(f"Path '{relative}' is outside the workspace folder ({root}).")
    return target


async def list_files(ctx: SkillContext, args: dict[str, Any]) -> Any:
    target = safe_path(ctx, str(args.get("path") or "."))
    if not target.is_dir():
        return f"'{args.get('path', '.')}' is not a folder."
    root = workspace_root(ctx)
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:200]
    listing = [
        {
            "path": str(p.relative_to(root)).replace("\\", "/"),
            "type": "file" if p.is_file() else "folder",
            "bytes": p.stat().st_size if p.is_file() else None,
        }
        for p in entries
    ]
    return listing or "Folder is empty."


async def read_file(ctx: SkillContext, args: dict[str, Any]) -> str:
    target = safe_path(ctx, str(args["path"]))
    if not target.is_file():
        return f"No such file: {args['path']}"
    return target.read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")


async def write_file(ctx: SkillContext, args: dict[str, Any]) -> str:
    target = safe_path(ctx, str(args["path"]))
    content = str(args["content"])
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return "Content too large (limit 200 KB)."
    mode = str(args.get("mode") or "create")
    if mode not in {"create", "append", "overwrite"}:
        return "mode must be create, append or overwrite."
    if mode == "create" and target.exists():
        return f"{args['path']} already exists. Use mode='append' or mode='overwrite' (confirm with the user first)."
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a" if mode == "append" else "w", encoding="utf-8") as fh:
        fh.write(content)
    return f"Wrote {args['path']} ({mode})."


async def open_url(ctx: SkillContext, args: dict[str, Any]) -> str:
    url = str(args["url"]).strip()
    if urlparse(url).scheme not in {"http", "https"}:
        return "Only http(s) links can be opened."
    webbrowser.open(url)
    return f"Opened {url} in the default browser."


async def open_app(ctx: SkillContext, args: dict[str, Any]) -> str:
    name = str(args["name"]).strip().lower()
    allow = {k.lower(): v for k, v in ctx.settings.app_allowlist.items()}
    if name not in allow:
        return f"'{name}' is not allowed. Allowed apps: {', '.join(sorted(allow))} (extend with TAPAN_APP_ALLOWLIST)."
    exe = shutil.which(allow[name]) or allow[name]
    try:
        subprocess.Popen([exe], close_fds=True)  # list form, no shell: the model cannot inject arguments
    except OSError as exc:
        return f"Couldn't launch {name}: {exc}"
    return f"Launched {name}."


async def system_info(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    usage = shutil.disk_usage(Path.cwd())
    info: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "disk_free_gb": round(usage.free / 1e9, 1),
        "disk_total_gb": round(usage.total / 1e9, 1),
    }
    try:
        import psutil  # optional

        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        info["memory_used_percent"] = psutil.virtual_memory().percent
        battery = psutil.sensors_battery()
        if battery:
            info["battery_percent"] = round(battery.percent)
    except ImportError:
        pass
    return info


def register(registry: SkillRegistry) -> None:
    registry.add(
        "list_files",
        "List files in the workspace folder (sandboxed).",
        schema({"path": {"type": "string", "description": "Relative folder, default '.'"}}),
        list_files,
        local_only=True,
    )
    registry.add(
        "read_file",
        "Read a text file from the workspace folder (sandboxed, first 100 KB).",
        schema({"path": {"type": "string"}}, ["path"]),
        read_file,
        local_only=True,
    )
    registry.add(
        "write_file",
        "Create or edit a text file in the workspace folder. Refuses to replace existing files unless mode='overwrite'.",
        schema(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["create", "append", "overwrite"]},
            },
            ["path", "content"],
        ),
        write_file,
        local_only=True,
    )
    registry.add(
        "open_url", "Open a link in the user's default browser.", schema({"url": {"type": "string"}}, ["url"]),
        open_url, local_only=True,
    )
    registry.add(
        "open_app", "Launch an allow-listed desktop application.", schema({"name": {"type": "string"}}, ["name"]),
        open_app, local_only=True,
    )
    registry.add(
        "system_info",
        "Report OS, disk, and (if available) CPU/memory/battery status of this machine.",
        schema(),
        system_info,
        local_only=True,
    )
