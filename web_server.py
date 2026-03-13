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
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
  <title>Cassandra</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --bg:#080d18;
      --sidebar:#060b14;
      --surface:#0e1628;
      --surface2:#121d30;
      --surface3:#172038;
      --glass:rgba(14,22,40,0.7);
      --border:rgba(255,255,255,0.06);
      --border2:rgba(255,255,255,0.1);
      --text:#e8f0fe;
      --text2:#94a3b8;
      --text3:#475569;
      --brand:#4f8eff;
      --brand2:#7ab3ff;
      --brand-dim:rgba(79,142,255,0.15);
      --brand-glow:rgba(79,142,255,0.3);
      --purple:#8b5cf6;
      --purple-dim:rgba(139,92,246,0.15);
      --green:#22c55e;
      --green-dim:rgba(34,197,94,0.12);
      --amber:#f59e0b;
      --amber-dim:rgba(245,158,11,0.12);
      --red:#ef4444;
      --red-dim:rgba(239,68,68,0.12);
      --r:12px;--rl:16px;--rx:20px;
      --sidebar-w:240px;--sidebar-collapsed:64px;
      --topbar-h:58px;--bottomnav-h:64px;
      --shadow:0 4px 24px rgba(0,0,0,0.4);
      --shadow-sm:0 2px 8px rgba(0,0,0,0.3);
    }

    html,body{height:100%;overflow:hidden;-webkit-font-smoothing:antialiased}
    body{
      font-family:'Inter',system-ui,-apple-system,sans-serif;
      background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;
    }

    /* ═══ SCROLLBAR ═══ */
    ::-webkit-scrollbar{width:4px;height:4px}
    ::-webkit-scrollbar-track{background:transparent}
    ::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:99px}
    ::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.18)}

    /* ═══ APP SHELL ═══ */
    .app{display:flex;height:100vh;overflow:hidden}

    /* ═══ SIDEBAR ═══ */
    .sidebar{
      display:none;width:var(--sidebar-w);flex-shrink:0;
      background:var(--sidebar);
      border-right:1px solid var(--border);
      flex-direction:column;
      transition:width .22s cubic-bezier(.4,0,.2,1);
      overflow:hidden;position:relative;z-index:10;
    }
    .sidebar.collapsed{width:var(--sidebar-collapsed)}
    @media(min-width:768px){.sidebar{display:flex}}

    .sb-top{
      display:flex;align-items:center;gap:10px;
      padding:16px 14px;border-bottom:1px solid var(--border);
      flex-shrink:0;min-height:var(--topbar-h);
    }
    .brand-icon{
      width:34px;height:34px;border-radius:10px;flex-shrink:0;
      background:linear-gradient(135deg,#4f8eff,#8b5cf6);
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 0 16px rgba(79,142,255,0.4);
    }
    .brand-icon svg{width:17px;height:17px;color:#fff}
    .brand-text{font-size:15px;font-weight:700;white-space:nowrap;letter-spacing:-.01em}
    .brand-sub{font-size:10px;color:var(--text3);white-space:nowrap;margin-top:-1px}
    .collapsed .brand-text,.collapsed .brand-sub{display:none}
    .collapse-btn{
      margin-left:auto;background:transparent;border:none;
      color:var(--text3);cursor:pointer;padding:5px;border-radius:8px;flex-shrink:0;
      display:flex;align-items:center;transition:all .15s;
    }
    .collapse-btn:hover{background:var(--surface);color:var(--text)}
    .collapse-btn svg{width:17px;height:17px;transition:transform .22s}
    .collapsed .collapse-btn svg{transform:rotate(180deg)}

    .sb-nav{flex:1;padding:10px 8px;display:flex;flex-direction:column;gap:2px;overflow-y:auto}
    .nav-item{
      display:flex;align-items:center;gap:11px;padding:10px 12px;
      border-radius:var(--r);border:none;background:transparent;
      color:var(--text2);font-size:13.5px;font-weight:500;
      cursor:pointer;width:100%;text-align:left;
      transition:all .15s;white-space:nowrap;position:relative;
    }
    .nav-item:hover{background:var(--surface);color:var(--text)}
    .nav-item.active{
      background:var(--brand-dim);color:var(--brand2);
      box-shadow:inset 3px 0 0 var(--brand);
    }
    .nav-icon{width:18px;height:18px;flex-shrink:0;transition:transform .15s}
    .nav-item:hover .nav-icon{transform:scale(1.1)}
    .nav-label{overflow:hidden;transition:opacity .2s,width .2s}
    .collapsed .nav-label{opacity:0;width:0}

    /* Tooltip on collapsed */
    .collapsed .nav-item::after{
      content:attr(data-label);position:absolute;left:calc(var(--sidebar-collapsed) + 8px);
      background:var(--surface3);border:1px solid var(--border2);color:var(--text);
      padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
      white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .15s;
      box-shadow:var(--shadow-sm);z-index:100;
    }
    .collapsed .nav-item:hover::after{opacity:1}

    .sb-section{
      padding:4px 12px;font-size:10px;font-weight:700;letter-spacing:.08em;
      color:var(--text3);text-transform:uppercase;margin-top:8px;
      white-space:nowrap;overflow:hidden;
    }
    .collapsed .sb-section{opacity:0}

    .sb-footer{padding:12px 8px;border-top:1px solid var(--border);flex-shrink:0}
    .status-chip{
      display:flex;align-items:center;gap:9px;padding:9px 12px;
      background:var(--surface);border:1px solid var(--border);
      border-radius:var(--r);font-size:12px;color:var(--text2);overflow:hidden;
      transition:all .15s;
    }
    .collapsed .status-chip-label{display:none}
    .sdot{
      width:8px;height:8px;border-radius:50%;flex-shrink:0;
      background:var(--green);box-shadow:0 0 6px var(--green);
    }
    .sdot.warn{
      background:var(--amber);box-shadow:0 0 6px var(--amber);
      animation:pulse .8s ease-in-out infinite;
    }
    @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(.85)}}

    /* ═══ MAIN ═══ */
    .main{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden}
    .main{padding-bottom:var(--bottomnav-h)}
    @media(min-width:768px){.main{padding-bottom:0}}

    /* ═══ TOPBAR ═══ */
    .topbar{
      display:flex;align-items:center;justify-content:space-between;
      padding:0 18px;height:var(--topbar-h);
      border-bottom:1px solid var(--border);
      background:rgba(6,11,20,0.8);
      backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
      flex-shrink:0;z-index:5;
    }
    .topbar-left{display:flex;align-items:center;gap:12px}
    .mobile-menu-btn{
      display:flex;background:transparent;border:none;color:var(--text2);
      cursor:pointer;padding:6px;border-radius:9px;transition:all .15s;
    }
    .mobile-menu-btn:hover{background:var(--surface);color:var(--text)}
    .mobile-menu-btn svg{width:20px;height:20px}
    @media(min-width:768px){.mobile-menu-btn{display:none}}
    .page-title{font-size:15px;font-weight:600;letter-spacing:-.01em}
    .topbar-right{display:flex;align-items:center;gap:10px}
    .clock{
      font-size:13px;color:var(--text2);font-variant-numeric:tabular-nums;
      font-weight:500;letter-spacing:.02em;
    }
    .alarm-pill{
      display:flex;align-items:center;gap:6px;padding:5px 11px;
      border-radius:99px;font-size:12px;font-weight:600;
      border:1px solid var(--border);background:var(--surface);color:var(--text2);
      transition:all .2s;cursor:default;
    }
    .alarm-pill.ringing{
      border-color:rgba(245,158,11,.4);background:var(--amber-dim);
      color:var(--amber);box-shadow:0 0 12px rgba(245,158,11,.2);
    }

    /* ═══ BODY ═══ */
    .body{flex:1;overflow-y:auto;padding:20px 18px}
    @media(min-width:640px){.body{padding:24px}}
    .tab-panel.hidden{display:none!important}
    .tab-panel{animation:fadeUp .2s ease both}
    @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}

    /* ═══ MOBILE OVERLAY ═══ */
    .mobile-overlay{
      display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
      z-index:200;backdrop-filter:blur(2px);
    }
    .mobile-overlay.open{display:block}
    .mobile-sidebar{
      position:fixed;left:0;top:0;bottom:0;width:var(--sidebar-w);
      background:var(--sidebar);border-right:1px solid var(--border);
      display:flex;flex-direction:column;z-index:201;
      transform:translateX(-100%);transition:transform .25s cubic-bezier(.4,0,.2,1);
    }
    .mobile-sidebar.open{transform:translateX(0)}
    @media(min-width:768px){.mobile-overlay,.mobile-sidebar{display:none!important}}

    /* ═══ BOTTOM NAV ═══ */
    .bottom-nav{
      display:flex;position:fixed;bottom:0;left:0;right:0;
      height:var(--bottomnav-h);
      background:rgba(6,11,20,0.95);
      border-top:1px solid var(--border);
      backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
      z-index:50;padding-bottom:env(safe-area-inset-bottom);
    }
    @media(min-width:768px){.bottom-nav{display:none}}
    .bn-item{
      flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:4px;background:transparent;border:none;color:var(--text3);
      font-size:10px;font-weight:600;cursor:pointer;transition:all .15s;
      padding-top:4px;letter-spacing:.02em;
    }
    .bn-item svg{width:21px;height:21px;transition:transform .15s}
    .bn-item.active{color:var(--brand2)}
    .bn-item.active svg{transform:scale(1.1)}
    .bn-dot{
      width:4px;height:4px;border-radius:50%;background:var(--brand);
      margin-top:2px;opacity:0;transition:opacity .15s;
    }
    .bn-item.active .bn-dot{opacity:1}

    /* ═══ BUTTONS ═══ */
    .btn{
      display:inline-flex;align-items:center;justify-content:center;gap:7px;
      padding:9px 16px;border:none;border-radius:var(--r);
      font-size:13px;font-weight:600;cursor:pointer;
      transition:all .15s;white-space:nowrap;font-family:inherit;
    }
    .btn:active{transform:scale(.96)}
    .btn svg{width:15px;height:15px}
    .btn-primary{
      background:var(--brand);color:#fff;
      box-shadow:0 0 0 0 var(--brand-glow);
    }
    .btn-primary:hover{background:#3d7af0;box-shadow:0 4px 16px var(--brand-glow)}
    .btn-ghost{
      background:var(--surface2);border:1px solid var(--border);color:var(--text);
    }
    .btn-ghost:hover{background:var(--surface3);border-color:var(--border2)}
    .btn-danger{
      background:var(--red-dim);border:1px solid rgba(239,68,68,.2);
      color:#fca5a5;
    }
    .btn-danger:hover{background:rgba(239,68,68,.22);border-color:rgba(239,68,68,.35)}
    .btn-sm{padding:6px 11px;font-size:12px;border-radius:9px}
    .btn-icon{padding:7px;border-radius:9px}
    .btn-icon svg{width:14px;height:14px}

    /* ═══ INPUTS ═══ */
    .row{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
    input[type=text],input[type=time],textarea{
      flex:1;min-width:0;padding:10px 14px;border-radius:var(--r);
      border:1px solid var(--border);background:var(--surface);
      color:var(--text);font-size:13.5px;outline:none;
      transition:border-color .15s,box-shadow .15s;font-family:inherit;
    }
    input:focus,textarea:focus{
      border-color:var(--brand);
      box-shadow:0 0 0 3px rgba(79,142,255,.12);
    }
    input::placeholder,textarea::placeholder{color:var(--text3)}

    /* ═══ SECTION HEADER ═══ */
    .sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
    .sec-title{font-size:16px;font-weight:700;letter-spacing:-.01em}
    .count-badge{
      font-size:12px;color:var(--text2);background:var(--surface2);
      border:1px solid var(--border);padding:3px 10px;border-radius:99px;font-weight:500;
    }

    /* ═══ DASHBOARD ═══ */
    .dash-hero{
      background:linear-gradient(135deg,rgba(79,142,255,.1) 0%,rgba(139,92,246,.07) 50%,rgba(79,142,255,.04) 100%);
      border:1px solid rgba(79,142,255,.15);border-radius:var(--rx);
      padding:22px;margin-bottom:18px;position:relative;overflow:hidden;
    }
    .dash-hero::before{
      content:"";position:absolute;top:-40px;right:-40px;width:160px;height:160px;
      border-radius:50%;background:radial-gradient(circle,rgba(79,142,255,.15),transparent 70%);
      pointer-events:none;
    }
    .dash-greeting{font-size:22px;font-weight:800;margin-bottom:4px;letter-spacing:-.02em}
    .dash-date{font-size:13px;color:var(--text2);font-weight:500}
    .dash-status-row{display:flex;align-items:center;gap:8px;margin-top:14px}
    .dash-status-badge{
      display:inline-flex;align-items:center;gap:6px;padding:5px 12px;
      border-radius:99px;font-size:12px;font-weight:600;
      background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);color:#4ade80;
    }

    .stats-grid{
      display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:18px;
    }
    @media(min-width:640px){.stats-grid{grid-template-columns:repeat(4,1fr)}}
    .stat-card{
      background:var(--surface);border:1px solid var(--border);border-radius:var(--rl);
      padding:16px;cursor:pointer;transition:all .15s;position:relative;overflow:hidden;
    }
    .stat-card:hover{
      border-color:var(--border2);transform:translateY(-2px);
      box-shadow:var(--shadow-sm);
    }
    .stat-card::after{
      content:"";position:absolute;inset:0;border-radius:var(--rl);
      background:var(--card-glow,transparent);
      opacity:0;transition:opacity .15s;pointer-events:none;
    }
    .stat-card:hover::after{opacity:1}
    .stat-icon{
      width:36px;height:36px;border-radius:10px;display:flex;
      align-items:center;justify-content:center;margin-bottom:10px;
    }
    .stat-icon svg{width:17px;height:17px}
    .stat-val{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
    .stat-lbl{font-size:12px;color:var(--text2);margin-top:2px;font-weight:500}

    .dash-cols{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:18px}
    @media(min-width:900px){.dash-cols{grid-template-columns:1fr 1fr}}
    .dash-section{
      background:var(--surface);border:1px solid var(--border);
      border-radius:var(--rl);padding:16px;
    }
    .dash-section-title{
      font-size:11px;font-weight:700;color:var(--text3);
      text-transform:uppercase;letter-spacing:.07em;margin-bottom:12px;
    }
    .mini-msg{
      padding:8px 0;border-bottom:1px solid var(--border);
      font-size:13px;transition:opacity .1s;
    }
    .mini-msg:last-child{border-bottom:none}
    .mini-msg-role{font-size:11px;color:var(--text3);margin-bottom:3px;font-weight:500}
    .mini-msg-text{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .alarm-row-mini{
      display:flex;align-items:center;gap:12px;padding:8px 0;
      border-bottom:1px solid var(--border);
    }
    .alarm-row-mini:last-child{border-bottom:none}
    .alarm-time-lg{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.02em}

    .tips-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
    .tips-title{font-size:15px;font-weight:700;letter-spacing:-.01em}
    .tips-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
    .tip-card{
      background:var(--surface);border:1px solid var(--border);border-radius:var(--rl);
      padding:16px;transition:all .15s;cursor:default;
    }
    .tip-card:hover{border-color:var(--border2);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
    .tip-icon{
      width:34px;height:34px;border-radius:10px;display:flex;
      align-items:center;justify-content:center;margin-bottom:10px;
    }
    .tip-icon svg{width:16px;height:16px}
    .tip-title{font-size:13px;font-weight:600;margin-bottom:5px}
    .tip-example{font-size:12px;color:var(--text2);font-style:italic;line-height:1.5}

    /* ═══ CHAT ═══ */
    .chat-wrap{display:flex;flex-direction:column;height:calc(100dvh - var(--bottomnav-h) - var(--topbar-h) - 40px)}
    @media(min-width:768px){.chat-wrap{height:calc(100dvh - var(--topbar-h) - 40px)}}
    .messages{
      flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;
      gap:12px;background:var(--surface);border:1px solid var(--border);
      border-radius:var(--rl);margin-bottom:12px;
    }
    .msg{max-width:76%;display:flex;flex-direction:column}
    .msg.user{align-self:flex-end;align-items:flex-end}
    .msg.assistant{align-self:flex-start}
    .msg.system{align-self:center;max-width:92%}
    .bubble{
      padding:10px 14px;border-radius:14px;line-height:1.5;
      white-space:pre-wrap;word-break:break-word;font-size:13.5px;
    }
    .msg.user .bubble{
      background:linear-gradient(135deg,var(--brand),#3d7af0);
      color:#fff;border-bottom-right-radius:4px;
      box-shadow:0 2px 12px rgba(79,142,255,.3);
    }
    .msg.assistant .bubble{
      background:var(--surface2);border:1px solid var(--border);
      border-bottom-left-radius:4px;
    }
    .msg.system .bubble{
      background:transparent;border:1px dashed var(--border2);
      color:var(--text2);font-size:12px;text-align:center;padding:8px 14px;
    }
    .msg-meta{font-size:11px;color:var(--text3);margin-top:4px;padding:0 4px;font-weight:500}
    .chat-bar{
      display:flex;gap:8px;align-items:flex-end;
      background:var(--surface);border:1px solid var(--border);
      border-radius:var(--rl);padding:10px 12px;
      transition:border-color .15s,box-shadow .15s;
    }
    .chat-bar:focus-within{border-color:var(--brand);box-shadow:0 0 0 3px rgba(79,142,255,.1)}
    .chat-bar input{
      flex:1;background:transparent;border:none;padding:2px 0;
      font-size:14px;outline:none;color:var(--text);
    }
    .chat-bar input::placeholder{color:var(--text3)}
    .chat-send{
      background:var(--brand);border:none;border-radius:9px;
      color:#fff;cursor:pointer;padding:8px;display:flex;
      align-items:center;justify-content:center;
      transition:all .15s;flex-shrink:0;
    }
    .chat-send:hover{background:#3d7af0;box-shadow:0 2px 8px var(--brand-glow)}
    .chat-send:active{transform:scale(.92)}
    .chat-send svg{width:17px;height:17px}
    .chat-actions{display:flex;gap:6px;margin-bottom:8px}

    /* Typing indicator */
    .typing{display:flex;gap:4px;align-items:center;padding:14px;animation:fadeUp .2s ease}
    .typing-dot{width:7px;height:7px;border-radius:50%;background:var(--text3);animation:typingBounce 1.2s infinite}
    .typing-dot:nth-child(2){animation-delay:.2s}
    .typing-dot:nth-child(3){animation-delay:.4s}
    @keyframes typingBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}

    /* ═══ LISTS ═══ */
    .list{display:flex;flex-direction:column;gap:8px}
    .item{
      display:flex;align-items:center;gap:13px;padding:13px 16px;
      background:var(--surface);border:1px solid var(--border);
      border-radius:var(--rl);transition:all .15s;
    }
    .item:hover{border-color:var(--border2);box-shadow:var(--shadow-sm)}
    .item-body{flex:1;min-width:0}
    .item-name{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13.5px}
    .item-sub{font-size:12px;color:var(--text2);margin-top:2px}
    .item-actions{display:flex;gap:6px;flex-shrink:0}
    .done .item-name{text-decoration:line-through;color:var(--text3)}
    .done{opacity:.7}
    .empty{
      text-align:center;padding:40px 0;color:var(--text3);font-size:13.5px;
      display:flex;flex-direction:column;align-items:center;gap:10px;
    }
    .empty svg{width:32px;height:32px;opacity:.3}

    /* ═══ NOTES ═══ */
    .notes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
    .note-card{
      padding:15px;background:var(--surface);border:1px solid var(--border);
      border-radius:var(--rl);position:relative;transition:all .15s;
      border-left:3px solid var(--note-accent,var(--border2));
    }
    .note-card:hover{border-color:var(--note-accent,var(--border2));transform:translateY(-1px);box-shadow:var(--shadow-sm)}
    .note-body{font-size:13.5px;line-height:1.55;word-break:break-word;padding-right:24px;color:var(--text)}
    .note-date{font-size:11px;color:var(--text3);margin-top:10px;font-weight:500}
    .note-del{position:absolute;top:10px;right:10px}

    /* ═══ ALARMS ═══ */
    .alarm-form{
      background:var(--surface);border:1px solid var(--border);border-radius:var(--rx);
      padding:20px;margin-bottom:18px;
    }
    .alarm-form-title{font-size:14px;font-weight:700;margin-bottom:16px;letter-spacing:-.01em}
    .form-label{font-size:11px;color:var(--text2);font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em}
    .day-picker{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
    .day-btn{
      padding:6px 13px;border-radius:99px;border:1px solid var(--border);
      background:transparent;color:var(--text2);font-size:12px;font-weight:600;
      cursor:pointer;transition:all .15s;font-family:inherit;
    }
    .day-btn:hover{border-color:var(--border2);color:var(--text)}
    .day-btn.on{
      background:var(--brand-dim);border-color:rgba(79,142,255,.4);
      color:var(--brand2);box-shadow:0 0 8px rgba(79,142,255,.1);
    }
    .day-presets{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
    .alarm-list-time{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
    .alarm-dot-led{width:10px;height:10px;border-radius:50%;flex-shrink:0}
    .alarm-dot-led.on{background:var(--green);box-shadow:0 0 6px var(--green)}
    .alarm-dot-led.off{background:var(--text3)}
    .day-tag{
      display:inline-flex;align-items:center;padding:2px 9px;border-radius:99px;font-size:11px;
      font-weight:600;background:var(--brand-dim);border:1px solid rgba(79,142,255,.2);
      color:var(--brand2);margin:2px 2px 0 0;
    }

    /* ═══ DIVIDER ═══ */
    .divider{height:1px;background:var(--border);margin:16px 0}
  </style>
</head>
<body>

<!-- Mobile overlay -->
<div class="mobile-overlay" id="mobileOverlay"></div>
<aside class="mobile-sidebar" id="mobileSidebar">
  <div class="sb-top">
    <div class="brand-icon">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
    </div>
    <div>
      <div class="brand-text">Cassandra</div>
      <div class="brand-sub">Assistente pessoal</div>
    </div>
  </div>
  <nav class="sb-nav" id="mobileNav"></nav>
</aside>

<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="sb-top">
      <div class="brand-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
      </div>
      <div>
        <div class="brand-text">Cassandra</div>
        <div class="brand-sub">Assistente pessoal</div>
      </div>
      <button class="collapse-btn" id="collapseBtn" title="Recolher">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
    </div>
    <nav class="sb-nav" id="desktopNav"></nav>
    <div class="sb-footer">
      <div class="status-chip">
        <span class="sdot" id="alarmDot"></span>
        <span class="status-chip-label" id="alarmStatusText">Sistema ok</span>
      </div>
    </div>
  </aside>

  <div class="main">
    <header class="topbar">
      <div class="topbar-left">
        <button class="mobile-menu-btn" id="mobileMenuBtn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <span class="page-title" id="pageTitle">Dashboard</span>
      </div>
      <div class="topbar-right">
        <span class="clock" id="clock"></span>
        <span class="alarm-pill" id="alarmPill">
          <span class="sdot" id="alarmPillDot"></span>
          <span id="alarmPillText">Ok</span>
        </span>
      </div>
    </header>

    <div class="body">

      <!-- ══ DASHBOARD ══ -->
      <div class="tab-panel" id="tab-dashboard">
        <div class="dash-hero">
          <div class="dash-greeting" id="dashGreeting">Olá!</div>
          <div class="dash-date" id="dashDate"></div>
          <div class="dash-status-row">
            <span class="dash-status-badge">
              <svg width="8" height="8" viewBox="0 0 8 8"><circle cx="4" cy="4" r="4" fill="#22c55e"/></svg>
              Cassandra ativa
            </span>
          </div>
        </div>

        <div class="stats-grid" id="statsGrid">
          <div class="stat-card" data-goto="todos" style="--card-glow:linear-gradient(135deg,rgba(79,142,255,.05),transparent)">
            <div class="stat-icon" style="background:var(--brand-dim);color:var(--brand2)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
            </div>
            <div class="stat-val" id="statTodos">—</div>
            <div class="stat-lbl">tarefas pendentes</div>
          </div>
          <div class="stat-card" data-goto="notes" style="--card-glow:linear-gradient(135deg,rgba(139,92,246,.05),transparent)">
            <div class="stat-icon" style="background:var(--purple-dim);color:#a78bfa">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            </div>
            <div class="stat-val" id="statNotes">—</div>
            <div class="stat-lbl">notas salvas</div>
          </div>
          <div class="stat-card" data-goto="shopping" style="--card-glow:linear-gradient(135deg,rgba(34,197,94,.05),transparent)">
            <div class="stat-icon" style="background:var(--green-dim);color:#4ade80">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>
            </div>
            <div class="stat-val" id="statShopping">—</div>
            <div class="stat-lbl">itens na lista</div>
          </div>
          <div class="stat-card" data-goto="alarms" style="--card-glow:linear-gradient(135deg,rgba(245,158,11,.05),transparent)">
            <div class="stat-icon" style="background:var(--amber-dim);color:#fbbf24">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>
            </div>
            <div class="stat-val" id="statAlarms">—</div>
            <div class="stat-lbl">alarmes ativos</div>
          </div>
        </div>

        <div class="dash-cols">
          <div class="dash-section">
            <div class="dash-section-title">Últimas mensagens</div>
            <div id="recentChat"><div class="empty" style="padding:16px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>Nenhuma mensagem ainda</div></div>
          </div>
          <div class="dash-section">
            <div class="dash-section-title">Próximos alarmes</div>
            <div id="upcomingAlarms"><div class="empty" style="padding:16px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>Nenhum alarme ativo</div></div>
          </div>
        </div>

        <div>
          <div class="tips-header">
            <span class="tips-title">O que posso fazer</span>
          </div>
          <div class="tips-grid" id="tipsGrid"></div>
        </div>
      </div>

      <!-- ══ CHAT ══ -->
      <div class="tab-panel hidden" id="tab-chat">
        <div class="chat-actions">
          <button class="btn btn-ghost btn-sm" id="clearBtn">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>
            Limpar conversa
          </button>
        </div>
        <div class="chat-wrap">
          <div class="messages" id="messages">
            <div class="empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
              Digite <b>cassandra,</b> para ativar
            </div>
          </div>
          <div class="chat-bar">
            <input id="msgInput" type="text" placeholder="cassandra, o que você pode fazer?"/>
            <button class="chat-send" id="sendBtn" title="Enviar">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
        </div>
      </div>

      <!-- ══ SHOPPING ══ -->
      <div class="tab-panel hidden" id="tab-shopping">
        <div class="sec-hdr">
          <span class="sec-title">Lista de compras</span>
          <span class="count-badge" id="shopCount">0 itens</span>
        </div>
        <div class="row">
          <input id="shopInput" type="text" placeholder="Ex.: leite, pão, café..."/>
          <button class="btn btn-primary" id="shopAdd">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Adicionar
          </button>
        </div>
        <div class="list" id="shopList"></div>
      </div>

      <!-- ══ TODOS ══ -->
      <div class="tab-panel hidden" id="tab-todos">
        <div class="sec-hdr">
          <span class="sec-title">Tarefas</span>
          <span class="count-badge" id="todoCount">0 pendentes</span>
        </div>
        <div class="row">
          <input id="todoInput" type="text" placeholder="Ex.: pagar conta de luz..."/>
          <button class="btn btn-primary" id="todoAdd">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Adicionar
          </button>
        </div>
        <div class="list" id="todoList"></div>
      </div>

      <!-- ══ NOTES ══ -->
      <div class="tab-panel hidden" id="tab-notes">
        <div class="sec-hdr">
          <span class="sec-title">Notas rápidas</span>
          <span class="count-badge" id="noteCount">0 notas</span>
        </div>
        <div class="row">
          <input id="noteInput" type="text" placeholder="Ex.: lembrar de ligar pro médico..."/>
          <button class="btn btn-primary" id="noteAdd">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Anotar
          </button>
        </div>
        <div class="notes-grid" id="noteList"></div>
      </div>

      <!-- ══ ALARMS ══ -->
      <div class="tab-panel hidden" id="tab-alarms">
        <div class="sec-hdr">
          <span class="sec-title">Alarmes</span>
          <span class="count-badge" id="alarmCount">0 alarmes</span>
        </div>
        <div class="alarm-form">
          <div class="alarm-form-title">Novo alarme</div>
          <div class="row">
            <input id="alarmTime" type="time" style="max-width:140px;flex:none"/>
            <input id="alarmLabel" type="text" placeholder="Rótulo (opcional)"/>
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
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary" id="alarmAdd">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Criar alarme
            </button>
            <button class="btn btn-danger" id="alarmStop">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              Parar alarme
            </button>
          </div>
        </div>
        <div class="list" id="alarmList"></div>
      </div>

    </div>
  </div>
</div>

<!-- Bottom nav -->
<nav class="bottom-nav" id="bottomNav"></nav>

<script>
// ── Icons ──
const IC = {
  dashboard:`<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
  chat:     `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  shopping: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>`,
  todos:    `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>`,
  notes:    `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  alarms:   `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>`,
  trash:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`,
  check:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
  undo:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 00-4-4H4"/></svg>`,
  x:        `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
};

const TABS = [
  {id:"dashboard", label:"Dashboard"},
  {id:"chat",      label:"Chat"},
  {id:"shopping",  label:"Compras"},
  {id:"todos",     label:"Tarefas"},
  {id:"notes",     label:"Notas"},
  {id:"alarms",    label:"Alarmes"},
];
const PAGE_TITLES = {
  dashboard:"Dashboard", chat:"Chat",
  shopping:"Compras", todos:"Tarefas",
  notes:"Notas rápidas", alarms:"Alarmes",
};
const DAY_NAMES = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"];
let selDays = [];

// ── Utils ──
const esc = t => (t||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
async function api(path, method="GET", body=null){
  const r = await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):null});
  const d = await r.json();
  if(!r.ok) throw new Error(d.error||"Erro na API");
  return d;
}
function enter(el, fn){ el.addEventListener("keydown", e=>{if(e.key==="Enter") fn()}); }
function fmtTime(ts){ return (ts||"").substring(11,16); }

// ── Build navs ──
function buildNav(container){
  container.innerHTML = TABS.map(t=>
    `<button class="nav-item${t.id==="dashboard"?" active":""}" data-tab="${t.id}" data-label="${t.label}">${IC[t.id]}<span class="nav-label">${t.label}</span></button>`
  ).join("");
  container.querySelectorAll(".nav-item").forEach(b=>b.addEventListener("click",()=>gotoTab(b.dataset.tab)));
}

const BN = document.getElementById("bottomNav");
BN.innerHTML = TABS.map(t=>
  `<button class="bn-item${t.id==="dashboard"?" active":""}" data-tab="${t.id}">
    ${IC[t.id]}<span>${t.label}</span><div class="bn-dot"></div>
  </button>`
).join("");
BN.querySelectorAll(".bn-item").forEach(b=>b.addEventListener("click",()=>gotoTab(b.dataset.tab)));

buildNav(document.getElementById("desktopNav"));
buildNav(document.getElementById("mobileNav"));

// ── Tab switching ──
let currentTab = "dashboard";
function gotoTab(tab){
  currentTab = tab;
  document.querySelectorAll(".tab-panel").forEach(p=>{
    const show = p.id==="tab-"+tab;
    if(show && p.classList.contains("hidden")){
      p.classList.remove("hidden");
      p.style.animation="none";
      p.offsetHeight;
      p.style.animation="";
    } else if(!show){
      p.classList.add("hidden");
    }
  });
  document.querySelectorAll(".nav-item,[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
  document.getElementById("pageTitle").textContent = PAGE_TITLES[tab]||tab;
  closeMobileMenu();
}

// ── Sidebar collapse ──
const sidebar = document.getElementById("sidebar");
if(localStorage.getItem("sbCollapsed")==="1") sidebar.classList.add("collapsed");
document.getElementById("collapseBtn").addEventListener("click",()=>{
  sidebar.classList.toggle("collapsed");
  localStorage.setItem("sbCollapsed",sidebar.classList.contains("collapsed")?"1":"0");
});

// ── Mobile menu ──
const mobileOverlay = document.getElementById("mobileOverlay");
const mobileSidebar = document.getElementById("mobileSidebar");
document.getElementById("mobileMenuBtn").addEventListener("click",()=>{
  mobileOverlay.classList.add("open"); mobileSidebar.classList.add("open");
});
mobileOverlay.addEventListener("click", closeMobileMenu);
function closeMobileMenu(){ mobileOverlay.classList.remove("open"); mobileSidebar.classList.remove("open"); }

// ── Clock + greeting ──
const MONTHS = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"];
const WEEKDAYS = ["Domingo","Segunda-feira","Terça-feira","Quarta-feira","Quinta-feira","Sexta-feira","Sábado"];
function tickClock(){
  const d = new Date();
  document.getElementById("clock").textContent = d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  const h = d.getHours();
  const greet = h<12?"Bom dia ☀️":h<18?"Boa tarde 🌤️":"Boa noite 🌙";
  document.getElementById("dashGreeting").textContent = greet;
  document.getElementById("dashDate").textContent = `${WEEKDAYS[d.getDay()]}, ${d.getDate()} de ${MONTHS[d.getMonth()]} de ${d.getFullYear()}`;
}
setInterval(tickClock,1000); tickClock();

// ── Stat card click ──
document.querySelectorAll(".stat-card[data-goto]").forEach(c=>c.addEventListener("click",()=>gotoTab(c.dataset.goto)));

// ── Tips ──
const TIPS = [
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>`, bg:"var(--amber-dim)",cl:"#fbbf24", title:"Alarmes inteligentes", ex:'"alarme às 7 de segunda a sexta"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`, bg:"var(--brand-dim)",cl:"var(--brand2)", title:"Timers", ex:'"me avisa em 10 minutos"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`, bg:"var(--purple-dim)",cl:"#a78bfa", title:"Notas de voz", ex:'"anota que preciso ligar pro médico"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>`, bg:"var(--green-dim)",cl:"#4ade80", title:"Calculadora", ex:'"quanto é 15% de 200?"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>`, bg:"var(--red-dim)",cl:"#f87171", title:"Volume do sistema", ex:'"volume 70%" / "aumenta o volume"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>`, bg:"var(--green-dim)",cl:"#4ade80", title:"Lista de compras", ex:'"adiciona leite na lista de compras"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>`, bg:"var(--brand-dim)",cl:"var(--brand2)", title:"Tarefas", ex:'"cria tarefa: pagar conta de luz"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s-8-4.5-8-11.8A8 8 0 0112 2a8 8 0 018 8.2c0 7.3-8 11.8-8 11.8z"/><circle cx="12" cy="10" r="3"/></svg>`, bg:"var(--amber-dim)",cl:"#fbbf24", title:"Clima", ex:'"como está o tempo em SP hoje?"'},
];
document.getElementById("tipsGrid").innerHTML = TIPS.map(t=>`
  <div class="tip-card">
    <div class="tip-icon" style="background:${t.bg};color:${t.cl}">${t.svg}</div>
    <div class="tip-title">${t.title}</div>
    <div class="tip-example">${esc(t.ex)}</div>
  </div>`).join("");

// ── Dashboard ──
function renderDashboard(data){
  const todos  = (data.todos||[]).filter(t=>!t.completed).length;
  const notes  = (data.notes||[]).length;
  const shop   = (data.shopping||[]).length;
  const alms   = (data.alarms||[]).filter(a=>a.enabled).length;
  document.getElementById("statTodos").textContent    = todos;
  document.getElementById("statNotes").textContent    = notes;
  document.getElementById("statShopping").textContent = shop;
  document.getElementById("statAlarms").textContent   = alms;

  const msgs = (data.history||[]).filter(m=>m.kind==="chat").slice(-4);
  const rcEl = document.getElementById("recentChat");
  if(!msgs.length) rcEl.innerHTML='<div class="empty" style="padding:14px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>Nenhuma mensagem ainda</div>';
  else rcEl.innerHTML = msgs.map(m=>`
    <div class="mini-msg">
      <div class="mini-msg-role">${m.role==="assistant"?"Cassandra":"Você"} · ${fmtTime(m.timestamp)}</div>
      <div class="mini-msg-text">${esc(m.content)}</div>
    </div>`).join("");

  const active = (data.alarms||[]).filter(a=>a.enabled)
    .sort((a,b)=>a.next_trigger_at.localeCompare(b.next_trigger_at)).slice(0,4);
  const uaEl = document.getElementById("upcomingAlarms");
  if(!active.length) uaEl.innerHTML='<div class="empty" style="padding:14px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>Nenhum alarme ativo</div>';
  else uaEl.innerHTML = active.map(a=>{
    const days = a.days_of_week;
    const dayHtml = days&&days.length
      ? days.map(d=>`<span class="day-tag">${DAY_NAMES[d]}</span>`).join("")
      : a.recurring_daily?'<span class="day-tag">Diário</span>':'<span class="day-tag" style="opacity:.5">Uma vez</span>';
    return `<div class="alarm-row-mini">
      <span class="alarm-time-lg">${esc(a.time_hhmm)}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;color:var(--text2);font-weight:500">${esc(a.label||"Alarme")}</div>
        <div style="margin-top:4px">${dayHtml}</div>
      </div>
    </div>`;
  }).join("");
}

// ── Chat ──
function showTyping(){
  const el=document.getElementById("messages");
  const d=document.createElement("div"); d.className="typing"; d.id="typingIndicator";
  d.innerHTML='<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  el.appendChild(d); el.scrollTop=el.scrollHeight;
}
function hideTyping(){ document.getElementById("typingIndicator")?.remove(); }

function renderMessages(items){
  const el=document.getElementById("messages");
  if(!items.length){
    el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>Digite <b>cassandra,</b> para ativar</div>';
    return;
  }
  el.innerHTML = items.map(m=>{
    const kind=m.kind||"chat";
    const cls=kind!=="chat"?"system":(m.role==="assistant"?"assistant":"user");
    return `<div class="msg ${cls}"><div class="bubble">${esc(m.content)}</div><div class="msg-meta">${fmtTime(m.timestamp)} · ${m.role}</div></div>`;
  }).join("");
  el.scrollTop=el.scrollHeight;
}

// ── Shopping ──
function renderShopping(items){
  const el=document.getElementById("shopList");
  document.getElementById("shopCount").textContent=items.length+(items.length===1?" item":" itens");
  if(!items.length){ el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>Lista vazia</div>'; return; }
  el.innerHTML=items.map(i=>`
    <div class="item">
      <div class="item-body">
        <div class="item-name">${esc(i.name)}</div>
        <div class="item-sub">${esc(i.created_at||"")}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-danger btn-sm btn-icon" data-shop-rm="${i.id}" title="Remover">${IC.trash}</button>
      </div>
    </div>`).join("");
  el.querySelectorAll("[data-shop-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/shopping/remove","POST",{id:b.dataset.shopRm});await refresh();}));
}

// ── Todos ──
function renderTodos(items){
  const el=document.getElementById("todoList");
  const p=items.filter(i=>!i.completed).length;
  document.getElementById("todoCount").textContent=p+" pendente"+(p!==1?"s":"");
  if(!items.length){ el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>Nenhuma tarefa</div>'; return; }
  el.innerHTML=items.map(i=>`
    <div class="item${i.completed?" done":""}">
      <div class="item-body">
        <div class="item-name">${esc(i.title)}</div>
        <div class="item-sub">${i.completed?"Concluída":"Pendente"}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-ghost btn-sm btn-icon" data-todo-tog="${i.id}" data-done="${i.completed}" title="${i.completed?"Reabrir":"Concluir"}">${i.completed?IC.undo:IC.check}</button>
        <button class="btn btn-danger btn-sm btn-icon" data-todo-rm="${i.id}" title="Remover">${IC.x}</button>
      </div>
    </div>`).join("");
  el.querySelectorAll("[data-todo-tog]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/todos/toggle","POST",{id:b.dataset.todoTog,completed:b.dataset.done!=="true"});await refresh();}));
  el.querySelectorAll("[data-todo-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/todos/remove","POST",{id:b.dataset.todoRm});await refresh();}));
}

// ── Notes ──
const NOTE_ACCENTS = ["#4f8eff","#8b5cf6","#22c55e","#f59e0b","#ec4899","#06b6d4"];
function renderNotes(items){
  const el=document.getElementById("noteList");
  document.getElementById("noteCount").textContent=items.length+(items.length===1?" nota":" notas");
  if(!items.length){ el.innerHTML='<div class="empty" style="grid-column:1/-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>Nenhuma nota</div>'; return; }
  el.innerHTML=items.map((n,i)=>{
    const accent=NOTE_ACCENTS[i%NOTE_ACCENTS.length];
    return `<div class="note-card" style="--note-accent:${accent}">
      <button class="btn btn-danger btn-sm btn-icon note-del" data-note-rm="${n.id}" title="Apagar">${IC.x}</button>
      <div class="note-body">${esc(n.content)}</div>
      <div class="note-date">${esc(n.created_at||"")}</div>
    </div>`;
  }).join("");
  el.querySelectorAll("[data-note-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/notes/remove","POST",{id:b.dataset.noteRm});await refresh();}));
}

