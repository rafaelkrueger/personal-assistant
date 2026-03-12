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
  <title>Cassandra Dashboard</title>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #111827;
      --panel-2: #0f172a;
      --line: #243244;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --brand: #4f46e5;
      --brand-2: #6366f1;
      --ok: #22c55e;
      --warn: #f59e0b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--text);
      background: radial-gradient(circle at top, #14213d, var(--bg) 45%);
    }
    .wrap { max-width: 1200px; margin: 24px auto; padding: 0 16px 24px; }
    .header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 16px; gap: 12px;
    }
    .title h1 { margin: 0; font-size: 24px; }
    .title p { margin: 4px 0 0; color: var(--muted); }
    .status {
      display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px;
      border-radius: 999px; border: 1px solid var(--line); background: var(--panel);
      font-size: 13px;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; }
    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
    .tab {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 600;
    }
    .tab.active { background: linear-gradient(180deg, var(--brand-2), var(--brand)); border-color: transparent; }
    .grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
    .panel {
      background: rgba(17, 24, 39, 0.9);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      min-height: 520px;
    }
    .hidden { display: none; }
    .chat-box {
      height: 420px;
      overflow: auto;
      background: #060b17;
      border: 1px solid #1e2a3b;
      border-radius: 12px;
      padding: 10px;
    }
    .msg {
      margin: 8px 0;
      padding: 10px 12px;
      border-radius: 12px;
      max-width: 85%;
      line-height: 1.35;
      white-space: pre-wrap;
    }
    .msg.user { background: #1e3a8a; margin-left: auto; }
    .msg.assistant { background: #1f2937; }
    .msg.system { background: #3f3f46; color: #f3f4f6; }
    .meta { font-size: 11px; color: var(--muted); margin-top: 5px; }
    .row { display: flex; gap: 8px; margin-top: 10px; }
    input[type=text], input[type=time] {
      flex: 1; padding: 10px; border-radius: 10px; border: 1px solid #314257;
      background: #0b1322; color: #fff;
    }
    button {
      padding: 10px 13px; border: 0; border-radius: 10px; cursor: pointer;
      background: linear-gradient(180deg, var(--brand-2), var(--brand)); color: white; font-weight: 600;
    }
    button.secondary { background: #334155; }
    button.danger { background: #7f1d1d; }
    .section-title { margin: 2px 0 10px; font-size: 15px; color: #cbd5e1; }
    .list { display: grid; gap: 8px; max-height: 430px; overflow: auto; padding-right: 4px; }
    .item {
      display: flex; justify-content: space-between; align-items: center; gap: 8px;
      padding: 10px; border-radius: 10px; border: 1px solid #29384c; background: #0b1322;
    }
    .item .name { font-weight: 600; }
    .item .sub { font-size: 12px; color: var(--muted); }
    .item-actions { display: flex; gap: 6px; align-items: center; }
    .badge {
      padding: 4px 8px; border-radius: 999px; font-size: 11px; border: 1px solid #2f445b; color: #cbd5e1;
    }
    .todo-done .name { text-decoration: line-through; color: #93a4bc; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="title">
        <h1>Cassandra Dashboard</h1>
        <p>Chat, lista de compras, tarefas e alarmes no mesmo lugar</p>
      </div>
      <div id="alarmStatus" class="status"><span class="dot ok"></span><span>Nenhum alarme tocando</span></div>
    </div>

    <div class="tabs">
      <button class="tab active" data-tab="chat">Chat</button>
      <button class="tab" data-tab="shopping">Compras</button>
      <button class="tab" data-tab="todos">Tarefas</button>
      <button class="tab" data-tab="alarms">Alarmes</button>
    </div>

    <div class="grid">
      <div class="panel">
        <div id="tab-chat">
          <div class="section-title">Conversa</div>
          <div id="history" class="chat-box"></div>
          <div class="row">
            <input id="message" type="text" placeholder="Digite: cassandra, ... para ativar" />
            <button id="send">Enviar</button>
            <button id="newSession" class="secondary">Limpar</button>
          </div>
        </div>

        <div id="tab-shopping" class="hidden">
          <div class="section-title">Lista de compras</div>
          <div class="row">
            <input id="shoppingInput" type="text" placeholder="Ex.: leite" />
            <button id="shoppingAdd">Adicionar</button>
          </div>
          <div id="shoppingList" class="list"></div>
        </div>

        <div id="tab-todos" class="hidden">
          <div class="section-title">Lista de tarefas</div>
          <div class="row">
            <input id="todoInput" type="text" placeholder="Ex.: pagar conta de luz" />
            <button id="todoAdd">Adicionar</button>
          </div>
          <div id="todoList" class="list"></div>
        </div>

        <div id="tab-alarms" class="hidden">
          <div class="section-title">Alarmes</div>
          <div class="row">
            <input id="alarmTime" type="time" />
            <input id="alarmLabel" type="text" placeholder="Rótulo (opcional)" />
          </div>
          <div class="row">
            <label class="badge"><input id="alarmRecurring" type="checkbox" /> Todos os dias</label>
            <button id="alarmAdd">Criar alarme</button>
            <button id="alarmStop" class="danger">Parar alarme tocando</button>
          </div>
          <div id="alarmList" class="list"></div>
        </div>
      </div>
      <div class="panel">
        <div class="section-title">Atalhos</div>
        <div class="list">
          <div class="item"><div><div class="name">Ativar no chat</div><div class="sub">Comece com: cassandra, ...</div></div></div>
          <div class="item"><div><div class="name">Parar alarme por voz/chat</div><div class="sub">"cassandra, parar alarme"</div></div></div>
          <div class="item"><div><div class="name">Memória unificada</div><div class="sub">Voz e web compartilham contexto</div></div></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const tabs = document.querySelectorAll(".tab");
    const sections = {
      chat: document.getElementById("tab-chat"),
      shopping: document.getElementById("tab-shopping"),
      todos: document.getElementById("tab-todos"),
      alarms: document.getElementById("tab-alarms"),
    };
    const historyEl = document.getElementById("history");
    const messageEl = document.getElementById("message");
    const sendEl = document.getElementById("send");
    const newSessionEl = document.getElementById("newSession");
    const alarmStatusEl = document.getElementById("alarmStatus");
    const shoppingInputEl = document.getElementById("shoppingInput");
    const shoppingAddEl = document.getElementById("shoppingAdd");
    const shoppingListEl = document.getElementById("shoppingList");
    const todoInputEl = document.getElementById("todoInput");
    const todoAddEl = document.getElementById("todoAdd");
    const todoListEl = document.getElementById("todoList");
    const alarmTimeEl = document.getElementById("alarmTime");
    const alarmLabelEl = document.getElementById("alarmLabel");
    const alarmRecurringEl = document.getElementById("alarmRecurring");
    const alarmAddEl = document.getElementById("alarmAdd");
    const alarmStopEl = document.getElementById("alarmStop");
    const alarmListEl = document.getElementById("alarmList");

    function escapeHtml(text) {
      return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }

    function activateTab(tabName) {
      for (const tab of tabs) {
        tab.classList.toggle("active", tab.dataset.tab === tabName);
      }
      for (const [name, el] of Object.entries(sections)) {
        el.classList.toggle("hidden", name !== tabName);
      }
    }

    tabs.forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));

    function render(items) {
      historyEl.innerHTML = "";
      for (const item of items) {
        const roleClass = item.role === "assistant" ? "assistant" : "user";
        const kind = (item.kind || "chat");
        const finalClass = kind !== "chat" ? "system" : roleClass;
        const html = `
          <div class="msg ${finalClass}">
            <div>${escapeHtml(item.content)}</div>
            <div class="meta">${item.timestamp || ""} - ${item.role || ""}</div>
          </div>
        `;
        historyEl.insertAdjacentHTML("beforeend", html);
      }
      historyEl.scrollTop = historyEl.scrollHeight;
    }

    async function api(path, method = "GET", body = null) {
      const res = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : null
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro na API");
      return data;
    }

    function renderShopping(items) {
      shoppingListEl.innerHTML = "";
      for (const item of items) {
        const html = `
          <div class="item">
            <div>
              <div class="name">${escapeHtml(item.name || "")}</div>
              <div class="sub">${escapeHtml(item.created_at || "")}</div>
            </div>
            <div class="item-actions">
              <button class="danger" data-shopping-remove="${item.id}">Remover</button>
            </div>
          </div>
        `;
        shoppingListEl.insertAdjacentHTML("beforeend", html);
      }
      shoppingListEl.querySelectorAll("[data-shopping-remove]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api("/api/shopping/remove", "POST", { id: btn.dataset.shoppingRemove });
          await refreshDashboard();
        });
      });
    }

    function renderTodos(items) {
      todoListEl.innerHTML = "";
      for (const item of items) {
        const doneClass = item.completed ? "todo-done" : "";
        const badge = item.completed ? "Concluída" : "Pendente";
        const html = `
          <div class="item ${doneClass}">
            <div>
              <div class="name">${escapeHtml(item.title || "")}</div>
              <div class="sub">${badge}</div>
            </div>
            <div class="item-actions">
              <button class="secondary" data-todo-toggle="${item.id}" data-completed="${item.completed}">
                ${item.completed ? "Reabrir" : "Concluir"}
              </button>
              <button class="danger" data-todo-remove="${item.id}">Remover</button>
            </div>
          </div>
        `;
        todoListEl.insertAdjacentHTML("beforeend", html);
      }
      todoListEl.querySelectorAll("[data-todo-toggle]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const completed = btn.dataset.completed !== "true";
          await api("/api/todos/toggle", "POST", { id: btn.dataset.todoToggle, completed });
          await refreshDashboard();
        });
      });
      todoListEl.querySelectorAll("[data-todo-remove]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api("/api/todos/remove", "POST", { id: btn.dataset.todoRemove });
          await refreshDashboard();
        });
      });
    }

    function renderAlarms(items) {
      alarmListEl.innerHTML = "";
      for (const item of items) {
        const recur = item.recurring_daily ? "Todos os dias" : "Uma vez";
        const status = item.enabled ? "Ativo" : "Desativado";
        const html = `
          <div class="item">
            <div>
              <div class="name">${escapeHtml(item.time_hhmm || "")} - ${escapeHtml(item.label || "Alarme")}</div>
              <div class="sub">${recur} | ${status}</div>
            </div>
            <div class="item-actions">
              <button class="danger" data-alarm-remove="${item.id}">Remover</button>
            </div>
          </div>
        `;
        alarmListEl.insertAdjacentHTML("beforeend", html);
      }
      alarmListEl.querySelectorAll("[data-alarm-remove]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api("/api/alarms/remove", "POST", { id: btn.dataset.alarmRemove });
          await refreshDashboard();
        });
      });
    }

    function renderAlarmStatus(isRinging) {
      alarmStatusEl.innerHTML = isRinging
        ? '<span class="dot warn"></span><span>Alarme tocando</span>'
        : '<span class="dot ok"></span><span>Nenhum alarme tocando</span>';
    }

    async function refreshHistory() {
      const data = await api("/api/history");
      render(data.history || []);
    }

    async function refreshDashboard() {
      const data = await api("/api/dashboard");
      render(data.history || []);
      renderShopping(data.shopping || []);
      renderTodos(data.todos || []);
      renderAlarms(data.alarms || []);
      renderAlarmStatus(Boolean(data.alarm_ringing));
    }

    async function sendMessage() {
      const text = messageEl.value.trim();
      if (!text) return;
      messageEl.value = "";
      try {
        const data = await api("/api/chat", "POST", { message: text });
        render(data.history || []);
      } catch (err) {
        alert(err.message || "Erro ao enviar mensagem.");
      }
    }

    sendEl.addEventListener("click", sendMessage);
    messageEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendMessage();
    });
    newSessionEl.addEventListener("click", async () => {
      await api("/api/reset", "POST", {});
      await refreshDashboard();
    });

    shoppingAddEl.addEventListener("click", async () => {
      const value = shoppingInputEl.value.trim();
      if (!value) return;
      shoppingInputEl.value = "";
      await api("/api/shopping/add", "POST", { name: value });
      await refreshDashboard();
    });

    todoAddEl.addEventListener("click", async () => {
      const value = todoInputEl.value.trim();
      if (!value) return;
      todoInputEl.value = "";
      await api("/api/todos/add", "POST", { title: value });
      await refreshDashboard();
    });

    alarmAddEl.addEventListener("click", async () => {
      const time = alarmTimeEl.value;
      if (!time) return;
      await api("/api/alarms/add", "POST", {
        time_hhmm: time,
        recurring_daily: alarmRecurringEl.checked,
        label: alarmLabelEl.value || "Alarme Cassandra"
      });
      alarmLabelEl.value = "";
      await refreshDashboard();
    });

    alarmStopEl.addEventListener("click", async () => {
      await api("/api/alarms/stop", "POST", {});
      await refreshDashboard();
    });

    refreshDashboard();
    setInterval(refreshDashboard, 5000);
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

            if parsed.path == "/api/dashboard":
                self._send_json(
                    {
                        "history": assistant.get_conversation_history(),
                        "shopping": assistant.get_shopping_items(),
                        "todos": assistant.get_todos(),
                        "alarms": assistant.list_alarms(),
                        "alarm_ringing": assistant.is_alarm_ringing(),
                    }
                )
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

            if parsed.path == "/api/shopping/add":
                data = self._read_json_body()
                name = str(data.get("name", "")).strip()
                if not name:
                    self._send_json({"error": "name is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                assistant.add_shopping_item(name)
                self._send_json({"shopping": assistant.get_shopping_items()})
                return

            if parsed.path == "/api/shopping/remove":
                data = self._read_json_body()
                item_id = str(data.get("id", "")).strip()
                if not item_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                removed = assistant.remove_shopping_item(item_id)
                self._send_json({"removed": removed, "shopping": assistant.get_shopping_items()})
                return

            if parsed.path == "/api/todos/add":
                data = self._read_json_body()
                title = str(data.get("title", "")).strip()
                if not title:
                    self._send_json({"error": "title is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                assistant.add_todo(title)
                self._send_json({"todos": assistant.get_todos()})
                return

            if parsed.path == "/api/todos/remove":
                data = self._read_json_body()
                task_id = str(data.get("id", "")).strip()
                if not task_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                removed = assistant.remove_todo(task_id)
                self._send_json({"removed": removed, "todos": assistant.get_todos()})
                return

            if parsed.path == "/api/todos/toggle":
                data = self._read_json_body()
                task_id = str(data.get("id", "")).strip()
                completed = bool(data.get("completed", False))
                if not task_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                changed = assistant.set_todo_completed(task_id, completed)
                self._send_json({"changed": changed, "todos": assistant.get_todos()})
                return

            if parsed.path == "/api/alarms/add":
                data = self._read_json_body()
                time_hhmm = str(data.get("time_hhmm", "")).strip()
                if not time_hhmm:
                    self._send_json({"error": "time_hhmm is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                recurring_daily = bool(data.get("recurring_daily", False))
                label = str(data.get("label", "Alarme Cassandra")).strip() or "Alarme Cassandra"
                try:
                    assistant.add_alarm(time_hhmm=time_hhmm, recurring_daily=recurring_daily, label=label)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"alarms": assistant.list_alarms()})
                return

            if parsed.path == "/api/alarms/remove":
                data = self._read_json_body()
                alarm_id = str(data.get("id", "")).strip()
                if not alarm_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                removed = assistant.remove_alarm(alarm_id)
                self._send_json({"removed": removed, "alarms": assistant.list_alarms()})
                return

            if parsed.path == "/api/alarms/stop":
                stopped = assistant.stop_alarm_ringing()
                self._send_json({"stopped": stopped, "alarm_ringing": assistant.is_alarm_ringing()})
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
