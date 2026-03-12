from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Type
from urllib.parse import urlparse

from cassandra.assistant import CassandraAssistant

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
        <input id="message" type="text" placeholder="Digite: cassandra, ... para ativar" />
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

    async function refreshHistory() {
      const res = await fetch("/api/history");
      const data = await res.json();
      render(data.history || []);
    }

    async function sendMessage() {
      const text = messageEl.value.trim();
      if (!text) return;
      messageEl.value = "";
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
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
      await fetch("/api/reset", { method: "POST" });
      await refreshHistory();
    });

    refreshHistory();
  </script>
</body>
</html>
"""


def make_handler(assistant: CassandraAssistant) -> Type[BaseHTTPRequestHandler]:
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
                history = assistant.get_conversation_history()
                self._send_json({"history": history})
                return

            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/reset":
                assistant.clear_conversation()
                self._send_json({"ok": True, "history": []})
                return

            if parsed.path == "/api/chat":
                data = self._read_json_body()
                message = str(data.get("message", "")).strip()
                try:
                    result = assistant.process_web_message(message)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": f"Internal error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json(
                    {
                        "reply": result["response"],
                        "dismissed": result["dismissed"],
                        "activated": result["activated"],
                        "history": assistant.get_conversation_history(),
                    }
                )
                return

            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    return CassandraWebHandler


def start_web_server(assistant: CassandraAssistant) -> ThreadingHTTPServer:
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    handler = make_handler(assistant)
    server = ThreadingHTTPServer((host, port), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(f"Web chat running at http://{host}:{port}")
    return server


def main() -> None:
    assistant = CassandraAssistant()
    start_web_server(assistant)
    assistant.run()


if __name__ == "__main__":
    main()