// ── Alarms ──
function renderAlarms(items){
  const el=document.getElementById("alarmList");
  document.getElementById("alarmCount").textContent=items.length+(items.length===1?" alarme":" alarmes");
  if(!items.length){ el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>Nenhum alarme</div>'; return; }
  el.innerHTML=items.map(a=>{
    const days=a.days_of_week;
    const dayHtml=days&&days.length?days.map(d=>`<span class="day-tag">${DAY_NAMES[d]}</span>`).join(" ")
      :a.recurring_daily?'<span class="day-tag">Todos os dias</span>'
      :'<span class="day-tag" style="opacity:.5">Uma vez</span>';
    return `<div class="item">
      <span class="alarm-dot-led ${a.enabled?"on":"off"}"></span>
      <div class="item-body">
        <div class="item-name">
          <span class="alarm-list-time">${esc(a.time_hhmm)}</span>
          <span style="font-size:13px;font-weight:400;color:var(--text2);margin-left:8px">${esc(a.label||"")}</span>
        </div>
        <div style="margin-top:6px">${dayHtml}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-danger btn-sm btn-icon" data-alarm-rm="${a.id}" title="Remover">${IC.trash}</button>
      </div>
    </div>`;
  }).join("");
  el.querySelectorAll("[data-alarm-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/alarms/remove","POST",{id:b.dataset.alarmRm});await refresh();}));
}

