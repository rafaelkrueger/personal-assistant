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
  <title>Cassandra</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:       #05090f;
      --sidebar:  #070d18;
      --surface:  #0c1524;
      --surface2: #101d30;
      --border:   #16253a;
      --border2:  #1c3050;
      --text:     #dde4f0;
      --muted:    #4d6680;
      --muted2:   #7a96b4;
      --brand:    #3b82f6;
      --brand2:   #60a5fa;
      --ok:       #22c55e;
      --warn:     #f59e0b;
      --danger:   #ef4444;
      --r:        10px;
      --rl:       14px;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5;
      min-height: 100vh;
    }
    .app { display: flex; height: 100vh; overflow: hidden; }

    /* ── SIDEBAR ── */
    .sidebar {
      width: 210px; flex-shrink: 0;
      background: var(--sidebar); border-right: 1px solid var(--border);
      display: flex; flex-direction: column; padding: 16px 10px; gap: 3px;
    }
    .brand {
      display: flex; align-items: center; gap: 10px;
      padding: 6px 8px 18px; border-bottom: 1px solid var(--border); margin-bottom: 6px;
    }
    .brand-icon {
      width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0;
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      display: flex; align-items: center; justify-content: center; font-size: 17px;
    }
    .brand-name { font-size: 15px; font-weight: 700; }
    .brand-sub  { font-size: 11px; color: var(--muted2); }
    .nav-btn {
      display: flex; align-items: center; gap: 9px; padding: 9px 10px;
      border-radius: var(--r); border: none; background: transparent;
      color: var(--muted2); font-size: 13.5px; font-weight: 500;
      cursor: pointer; width: 100%; text-align: left; transition: all .12s;
    }
    .nav-btn:hover  { background: var(--surface); color: var(--text); }
    .nav-btn.active { background: rgba(59,130,246,.13); color: var(--brand2); }
    .nav-icon { font-size: 15px; width: 18px; text-align: center; }
    .sidebar-footer { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); }
    .status-chip {
      display: flex; align-items: center; gap: 7px; padding: 8px 10px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--r);
      font-size: 12px; color: var(--muted2);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .dot.ok   { background: var(--ok); }
    .dot.warn { background: var(--warn); animation: pulse .8s step-end infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.2} }

    /* ── MAIN ── */
    .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
    .topbar {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 22px; border-bottom: 1px solid var(--border);
      background: var(--sidebar); flex-shrink: 0;
    }
    .page-title { font-size: 15px; font-weight: 600; }
    .page-sub   { font-size: 12px; color: var(--muted); margin-top: 1px; }
    .clock { font-size: 13px; color: var(--muted2); font-variant-numeric: tabular-nums; }
    .body { flex: 1; overflow-y: auto; padding: 20px 22px; }
    .tab-panel.hidden { display: none !important; }

    /* ── BUTTONS ── */
    .btn {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 8px 14px; border: none; border-radius: var(--r);
      font-size: 13px; font-weight: 600; cursor: pointer; transition: opacity .12s, transform .08s;
      white-space: nowrap;
    }
    .btn:active { transform: scale(.96); }
    .btn-primary { background: var(--brand); color: #fff; }
    .btn-primary:hover { opacity: .85; }
    .btn-ghost {
      background: var(--surface2); border: 1px solid var(--border);
      color: var(--text);
    }
    .btn-ghost:hover { background: var(--border); }
    .btn-danger {
      background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.25);
      color: #fca5a5;
    }
    .btn-danger:hover { background: rgba(239,68,68,.22); }
    .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 8px; }

    /* ── INPUTS ── */
    .row { display: flex; gap: 8px; margin-bottom: 12px; }
    input[type=text], input[type=time] {
      flex: 1; padding: 9px 12px; border-radius: var(--r);
      border: 1px solid var(--border); background: var(--surface);
      color: var(--text); font-size: 13.5px; outline: none; transition: border-color .12s;
    }
    input:focus { border-color: var(--brand); }
    input::placeholder { color: var(--muted); }

    /* ── CHAT ── */
    .chat-wrap { display: flex; flex-direction: column; height: calc(100vh - 126px); }
    .messages {
      flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column;
      gap: 10px; background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--rl); margin-bottom: 12px;
    }
    .msg { max-width: 76%; display: flex; flex-direction: column; }
    .msg.user      { align-self: flex-end; align-items: flex-end; }
    .msg.assistant { align-self: flex-start; }
    .msg.system    { align-self: center; max-width: 90%; }
    .bubble {
      padding: 9px 13px; border-radius: 13px; line-height: 1.45;
      white-space: pre-wrap; word-break: break-word; font-size: 13.5px;
    }
    .msg.user .bubble {
      background: var(--brand); color: #fff; border-bottom-right-radius: 3px;
    }
    .msg.assistant .bubble {
      background: var(--surface2); border: 1px solid var(--border);
      border-bottom-left-radius: 3px;
    }
    .msg.system .bubble {
      background: transparent; border: 1px dashed var(--border2);
      color: var(--muted2); font-size: 12px; text-align: center;
    }
    .msg-meta { font-size: 11px; color: var(--muted); margin-top: 3px; padding: 0 4px; }
    .chat-input { display: flex; gap: 8px; }
    .chat-input input { flex: 1; }

    /* ── LISTS ── */
    .sec-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
    .sec-title  { font-size: 15px; font-weight: 600; }
    .badge-count {
      font-size: 12px; color: var(--muted2); background: var(--surface2);
      border: 1px solid var(--border); padding: 2px 9px; border-radius: 99px;
    }
    .list { display: flex; flex-direction: column; gap: 8px; }
    .item {
      display: flex; align-items: center; gap: 12px; padding: 11px 14px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--r);
      transition: border-color .12s;
    }
    .item:hover { border-color: var(--border2); }
    .item-body { flex: 1; min-width: 0; }
    .item-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .item-sub  { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .item-actions { display: flex; gap: 6px; flex-shrink: 0; }
    .done .item-name { text-decoration: line-through; color: var(--muted); }
    .empty { text-align: center; padding: 40px 0; color: var(--muted); font-size: 13px; }

    /* ── NOTES GRID ── */
    .notes-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px;
    }
    .note-card {
      padding: 13px 13px 10px; background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--r); position: relative; transition: border-color .12s;
    }
    .note-card:hover { border-color: var(--border2); }
    .note-body { font-size: 13.5px; line-height: 1.5; word-break: break-word; padding-right: 22px; }
    .note-date { font-size: 11px; color: var(--muted); margin-top: 8px; }
    .note-del  { position: absolute; top: 8px; right: 8px; }

    /* ── ALARMS ── */
    .alarm-form {
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--rl);
      padding: 16px; margin-bottom: 16px;
    }
    .form-label { font-size: 12px; color: var(--muted2); font-weight: 600; margin-bottom: 6px; }
    .day-picker { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 10px; }
    .day-btn {
      padding: 5px 11px; border-radius: 99px; border: 1px solid var(--border);
      background: transparent; color: var(--muted2); font-size: 12px; font-weight: 600;
      cursor: pointer; transition: all .12s;
    }
    .day-btn.on { background: rgba(59,130,246,.18); border-color: var(--brand); color: var(--brand2); }
    .day-presets { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
    .day-tag {
      display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11px;
      font-weight: 600; background: rgba(59,130,246,.1); border: 1px solid rgba(59,130,246,.2);
      color: var(--brand2);
    }
    .alarm-time { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .alarm-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .alarm-dot.on  { background: var(--ok); }
    .alarm-dot.off { background: var(--muted); }

    /* ── SCROLLBARS ── */
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 99px; }

    @media (max-width: 600px) {
      .sidebar { width: 100%; height: auto; flex-direction: row; padding: 8px; overflow-x: auto; }
      .brand, .sidebar-footer { display: none; }
      .app { flex-direction: column; }
      .nav-btn { flex-direction: column; font-size: 10px; gap: 2px; padding: 7px 10px; }
      .nav-icon { font-size: 18px; }
      .body { padding: 12px; }
    }
  </style>
</head>
<body>
<div class="app">

  <!-- SIDEBAR -->
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-icon">🤖</div>
      <div>
        <div class="brand-name">Cassandra</div>
        <div class="brand-sub">Assistente pessoal</div>
      </div>
    </div>
    <button class="nav-btn active" data-tab="chat"><span class="nav-icon">💬</span>Chat</button>
    <button class="nav-btn" data-tab="shopping"><span class="nav-icon">🛒</span>Compras</button>
    <button class="nav-btn" data-tab="todos"><span class="nav-icon">✅</span>Tarefas</button>
    <button class="nav-btn" data-tab="notes"><span class="nav-icon">📝</span>Notas</button>
    <button class="nav-btn" data-tab="alarms"><span class="nav-icon">🔔</span>Alarmes</button>
    <div class="sidebar-footer">
      <div class="status-chip">
        <span class="dot ok" id="alarmDot"></span>
        <span id="alarmStatusText">Nenhum alarme</span>
      </div>
    </div>
  </aside>

  <!-- MAIN -->
  <div class="main">
    <div class="topbar">
      <div>
        <div class="page-title" id="pageTitle">Chat</div>
        <div class="page-sub"  id="pageSub">Fale com a Cassandra</div>
      </div>
      <span class="clock" id="clock"></span>
    </div>

    <div class="body">

      <!-- CHAT -->
      <div class="tab-panel" id="tab-chat">
        <div class="chat-wrap">
          <div class="messages" id="messages">
            <div class="empty">Nenhuma mensagem. Digite <b>cassandra, ...</b> para ativar.</div>
          </div>
          <div class="chat-input">
            <input id="msgInput" type="text" placeholder="cassandra, o que você pode fazer?" />
            <button class="btn btn-primary" id="sendBtn">Enviar</button>
            <button class="btn btn-ghost"   id="clearBtn">Limpar</button>
          </div>
        </div>
      </div>

      <!-- SHOPPING -->
      <div class="tab-panel hidden" id="tab-shopping">
        <div class="sec-header">
          <span class="sec-title">Lista de compras</span>
          <span class="badge-count" id="shopCount">0 itens</span>
        </div>
        <div class="row">
          <input id="shopInput" type="text" placeholder="Ex.: leite, pão, café..." />
          <button class="btn btn-primary" id="shopAdd">+ Adicionar</button>
        </div>
        <div class="list" id="shopList"></div>
      </div>

      <!-- TODOS -->
      <div class="tab-panel hidden" id="tab-todos">
        <div class="sec-header">
          <span class="sec-title">Tarefas</span>
          <span class="badge-count" id="todoCount">0 pendentes</span>
        </div>
        <div class="row">
          <input id="todoInput" type="text" placeholder="Ex.: pagar conta de luz..." />
          <button class="btn btn-primary" id="todoAdd">+ Adicionar</button>
        </div>
        <div class="list" id="todoList"></div>
      </div>

      <!-- NOTES -->
      <div class="tab-panel hidden" id="tab-notes">
        <div class="sec-header">
          <span class="sec-title">Notas rápidas</span>
          <span class="badge-count" id="noteCount">0 notas</span>
        </div>
        <div class="row">
          <input id="noteInput" type="text" placeholder="Ex.: lembrar de ligar pro médico..." />
          <button class="btn btn-primary" id="noteAdd">+ Anotar</button>
        </div>
        <div class="notes-grid" id="noteList"></div>
      </div>

      <!-- ALARMS -->
      <div class="tab-panel hidden" id="tab-alarms">
        <div class="sec-header">
          <span class="sec-title">Alarmes</span>
          <span class="badge-count" id="alarmCount">0 alarmes</span>
        </div>
        <div class="alarm-form">
          <div class="form-label" style="margin-bottom:10px;">Novo alarme</div>
          <div class="row">
            <input id="alarmTime" type="time" style="max-width:130px;flex:none;" />
            <input id="alarmLabel" type="text" placeholder="Rótulo (opcional)" />
          </div>
          <div class="form-label">Dias da semana</div>
          <div class="day-picker" id="dayPicker">
            <button class="day-btn" data-day="0">Seg</button>
            <button class="day-btn" data-day="1">Ter</button>
            <button class="day-btn" data-day="2">Qua</button>
            <button class="day-btn" data-day="3">Qui</button>
            <button class="day-btn" data-day="4">Sex</button>
            <button class="day-btn" data-day="5">Sáb</button>
            <button class="day-btn" data-day="6">Dom</button>
          </div>
          <div class="day-presets">
            <button class="btn btn-ghost btn-sm" onclick="setPreset([0,1,2,3,4])">Dias úteis</button>
            <button class="btn btn-ghost btn-sm" onclick="setPreset([5,6])">Fim de semana</button>
            <button class="btn btn-ghost btn-sm" onclick="setPreset([])">Todos os dias</button>
            <button class="btn btn-ghost btn-sm" onclick="setPreset(null)">Uma vez</button>
          </div>
          <div class="row" style="margin:0;">
            <button class="btn btn-primary" id="alarmAdd">Criar alarme</button>
            <button class="btn btn-danger"  id="alarmStop">⏹ Parar alarme tocando</button>
          </div>
        </div>
        <div class="list" id="alarmList"></div>
      </div>

    </div>
  </div>
</div>

<script>
const PAGE = {
  chat:     ["Chat",            "Fale com a Cassandra via web"],
  shopping: ["Lista de compras","Gerencie suas compras"],
  todos:    ["Tarefas",         "Organize suas pendências"],
  notes:    ["Notas rápidas",   "Anote lembretes e ideias"],
  alarms:   ["Alarmes",         "Configure alarmes por dia e horário"],
};
const DAY_NAMES = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"];
let selDays = []; // []: all days recurring, null: one-time, [0..6]: specific days

// ── Utils ──
const esc = t => (t||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
async function api(path, method="GET", body=null) {
  const r = await fetch(path, {method, headers:{"Content-Type":"application/json"}, body: body ? JSON.stringify(body) : null});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "Erro na API");
  return d;
}
function enter(el, fn) { el.addEventListener("keydown", e => { if (e.key==="Enter") fn(); }); }

// ── Clock ──
(function tick() {
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  setTimeout(tick, 1000);
})();

// ── Tabs ──
const navBtns = document.querySelectorAll(".nav-btn");
navBtns.forEach(b => b.addEventListener("click", () => {
  const tab = b.dataset.tab;
  navBtns.forEach(x => x.classList.toggle("active", x.dataset.tab===tab));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("hidden", p.id!=="tab-"+tab));
  const [title, sub] = PAGE[tab] || [tab,""];
  document.getElementById("pageTitle").textContent = title;
  document.getElementById("pageSub").textContent   = sub;
}));

