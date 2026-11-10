"""The local web server behind `jobapply panel`.

Safety: it listens on 127.0.0.1 only. Every POST, and every call the page makes to /api, must carry this run's
random token (the API wants it in a header no other website can set). The Host header must be ours (defeats DNS
rebinding) and an Origin header, if there is one, must be ours too. Scripts and styles load only from this server.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from ..config import Paths
from . import panel_page
from .actions import ActionError
from .app import UiApp
from .forms import ADD_SKILL, AI_FILL, MAX_UPLOAD_BYTES, parse_multipart
from .markdown import parse_markdown
from .panel import Panel
from .runner import Busy

DEFAULT_PORT = 8765
ENVELOPE_BYTES = 64 * 1024  # room for form fields around an upload
MAX_JSON_BYTES = 8 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).with_name("static")
STATIC_TYPES = {"theme.css": "text/css; charset=utf-8", "panel.js": "text/javascript; charset=utf-8"}
TOKEN_HEADER = "X-Token"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
}


def make_handler(app: UiApp, panel: Panel):
    class Handler(BaseHTTPRequestHandler):
        server_version = "JobApplyPanel"

        def log_message(self, *args) -> None:  # keep the console quiet
            pass

        # -- answering -----------------------------------------------------------------------
        def _finish(self, status: int, data: bytes = b"", content_type: str = "text/html; charset=utf-8",
                    location: str = "") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if location:
                self.send_header("Location", location)
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def _html(self, body: str, status: int = 200) -> None:
            self._finish(status, body.encode("utf-8"))

        def _text(self, status: int, message: str) -> None:
            self._finish(status, message.encode("utf-8"), "text/plain; charset=utf-8")

        def _redirect(self, location: str) -> None:
            self._finish(303, location=location)

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            self._finish(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        # -- who is asking -------------------------------------------------------------------
        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in app.allowed_hosts

        def _api_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            origin_ok = origin is None or origin in {f"http://{host}" for host in app.allowed_hosts}
            return self._host_ok() and origin_ok and app.token_ok(self.headers.get(TOKEN_HEADER))

        # -- reading the request -------------------------------------------------------------
        def _read_body(self, limit: int) -> Optional[bytes]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if not 0 <= length <= limit:
                return None
            return self.rfile.read(length)

        @staticmethod
        def _urlencoded(body: bytes) -> Dict[str, str]:
            return {key: values[0] for key, values in
                    parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}

        # -- GET -----------------------------------------------------------------------------
        def do_GET(self) -> None:
            if not self._host_ok():
                return self._text(403, "Forbidden")
            parsed = urlparse(self.path)
            route = parsed.path
            if route.startswith("/api/"):
                return self._api("GET", route, parse_qs(parsed.query), {})
            if route.startswith("/static/"):
                return self._static(route[len("/static/"):])
            if route == "/":
                return self._html(panel_page.render(app.token))
            if route == "/profile":
                return self._html(app.upload_html())
            if route == "/form":
                return self._html(app.form_html()) if app.has_resume() else self._redirect("/profile")
            if route == "/done":
                return self._html(app.done_html()) if app.saved_profile() else self._redirect("/profile")
            if route == "/ai":
                query = parse_qs(parsed.query)
                banner = ("ok", "Saved.") if "saved" in query else ("", "")
                if "added" in query:
                    banner = ("ok", "Added. Now choose it as your main AI, or as a backup, and press Save.")
                return self._html(app.ai_html(banner=banner))
            if route == "/questions":
                query = parse_qs(parsed.query)
                saved = query.get("saved", [""])[0]
                banner = ("ok", f"Saved {saved} answer{'' if saved == '1' else 's'}.") if saved.isdigit() and int(saved) else ("", "")
                if "forgot" in query:
                    banner = ("ok", "Removed that saved answer.")
                if "edited" in query:
                    banner = ("ok", "Saved your change.")
                return self._html(app.questions_html(banner, saved_open="forgot" in query or "edited" in query))
            self._text(404, "Not found")

        def _static(self, name: str) -> None:
            content_type = STATIC_TYPES.get(name)  # only these two names: nothing typed is ever joined to a path
            if content_type is None:
                return self._text(404, "Not found")
            self._finish(200, (STATIC_DIR / name).read_bytes(), content_type)

        # -- POST ----------------------------------------------------------------------------
        def do_POST(self) -> None:
            if not self._host_ok():
                return self._text(403, "Forbidden")
            route = urlparse(self.path).path
            if route.startswith("/api/"):
                return self._api_post(route)
            body = self._read_body(MAX_UPLOAD_BYTES + ENVELOPE_BYTES)
            if body is None:
                return self._text(413, "That upload is too large.")
            if route == "/resume":
                return self._post_resume(body)
            if route == "/save":
                return self._post_save(body)
            if route == "/ai/save":
                return self._post_ai_save(body)
            if route == "/ai/test":
                return self._post_ai_test(body)
            if route == "/ai/remove":
                return self._post_ai_remove(body)
            if route == "/ai/provider":
                return self._post_ai_provider(body)
            if route == "/ai/provider/remove":
                return self._post_ai_provider_remove(body)
            if route == "/questions/save":
                return self._post_questions(body)
            if route == "/questions/forget":
                return self._post_forget(body)
            if route == "/questions/edit":
                return self._post_edit(body)
            self._text(404, "Not found")

        def _post_questions(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            self._redirect(f"/questions?saved={app.accept_answers(raw)}")

        def _post_forget(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            self._redirect("/questions?forgot=1" if app.forget_answer(raw.get("question", "")) else "/questions")

        def _post_edit(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            changed = app.change_answer(raw.get("question", ""), raw.get("answer", ""))
            self._redirect("/questions?edited=1" if changed else "/questions")

        def _post_resume(self, body: bytes) -> None:
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
            if not app.token_ok(fields.get("token")):
                return self._text(403, "Forbidden")
            filename, data = files.get("resume", ("", b""))
            error = app.accept_resume(filename, data)
            if error:
                return self._html(app.upload_html(error), 400)
            self._redirect("/form")

        def _post_save(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            if not app.has_resume():
                return self._redirect("/profile")
            if ADD_SKILL in raw:  # the "Add another skill" button: show the form again with a new row, save nothing
                return self._html(app.form_with_another_skill(raw))
            if AI_FILL in raw:  # the "AI Fill" button: the AI's suggestions in the empty boxes, save nothing
                return self._html(app.form_with_ai(raw))
            retry = app.accept_form(raw)
            if retry is not None:
                return self._html(retry, 400)
            self._redirect("/done")

        def _post_ai_save(self, body: bytes) -> None:
            fields, files = parse_multipart(self.headers.get("Content-Type", ""), body)
            if not app.token_ok(fields.get("token")):
                return self._text(403, "Forbidden")
            retry = app.accept_ai(fields, files)
            if retry is not None:
                return self._html(retry, 400)
            self._redirect("/ai?saved=1")

        def _post_ai_test(self, body: bytes) -> None:
            if not app.token_ok(self._urlencoded(body).get("token")):
                return self._text(403, "Forbidden")
            self._html(app.ai_html(banner=app.test_ai()))

        def _post_ai_remove(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            app.remove_about(raw.get("name", ""))
            self._redirect("/ai")

        def _post_ai_provider(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            retry = app.add_provider(raw)
            if retry is not None:
                return self._html(retry, 400)
            self._redirect("/ai?added=1")

        def _post_ai_provider_remove(self, body: bytes) -> None:
            raw = self._urlencoded(body)
            if not app.token_ok(raw.get("token")):
                return self._text(403, "Forbidden")
            self._html(app.ai_html(banner=app.remove_provider(raw.get("id", ""))))

        # -- the page's own calls ------------------------------------------------------------
        def _api_post(self, route: str) -> None:
            if not self._api_allowed():
                return self._json(403, {"error": "Forbidden"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "Send JSON."})
            raw = self._read_body(MAX_JSON_BYTES)
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = None
            if not isinstance(body, dict):
                return self._json(400, {"error": "That request was not understood."})
            self._api("POST", route, {}, body)

        def _api(self, method: str, route: str, query: Dict[str, list], body: Dict[str, Any]) -> None:
            if not self._api_allowed():
                return self._json(403, {"error": "Forbidden"})
            try:
                if (method, route) == ("GET", "/api/state"):
                    return self._json(200, panel.state(_whole(query.get("since", ["0"])[0])))
                if (method, route) == ("GET", "/api/report"):
                    return self._json(200, {"blocks": parse_markdown(panel.report(query.get("name", [""])[0]))})
                if (method, route) == ("POST", "/api/report/delete"):
                    return self._json(200, panel.delete_report(body.get("name")))
                if (method, route) == ("POST", "/api/erase"):
                    return self._json(200, panel.erase(body))
                if (method, route) == ("POST", "/api/run"):
                    return self._json(202, panel.run(body))
                if (method, route) == ("POST", "/api/stop"):
                    return self._json(200, {"stopped": panel.stop()})
                if (method, route) == ("POST", "/api/open"):
                    return self._json(200, panel.open_folder(body.get("target")))
                if (method, route) == ("POST", "/api/quit"):
                    return self._quit()
            except ActionError as exc:
                return self._json(400, {"error": str(exc)})
            except Busy as exc:
                return self._json(409, {"error": f"{exc} Stop it first, or wait for it to finish."})
            self._json(404, {"error": "Not found"})

        def _quit(self) -> None:
            if panel.runner.busy:
                return self._json(409, {"error": "A run is in progress. Stop it first."})
            self._json(200, {"bye": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()  # not from this thread: it would wait for itself

    return Handler


def _whole(text: str) -> int:
    return int(text) if text.isdigit() else 0


def build_server(paths: Paths, port: int = DEFAULT_PORT, root: Path = PROJECT_ROOT,
                 panel: Optional[Panel] = None) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 (the preferred port, else any free one). The pages' logic is on `server.app`, the buttons' on `server.panel`."""
    paths.ensure()
    app = UiApp(paths)
    panel = panel or Panel(paths, root)
    handler = make_handler(app, panel)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:  # that port is taken: let the system pick one
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    bound = server.server_address[1]
    app.allowed_hosts = {f"127.0.0.1:{bound}", f"localhost:{bound}"}
    server.app, server.panel = app, panel  # type: ignore[attr-defined]
    return server


def serve(paths: Paths, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    server = build_server(paths, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    # flush: when output goes through a pipe (a wrapper, an IDE terminal) Python would otherwise hold these lines back
    print(f"The control panel is open at {url}", flush=True)
    print("Leave this window open while you use it. Close it, or press Ctrl+C here, to quit.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.panel.runner.shutdown()  # type: ignore[attr-defined]
        server.server_close()
