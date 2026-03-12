from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cassandra.chat_engine import ChatEngine

engine = ChatEngine()

HTML_PAGE = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cassandra Web Chat</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    .wrap { max-width: 900px; margin: 24px auto; padding: 0 16px; }
    .card { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px; }
    h1 { margin-top: 0; font-size: 20px; }
    #history { height: 60vh; overflow: auto; padding: 12px; background: #030712; border-radius: 10px; }
    .msg { margin: 10px 0; line-height: 1.4; }
    .user { color: #93c5fd; }
    .assistant { color: #86efac; }
    .timer { color: #fcd34d; }
    .meta { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
    .row { display: flex; gap: 8px; margin-top: 12px; }
    input[type=text] { flex: 1; padding: 10px; border-radius: 8px; border: 1px solid #374151; background: #0b1220; color: #fff; }
    button { padding: 10px 14px; border: none; border-radius: 8px; cursor: pointer; background: #2563eb; color: white; }
    button.secondary { background: #475569; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Cassandra - Chat Web</h1>
      <div id="history"></div>
      <div class="row">
        <input id="message" type="text" placeholder="Digite sua mensagem..." />
        <button id="send">Enviar</button>
        <button id="newSession" class="secondary">Nova conversa</button>
      </div>
    </div>
  </div>

  <script>
    const historyEl = document.getElementById("history");
    const messageEl = document.getElementById("message");
    const sendEl = document.getElementById("send");
    const newSessionEl = document.getElementById("newSession");

    let sessionId = localStorage.getItem("cassandra_session_id");

    function escapeHtml(text) {
      return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }

    function render(items) {
      historyEl.innerHTML = "";
      for (const item of items) {
        const roleClass = item.kind === "timer" ? "timer" : item.role;
        const roleLabel = item.kind === "timer" ? "timer" : item.role;
        const html = `
          <div class="msg ${roleClass}">
            <div class="meta">${item.timestamp} - ${roleLabel}</div>
            <div>${escapeHtml(item.content)}</div>
          </div>
        `;
        historyEl.insertAdjacentHTML("beforeend", html);
      }
      historyEl.scrollTop = historyEl.scrollHeight;
    }

    async function ensureSession() {
      if (sessionId) return sessionId;
      const res = await fetch("/api/session", { method: "POST" });
      const data = await res.json();
      sessionId = data.session_id;
      localStorage.setItem("cassandra_session_id", sessionId);
      return sessionId;
    }

    async function refreshHistory() {
      const sid = await ensureSession();
      const res = await fetch(`/api/history?session_id=${encodeURIComponent(sid)}`);
      const data = await res.json();
      render(data.history || []);
    }

    async function sendMessage() {
      const text = messageEl.value.trim();
      if (!text) return;
      messageEl.value = "";
      const sid = await ensureSession();
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, message: text })
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Erro ao enviar mensagem.");
        return;
      }
      render(data.history || []);
    }

    sendEl.addEventListener("click", sendMessage);
    messageEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendMessage();
    });
    newSessionEl.addEventListener("click", async () => {
      sessionId = null;
      localStorage.removeItem("cassandra_session_id");
      await refreshHistory();
    });

    refreshHistory();
  </script>
</body>
</html>
"""


class CassandraWebHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML_PAGE)
            return

        if parsed.path == "/api/history":
            query = parse_qs(parsed.query)
            session_id = (query.get("session_id") or [""])[0]
            try:
                history = engine.get_history(session_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"session_id": session_id, "history": history})
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/session":
            session_id = engine.create_session()
            self._send_json({"session_id": session_id, "history": []})
            return

        if parsed.path == "/api/chat":
            data = self._read_json_body()
            session_id = str(data.get("session_id", "")).strip()
            message = str(data.get("message", "")).strip()
            try:
                response = engine.chat(session_id=session_id, message=message)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"Internal error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(response)
            return

        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), CassandraWebHandler)
    print(f"Web chat running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
