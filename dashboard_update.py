"""Pull a newer Silvia dashboard from this family's publisher.

The publisher serves the program files that are on disk. A dashboard shows
Update when those files differ. Applying the update replaces program files
under this dashboard folder only.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_MANIFEST_URL = "http://100.83.70.107:8874/dashboard-update/manifest.json"
PI_FUNNEL_MANIFEST_URL = (
    "https://symbiosis-relay.tail69d8db.ts.net/family-installer/dashboard-update/manifest.json"
)
PI_UPDATE_HOSTS = {"100.83.70.107", "symbiosis-relay", "symbiosis-relay.tail69d8db.ts.net"}
# A running dashboard looks again on this beat, so an update shows without a restart.
CHECK_INTERVAL_MS = 30_000
PUBLISHER_HOST = "DESKTOP-AQOETJB"
PUBLISHER_HOME = Path(r"C:\Users\Irika\.grok")
PROTECTED = {"documents", "downloads", "pictures", "videos"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", "state", "imagine-drafts"}
SKIP_NAMES = {"update-source.json", "update-applied.json", "auth.json"}


def is_publisher() -> bool:
    """True only on the computer that serves the dashboard files."""
    host = os.environ.get("COMPUTERNAME", "").strip().upper()
    if host != PUBLISHER_HOST:
        return False
    try:
        return (Path.home() / ".grok").resolve() == PUBLISHER_HOME.resolve()
    except OSError:
        return False


def allowed_rel(rel: str) -> bool:
    """A program file path. Rejects escapes, state, and sign-in files."""
    text = str(rel or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ":" in text:
        return False
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if any(part.casefold() in SKIP_PARTS for part in parts):
        return False
    name = parts[-1]
    if name.casefold() in SKIP_NAMES:
        return False
    if name.casefold() == "silvia.ico":
        return len(parts) == 1
    return name.lower().endswith(".py")


def _protected(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    parts = {part.casefold() for part in resolved.parts}
    if parts & PROTECTED:
        return True
    return resolved.name.casefold() == "auth.json"


def build_manifest(root: Path) -> dict[str, Any]:
    """Hashes of the program files under root."""
    base = Path(root)
    files: list[dict[str, Any]] = []
    if base.is_dir():
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if not allowed_rel(rel):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            files.append(
                {
                    "path": rel,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
    version = hashlib.sha256(
        "\n".join(f"{item['path']} {item['sha256']}" for item in files).encode("utf-8")
    ).hexdigest()
    return {"ok": True, "product": "silvia-dashboard", "version": version, "files": files}


def compare_manifests(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    """Files the remote copy has that this folder does not."""
    remote_files = {
        str(item.get("path") or ""): item
        for item in (remote.get("files") or [])
        if allowed_rel(str(item.get("path") or ""))
    }
    local_files = {str(item.get("path") or ""): item for item in (local.get("files") or [])}
    changed: list[str] = []
    for path in sorted(remote_files):
        have = local_files.get(path)
        if have is None or have.get("sha256") != remote_files[path].get("sha256"):
            changed.append(path)
    return {
        "available": bool(changed),
        "files": changed,
        "remote_version": str(remote.get("version") or ""),
        "local_version": str(local.get("version") or ""),
    }


def _allowed_manifest_url(url: str) -> bool:
    text = str(url or "").strip()
    if text.startswith("https://"):
        return True
    parsed = urllib.parse.urlparse(text)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", *PI_UPDATE_HOSTS}


def _saved_manifest_url(root: Path) -> str:
    path = Path(root) / "update-source.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    custom = str(data.get("manifest_url") or "").strip()
    if _allowed_manifest_url(custom):
        return custom
    return ""


def candidate_urls(root: Path) -> list[str]:
    """Every update address this version knows. A dead saved address is not the only try."""
    ordered = [DEFAULT_MANIFEST_URL, PI_FUNNEL_MANIFEST_URL, _saved_manifest_url(root)]
    seen: set[str] = set()
    urls: list[str] = []
    for url in ordered:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def load_source(root: Path) -> dict[str, str]:
    """Where this dashboard looks for an update."""
    urls = candidate_urls(root)
    role = "publisher" if is_publisher() else "client"
    return {"role": role, "manifest_url": urls[0] if urls else DEFAULT_MANIFEST_URL}


def file_url(manifest_url: str, rel: str) -> str:
    base = str(manifest_url).rsplit("/", 1)[0]
    return base + "/file/" + urllib.parse.quote(rel, safe="/")


def fetch_bytes(url: str, timeout: float = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "silvia-dashboard-update"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def check_for_update(root: Path, *, timeout: float = 5) -> dict[str, Any]:
    """Ask each known update address whether its program files differ."""
    if is_publisher():
        return {"available": False, "reason": "publisher", "files": []}
    last_error = "no update server answered"
    local = build_manifest(root)
    for url in candidate_urls(root):
        try:
            remote = json.loads(fetch_bytes(url, timeout=timeout).decode("utf-8"))
        except (OSError, json.JSONDecodeError, urllib.error.URLError, ValueError) as exc:
            last_error = str(exc)
            continue
        diff = compare_manifests(local, remote)
        diff["manifest_url"] = url
        diff["reason"] = ""
        return diff
    return {"available": False, "reason": last_error, "files": []}


def apply_update(root: Path, remote: dict[str, Any], fetch: Callable[[str], bytes]) -> dict[str, Any]:
    """Replace the program files that differ. Leave user folders and auth.json alone."""
    if is_publisher():
        return {"ok": False, "reason": "this computer publishes the dashboard", "files": []}
    base = Path(root).resolve()
    if _protected(base):
        return {"ok": False, "reason": "refused path", "files": []}
    diff = compare_manifests(build_manifest(base), remote)
    if not diff["available"]:
        return {"ok": True, "available": False, "files": [], "version": diff["remote_version"]}
    remote_files = {
        str(item.get("path") or ""): item for item in (remote.get("files") or [])
    }
    staged: list[tuple[Path, bytes, str]] = []
    for rel in diff["files"]:
        if not allowed_rel(rel):
            return {"ok": False, "reason": "refused path", "path": rel, "files": []}
        dest = (base / rel).resolve()
        if _protected(dest) or not dest.is_relative_to(base):
            return {"ok": False, "reason": "refused path", "path": rel, "files": []}
        item = remote_files.get(rel) or {}
        try:
            data = bytes(fetch(rel))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return {"ok": False, "reason": str(exc), "path": rel, "files": []}
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.get("sha256"):
            return {"ok": False, "reason": "hash mismatch", "path": rel, "files": []}
        staged.append((dest, data, rel))
    written: list[str] = []
    for dest, data, rel in staged:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_name(dest.name + ".update-tmp")
            temporary.write_bytes(data)
            temporary.replace(dest)
        except OSError as exc:
            return {"ok": False, "reason": str(exc), "path": rel, "files": written}
        written.append(rel)
    record = {
        "version": diff["remote_version"],
        "files": written,
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        (base / "update-applied.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "available": True, "files": written, "version": diff["remote_version"]}


def apply_available(root: Path) -> dict[str, Any]:
    """Download the current manifest and apply it."""
    if is_publisher():
        return {"ok": False, "reason": "this computer publishes the dashboard", "files": []}
    found = check_for_update(root, timeout=8)
    url = str(found.get("manifest_url") or "")
    if not found.get("available") or not url:
        return {"ok": False, "reason": str(found.get("reason") or "no update"), "files": []}
    try:
        remote = json.loads(fetch_bytes(url, timeout=8).decode("utf-8"))
    except (OSError, json.JSONDecodeError, urllib.error.URLError, ValueError) as exc:
        return {"ok": False, "reason": str(exc), "files": []}

    def fetch(rel: str) -> bytes:
        return fetch_bytes(file_url(url, rel), timeout=30)

    return apply_update(root, remote, fetch)


def schedule_restart(root: Path) -> dict[str, Any]:
    """Start this dashboard again after this process has exited."""
    pythonw = Path(sys.executable)
    if pythonw.name.lower() in {"python.exe", "py.exe"}:
        sibling = pythonw.with_name("pythonw.exe")
        if sibling.is_file():
            pythonw = sibling
    script = Path(root) / "__main__.py"
    if not script.is_file() or not pythonw.is_file():
        return {"ok": False, "reason": "restart program missing"}
    code = (
        "import sys, time, ctypes, subprocess\n"
        "pid = int(sys.argv[1])\n"
        "kernel = ctypes.WinDLL('kernel32')\n"
        "kernel.OpenProcess.restype = ctypes.c_void_p\n"
        "handle = kernel.OpenProcess(0x00100000, False, pid)\n"
        "if handle:\n"
        "    kernel.WaitForSingleObject(handle, 15000)\n"
        "    kernel.CloseHandle(handle)\n"
        "else:\n"
        "    time.sleep(1)\n"
        "subprocess.Popen([sys.argv[2], '-u', sys.argv[3], 'launch'], cwd=sys.argv[4], "
        "creationflags=0x00000008 | 0x00000200 | 0x08000000, close_fds=True)\n"
    )
    flags = 0x00000008 | 0x00000200 | 0x08000000
    proc = subprocess.Popen(
        [str(pythonw), "-c", code, str(os.getpid()), str(pythonw), str(script), str(root)],
        creationflags=flags,
        close_fds=True,
    )
    return {"ok": True, "pid": proc.pid}