// ── Alarm status ──
function renderAlarmStatus(ringing){
  const d1=document.getElementById("alarmDot"),d2=document.getElementById("alarmPillDot");
  const t1=document.getElementById("alarmStatusText"),t2=document.getElementById("alarmPillText");
  const pill=document.getElementById("alarmPill");
  [d1,d2].forEach(d=>{d.className="sdot"+(ringing?" warn":"")});
  t1.textContent=ringing?"Alarme tocando!":"Sistema ok";
  t2.textContent=ringing?"Alarme!":"Ok";
  pill.className="alarm-pill"+(ringing?" ringing":"");
}

// ── Day picker ──
function setPreset(days){
  selDays=days;
  document.querySelectorAll(".day-btn").forEach(b=>b.classList.toggle("on",Array.isArray(days)&&days.includes(+b.dataset.day)));
}
document.querySelectorAll(".day-btn").forEach(b=>b.addEventListener("click",()=>{
  if(!Array.isArray(selDays)) selDays=[];
  const d=+b.dataset.day;
  selDays=selDays.includes(d)?selDays.filter(x=>x!==d):[...selDays,d].sort((a,b)=>a-b);
  b.classList.toggle("on",selDays.includes(d));
}));

// ── Refresh ──
async function refresh(){
  try{
    const data=await api("/api/dashboard");
    renderDashboard(data);
    renderMessages(data.history||[]);
    renderShopping(data.shopping||[]);
    renderTodos(data.todos||[]);
    renderNotes(data.notes||[]);
    renderAlarms(data.alarms||[]);
    renderAlarmStatus(Boolean(data.alarm_ringing));
  } catch(e){ console.error("Refresh error:",e); }
}