// ── Render Messages ──
function renderMessages(items) {
  const el = document.getElementById("messages");
  if (!items.length) { el.innerHTML = '<div class="empty">Nenhuma mensagem. Digite <b>cassandra, ...</b> para ativar.</div>'; return; }
  el.innerHTML = items.map(m => {
    const kind = m.kind||"chat";
    const cls  = kind!=="chat" ? "system" : (m.role==="assistant" ? "assistant" : "user");
    return `<div class="msg ${cls}">
      <div class="bubble">${esc(m.content)}</div>
      <div class="msg-meta">${(m.timestamp||"").substring(11,16)} · ${m.role}</div>
    </div>`;
  }).join("");
  el.scrollTop = el.scrollHeight;
}

// ── Render Shopping ──
function renderShopping(items) {
  const el = document.getElementById("shopList");
  document.getElementById("shopCount").textContent = items.length + (items.length===1?" item":" itens");
  if (!items.length) { el.innerHTML='<div class="empty">Lista vazia.</div>'; return; }
  el.innerHTML = items.map(i => `
    <div class="item">
      <div class="item-body">
        <div class="item-name">${esc(i.name)}</div>
        <div class="item-sub">${esc(i.created_at||"")}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-danger btn-sm" data-shop-rm="${i.id}">Remover</button>
      </div>
    </div>`).join("");
  el.querySelectorAll("[data-shop-rm]").forEach(b => b.addEventListener("click", async () => {
    await api("/api/shopping/remove","POST",{id:b.dataset.shopRm}); await refresh();
  }));
}

