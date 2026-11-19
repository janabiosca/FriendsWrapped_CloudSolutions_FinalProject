"""Private, read-only dashboard preview. Binds only to this Mac; never exposes AWS keys."""
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("TABLE_NAME", "sfw-dev")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
from demo_weekly_ranking import demo_weekly_ranking
from show_group_stats import weekly_from_store
import listening_stats
import store

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765"):
            self.send_error(403)
            return
        route = urlparse(self.path)
        if route.path == "/":
            body = (ROOT / "web/index.html").read_bytes()
            content_type = "text/html; charset=utf-8"
        elif route.path == "/api/demo-weekly-ranking":
            body = json.dumps(demo_weekly_ranking(), ensure_ascii=False).encode()
            content_type = "application/json; charset=utf-8"
        elif route.path == "/api/group-weekly":
            try:
                today = dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
                monday = today - dt.timedelta(days=today.weekday())
                result = weekly_from_store(os.environ.get("GROUP_ID", "friends"), monday)
                body = json.dumps(result, ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            except Exception:
                self.send_error(503, "Group statistics unavailable")
                return
        elif route.path == "/api/stats":
            period = parse_qs(route.query).get("period", ["all"])[0]
            if period not in ("all", "today", "7d"):
                self.send_error(400)
                return
            try:
                now = dt.datetime.now(ZoneInfo("Europe/Madrid"))
                start = "0000"
                if period != "all":
                    beginning = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    if period == "7d":
                        beginning -= dt.timedelta(days=6)
                    start = beginning.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                end = now.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                profile = store.get_profile("jana") or {}
                result = listening_stats.summarize(store.plays_between("jana", start, end))
                result.update(display_name=profile.get("display_name", "Jana"),
                    last_sync_at=profile.get("last_sync_at"),
                    last_sync_status=profile.get("last_sync_status"),
                    possible_gaps=int(profile.get("possible_gaps", 0)), period=period)
                body = json.dumps(result, ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            except Exception:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b'{"error":"No se han podido consultar los datos. Comprueba la sesion de AWS Academy."}')
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    print("Vista privada: http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