// ── Actions ──
async function sendMsg(){
  const el=document.getElementById("msgInput");
  const t=el.value.trim(); if(!t) return; el.value="";
  const msgs=document.getElementById("messages");
  // Optimistic user bubble
  const div=document.createElement("div"); div.className="msg user";
  div.innerHTML=`<div class="bubble">${esc(t)}</div><div class="msg-meta">agora · user</div>`;
  if(msgs.querySelector(".empty")) msgs.innerHTML="";
  msgs.appendChild(div); msgs.scrollTop=msgs.scrollHeight;
  showTyping();
  try{
    const d=await api("/api/chat","POST",{message:t});
    hideTyping(); renderMessages(d.history||[]);
  } catch(e){ hideTyping(); alert(e.message); }
}
document.getElementById("sendBtn").addEventListener("click",sendMsg);
enter(document.getElementById("msgInput"),sendMsg);
document.getElementById("clearBtn").addEventListener("click",async()=>{await api("/api/reset","POST",{});await refresh();});

const shopInput=document.getElementById("shopInput");
document.getElementById("shopAdd").addEventListener("click",async()=>{const v=shopInput.value.trim();if(!v)return;shopInput.value="";await api("/api/shopping/add","POST",{name:v});await refresh();});
enter(shopInput,()=>document.getElementById("shopAdd").click());