// ── Render Todos ──
function renderTodos(items) {
  const el = document.getElementById("todoList");
  const p = items.filter(i=>!i.completed).length;
  document.getElementById("todoCount").textContent = p+" pendente"+(p!==1?"s":"");
  if (!items.length) { el.innerHTML='<div class="empty">Nenhuma tarefa.</div>'; return; }
  el.innerHTML = items.map(i => `
    <div class="item ${i.completed?"done":""}">
      <div class="item-body">
        <div class="item-name">${esc(i.title)}</div>
        <div class="item-sub">${i.completed?"✓ Concluída":"Pendente"}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-ghost btn-sm" data-todo-tog="${i.id}" data-done="${i.completed}">${i.completed?"Reabrir":"Concluir"}</button>
        <button class="btn btn-danger btn-sm" data-todo-rm="${i.id}">✕</button>
      </div>
    </div>`).join("");
  el.querySelectorAll("[data-todo-tog]").forEach(b => b.addEventListener("click", async () => {
    await api("/api/todos/toggle","POST",{id:b.dataset.todoTog,completed:b.dataset.done!=="true"}); await refresh();
  }));
  el.querySelectorAll("[data-todo-rm]").forEach(b => b.addEventListener("click", async () => {
    await api("/api/todos/remove","POST",{id:b.dataset.todoRm}); await refresh();
  }));
}

