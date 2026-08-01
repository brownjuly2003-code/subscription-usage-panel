"""Local live dashboard server: HTML + JSON API with auto-refresh."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from panel.config import AppConfig
from panel.fetch import fetch_all
from panel.history import append_snapshot, attach_history
from panel.html_dash import render_dashboard_html, write_dashboard
from panel.schema import build_payload

# Written on each refresh so file://dashboard.html is not weeks old after serve ran.
DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "dashboard.html"


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.payload: dict[str, Any] = {}
        self.results = []
        self.wall_ms = 0.0
        self.cfg: AppConfig | None = None
        self.updated_at = 0.0
        self.host: str = "127.0.0.1"
        self.port: int = 8765


STATE = State()


def refresh(cfg: AppConfig) -> None:
    results, wall = fetch_all(cfg)
    payload = build_payload(
        results,
        wall,
        meta={"mode": "serve", "auto_discover": cfg.auto_discover},
    )
    append_snapshot(payload.get("profiles") or [])
    attach_history(payload)
    with STATE.lock:
        STATE.results = results
        STATE.wall_ms = wall
        STATE.payload = payload
        STATE.cfg = cfg
        STATE.updated_at = time.time()
    # Keep on-disk snapshot in sync (people often open the file, not the URL).
    try:
        write_dashboard(
            results,
            wall,
            DASHBOARD_PATH,
            theme=cfg.theme,
            live_hint_port=STATE.port,
            payload=payload,
        )
    except Exception:
        pass


def _bg_loop(cfg: AppConfig, interval: int, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            refresh(cfg)
        except Exception:
            pass
        stop.wait(interval)


class Handler(BaseHTTPRequestHandler):
    server_version = "SubscriptionUsagePanel/1.0"

    def log_message(self, fmt: str, *args) -> None:
        # quieter
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Allow file://dashboard.html to detect live server and redirect.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        qs = parse_qs(parsed.query)

        if path in ("/", "/dashboard", "/dashboard.html", "/index.html"):
            with STATE.lock:
                results = list(STATE.results)
                wall = STATE.wall_ms
                cfg = STATE.cfg
                payload = dict(STATE.payload) if STATE.payload else None
                theme = (cfg.theme if cfg else "dark")
                if qs.get("theme"):
                    theme = qs["theme"][0]
            # live page embeds poll interval; pass payload to avoid re-snapshot
            html = render_dashboard_html(
                results,
                wall,
                theme=theme,
                live=True,
                poll_seconds=max(15, int((cfg.interval if cfg else 60))),
                payload=payload,
                live_port=STATE.port,
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path in ("/api/usage", "/api/v1/usage", "/usage"):
            with STATE.lock:
                payload = dict(STATE.payload)
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        if path == "/api/health":
            with STATE.lock:
                age = time.time() - STATE.updated_at if STATE.updated_at else None
            from panel.schema import SCHEMA_VERSION

            body = json.dumps(
                {
                    "ok": True,
                    "age_s": age,
                    "schemaVersion": SCHEMA_VERSION,
                    "url": f"http://{STATE.host}:{STATE.port}/",
                }
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return

        if path == "/api/refresh":
            if STATE.cfg:
                refresh(STATE.cfg)
            with STATE.lock:
                payload = dict(STATE.payload)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        self._send(404, b'{"error":"not found"}', "application/json")


def payload_schema() -> str:
    from panel.schema import SCHEMA_VERSION

    return SCHEMA_VERSION


def serve(
    cfg: AppConfig,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    STATE.host = host
    STATE.port = port
    refresh(cfg)
    stop = threading.Event()
    t = threading.Thread(
        target=_bg_loop, args=(cfg, max(15, cfg.interval), stop), daemon=True
    )
    t.start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Serving live dashboard at {url}")
    print(f"JSON API: {url}api/usage")
    print(f"Also wrote snapshot: {DASHBOARD_PATH}")
    print("Open the URL above (not the .html file) for auto-refresh.")
    print("Ctrl+C to stop")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        stop.set()
        httpd.shutdown()
