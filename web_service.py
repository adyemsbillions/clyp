from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_from_directory

from video_service import video

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")

app = Flask(__name__, static_folder=None)
app.register_blueprint(video)
AI_ENDPOINT = os.getenv("CLYP_AI_ENDPOINT", "http://127.0.0.1:8100").rstrip("/")
INTERNAL_TOKEN = os.getenv("CLYP_AI_INTERNAL_TOKEN", "change-me")
APP_URL = os.getenv("CLYP_APP_URL", "http://127.0.0.1:8080")
OPENVERSE = "https://api.openverse.org/v1/images/"
UA = "Clyp-Local-Design-Studio/4.0"


def proxy_ai(route: str, timeout: int = 180):
    payload = request.get_data() or b"{}"
    req = urllib.request.Request(
        f"{AI_ENDPOINT}/{route}",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Internal-Token": INTERNAL_TOKEN,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return Response(body, status=response.status, content_type="application/json")
    except urllib.error.HTTPError as exc:
        body = exc.read() or json.dumps({"ok": False, "message": str(exc)}).encode()
        return Response(body, status=exc.code, content_type="application/json")
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Python AI service unavailable: {exc}"}), 502


@app.post("/api/ai/generate")
def ai_generate():
    return proxy_ai("generate")


@app.post("/api/ai/edit")
def ai_edit():
    return proxy_ai("edit")


@app.post("/api/ai/reconstruct")
def ai_reconstruct():
    return proxy_ai("reconstruct")


@app.post("/api/ai/image-generate")
def ai_image_generate():
    return proxy_ai("image-generate", timeout=180)


@app.get("/api/ai/health")
def ai_health():
    req = urllib.request.Request(f"{AI_ENDPOINT}/health", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return Response(response.read(), status=response.status, content_type="application/json")
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502


def public_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
            return False
        # Resolve and reject private/link-local/loopback destinations to avoid turning the
        # local development proxy into an SSRF helper.
        for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False

def basic_remote_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}
    except Exception:
        return False


@app.get("/api/assets/search")
def asset_search():
    q = (request.args.get("q") or "").strip()[:180]
    if len(q) < 2:
        return jsonify({"ok": False, "message": "Type at least two characters to search."}), 422
    params = urllib.parse.urlencode({"q": q, "page_size": 18})
    req = urllib.request.Request(f"{OPENVERSE}?{params}", headers={"Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Online image search unavailable: {exc}"}), 502
    results = []
    for item in data.get("results") or []:
        if item.get("mature"):
            continue
        original = str(item.get("url") or "")
        thumb = str(item.get("thumbnail") or "")
        if not (basic_remote_url(original) or basic_remote_url(thumb)):
            continue
        results.append({
            "id": item.get("id"),
            "title": item.get("title") or "Untitled image",
            "creator": item.get("creator") or "Unknown creator",
            "license": item.get("license") or "",
            "license_url": item.get("license_url") or "",
            "attribution": item.get("attribution") or "",
            "landing_url": item.get("foreign_landing_url") or item.get("detail_url") or "",
            "url": original or thumb,
            "thumbnail": thumb or original,
            "width": item.get("width") or 0,
            "height": item.get("height") or 0,
        })
    return jsonify({"ok": True, "provider": "Openverse", "results": results})


@app.get("/api/assets/fetch")
def asset_fetch():
    url = (request.args.get("url") or "").strip()
    if not public_http_url(url):
        return jsonify({"ok": False, "message": "That image URL is not allowed."}), 400
    req = urllib.request.Request(url, headers={"Accept": "image/*", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                return jsonify({"ok": False, "message": "Remote resource is not an image."}), 415
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                return jsonify({"ok": False, "message": "Online image is larger than 8 MB."}), 413
            return Response(body, content_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Could not load online image: {exc}"}), 502


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "clyp-web", "storage": "browser-local", "auth": False, "mysql": False, "online_assets": "Openverse", "video_editor": True})


@app.get("/")
def root():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    target = (ROOT / path).resolve()
    if ROOT.resolve() not in target.parents and target != ROOT.resolve():
        return "Not found", 404
    if target.is_file():
        return send_from_directory(ROOT, path)
    return "Not found", 404


if __name__ == "__main__":
    parsed = urlparse(APP_URL if "://" in APP_URL else f"http://{APP_URL}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