// ── Render Notes ──
function renderNotes(items) {
  const el = document.getElementById("noteList");
  document.getElementById("noteCount").textContent = items.length+(items.length===1?" nota":" notas");
  if (!items.length) { el.innerHTML='<div class="empty" style="grid-column:1/-1">Nenhuma nota.</div>'; return; }
  el.innerHTML = items.map(n => `
    <div class="note-card">
      <button class="btn btn-danger btn-sm note-del" data-note-rm="${n.id}" title="Apagar">✕</button>
      <div class="note-body">${esc(n.content)}</div>
      <div class="note-date">${esc(n.created_at||"")}</div>
    </div>`).join("");
  el.querySelectorAll("[data-note-rm]").forEach(b => b.addEventListener("click", async () => {
    await api("/api/notes/remove","POST",{id:b.dataset.noteRm}); await refresh();
  }));
}

// ── Render Alarms ──
function renderAlarms(items) {
  const el = document.getElementById("alarmList");
  document.getElementById("alarmCount").textContent = items.length+(items.length===1?" alarme":" alarmes");
  if (!items.length) { el.innerHTML='<div class="empty">Nenhum alarme.</div>'; return; }
  el.innerHTML = items.map(a => {
    const days = a.days_of_week;
    let dayHtml;
    if (days && days.length) {
      dayHtml = days.map(d=>`<span class="day-tag">${DAY_NAMES[d]}</span>`).join(" ");
    } else if (a.recurring_daily) {
      dayHtml = '<span class="day-tag">Todos os dias</span>';
    } else {
      dayHtml = '<span class="day-tag" style="opacity:.6">Uma vez</span>';
    }
    return `<div class="item">
      <span class="alarm-dot ${a.enabled?"on":"off"}"></span>
      <div class="item-body">
        <div class="item-name"><span class="alarm-time">${esc(a.time_hhmm)}</span>
          <span style="font-size:13px;font-weight:400;color:var(--muted2);margin-left:6px;">${esc(a.label||"")}</span>
        </div>
        <div class="item-sub" style="margin-top:5px;">${dayHtml}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-danger btn-sm" data-alarm-rm="${a.id}">Remover</button>
      </div>
    </div>`;
  }).join("");
  el.querySelectorAll("[data-alarm-rm]").forEach(b => b.addEventListener("click", async () => {
    await api("/api/alarms/remove","POST",{id:b.dataset.alarmRm}); await refresh();
  }));
}