const todoInput=document.getElementById("todoInput");
document.getElementById("todoAdd").addEventListener("click",async()=>{const v=todoInput.value.trim();if(!v)return;todoInput.value="";await api("/api/todos/add","POST",{title:v});await refresh();});
enter(todoInput,()=>document.getElementById("todoAdd").click());

const noteInput=document.getElementById("noteInput");
document.getElementById("noteAdd").addEventListener("click",async()=>{const v=noteInput.value.trim();if(!v)return;noteInput.value="";await api("/api/notes/add","POST",{content:v});await refresh();});
enter(noteInput,()=>document.getElementById("noteAdd").click());

document.getElementById("alarmAdd").addEventListener("click",async()=>{
  const time=document.getElementById("alarmTime").value;
  if(!time){alert("Escolha um horário.");return;}
  const label=document.getElementById("alarmLabel").value||"Alarme";
  const recurring_daily=selDays!==null;
  const days_of_week=(Array.isArray(selDays)&&selDays.length)?selDays:null;
  await api("/api/alarms/add","POST",{time_hhmm:time,recurring_daily,label,days_of_week});
  document.getElementById("alarmLabel").value=""; setPreset([]);
  await refresh();
});
document.getElementById("alarmStop").addEventListener("click",async()=>{await api("/api/alarms/stop","POST",{});await refresh();});