// ── Alarm status ──
function renderAlarmStatus(ringing) {
  document.getElementById("alarmDot").className = "dot " + (ringing ? "warn" : "ok");
  document.getElementById("alarmStatusText").textContent = ringing ? "⚠ Alarme tocando!" : "Nenhum alarme";
}

// ── Day picker ──
function setPreset(days) {
  selDays = days;
  document.querySelectorAll(".day-btn").forEach(b => {
    b.classList.toggle("on", Array.isArray(days) && days.includes(+b.dataset.day));
  });
}
document.querySelectorAll(".day-btn").forEach(b => b.addEventListener("click", () => {
  if (!Array.isArray(selDays)) selDays = [];
  const d = +b.dataset.day;
  selDays = selDays.includes(d) ? selDays.filter(x=>x!==d) : [...selDays,d].sort((a,b)=>a-b);
  b.classList.toggle("on", selDays.includes(d));
}));

// ── Refresh ──
async function refresh() {
  const d = await api("/api/dashboard");
  renderMessages(d.history||[]);
  renderShopping(d.shopping||[]);
  renderTodos(d.todos||[]);
  renderNotes(d.notes||[]);
  renderAlarms(d.alarms||[]);
  renderAlarmStatus(Boolean(d.alarm_ringing));
}

// ── Actions ──
async function sendMsg() {
  const el = document.getElementById("msgInput");
  const t = el.value.trim(); if (!t) return;
  el.value = "";
  try {
    const d = await api("/api/chat","POST",{message:t});
    renderMessages(d.history||[]);
  } catch(e) { alert(e.message); }
}
document.getElementById("sendBtn").addEventListener("click", sendMsg);
enter(document.getElementById("msgInput"), sendMsg);
document.getElementById("clearBtn").addEventListener("click", async () => { await api("/api/reset","POST",{}); await refresh(); });

const shopInput = document.getElementById("shopInput");
document.getElementById("shopAdd").addEventListener("click", async () => {
  const v=shopInput.value.trim(); if(!v) return; shopInput.value="";
  await api("/api/shopping/add","POST",{name:v}); await refresh();
});
enter(shopInput, () => document.getElementById("shopAdd").click());

const todoInput = document.getElementById("todoInput");
document.getElementById("todoAdd").addEventListener("click", async () => {
  const v=todoInput.value.trim(); if(!v) return; todoInput.value="";
  await api("/api/todos/add","POST",{title:v}); await refresh();
});
enter(todoInput, () => document.getElementById("todoAdd").click());

const noteInput = document.getElementById("noteInput");
document.getElementById("noteAdd").addEventListener("click", async () => {
  const v=noteInput.value.trim(); if(!v) return; noteInput.value="";
  await api("/api/notes/add","POST",{content:v}); await refresh();
});
enter(noteInput, () => document.getElementById("noteAdd").click());

document.getElementById("alarmAdd").addEventListener("click", async () => {
  const time = document.getElementById("alarmTime").value;
  if (!time) { alert("Escolha um horário."); return; }
  const label = document.getElementById("alarmLabel").value||"Alarme";
  const recurring_daily = selDays !== null;
  const days_of_week = (Array.isArray(selDays) && selDays.length) ? selDays : null;
  await api("/api/alarms/add","POST",{time_hhmm:time,recurring_daily,label,days_of_week});
  document.getElementById("alarmLabel").value=""; setPreset([]);
  await refresh();
});
document.getElementById("alarmStop").addEventListener("click", async () => {
  await api("/api/alarms/stop","POST",{}); await refresh();
});

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


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
                self._send_json({"history": assistant.get_conversation_history()})
                return
            if parsed.path == "/api/dashboard":
                self._send_json({
                    "history":      assistant.get_conversation_history(),
                    "shopping":     assistant.get_shopping_items(),
                    "todos":        assistant.get_todos(),
                    "notes":        assistant.get_notes(),
                    "alarms":       assistant.list_alarms(),
                    "alarm_ringing": assistant.is_alarm_ringing(),
                })
                return
            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path == "/api/reset":
                assistant.clear_conversation()
                self._send_json({"ok": True})
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
                self._send_json({
                    "reply":     result["response"],
                    "dismissed": result["dismissed"],
                    "activated": result["activated"],
                    "history":   assistant.get_conversation_history(),
                })
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
                assistant.remove_shopping_item(item_id)
                self._send_json({"shopping": assistant.get_shopping_items()})
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
                assistant.remove_todo(task_id)
                self._send_json({"todos": assistant.get_todos()})
                return

            if parsed.path == "/api/todos/toggle":
                data = self._read_json_body()
                task_id = str(data.get("id", "")).strip()
                completed = bool(data.get("completed", False))
                if not task_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                assistant.set_todo_completed(task_id, completed)
                self._send_json({"todos": assistant.get_todos()})
                return

            if parsed.path == "/api/notes/add":
                data = self._read_json_body()
                content = str(data.get("content", "")).strip()
                if not content:
                    self._send_json({"error": "content is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                note = assistant.add_note(content)
                self._send_json({"note": note, "notes": assistant.get_notes()})
                return

            if parsed.path == "/api/notes/remove":
                data = self._read_json_body()
                note_id = str(data.get("id", "")).strip()
                if not note_id:
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                assistant.remove_note(note_id)
                self._send_json({"notes": assistant.get_notes()})
                return

            if parsed.path == "/api/alarms/add":
                data = self._read_json_body()
                time_hhmm = str(data.get("time_hhmm", "")).strip()
                if not time_hhmm:
                    self._send_json({"error": "time_hhmm is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                recurring_daily = bool(data.get("recurring_daily", False))
                label = str(data.get("label", "Alarme Cassandra")).strip() or "Alarme Cassandra"
                raw_days = data.get("days_of_week")
                days_of_week = [int(d) for d in raw_days] if isinstance(raw_days, list) else None
                try:
                    assistant.add_alarm(
                        time_hhmm=time_hhmm,
                        recurring_daily=recurring_daily,
                        label=label,
                        days_of_week=days_of_week,
                    )
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
                assistant.remove_alarm(alarm_id)
                self._send_json({"alarms": assistant.list_alarms()})
                return

            if parsed.path == "/api/alarms/stop":
                assistant.stop_alarm_ringing()
                self._send_json({"alarm_ringing": assistant.is_alarm_ringing()})
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
    Thread(target=server.serve_forever, daemon=True).start()
    print(f"Web chat running at http://{host}:{port}")
    return server


def main() -> None:
    assistant = CassandraAssistant()
    start_web_server(assistant)
    assistant.run()


if __name__ == "__main__":
    main()