// ── Init ──
refresh();
setInterval(refresh,5000);
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
                    "history":       assistant.get_conversation_history(),
                    "shopping":      assistant.get_shopping_items(),
                    "todos":         assistant.get_todos(),
                    "notes":         assistant.get_notes(),
                    "alarms":        assistant.list_alarms(),
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
                assistant.remove_shopping_item(str(data.get("id", "")).strip())
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
                assistant.remove_todo(str(data.get("id", "")).strip())
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
                assistant.remove_note(str(data.get("id", "")).strip())
                self._send_json({"notes": assistant.get_notes()})
                return

            if parsed.path == "/api/alarms/add":
                data = self._read_json_body()
                time_hhmm = str(data.get("time_hhmm", "")).strip()
                if not time_hhmm:
                    self._send_json({"error": "time_hhmm is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                recurring_daily = bool(data.get("recurring_daily", False))
                label = str(data.get("label", "Alarme")).strip() or "Alarme"
                raw_days = data.get("days_of_week")
                days_of_week = [int(d) for d in raw_days] if isinstance(raw_days, list) else None
                try:
                    assistant.add_alarm(time_hhmm=time_hhmm, recurring_daily=recurring_daily, label=label, days_of_week=days_of_week)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"alarms": assistant.list_alarms()})
                return

            if parsed.path == "/api/alarms/remove":
                data = self._read_json_body()
                assistant.remove_alarm(str(data.get("id", "")).strip())
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
