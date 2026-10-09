from __future__ import annotations

import json
import os
import re
import time
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Type
from urllib.parse import parse_qs, urlencode, urlparse

from cassandra import audio_devices, llm_settings
from cassandra import spotify as spotify_api
from cassandra import network_devices
from cassandra.mic_monitor import monitor as mic_monitor
from cassandra.bt_audio import bt_audio
from cassandra.assistant import CassandraAssistant

HTML_PAGE = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover"/>
  <title>Cassandra · Assistente pessoal</title>
  <!--PERSONA_JS-->
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --bg:#05080f;--sidebar:#07091280;--surface:#0c1220;--surface2:#111827;--surface3:#1a2540;
      --glass:rgba(12,18,32,0.7);--glass2:rgba(17,24,39,0.8);
      --border:rgba(255,255,255,0.055);--border2:rgba(255,255,255,0.1);--border3:rgba(255,255,255,0.15);
      --text:#e2eaff;--text2:#8899b8;--text3:#3d5070;
      /* Cassandra (persona.js): laranja quente → rosa. */
      --brand:#fb923c;--brand2:#fdba74;--brand3:#fed7aa;
      --brand-dim:rgba(251,146,60,0.12);--brand-glow:rgba(251,146,60,0.35);
      --purple:#f472b6;--purple-dim:rgba(244,114,182,0.12);--purple-glow:rgba(244,114,182,0.25);
      --cyan:#22d3ee;--cyan-dim:rgba(34,211,238,0.1);
      --green:#34d399;--green-dim:rgba(52,211,153,0.1);--green-glow:rgba(52,211,153,0.25);
      --amber:#fbbf24;--amber-dim:rgba(251,191,36,0.1);
      --red:#f87171;--red-dim:rgba(248,113,113,0.1);
      --r:12px;--rl:18px;--rx:24px;--rxl:30px;
      --sidebar-w:236px;--sidebar-collapsed:62px;
      --topbar-h:56px;
      --shadow:0 8px 32px rgba(0,0,0,0.6);--shadow-sm:0 2px 12px rgba(0,0,0,0.4);
      --shadow-glow:0 0 40px rgba(251,146,60,0.08);
    }
    html,body{height:100%;overflow:hidden;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
    /* sem zoom: nada de toque duplo/pinça e o iPhone não amplia ao focar um campo (precisa de fonte >= 16px) */
    html{touch-action:manipulation;-webkit-text-size-adjust:100%;text-size-adjust:100%}
    @media(max-width:767px){input,select,textarea{font-size:16px!important}}
    body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
    body::before{content:"";position:fixed;inset:0;background:
      radial-gradient(ellipse 80% 60% at 20% -10%,rgba(251,146,60,0.07) 0%,transparent 60%),
      radial-gradient(ellipse 60% 40% at 80% 100%,rgba(244,114,182,0.06) 0%,transparent 60%),
      radial-gradient(ellipse 40% 40% at 50% 50%,rgba(34,211,238,0.03) 0%,transparent 70%);
      pointer-events:none;z-index:0}
    body>*{position:relative;z-index:1}
    ::-webkit-scrollbar{width:3px;height:3px}
    ::-webkit-scrollbar-track{background:transparent}
    ::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:99px}
    ::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.14)}

    /* ═══ SHELL ═══ */
    .app{display:flex;height:100vh;height:var(--app-h,100dvh);overflow:hidden}
    .sidebar{
      display:none;width:var(--sidebar-w);flex-shrink:0;
      background:var(--sidebar);border-right:1px solid var(--border);
      backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
      flex-direction:column;transition:width .25s cubic-bezier(.4,0,.2,1);overflow:hidden;z-index:10;
    }
    .sidebar.collapsed{width:var(--sidebar-collapsed)}
    @media(min-width:768px){.sidebar{display:flex}}
    .main{flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden;padding-bottom:env(safe-area-inset-bottom)}

    /* ═══ SIDEBAR ═══ */
    .sb-top{display:flex;align-items:center;gap:10px;padding:14px 12px;border-bottom:1px solid var(--border);flex-shrink:0;min-height:var(--topbar-h)}
    .brand-icon{
      width:36px;height:36px;border-radius:11px;flex-shrink:0;
      background:linear-gradient(135deg,#fb923c,#f472b6);
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 0 20px rgba(251,146,60,0.45),0 2px 8px rgba(0,0,0,0.4);
    }
    .brand-icon svg{width:17px;height:17px;color:#fff}
    .brand-face{display:grid;place-items:center;flex-shrink:0;width:40px;height:40px}
    .brand-text{font-style:italic}

    /* ═══ CASSANDRA: bolhas bem redondas, calor, rosto dela no chat ═══ */
    .msg.assistant{flex-direction:row;align-items:flex-end;gap:10px}
    .msg-col{display:flex;flex-direction:column;min-width:0}
    .messages .msg.assistant .bubble{border-radius:24px 24px 24px 8px;background:linear-gradient(150deg,rgba(251,146,60,.14),rgba(244,114,182,.07) 55%,var(--glass2));border-color:rgba(251,146,60,.2)}
    .messages .msg.user .bubble{border-radius:24px 24px 8px 24px}
    .typing .ap-face{margin-right:6px}
    .cass-empty{display:flex;flex-direction:column;align-items:center;gap:10px;padding:40px 0 24px;text-align:center}
    .cass-empty .ce-face{position:relative;display:grid;place-items:center}
    .cass-empty .ce-face::before{content:"";position:absolute;inset:-40%;border-radius:50%;background:radial-gradient(circle,rgba(251,146,60,.32),rgba(244,114,182,.10) 45%,transparent 70%)}
    .cass-empty b{font-size:22px;font-style:italic;background:linear-gradient(90deg,#fff,var(--brand) 50%,var(--purple));-webkit-background-clip:text;background-clip:text;color:transparent}
    .cass-empty span{color:var(--text2);font-size:13.5px}
    .brand-text{font-size:15px;font-weight:800;white-space:nowrap;letter-spacing:-.02em;background:linear-gradient(90deg,var(--brand2),var(--purple));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
    .brand-sub{font-size:10px;color:var(--text3);white-space:nowrap;margin-top:-1px;letter-spacing:.02em;-webkit-text-fill-color:var(--text3)}
    .collapsed .brand-text,.collapsed .brand-sub{display:none}
    .collapse-btn{margin-left:auto;background:transparent;border:none;color:var(--text3);cursor:pointer;padding:5px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;transition:all .15s}
    .collapse-btn:hover{background:var(--surface);color:var(--text2)}
    .collapse-btn svg{width:16px;height:16px;transition:transform .25s}
    .collapsed .collapse-btn svg{transform:rotate(180deg)}
    .sb-nav{flex:1;padding:8px 6px;display:flex;flex-direction:column;gap:1px;overflow-y:auto}
    .nav-section-label{font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.1em;padding:10px 10px 4px;white-space:nowrap;overflow:hidden}
    .collapsed .nav-section-label{opacity:0;height:0;padding:0;overflow:hidden}
    .nav-item{
      display:flex;align-items:center;gap:11px;padding:9px 11px;
      border-radius:var(--r);border:none;background:transparent;
      color:var(--text2);font-size:13px;font-weight:500;cursor:pointer;width:100%;text-align:left;
      transition:all .15s;white-space:nowrap;position:relative;
    }
    .nav-item:hover{background:rgba(255,255,255,.04);color:var(--text)}
    .nav-item.active{
      background:linear-gradient(90deg,var(--brand-dim),rgba(251,146,60,0.06));
      color:var(--brand2);
    }
    .nav-item.active::before{content:"";position:absolute;left:0;top:20%;bottom:20%;width:2.5px;border-radius:99px;background:linear-gradient(180deg,var(--brand),var(--purple))}
    .nav-icon{width:17px;height:17px;flex-shrink:0;transition:all .15s;opacity:.7}
    .nav-item:hover .nav-icon{opacity:1}
    .nav-item.active .nav-icon{opacity:1;filter:drop-shadow(0 0 4px var(--brand-glow))}
    .nav-label{overflow:hidden;transition:opacity .2s}
    .collapsed .nav-label{opacity:0;width:0}
    .collapsed .nav-item::after{
      content:attr(data-label);position:absolute;left:calc(var(--sidebar-collapsed) + 10px);
      background:var(--surface2);border:1px solid var(--border2);color:var(--text);
      padding:5px 12px;border-radius:9px;font-size:12px;font-weight:500;white-space:nowrap;
      pointer-events:none;opacity:0;transition:opacity .15s;box-shadow:var(--shadow);z-index:100;
    }
    .collapsed .nav-item:hover::after{opacity:1}
    .sb-footer{padding:10px 6px;border-top:1px solid var(--border);flex-shrink:0}
    .status-chip{display:flex;align-items:center;gap:9px;padding:9px 11px;background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:var(--r);font-size:12px;color:var(--text2);overflow:hidden}
    .collapsed .status-chip-label{display:none}
    .sdot{width:7px;height:7px;border-radius:50%;flex-shrink:0;background:var(--green);box-shadow:0 0 8px var(--green-glow)}
    .sdot.warn{background:var(--amber);box-shadow:0 0 8px rgba(251,191,36,.4);animation:pulse .9s ease-in-out infinite}
    @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}

    /* ═══ TOPBAR ═══ */
    .conv-btn{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px;border-radius:10px;border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text2);cursor:pointer;font-size:12.5px;font-weight:700;transition:all .15s;flex-shrink:0}
    .conv-btn svg{width:15px;height:15px}
    .conv-btn:hover{border-color:var(--border2);color:var(--text)}
    .conv-btn.on{border-color:rgba(52,211,153,.5);background:rgba(52,211,153,.14);color:#6ee7b7}
    .conv-btn.on .conv-dot{display:inline-block}
    .conv-dot{display:none;width:7px;height:7px;border-radius:99px;background:#34d399;animation:tpBlink 1.4s ease-in-out infinite}
    @media(max-width:640px){.conv-btn .conv-label{display:none}.conv-btn{padding:0 9px}}
    .restart-btn{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:10px;border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text2);cursor:pointer;transition:all .15s;flex-shrink:0}
    .restart-btn:hover{color:var(--text);border-color:var(--border2);background:rgba(255,255,255,.08)}
    .restart-btn svg{width:16px;height:16px}
    .restart-btn.spinning svg{animation:spin 1s linear infinite}
    @keyframes spin{to{transform:rotate(360deg)}}
    .restart-overlay{position:fixed;inset:0;z-index:200;display:none;align-items:center;justify-content:center;background:rgba(5,8,15,.82);backdrop-filter:blur(6px)}
    .restart-overlay.show{display:flex}
    .restart-box{text-align:center;padding:24px;max-width:320px}
    .restart-box svg{width:34px;height:34px;color:var(--brand2);animation:spin 1s linear infinite;margin-bottom:12px}
    .restart-box div{font-weight:700;font-size:15px}
    .restart-box p{color:var(--text2);font-size:13px;margin-top:6px}
    .topbar{
      display:flex;align-items:center;justify-content:space-between;
      padding:0 20px;height:var(--topbar-h);
      border-bottom:1px solid var(--border);
      background:rgba(5,8,15,0.7);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      flex-shrink:0;z-index:5;
    }
    .topbar-left{display:flex;align-items:center;gap:12px}
    .mobile-menu-btn{display:flex;background:transparent;border:none;color:var(--text2);cursor:pointer;padding:6px;border-radius:9px;transition:all .15s}
    .mobile-menu-btn:hover{background:var(--surface);color:var(--text)}
    .mobile-menu-btn svg{width:20px;height:20px}
    @media(min-width:768px){.mobile-menu-btn{display:none}}
    .page-title{font-size:15px;font-weight:700;letter-spacing:-.02em}
    .topbar-right{display:flex;align-items:center;gap:10px}
    .clock{font-size:13px;color:var(--text2);font-variant-numeric:tabular-nums;font-weight:500;letter-spacing:.02em}
    .alarm-pill{display:flex;align-items:center;gap:6px;padding:5px 12px;border-radius:99px;font-size:11.5px;font-weight:600;border:1px solid var(--border);background:rgba(255,255,255,.03);color:var(--text2);transition:all .2s}
    .timer-pills{display:flex;align-items:center;gap:6px}
    .timer-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 6px 4px 10px;border-radius:99px;font-size:12.5px;font-weight:700;border:1px solid rgba(96,165,250,.35);background:rgba(96,165,250,.12);color:#93c5fd;font-variant-numeric:tabular-nums;white-space:nowrap}
    .timer-pill svg{width:13px;height:13px;flex-shrink:0}
    .timer-pill .tp-x{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:99px;border:0;background:transparent;color:inherit;cursor:pointer;opacity:.7;font-size:15px;line-height:1}
    .timer-pill .tp-x:hover{opacity:1;background:rgba(255,255,255,.1)}
    .timer-pill.fired{border-color:rgba(251,191,36,.45);background:var(--amber-dim);color:var(--amber);animation:tpBlink 1s ease-in-out infinite}
    @keyframes tpBlink{50%{opacity:.55}}
    @media(max-width:640px){.timer-pill .tp-label{display:none}.topbar-right .clock.has-timers{display:none}}
    .alarm-toast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,140%);z-index:300;display:flex;align-items:center;gap:14px;padding:14px 14px 14px 18px;border-radius:16px;border:1px solid rgba(251,191,36,.45);background:#1c1508;color:var(--text);box-shadow:0 12px 40px rgba(0,0,0,.55),0 0 28px rgba(251,191,36,.18);transition:transform .25s ease;width:max-content;max-width:calc(100vw - 32px)}
    .alarm-toast.show{transform:translate(-50%,0)}
    .alarm-toast .at-icon{width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:var(--amber-dim);color:var(--amber);flex-shrink:0;animation:atRing 1s ease-in-out infinite}
    .alarm-toast .at-icon svg{width:20px;height:20px}
    .alarm-toast .at-text{min-width:0}
    .alarm-toast .at-title{font-weight:700;font-size:14px;color:var(--amber)}
    .alarm-toast .at-sub{font-size:12.5px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .alarm-toast .at-stop{border:0;border-radius:12px;padding:11px 16px;font-weight:700;font-size:14px;background:var(--amber);color:#1a1204;cursor:pointer;flex-shrink:0;white-space:nowrap}
    .alarm-toast .at-stop:disabled{opacity:.6}
    @keyframes atRing{0%,100%{transform:rotate(0)}20%{transform:rotate(-14deg)}40%{transform:rotate(12deg)}60%{transform:rotate(-8deg)}80%{transform:rotate(5deg)}}
    @media(max-width:640px){.alarm-toast{bottom:16px;width:calc(100vw - 32px)}.alarm-toast .at-text{flex:1}}
    .alarm-pill.ringing{border-color:rgba(251,191,36,.35);background:var(--amber-dim);color:var(--amber);box-shadow:0 0 16px rgba(251,191,36,.15)}
    button.alarm-pill{font-family:inherit;cursor:default}
    button.alarm-pill.ringing{cursor:pointer;font-size:12.5px;font-weight:700;padding:6px 14px;background:var(--amber);color:#1a1204;border-color:var(--amber);animation:tpBlink 1s ease-in-out infinite}
    button.alarm-pill.ringing .sdot{background:#1a1204!important;box-shadow:none}
    button.alarm-pill.ringing:hover{animation:none;filter:brightness(1.08)}

    /* ═══ BODY ═══ */
    .body{flex:1;overflow-y:auto;padding:20px 18px calc(40px + env(safe-area-inset-bottom));-webkit-overflow-scrolling:touch}
    @media(min-width:640px){.body{padding:24px 22px calc(40px + env(safe-area-inset-bottom))}}
    .tab-panel.hidden{display:none!important}
    .tab-panel{animation:fadeUp .22s cubic-bezier(.4,0,.2,1) both}
    @keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

    /* ═══ MOBILE OVERLAY ═══ */
    .mobile-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;backdrop-filter:blur(4px)}
    .mobile-overlay.open{display:block}
    .mobile-sidebar{position:fixed;left:0;top:0;bottom:0;width:var(--sidebar-w);background:rgba(7,9,18,0.95);border-right:1px solid var(--border);backdrop-filter:blur(24px);display:flex;flex-direction:column;z-index:201;transform:translateX(-100%);transition:transform .28s cubic-bezier(.4,0,.2,1)}
    .mobile-sidebar.open{transform:translateX(0)}
    @media(min-width:768px){.mobile-overlay,.mobile-sidebar{display:none!important}}

    /* ═══ BOTTOM NAV ═══ */

    /* ═══ BUTTONS ═══ */
    .btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:9px 16px;border:none;border-radius:var(--r);font-size:13px;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap;font-family:inherit;letter-spacing:-.01em}
    .btn:active{transform:scale(.95)}
    .btn svg{width:14px;height:14px}
    .btn-primary{background:linear-gradient(135deg,var(--brand),#4880e8);color:#fff;box-shadow:0 2px 12px rgba(251,146,60,.25)}
    .btn-primary:hover{background:linear-gradient(135deg,#fdba74,#f97316);box-shadow:0 4px 20px var(--brand-glow)}
    .btn-ghost{background:rgba(255,255,255,.04);border:1px solid var(--border);color:var(--text)}
    .btn-ghost:hover{background:rgba(255,255,255,.07);border-color:var(--border2)}
    .btn-danger{background:var(--red-dim);border:1px solid rgba(248,113,113,.18);color:#fca5a5}
    .btn-danger:hover{background:rgba(248,113,113,.18);border-color:rgba(248,113,113,.3)}
    .btn-warn{background:var(--amber-dim);border:1px solid rgba(251,191,36,.2);color:#fbbf24}
    .btn-warn:hover{background:rgba(251,191,36,.18)}
    .btn-sm{padding:6px 12px;font-size:12px;border-radius:8px}
    .btn-icon{padding:7px;border-radius:9px}
    .btn-icon svg{width:14px;height:14px}

    /* ═══ INPUTS ═══ */
    .row{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
    input[type=text],input[type=time],input[type=number],input[type=date],input[type=email],input[type=password],select,textarea{
      flex:1;min-width:0;padding:10px 14px;border-radius:var(--r);
      border:1px solid var(--border);
      background:rgba(255,255,255,.03);color:var(--text);font-size:13.5px;outline:none;
      transition:border-color .15s,box-shadow .15s,background .15s;font-family:inherit;
    }
    input:focus,select:focus,textarea:focus{
      border-color:rgba(251,146,60,.5);
      box-shadow:0 0 0 3px rgba(251,146,60,.1);
      background:rgba(251,146,60,.04);
    }
    input::placeholder,textarea::placeholder{color:var(--text3)}
    select option{background:var(--surface2)}

    /* ═══ SECTION HEADER ═══ */
    .sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
    .sec-title{font-size:17px;font-weight:800;letter-spacing:-.03em}
    .count-badge{font-size:11.5px;color:var(--text2);background:rgba(255,255,255,.04);border:1px solid var(--border);padding:3px 11px;border-radius:99px;font-weight:600}

    /* ═══ HÁBITOS ═══ a grade do ano (uma coluna por semana, de segunda a domingo) e o registro de hoje */
    .hb-row{padding:14px 0;border-bottom:1px solid var(--border)}
    .hb-row:last-child{border-bottom:none;padding-bottom:2px}
    .hb-row:first-child{padding-top:2px}
    .hb-head{display:flex;align-items:center;gap:9px;margin-bottom:9px}
    .hb-dot{flex:none;width:18px;height:18px;border-radius:50%;background:var(--hc);display:grid;place-items:center;color:#0b1220;font-size:11px;font-weight:900}
    .hb-name{flex:1;min-width:0;font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .hb-name small{font-weight:500;color:var(--text2);font-size:12.5px}
    .hb-pct{font-weight:800;font-size:15px;font-variant-numeric:tabular-nums;color:var(--hc)}
    .hb-meta{font-size:11.5px;color:var(--text3);font-weight:600;white-space:nowrap}
    .hb-edit{background:none;border:none;color:var(--text3);cursor:pointer;padding:4px 6px;border-radius:7px;font-size:13px}
    .hb-edit:hover{background:rgba(255,255,255,.06);color:var(--text)}
    .hb-grid{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,1fr);grid-auto-columns:minmax(0,1fr);gap:2px;max-width:960px}
    .hb-cell{aspect-ratio:1;border-radius:22%;background:rgba(255,255,255,.055);min-width:0}
    .hb-cell.on{background:var(--hc);cursor:pointer}
    .hb-cell.l1{opacity:.3}.hb-cell.l2{opacity:.5}.hb-cell.l3{opacity:.72}
    .hb-cell.open{cursor:pointer}.hb-cell.open:hover{background:rgba(255,255,255,.16)}
    .hb-cell.skip{background:rgba(255,255,255,.022)}
    .hb-cell.future{background:rgba(255,255,255,.022)}
    .hb-cell.out{visibility:hidden}
    .hb-cell.today{box-shadow:0 0 0 1.5px var(--text)}
    .hb-months{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:2px;margin-top:5px;max-width:960px;font-size:9.5px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
    .hb-months span{white-space:nowrap;overflow:visible}
    .hb-today{display:grid;grid-template-columns:38px 1fr auto;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}
    .hb-today:last-child{border-bottom:none}
    .hb-check{width:38px;height:38px;border-radius:12px;border:2px solid var(--hc);background:transparent;color:var(--hc);cursor:pointer;font-size:17px;font-weight:900;display:grid;place-items:center;transition:all .15s;font-family:inherit}
    .hb-check.done{background:var(--hc);color:#0b1220}
    .hb-check:active{transform:scale(.92)}
    .hb-today b{display:block;font-weight:700;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .hb-today small{display:block;font-size:12px;color:var(--text2)}
    .hb-bar{height:5px;border-radius:99px;background:rgba(255,255,255,.07);margin-top:6px;overflow:hidden;max-width:260px}
    .hb-bar i{display:block;height:100%;border-radius:99px;background:var(--hc);transition:width .3s}
    .hb-step{display:flex;align-items:center;gap:6px}
    .hb-step button{width:30px;height:30px;border-radius:9px;border:1px solid var(--border2);background:rgba(255,255,255,.04);color:var(--text);cursor:pointer;font-size:16px;font-weight:700;font-family:inherit}
    .hb-step button:hover{border-color:var(--hc);color:var(--hc)}
    .hb-streak{font-size:12px;font-weight:700;color:var(--text2);white-space:nowrap;min-width:44px;text-align:right}
    .hb-bars{display:flex;align-items:flex-end;gap:8px;height:150px}
    .hb-bars .c{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;min-width:0}
    .hb-bars .c small{font-size:10.5px;font-weight:700;color:var(--text2);margin-bottom:4px}
    .hb-bars .c i{width:68%;max-width:36px;min-height:2px;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,var(--brand2),var(--brand))}
    .hb-bars .c.none i{background:rgba(255,255,255,.07)}
    .hb-bars .c.best i{box-shadow:0 0 16px var(--brand-glow)}
    .hb-bars-x{display:flex;gap:8px;margin-top:7px}
    .hb-bars-x span{flex:1;text-align:center;font-size:10.5px;font-weight:600;color:var(--text3);min-width:0}
    .hb-modal{position:fixed;inset:0;z-index:90;display:grid;place-items:center;padding:16px;background:rgba(2,5,12,.72);backdrop-filter:blur(6px)}
    .hb-modal.hidden{display:none}
    .hb-box{width:min(480px,100%);max-height:calc(100dvh - 32px);overflow-y:auto;background:var(--surface);border:1px solid var(--border2);border-radius:var(--rx);padding:22px;box-shadow:var(--shadow)}
    .hb-box h3{font-size:17px;font-weight:800;letter-spacing:-.02em;margin-bottom:14px}
    .hb-box label{display:block;font-size:12px;font-weight:600;color:var(--text2);margin:14px 0 6px}
    .hb-box input,.hb-box select{width:100%}
    .hb-two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .hb-sw{display:flex;gap:8px;flex-wrap:wrap}
    .hb-sw button{width:30px;height:30px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0}
    .hb-sw button.on{border-color:#fff;box-shadow:0 0 0 2px var(--bg)}
    .hb-days{display:flex;gap:6px;flex-wrap:wrap}
    .hb-days button{padding:7px 0;width:42px;border-radius:9px;border:1px solid var(--border2);background:rgba(255,255,255,.03);color:var(--text2);cursor:pointer;font-size:12px;font-weight:700;font-family:inherit}
    .hb-days button.on{background:var(--brand-dim);border-color:var(--brand);color:var(--brand2)}
    .hb-foot{display:flex;gap:8px;justify-content:flex-end;margin-top:20px}
    .hb-foot .btn-danger{margin-right:auto}

    /* ═══ DASHBOARD ═══ */
    .dash-hero{
      background:linear-gradient(135deg,rgba(251,146,60,.09),rgba(244,114,182,.07),rgba(34,211,238,.04));
      border:1px solid rgba(251,146,60,.14);border-radius:var(--rxl);
      padding:24px 26px;margin-bottom:20px;position:relative;overflow:hidden;
    }
    .dash-hero::before{content:"";position:absolute;top:-60px;right:-60px;width:220px;height:220px;border-radius:50%;background:radial-gradient(circle,rgba(251,146,60,.12),transparent 70%);pointer-events:none}
    .dash-hero::after{content:"";position:absolute;bottom:-40px;left:30%;width:160px;height:160px;border-radius:50%;background:radial-gradient(circle,rgba(244,114,182,.08),transparent 70%);pointer-events:none}
    .dash-greeting{font-size:26px;font-weight:900;margin-bottom:5px;letter-spacing:-.04em;background:linear-gradient(135deg,var(--text),var(--brand3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
    .dash-face{float:right;margin:-6px -4px 0 12px;position:relative;z-index:1}
    .dash-face .brand-face{width:92px;height:92px}
    @media(max-width:520px){.dash-face{float:none;margin:0 0 8px}}
    .dash-date{font-size:13px;color:var(--text2);font-weight:500;letter-spacing:.01em}
    .dash-status-row{display:flex;align-items:center;gap:8px;margin-top:16px;flex-wrap:wrap}
    .dash-status-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 13px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.2);color:var(--green)}
    .stats-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:20px}
    @media(min-width:640px){.stats-grid{grid-template-columns:repeat(3,1fr)}}
    .stat-card{
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);
      padding:18px;cursor:pointer;transition:all .2s;position:relative;overflow:hidden;
      backdrop-filter:blur(12px);
    }
    .stat-card:hover{border-color:var(--border2);transform:translateY(-3px);box-shadow:var(--shadow-sm),0 0 20px rgba(251,146,60,.06)}
    .stat-card::after{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,.03),transparent);pointer-events:none}
    .stat-icon{width:38px;height:38px;border-radius:11px;display:flex;align-items:center;justify-content:center;margin-bottom:12px}
    .stat-icon svg{width:17px;height:17px}
    .stat-val{font-size:28px;font-weight:900;font-variant-numeric:tabular-nums;letter-spacing:-.04em}
    .stat-lbl{font-size:12px;color:var(--text2);margin-top:3px;font-weight:500}
    .dash-cols{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:20px}
    @media(min-width:900px){.dash-cols{grid-template-columns:1fr 1fr}}
    .dash-section{background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);padding:18px;backdrop-filter:blur(12px)}
    .dash-section-title{font-size:10.5px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.09em;margin-bottom:14px}
    .mini-msg{padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}
    .mini-msg:last-child{border-bottom:none}
    .mini-msg-role{font-size:10.5px;color:var(--text3);margin-bottom:3px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
    .mini-msg-text{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .alarm-row-mini{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--border)}
    .alarm-row-mini:last-child{border-bottom:none}
    .alarm-time-lg{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
    .cost-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:14px}
    .cost-chart{width:100%;height:190px;display:block}
    .cost-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--text2);margin-top:8px}
    .cost-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
    .cost-table{width:100%;border-collapse:collapse;font-size:12.5px}
    .cost-table td,.cost-table th{padding:7px 6px;border-bottom:1px solid var(--border);text-align:left}
    .cost-table th{font-size:10.5px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;font-weight:700}
    .cost-table td.num,.cost-table th.num{text-align:right;font-variant-numeric:tabular-nums}
    .cost-bar{height:7px;border-radius:99px;background:var(--border2);overflow:hidden;margin-top:6px}
    .cost-bar>div{height:100%;background:var(--brand)}
    .cost-note{font-size:12px;color:var(--text3);margin-top:10px;line-height:1.5}
    .tips-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
    .tip-card{
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);
      padding:18px;transition:all .2s;backdrop-filter:blur(12px);position:relative;overflow:hidden;
    }
    .tip-card:hover{border-color:var(--border2);transform:translateY(-2px);box-shadow:var(--shadow-sm)}
    .tip-card::after{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,.025),transparent);pointer-events:none}
    .tip-icon{width:36px;height:36px;border-radius:11px;display:flex;align-items:center;justify-content:center;margin-bottom:12px}
    .tip-icon svg{width:16px;height:16px}
    .tip-title{font-size:13px;font-weight:700;margin-bottom:6px;letter-spacing:-.01em}
    .tip-example{font-size:12px;color:var(--text2);font-style:italic;line-height:1.6}

    /* ═══ CHAT ═══ */
    .chat-wrap{display:flex;flex-direction:column;height:calc(var(--app-h,100dvh) - var(--topbar-h) - 112px - env(safe-area-inset-bottom));min-height:260px}
    @media(min-width:640px){.chat-wrap{height:calc(var(--app-h,100dvh) - var(--topbar-h) - 120px - env(safe-area-inset-bottom))}}
    #tab-chat{padding-bottom:0}
    .messages{
      flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:14px;
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);margin-bottom:12px;
      backdrop-filter:blur(12px);
    }
    .msg{max-width:76%;display:flex;flex-direction:column}
    .msg.user{align-self:flex-end;align-items:flex-end}
    .msg.assistant{align-self:flex-start}
    .msg.system{align-self:center;max-width:92%}
    .bubble{padding:11px 16px;border-radius:16px;line-height:1.6;white-space:pre-wrap;word-break:break-word;font-size:13.5px}
    .msg.user .bubble{background:linear-gradient(135deg,var(--brand),#ec4899);color:#fff;border-bottom-right-radius:4px;box-shadow:0 2px 16px rgba(251,146,60,.25)}
    .msg.assistant .bubble{background:var(--glass2);border:1px solid var(--border);border-bottom-left-radius:4px;backdrop-filter:blur(8px)}
    .msg.system .bubble{background:transparent;border:1px dashed var(--border2);color:var(--text2);font-size:12px;text-align:center;padding:8px 16px}
    .msg-meta{font-size:10.5px;color:var(--text3);margin-top:5px;padding:0 4px;font-weight:600;letter-spacing:.02em}
    .chat-bar{
      display:flex;gap:8px;align-items:flex-end;
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);
      padding:10px 12px;transition:border-color .15s,box-shadow .15s;
      backdrop-filter:blur(12px);
    }
    .chat-bar:focus-within{border-color:rgba(251,146,60,.4);box-shadow:0 0 0 3px rgba(251,146,60,.08)}
    .chat-bar textarea{flex:1;overflow-y:hidden;background:transparent;border:none;padding:6px 0;font-size:15px;line-height:1.45;outline:none;color:var(--text);resize:none;max-height:140px;min-height:24px;box-shadow:none!important;font-family:inherit}
    .chat-bar textarea:focus{background:transparent;box-shadow:none}
    .chat-bar textarea::placeholder{color:var(--text3)}
    @media(max-width:640px){.msg{max-width:88%}.bubble{font-size:15px;padding:10px 14px}.messages{padding:14px}}
    .chat-send{background:linear-gradient(135deg,var(--brand),#ec4899);border:none;border-radius:10px;color:#fff;cursor:pointer;padding:9px;display:flex;align-items:center;justify-content:center;transition:all .15s;flex-shrink:0;box-shadow:0 2px 8px rgba(251,146,60,.3)}
    .chat-send:hover{box-shadow:0 4px 16px var(--brand-glow);transform:scale(1.04)}
    .chat-send:active{transform:scale(.9)}
    .chat-send svg{width:17px;height:17px}
    .typing{display:flex;gap:5px;align-items:center;padding:14px;animation:fadeUp .2s ease}
    .typing-dot{width:7px;height:7px;border-radius:50%;background:var(--text3);animation:typingBounce 1.3s infinite}
    .typing-dot:nth-child(2){animation-delay:.22s}
    .typing-dot:nth-child(3){animation-delay:.44s}
    @keyframes typingBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-7px)}}

    /* ═══ LISTS ═══ */
    .list{display:flex;flex-direction:column;gap:8px}
    .item{
      display:flex;align-items:center;gap:13px;padding:13px 16px;
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);
      transition:all .15s;backdrop-filter:blur(8px);
    }
    .item:hover{border-color:var(--border2);box-shadow:var(--shadow-sm)}
    .item-body{flex:1;min-width:0}
    .item-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13.5px;letter-spacing:-.01em}
    .item-sub{font-size:12px;color:var(--text2);margin-top:2px}
    .item-actions{display:flex;gap:6px;flex-shrink:0}
    .done .item-name{text-decoration:line-through;color:var(--text3)}
    .done{opacity:.6}
    .empty{text-align:center;padding:48px 0;color:var(--text3);font-size:13.5px;display:flex;flex-direction:column;align-items:center;gap:12px}
    .empty svg{width:36px;height:36px;opacity:.2}

    /* ═══ FORM SECTIONS ═══ */
    .alarm-form{
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);
      padding:22px;margin-bottom:20px;backdrop-filter:blur(12px);position:relative;overflow:hidden;
    }
    .alarm-form::after{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,.025),transparent);pointer-events:none}
    .alarm-form-title{font-size:14px;font-weight:700;margin-bottom:18px;letter-spacing:-.02em}
    .form-label{font-size:10.5px;color:var(--text2);font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:.08em}
    .day-picker{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
    .day-btn{
      padding:6px 14px;border-radius:99px;border:1px solid var(--border);
      background:transparent;color:var(--text2);font-size:12px;font-weight:600;
      cursor:pointer;transition:all .15s;font-family:inherit;
    }
    .day-btn:hover{border-color:var(--border2);color:var(--text)}
    .day-btn.on{background:var(--brand-dim);border-color:rgba(251,146,60,.35);color:var(--brand2)}
    .day-presets{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
    .alarm-list-time{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
    .alarm-dot-led{width:10px;height:10px;border-radius:50%;flex-shrink:0}
    .alarm-dot-led.on{background:var(--green);box-shadow:0 0 8px var(--green-glow)}
    .alarm-dot-led.off{background:var(--text3)}
    .day-tag{display:inline-flex;align-items:center;padding:2px 9px;border-radius:99px;font-size:11px;font-weight:600;background:var(--brand-dim);border:1px solid rgba(251,146,60,.2);color:var(--brand2);margin:2px 2px 0 0}

    /* ═══ ALARM CALENDAR ═══ */
    .alm-page{display:flex;flex-direction:column;gap:16px}
    @media(min-width:980px){.alm-page{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);align-items:start}}
    .alm-cal{
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);
      padding:16px 16px 14px;backdrop-filter:blur(12px);position:relative;overflow:hidden;
    }
    .alm-cal.pulse{box-shadow:0 0 0 2px var(--brand),0 0 28px var(--brand-glow)}
    .alm-cal-head{display:flex;align-items:center;gap:6px;margin-bottom:12px}
    .alm-cal-nav{
      width:34px;height:34px;border-radius:10px;border:1px solid var(--border);
      background:rgba(255,255,255,.03);color:var(--text);cursor:pointer;
      display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;font-family:inherit;
    }
    .alm-cal-nav:hover{border-color:var(--brand);color:var(--brand2)}
    .alm-cal-title{
      flex:1;text-align:center;background:none;border:0;color:var(--text);
      font:700 15px inherit;cursor:pointer;letter-spacing:-.02em;padding:6px 8px;border-radius:10px;
    }
    .alm-cal-title:hover{color:var(--brand2);background:var(--brand-dim)}
    .alm-cal-picker{
      margin-bottom:12px;padding:12px;border:1px solid var(--border);border-radius:14px;
      background:rgba(5,8,15,.55);
    }
    .alm-cal-picker-years{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:12px}
    .alm-cal-picker-year{font-size:20px;font-weight:800;letter-spacing:-.03em;min-width:76px;text-align:center}
    .alm-cal-picker-months{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
    .alm-cal-month-btn{
      border:1px solid var(--border);background:rgba(255,255,255,.03);color:var(--text2);
      border-radius:10px;padding:10px 6px;font:700 12px inherit;cursor:pointer;
    }
    .alm-cal-month-btn:hover{border-color:var(--brand);color:var(--brand2)}
    .alm-cal-month-btn.on{background:var(--brand-dim);border-color:rgba(251,146,60,.45);color:var(--brand2)}
    .alm-cal-dow,.alm-cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
    .alm-cal-dow{margin-bottom:4px}
    .alm-cal-dow span{text-align:center;font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;padding:2px 0}
    .alm-cal-cell{
      position:relative;min-height:46px;border:0;background:transparent;border-radius:11px;
      color:var(--text);font:700 13px inherit;cursor:pointer;
      display:flex;flex-direction:column;align-items:center;padding:5px 0 4px;
    }
    .alm-cal-cell:hover{background:var(--brand-dim)}
    .alm-cal-cell.out{color:var(--text3);opacity:.45}
    .alm-cal-cell.today{background:var(--brand-dim);color:var(--brand2)}
    .alm-cal-cell.selected{box-shadow:inset 0 0 0 1.5px var(--brand);background:rgba(251,146,60,.16)}
    .alm-cal-cell.past:not(.today){opacity:.55}
    .alm-cal-cell.has-alarms:not(.selected):not(.today){background:rgba(251,146,60,.08)}
    .alm-cal-cell.has-draft:not(.selected){background:rgba(251,191,36,.14)}
    .alm-cal-dots{display:flex;gap:2px;justify-content:center;min-height:6px;margin-top:3px}
    .alm-cal-more{font-size:9px;font-weight:700;color:var(--text2)}
    .alm-dot{width:5px;height:5px;border-radius:50%;display:inline-block}
    .alm-dot.saved{background:var(--brand)}
    .alm-dot.draft{background:var(--amber)}
    .alm-dot.off{background:var(--text3)}
    .alm-cal-legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:11px;font-weight:700;color:var(--text2)}
    .alm-cal-legend span{display:inline-flex;align-items:center;gap:5px}
    .alm-cal-agenda{margin-top:12px;display:flex;flex-direction:column;gap:6px}
    .alm-agenda-day{font-size:11px;font-weight:700;color:var(--text2)}
    .alm-agenda-item{
      display:flex;align-items:center;gap:8px;width:100%;text-align:left;
      background:rgba(255,255,255,.03);border:1px solid var(--border);
      border-radius:10px;padding:8px 10px;color:inherit;font:inherit;cursor:pointer;
    }
    .alm-agenda-item:hover{border-color:var(--brand)}
    .alm-agenda-item.draft{border-color:rgba(251,191,36,.45)}
    .alm-agenda-time{font-size:13px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--brand2);min-width:44px}
    .alm-agenda-item.draft .alm-agenda-time{color:var(--amber)}
    .alm-agenda-task{flex:1;min-width:0;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .alm-type-pills,.alm-time-pills{display:grid;gap:6px}
    .alm-type-pills{grid-template-columns:1fr 1fr}
    .alm-time-pills{grid-template-columns:repeat(3,1fr)}
    .alm-type-pill,.alm-time-pill{
      background:rgba(255,255,255,.03);color:var(--text2);border:1px solid var(--border);
      border-radius:10px;padding:8px 6px;font:700 12px inherit;cursor:pointer;
    }
    .alm-type-pill.active,.alm-time-pill.active{background:var(--brand-dim);color:var(--brand2);border-color:rgba(251,146,60,.45)}
    .alm-picked{
      background:rgba(255,255,255,.03);border:1px dashed rgba(251,146,60,.4);
      border-radius:10px;padding:8px 11px;color:var(--text);font:700 13px inherit;
      width:100%;text-align:left;cursor:pointer;
    }
    .alm-picked:hover{border-style:solid;border-color:var(--brand);color:var(--brand2)}
    .alm-preview{
      background:var(--brand-dim);border:1px solid rgba(251,146,60,.3);
      border-radius:10px;padding:9px 12px;color:var(--text);font-weight:700;line-height:1.45;font-size:12.5px;
    }
    .alm-preview.hint{background:rgba(255,255,255,.03);border-style:dashed;color:var(--text2);font-weight:600}
    .alm-preview.warn{background:var(--amber-dim);border-color:rgba(251,191,36,.45);color:var(--amber)}
    .alm-form.pulse{box-shadow:0 0 0 2px var(--brand),0 0 24px var(--brand-glow)}
    .alm-time-custom{display:flex;align-items:center;gap:10px;margin-top:6px}
    .alm-time-custom span{font-size:11px;font-weight:700;color:var(--text2);white-space:nowrap}
    #alarmTime{flex:1;min-width:0}

    /* ═══ SETTINGS ═══ */
    .settings-layout{display:flex;flex-direction:column;gap:14px}
    @media(min-width:900px){.settings-layout{display:grid;grid-template-columns:1fr;gap:12px;align-items:start}}
    /* seções recolhíveis */
    .settings-card-title.sc-toggle{cursor:pointer;user-select:none;margin-bottom:0;border-radius:8px}
    .settings-card-title.sc-toggle:hover{color:var(--text)}
    .settings-card:not(.sc-collapsed) .settings-card-title.sc-toggle{margin-bottom:16px}
    .settings-card-title .sc-chevron{margin-left:auto;width:16px;height:16px;opacity:.7;transition:transform .2s}
    .settings-card:not(.sc-collapsed) .sc-chevron{transform:rotate(180deg)}
    .settings-card.sc-collapsed .sc-body{display:none}
    .ag-row .settings-row-label{display:flex;align-items:center;gap:8px}
    .ag-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:#6b7280}
    .ag-dot.online{background:var(--green)}
    .ag-dot.cli{background:#f472b6}
    .ag-state{font-size:11px;font-weight:600;color:var(--text3,var(--text2));opacity:.8}
    .ag-row.ag-off .settings-row-info{opacity:.55}
    .settings-card{
      background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);
      padding:16px;backdrop-filter:blur(12px);position:relative;overflow:hidden;
    }
    @media(min-width:640px){.settings-card{padding:20px}}
    .settings-card::after{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,.02),transparent);pointer-events:none}
    .settings-card-title{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.09em;margin-bottom:16px;display:flex;align-items:center;gap:8px}
    .settings-card-title svg{width:14px;height:14px;opacity:.5}
    .settings-row{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:12px 0;border-bottom:1px solid var(--border)}
    .settings-row:last-child{border-bottom:none;padding-bottom:0}
    .settings-row-info{flex:1;min-width:140px}
    .settings-row-label{font-size:13.5px;font-weight:600;letter-spacing:-.01em}
    .settings-row-desc{font-size:12px;color:var(--text2);margin-top:2px;line-height:1.4}
    .settings-row-control{flex-shrink:0;display:flex;align-items:center}
    /* Toggle */
    .toggle{position:relative;width:44px;height:24px;flex-shrink:0;display:block}
    .toggle input{opacity:0;width:0;height:0;position:absolute}
    .toggle-slider{position:absolute;inset:0;background:rgba(255,255,255,.06);border-radius:99px;cursor:pointer;transition:.2s;border:1px solid var(--border2)}
    .toggle-slider::before{content:"";position:absolute;width:18px;height:18px;border-radius:50%;background:#fff;bottom:2px;left:2px;transition:.2s;box-shadow:0 1px 4px rgba(0,0,0,.4)}
    .toggle input:checked + .toggle-slider{background:linear-gradient(135deg,var(--brand),#ec4899);border-color:transparent;box-shadow:0 0 12px rgba(251,146,60,.3)}
    .toggle input:checked + .toggle-slider::before{transform:translateX(20px)}
    /* Range */
    .settings-range{display:flex;align-items:center;gap:8px;min-width:130px;max-width:190px}
    .settings-range input[type=range]{flex:1;accent-color:var(--brand);cursor:pointer}
    .settings-range-val{font-size:12px;font-weight:700;color:var(--brand2);min-width:30px;text-align:right}
    /* Select in settings */
    .settings-select{padding:7px 10px;min-width:0;max-width:160px;width:auto}
    /* Info chip */
    .info-chip{display:inline-flex;align-items:center;padding:4px 11px;border-radius:99px;background:rgba(255,255,255,.04);border:1px solid var(--border);font-size:12px;color:var(--text2);font-weight:500;white-space:nowrap}
    .settings-card.full{grid-column:1/-1}
    /* Som & Bluetooth */
    .vol-control{display:flex;align-items:center;gap:10px;width:100%}
    .vol-control input[type=range]{flex:1;accent-color:var(--brand);cursor:pointer;min-width:0}
    .vol-val{font-size:13px;font-weight:700;color:var(--brand2);min-width:40px;text-align:right;font-variant-numeric:tabular-nums}
    .vol-control.muted input[type=range]{opacity:.35}
    .vol-control.muted .vol-val{color:var(--text3)}
    .bt-list{display:flex;flex-direction:column;gap:8px;margin-top:4px}
    .bt-item{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:10px 12px;border:1px solid var(--border);border-radius:var(--r);background:rgba(255,255,255,.02)}
    .bt-item.connected{border-color:rgba(52,211,153,.3);background:var(--green-dim)}
    .bt-item-info{flex:1;min-width:150px}
    .bt-item-name{font-size:13.5px;font-weight:600;overflow-wrap:anywhere}
    .bt-item-meta{font-size:11.5px;color:var(--text2);margin-top:2px;font-family:monospace}
    .bt-item-actions{display:flex;gap:6px;flex-wrap:wrap}
    .bt-dot{width:9px;height:9px;border-radius:50%;background:var(--text3);flex-shrink:0}
    .bt-item.connected .bt-dot{background:var(--green);box-shadow:0 0 8px var(--green-glow)}
    .bt-job{font-size:12.5px;padding:9px 12px;border-radius:var(--r);margin-top:12px;border:1px solid var(--border);color:var(--text2);display:none}
    .bt-job.running{display:block;border-color:rgba(251,146,60,.3);color:var(--brand2)}
    .bt-job.ok{display:block;border-color:rgba(52,211,153,.3);color:var(--green)}
    .bt-job.error{display:block;border-color:rgba(248,113,113,.3);color:#fca5a5}
    .bt-section-label{font-size:10.5px;color:var(--text2);font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin:16px 0 8px}
    .bt-empty{font-size:12.5px;color:var(--text3);padding:6px 0}
    .sp-now{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--border);border-radius:var(--r);background:rgba(255,255,255,.02);margin-top:4px;flex-wrap:wrap}
    .sp-cover{width:52px;height:52px;border-radius:8px;object-fit:cover;background:rgba(255,255,255,.05);flex-shrink:0}
    .sp-info{flex:1;min-width:140px}
    .sp-title{font-size:14px;font-weight:700;overflow-wrap:anywhere}
    .sp-artist{font-size:12.5px;color:var(--text2);margin-top:2px;overflow-wrap:anywhere}
    .sp-controls{display:flex;gap:6px}
    .sp-play-row{display:flex;gap:8px;margin-top:12px}
    .sp-play-row input{flex:1;min-width:0}
    .sp-green{color:#1ed760}
    /* ═══ MICROFONE ═══ */
    .mic-status{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);padding:16px;margin-bottom:14px}
    .mic-dot{width:12px;height:12px;border-radius:50%;background:var(--text3);flex-shrink:0}
    .mic-dot.on{background:var(--green);box-shadow:0 0 10px var(--green-glow)}
    .mic-dot.off{background:var(--red)}
    .mic-title{font-weight:800;font-size:15px}
    .mic-sub{font-size:12.5px;color:var(--text2);margin-top:2px;overflow-wrap:anywhere}
    .mic-phase{margin-left:auto;font-size:12px;font-weight:700;padding:5px 12px;border-radius:99px;background:var(--brand-dim);color:var(--brand2);border:1px solid rgba(251,146,60,.25)}
    .mic-meter-wrap{background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);padding:14px 16px;margin-bottom:14px}
    .mic-meter{position:relative;height:14px;border-radius:99px;background:rgba(255,255,255,.06);overflow:hidden;margin:8px 0 6px}
    .mic-meter-fill{position:absolute;left:0;top:0;bottom:0;width:0;border-radius:99px;background:linear-gradient(90deg,#34d399,#fbbf24 70%,#f87171);transition:width .12s linear}
    .mic-meter-peak{position:absolute;top:0;bottom:0;width:2px;background:#fff;opacity:.7;left:0;transition:left .12s linear}
    .mic-meter-thr{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--brand2)}
    .mic-meter-legend{display:flex;justify-content:space-between;font-size:11.5px;color:var(--text2);font-variant-numeric:tabular-nums}
    .mic-log{display:flex;flex-direction:column;gap:6px}
    .mic-row{display:flex;gap:10px;align-items:flex-start;padding:8px 12px;border:1px solid var(--border);border-radius:var(--r);background:rgba(255,255,255,.02);font-size:13px}
    .mic-time{font-size:11.5px;color:var(--text3);font-variant-numeric:tabular-nums;flex-shrink:0;padding-top:1px}
    .mic-kind{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;padding:2px 8px;border-radius:99px;flex-shrink:0;background:rgba(255,255,255,.06);color:var(--text2)}
    .mic-kind.wake,.mic-kind.command{background:var(--green-dim);color:var(--green)}
    .mic-kind.response{background:var(--brand-dim);color:var(--brand2)}
    .mic-kind.error{background:var(--red-dim);color:#fca5a5}
    .mic-kind.status{background:var(--amber-dim);color:#fbbf24}
    .mic-text{flex:1;min-width:0;overflow-wrap:anywhere}
    .mic-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:18px 0 10px}
    /* ═══ APARELHOS ═══ */
    .dv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-bottom:8px}
    .dv-card{background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);padding:14px;display:flex;flex-direction:column;gap:10px;min-width:0}
    .dv-card.clickable{cursor:pointer;transition:all .15s}
    .dv-card.clickable:hover{border-color:rgba(251,146,60,.35);transform:translateY(-2px)}
    .dv-head{display:flex;align-items:center;gap:10px;min-width:0}
    .dv-icon{width:40px;height:40px;border-radius:12px;background:var(--brand-dim);color:var(--brand2);display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .dv-icon svg{width:20px;height:20px}
    .dv-name{font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .dv-sub{font-size:12px;color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .dv-dot{width:8px;height:8px;border-radius:50%;background:var(--text3);display:inline-block;margin-right:6px;vertical-align:1px}
    .dv-dot.on{background:var(--green);box-shadow:0 0 8px var(--green-glow)}
    .dv-actions{display:flex;gap:6px;flex-wrap:wrap}
    .dv-section-title{font-size:12px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin:18px 0 10px;display:flex;align-items:center;gap:10px}
    .dv-section-title span{flex:1}
    .remote{max-width:430px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
    .remote-top{display:flex;align-items:center;gap:10px}
    .remote-panel{background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);padding:16px;display:flex;flex-direction:column;gap:14px}
    .remote-row{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}
    .rbtn{min-width:52px;height:48px;padding:0 14px;border-radius:14px;border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text);display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;font-family:inherit;font-weight:700;font-size:13px;transition:all .12s}
    .rbtn:hover{background:rgba(255,255,255,.08);border-color:var(--border2)}
    .rbtn:active{transform:scale(.94)}
    .rbtn svg{width:18px;height:18px}
    .rbtn[disabled]{opacity:.28;cursor:not-allowed}
    .rbtn.power-off{color:#fca5a5;border-color:rgba(248,113,113,.3)}
    .rbtn.power-on{color:var(--green);border-color:rgba(52,211,153,.3)}
    .dpad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,64px);gap:8px;justify-content:center}
    .dpad .rbtn{width:64px;height:64px;min-width:0;padding:0;border-radius:18px}
    .dpad .ok{border-radius:50%;background:var(--brand-dim);color:var(--brand2);border-color:rgba(251,146,60,.35)}
    .remote-label{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;text-align:center}
    .app-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
    .app-btn{height:52px;border-radius:12px;border:none;color:#fff;font-weight:800;font-size:13px;cursor:pointer;font-family:inherit;transition:transform .12s,filter .12s}
    .app-btn:hover{filter:brightness(1.12)}.app-btn:active{transform:scale(.95)}
    .remote-msg{font-size:12.5px;text-align:center;min-height:18px;color:var(--text2)}
    .remote-msg.ok{color:var(--green)}.remote-msg.error{color:#fca5a5}
    .remote-note{font-size:12.5px;color:#fde68a;background:var(--amber-dim);border:1px solid rgba(251,191,36,.3);border-radius:var(--r);padding:10px 12px}
    /* ═══ MÚSICA ═══ */
    .mu-hero{display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:var(--glass);border:1px solid var(--border);border-radius:var(--rx);padding:18px;backdrop-filter:blur(12px);margin-bottom:16px;position:relative;overflow:hidden}
    .mu-hero::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 0% 0%,rgba(30,215,96,.10),transparent 55%);pointer-events:none}
    .mu-cover{width:132px;height:132px;border-radius:14px;object-fit:cover;background:rgba(255,255,255,.05);flex-shrink:0;box-shadow:0 8px 28px rgba(0,0,0,.45)}
    .mu-cover.empty{display:none}
    @media(max-width:560px){.mu-hero{padding:14px}.mu-cover{width:min(62vw,220px);height:auto;aspect-ratio:1/1;margin:0 auto}.mu-main{min-width:0;flex-basis:100%}.mu-title{font-size:18px}}
    .mu-banner{display:flex;align-items:center;gap:10px 14px;flex-wrap:wrap;padding:12px 14px;margin-bottom:14px;border-radius:var(--rl);border:1px solid rgba(251,191,36,.3);background:var(--amber-dim);color:#fde68a;font-size:13px}
    .mu-banner span{flex:1;min-width:180px}
    .mu-main{flex:1;min-width:220px;position:relative}
    .mu-title{font-size:20px;font-weight:800;letter-spacing:-.03em;overflow-wrap:anywhere}
    .mu-sub{font-size:13px;color:var(--text2);margin-top:3px;overflow-wrap:anywhere}
    .mu-progress{display:flex;align-items:center;gap:10px;margin:14px 0 10px;font-size:11.5px;color:var(--text2);font-variant-numeric:tabular-nums}
    .mu-bar{flex:1;height:6px;border-radius:99px;background:rgba(255,255,255,.08);cursor:pointer;position:relative}
    .mu-bar-fill{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:linear-gradient(90deg,#1ed760,#5eead4);width:0}
    .mu-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .mu-btn{position:relative;width:38px;height:38px;border-radius:50%;border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:all .15s;flex-shrink:0}
    .mu-btn:hover{border-color:var(--border2);background:rgba(255,255,255,.08)}
    .mu-btn svg{width:16px;height:16px}
    .mu-btn.on{color:#1ed760;border-color:rgba(30,215,96,.35)}
    .mu-btn.big{width:50px;height:50px;background:#1ed760;color:#04130a;border:none}
    .mu-btn.big:hover{background:#3be477}
    .mu-btn.big svg{width:22px;height:22px}
    .mu-btn.liked{color:#1ed760}
    .mu-extra{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}
    .mu-extra input[type=range]{flex:1;min-width:100px;max-width:200px;accent-color:#1ed760}
    .mu-extra select{max-width:200px;padding:6px 10px}
    .mu-msg{font-size:12.5px;min-height:18px;margin-top:8px;color:var(--text2)}
    .mu-msg.error{color:#fca5a5}.mu-msg.ok{color:var(--green)}
    .mu-search{display:flex;gap:8px;margin-bottom:10px}
    .mu-search input{flex:1;min-width:0}
    .mu-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
    .mu-section{margin-bottom:22px}
    .mu-section-title{font-size:12px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:8px}
    .mu-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px}
    .mu-card{background:var(--glass);border:1px solid var(--border);border-radius:var(--rl);padding:10px;cursor:pointer;transition:all .15s;min-width:0}
    .mu-card:hover{border-color:rgba(30,215,96,.3);transform:translateY(-2px)}
    .mu-card img,.mu-card .mu-ph{width:100%;aspect-ratio:1/1;border-radius:10px;object-fit:cover;background:rgba(255,255,255,.05);display:block}
    .mu-card.round img,.mu-card.round .mu-ph{border-radius:50%}
    .mu-card-name{font-size:13px;font-weight:600;margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .mu-card-sub{font-size:11.5px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .mu-list{display:flex;flex-direction:column;gap:6px}
    .mu-row{display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid var(--border);border-radius:var(--r);background:rgba(255,255,255,.02)}
    .mu-row:hover{border-color:var(--border2)}
    .mu-row img,.mu-row .mu-ph{width:40px;height:40px;border-radius:6px;object-fit:cover;background:rgba(255,255,255,.05);flex-shrink:0}
    .mu-row-info{flex:1;min-width:0}
    .mu-row-name{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .mu-row-sub{font-size:12px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .mu-row-actions{display:flex;gap:6px;flex-shrink:0}
    .mu-connect{text-align:center;padding:36px 18px;background:var(--glass);border:1px solid var(--border);border-radius:var(--rx)}
    .mu-connect p{color:var(--text2);font-size:13.5px;margin:8px auto 16px;max-width:460px}
    .save-bar{display:flex;align-items:center;gap:10px;padding-top:4px}
    .save-toast{font-size:12px;color:var(--green);font-weight:600;opacity:0;transition:opacity .3s}
    .save-toast.show{opacity:1}
    /* Modelo de IA */
    .llm-input{width:230px;max-width:100%}
    .llm-note{font-size:12px;line-height:1.45;color:var(--text2);padding:10px 12px;border-radius:var(--r);background:rgba(255,255,255,.03);border:1px solid var(--border);margin-top:12px}
    .llm-section{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--brand2);margin:18px 0 2px;padding-top:12px;border-top:1px solid var(--border)}
    .sc-body > .llm-section:first-child{border-top:0;padding-top:0;margin-top:0}
    @media(max-width:640px){
      .llm-card .settings-row-control{flex:1 1 100%;flex-wrap:wrap;gap:8px}
      .llm-card .settings-row-control > *{flex:1 1 100%;max-width:none!important;width:100%!important}
      .llm-card .settings-row-control > .btn{flex:0 0 auto;width:auto!important}
      .llm-card .settings-row-control > .llm-active{flex:0 0 auto;width:auto!important}
      .llm-card .settings-row-desc{font-size:11.5px}
    }
    .llm-card .settings-select{max-width:260px}
    .llm-note.warn{color:var(--amber);background:var(--amber-dim);border-color:rgba(251,191,36,.25)}
    .llm-active{color:var(--green);font-weight:700}
  </style>
</head>
<body>

<div class="mobile-overlay" id="mobileOverlay"></div>
<aside class="mobile-sidebar" id="mobileSidebar">
  <div class="sb-top">
    <span class="brand-face" data-agent-face="personal-assistant" data-size="40"></span>
    <div><div class="brand-text">Cassandra</div><div class="brand-sub">Assistente pessoal</div></div>
  </div>
  <nav class="sb-nav" id="mobileNav"></nav>
</aside>

<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="sb-top">
      <span class="brand-face" data-agent-face="personal-assistant" data-size="40"></span>
      <div><div class="brand-text">Cassandra</div><div class="brand-sub">Assistente pessoal</div></div>
      <button class="collapse-btn" id="collapseBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
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
        <button class="mobile-menu-btn" id="mobileMenuBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
        <span class="page-title" id="pageTitle">Dashboard</span>
      </div>
      <div class="topbar-right">
        <span class="timer-pills" id="timerPills"></span>
        <span class="clock" id="clock"></span>
        <button type="button" class="conv-btn" id="convBtn" title="Modo conversa: ela bate papo, puxa assunto e espera mais por você"><span class="conv-dot"></span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.4 8.4 0 01-9 8.4 8.8 8.8 0 01-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1121 11.5z"/></svg><span class="conv-label">Conversa</span></button>
        <button class="restart-btn" id="restartBtn" title="Reiniciar a Cassandra"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg></button>
        <button type="button" class="alarm-pill" id="alarmPill" title="Status do alarme"><span class="sdot" id="alarmPillDot"></span><span id="alarmPillText">Ok</span></button>
      </div>
    </header>

    <div class="body">

      <!-- ══ DASHBOARD ══ -->
      <div class="tab-panel" id="tab-dashboard">
        <div class="dash-hero">
          <div class="dash-face"><span class="brand-face" data-agent-face="personal-assistant" data-size="92"></span></div>
          <div class="dash-greeting" id="dashGreeting">Olá!</div>
          <div class="dash-date" id="dashDate"></div>
          <div class="dash-status-row">
            <span class="dash-status-badge"><svg width="7" height="7" viewBox="0 0 8 8"><circle cx="4" cy="4" r="4" fill="#34d399"/></svg>Cassandra ativa</span>
            <span id="heroWebAgentBadge" style="display:none;align-items:center;gap:6px;padding:5px 13px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(251,146,60,.08);border:1px solid rgba(251,146,60,.2);color:var(--brand2)"><svg width="7" height="7" viewBox="0 0 8 8"><circle cx="4" cy="4" r="4" fill="#fb923c"/></svg>Maestro online</span>
          </div>
        </div>
        <div class="stats-grid" id="statsGrid">
          <div class="stat-card" data-goto="todos">
            <div class="stat-icon" style="background:var(--brand-dim);color:var(--brand2)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg></div>
            <div class="stat-val" id="statTodos">—</div><div class="stat-lbl">tarefas pendentes</div>
          </div>
          <div class="stat-card" data-goto="shopping">
            <div class="stat-icon" style="background:var(--green-dim);color:#4ade80"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg></div>
            <div class="stat-val" id="statShopping">—</div><div class="stat-lbl">itens na lista</div>
          </div>
          <div class="stat-card" data-goto="alarms">
            <div class="stat-icon" style="background:var(--amber-dim);color:#fbbf24"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div>
            <div class="stat-val" id="statAlarms">—</div><div class="stat-lbl">alarmes ativos</div>
          </div>
        </div>
        <div class="dash-section" id="dashHabitsBox" style="margin-bottom:14px;display:none">
          <div class="dash-section-title" style="display:flex;justify-content:space-between;align-items:center"><span>Hábitos de hoje</span><span id="dashHabitsCount" style="color:var(--brand2);cursor:pointer" data-goto="habits"></span></div>
          <div id="dashHabits"></div>
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
          <div class="sec-hdr"><span class="sec-title">O que posso fazer</span></div>
          <div class="tips-grid" id="tipsGrid"></div>
        </div>
      </div>

      <!-- ══ GASTOS ══ -->
      <div class="tab-panel hidden" id="tab-costs">
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <select id="costDays" class="settings-select" style="max-width:180px">
            <option value="7">Últimos 7 dias</option><option value="30" selected>Últimos 30 dias</option><option value="90">Últimos 90 dias</option>
          </select>
          <span class="cost-note" id="costUpdated" style="margin:0"></span>
        </div>
        <div class="cost-grid">
          <div class="stat-card"><div class="stat-val" id="costToday">—</div><div class="stat-lbl">hoje</div></div>
          <div class="stat-card"><div class="stat-val" id="costMonth">—</div><div class="stat-lbl">este mês</div></div>
          <div class="stat-card"><div class="stat-val" id="costProj">—</div><div class="stat-lbl">previsão do mês</div></div>
          <div class="stat-card"><div class="stat-val" id="costPeriod">—</div><div class="stat-lbl" id="costPeriodLbl">no período</div></div>
        </div>
        <div class="dash-section" style="margin-bottom:14px">
          <div class="dash-section-title">Gasto por dia (US$)</div>
          <svg class="cost-chart" id="costChart" viewBox="0 0 600 190" preserveAspectRatio="none"></svg>
          <div class="cost-legend" id="costLegend"></div>
        </div>
        <div class="dash-cols">
          <div class="dash-section">
            <div class="dash-section-title">Por modelo</div>
            <div style="overflow-x:auto"><table class="cost-table" id="costModels"></table></div>
          </div>
          <div class="dash-section">
            <div class="dash-section-title">Azure (cota grátis do mês) e cache da voz</div>
            <div id="costAzure"></div>
            <div id="costCache" style="margin-top:14px"></div>
          </div>
        </div>
        <div class="cost-note">Estimativa pela tabela de preços de cada provedor (US$, sem impostos), a partir do que a Cassandra registra em cada chamada. Transcrição local (Vosk) e voz local (Piper) são grátis e não aparecem.</div>
      </div>

      <!-- ══ CHAT ══ -->
      <div class="tab-panel hidden" id="tab-chat">
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <button class="btn btn-ghost btn-sm" id="clearBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>Limpar conversa</button>
        </div>
        <div class="chat-wrap">
          <div class="messages" id="messages">
            <div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>Pergunte ou peça qualquer coisa à Cassandra</div>
          </div>
          <div class="chat-bar">
            <textarea id="msgInput" rows="1" placeholder="Fale com a Cassandra…" enterkeyhint="send" autocomplete="off"></textarea>
            <button class="chat-send" id="sendBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
          </div>
        </div>
      </div>

      <!-- ══ MÚSICA ══ -->
      <div class="tab-panel hidden" id="tab-music">
        <div class="sec-hdr"><span class="sec-title">Música</span><span class="count-badge" id="muDeviceBadge">Spotify</span></div>

        <div class="mu-connect" id="muConnect" style="display:none">
          <div style="font-size:15px;font-weight:700" id="muConnectTitle">Conecte o Spotify</div>
          <p id="muConnectText">Conecte sua conta (Premium) para a Cassandra tocar o que você pedir, por voz ou por aqui.</p>
          <button class="btn btn-primary" id="muConnectBtn">Conectar Spotify</button>
        </div>

        <div id="muBody" style="display:none">
          <div class="mu-banner" id="muBanner" style="display:none"><span id="muBannerText"></span><a class="btn btn-warn btn-sm" id="muPairLink" target="_blank" rel="noopener" style="display:none;text-decoration:none">Abrir spotify.com/pair</a><button class="btn btn-warn btn-sm" id="muLinkBtn">Conectar a caixa</button></div>
          <div class="mu-hero">
            <img class="mu-cover" id="muCover" alt=""/>
            <div class="mu-main">
              <div class="mu-title" id="muTitle">Nada tocando</div>
              <div class="mu-sub" id="muSub">Busque abaixo ou diga "Cassandra, toca …"</div>
              <div class="mu-progress"><span id="muPos">0:00</span><div class="mu-bar" id="muBar"><div class="mu-bar-fill" id="muFill"></div></div><span id="muDur">0:00</span></div>
              <div class="mu-controls">
                <button class="mu-btn" id="muShuffle" title="Aleatório"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg></button>
                <button class="mu-btn" data-mu="previous" title="Anterior"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h2v14H6zM20 5v14L9 12z"/></svg></button>
                <button class="mu-btn big" id="muToggle" title="Tocar/pausar"><svg viewBox="0 0 24 24" fill="currentColor" id="muToggleIcon"><path d="M8 5v14l11-7z"/></svg></button>
                <button class="mu-btn" data-mu="next" title="Próxima"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 5h2v14h-2zM4 5v14l11-7z"/></svg></button>
                <button class="mu-btn" id="muRepeat" title="Repetir"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 014-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg><span id="muRepeatOne" style="position:absolute;font-size:8px;font-weight:800;display:none">1</span></button>
                <button class="mu-btn" id="muLike" title="Curtir"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" id="muLikeIcon"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/></svg></button>
              </div>
              <div class="mu-extra">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;color:var(--text2)"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>
                <input type="range" id="muVol" min="0" max="100" value="50" title="Volume da música"/>
                <select id="muDevice" class="settings-select" title="Tocar em"></select>
              </div>
              <div class="mu-msg" id="muMsg"></div>
            </div>
          </div>

          <div class="mu-search">
            <input type="text" id="muQuery" placeholder="Buscar música, artista, álbum ou playlist…"/>
            <button class="btn btn-primary" id="muSearchBtn">Buscar</button>
          </div>
          <div class="mu-chips">
            <button class="btn btn-ghost btn-sm" data-mu="liked">❤ Minhas curtidas</button>
            <button class="btn btn-ghost btn-sm" data-mu="top">★ Mais ouvidas</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="música pra relaxar">Relaxar</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="música pra animar">Animar</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="lo-fi pra estudar">Foco</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="rock clássico">Rock</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="sertanejo">Sertanejo</button>
            <button class="btn btn-ghost btn-sm" data-mu-ask="MPB">MPB</button>
          </div>

          <div id="muResults"></div>

          <div class="mu-section" id="muQueueSec" style="display:none"><div class="mu-section-title">A seguir</div><div class="mu-list" id="muQueue"></div></div>
          <div class="mu-section"><div class="mu-section-title">Suas playlists</div><div class="mu-grid" id="muPlaylists"><div class="bt-empty">Carregando…</div></div></div>
          <div class="mu-section" id="muRecentSec" style="display:none"><div class="mu-section-title">Tocadas recentemente</div><div class="mu-list" id="muRecent"></div></div>
        </div>
      </div>

      <!-- ══ MICROFONE ══ -->
      <div class="tab-panel hidden" id="tab-mic">
        <div class="sec-hdr"><span class="sec-title">Microfone</span><span class="count-badge" id="micBadge">—</span></div>
        <div class="mic-status">
          <span class="mic-dot" id="micDot"></span>
          <div style="min-width:0;flex:1"><div class="mic-title" id="micTitle">Verificando…</div><div class="mic-sub" id="micSub">—</div></div>
          <span class="mic-phase" id="micPhase">—</span>
        </div>
        <div class="mic-meter-wrap">
          <div class="settings-row-label">Nível de som agora</div>
          <div class="mic-meter"><div class="mic-meter-fill" id="micFill"></div><div class="mic-meter-peak" id="micPeak"></div><div class="mic-meter-thr" id="micThr" title="Limite: acima disso conta como fala"></div></div>
          <div class="mic-meter-legend"><span id="micLevel">—</span><span id="micThrLabel">—</span></div>
        </div>
        <div class="mic-tools">
          <span class="settings-row-label" style="flex:1">O que ela captou</span>
          <label style="display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--text2);cursor:pointer"><input type="checkbox" id="micOnlyUseful" style="width:auto;flex:none"/> só falas e pedidos</label>
          <button class="btn btn-ghost btn-sm" id="micPause">Pausar</button>
          <button class="btn btn-ghost btn-sm" id="micClear">Limpar</button>
        </div>
        <div class="mic-log" id="micLog"><div class="bt-empty">Nada captado ainda. Fale perto do microfone.</div></div>
      </div>

      <!-- ══ APARELHOS ══ -->
      <div class="tab-panel hidden" id="tab-devices">
        <div id="dvList">
          <div class="sec-hdr"><span class="sec-title">Aparelhos</span><span class="count-badge" id="dvCount">—</span></div>
          <div class="dv-section-title"><span>Conectados</span></div>
          <div class="dv-grid" id="dvSaved"><div class="bt-empty">Carregando…</div></div>
          <div class="dv-section-title"><span>Na mesma rede</span><button class="btn btn-primary btn-sm" id="dvScan">Procurar aparelhos</button></div>
          <div class="settings-row-desc" style="margin-bottom:10px">O aparelho precisa estar ligado e no mesmo Wi-Fi. Ao conectar, a Cassandra identifica o que ele é e, se der para controlá-lo, mostra a opção Controlar. Alguns pedem uma confirmação na própria tela.</div>
          <div class="dv-grid" id="dvFound"></div>
          <div class="bt-job" id="dvJob"></div>
          <div class="dv-section-title"><span>Bluetooth</span><button class="btn btn-ghost btn-sm" onclick="gotoTab('settings')">Gerenciar</button></div>
          <div class="dv-grid" id="dvBt"><div class="bt-empty">Carregando…</div></div>
        </div>

        <div id="dvRemote" style="display:none">
          <div class="remote">
            <div class="remote-top">
              <button class="btn btn-ghost btn-sm" id="rmBack">← Aparelhos</button>
              <div style="flex:1;min-width:0"><div class="dv-name" id="rmName">TV</div><div class="dv-sub" id="rmSub">—</div></div>
            </div>
            <div class="remote-note" id="rmNote" style="display:none"></div>
            <div id="pnlTv">
            <div class="remote-panel">
              <div class="remote-row">
                <button class="rbtn power-on" data-rm="power_on" title="Ligar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18.36 6.64a9 9 0 11-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>Ligar</button>
                <button class="rbtn power-off" data-rm="power_off" title="Desligar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18.36 6.64a9 9 0 11-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>Desligar</button>
              </div>
              <div class="remote-label">Volume</div>
              <div class="remote-row">
                <button class="rbtn" data-rm="volume_down" title="Diminuir">Vol −</button>
                <button class="rbtn" data-rm="mute" title="Mudo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg></button>
                <button class="rbtn" data-rm="volume_up" title="Aumentar">Vol +</button>
                <button class="rbtn" data-rm="channel_down" title="Canal anterior">Ch −</button>
                <button class="rbtn" data-rm="channel_up" title="Próximo canal">Ch +</button>
              </div>
            </div>
            <div class="remote-panel">
              <div class="dpad">
                <span></span><button class="rbtn" data-rm="up" title="Cima">▲</button><span></span>
                <button class="rbtn" data-rm="left" title="Esquerda">◀</button><button class="rbtn ok" data-rm="ok" title="OK">OK</button><button class="rbtn" data-rm="right" title="Direita">▶</button>
                <span></span><button class="rbtn" data-rm="down" title="Baixo">▼</button><span></span>
              </div>
              <div class="remote-row">
                <button class="rbtn" data-rm="back" title="Voltar">↩ Voltar</button>
                <button class="rbtn" data-rm="home" title="Início">⌂ Início</button>
                <button class="rbtn" data-rm="menu" title="Menu">☰</button>
              </div>
              <div class="remote-row">
                <button class="rbtn" data-rm="rewind" title="Voltar">⏪</button>
                <button class="rbtn" data-rm="play_pause" title="Play/pausa">⏯</button>
                <button class="rbtn" data-rm="forward" title="Avançar">⏩</button>
              </div>
            </div>
            <div class="remote-panel" id="rmInputsPanel">
              <div class="remote-label">Entradas</div>
              <div class="remote-row" id="rmInputs"></div>
            </div>
            <div class="remote-panel">
              <div class="remote-label">Apps</div>
              <div class="app-grid" id="rmApps"><div class="bt-empty">Carregando…</div></div>
            </div>
            </div>

            <!-- computador (pelo maestro) -->
            <div id="pnlComputer" style="display:none">
              <div class="remote-panel">
                <div class="remote-label">Sessão</div>
                <div class="remote-row">
                  <button class="rbtn" data-rm="lock">Bloquear</button>
                  <button class="rbtn" data-rm="screen_off">Apagar a tela</button>
                  <button class="rbtn" data-rm="sleep">Suspender</button>
                </div>
                <div class="remote-label">Energia</div>
                <div class="remote-row">
                  <button class="rbtn power-off" data-rm-confirm="shutdown" data-rm="shutdown">Desligar</button>
                  <button class="rbtn" data-rm-confirm="restart" data-rm="restart">Reiniciar</button>
                  <button class="rbtn" data-rm="cancel_shutdown">Cancelar desligamento</button>
                </div>
              </div>
              <div class="remote-panel">
                <div class="remote-label">Som e mídia</div>
                <div class="remote-row">
                  <button class="rbtn" data-rm="volume_down">Vol −</button>
                  <button class="rbtn" data-rm="mute">Mudo</button>
                  <button class="rbtn" data-rm="volume_up">Vol +</button>
                </div>
                <div class="remote-row">
                  <button class="rbtn" data-rm="previous">⏮</button>
                  <button class="rbtn" data-rm="play_pause">⏯</button>
                  <button class="rbtn" data-rm="next">⏭</button>
                </div>
              </div>
            </div>

            <!-- lâmpada -->
            <div id="pnlLight" style="display:none">
              <div class="remote-panel">
                <div class="remote-row">
                  <button class="rbtn power-on" data-rm="light_on">Acender</button>
                  <button class="rbtn power-off" data-rm="light_off">Apagar</button>
                </div>
                <div class="remote-label">Brilho <span id="lgBrightVal"></span></div>
                <input type="range" id="lgBright" min="10" max="100" step="5" value="100" style="accent-color:var(--amber)"/>
                <div class="remote-label">Tom: quente ↔ frio <span id="lgTempVal"></span></div>
                <input type="range" id="lgTemp" min="2200" max="6500" step="100" value="4000" style="accent-color:var(--brand)"/>
                <div class="remote-label">Cor</div>
                <div class="remote-row" id="lgColors"></div>
              </div>
            </div>

            <!-- caixa de som (Spotify Connect) -->
            <div id="pnlSpeaker" style="display:none">
              <div class="remote-panel">
                <div class="remote-row"><button class="rbtn power-on" data-rm="play_here">Tocar aqui (Spotify)</button></div>
                <div class="remote-label">Volume</div>
                <input type="range" id="spkVol" min="0" max="100" step="5" value="50" style="accent-color:#1ed760"/>
                <div class="remote-row">
                  <button class="rbtn" data-rm="previous">⏮</button>
                  <button class="rbtn" data-rm="play_pause">⏯</button>
                  <button class="rbtn" data-rm="next">⏭</button>
                </div>
              </div>
            </div>

            <!-- caixa/fone Bluetooth -->
            <div id="pnlBt" style="display:none">
              <div class="remote-panel">
                <div class="remote-label">Volume da caixa <span id="btVolVal"></span></div>
                <input type="range" id="btVol" min="0" max="100" step="2" value="50" style="accent-color:var(--brand)"/>
                <div class="remote-row">
                  <button class="rbtn" id="btMute">Mudo</button>
                  <button class="rbtn power-on" id="btOutput">Usar como saída</button>
                </div>
              </div>
              <div class="remote-panel">
                <div class="remote-row" style="justify-content:space-between;align-items:center">
                  <div class="remote-label" style="text-align:left">Equalizador (grave e agudo)</div>
                  <label class="toggle"><input type="checkbox" id="btEqOn"/><span class="toggle-slider"></span></label>
                </div>
                <div class="remote-label">Grave <span id="btBassVal"></span></div>
                <input type="range" id="btBass" min="-12" max="12" step="1" value="0" style="accent-color:var(--amber)"/>
                <div class="remote-label">Agudo <span id="btTrebleVal"></span></div>
                <input type="range" id="btTreble" min="-12" max="12" step="1" value="0" style="accent-color:var(--green)"/>
                <div class="remote-row" id="btPresets"></div>
              </div>
            </div>

            <!-- rede: vale para todo aparelho -->
            <div class="remote-panel" id="pnlNet">
              <div class="remote-label">Rede</div>
              <div class="dv-sub" id="rmNetInfo" style="text-align:center">—</div>
              <div class="remote-row">
                <a class="btn btn-ghost btn-sm" id="rmPage" target="_blank" rel="noopener" style="display:none;text-decoration:none">Abrir página do aparelho</a>
                <button class="rbtn" data-rm="wake" id="rmWake">Ligar pela rede</button>
              </div>
            </div>
            <div class="remote-msg" id="rmMsg"></div>
          </div>
        </div>
      </div>

      <!-- ══ SHOPPING ══ -->
      <div class="tab-panel hidden" id="tab-shopping">
        <div class="sec-hdr"><span class="sec-title">Lista de compras</span><span class="count-badge" id="shopCount">0 itens</span></div>
        <div class="row">
          <input id="shopInput" type="text" placeholder="Ex.: leite, pão, café..."/>
          <button class="btn btn-primary" id="shopAdd"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Adicionar</button>
        </div>
        <div class="list" id="shopList"></div>
      </div>

      <!-- ══ TODOS ══ -->
      <div class="tab-panel hidden" id="tab-todos">
        <div class="sec-hdr"><span class="sec-title">Tarefas</span><span class="count-badge" id="todoCount">0 pendentes</span></div>
        <div class="row">
          <input id="todoInput" type="text" placeholder="Ex.: pagar conta de luz..."/>
          <button class="btn btn-primary" id="todoAdd"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Adicionar</button>
        </div>
        <div class="list" id="todoList"></div>
      </div>

      <!-- ══ HÁBITOS ══ -->
      <div class="tab-panel hidden" id="tab-habits">
        <div class="sec-hdr">
          <span class="sec-title">Hábitos</span>
          <span style="display:flex;gap:8px;align-items:center">
            <select id="hbYear" class="settings-select"></select>
            <button class="btn btn-primary" id="hbNew"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Novo hábito</button>
          </span>
        </div>
        <div class="cost-grid">
          <div class="stat-card"><div class="stat-val" id="hbStatToday">—</div><div class="stat-lbl">feitos hoje</div></div>
          <div class="stat-card"><div class="stat-val" id="hbStatPct">—</div><div class="stat-lbl">consistência no ano</div></div>
          <div class="stat-card"><div class="stat-val" id="hbStatStreak">—</div><div class="stat-lbl">maior sequência em curso</div></div>
          <div class="stat-card"><div class="stat-val" id="hbStatBest">—</div><div class="stat-lbl">melhor sequência</div></div>
        </div>
        <div class="dash-section" style="margin-bottom:14px">
          <div class="dash-section-title">Hoje</div>
          <div id="hbTodayList"></div>
        </div>
        <div class="dash-section" style="margin-bottom:14px">
          <div class="dash-section-title" id="hbYearTitle">O ano em revisão</div>
          <div id="hbGrids"></div>
          <div class="cost-note">Cada quadradinho é um dia (as colunas são as semanas, de segunda a domingo). Quanto mais cheio, mais perto da meta do dia. Toque num dia para marcar ou corrigir.</div>
        </div>
        <div class="dash-cols">
          <div class="dash-section">
            <div class="dash-section-title">Consistência por semana (últimas 12)</div>
            <svg class="cost-chart" id="hbWeeks" viewBox="0 0 600 190" preserveAspectRatio="none"></svg>
          </div>
          <div class="dash-section">
            <div class="dash-section-title">Em que dia da semana você cumpre mais</div>
            <div id="hbWeekdays"></div>
          </div>
        </div>
        <div class="dash-section">
          <div class="dash-section-title">Mês a mês</div>
          <div id="hbMonths"></div>
        </div>
      </div>

      <!-- Hábito: criar ou editar -->
      <div class="hb-modal hidden" id="hbModal">
        <div class="hb-box" role="dialog" aria-modal="true" aria-labelledby="hbFormTitle">
          <h3 id="hbFormTitle">Novo hábito</h3>
          <div class="hb-two" style="grid-template-columns:1fr 84px">
            <div><label style="margin-top:0">Nome</label><input id="hbName" type="text" maxlength="60" placeholder="Ex.: Beber água"/></div>
            <div><label style="margin-top:0">Emoji</label><input id="hbEmoji" type="text" maxlength="8" placeholder="💧"/></div>
          </div>
          <label>Meta</label>
          <div class="hb-two" style="grid-template-columns:90px 1fr 1fr">
            <input id="hbTarget" type="text" inputmode="decimal" placeholder="1"/>
            <input id="hbUnit" type="text" maxlength="20" placeholder="copos, páginas, min…"/>
            <select id="hbPeriod"><option value="day">por dia</option><option value="week">por semana</option></select>
          </div>
          <div class="cost-note" style="margin-top:6px">Só marcar feito/não feito? Deixe a meta em 1.</div>
          <div id="hbDaysWrap"><label>Em quais dias</label><div class="hb-days" id="hbDays"></div></div>
          <label>Cor</label><div class="hb-sw" id="hbColors"></div>
          <div class="cost-note" id="hbFormMsg" style="color:var(--red);min-height:18px"></div>
          <div class="hb-foot"><button class="btn btn-danger" id="hbDelete">Excluir</button><button class="btn btn-ghost" id="hbCancel">Cancelar</button><button class="btn btn-primary" id="hbSave">Salvar</button></div>
        </div>
      </div>

      <!-- ══ ALARMS ══ -->
      <div class="tab-panel hidden" id="tab-alarms">
        <div class="sec-hdr">
          <span class="sec-title">Alarmes</span>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span class="count-badge" id="alarmCount">0 alarmes</span>
            <button class="btn btn-ghost btn-sm" type="button" onclick="startNewAlarm()">Novo</button>
            <button class="btn btn-danger btn-sm" id="alarmStop" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>Parar</button>
          </div>
        </div>
        <div class="alm-page">
          <div class="alm-cal" id="alm-cal">
            <div class="alm-cal-head">
              <button type="button" class="alm-cal-nav" onclick="shiftAlmCalYear(-1)" title="Ano anterior">«</button>
              <button type="button" class="alm-cal-nav" onclick="shiftAlmCal(-1)" title="Mês anterior">‹</button>
              <button type="button" class="alm-cal-title" id="alm-cal-title" onclick="toggleAlmCalPicker()" title="Escolher mês e ano">Setembro 2026</button>
              <button type="button" class="alm-cal-nav" onclick="shiftAlmCal(1)" title="Próximo mês">›</button>
              <button type="button" class="alm-cal-nav" onclick="shiftAlmCalYear(1)" title="Próximo ano">»</button>
            </div>
            <div class="alm-cal-picker" id="alm-cal-picker" hidden>
              <div class="alm-cal-picker-years">
                <button type="button" class="alm-cal-nav" onclick="shiftAlmCalYear(-1)" title="Ano anterior">‹</button>
                <span class="alm-cal-picker-year" id="alm-cal-picker-year">2026</span>
                <button type="button" class="alm-cal-nav" onclick="shiftAlmCalYear(1)" title="Próximo ano">›</button>
              </div>
              <div class="alm-cal-picker-months" id="alm-cal-picker-months"></div>
              <div style="display:flex;justify-content:center;margin-top:10px">
                <button type="button" class="btn btn-ghost btn-sm" onclick="goAlmCalToday()">Hoje</button>
              </div>
            </div>
            <div class="alm-cal-dow"><span>Seg</span><span>Ter</span><span>Qua</span><span>Qui</span><span>Sex</span><span>Sáb</span><span>Dom</span></div>
            <div class="alm-cal-grid" id="alm-cal-grid"></div>
            <div class="alm-cal-legend">
              <span><i class="alm-dot saved"></i> Alarme</span>
              <span><i class="alm-dot draft"></i> Este rascunho</span>
              <span><i class="alm-dot off"></i> Desligado</span>
            </div>
            <div class="alm-cal-agenda" id="alm-cal-agenda"></div>
          </div>
          <div class="alarm-form alm-form" id="alarmForm">
            <div class="alarm-form-title" id="alarm-form-title">Novo alarme</div>
            <p class="item-sub" style="margin:-8px 0 14px">Clique no calendário para marcar o dia — dá para mudar o mês e o ano. O rascunho aparece em amarelo.</p>
            <div class="form-label">Rótulo</div>
            <input id="alarmLabel" type="text" placeholder="Ex.: acordar, consulta, lixo" oninput="onAlarmFormChange()"/>
            <div class="form-label" style="margin-top:14px">Quando repetir</div>
            <input type="hidden" id="alarm-type-input" value="once"/>
            <div class="alm-type-pills">
              <button type="button" class="alm-type-pill active" data-type="once" onclick="setAlarmType('once')">Uma vez</button>
              <button type="button" class="alm-type-pill" data-type="daily" onclick="setAlarmType('daily')">Todo dia</button>
              <button type="button" class="alm-type-pill" data-type="weekly" onclick="setAlarmType('weekly')">Na semana</button>
              <button type="button" class="alm-type-pill" data-type="monthly" onclick="setAlarmType('monthly')">Todo mês</button>
            </div>
            <div class="item-sub" id="alm-when-hint" style="margin:8px 0 0">Clique num dia no calendário para escolher a data.</div>
            <div class="form-label" style="margin-top:14px">Horário</div>
            <div class="alm-time-pills">
              <button type="button" class="alm-time-pill" data-time="07:00" onclick="setAlarmTime('07:00')">07:00</button>
              <button type="button" class="alm-time-pill active" data-time="09:00" onclick="setAlarmTime('09:00')">09:00</button>
              <button type="button" class="alm-time-pill" data-time="12:00" onclick="setAlarmTime('12:00')">12:00</button>
              <button type="button" class="alm-time-pill" data-time="15:00" onclick="setAlarmTime('15:00')">15:00</button>
              <button type="button" class="alm-time-pill" data-time="18:00" onclick="setAlarmTime('18:00')">18:00</button>
              <button type="button" class="alm-time-pill" data-time="21:00" onclick="setAlarmTime('21:00')">21:00</button>
            </div>
            <div class="alm-time-custom">
              <span>Outro</span>
              <input type="time" id="alarmTime" value="09:00" onchange="onAlarmTimeInput()"/>
            </div>
            <div id="alarm-date-field" style="margin-top:14px">
              <div class="form-label">Data</div>
              <button type="button" class="alm-picked" id="alarm-date-label" onclick="focusAlmCalendar()">Clique no calendário</button>
            </div>
            <div id="alarm-weekdays-field" hidden style="margin-top:14px">
              <div class="form-label">Dias da semana</div>
              <div class="day-picker" id="dayPicker">
                <button type="button" class="day-btn" data-day="0">Seg</button>
                <button type="button" class="day-btn" data-day="1">Ter</button>
                <button type="button" class="day-btn" data-day="2">Qua</button>
                <button type="button" class="day-btn" data-day="3">Qui</button>
                <button type="button" class="day-btn" data-day="4">Sex</button>
                <button type="button" class="day-btn" data-day="5">Sáb</button>
                <button type="button" class="day-btn" data-day="6">Dom</button>
              </div>
              <div class="day-presets">
                <button type="button" class="btn btn-ghost btn-sm" onclick="setPreset([0,1,2,3,4])">Dias úteis</button>
                <button type="button" class="btn btn-ghost btn-sm" onclick="setPreset([5,6])">Fim de semana</button>
              </div>
            </div>
            <div id="alarm-dom-field" hidden style="margin-top:14px">
              <div class="form-label">Dia do mês</div>
              <button type="button" class="alm-picked" id="alarm-dom-label" onclick="focusAlmCalendar()">Clique no calendário</button>
            </div>
            <div class="alm-preview hint" id="alm-preview" style="margin-top:14px">Clique no calendário e escolha o horário.</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px">
              <button type="button" class="btn btn-ghost" onclick="startNewAlarm()">Limpar</button>
              <button type="button" class="btn btn-primary" id="alarmAdd"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Criar alarme</button>
            </div>
          </div>
        </div>
        <div class="list" id="alarmList" style="margin-top:16px"></div>
      </div>

      <!-- ══ AGENDA ══ -->
      <div class="tab-panel hidden" id="tab-agenda">
        <div class="sec-hdr">
          <span class="sec-title">Agenda</span>
          <div style="display:flex;gap:8px;align-items:center">
            <select id="agendaDays" style="padding:5px 8px;font-size:12px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text)">
              <option value="1">Hoje</option><option value="2">Amanhã</option><option value="7" selected>7 dias</option><option value="30">30 dias</option>
            </select>
            <button class="btn btn-ghost btn-sm" onclick="loadAgenda()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg></button>
          </div>
        </div>

        <!-- Status da conexão -->
        <div id="agendaConnBanner" style="display:none;margin-bottom:16px;padding:12px 14px;border-radius:8px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);font-size:13px;color:#f87171">
          Agenda não conectada. Vá em <strong>Configurações → Conta de Agenda</strong> para conectar.
        </div>

        <!-- Novo evento -->
        <div class="alarm-form" id="agendaNewForm">
          <div class="alarm-form-title">Novo compromisso</div>
          <div class="row" style="flex-wrap:wrap;gap:8px">
            <input id="evTitle" type="text" placeholder="Título do compromisso" style="flex:2;min-width:180px"/>
            <input id="evDate" type="date" style="flex:none;width:150px"/>
          </div>
          <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:8px">
            <div style="display:flex;align-items:center;gap:6px;font-size:13px"><label>Início</label><input id="evStart" type="time" value="09:00" style="width:110px"/></div>
            <div style="display:flex;align-items:center;gap:6px;font-size:13px"><label>Fim</label><input id="evEnd" type="time" value="10:00" style="width:110px"/></div>
          </div>
          <div class="row" style="margin-top:8px"><input id="evDesc" type="text" placeholder="Descrição (opcional)"/></div>
          <div style="margin-top:12px"><button class="btn btn-primary" id="evAdd"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Criar compromisso</button></div>
        </div>

        <div class="list" id="agendaList"></div>
      </div>

      <!-- ══ ROUTINES ══ -->
      <div class="tab-panel hidden" id="tab-routines">
        <div class="sec-hdr"><span class="sec-title">Rotinas</span><span class="count-badge" id="routineCount">0 rotinas</span></div>
        <div class="alarm-form" id="routineForm">
          <div class="alarm-form-title">Nova rotina</div>
          <div class="row"><input id="routineName" type="text" placeholder="Nome (ex.: Rotina matinal)"/></div>
          <div class="form-label" style="margin-top:12px">Gatilho</div>
          <div class="row" style="gap:12px;flex-wrap:wrap">
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px"><input type="radio" name="rTrigType" value="alarm" checked onchange="rTrigChange()"/> Quando alarme tocar</label>
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px"><input type="radio" name="rTrigType" value="time" onchange="rTrigChange()"/> Horário fixo diário</label>
          </div>
          <div id="rTrigAlarmSel" style="margin-top:8px"><select id="routineAlarmId" class="settings-select" style="max-width:100%;width:280px"><option value="">-- selecione um alarme --</option></select></div>
          <div id="rTrigTimeSel" style="margin-top:8px;display:none"><input id="routineTimeHhmm" type="time" style="max-width:140px"/></div>
          <div class="form-label" style="margin-top:14px">Ações <span style="font-weight:400;opacity:.6">(em ordem)</span></div>
          <div style="display:flex;flex-direction:column;gap:8px;margin-top:6px">
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="noticias"/> Notícias do dia</label>
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="cotacao"/> Cotações do mercado</label>
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="clima"/> Previsão do tempo</label>
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="esporte"/> Resultados esportivos</label>
            <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="transito"/> Trânsito em tempo real</label>
            <div style="display:flex;flex-direction:column;gap:4px">
              <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer"><input type="checkbox" class="rAct" value="falar" id="rActFalar" onchange="document.getElementById('routineFalarText').style.display=this.checked?'block':'none'"/> Falar mensagem personalizada</label>
              <input type="text" id="routineFalarText" placeholder="Texto a falar…" style="display:none;margin-left:26px;width:calc(100% - 26px)"/>
            </div>
          </div>
          <div style="margin-top:14px"><button class="btn btn-primary" id="routineAdd"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Criar rotina</button></div>
        </div>
        <div class="list" id="routineList"></div>
      </div>

      <!-- ══ SETTINGS ══ -->
      <div class="tab-panel hidden" id="tab-settings">
        <div class="sec-hdr">
          <span class="sec-title">Configurações</span>
          <div class="save-bar">
            <button class="btn btn-primary btn-sm" id="saveSettingsBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Salvar</button>
            <span class="save-toast" id="saveToast">Salvo!</span>
          </div>
        </div>

        <div class="settings-layout">

          <!-- Modelo de IA (LLM) -->
          <div class="settings-card full llm-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>Modelo de IA</div>
            <div class="llm-section">Texto</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Provedor</div><div class="settings-row-desc">Quem conversa e executa os pedidos</div></div>
              <div class="settings-row-control"><select id="llm-provider" class="settings-select"><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="local">Local (Llama Desk)</option></select></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">OpenAI <span class="llm-active" id="llm-openai-active"></span></div><div class="settings-row-desc" id="llm-openai-desc">Modelo e chave</div></div>
              <div class="settings-row-control" style="gap:8px;flex-wrap:wrap">
                <input type="text" id="llm-openai-model" class="llm-input" list="llm-openai-models" placeholder="gpt-4o-mini"/>
                <input type="password" id="llm-openai-key" class="llm-input" placeholder="Chave (sk-...)" autocomplete="off"/>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">DeepSeek <span class="llm-active" id="llm-deepseek-active"></span></div><div class="settings-row-desc" id="llm-deepseek-desc">Modelo e chave</div></div>
              <div class="settings-row-control" style="gap:8px;flex-wrap:wrap">
                <input type="text" id="llm-deepseek-model" class="llm-input" list="llm-deepseek-models" placeholder="deepseek-flash"/>
                <input type="password" id="llm-deepseek-key" class="llm-input" placeholder="Chave (sk-...)" autocomplete="off"/>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Local · Llama Desk <span class="llm-active" id="llm-local-active"></span></div><div class="settings-row-desc" id="llm-local-desc">Modelos do Llama Desk no PC</div></div>
              <div class="settings-row-control" style="gap:8px;flex-wrap:wrap">
                <input type="text" id="llm-local-url" class="llm-input" placeholder="http://desktop-cc6nlck.local:8002"/>
                <select id="llm-local-model" class="settings-select"><option value="">—</option></select>
                <button type="button" class="btn btn-ghost btn-sm" id="llmLocalRefresh" title="Buscar os modelos do Llama Desk">Atualizar</button>
              </div>
            </div>
            <div class="llm-section">Voz</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Motor de voz</div><div class="settings-row-desc">Automático: Azure, depois OpenAI</div></div>
              <div class="settings-row-control">
                <select id="voice-engine" class="settings-select">
                  <option value="auto">Automático</option>
                  <option value="azure">Azure (grátis)</option>
                  <option value="openai">OpenAI (pago)</option>
                  <option value="espeak">espeak (grátis, robótica)</option>
                  <option value="piper">Piper (grátis, lenta)</option>
                </select>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Voz do Azure <span class="llm-active" id="llm-azure-active"></span></div><div class="settings-row-desc" id="llm-azure-desc">Grátis até 500 mil caracteres/mês</div></div>
              <div class="settings-row-control" style="gap:8px;flex-wrap:wrap">
                <input type="password" id="llm-azure-key" class="llm-input" placeholder="Chave do Azure" autocomplete="off"/>
                <input type="text" id="llm-azure-region" class="llm-input" placeholder="brazilsouth" style="max-width:130px"/>
                <select id="llm-azure-voice" class="settings-select"><option value="">—</option></select>
                <button type="button" class="btn btn-ghost btn-sm" id="llmAzureTest">Testar voz</button>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Voz da OpenAI</div><div class="settings-row-desc">Pago · usa a chave da OpenAI</div></div>
              <div class="settings-row-control" style="gap:8px;flex-wrap:wrap">
                <select id="voice-tts-model" class="settings-select">
                  <option value="gpt-4o-mini-tts">gpt-4o-mini-tts</option>
                  <option value="tts-1">tts-1</option>
                  <option value="tts-1-hd">tts-1-hd</option>
                </select>
                <select id="voice-tts-voice" class="settings-select">
                  <option value="alloy">Alloy</option>
                  <option value="echo">Echo</option>
                  <option value="fable">Fable</option>
                  <option value="onyx">Onyx</option>
                  <option value="nova">Nova</option>
                  <option value="shimmer">Shimmer</option>
                </select>
              </div>
            </div>
            <div class="llm-section">Transcrição</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Quem transcreve</div><div class="settings-row-desc">O que você fala vira texto</div></div>
              <div class="settings-row-control">
                <select id="stt-provider" class="settings-select">
                  <option value="auto">Automático</option>
                  <option value="openai">OpenAI (pago)</option>
                  <option value="azure">Azure (grátis até 5 h/mês)</option>
                  <option value="local">Local (grátis, menos preciso)</option>
                </select>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Modelo da OpenAI</div><div class="settings-row-desc">Quando for pela OpenAI</div></div>
              <div class="settings-row-control">
                <select id="stt-model" class="settings-select">
                  <option value="gpt-4o-mini-transcribe">gpt-4o-mini-transcribe</option>
                  <option value="gpt-4o-transcribe">gpt-4o-transcribe</option>
                  <option value="whisper-1">whisper-1</option>
                </select>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Detecção do nome</div><div class="settings-row-desc">Sempre no próprio Pi</div></div>
              <div class="settings-row-control"><span class="llm-active">local · grátis</span></div>
            </div>
            <datalist id="llm-openai-models"><option value="gpt-4o-mini"/><option value="gpt-4o"/></datalist>
            <datalist id="llm-deepseek-models"><option value="deepseek-flash"/><option value="deepseek-v4-pro"/></datalist>
            <div class="llm-note" id="llm-audio-note">A DeepSeek só faz texto. Voz (fala da Cassandra) e microfone usam sempre a OpenAI.</div>
            <div class="save-bar" style="margin-top:12px">
              <button class="btn btn-primary btn-sm" id="saveLlmBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>Salvar modelos</button>
              <span class="save-toast" id="llmToast">Salvo!</span>
            </div>
          </div>

          <!-- Módulos -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>Módulos ativos</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Chat</div><div class="settings-row-desc">Conversa com a Cassandra por texto</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-chat" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Música</div><div class="settings-row-desc">Spotify: tocar, buscar, playlists e controles</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-music" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Aparelhos</div><div class="settings-row-desc">TVs, Fire TV e Bluetooth: conectar e controlar</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-devices" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Compras</div><div class="settings-row-desc">Lista de compras com voz</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-shopping" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Tarefas</div><div class="settings-row-desc">Gerenciamento de to-dos por voz</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-todos" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Alarmes</div><div class="settings-row-desc">Alarmes recorrentes por dia da semana</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-alarms" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Rotinas</div><div class="settings-row-desc">Automações disparadas por alarme ou horário</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-routines" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Agenda</div><div class="settings-row-desc">Calendário via CalDAV (Google, iCloud, Nextcloud)</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="mod-agenda" checked/><span class="toggle-slider"></span></label></div>
            </div>
          </div>

          <!-- Voz & TTS -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>Voz & TTS</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Resposta por voz</div><div class="settings-row-desc">Cassandra fala as respostas em voz alta</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="voice-enabled" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Idioma fallback</div><div class="settings-row-desc">Idioma da voz grátis (espeak)</div></div>
              <div class="settings-row-control">
                <select id="voice-fallback-lang" class="settings-select">
                  <option value="pt">Português</option>
                  <option value="en">English</option>
                  <option value="es">Español</option>
                </select>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Velocidade da fala</div><div class="settings-row-desc">Vozes grátis (Piper e espeak); 160 = normal</div></div>
              <div class="settings-row-control">
                <div class="settings-range">
                  <input type="range" id="voice-rate" min="80" max="280" step="10" value="160"/>
                  <span class="settings-range-val" id="voice-rate-val">160</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Sons -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="23" y2="15"/><line x1="20" y1="12" x2="20" y2="12"/></svg>Sons do sistema</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Sons de interação</div><div class="settings-row-desc">Toques de ativação, desativação e alertas</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="sounds-enabled" checked/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info" style="flex-basis:100%"><div class="settings-row-label">Volume</div><div class="settings-row-desc" id="vol-desc">Volume da saída de áudio atual — ou diga "volume 70%"</div></div>
              <div class="vol-control" id="vol-control">
                <button class="btn btn-ghost btn-icon" id="vol-mute" title="Silenciar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path id="vol-mute-waves" d="M15.54 8.46a5 5 0 010 7.07"/><g id="vol-mute-x" style="display:none"><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></g></svg></button>
                <button class="btn btn-ghost btn-sm" id="vol-down" title="Diminuir">−</button>
                <input type="range" id="vol-range" min="0" max="100" step="1" value="0" disabled/>
                <button class="btn btn-ghost btn-sm" id="vol-up" title="Aumentar">+</button>
                <span class="vol-val" id="vol-val">—</span>
              </div>
            </div>
            <div class="settings-row" style="border-bottom:none">
              <div class="settings-row-info"><div class="settings-row-label">Saída de áudio</div><div class="settings-row-desc">Onde a Cassandra toca (caixas Bluetooth aparecem aqui quando conectadas)</div></div>
              <div class="settings-row-control"><select id="audio-output" class="settings-select" style="max-width:220px"><option value="">—</option></select></div>
            </div>
          </div>

          <!-- Bluetooth -->
          <div class="settings-card full">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5"/></svg>Bluetooth</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Bluetooth</div><div class="settings-row-desc" id="bt-desc">Caixas de som, fones e outros aparelhos</div></div>
              <div class="settings-row-control"><label class="toggle"><input type="checkbox" id="bt-power"/><span class="toggle-slider"></span></label></div>
            </div>
            <div class="bt-section-label">Meus aparelhos</div>
            <div class="bt-list" id="bt-paired"><div class="bt-empty">Carregando…</div></div>
            <div class="bt-section-label" style="display:flex;align-items:center;gap:10px">
              <span style="flex:1">Conectar um aparelho novo</span>
              <button class="btn btn-primary btn-sm" id="bt-scan">Procurar aparelhos</button>
            </div>
            <div class="settings-row-desc">Coloque o aparelho em modo de pareamento (normalmente segurando o botão de Bluetooth dele) e toque em <b>Procurar aparelhos</b>.</div>
            <div class="bt-list" id="bt-found"></div>
            <div class="bt-job" id="bt-job"></div>
          </div>

          <!-- Spotify -->
          <div class="settings-card full">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M7 9.5c3.5-1 7-.6 10 1"/><path d="M7.5 12.5c3-.8 5.8-.4 8.3.9"/><path d="M8 15.4c2.4-.6 4.6-.3 6.5.7"/></svg>Spotify</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Conta</div><div class="settings-row-desc" id="sp-account">Verificando…</div></div>
              <div class="settings-row-control" style="gap:8px">
                <button class="btn btn-primary btn-sm" id="sp-connect" style="display:none">Conectar Spotify</button>
                <button class="btn btn-ghost btn-sm" id="sp-renew" style="display:none" title="Faz o login de novo (o Spotify pede a cada 180 dias)">Renovar credenciais</button>
                <button class="btn btn-ghost btn-sm" id="sp-disconnect" style="display:none">Desconectar</button>
              </div>
            </div>
            <div class="settings-row" id="sp-device-row" style="display:none">
              <div class="settings-row-info"><div class="settings-row-label">Caixa "<span id="sp-device-name">Cassandra</span>"</div><div class="settings-row-desc" id="sp-device-desc">—</div></div>
              <div class="settings-row-control"><span class="info-chip" id="sp-device-chip">—</span></div>
            </div>
            <div id="sp-player" style="display:none">
              <div class="sp-now">
                <img class="sp-cover" id="sp-cover" alt=""/>
                <div class="sp-info"><div class="sp-title" id="sp-title">Nada tocando</div><div class="sp-artist" id="sp-artist">Peça "Cassandra, toca …" ou use o campo abaixo</div></div>
                <div class="sp-controls">
                  <button class="btn btn-ghost btn-icon" data-sp="previous" title="Anterior"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h2v14H6zM20 5v14L9 12z"/></svg></button>
                  <button class="btn btn-primary btn-icon" data-sp="toggle" id="sp-toggle" title="Tocar/pausar"><svg viewBox="0 0 24 24" fill="currentColor" id="sp-toggle-icon"><path d="M8 5v14l11-7z"/></svg></button>
                  <button class="btn btn-ghost btn-icon" data-sp="next" title="Próxima"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 5h2v14h-2zM4 5v14l11-7z"/></svg></button>
                </div>
              </div>
              <div class="sp-play-row">
                <input type="text" id="sp-query" placeholder="Tocar… (ex.: Legião Urbana, playlist de rock, minhas curtidas)"/>
                <button class="btn btn-primary btn-sm" id="sp-play">Tocar</button>
              </div>
              <div class="settings-row-desc" style="margin-top:10px">Por voz: "toca Tempo Perdido", "coloca a playlist X", "toca um sertanejo", "pausa", "próxima", "abaixa a música", "que música é essa?", "curti essa", "põe na fila …", "modo aleatório".</div>
            </div>
            <div class="bt-job" id="sp-msg"></div>
          </div>

          <!-- Sessão -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Sessão ativa</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Timeout de sessão</div><div class="settings-row-desc">Segundos sem comando até a sessão expirar automaticamente</div></div>
              <div class="settings-row-control">
                <input type="number" id="session-timeout" min="10" max="300" step="5" value="30" style="width:80px;flex:none;text-align:center"/>
              </div>
            </div>
          </div>

          <!-- Conta de Agenda (CalDAV) -->
          <div class="settings-card full">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>Conta de Agenda</div>
            <div class="settings-row">
              <div class="settings-row-info">
                <div class="settings-row-label">Status</div>
                <div class="settings-row-desc" id="cal-user-label" style="font-size:11px">—</div>
              </div>
              <div class="settings-row-control" style="gap:8px">
                <span id="cal-badge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--border);color:var(--text2)">
                  <span id="cal-dot" style="width:9px;height:9px;border-radius:50%;background:#6b7280;flex-shrink:0;display:inline-block"></span>
                  <span id="cal-badge-label">Não conectada</span>
                </span>
                <button class="btn btn-danger btn-sm" id="calDisconnectBtn" style="display:none">Desconectar</button>
              </div>
            </div>
            <div id="calConnForm">
              <div class="form-label" style="margin-top:14px;margin-bottom:8px">Provedor</div>
              <div class="row" style="gap:8px;flex-wrap:wrap;margin-bottom:10px">
                <button class="btn btn-ghost btn-sm cal-provider-btn" data-url="https://apidata.googleusercontent.com/caldav/v2/{email}/events">Google Calendar</button>
                <button class="btn btn-ghost btn-sm cal-provider-btn" data-url="https://caldav.icloud.com">Apple iCloud</button>
                <button class="btn btn-ghost btn-sm cal-provider-btn" data-url="">Outro (manual)</button>
              </div>
              <div class="row" style="flex-direction:column;gap:8px">
                <input id="calUrl" type="text" placeholder="URL CalDAV (ex: https://apidata.googleusercontent.com/caldav/v2/seu@gmail.com/events)"/>
                <input id="calUsername" type="email" placeholder="E-mail (ex: seu@gmail.com)"/>
                <input id="calPassword" type="password" placeholder="Senha de app (Google: conta → Segurança → Senhas de app)"/>
              </div>
              <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
                <button class="btn btn-primary btn-sm" id="calConnectBtn">Conectar e testar</button>
                <span id="calTestMsg" style="font-size:12px;color:var(--text2)"></span>
              </div>
              <div style="margin-top:10px;font-size:11px;color:var(--text2);line-height:1.5">
                <strong>Google:</strong> ative a verificação em 2 etapas → Google Account → Segurança → Senhas de app → crie uma para "Cassandra".<br/>
                <strong>iCloud:</strong> Apple ID → Segurança → Senhas de app específicas do app.
              </div>
            </div>
          </div>

          <!-- Maestro (ponte para os outros agentes) -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 010 20M12 2a15.3 15.3 0 000 20"/></svg>Maestro</div>
            <div class="settings-row">
              <div class="settings-row-info">
                <div class="settings-row-label">Status da conexão</div>
                <div class="settings-row-desc" id="web-agent-url" style="font-family:monospace;font-size:11px">—</div>
              </div>
              <div class="settings-row-control" style="gap:8px">
                <span id="web-agent-badge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--border);color:var(--text2)">
                  <span id="web-agent-dot" style="width:9px;height:9px;border-radius:50%;background:#6b7280;flex-shrink:0;display:inline-block"></span>
                  <span id="web-agent-label">Verificando…</span>
                </span>
                <button class="btn btn-ghost btn-sm" id="checkWebAgentBtn" title="Verificar agora"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg></button>
              </div>
            </div>
            <div class="settings-row" style="border-bottom:none">
              <div class="settings-row-info">
                <div class="settings-row-label">Agentes que ele controla</div>
                <div class="settings-row-desc">A Cassandra pede tudo a outros agentes através do maestro (pesquisas na internet vão para o web-agent).</div>
                <div class="settings-row-desc" id="orch-agents" style="margin-top:6px">—</div>
              </div>
            </div>
          </div>

          <!-- Agentes que a Cassandra pode usar (lista vinda do Maestro) -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><line x1="12" y1="8" x2="6.5" y2="16.5"/><line x1="12" y1="8" x2="17.5" y2="16.5"/></svg>Agentes que a Cassandra usa</div>
            <div class="settings-row">
              <div class="settings-row-info">
                <div class="settings-row-label">Acesso aos agentes do Maestro</div>
                <div class="settings-row-desc">Com o acesso ligado, a Cassandra pode pedir coisas a esse agente (ex.: "pesquise X", "leia meu WhatsApp", "crie um site"). A lista vem do Maestro: um agente novo aparece aqui sozinho, já liberado.</div>
              </div>
              <div class="settings-row-control"><button class="btn btn-ghost btn-sm" id="agAccessRefresh" title="Atualizar a lista"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg></button></div>
            </div>
            <div id="agAccessList"><div class="settings-row" style="border-bottom:none"><div class="settings-row-desc">Carregando…</div></div></div>
          </div>

          <!-- Sistema (read-only) -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>Sistema</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Nome do assistente</div></div>
              <div class="settings-row-control"><span class="info-chip" id="info-name">—</span></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Modo de entrada</div></div>
              <div class="settings-row-control"><span class="info-chip" id="info-input">—</span></div>
            </div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Modelo de IA</div></div>
              <div class="settings-row-control"><span class="info-chip" id="info-model">—</span></div>
            </div>
          </div>

          <!-- Dados -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>Dados & histórico</div>
            <div class="settings-row">
              <div class="settings-row-info"><div class="settings-row-label">Exportar histórico</div><div class="settings-row-desc">Baixa todas as mensagens em JSON</div></div>
              <div class="settings-row-control"><button class="btn btn-ghost btn-sm" id="exportHistBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Exportar</button></div>
            </div>
            <div class="settings-row" style="border-bottom:none">
              <div class="settings-row-info"><div class="settings-row-label">Limpar histórico</div><div class="settings-row-desc">Remove todas as mensagens permanentemente</div></div>
              <div class="settings-row-control"><button class="btn btn-danger btn-sm" id="clearHistBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/></svg>Limpar</button></div>
            </div>
          </div>

          <!-- Reset -->
          <div class="settings-card">
            <div class="settings-card-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>Restaurar padrões</div>
            <div class="settings-row" style="border-bottom:none">
              <div class="settings-row-info"><div class="settings-row-label">Restaurar configurações</div><div class="settings-row-desc">Volta todos os ajustes para os valores originais</div></div>
              <div class="settings-row-control"><button class="btn btn-warn btn-sm" id="resetSettingsBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>Restaurar</button></div>
            </div>
          </div>

        </div>
      </div>

    </div>
  </div>
</div>


<div class="alarm-toast" id="alarmToast" role="alertdialog" aria-live="assertive"><div class="at-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div><div class="at-text"><div class="at-title">Alarme tocando</div><div class="at-sub" id="alarmToastSub"></div></div><button class="at-stop" id="alarmToastStop">Parar alarme</button></div>
<div class="restart-overlay" id="restartOverlay"><div class="restart-box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg><div id="restartTitle">Reiniciando a Cassandra…</div><p id="restartText">Leva uns 20 segundos. A página volta sozinha.</p></div></div>

<script>
const IC = {
  dashboard:`<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
  chat:     `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  mic:      `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0014 0"/><line x1="12" y1="17" x2="12" y2="22"/></svg>`,
  devices:  `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="13" rx="2"/><polyline points="17 2 12 7 7 2"/></svg>`,
  music:    `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
  shopping: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>`,
  todos:    `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>`,
  alarms:   `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>`,
  routines: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 014-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>`,
  agenda:   `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
  settings: `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
  habits:   `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14.5 17.5l2.2 2.2 4-4.4"/></svg>`,
  costs:    `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>`,
  trash:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>`,
  check:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
  undo:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 00-4-4H4"/></svg>`,
  x:        `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
};

// All possible tabs (settings always shown)
// Grupos da barra lateral: "" = sem título (o topo).
const ALL_TABS = [
  {id:"dashboard", label:"Dashboard",  group:""},
  {id:"chat",      label:"Chat",       group:""},
  {id:"music",     label:"Música",     group:"Casa"},
  {id:"devices",   label:"Aparelhos",  group:"Casa"},
  {id:"shopping",  label:"Compras",    group:"Organização"},
  {id:"todos",     label:"Tarefas",    group:"Organização"},
  {id:"habits",    label:"Hábitos",    group:"Organização"},
  {id:"agenda",    label:"Agenda",     group:"Organização"},
  {id:"alarms",    label:"Alarmes",    group:"Automação"},
  {id:"routines",  label:"Rotinas",    group:"Automação"},
  {id:"mic",       label:"Microfone",  group:"Sistema"},
  {id:"costs",     label:"Gastos",     group:"Sistema"},
  {id:"settings",  label:"Config.",    group:"Sistema"},
];
let currentTab = "dashboard";
const PAGE_TITLES = {
  dashboard:"Dashboard",chat:"Chat",music:"Música",devices:"Aparelhos",mic:"Microfone",shopping:"Compras",
  todos:"Tarefas",habits:"Hábitos",alarms:"Alarmes",routines:"Rotinas",agenda:"Agenda",settings:"Configurações",costs:"Gastos",
};
const DAY_NAMES = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"];
const MONTHS_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"];
const MONTHS_SHORT = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];
function _isoDate(d){
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}
let selDays = [];
let _alarmsCache = [];
let _almType = "once";
const _nowCal = new Date();
let _almDate = _isoDate(_nowCal);
let _almDom = _nowCal.getDate();
let _almTime = "09:00";
let _almCalYear = _nowCal.getFullYear();
let _almCalMonth = _nowCal.getMonth();
let _almCalSelected = _isoDate(_nowCal);
let _almPickerOpen = false;
let currentSettings = {};

// ── Utils ──
const esc = t=>(t||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function _apiError(message,status){
  const err=new Error(message);
  err.status=status||0;
  return err;
}
function isGatewayTimeout(err){
  const status=err&&err.status;
  const msg=String(err&&err.message||"");
  return status===502||status===503||status===504||/HTTP 50[234]/.test(msg)||/não respondeu a tempo/i.test(msg);
}
function alertUnlessTimeout(err){
  if(isGatewayTimeout(err)) return;
  alert(err&&err.message||String(err));
}
async function api(path,method="GET",body=null){
  let r;
  try{r=await fetch(path,{method,headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):null});}
  catch(e){throw _apiError("Sem conexão com a Cassandra. Tente de novo.",0);}
  const text=await r.text();
  let d;
  try{d=text?JSON.parse(text):{};}
  catch(e){throw _apiError(r.ok?"Resposta inválida da Cassandra.":`A Cassandra não respondeu a tempo (HTTP ${r.status}). Tente de novo.`,r.status);}
  if(!r.ok) throw _apiError(d.error||`Erro na API (HTTP ${r.status})`,r.status);
  return d;
}
function enter(el,fn){el.addEventListener("keydown",e=>{if(e.key==="Enter")fn()});}
function fmtTime(ts){return(ts||"").substring(11,16);}

// ── Visible tabs based on settings modules ──
function getVisibleTabs(){
  const mods = currentSettings.modules || {};
  return ALL_TABS.filter(t=>{
    if(t.id==="dashboard"||t.id==="settings"||t.id==="mic") return true;
    return mods[t.id]!==false;
  });
}

// ── Build nav ──
function buildNav(container,visibleTabs){
  let group=null;
  container.innerHTML=visibleTabs.map(t=>{
    const header=t.group!==group&&t.group?`<div class="nav-section-label">${t.group}</div>`:"";
    group=t.group;
    return header+`<button class="nav-item${t.id===currentTab?" active":""}" data-tab="${t.id}" data-label="${t.label}">${IC[t.id]}<span class="nav-label">${t.label}</span></button>`;
  }).join("");
  container.querySelectorAll(".nav-item").forEach(b=>b.addEventListener("click",()=>gotoTab(b.dataset.tab)));
}

function rebuildNavs(){
  const vis=getVisibleTabs();
  buildNav(document.getElementById("desktopNav"),vis);
  buildNav(document.getElementById("mobileNav"),vis);
}

// ── Tab switching ──
function gotoTab(tab){
  currentTab=tab;
  document.querySelectorAll(".tab-panel").forEach(p=>{
    const show=p.id==="tab-"+tab;
    if(show&&p.classList.contains("hidden")){
      p.classList.remove("hidden");
      p.style.animation="none";p.offsetHeight;p.style.animation="";
    }else if(!show){p.classList.add("hidden");}
  });
  document.querySelectorAll(".nav-item,[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
  document.getElementById("pageTitle").textContent=PAGE_TITLES[tab]||tab;
  closeMobileMenu();
  if(tab==="music") muOpen();
  if(tab==="devices") dvOpen();
  if(tab==="mic") micOpen(); else micClose();
  if(tab==="alarms") renderAlmCalendar();
  if(tab==="costs") loadCosts();
  if(tab==="habits") loadHabits(true);
}

// ── Hábitos ── (as contas vêm prontas de /api/habits; aqui é só desenhar e registrar)
let hbData=null,hbYearSel=null,hbLast="",hbEditing=null,hbColor="";
const HB_MONTHS=["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];
const hbNum=v=>(+v||0).toLocaleString("pt-BR",{maximumFractionDigits:2});
const hbIso=d=>d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");
function hbGoal(h){
  const what=h.target==1&&!h.unit?(h.period==="week"?"1 vez":""):hbNum(h.target)+(h.unit?" "+h.unit:(h.period==="week"?" vezes":""));
  if(h.period==="week") return what+" por semana";
  const days=h.weekdays||[];
  const when=days.length===7?(what?"por dia":"todo dia"):days.map(d=>DAY_NAMES[d].toLowerCase()).join(", ");
  return what?what+" "+(days.length===7?when:"· "+when):when;
}
function hbStep(h){return h.target>=100?10:h.target>=30?5:1;}
function hbTodayRow(h){
  const t=h.today,many=h.target>1||h.period==="week",pct=Math.min(100,Math.round(t.progress/h.target*100));
  const sub=!t.scheduled?"hoje não é dia":many?hbNum(t.progress)+" / "+hbNum(h.target)+(h.unit?" "+esc(h.unit):"")+(h.period==="week"?" nesta semana":""):(t.done?"feito hoje":"ainda não");
  const streak=h.streak?"🔥 "+h.streak+(h.period==="week"?" sem":h.streak===1?" dia":" dias"):"";
  return `<div class="hb-today" style="--hc:${h.color};${t.scheduled?"":"opacity:.45"}">
    <button class="hb-check${t.done?" done":""}" data-hb-tog="${h.id}" title="${t.done?"Desmarcar":"Marcar como feito"}">${t.done?"✓":(h.emoji?esc(h.emoji):"")}</button>
    <div style="min-width:0"><b>${esc(h.name)}${h.emoji&&t.done?" "+esc(h.emoji):""}</b><small>${sub}</small>${many?`<div class="hb-bar"><i style="width:${pct}%"></i></div>`:""}</div>
    <div class="hb-step">${many?`<button data-hb-add="${h.id}" data-d="-${hbStep(h)}" title="Tirar">−</button><button data-hb-add="${h.id}" data-d="${hbStep(h)}" title="Somar">+</button>`:""}<span class="hb-streak">${streak}</span></div>
  </div>`;
}
function hbGridRow(h,year,today){
  const jan1=new Date(year,0,1),dec31=new Date(year,11,31);
  const start=new Date(jan1);start.setDate(start.getDate()-((jan1.getDay()+6)%7));  // a segunda da semana de 1º de janeiro
  const days=new Set(h.weekdays||[0,1,2,3,4,5,6]);
  let cells="",months=[];
  for(const d=new Date(start);d<=dec31||(d.getDay()+6)%7!==0;d.setDate(d.getDate()+1)){
    const iso=hbIso(d),wd=(d.getDay()+6)%7;
    if(wd===0){const end=new Date(d);end.setDate(end.getDate()+6);  // rotula a coluna (semana) em que cai o dia 1º do mês
      months.push(end.getDate()<=7&&end.getFullYear()===year?HB_MONTHS[end.getMonth()]:"");}
    if(d<jan1||d>dec31){cells+='<i class="hb-cell out"></i>';continue;}
    const r=h.cells[iso]||0,amount=h.amounts[iso]||0;
    let cls=iso>today?"future":r>0?"on"+(r>=1?"":r>=.66?" l3":r>=.33?" l2":" l1"):(iso<h.start||!days.has(wd)?"skip open":"open");
    if(iso===today) cls+=" today";
    const label=String(d.getDate()).padStart(2,"0")+"/"+String(d.getMonth()+1).padStart(2,"0")+(amount?" · "+hbNum(amount)+(h.unit?" "+h.unit:""):"");
    cells+=`<i class="hb-cell ${cls}" ${iso>today?"":`data-hb-day="${h.id}" data-date="${iso}"`} title="${esc(label)}"></i>`;
  }
  const done=h.period==="week"?h.done_count+" de "+h.total_count+" semanas":h.done_count+" de "+h.total_count+" dias";
  return `<div class="hb-row" style="--hc:${h.color}">
    <div class="hb-head"><span class="hb-dot">✓</span><span class="hb-name">${esc(h.name)}${h.emoji?" "+esc(h.emoji):""} <small>– ${esc(hbGoal(h))}</small></span>
      <span class="hb-meta">${h.total_count?done:""}</span><span class="hb-pct">${h.pct==null?"—":h.pct+"%"}</span>
      <button class="hb-edit" data-hb-edit="${h.id}" title="Editar">✎</button></div>
    <div class="hb-grid">${cells}</div>
    <div class="hb-months">${months.map(m=>`<span>${m}</span>`).join("")}</div>
  </div>`;
}
function hbBars(values,labels){
  const max=Math.max(...values.map(v=>v||0));
  return `<div class="hb-bars">${values.map(v=>`<div class="c${v==null?" none":v===max&&max>0?" best":""}"><small>${v==null?"":v+"%"}</small><i style="height:${v==null?2:Math.max(2,v*.8)}%"></i></div>`).join("")}</div>
    <div class="hb-bars-x">${labels.map(l=>`<span>${l}</span>`).join("")}</div>`;
}
function hbWeeksChart(weeks){
  const svg=document.getElementById("hbWeeks"),W=600,H=190,P=26,n=weeks.length;
  const x=i=>P+i*(W-2*P)/(n-1),y=v=>H-P-(v/100)*(H-2*P-6);
  let out="";
  [0,50,100].forEach(v=>{out+=`<line x1="${P}" y1="${y(v)}" x2="${W-P}" y2="${y(v)}" stroke="var(--border2)" stroke-dasharray="${v?"3 5":"0"}"/><text x="${P-5}" y="${y(v)+3}" font-size="10" text-anchor="end" fill="var(--text3)">${v}</text>`;});
  const pts=weeks.map((w,i)=>w.pct==null?null:[x(i),y(w.pct)]).filter(Boolean);
  if(pts.length>1){
    out+=`<polygon fill="var(--brand)" opacity=".12" points="${pts[0][0]},${y(0)} ${pts.map(p=>p.join(",")).join(" ")} ${pts[pts.length-1][0]},${y(0)}"/>`;
    out+=`<polyline fill="none" stroke="var(--brand)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" points="${pts.map(p=>p.join(",")).join(" ")}"/>`;
  }
  weeks.forEach((w,i)=>{
    if(w.pct!=null) out+=`<circle cx="${x(i)}" cy="${y(w.pct)}" r="${i===n-1?5:3.5}" fill="var(--brand2)" stroke="var(--surface)" stroke-width="2" vector-effect="non-scaling-stroke"><title>semana de ${w.start.slice(8,10)}/${w.start.slice(5,7)}: ${w.pct}%</title></circle>`;
    if(i%3===2||i===n-1) out+=`<text x="${x(i)}" y="${H-6}" font-size="10" text-anchor="${i===n-1?"end":"middle"}" fill="var(--text3)">${w.start.slice(8,10)}/${w.start.slice(5,7)}</text>`;
  });
  if(!pts.length) out+=`<text x="${W/2}" y="${H/2}" font-size="12" text-anchor="middle" fill="var(--text3)">Aparece depois dos primeiros registros</text>`;
  svg.innerHTML=out;
}
function renderHabits(d){
  hbData=d;const s=d.summary,any=d.habits.length>0;
  const none='<div class="empty" style="padding:22px 0">Nenhum hábito ainda. Crie o primeiro em “Novo hábito”.</div>';
  // dashboard: só o registro de hoje
  const box=document.getElementById("dashHabitsBox");box.style.display=any?"":"none";
  document.getElementById("dashHabitsCount").textContent=any?s.today_done+" de "+s.today_total+" · ver tudo →":"";
  document.getElementById("dashHabits").innerHTML=d.habits.filter(h=>h.today.scheduled).map(hbTodayRow).join("")||'<div class="cost-note" style="margin:0">Nenhum hábito previsto para hoje.</div>';
  // aba
  document.getElementById("hbStatToday").textContent=any?s.today_done+"/"+s.today_total:"—";
  document.getElementById("hbStatPct").textContent=s.pct==null?"—":s.pct+"%";
  document.getElementById("hbStatStreak").textContent=any?s.streak:"—";
  document.getElementById("hbStatBest").textContent=any?s.best_streak:"—";
  document.getElementById("hbTodayList").innerHTML=any?d.habits.map(hbTodayRow).join(""):none;
  document.getElementById("hbYearTitle").textContent=d.year+" em revisão";
  document.getElementById("hbGrids").innerHTML=any?[...d.habits].sort((a,b)=>(b.pct??-1)-(a.pct??-1)).map(h=>hbGridRow(h,d.year,d.today)).join(""):none;
  hbWeeksChart(d.weeks);
  document.getElementById("hbWeekdays").innerHTML=hbBars(d.weekdays,DAY_NAMES);
  document.getElementById("hbMonths").innerHTML=hbBars(d.months,HB_MONTHS);
  const sel=document.getElementById("hbYear"),thisYear=+d.today.slice(0,4);
  let first=thisYear;d.habits.forEach(h=>{first=Math.min(first,+h.start.slice(0,4));});
  let opts="";for(let y=thisYear;y>=first;y--) opts+=`<option${y===d.year?" selected":""}>${y}</option>`;
  sel.innerHTML=opts;sel.style.display=first<thisYear?"":"none";
}
async function loadHabits(force){
  if(!document.getElementById("hbModal").classList.contains("hidden")&&!force) return;
  try{
    const d=await api("/api/habits"+(hbYearSel?"?year="+hbYearSel:"")),json=JSON.stringify(d);
    if(json===hbLast&&!force) return;  // nada mudou: não redesenha a grade inteira a cada atualização
    hbLast=json;renderHabits(d);
  }catch(e){console.error("Hábitos:",e);}
}
async function hbLog(body){
  try{const d=await api("/api/habits/log","POST",{...body,year:hbYearSel});hbLast=JSON.stringify(d);renderHabits(d);}
  catch(e){alertUnlessTimeout(e);}
}
function hbOpenForm(h){
  hbEditing=h?h.id:null;hbColor=h?h.color:"";
  document.getElementById("hbFormTitle").textContent=h?"Editar hábito":"Novo hábito";
  document.getElementById("hbName").value=h?h.name:"";document.getElementById("hbEmoji").value=h?h.emoji:"";
  document.getElementById("hbTarget").value=h?String(h.target).replace(".",","):"1";document.getElementById("hbUnit").value=h?h.unit:"";
  document.getElementById("hbPeriod").value=h?h.period:"day";
  const on=new Set(h?h.weekdays:[0,1,2,3,4,5,6]);
  document.getElementById("hbDays").innerHTML=DAY_NAMES.map((n,i)=>`<button type="button" data-wd="${i}" class="${on.has(i)?"on":""}">${n}</button>`).join("");
  const colors=(hbData&&hbData.colors)||[];if(!hbColor){const used=new Set(((hbData&&hbData.habits)||[]).map(x=>x.color));hbColor=colors.find(c=>!used.has(c))||colors[0]||"";}
  document.getElementById("hbColors").innerHTML=colors.map(c=>`<button type="button" data-color="${c}" style="background:${c}" class="${c===hbColor?"on":""}" aria-label="cor"></button>`).join("");
  document.getElementById("hbDaysWrap").style.display=document.getElementById("hbPeriod").value==="week"?"none":"";
  document.getElementById("hbDelete").style.display=h?"":"none";document.getElementById("hbFormMsg").textContent="";
  document.getElementById("hbModal").classList.remove("hidden");
  if(!h) setTimeout(()=>document.getElementById("hbName").focus(),50);
}
function hbCloseForm(){document.getElementById("hbModal").classList.add("hidden");}
document.getElementById("hbNew").addEventListener("click",()=>hbOpenForm(null));
document.getElementById("hbCancel").addEventListener("click",hbCloseForm);
document.getElementById("hbModal").addEventListener("click",e=>{
  if(e.target.id==="hbModal") return hbCloseForm();
  const wd=e.target.closest("[data-wd]");if(wd) wd.classList.toggle("on");
  const c=e.target.closest("[data-color]");if(c){hbColor=c.dataset.color;document.querySelectorAll("#hbColors button").forEach(b=>b.classList.toggle("on",b===c));}
});
document.getElementById("hbPeriod").addEventListener("change",e=>{document.getElementById("hbDaysWrap").style.display=e.target.value==="week"?"none":"";});
document.getElementById("hbSave").addEventListener("click",async()=>{
  const body={id:hbEditing||undefined,name:document.getElementById("hbName").value,emoji:document.getElementById("hbEmoji").value,
    target:document.getElementById("hbTarget").value,unit:document.getElementById("hbUnit").value,period:document.getElementById("hbPeriod").value,
    color:hbColor,weekdays:[...document.querySelectorAll("#hbDays button.on")].map(b=>+b.dataset.wd),year:hbYearSel};
  try{const d=await api("/api/habits/save","POST",body);hbCloseForm();hbLast=JSON.stringify(d);renderHabits(d);}
  catch(e){document.getElementById("hbFormMsg").textContent=e.message;}
});
document.getElementById("hbDelete").addEventListener("click",async()=>{
  if(!hbEditing||!confirm("Excluir este hábito e todo o histórico dele?")) return;
  try{const d=await api("/api/habits/remove","POST",{id:hbEditing,year:hbYearSel});hbCloseForm();hbLast=JSON.stringify(d);renderHabits(d);}
  catch(e){document.getElementById("hbFormMsg").textContent=e.message;}
});
document.getElementById("hbYear").addEventListener("change",e=>{hbYearSel=+e.target.value;loadHabits(true);});
document.addEventListener("click",e=>{
  const byId=id=>hbData&&hbData.habits.find(h=>h.id===id);
  const tog=e.target.closest("[data-hb-tog]"),add=e.target.closest("[data-hb-add]"),day=e.target.closest("[data-hb-day]"),ed=e.target.closest("[data-hb-edit]");
  if(tog){const h=byId(tog.dataset.hbTog);if(!h) return;
    // hábito com quantidade: o botão completa a meta de hoje (ou zera, se já estava completa)
    if(h.period==="week") hbLog({id:h.id,toggle:true});
    else hbLog({id:h.id,amount:h.today.done?0:h.target});
  }else if(add){hbLog({id:add.dataset.hbAdd,delta:+add.dataset.d});
  }else if(day){const h=byId(day.dataset.hbDay);if(!h) return;const iso=day.dataset.date;
    if(h.target==1&&h.period!=="week"){hbLog({id:h.id,date:iso,toggle:true});return;}
    const now=h.amounts[iso]||0,v=prompt(`${h.name} em ${iso.slice(8,10)}/${iso.slice(5,7)}: quanto?${h.unit?" ("+h.unit+")":""} — meta ${hbNum(h.target)}${h.period==="week"?" por semana":" por dia"}`,String(now||(h.period==="week"?1:h.target)).replace(".",","));
    if(v!==null) hbLog({id:h.id,date:iso,amount:v});
  }else if(ed){const h=byId(ed.dataset.hbEdit);if(h) hbOpenForm(h);}
});

// ── Gastos ──
const COST_COLORS={llm:"#fb923c",tts:"#f472b6",stt:"#34d399"};
function usd(v){if(v==null)return"—";return v<0.01&&v>0?"US$ "+v.toFixed(4):"US$ "+v.toFixed(2);}
function fmtSecs(s){s=Math.round(s||0);return s>=3600?(s/3600).toFixed(1)+" h":s>=60?Math.round(s/60)+" min":s+" s";}
function fmtNum(n){return (n||0).toLocaleString("pt-BR");}
function drawCostChart(d){
  const svg=document.getElementById("costChart"),W=600,H=190,P=24,days=d.days,n=days.length;
  const kinds=Object.keys(d.kinds);
  const totals=days.map((_,i)=>kinds.reduce((a,k)=>a+d.daily[k][i],0));
  const max=Math.max(...totals,...kinds.flatMap(k=>d.daily[k]),0.0001);
  const x=i=>P+(n<2?0:i*(W-2*P)/(n-1)), y=v=>H-P-(v/max)*(H-2*P);
  let out=`<line x1="${P}" y1="${H-P}" x2="${W-P}" y2="${H-P}" stroke="var(--border2)"/>`;
  out+=`<text x="${P}" y="12" font-size="10" fill="var(--text3)">${usd(max)}</text>`;
  const line=(vals,color,w,dash)=>`<polyline fill="none" stroke="${color}" stroke-width="${w}" ${dash?'stroke-dasharray="4 4"':""} stroke-linejoin="round" vector-effect="non-scaling-stroke" points="${vals.map((v,i)=>x(i)+","+y(v)).join(" ")}"/>`;
  out+=line(totals,"var(--text3)",1.5,true);
  kinds.forEach(k=>{out+=line(d.daily[k],COST_COLORS[k],2.2);});
  [0,Math.floor((n-1)/2),n-1].forEach(i=>{out+=`<text x="${x(i)}" y="${H-6}" font-size="10" fill="var(--text3)" text-anchor="${i===0?"start":i===n-1?"end":"middle"}">${days[i].slice(8,10)}/${days[i].slice(5,7)}</text>`;});
  svg.innerHTML=out;
  document.getElementById("costLegend").innerHTML=kinds.map(k=>`<span><i style="background:${COST_COLORS[k]}"></i>${d.kinds[k]} ${usd(d.daily[k].reduce((a,b)=>a+b,0))}</span>`).join("")+`<span><i style="background:var(--text3)"></i>Total</span>`;
}
async function loadCosts(){
  const days=+document.getElementById("costDays").value||30;
  let d;
  try{d=await api("/api/usage?days="+days);}catch(e){document.getElementById("costUpdated").textContent=e.message;return;}
  document.getElementById("costToday").textContent=usd(d.totals.today);
  document.getElementById("costMonth").textContent=usd(d.totals.month);
  document.getElementById("costProj").textContent=usd(d.month_projection);
  document.getElementById("costPeriod").textContent=usd(d.totals.period);
  document.getElementById("costPeriodLbl").textContent=`nos últimos ${days} dias`;
  document.getElementById("costUpdated").textContent="Atualizado às "+new Date().toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"});
  drawCostChart(d);
  const rows=d.by_model.map(m=>{
    const qty=m.kind==="llm"?`${fmtNum(m.tokens_in)} → ${fmtNum(m.tokens_out)} tokens`:m.kind==="tts"?`${fmtNum(m.chars)} caracteres`:fmtSecs(m.seconds)+" de áudio";
    return `<tr><td><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${COST_COLORS[m.kind]};margin-right:6px"></i>${esc(d.kinds[m.kind])}</td><td>${esc(m.provider)} · ${esc(m.model)}</td><td class="num">${fmtNum(m.calls)}</td><td class="num">${qty}</td><td class="num">${usd(m.cost)}</td></tr>`;
  }).join("");
  document.getElementById("costModels").innerHTML=rows?`<tr><th>Tipo</th><th>Modelo</th><th class="num">Chamadas</th><th class="num">Uso</th><th class="num">Custo</th></tr>${rows}`:'<tr><td class="cost-note">Nada registrado ainda — o registro começa a contar a partir de agora.</td></tr>';
  const a=d.azure,tp=Math.min(100,a.tts_chars/a.tts_free*100),sp=Math.min(100,a.stt_seconds/a.stt_free*100);
  document.getElementById("costAzure").innerHTML=a.free_tier
    ?`<div style="font-size:13px">Voz: ${fmtNum(a.tts_chars)} de ${fmtNum(a.tts_free)} caracteres</div><div class="cost-bar"><div style="width:${tp}%"></div></div>
      <div style="font-size:13px;margin-top:10px">Transcrição: ${fmtSecs(a.stt_seconds)} de ${fmtSecs(a.stt_free)}</div><div class="cost-bar"><div style="width:${sp}%"></div></div>
      <div class="cost-note">Plano gratuito (F0): dentro da cota o Azure não cobra. Passando dela, ele recusa e a Cassandra usa a OpenAI.</div>`
    :`<div class="cost-note">Plano pago (S0): voz ${fmtNum(a.tts_chars)} caracteres, transcrição ${fmtSecs(a.stt_seconds)} este mês.</div>`;
  const c=d.cache;
  document.getElementById("costCache").innerHTML=`<div style="font-size:13px">${fmtNum(c.hits)} frases tocadas do cache (${fmtNum(c.chars)} caracteres sem gerar voz de novo) — cerca de ${usd(c.saved)} economizados.</div>`
    +(d.unpriced.length?`<div class="cost-note">Sem preço cadastrado: ${d.unpriced.map(esc).join(", ")}.</div>`:"");
}
document.getElementById("costDays").addEventListener("change",loadCosts);

// Enquanto a Cassandra trabalha num pedido do chat, mostra o que já chegou — ex.: o aviso "deixa eu dar uma
// olhada" antes de uma pesquisa ou de outro agente; o resultado vem depois, em outra mensagem.
setInterval(async()=>{
  if(currentTab!=="chat"||!document.getElementById("typingIndicator")) return;
  try{
    const d=await api("/api/history");
    const items=d.history||[];
    if(items.length>document.querySelectorAll("#messages .msg").length){renderMessages(items);showTyping();}
  }catch(e){}
},1500);

// ── Sidebar ──
const sidebar=document.getElementById("sidebar");
if(localStorage.getItem("sbCollapsed")==="1") sidebar.classList.add("collapsed");
document.getElementById("collapseBtn").addEventListener("click",()=>{
  sidebar.classList.toggle("collapsed");
  localStorage.setItem("sbCollapsed",sidebar.classList.contains("collapsed")?"1":"0");
});

// ── Mobile ──
const mobileOverlay=document.getElementById("mobileOverlay");
const mobileSidebar=document.getElementById("mobileSidebar");
document.getElementById("mobileMenuBtn").addEventListener("click",()=>{mobileOverlay.classList.add("open");mobileSidebar.classList.add("open");});
mobileOverlay.addEventListener("click",closeMobileMenu);
function closeMobileMenu(){mobileOverlay.classList.remove("open");mobileSidebar.classList.remove("open");}

// ── Clock ──
const MONTHS=["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"];
const WEEKDAYS=["Domingo","Segunda-feira","Terça-feira","Quarta-feira","Quinta-feira","Sexta-feira","Sábado"];
function tickClock(){
  const d=new Date();
  document.getElementById("clock").textContent=d.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  const h=d.getHours();
  document.getElementById("dashGreeting").textContent=(h<12?"Bom dia ☀️":h<18?"Boa tarde 🌤️":"Boa noite 🌙");
  document.getElementById("dashDate").textContent=`${WEEKDAYS[d.getDay()]}, ${d.getDate()} de ${MONTHS[d.getMonth()]} de ${d.getFullYear()}`;
}
setInterval(tickClock,1000);tickClock();

document.querySelectorAll(".stat-card[data-goto]").forEach(c=>c.addEventListener("click",()=>gotoTab(c.dataset.goto)));
document.getElementById("dashHabitsCount").addEventListener("click",()=>gotoTab("habits"));

// ── Tips ──
const TIPS=[
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>`,bg:"var(--amber-dim)",cl:"var(--amber)",title:"Alarmes inteligentes",ex:'"alarme às 7 de segunda a sexta"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,bg:"var(--brand-dim)",cl:"var(--brand2)",title:"Timers",ex:'"me avisa em 10 minutos"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10"/><path d="M12 2a15.3 15.3 0 014 10"/><path d="M22 12a10 10 0 01-10 10"/></svg>`,bg:"var(--cyan-dim)",cl:"var(--cyan)",title:"Pesquisa web",ex:'"como está o dólar hoje?" / "notícias de hoje"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>`,bg:"var(--green-dim)",cl:"var(--green)",title:"Lista de compras",ex:'"adiciona leite na lista de compras"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>`,bg:"var(--brand-dim)",cl:"var(--brand2)",title:"Tarefas",ex:'"cria tarefa: pagar conta de luz"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>`,bg:"var(--red-dim)",cl:"var(--red)",title:"Volume do sistema",ex:'"volume 70%" / "aumenta o volume"'},
  {svg:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,bg:"var(--purple-dim)",cl:"var(--purple)",title:"Agenda & lembretes",ex:'"lembra eu de ligar pra farmácia amanhã"'},
];
document.getElementById("tipsGrid").innerHTML=TIPS.map(t=>`
  <div class="tip-card">
    <div class="tip-icon" style="background:${t.bg};color:${t.cl}">${t.svg}</div>
    <div class="tip-title">${t.title}</div>
    <div class="tip-example">${esc(t.ex)}</div>
  </div>`).join("");

// ── Dashboard ──
function renderDashboard(data){
  const todos=(data.todos||[]).filter(t=>!t.completed).length;
  const shop=(data.shopping||[]).length;
  const alms=(data.alarms||[]).filter(a=>a.enabled).length;
  document.getElementById("statTodos").textContent=todos;
  document.getElementById("statShopping").textContent=shop;
  document.getElementById("statAlarms").textContent=alms;
  const msgs=(data.history||[]).filter(m=>m.kind==="chat").slice(-4);
  const rcEl=document.getElementById("recentChat");
  if(!msgs.length) rcEl.innerHTML='<div class="empty" style="padding:14px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>Nenhuma mensagem ainda</div>';
  else rcEl.innerHTML=msgs.map(m=>`<div class="mini-msg"><div class="mini-msg-role">${m.role==="assistant"?"Cassandra":"Você"} · ${fmtTime(m.timestamp)}</div><div class="mini-msg-text">${esc(m.content)}</div></div>`).join("");
  const active=(data.alarms||[]).filter(a=>a.enabled).sort((a,b)=>a.next_trigger_at.localeCompare(b.next_trigger_at)).slice(0,4);
  const uaEl=document.getElementById("upcomingAlarms");
  if(!active.length) uaEl.innerHTML='<div class="empty" style="padding:14px 0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>Nenhum alarme ativo</div>';
  else uaEl.innerHTML=active.map(a=>{
    const dayHtml=`<span class="day-tag">${esc(_alarmRepeatLabel(a))}</span>`;
    return `<div class="alarm-row-mini"><span class="alarm-time-lg">${esc(a.time_hhmm)}</span><div style="flex:1;min-width:0"><div style="font-size:12px;color:var(--text2);font-weight:500">${esc(a.label||"Alarme")}</div><div style="margin-top:4px">${dayHtml}</div></div></div>`;
  }).join("");
}

// ── Messages ──
let _lastHistory=[];
let _chatWaiting=false;
function _assistantCount(items){
  return (items||[]).filter(m=>(m.kind||"chat")==="chat"&&m.role==="assistant").length;
}
function showTyping(){
  const el=document.getElementById("messages");
  if(!el||document.getElementById("typingIndicator")) return;
  const d=document.createElement("div");d.className="typing";d.id="typingIndicator";d.innerHTML=AgentPersona.face("personal-assistant",{size:30,state:"is-working"})+'<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';el.appendChild(d);el.scrollTop=el.scrollHeight;
  setCassWorking(true);
}
function hideTyping(){document.getElementById("typingIndicator")?.remove();setCassWorking(false);}
// Enquanto ela pensa, o rosto da marca também trabalha (a estrelinha pisca rápido, olhos procuram).
function setCassWorking(on){
  document.querySelectorAll(".brand-face").forEach(f=>f.setAttribute("data-state",on?"is-working":""));
  if(window.AgentPersona) AgentPersona.mount();
}
function renderMessages(items){
  _lastHistory=items||[];
  const el=document.getElementById("messages");
  if(!items.length){el.innerHTML=`<div class="empty cass-empty"><div class="ce-face">${AgentPersona.face("personal-assistant",{size:84})}</div><b>Oi! Eu sou a Cassandra.</b><span>Pergunte ou peça qualquer coisa — pela voz ou por aqui.</span></div>`;if(_chatWaiting) showTyping();return;}
  el.innerHTML=items.map(m=>{const kind=m.kind||"chat";const cls=kind!=="chat"?"system":(m.role==="assistant"?"assistant":"user");const body=`<div class="bubble">${esc(m.content)}</div><div class="msg-meta">${fmtTime(m.timestamp)} · ${m.role==="assistant"?"Cassandra":m.role}</div>`;return cls==="assistant"?`<div class="msg assistant">${AgentPersona.face("personal-assistant",{size:30})}<div class="msg-col">${body}</div></div>`:`<div class="msg ${cls}">${body}</div>`;}).join("");
  if(_chatWaiting) showTyping();
  el.scrollTop=el.scrollHeight;
}
async function waitForChatReply(beforeAssistants,timeoutMs=180000){
  const started=Date.now();
  while(Date.now()-started<timeoutMs){
    if(_assistantCount(_lastHistory)>beforeAssistants) return {history:_lastHistory};
    await new Promise(r=>setTimeout(r,1500));
    try{
      const d=await api("/api/history");
      if(_assistantCount(d.history)>beforeAssistants) return d;
    }catch(e){
      if(!isGatewayTimeout(e)) throw e;
    }
  }
  return null;
}

// ── Shopping ──
function renderShopping(items){
  const el=document.getElementById("shopList");
  document.getElementById("shopCount").textContent=items.length+(items.length===1?" item":" itens");
  if(!items.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6H6"/></svg>Lista vazia</div>';return;}
  el.innerHTML=items.map(i=>`<div class="item"><div class="item-body"><div class="item-name">${esc(i.name)}</div><div class="item-sub">${esc(i.created_at||"")}</div></div><div class="item-actions"><button class="btn btn-danger btn-sm btn-icon" data-shop-rm="${i.id}">${IC.trash}</button></div></div>`).join("");
  el.querySelectorAll("[data-shop-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/shopping/remove","POST",{id:b.dataset.shopRm});await refresh();}));
}

// ── Todos ──
function renderTodos(items){
  const el=document.getElementById("todoList");
  const p=items.filter(i=>!i.completed).length;
  document.getElementById("todoCount").textContent=p+" pendente"+(p!==1?"s":"");
  if(!items.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>Nenhuma tarefa</div>';return;}
  el.innerHTML=items.map(i=>`<div class="item${i.completed?" done":""}"><div class="item-body"><div class="item-name">${esc(i.title)}</div><div class="item-sub">${i.completed?"Concluída":"Pendente"}</div></div><div class="item-actions"><button class="btn btn-ghost btn-sm btn-icon" data-todo-tog="${i.id}" data-done="${i.completed}">${i.completed?IC.undo:IC.check}</button><button class="btn btn-danger btn-sm btn-icon" data-todo-rm="${i.id}">${IC.x}</button></div></div>`).join("");
  el.querySelectorAll("[data-todo-tog]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/todos/toggle","POST",{id:b.dataset.todoTog,completed:b.dataset.done!=="true"});await refresh();}));
  el.querySelectorAll("[data-todo-rm]").forEach(b=>b.addEventListener("click",async()=>{await api("/api/todos/remove","POST",{id:b.dataset.todoRm});await refresh();}));
}

// ── Alarms ──
function _apiWeekday(d){return (d.getDay()+6)%7;}
function _fmtLongDate(iso){
  const d=new Date(iso+"T00:00:00");
  if(Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("pt-BR",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
}
function _alarmTypeOf(a){
  if(a.date_ymd) return "once";
  if(a.day_of_month) return "monthly";
  if(a.days_of_week&&a.days_of_week.length) return "weekly";
  if(a.recurring_daily) return "daily";
  return "once";
}
function _alarmRepeatLabel(a){
  const type=_alarmTypeOf(a);
  if(type==="daily") return "Todo dia";
  if(type==="weekly") return (a.days_of_week||[]).map(d=>DAY_NAMES[d]).join(", ")||"Na semana";
  if(type==="monthly") return `Todo dia ${a.day_of_month}`;
  if(a.date_ymd){
    const d=new Date(a.date_ymd+"T00:00:00");
    return d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short",year:"numeric"});
  }
  if(a.next_trigger_at) return _fmtLongDate(String(a.next_trigger_at).slice(0,10));
  return "Uma vez";
}
function _alarmOccursOn(a,date){
  const iso=_isoDate(date);
  if(a.date_ymd) return a.date_ymd===iso;
  if(a.day_of_month){
    const last=new Date(date.getFullYear(),date.getMonth()+1,0).getDate();
    return date.getDate()===Math.min(a.day_of_month,last);
  }
  if(a.days_of_week&&a.days_of_week.length) return a.days_of_week.includes(_apiWeekday(date));
  if(a.recurring_daily) return true;
  if(a.next_trigger_at) return String(a.next_trigger_at).slice(0,10)===iso;
  return false;
}
function _draftAlarm(){
  const spec=_peekAlarmSpec();
  if(!spec) return null;
  return {id:"__draft__",label:(document.getElementById("alarmLabel")?.value||"").trim()||"Novo alarme",time_hhmm:_almTime,recurring_daily:spec.type==="daily",days_of_week:spec.weekdays,date_ymd:spec.date,day_of_month:spec.day_of_month,enabled:true,_draft:true};
}
function _peekAlarmSpec(){
  if(_almType==="once") return _almDate?{type:"once",date:_almDate,time:_almTime}:null;
  if(_almType==="daily") return {type:"daily",time:_almTime};
  if(_almType==="weekly") return selDays&&selDays.length?{type:"weekly",weekdays:selDays.slice(),time:_almTime}:null;
  if(_almType==="monthly") return {type:"monthly",day_of_month:_almDom,time:_almTime};
  return null;
}
function _nextFromAlarmSpec(spec){
  if(!spec) return null;
  const [hh,mm]=(spec.time||"09:00").split(":").map(Number);
  const atTime=d=>{const x=new Date(d);x.setHours(hh,mm,0,0);return x;};
  const after=new Date();
  if(spec.type==="once") return spec.date?atTime(new Date(spec.date+"T00:00:00")):null;
  if(spec.type==="daily"){let d=atTime(after);if(d<=after) d.setDate(d.getDate()+1);return d;}
  if(spec.type==="weekly"){
    const days=spec.weekdays||[];
    for(let i=0;i<8;i++){
      const d=atTime(new Date(after.getFullYear(),after.getMonth(),after.getDate()+i));
      if(days.includes(_apiWeekday(d))&&d>after) return d;
    }
    return null;
  }
  if(spec.type==="monthly"){
    const dom=spec.day_of_month||1;
    for(let add=0;add<13;add++){
      const total=after.getMonth()+add;
      const year=after.getFullYear()+Math.floor(total/12);
      const month=((total%12)+12)%12;
      const last=new Date(year,month+1,0).getDate();
      const d=atTime(new Date(year,month,Math.min(dom,last)));
      if(d>after) return d;
    }
  }
  return null;
}
function updateAlarmPreview(){
  const el=document.getElementById("alm-preview");
  const dateLabel=document.getElementById("alarm-date-label");
  const domLabel=document.getElementById("alarm-dom-label");
  if(dateLabel) dateLabel.textContent=_almDate?_fmtLongDate(_almDate):"Clique no calendário";
  if(domLabel) domLabel.textContent=_almDom?`Dia ${_almDom} de cada mês`:"Clique no calendário";
  if(!el) return;
  const spec=_peekAlarmSpec();
  if(!spec){
    el.className="alm-preview hint";
    el.textContent=_almType==="weekly"?"Selecione ao menos um dia da semana.":_almType==="once"?"Clique num dia no calendário para marcar a data.":"Escolha quando o alarme deve tocar.";
    return;
  }
  const next=_nextFromAlarmSpec(spec);
  const pastOnce=spec.type==="once"&&next&&next<=new Date();
  const desc=_alarmRepeatLabel({date_ymd:spec.date,day_of_month:spec.day_of_month,days_of_week:spec.weekdays,recurring_daily:spec.type==="daily",time_hhmm:spec.time});
  if(pastOnce){
    el.className="alm-preview warn";
    el.innerHTML=`${esc(spec.time)} · ${esc(desc)}<br>Esse horário já passou. Escolha um dia ou hora no futuro.`;
    return;
  }
  el.className="alm-preview";
  const when=next?next.toLocaleString("pt-BR",{weekday:"short",day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}):"não calculado";
  el.innerHTML=`${esc(spec.time)} · ${esc(desc)}<br>Próximo toque: ${esc(when)}`;
}
function onAlarmFormChange(){updateAlarmPreview();renderAlmCalendar();}
function setAlarmType(type){
  _almType=type;
  document.getElementById("alarm-type-input").value=type;
  document.querySelectorAll(".alm-type-pill").forEach(b=>b.classList.toggle("active",b.dataset.type===type));
  document.getElementById("alarm-date-field").hidden=type!=="once";
  document.getElementById("alarm-weekdays-field").hidden=type!=="weekly";
  document.getElementById("alarm-dom-field").hidden=type!=="monthly";
  const hint=document.getElementById("alm-when-hint");
  if(hint) hint.textContent=type==="once"?"Clique num dia no calendário para escolher a data — inclusive de outro mês ou ano."
    :type==="weekly"?"Clique no calendário ou nos dias da semana. Presets: dias úteis / fim de semana."
    :type==="monthly"?"Clique num dia do calendário para escolher o dia do mês."
    :"Toca todos os dias neste horário.";
  if(type==="once"&&_almCalSelected) _almDate=_almCalSelected;
  if(type==="monthly"&&_almCalSelected) _almDom=Number(_almCalSelected.slice(8,10));
  if(type==="weekly"&&(!selDays||!selDays.length)&&_almCalSelected){
    const d=new Date(_almCalSelected+"T00:00:00");
    setPreset([_apiWeekday(d)]);
    return;
  }
  onAlarmFormChange();
}
function setAlarmTime(time,opts={}){
  _almTime=time;
  const input=document.getElementById("alarmTime");
  if(input) input.value=time;
  document.querySelectorAll(".alm-time-pill").forEach(b=>b.classList.toggle("active",b.dataset.time===time));
  if(!opts.silent) onAlarmFormChange();
}
function onAlarmTimeInput(){
  const time=document.getElementById("alarmTime")?.value||"09:00";
  setAlarmTime(time);
}
function startNewAlarm(){
  document.getElementById("alarmLabel").value="";
  selDays=[];
  _almDate=_almCalSelected||_isoDate(new Date());
  _almDom=Number((_almDate||"01").slice(8,10))||1;
  setAlarmTime("09:00",{silent:true});
  setAlarmType("once");
  document.getElementById("alarmForm")?.scrollIntoView({behavior:"smooth",block:"nearest"});
}
function shiftAlmCal(delta){
  _almCalMonth+=delta;
  while(_almCalMonth<0){_almCalMonth+=12;_almCalYear-=1;}
  while(_almCalMonth>11){_almCalMonth-=12;_almCalYear+=1;}
  renderAlmCalendar();
}
function shiftAlmCalYear(delta){
  _almCalYear+=delta;
  renderAlmCalendar();
}
function goAlmCalToday(){
  const n=new Date();
  _almCalYear=n.getFullYear();
  _almCalMonth=n.getMonth();
  _almCalSelected=_isoDate(n);
  _almPickerOpen=false;
  if(_almType==="once") _almDate=_almCalSelected;
  if(_almType==="monthly") _almDom=n.getDate();
  renderAlmCalendar();
}
function toggleAlmCalPicker(){
  _almPickerOpen=!_almPickerOpen;
  renderAlmCalendar();
}
function pickAlmCalMonth(month){
  _almCalMonth=month;
  _almPickerOpen=false;
  renderAlmCalendar();
}
function focusAlmCalendar(){
  const el=document.getElementById("alm-cal");
  if(!el) return;
  el.scrollIntoView({behavior:"smooth",block:"nearest"});
  el.classList.add("pulse");
  setTimeout(()=>el.classList.remove("pulse"),700);
}
function onAlmCalDayClick(iso){
  _almCalSelected=iso;
  const d=new Date(iso+"T00:00:00");
  _almCalYear=d.getFullYear();
  _almCalMonth=d.getMonth();
  _almPickerOpen=false;
  if(_almType==="once") _almDate=iso;
  else if(_almType==="monthly") _almDom=d.getDate();
  else if(_almType==="weekly"){
    const wd=_apiWeekday(d);
    if(!Array.isArray(selDays)) selDays=[];
    if(!selDays.includes(wd)) selDays=[...selDays,wd].sort((a,b)=>a-b);
    document.querySelectorAll(".day-btn").forEach(b=>b.classList.toggle("on",selDays.includes(+b.dataset.day)));
  }
  onAlarmFormChange();
  const form=document.getElementById("alarmForm");
  if(form){
    form.scrollIntoView({behavior:"smooth",block:"nearest"});
    form.classList.add("pulse");
    setTimeout(()=>form.classList.remove("pulse"),700);
  }
}
function renderAlmCalendar(){
  const grid=document.getElementById("alm-cal-grid");
  const title=document.getElementById("alm-cal-title");
  const picker=document.getElementById("alm-cal-picker");
  const pickerYear=document.getElementById("alm-cal-picker-year");
  const pickerMonths=document.getElementById("alm-cal-picker-months");
  if(!grid) return;
  if(title) title.textContent=`${MONTHS_PT[_almCalMonth]} ${_almCalYear}`;
  if(picker) picker.hidden=!_almPickerOpen;
  if(pickerYear) pickerYear.textContent=String(_almCalYear);
  if(pickerMonths){
    pickerMonths.innerHTML=MONTHS_SHORT.map((name,idx)=>`<button type="button" class="alm-cal-month-btn${idx===_almCalMonth?" on":""}" onclick="pickAlmCalMonth(${idx})">${name}</button>`).join("");
  }
  const startOffset=_apiWeekday(new Date(_almCalYear,_almCalMonth,1));
  const todayIso=_isoDate(new Date());
  const draft=_draftAlarm();
  const items=_alarmsCache.slice();
  if(draft) items.push(draft);
  const hitsByIso={};
  const cursor=new Date(_almCalYear,_almCalMonth,1-startOffset);
  const cells=[];
  for(let i=0;i<42;i++){
    const date=new Date(cursor);
    date.setDate(cursor.getDate()+i);
    const iso=_isoDate(date);
    const inMonth=date.getMonth()===_almCalMonth;
    const hits=items.filter(a=>_alarmOccursOn(a,date));
    if(hits.length) hitsByIso[iso]=hits;
    const sorted=hits.slice().sort((a,b)=>(b._draft?1:0)-(a._draft?1:0));
    const dots=sorted.slice(0,3).map(a=>{
      const kind=a._draft?"draft":(a.enabled?"saved":"off");
      return `<i class="alm-dot ${kind}"></i>`;
    }).join("");
    const extra=hits.length>3?`<span class="alm-cal-more">+${hits.length-3}</span>`:"";
    const tip=hits.map(a=>`${a.time_hhmm||""} ${a.label||"Alarme"}`).join(" · ");
    const cls=["alm-cal-cell",inMonth?"":"out",iso===todayIso?"today":"",iso===_almCalSelected?"selected":"",iso<todayIso&&inMonth?"past":"",hits.length?"has-alarms":"",hits.some(a=>a._draft)?"has-draft":""].filter(Boolean).join(" ");
    cells.push(`<button type="button" class="${cls}" title="${esc(tip)}" onclick="onAlmCalDayClick('${iso}')"><span>${date.getDate()}</span><span class="alm-cal-dots">${dots}${extra}</span></button>`);
  }
  grid.innerHTML=cells.join("");
  _renderAlmAgenda(_almCalSelected||todayIso,hitsByIso[_almCalSelected||todayIso]||[]);
  updateAlarmPreview();
}
function _renderAlmAgenda(iso,hits){
  const el=document.getElementById("alm-cal-agenda");
  if(!el) return;
  if(!hits.length){
    el.innerHTML=`<div class="alm-agenda-day">${esc(_fmtLongDate(iso))}</div><div class="item-sub">Nenhum alarme neste dia. Clique para marcar um.</div>`;
    return;
  }
  const rows=hits.slice().sort((a,b)=>String(a.time_hhmm).localeCompare(String(b.time_hhmm))).map(a=>{
    const cls=a._draft?"alm-agenda-item draft":"alm-agenda-item";
    return `<button type="button" class="${cls}" ${a._draft?"":`onclick="jumpToAlarm('${a.id}')"`}>
      <span class="alm-agenda-time">${esc(a.time_hhmm||"--:--")}</span>
      <span class="alm-agenda-task">${esc(a.label||"Alarme")}${a._draft?" · rascunho":""} · ${esc(_alarmRepeatLabel(a))}</span>
    </button>`;
  }).join("");
  el.innerHTML=`<div class="alm-agenda-day">${esc(_fmtLongDate(iso))} · ${hits.length} alarme${hits.length===1?"":"s"}</div>${rows}`;
}
function jumpToAlarm(id){
  const a=_alarmsCache.find(x=>x.id===id);
  if(!a) return;
  const iso=a.date_ymd||String(a.next_trigger_at||"").slice(0,10)||_isoDate(new Date());
  const d=new Date(iso+"T00:00:00");
  if(!Number.isNaN(d.getTime())){
    _almCalYear=d.getFullYear();
    _almCalMonth=d.getMonth();
    _almCalSelected=iso;
  }
  renderAlmCalendar();
  document.getElementById("alm-cal")?.scrollIntoView({behavior:"smooth",block:"nearest"});
}
function renderAlarms(items){
  _alarmsCache=items||[];
  const el=document.getElementById("alarmList");
  document.getElementById("alarmCount").textContent=_alarmsCache.length+(_alarmsCache.length===1?" alarme":" alarmes");
  renderAlmCalendar();
  if(!_alarmsCache.length){el.innerHTML='<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>Nenhum alarme ainda. Clique num dia do calendário para criar.</div>';return;}
  const sorted=_alarmsCache.slice().sort((a,b)=>String(a.next_trigger_at||"").localeCompare(String(b.next_trigger_at||"")));
  el.innerHTML=sorted.map(a=>`<div class="item" onclick="jumpToAlarm('${a.id}')" style="cursor:pointer"><span class="alarm-dot-led ${a.enabled?"on":"off"}"></span><div class="item-body"><div class="item-name"><span class="alarm-list-time">${esc(a.time_hhmm)}</span><span style="font-size:13px;font-weight:400;color:var(--text2);margin-left:8px">${esc(a.label||"")}</span></div><div style="margin-top:6px"><span class="day-tag">${esc(_alarmRepeatLabel(a))}</span></div></div><div class="item-actions"><button class="btn btn-danger btn-sm btn-icon" data-alarm-rm="${a.id}">${IC.trash}</button></div></div>`).join("");
  el.querySelectorAll("[data-alarm-rm]").forEach(b=>b.addEventListener("click",async ev=>{ev.stopPropagation();await api("/api/alarms/remove","POST",{id:b.dataset.alarmRm});await refresh();}));
}

// ── Timers ativos (header) ──
let tmList=[], tmOffset=0, tmTick=null;
const TM_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="13" r="8"/><polyline points="12 9 12 13 14.5 15"/><line x1="10" y1="2" x2="14" y2="2"/></svg>';
function tmFmt(sec){
  sec=Math.max(0,Math.ceil(sec));
  const h=Math.floor(sec/3600), m=Math.floor(sec%3600/60), s=sec%60, p=n=>String(n).padStart(2,"0");
  return h?`${h}:${p(m)}:${p(s)}`:`${m}:${p(s)}`;
}
function renderTimers(list,serverNow){
  tmList=list||[];
  if(serverNow) tmOffset=serverNow-Date.now()/1000;
  drawTimers();
  clearInterval(tmTick); tmTick=tmList.length?setInterval(drawTimers,1000):null;
}
function drawTimers(){
  const el=document.getElementById("timerPills"); if(!el) return;
  const now=Date.now()/1000+tmOffset;
  el.innerHTML=tmList.map(t=>{
    const left=t.ends_at-now, fired=t.fired||left<=0;
    const txt=fired?"Tempo!":tmFmt(left);
    return `<span class="timer-pill${fired?" fired":""}" title="Timer de ${esc(t.label)}">${TM_ICON}<span>${txt}</span><span class="tp-label">· ${esc(t.label)}</span>${fired?"":`<button class="tp-x" data-tm-cancel="${esc(t.name)}" title="Cancelar timer">×</button>`}</span>`;
  }).join("");
  document.getElementById("clock").classList.toggle("has-timers",tmList.length>0);
  el.querySelectorAll("[data-tm-cancel]").forEach(b=>b.addEventListener("click",async()=>{
    try{const d=await api("/api/timers/cancel","POST",{name:b.dataset.tmCancel});renderTimers(d.timers,d.now);}catch(e){console.error(e);}
  }));
}
async function loadTimers(){try{const d=await api("/api/timers");renderTimers(d.timers,d.now);}catch(e){}}

// ── Alarme tocando: aviso fixo até parar (timers não entram aqui) ──
function renderAlarmToast(list){
  const t=document.getElementById("alarmToast"); if(!t) return;
  list=list||[];
  if(!list.length){t.classList.remove("show");return;}
  document.getElementById("alarmToastSub").textContent=list.map(a=>`${a.time_hhmm}${a.label&&a.label!=="Alarme"?" · "+a.label:""}`).join("  ·  ");
  t.classList.add("show");
}
async function loadAlarmRinging(){
  try{const d=await api("/api/alarms/ringing");renderAlarmToast(d.ringing);renderAlarmStatus(d.ringing.length>0);}catch(e){}
}
document.getElementById("alarmToastStop").addEventListener("click",async e=>{
  const b=e.currentTarget; b.disabled=true;
  try{await api("/api/alarms/stop","POST",{});renderAlarmToast([]);renderAlarmStatus(false);}
  catch(err){console.error(err);}
  finally{b.disabled=false;}
});

// ── Alarm status ──
document.getElementById("alarmPill").addEventListener("click",async e=>{
  const b=e.currentTarget; if(!b.classList.contains("ringing")) return;
  b.disabled=true;
  try{await api("/api/alarms/stop","POST",{});renderAlarmStatus(false);renderAlarmToast([]);}
  catch(err){console.error(err);}
  finally{b.disabled=false;}
});
function renderAlarmStatus(ringing){
  [document.getElementById("alarmDot"),document.getElementById("alarmPillDot")].forEach(d=>{d.className="sdot"+(ringing?" warn":"");});
  document.getElementById("alarmStatusText").textContent=ringing?"Alarme tocando!":"Sistema ok";
  document.getElementById("alarmPillText").textContent=ringing?"Parar alarme":"Ok";
  const pill=document.getElementById("alarmPill");
  pill.className="alarm-pill"+(ringing?" ringing":"");
  pill.title=ringing?"Parar o alarme que está tocando":"Status do alarme";
}

// ── Day picker ──
function setPreset(days){
  selDays=Array.isArray(days)?days.slice():[];
  document.querySelectorAll(".day-btn").forEach(b=>b.classList.toggle("on",selDays.includes(+b.dataset.day)));
  if(_almType!=="weekly") setAlarmType("weekly");
  else onAlarmFormChange();
}
document.querySelectorAll(".day-btn").forEach(b=>b.addEventListener("click",()=>{
  if(!Array.isArray(selDays)) selDays=[];
  const d=+b.dataset.day;
  selDays=selDays.includes(d)?selDays.filter(x=>x!==d):[...selDays,d].sort((a,b)=>a-b);
  b.classList.toggle("on",selDays.includes(d));
  if(_almType!=="weekly") setAlarmType("weekly");
  else onAlarmFormChange();
}));

// ── Settings ──
function applySettingsToForm(s){
  currentSettings=s;
  const m=s.modules||{};
  document.getElementById("mod-chat").checked=m.chat!==false;
  document.getElementById("mod-music").checked=m.music!==false;
  document.getElementById("mod-devices").checked=m.devices!==false;
  document.getElementById("mod-shopping").checked=m.shopping!==false;
  document.getElementById("mod-todos").checked=m.todos!==false;
  document.getElementById("mod-alarms").checked=m.alarms!==false;
  document.getElementById("mod-routines").checked=m.routines!==false;
  document.getElementById("mod-agenda").checked=m.agenda!==false;
  const v=s.voice||{};
  document.getElementById("voice-enabled").checked=v.enabled!==false;
  document.getElementById("voice-engine").value=v.engine||"auto";
  document.getElementById("voice-tts-model").value=v.tts_model||"gpt-4o-mini-tts";
  document.getElementById("voice-tts-voice").value=v.tts_voice||"nova";
  document.getElementById("voice-fallback-lang").value=v.fallback_lang||"pt";
  const rate=v.fallback_rate||160;
  document.getElementById("voice-rate").value=rate;
  document.getElementById("voice-rate-val").textContent=rate;
  const snd=s.sounds||{};
  document.getElementById("sounds-enabled").checked=snd.enabled!==false;
  const sess=s.session||{};
  document.getElementById("session-timeout").value=sess.wake_timeout||30;
  const rt=s._runtime||{};
  document.getElementById("info-name").textContent=rt.assistant_name||"cassandra";
  document.getElementById("info-input").textContent=rt.input_mode||"text";
  document.getElementById("info-model").textContent=rt.llm||rt.openai_model||"—";
  rebuildNavs();
}

function collectSettingsFromForm(){
  return {
    modules:{
      chat:document.getElementById("mod-chat").checked,
      music:document.getElementById("mod-music").checked,
      devices:document.getElementById("mod-devices").checked,
      shopping:document.getElementById("mod-shopping").checked,
      todos:document.getElementById("mod-todos").checked,
      alarms:document.getElementById("mod-alarms").checked,
      routines:document.getElementById("mod-routines").checked,
      agenda:document.getElementById("mod-agenda").checked,
    },
    voice:{
      enabled:document.getElementById("voice-enabled").checked,
      engine:document.getElementById("voice-engine").value,
      tts_model:document.getElementById("voice-tts-model").value,
      tts_voice:document.getElementById("voice-tts-voice").value,
      fallback_lang:document.getElementById("voice-fallback-lang").value,
      fallback_rate:parseInt(document.getElementById("voice-rate").value),
    },
    sounds:{enabled:document.getElementById("sounds-enabled").checked},
    session:{wake_timeout:parseInt(document.getElementById("session-timeout").value)||30},
  };
}

document.getElementById("voice-rate").addEventListener("input",e=>{
  document.getElementById("voice-rate-val").textContent=e.target.value;
});

document.getElementById("saveSettingsBtn").addEventListener("click",async()=>{
  const patch=collectSettingsFromForm();
  const s=await api("/api/settings","POST",patch);
  applySettingsToForm(s);
  const toast=document.getElementById("saveToast");
  toast.classList.add("show");setTimeout(()=>toast.classList.remove("show"),2000);
});

document.getElementById("resetSettingsBtn").addEventListener("click",async()=>{
  if(!confirm("Restaurar todas as configurações para o padrão?")) return;
  const s=await api("/api/settings/reset","POST",{});
  applySettingsToForm(s);
  const toast=document.getElementById("saveToast");
  toast.textContent="Restaurado!";toast.classList.add("show");
  setTimeout(()=>{toast.classList.remove("show");toast.textContent="Salvo!";},2000);
});

// ── Modelo de IA (LLM) ──
function applyLlm(l){
  document.getElementById("llm-provider").value=l.llm_provider||"openai";
  document.getElementById("llm-openai-model").value=l.openai_model||"";
  document.getElementById("llm-deepseek-model").value=l.deepseek_model||"";
  document.getElementById("llm-local-url").value=l.local_llm_base_url||"";
  document.getElementById("llm-local-active").textContent=l.llm_provider==="local"?"· em uso":"";
  loadLocalModels(l.local_llm_model);
  for(const p of ["openai","deepseek"]){
    const key=document.getElementById(`llm-${p}-key`);
    key.value="";
    key.placeholder=l[`${p}_api_key_set`]?`Salva · ${l[`${p}_api_key_preview`]}`:"Cole a chave (sk-...)";
    document.getElementById(`llm-${p}-active`).textContent=l.llm_provider===p?"· em uso":"";
  }
  const ak=document.getElementById("llm-azure-key");
  ak.value="";
  ak.placeholder=l.azure_speech_key_set?`Salva · ${l.azure_speech_key_preview}`:"Cole a chave do Azure";
  document.getElementById("llm-azure-region").value=l.azure_speech_region||"brazilsouth";
  document.getElementById("llm-azure-active").textContent=l.azure_speech_key_set?"· voz em uso":"";
  loadAzureVoices(l.azure_tts_voice);
  document.getElementById("stt-provider").value=l.stt_provider||"auto";
  document.getElementById("stt-model").value=l.stt_model||"gpt-4o-mini-transcribe";
  const note=document.getElementById("llm-audio-note");
  if(l.audio_available){
    note.className="llm-note";
    note.style.display="none";
    note.textContent=l.azure_speech_key_set?"DeepSeek e o modelo local só fazem texto. A voz e a transcrição usam o que estiver escolhido nas seções abaixo.":"";
  }else{
    note.className="llm-note warn";
    note.style.display="";
    note.textContent=l.azure_speech_key_set?"Sem chave da OpenAI: a transcrição só funciona pelo Azure ou pela local.":"Sem chave da OpenAI nem do Azure: voz robótica (espeak) e transcrição só local.";
  }
  const name=l.llm_provider==="deepseek"?`DeepSeek · ${l.deepseek_model}`:l.llm_provider==="local"?`Local · ${l.local_llm_model||"sem modelo"}`:`OpenAI · ${l.openai_model}`;
  document.getElementById("info-model").textContent=name;
}

async function loadLocalModels(current){
  const sel=document.getElementById("llm-local-model");
  const desc=document.getElementById("llm-local-desc");
  const keep=current!==undefined?current:sel.value;
  let d={models:[]};
  try{d=await api("/api/llm/local-models");}catch(e){d={models:[],error:e.message};}
  const models=d.models||[];
  if(keep&&!models.includes(keep)) models.unshift(keep);
  sel.innerHTML=(models.length?"":`<option value="">nenhum modelo</option>`)+models.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join("");
  if(keep) sel.value=keep;
  desc.classList.toggle("warn",!!d.error);
  desc.textContent=d.error?"Llama Desk fora do ar (PC desligado?)":"Modelos do Llama Desk no PC";
}
document.getElementById("llmLocalRefresh").addEventListener("click",async()=>{
  const url=document.getElementById("llm-local-url").value.trim();
  if(url){try{await api("/api/llm","POST",{local_llm_base_url:url});}catch(e){}}
  loadLocalModels();
});

async function loadAzureVoices(current){
  const sel=document.getElementById("llm-azure-voice");
  const keep=current||sel.value||"pt-BR-FranciscaNeural";
  let voices=[];
  try{voices=(await api("/api/azure/voices")).voices||[];}catch(e){}
  if(!voices.length) voices=[{name:keep,label:keep.replace("pt-BR-","").replace("Neural",""),gender:""}];
  if(!voices.some(v=>v.name===keep)) voices.unshift({name:keep,label:keep,gender:""});
  sel.innerHTML=voices.map(v=>`<option value="${esc(v.name)}">${esc(v.label)}${v.gender?" ("+esc(v.gender)+")":""}</option>`).join("");
  sel.value=keep;
}
function voiceFields(){
  return {voice:{engine:document.getElementById("voice-engine").value,
                 tts_model:document.getElementById("voice-tts-model").value,
                 tts_voice:document.getElementById("voice-tts-voice").value}};
}
function azureFields(){
  const b={azure_speech_region:document.getElementById("llm-azure-region").value.trim(),
           azure_tts_voice:document.getElementById("llm-azure-voice").value};
  const k=document.getElementById("llm-azure-key").value.trim();
  if(k) b.azure_speech_key=k;
  return b;
}
document.getElementById("llmAzureTest").addEventListener("click",async e=>{
  const b=e.currentTarget; b.disabled=true; b.textContent="Falando…";
  try{
    applyLlm(await api("/api/llm","POST",azureFields()));
    applySettingsToForm(await api("/api/settings","POST",voiceFields()));
    await api("/api/speak","POST",{text:"Oi! Esta é a minha voz. O que você achou?"});
  }catch(err){alert(err.message);}
  finally{setTimeout(()=>{b.disabled=false;b.textContent="Testar voz";},2500);}
});

async function loadLlm(){
  try{applyLlm(await api("/api/llm"));}catch(e){console.error("LLM:",e);}
}

document.getElementById("saveLlmBtn").addEventListener("click",async()=>{
  const body={
    llm_provider:document.getElementById("llm-provider").value,
    openai_model:document.getElementById("llm-openai-model").value.trim(),
    deepseek_model:document.getElementById("llm-deepseek-model").value.trim(),
  };
  Object.assign(body,azureFields());
  body.local_llm_base_url=document.getElementById("llm-local-url").value.trim();
  body.local_llm_model=document.getElementById("llm-local-model").value;
  body.stt_provider=document.getElementById("stt-provider").value;
  body.stt_model=document.getElementById("stt-model").value;
  const ok=document.getElementById("llm-openai-key").value.trim();
  const dk=document.getElementById("llm-deepseek-key").value.trim();
  if(ok) body.openai_api_key=ok;
  if(dk) body.deepseek_api_key=dk;
  const toast=document.getElementById("llmToast");
  try{
    const l=await api("/api/llm","POST",body);
    applyLlm(l);
    applySettingsToForm(await api("/api/settings","POST",voiceFields()));
    if(l.llm_provider==="local"){toast.textContent=l.local_llm_model?"Salvo!":"Salvo — escolha o modelo local";}
    else if(!l[`${l.llm_provider}_api_key_set`]){toast.textContent="Salvo — falta a chave desse provedor";}
    else toast.textContent="Salvo!";
  }catch(e){toast.textContent=`Erro: ${e.message}`;}
  toast.classList.add("show");setTimeout(()=>{toast.classList.remove("show");toast.textContent="Salvo!";},3000);
});

// ── Routines ──
const ACTION_LABELS={noticias:"Notícias",cotacao:"Cotações",clima:"Clima",esporte:"Esportes",transito:"Trânsito",falar:"Falar"};

function rTrigChange(){
  const v=document.querySelector('input[name="rTrigType"]:checked').value;
  document.getElementById("rTrigAlarmSel").style.display=v==="alarm"?"block":"none";
  document.getElementById("rTrigTimeSel").style.display=v==="time"?"block":"none";
}

function renderRoutines(routines,alarms){
  const list=document.getElementById("routineList");
  document.getElementById("routineCount").textContent=routines.length+" rotina"+(routines.length!==1?"s":"");
  if(!routines.length){list.innerHTML='<div class="empty">Nenhuma rotina cadastrada.<br/>Crie a primeira acima.</div>';return;}
  list.innerHTML=routines.map(r=>{
    const trig=r.trigger;
    let trigStr="";
    if(trig.type==="alarm"){
      const al=(alarms||[]).find(a=>a.id===trig.alarm_id);
      trigStr=al?`Alarme: ${al.label} (${al.time_hhmm})`:`Alarme #${trig.alarm_id}`;
    } else {
      trigStr=`Diariamente às ${trig.time_hhmm}`;
    }
    const acts=r.actions.map(a=>ACTION_LABELS[a.type]||(a.type)).join(" → ");
    return `<div class="list-item" style="flex-direction:column;align-items:flex-start;gap:6px">
      <div style="display:flex;width:100%;align-items:center;gap:8px">
        <label class="toggle" style="flex-shrink:0"><input type="checkbox" ${r.enabled?"checked":""} onchange="toggleRoutine('${r.id}',this.checked)"/><span class="toggle-slider"></span></label>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;font-size:14px">${esc(r.name)}</div>
          <div style="font-size:12px;color:var(--text2);margin-top:2px">${esc(trigStr)}</div>
        </div>
        <button class="btn btn-ghost btn-sm" title="Executar agora" onclick="runRoutine('${r.id}')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polygon points="5 3 19 12 5 21 5 3"/></svg></button>
        <button class="btn btn-danger btn-sm" onclick="removeRoutine('${r.id}')">${IC.trash}</button>
      </div>
      <div style="font-size:12px;color:var(--text2);padding-left:52px">${esc(acts)}</div>
    </div>`;
  }).join("");
}

async function loadRoutines(){
  try{
    const [rData, aData]=await Promise.all([api("/api/routines"),api("/api/dashboard")]);
    renderRoutines(rData.routines||[],aData.alarms||[]);
    // Preenche select de alarmes no form
    const sel=document.getElementById("routineAlarmId");
    const cur=sel.value;
    sel.innerHTML='<option value="">-- selecione um alarme --</option>'+(aData.alarms||[]).map(a=>`<option value="${a.id}">${esc(a.label)} (${a.time_hhmm})</option>`).join("");
    if(cur)sel.value=cur;
  }catch(e){console.error("Routines:",e);}
}

async function toggleRoutine(id,enabled){
  await api("/api/routines/toggle","POST",{id,enabled});
  await loadRoutines();
}
async function removeRoutine(id){
  if(!confirm("Remover esta rotina?"))return;
  await api("/api/routines/remove","POST",{id});
  await loadRoutines();
}
async function runRoutine(id){
  await api("/api/routines/run","POST",{id});
  alert("Rotina iniciada em background.");
}

document.getElementById("routineAdd").addEventListener("click",async()=>{
  const name=document.getElementById("routineName").value.trim();
  if(!name){alert("Digite um nome para a rotina.");return;}
  const trigType=document.querySelector('input[name="rTrigType"]:checked').value;
  const trigger={type:trigType};
  if(trigType==="alarm"){
    const aid=document.getElementById("routineAlarmId").value;
    if(!aid){alert("Selecione um alarme.");return;}
    trigger.alarm_id=aid;
  } else {
    const t=document.getElementById("routineTimeHhmm").value;
    if(!t){alert("Escolha um horário.");return;}
    trigger.time_hhmm=t;
  }
  const actions=[];
  document.querySelectorAll(".rAct:checked").forEach(cb=>{
    const act={type:cb.value};
    if(cb.value==="falar") act.text=document.getElementById("routineFalarText").value.trim();
    actions.push(act);
  });
  if(!actions.length){alert("Selecione pelo menos uma ação.");return;}
  await api("/api/routines/add","POST",{name,trigger,actions});
  document.getElementById("routineName").value="";
  document.querySelectorAll(".rAct").forEach(cb=>{cb.checked=false;});
  document.getElementById("routineFalarText").style.display="none";
  document.getElementById("routineFalarText").value="";
  await loadRoutines();
});

// ── Agenda ──
function renderAgenda(events, configured){
  const list=document.getElementById("agendaList");
  const banner=document.getElementById("agendaConnBanner");
  const form=document.getElementById("agendaNewForm");
  if(!configured){
    banner.style.display="block";
    form.style.display="none";
    list.innerHTML="";
    return;
  }
  banner.style.display="none";
  form.style.display="";
  if(!events.length){list.innerHTML='<div class="empty">Nenhum compromisso no período.</div>';return;}
  list.innerHTML=events.map(ev=>`<div class="list-item" style="flex-direction:column;align-items:flex-start;gap:4px">
    <div style="display:flex;width:100%;align-items:center;gap:8px">
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:14px">${esc(ev.title)}</div>
        <div style="font-size:12px;color:var(--brand2);margin-top:2px">${esc(ev.start)}${ev.end?" → "+esc(ev.end):""}</div>
        ${ev.description?`<div style="font-size:12px;color:var(--text2);margin-top:2px">${esc(ev.description)}</div>`:""}
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteEvent('${esc(ev.id)}')">${IC.trash}</button>
    </div>
  </div>`).join("");
}

async function loadAgenda(){
  try{
    const days=parseInt(document.getElementById("agendaDays").value)||7;
    const data=await api("/api/agenda/events?days="+days);
    renderAgenda(data.events||[],data.configured);
  }catch(e){console.error("Agenda:",e);}
}

async function deleteEvent(eventId){
  if(!confirm("Remover este compromisso do calendário?"))return;
  try{
    await api("/api/agenda/events/delete","POST",{event_id:eventId});
    await loadAgenda();
  }catch(e){if(!isGatewayTimeout(e)) alert("Erro ao remover: "+e.message);}
}

document.getElementById("evAdd").addEventListener("click",async()=>{
  const title=document.getElementById("evTitle").value.trim();
  const date=document.getElementById("evDate").value;
  const start=document.getElementById("evStart").value;
  const end=document.getElementById("evEnd").value;
  const desc=document.getElementById("evDesc").value.trim();
  if(!title||!date||!start||!end){alert("Preencha título, data, início e fim.");return;}
  try{
    await api("/api/agenda/events/add","POST",{title,date,start,end,description:desc});
    document.getElementById("evTitle").value="";
    document.getElementById("evDesc").value="";
    await loadAgenda();
  }catch(e){if(!isGatewayTimeout(e)) alert("Erro ao criar: "+e.message);}
});

document.getElementById("agendaDays").addEventListener("change",loadAgenda);

// Calendar settings
async function loadCalendarStatus(){
  try{
    const d=await api("/api/calendar/status");
    const dot=document.getElementById("cal-dot");
    const lbl=document.getElementById("cal-badge-label");
    const userLbl=document.getElementById("cal-user-label");
    const disBtn=document.getElementById("calDisconnectBtn");
    const form=document.getElementById("calConnForm");
    if(d.configured){
      dot.style.background="var(--green)";dot.style.boxShadow="0 0 6px var(--green)";
      lbl.textContent="Conectada";
      userLbl.textContent=d.username+(d.url?" · "+d.url:"");
      disBtn.style.display="";
      form.style.display="none";
    } else {
      dot.style.background="#6b7280";dot.style.boxShadow="none";
      lbl.textContent="Não conectada";
      userLbl.textContent="—";
      disBtn.style.display="none";
      form.style.display="";
    }
  }catch(e){console.error("Cal status:",e);}
}

document.getElementById("calConnectBtn").addEventListener("click",async()=>{
  const url=document.getElementById("calUrl").value.trim();
  const username=document.getElementById("calUsername").value.trim();
  const password=document.getElementById("calPassword").value;
  const msg=document.getElementById("calTestMsg");
  if(!url||!username||!password){alert("Preencha URL, e-mail e senha.");return;}
  msg.textContent="Testando conexão…";msg.style.color="var(--text2)";
  try{
    const d=await api("/api/calendar/configure","POST",{url,username,password});
    if(d.ok){
      msg.textContent=d.message;msg.style.color="var(--green)";
      await loadCalendarStatus();
    } else {
      msg.textContent=d.message;msg.style.color="var(--red)";
    }
  }catch(e){msg.textContent="Erro: "+e.message;msg.style.color="var(--red)";}
});

document.getElementById("calDisconnectBtn").addEventListener("click",async()=>{
  if(!confirm("Desconectar a conta de agenda?"))return;
  await api("/api/calendar/disconnect","POST",{});
  await loadCalendarStatus();
});

let currentCalProviderTemplate = "";
function syncCalUrlFromTemplate(){
  if(!currentCalProviderTemplate)return;
  const emailEl=document.getElementById("calUsername");
  const urlEl=document.getElementById("calUrl");
  if(currentCalProviderTemplate.includes("{email}")){
    const email=emailEl.value.trim();
    urlEl.value=email?currentCalProviderTemplate.replace("{email}",email):currentCalProviderTemplate;
  }
}

document.querySelectorAll(".cal-provider-btn").forEach(btn=>{
  btn.addEventListener("click",()=>{
    const url=btn.dataset.url||"";
    const emailEl=document.getElementById("calUsername");
    const urlEl=document.getElementById("calUrl");
    currentCalProviderTemplate = url;
    if(url.includes("{email}")){
      const email=emailEl.value.trim();
      urlEl.value=email?url.replace("{email}",email):url;
    } else {
      urlEl.value=url;
    }
  });
});
document.getElementById("calUsername").addEventListener("input", syncCalUrlFromTemplate);

// ── Refresh ──
async function refresh(){
  try{
    const data=await api("/api/dashboard");
    renderDashboard(data);
    renderMessages(data.history||[]);
    renderShopping(data.shopping||[]);
    renderTodos(data.todos||[]);
    renderAlarms(data.alarms||[]);
    renderAlarmStatus(Boolean(data.alarm_ringing));
    renderAlarmToast(data.alarms_ringing||[]);
    renderTimers(data.timers||[],data.now);
    loadRoutines();
    loadAgenda();
    if(currentTab==="dashboard"||currentTab==="habits") loadHabits();
  }catch(e){console.error("Refresh:",e);}
}

// ── Chat actions ──
async function sendMsg(){
  const el=document.getElementById("msgInput");
  const t=el.value.trim();if(!t)return;el.value="";
  const msgs=document.getElementById("messages");
  const div=document.createElement("div");div.className="msg user";
  div.innerHTML=`<div class="bubble">${esc(t)}</div><div class="msg-meta">agora · user</div>`;
  if(msgs.querySelector(".empty"))msgs.innerHTML="";
  msgs.appendChild(div);msgs.scrollTop=msgs.scrollHeight;
  showTyping();
  const beforeAssistants=_assistantCount(_lastHistory);
  _chatWaiting=true;
  try{
    const d=await api("/api/chat","POST",{message:t});
    _chatWaiting=false;hideTyping();renderMessages(d.history||[]);loadTimers();
  }catch(e){
    if(isGatewayTimeout(e)){
      try{
        const d=await waitForChatReply(beforeAssistants);
        _chatWaiting=false;hideTyping();
        if(d){renderMessages(d.history||[]);loadTimers();}
      }catch(waitErr){
        _chatWaiting=false;hideTyping();
        alertUnlessTimeout(waitErr);
      }
      return;
    }
    _chatWaiting=false;hideTyping();alert(e.message);
  }
}
document.getElementById("sendBtn").addEventListener("click",sendMsg);
(function(){ // caixa de mensagem: cresce com o texto; Enter envia, Shift+Enter quebra a linha
  const box=document.getElementById("msgInput");
  const fit=()=>{box.style.height="auto";box.style.height=Math.min(box.scrollHeight,140)+"px";box.style.overflowY=box.scrollHeight>140?"auto":"hidden";};
  box.addEventListener("input",fit);
  box.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendMsg().then?.(fit);setTimeout(fit,0);}});
  box.addEventListener("focus",()=>setTimeout(()=>{const m=document.getElementById("messages");m.scrollTop=m.scrollHeight;},300));
})();
(function(){ // altura real da tela (o teclado do iPhone encolhe a área visível) e nada de zoom
  const vv=window.visualViewport;
  const setH=()=>{document.documentElement.style.setProperty("--app-h",(vv?vv.height:window.innerHeight)+"px");window.scrollTo(0,0);};
  if(vv){vv.addEventListener("resize",setH);vv.addEventListener("scroll",()=>window.scrollTo(0,0));}
  window.addEventListener("resize",setH);setH();
  ["gesturestart","gesturechange"].forEach(ev=>document.addEventListener(ev,e=>e.preventDefault(),{passive:false}));
})();
document.getElementById("clearBtn").addEventListener("click",async()=>{await api("/api/reset","POST",{});await refresh();});

const shopInput=document.getElementById("shopInput");
document.getElementById("shopAdd").addEventListener("click",async()=>{const v=shopInput.value.trim();if(!v)return;shopInput.value="";await api("/api/shopping/add","POST",{name:v});await refresh();});
enter(shopInput,()=>document.getElementById("shopAdd").click());

const todoInput=document.getElementById("todoInput");
document.getElementById("todoAdd").addEventListener("click",async()=>{const v=todoInput.value.trim();if(!v)return;todoInput.value="";await api("/api/todos/add","POST",{title:v});await refresh();});
enter(todoInput,()=>document.getElementById("todoAdd").click());

document.getElementById("alarmAdd").addEventListener("click",async()=>{
  const time=document.getElementById("alarmTime").value||_almTime;
  if(!time){alert("Escolha um horário.");return;}
  const spec=_peekAlarmSpec();
  if(!spec){
    alert(_almType==="weekly"?"Selecione ao menos um dia da semana.":"Clique num dia no calendário para marcar a data.");
    focusAlmCalendar();
    return;
  }
  const next=_nextFromAlarmSpec(spec);
  if(spec.type==="once"&&next&&next<=new Date()){
    alert("Esse horário já passou. Escolha um dia ou hora no futuro.");
    return;
  }
  const label=(document.getElementById("alarmLabel").value||"").trim()||"Alarme";
  const body={time_hhmm:time,label,recurring_daily:_almType==="daily"};
  if(_almType==="once"&&_almDate) body.date_ymd=_almDate;
  if(_almType==="weekly") body.days_of_week=selDays.slice();
  if(_almType==="monthly") body.day_of_month=_almDom;
  try{
    await api("/api/alarms/add","POST",body);
    document.getElementById("alarmLabel").value="";
    startNewAlarm();
    await refresh();
  }catch(e){alertUnlessTimeout(e);}
});
document.getElementById("alarmStop").addEventListener("click",async()=>{await api("/api/alarms/stop","POST",{});renderAlarmToast([]);await refresh();});

// ── Export history ──
document.getElementById("exportHistBtn").addEventListener("click",async()=>{
  const data=await api("/api/dashboard");
  const blob=new Blob([JSON.stringify(data.history||[],null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);
  a.download=`cassandra-historico-${new Date().toISOString().slice(0,10)}.json`;
  a.click();URL.revokeObjectURL(a.href);
});
document.getElementById("clearHistBtn").addEventListener("click",async()=>{
  if(!confirm("Limpar todo o histórico de conversas?")) return;
  await api("/api/reset","POST",{});await refresh();
  alert("Histórico limpo.");
});

// ── Web-agent status ──
async function checkWebAgentStatus(){
  const dot=document.getElementById("web-agent-dot");
  const lbl=document.getElementById("web-agent-label");
  const badge=document.getElementById("web-agent-badge");
  const urlEl=document.getElementById("web-agent-url");
  dot.style.background="#f472b6"; lbl.textContent="Verificando…";
  badge.style.borderColor="var(--border)";
  try{
    const d=await api("/api/maestro-status");
    urlEl.textContent=d.url||"";
    const agentsEl=document.getElementById("orch-agents");
    if(agentsEl){
      const list=(d.agents||[]).map(a=>`${a.name} — ${a.enabled===false?"desligado":a.status}`);
      agentsEl.textContent=list.length?list.join(" · "):(d.connected?"nenhum agente":"—");
    }
    const heroBadge=document.getElementById("heroWebAgentBadge");
    if(d.connected){
      dot.style.background="var(--green)"; lbl.textContent="Conectado";
      badge.style.borderColor="rgba(52,211,153,.3)"; badge.style.color="var(--green)";
      if(heroBadge){heroBadge.style.display="inline-flex";}
    } else {
      dot.style.background="var(--red)"; lbl.textContent="Desconectado";
      badge.style.borderColor="rgba(248,113,113,.3)"; badge.style.color="var(--red)";
      if(heroBadge){heroBadge.style.display="none";}
    }
  }catch(e){
    dot.style.background="var(--red)"; lbl.textContent="Erro";
    badge.style.color="var(--red)";
  }
}
document.getElementById("checkWebAgentBtn").addEventListener("click",checkWebAgentStatus);

// ── Som: volume e saída ──
let volBusy=false, volTimer=null;
function renderVolume(d){
  const range=document.getElementById("vol-range"), val=document.getElementById("vol-val");
  const ctl=document.getElementById("vol-control");
  if(!d.available){range.disabled=true;val.textContent="—";document.getElementById("vol-desc").textContent="Controle de volume indisponível neste aparelho";return;}
  range.disabled=false;
  if(!volBusy) range.value=d.volume;
  val.textContent=d.muted?"mudo":d.volume+"%";
  ctl.classList.toggle("muted",!!d.muted);
  document.getElementById("vol-mute").dataset.muted=d.muted?"1":"";
  document.getElementById("vol-mute").title=d.muted?"Tirar do mudo":"Silenciar";
  document.getElementById("vol-mute-waves").style.display=d.muted?"none":"";
  document.getElementById("vol-mute-x").style.display=d.muted?"":"none";
  const sel=document.getElementById("audio-output");
  if(document.activeElement!==sel){
    const outs=d.outputs||[];
    sel.innerHTML=outs.length?outs.map(o=>`<option value="${o.id}" ${o.default?"selected":""}>${esc(o.name)}</option>`).join(""):'<option value="">—</option>';
    sel.disabled=outs.length<2;
  }
}
async function loadAudio(){try{renderVolume(await api("/api/audio"));}catch(e){console.error("Audio:",e);}}
async function sendVolume(body){try{renderVolume(await api("/api/audio/volume","POST",body));}catch(e){alertUnlessTimeout(e);}}
document.getElementById("vol-range").addEventListener("input",e=>{
  volBusy=true; document.getElementById("vol-val").textContent=e.target.value+"%";
  clearTimeout(volTimer);
  volTimer=setTimeout(async()=>{await sendVolume({volume:+e.target.value,muted:false});volBusy=false;},180);
});
document.getElementById("vol-up").addEventListener("click",()=>sendVolume({delta:5}));
document.getElementById("vol-down").addEventListener("click",()=>sendVolume({delta:-5}));
document.getElementById("vol-mute").addEventListener("click",e=>sendVolume({muted:!e.currentTarget.dataset.muted}));
document.getElementById("audio-output").addEventListener("change",async e=>{
  if(!e.target.value) return;
  try{renderVolume(await api("/api/audio/output","POST",{id:+e.target.value}));}catch(err){alertUnlessTimeout(err);loadAudio();}
});

// ── Bluetooth ──
let btPoll=null;
function btItem(d,found){
  const meta=[d.mac, d.connected?"conectado":(d.paired?"pareado":"novo")].join(" · ");
  const actions=found
    ? `<button class="btn btn-primary btn-sm" data-bt="connect" data-mac="${d.mac}">Conectar</button>`
    : (d.connected
        ? `<button class="btn btn-ghost btn-sm" data-bt="disconnect" data-mac="${d.mac}">Desconectar</button>`
        : `<button class="btn btn-primary btn-sm" data-bt="connect" data-mac="${d.mac}">Conectar</button>`)
      + `<button class="btn btn-danger btn-sm" data-bt="forget" data-mac="${d.mac}" data-name="${esc(d.name)}">Esquecer</button>`;
  return `<div class="bt-item ${d.connected?"connected":""}"><span class="bt-dot"></span><div class="bt-item-info"><div class="bt-item-name">${esc(d.name)}</div><div class="bt-item-meta">${meta}</div></div><div class="bt-item-actions">${actions}</div></div>`;
}
function renderBluetooth(d){
  const power=document.getElementById("bt-power"), scan=document.getElementById("bt-scan");
  const desc=document.getElementById("bt-desc");
  if(!d.available){desc.textContent="Bluetooth indisponível neste aparelho";power.disabled=true;scan.disabled=true;
    document.getElementById("bt-paired").innerHTML='<div class="bt-empty">—</div>';return;}
  power.disabled=false; power.checked=!!d.powered;
  const devs=d.devices||[], paired=devs.filter(x=>x.paired), found=devs.filter(x=>!x.paired);
  const nConn=paired.filter(x=>x.connected).length;
  desc.textContent=!d.powered?"Desligado":(nConn?`${nConn} aparelho${nConn>1?"s":""} conectado${nConn>1?"s":""}`:"Ligado, nenhum aparelho conectado");
  document.getElementById("bt-paired").innerHTML=paired.length?paired.map(x=>btItem(x,false)).join(""):'<div class="bt-empty">Nenhum aparelho pareado ainda.</div>';
  const busy=d.job&&d.job.state==="running";
  document.getElementById("bt-found").innerHTML=found.length?found.map(x=>btItem(x,true)).join("")
    :(d.scanning?'<div class="bt-empty">Procurando…</div>':"");
  scan.disabled=!d.powered||d.scanning||busy;
  scan.textContent=d.scanning?"Procurando…":"Procurar aparelhos";
  document.querySelectorAll("[data-bt]").forEach(b=>b.disabled=!!busy);
  const job=document.getElementById("bt-job");
  job.className="bt-job"+(d.job&&(Date.now()/1000-d.job.at<120||busy)?" "+d.job.state:"");
  job.textContent=d.job?d.job.message:"";
  // enquanto procura ou conecta, atualiza rápido; depois, para
  if(d.scanning||busy){if(!btPoll) btPoll=setInterval(loadBluetooth,2000);}
  else if(btPoll){clearInterval(btPoll);btPoll=null;loadAudio();}
}
async function loadBluetooth(){try{renderBluetooth(await api("/api/bluetooth"));}catch(e){console.error("Bluetooth:",e);}}
async function btAction(path,body){try{renderBluetooth(await api(path,"POST",body));}catch(e){alertUnlessTimeout(e);loadBluetooth();}}
document.getElementById("bt-scan").addEventListener("click",()=>btAction("/api/bluetooth/scan",{}));
document.getElementById("bt-power").addEventListener("change",e=>btAction("/api/bluetooth/power",{on:e.target.checked}));
document.getElementById("bt-paired").parentElement.addEventListener("click",e=>{
  const b=e.target.closest("[data-bt]"); if(!b) return;
  const act=b.dataset.bt, mac=b.dataset.mac;
  if(act==="forget"&&!confirm(`Esquecer ${b.dataset.name}? Para usar de novo, será preciso parear outra vez.`)) return;
  btAction(`/api/bluetooth/${act}`,{mac});
});

// ── Spotify ──
let spState=null;
function renderSpotify(d){
  spState=d;
  const acc=document.getElementById("sp-account"), con=document.getElementById("sp-connect"), dis=document.getElementById("sp-disconnect");
  const devRow=document.getElementById("sp-device-row"), player=document.getElementById("sp-player");
  if(!d.configured){acc.textContent="Falta o SPOTIFY_CLIENT_ID no .env da Cassandra";con.style.display="none";dis.style.display="none";devRow.style.display="none";player.style.display="none";return;}
  if(!d.connected){acc.textContent="Não conectada — conecte para ela tocar o que você pedir (conta Premium)";con.style.display="";dis.style.display="none";devRow.style.display="none";player.style.display="none";return;}
  con.style.display="none"; dis.style.display="";
  const renew=document.getElementById("sp-renew");
  renew.style.display="";
  const days=d.expires_at?Math.floor((d.expires_at*1000-Date.now())/86400000):null;
  renew.className="btn btn-sm "+(d.expired||(days!==null&&days<=14)?"btn-warn":"btn-ghost");
  renew.textContent=d.expired?"Renovar credenciais (expirou)":"Renovar credenciais";
  const validity=days===null?"":(days>0?` · login vale por mais ${days} dia${days>1?"s":""}`:" · login vencido");
  acc.innerHTML=d.error?`<span style="color:#fca5a5">${esc(d.error)}</span>`:`Conectada como <b>${esc(d.user||"")}</b>${d.premium===false?' — <span style="color:#fca5a5">precisa de Premium para tocar</span>':""}${validity}`;
  devRow.style.display=""; player.style.display="";
  document.getElementById("sp-device-name").textContent=d.device_name;
  const chip=document.getElementById("sp-device-chip");
  chip.textContent=d.device_online?"online":"não apareceu";
  chip.style.color=d.device_online?"var(--green)":"var(--amber)";
  document.getElementById("sp-device-desc").textContent=d.device_online
    ?"O Raspberry Pi toca no Spotify pela saída de áudio atual"
    :(d.pair?`Falta parear: abra spotify.com/pair e digite o código ${d.pair.code}`:"Desconectada — conecte pela aba Música");
  const np=d.now_playing;
  document.getElementById("sp-title").textContent=np?np.title:"Nada tocando";
  document.getElementById("sp-artist").textContent=np?(np.artist+(np.device&&np.device!==d.device_name?` · em ${np.device}`:"")):'Peça "Cassandra, toca …" ou use o campo abaixo';
  const cover=document.getElementById("sp-cover");
  if(np&&np.image){cover.src=np.image;cover.style.visibility="";}else{cover.removeAttribute("src");cover.style.visibility="hidden";}
  document.getElementById("sp-toggle-icon").innerHTML=np&&np.is_playing?'<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>':'<path d="M8 5v14l11-7z"/>';
}
function spMsg(text,state){const m=document.getElementById("sp-msg");m.className="bt-job "+(state||"");m.textContent=text||"";}
async function loadSpotify(){try{renderSpotify(await api("/api/spotify/status"));}catch(e){console.error("Spotify:",e);}}
function spLogin(){window.location.href="/api/spotify/login?origin="+encodeURIComponent(window.location.origin);}
document.getElementById("sp-connect").addEventListener("click",spLogin);
document.getElementById("sp-renew").addEventListener("click",spLogin);
document.getElementById("sp-disconnect").addEventListener("click",async()=>{
  if(!confirm("Desconectar a conta do Spotify da Cassandra?")) return;
  try{renderSpotify(await api("/api/spotify/disconnect","POST",{}));spMsg("");}catch(e){alertUnlessTimeout(e);}
});
document.getElementById("sp-player").addEventListener("click",async e=>{
  const b=e.target.closest("[data-sp]"); if(!b) return;
  let action=b.dataset.sp;
  if(action==="toggle") action=spState&&spState.now_playing&&spState.now_playing.is_playing?"pause":"resume";
  try{const d=await api("/api/spotify/control","POST",{action});spMsg(d.message,"ok");setTimeout(loadSpotify,700);}
  catch(err){spMsg(err.message,"error");}
});
async function spPlay(){
  const q=document.getElementById("sp-query").value.trim(); if(!q) return;
  spMsg("Procurando…","running");
  try{const d=await api("/api/spotify/play","POST",{query:q});spMsg(d.message,"ok");document.getElementById("sp-query").value="";setTimeout(loadSpotify,1200);}
  catch(err){spMsg(err.message,"error");}
}
document.getElementById("sp-play").addEventListener("click",spPlay);
enter(document.getElementById("sp-query"),spPlay);
// ── Reiniciar a Cassandra (botão do cabeçalho) ──
document.getElementById("restartBtn").addEventListener("click",async()=>{
  if(!confirm("Reiniciar a Cassandra agora? Ela fica fora do ar por uns 20 segundos.")) return;
  const overlay=document.getElementById("restartOverlay");
  overlay.classList.add("show");
  try{await api("/api/system/restart","POST",{});}catch(e){/* a conexão pode cair no meio: normal */}
  const started=Date.now();
  await new Promise(r=>setTimeout(r,6000));  // dá tempo de ela desligar antes de perguntar se voltou
  while(Date.now()-started<120000){
    try{const r=await fetch("/api/settings",{cache:"no-store"});if(r.ok){location.reload();return;}}catch(e){}
    await new Promise(r=>setTimeout(r,2000));
  }
  document.getElementById("restartTitle").textContent="A Cassandra está demorando para voltar";
  document.getElementById("restartText").textContent="Recarregue a página em alguns instantes.";
});

// ── Aba Microfone ──
const MIC_KINDS={status:"estado",heard:"som",no_wake:"sem nome",wake:"nome",transcribed:"texto",ignored:"ignorado",command:"pedido",response:"resposta",error:"erro"};
const MIC_USEFUL=new Set(["wake","transcribed","ignored","command","response","error","status"]);
let micAfter=0, micTimer=null, micPaused=false, micEvents=[];
function micRender(d){
  const dot=document.getElementById("micDot"), title=document.getElementById("micTitle"), sub=document.getElementById("micSub");
  if(d.present===false){dot.className="mic-dot off";title.textContent="Nenhum microfone conectado";sub.textContent="Plugue um microfone USB no Raspberry Pi — ela começa a ouvir sozinha.";}
  else if(d.listening){dot.className="mic-dot on";title.textContent="Microfone conectado e ouvindo";sub.textContent=[d.device,d.rate?`${d.rate} Hz`+(d.rate!==16000?" → 16000 Hz":""):""].filter(Boolean).join(" · ")||"—";}
  else{dot.className="mic-dot";title.textContent=d.present?"Microfone conectado":"Microfone: sem sinal agora";sub.textContent=(d.device?d.device+" · ":"")+"não está lendo o áudio neste instante (falando ou pensando?)";}
  document.getElementById("micPhase").textContent=d.phase||"—";
  document.getElementById("micBadge").textContent=d.listening?"ao vivo":"parado";
  const max=Math.max(d.threshold*3,1500);
  document.getElementById("micFill").style.width=Math.min(100,d.level/max*100)+"%";
  document.getElementById("micPeak").style.left=Math.min(100,d.peak/max*100)+"%";
  document.getElementById("micThr").style.left=Math.min(100,d.threshold/max*100)+"%";
  document.getElementById("micLevel").textContent=`nível ${d.level} · pico ${d.peak}`;
  document.getElementById("micThrLabel").textContent=`limite de fala ${d.threshold} · ruído ${d.noise||0}`;
  if(!micPaused&&(d.events||[]).length){micEvents=micEvents.concat(d.events).slice(-10);micRenderLog();}
  if((d.events||[]).length) micAfter=d.events[d.events.length-1].id;
}
function micRenderLog(){
  const only=document.getElementById("micOnlyUseful").checked;
  const list=micEvents.filter(e=>!only||MIC_USEFUL.has(e.kind)).slice().reverse();
  document.getElementById("micLog").innerHTML=list.length?list.map(e=>{
    const t=new Date(e.ts*1000).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
    return `<div class="mic-row"><span class="mic-time">${t}</span><span class="mic-kind ${e.kind}">${MIC_KINDS[e.kind]||e.kind}</span><span class="mic-text">${esc(e.text)}</span></div>`;
  }).join(""):'<div class="bt-empty">Nada captado ainda. Fale perto do microfone.</div>';
}
async function micPoll(){try{micRender(await api(`/api/mic?after=${micAfter}`));}catch(e){document.getElementById("micTitle").textContent="Sem resposta da Cassandra";}}
function micOpen(){micPoll();clearInterval(micTimer);micTimer=setInterval(micPoll,700);}
function micClose(){clearInterval(micTimer);micTimer=null;}
document.getElementById("micPause").addEventListener("click",e=>{micPaused=!micPaused;e.currentTarget.textContent=micPaused?"Continuar":"Pausar";});
document.getElementById("micClear").addEventListener("click",()=>{micEvents=[];micRenderLog();});
document.getElementById("micOnlyUseful").addEventListener("change",micRenderLog);
document.addEventListener("visibilitychange",()=>{if(document.hidden) micClose(); else if(currentTab==="mic") micOpen();});

// ── Aba Aparelhos ──
const APP_COLORS={netflix:"#e50914",youtube:"#ff0033",prime:"#00a8e1",disney:"#113ccf",globoplay:"#f15a24",max:"#5822b4",spotify:"#1db954",twitch:"#9146ff"};
// Categoria vem do servidor (classificada ao conectar); aqui só o nome e o ícone de cada uma.
const DV_CATEGORIES={
  tv:["TV",'<rect x="2" y="7" width="20" height="13" rx="2"/><polyline points="17 2 12 7 7 2"/>'],
  streaming:["Player de streaming",'<rect x="3" y="9" width="18" height="6" rx="2"/><line x1="7" y1="12" x2="7.01" y2="12"/><path d="M15 15v3"/>'],
  speaker:["Caixa de som",'<rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="14" r="4"/><line x1="12" y1="6" x2="12.01" y2="6"/>'],
  light:["Lâmpada",'<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 00-4 12.7V17h8v-2.3A7 7 0 0012 2z"/>'],
  computer:["Computador",'<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>'],
  router:["Roteador",'<rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6.01 17.5h.01"/><path d="M10 17.5h.01"/><path d="M15 10a4 4 0 016 0"/><path d="M13 7a8 8 0 0110 0"/>'],
  printer:["Impressora",'<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>'],
  smart_home:["Casa inteligente",'<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><circle cx="12" cy="14" r="3"/>'],
  media_server:["Servidor de mídia",'<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/>'],
  other:["Aparelho",'<rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>'],
};
const dvIcon=c=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${(DV_CATEGORIES[c]||DV_CATEGORIES.other)[1]}</svg>`;
const dvLabel=c=>(DV_CATEGORIES[c]||DV_CATEGORIES.other)[0];
const DV_BT_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5"/></svg>';
let dvState=null, dvCurrent=null, dvPoll=null;
function dvSay(text,state){const m=document.getElementById("dvJob");m.className="bt-job "+(state||"");m.textContent=text||"";}
function rmSay(text,state){const m=document.getElementById("rmMsg");m.className="remote-msg "+(state||"");m.textContent=text||"";}
function renderDevices(d){
  dvState=d;
  const saved=d.devices||[], found=d.found||[];
  document.getElementById("dvCount").textContent=`${saved.length} conectado${saved.length===1?"":"s"}`;
  const catOptions=cur=>Object.keys(DV_CATEGORIES).map(c=>`<option value="${c}" ${c===cur?"selected":""}>${dvLabel(c)}</option>`).join("");
  document.getElementById("dvSaved").innerHTML=saved.length?saved.map(x=>`
    <div class="dv-card clickable" data-dv-open="${esc(x.id)}">
      <div class="dv-head"><div class="dv-icon">${dvIcon(x.category)}</div><div style="min-width:0;flex:1"><div class="dv-name">${esc(x.name)}</div><div class="dv-sub"><span class="dv-dot ${x.online?"on":""}"></span>${x.online?"online":"fora do ar"} · ${esc(dvLabel(x.category))}${x.model?" · "+esc(x.model):""}</div></div></div>
      <div class="dv-actions">
        <button class="btn btn-primary btn-sm" data-dv-open="${esc(x.id)}">Controlar</button>
        ${x.panel==="tv"?(x.default?'<span class="info-chip">padrão da voz</span>':`<button class="btn btn-ghost btn-sm" data-dv-act="default" data-id="${esc(x.id)}">Tornar padrão</button>`):""}
        <button class="btn btn-ghost btn-sm" data-dv-act="rename" data-id="${esc(x.id)}">Renomear</button>
        <button class="btn btn-danger btn-sm" data-dv-act="forget" data-id="${esc(x.id)}" data-name="${esc(x.name)}">Esquecer</button>
        <select class="settings-select" data-dv-cat="${esc(x.id)}" title="Tipo do aparelho (corrija se a Cassandra errou)" style="min-width:150px;max-width:190px;flex:1">${catOptions(x.category)}</select>
      </div></div>`).join(""):'<div class="bt-empty">Nenhum aparelho conectado. Toque em "Procurar aparelhos".</div>';
  const scan=document.getElementById("dvScan");
  scan.disabled=!!d.scanning; scan.textContent=d.scanning?"Procurando…":"Procurar aparelhos";
  const jobs=d.jobs||{};
  document.getElementById("dvFound").innerHTML=found.map(f=>{
    const job=jobs[f.host], busy=job&&job.state==="running";
    const sub=[f.manufacturer,f.model,f.host].filter(Boolean).join(" · ");
    return `<div class="dv-card"><div class="dv-head"><div class="dv-icon">${dvIcon("other")}</div><div style="min-width:0;flex:1"><div class="dv-name">${esc(f.name)}</div><div class="dv-sub">${esc(sub)}</div></div></div>
      <div class="dv-actions"><button class="btn btn-primary btn-sm" data-dv-connect="${esc(f.host)}" ${busy?"disabled":""}>${busy?"Conectando…":"Conectar"}</button></div></div>`;
  }).join("");
  const running=Object.values(jobs).find(j=>j.state==="running");
  const last=Object.values(jobs).sort((a,b)=>b.at-a.at)[0];
  if(running) dvSay(running.message,"running"); else if(last&&Date.now()/1000-last.at<90) dvSay(last.message,last.state); else dvSay("");
  if(running){if(!dvPoll) dvPoll=setInterval(loadDevices,2500);} else if(dvPoll){clearInterval(dvPoll);dvPoll=null;}
}
async function loadDevices(){try{renderDevices(await api("/api/devices"));}catch(e){dvSay(e.message,"error");}}
async function loadDeviceBt(){
  try{
    const d=await api("/api/bluetooth");
    const paired=(d.devices||[]).filter(x=>x.paired);
    document.getElementById("dvBt").innerHTML=!d.available?'<div class="bt-empty">Bluetooth indisponível.</div>':(paired.length?paired.map(x=>`
      <div class="dv-card"><div class="dv-head"><div class="dv-icon">${DV_BT_ICON}</div><div style="min-width:0;flex:1"><div class="dv-name">${esc(x.name)}</div><div class="dv-sub"><span class="dv-dot ${x.connected?"on":""}"></span>${x.connected?"conectado":"desconectado"}</div></div></div>
      <div class="dv-actions">${x.connected?`<button class="btn btn-primary btn-sm" data-bt-open="${esc(x.mac)}" data-name="${esc(x.name)}">Controlar</button><button class="btn btn-ghost btn-sm" data-dv-bt="disconnect" data-mac="${esc(x.mac)}">Desconectar</button>`:`<button class="btn btn-primary btn-sm" data-dv-bt="connect" data-mac="${esc(x.mac)}">Conectar</button>`}</div></div>`).join(""):'<div class="bt-empty">Nenhum aparelho Bluetooth pareado.</div>');
  }catch(e){document.getElementById("dvBt").innerHTML=`<div class="bt-empty">${esc(e.message)}</div>`;}
}
function dvOpen(){document.getElementById("dvList").style.display="";document.getElementById("dvRemote").style.display="none";loadDevices();loadDeviceBt();}
async function dvScan(){
  document.getElementById("dvScan").disabled=true; dvSay("Procurando aparelhos na rede…","running");
  try{renderDevices(await api("/api/devices/scan","POST",{}));const n=(dvState.found||[]).length;dvSay(n?`${n} aparelho${n>1?"s":""} encontrado${n>1?"s":""}.`:"Nenhum aparelho novo encontrado. Ele está ligado e no mesmo Wi-Fi?",n?"ok":"error");}
  catch(e){dvSay(e.message,"error");document.getElementById("dvScan").disabled=false;}
}
const LIGHT_COLORS=["#ff3b30","#ff9500","#ffcc00","#34c759","#00c7be","#007aff","#af52de","#ff2d55","#ffffff"];
let lgTimer=null, spkTimer=null;
function openRemote(id){
  const x=(dvState&&dvState.devices||[]).find(d=>d.id===id); if(!x) return;
  const panel=x.panel||"generic";
  ["pnlTv","pnlComputer","pnlLight","pnlSpeaker","pnlBt"].forEach(p=>document.getElementById(p).style.display="none");
  document.getElementById("pnlNet").style.display="";
  const show={tv:"pnlTv",computer:"pnlComputer",light:"pnlLight",speaker:"pnlSpeaker"}[panel];
  if(show) document.getElementById(show).style.display="";
  const page=document.getElementById("rmPage");
  if(x.page_url){page.href=x.page_url;page.style.display="";}else page.style.display="none";
  document.getElementById("rmNetInfo").textContent=[x.host,x.mac?`MAC ${x.mac}`:"",x.manufacturer,x.model].filter(Boolean).join(" · ");
  document.getElementById("lgColors").innerHTML=LIGHT_COLORS.map(c=>`<button class="rbtn" data-rm-color="${c}" title="${c}" style="min-width:40px;background:${c}"></button>`).join("");
  if(panel==="light"){
    api(`/api/devices/${encodeURIComponent(id)}/state`).then(st=>{
      if(st.brightness){document.getElementById("lgBright").value=st.brightness;document.getElementById("lgBrightVal").textContent=st.brightness+"%";}
      if(st.color_temp){document.getElementById("lgTemp").value=st.color_temp;document.getElementById("lgTempVal").textContent=st.color_temp+" K";}
    }).catch(()=>{});
  }
  dvCurrent=x;
  document.getElementById("dvList").style.display="none"; document.getElementById("dvRemote").style.display="";
  document.getElementById("rmName").textContent=x.name;
  document.getElementById("rmSub").textContent=`${x.online?"online":"fora do ar"} · ${dvLabel(x.category)} · ${x.control_label}`;
  const caps=new Set(x.capabilities||[]);
  document.querySelectorAll("#dvRemote [data-rm]").forEach(b=>b.disabled=!caps.has(b.dataset.rm));
  const note=document.getElementById("rmNote");
  if(panel==="computer"){note.style.display="";note.textContent="Controlado pelo Maestro, que roda neste computador. Desligar e reiniciar esperam 1 minuto — dá para cancelar.";}
  else if(panel==="generic"){note.style.display="";note.textContent="A Cassandra ainda não tem controle próprio para este tipo de aparelho. Dá para abrir a página de configuração dele (no mesmo Wi-Fi) e, se ele aceitar, ligá-lo pela rede.";}
  else if(x.control==="dial"){note.style.display="";note.textContent="Este aparelho só aceita abrir e fechar apps pela rede. Para ligar, desligar e volume, use o controle dele, um Fire TV plugado nele ou um emissor infravermelho.";}
  else if(x.control==="firetv"){note.style.display="";note.textContent="Ligar/desligar e volume passam pelo HDMI (CEC): funcionam se a TV tiver o CEC ativado (Anynet+, SimpLink, Bravia Sync…).";}
  else note.style.display="none";
  document.getElementById("rmInputsPanel").style.display=caps.has("input")?"":"none";
  document.getElementById("rmInputs").innerHTML=[1,2,3,4].map(n=>`<button class="rbtn" data-rm-input="${n}">HDMI ${n}</button>`).join("");
  rmSay("");
  if(panel!=="tv") return;
  document.getElementById("rmApps").innerHTML='<div class="bt-empty">Carregando…</div>';
  api(`/api/devices/${encodeURIComponent(id)}/apps`).then(d=>{
    const apps=d.apps||[];
    document.getElementById("rmApps").innerHTML=apps.length?apps.map(a=>`<button class="app-btn" style="background:${APP_COLORS[a.id]||"#334155"}" data-rm-app="${esc(a.id)}">${esc(a.label)}</button>`).join(""):'<div class="bt-empty">Nenhum app conhecido.</div>';
  }).catch(e=>{document.getElementById("rmApps").innerHTML=`<div class="bt-empty">${esc(e.message)}</div>`;});
}
// ── Caixa/fone Bluetooth ──
const BT_PRESETS={normal:"Normal",grave:"Mais grave",grave_forte:"Grave forte",voz:"Voz",agudo:"Mais agudo"};
let btMac=null, btTimer=null, btState=null;
const dbLabel=v=>(v>0?"+":"")+v+" dB";
function btRender(st){
  btState=st;
  document.getElementById("rmSub").textContent=st.connected?`conectado · Bluetooth · ${st.mac}`:`desconectado · Bluetooth · ${st.mac}`;
  if(document.activeElement!==document.getElementById("btVol")&&st.volume!=null){document.getElementById("btVol").value=st.volume;}
  document.getElementById("btVolVal").textContent=st.volume!=null?st.volume+"%":"—";
  document.getElementById("btMute").textContent=st.muted?"Tirar do mudo":"Mudo";
  document.getElementById("btOutput").textContent=st.is_output?"Saída atual ✓":"Usar como saída";
  const eq=st.eq||{};
  document.getElementById("btEqOn").checked=!!eq.enabled;
  if(document.activeElement!==document.getElementById("btBass")) document.getElementById("btBass").value=eq.bass||0;
  if(document.activeElement!==document.getElementById("btTreble")) document.getElementById("btTreble").value=eq.treble||0;
  document.getElementById("btBassVal").textContent=dbLabel(eq.bass||0);
  document.getElementById("btTrebleVal").textContent=dbLabel(eq.treble||0);
  document.querySelectorAll("#pnlBt input,#pnlBt button").forEach(el=>el.disabled=!st.connected);
}
async function btSend(body){
  if(!btMac) return;
  try{btRender(await api(`/api/btaudio/${btMac}`,"POST",body));rmSay("Feito.","ok");}catch(e){rmSay(e.message,"error");}
}
function openBtPanel(mac,name){
  btMac=mac; dvCurrent=null;
  document.getElementById("dvList").style.display="none"; document.getElementById("dvRemote").style.display="";
  ["pnlTv","pnlComputer","pnlLight","pnlSpeaker"].forEach(p=>document.getElementById(p).style.display="none");
  document.getElementById("pnlNet").style.display="none";
  document.getElementById("pnlBt").style.display="";
  document.getElementById("rmName").textContent=name;
  const note=document.getElementById("rmNote"); note.style.display="";
  note.textContent="Volume e mudo são da própria caixa (pelo Bluetooth). O grave e o agudo são aplicados pelo Raspberry Pi no som que vai para ela — os ajustes internos da caixa (modos de som do app do fabricante) usam um protocolo fechado.";
  document.getElementById("btPresets").innerHTML=Object.entries(BT_PRESETS).map(([k,v])=>`<button class="rbtn" data-bt-preset="${k}">${v}</button>`).join("");
  rmSay("");
  api(`/api/btaudio/${mac}`).then(btRender).catch(e=>rmSay(e.message,"error"));
}
document.getElementById("btVol").addEventListener("input",e=>{document.getElementById("btVolVal").textContent=e.target.value+"%";clearTimeout(btTimer);btTimer=setTimeout(()=>btSend({volume:+e.target.value}),250);});
document.getElementById("btBass").addEventListener("input",e=>{document.getElementById("btBassVal").textContent=dbLabel(+e.target.value);clearTimeout(btTimer);btTimer=setTimeout(()=>btSend({bass:+e.target.value}),300);});
document.getElementById("btTreble").addEventListener("input",e=>{document.getElementById("btTrebleVal").textContent=dbLabel(+e.target.value);clearTimeout(btTimer);btTimer=setTimeout(()=>btSend({treble:+e.target.value}),300);});
document.getElementById("btEqOn").addEventListener("change",e=>{rmSay("Aplicando…");btSend({eq_enabled:e.target.checked});});
document.getElementById("btMute").addEventListener("click",()=>btSend({muted:!(btState&&btState.muted)}));
document.getElementById("btOutput").addEventListener("click",()=>btSend({output:true}));
document.getElementById("btPresets").addEventListener("click",e=>{const b=e.target.closest("[data-bt-preset]");if(b){rmSay("Aplicando…");btSend({preset:b.dataset.btPreset});}});

async function rmCommand(action,value){
  if(!dvCurrent) return;
  rmSay("…");
  try{const d=await api(`/api/devices/${encodeURIComponent(dvCurrent.id)}/command`,"POST",{action,value});rmSay(d.message&&d.message!=="ok"?d.message:"Feito.","ok");}
  catch(e){rmSay(e.message,"error");}
}
document.getElementById("dvScan").addEventListener("click",dvScan);
document.getElementById("lgBright").addEventListener("input",e=>{document.getElementById("lgBrightVal").textContent=e.target.value+"%";clearTimeout(lgTimer);lgTimer=setTimeout(()=>rmCommand("brightness",+e.target.value),250);});
document.getElementById("lgTemp").addEventListener("input",e=>{document.getElementById("lgTempVal").textContent=e.target.value+" K";clearTimeout(lgTimer);lgTimer=setTimeout(()=>rmCommand("color_temp",+e.target.value),250);});
document.getElementById("spkVol").addEventListener("input",e=>{clearTimeout(spkTimer);spkTimer=setTimeout(()=>rmCommand("volume",+e.target.value),250);});
document.getElementById("rmBack").addEventListener("click",dvOpen);
document.getElementById("tab-devices").addEventListener("change",async e=>{
  const sel=e.target.closest("[data-dv-cat]"); if(!sel) return;
  try{renderDevices(await api(`/api/devices/${encodeURIComponent(sel.dataset.dvCat)}/category`,"POST",{category:sel.value}));}catch(err){dvSay(err.message,"error");}
});
document.getElementById("tab-devices").addEventListener("click",async e=>{
  if(e.target.closest("[data-dv-cat]")) return;
  const open=e.target.closest("[data-dv-open]"); const act=e.target.closest("[data-dv-act]");
  if(act){
    e.stopPropagation();
    const id=act.dataset.id, what=act.dataset.dvAct;
    try{
      if(what==="forget"){if(!confirm(`Esquecer ${act.dataset.name}? Para usar de novo, será preciso conectar outra vez.`))return;await api(`/api/devices/${encodeURIComponent(id)}/forget`,"POST",{});}
      else if(what==="rename"){const name=prompt("Nome do aparelho (ex.: TV da sala):");if(!name)return;await api(`/api/devices/${encodeURIComponent(id)}/rename`,"POST",{name});}
      else if(what==="default"){await api(`/api/devices/${encodeURIComponent(id)}/default`,"POST",{});}
      loadDevices();
    }catch(err){dvSay(err.message,"error");}
    return;
  }
  if(open){openRemote(open.dataset.dvOpen);return;}
  const con=e.target.closest("[data-dv-connect]");
  if(con){try{renderDevices(await api("/api/devices/connect","POST",{host:con.dataset.dvConnect}));}catch(err){dvSay(err.message,"error");}return;}
  const bto=e.target.closest("[data-bt-open]"); if(bto){openBtPanel(bto.dataset.btOpen,bto.dataset.name);return;}
  const bt=e.target.closest("[data-dv-bt]");
  if(bt){bt.disabled=true;try{await api(`/api/bluetooth/${bt.dataset.dvBt}`,"POST",{mac:bt.dataset.mac});}catch(err){alertUnlessTimeout(err);}setTimeout(loadDeviceBt,bt.dataset.dvBt==="connect"?6000:800);return;}
  const conf=e.target.closest("[data-rm-confirm]");
  if(conf){
    const what=conf.dataset.rmConfirm==="shutdown"?"Desligar":"Reiniciar";
    if(confirm(`${what} o computador? Ele espera 1 minuto — dá para cancelar.`)) rmCommand(conf.dataset.rmConfirm,60);
    return;
  }
  const col=e.target.closest("[data-rm-color]"); if(col){rmCommand("color",col.dataset.rmColor);return;}
  const rm=e.target.closest("[data-rm]"); if(rm){rmCommand(rm.dataset.rm);return;}
  const inp=e.target.closest("[data-rm-input]"); if(inp){rmCommand("input",+inp.dataset.rmInput);return;}
  const app=e.target.closest("[data-rm-app]"); if(app){rmCommand("app",app.dataset.rmApp);return;}
});

// ── Aba Música ──
let muView=null, muTick=null, muPoll=null, muLibLoaded=false, muVolTimer=null;
const muFmt=ms=>{ms=Math.max(0,ms||0);const s=Math.floor(ms/1000);return Math.floor(s/60)+":"+String(s%60).padStart(2,"0");};
function muSay(text,state){const m=document.getElementById("muMsg");m.className="mu-msg "+(state||"");m.textContent=text||"";}
const MU_PH='<div class="mu-ph"></div>';
function muImg(src){return src?`<img src="${esc(src)}" alt="" loading="lazy"/>`:MU_PH;}
function muRow(i,ctx){
  return `<div class="mu-row">${muImg(i.image)}<div class="mu-row-info"><div class="mu-row-name">${esc(i.name)}</div><div class="mu-row-sub">${esc(i.subtitle||"")}</div></div>
    <div class="mu-row-actions">
      <button class="btn btn-ghost btn-icon" title="Pôr na fila" data-mu-act="queue" data-uri="${esc(i.uri)}" data-name="${esc(i.name)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="15" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="11" y2="18"/><line x1="19" y1="14" x2="19" y2="22"/><line x1="15" y1="18" x2="23" y2="18"/></svg></button>
      <button class="btn btn-primary btn-icon" title="Tocar" data-mu-act="play_uri" data-uri="${esc(i.uri)}" data-name="${esc(i.name)}" data-ctx="${esc(ctx||"")}"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></button>
    </div></div>`;
}
function muCard(i){
  return `<div class="mu-card${i.type==="artist"?" round":""}" data-mu-act="play_uri" data-uri="${esc(i.uri)}" data-name="${esc(i.name)}" title="Tocar ${esc(i.name)}">${muImg(i.image)}<div class="mu-card-name">${esc(i.name)}</div><div class="mu-card-sub">${esc(i.subtitle||"")}</div></div>`;
}
function renderMusic(v){
  muView=v;
  const connect=document.getElementById("muConnect"), body=document.getElementById("muBody");
  const badge=document.getElementById("muDeviceBadge");
  if(!v.connected||v.expired){
    connect.style.display=""; body.style.display="none";
    document.getElementById("muConnectTitle").textContent=v.expired?"O login do Spotify expirou":"Conecte o Spotify";
    document.getElementById("muConnectBtn").textContent=v.expired?"Renovar credenciais":"Conectar Spotify";
    badge.textContent="Spotify desconectado"; return;
  }
  connect.style.display="none"; body.style.display="";
  badge.textContent=v.device_online?`Caixa ${v.device_name} conectada`:`Caixa ${v.device_name} desconectada`;
  const link=document.getElementById("muLinkBtn"), pairLink=document.getElementById("muPairLink");
  document.getElementById("muBanner").style.display=v.device_online?"none":"";
  const bannerText=document.getElementById("muBannerText");
  if(v.pair){
    bannerText.innerHTML=`Falta parear a caixa ${esc(v.device_name)} (o Raspberry Pi) com o seu Spotify, uma vez só: abra <b>spotify.com/pair</b> e digite o código <b style="font-size:16px;letter-spacing:.12em;color:#fff">${esc(v.pair.code)}</b>`;
    pairLink.href=v.pair.url; pairLink.style.display=""; link.textContent="Gerar outro código";
  }else{
    bannerText.textContent=`A caixa ${v.device_name} (o Raspberry Pi) não está conectada ao Spotify.`;
    pairLink.style.display="none"; link.textContent="Conectar a caixa";
  }
  badge.style.color=v.device_online?"var(--green)":"var(--amber)";
  const t=v.track;
  document.getElementById("muTitle").textContent=t?t.name:"Nada tocando";
  document.getElementById("muSub").textContent=t?[t.subtitle,t.album].filter(Boolean).join(" · "):'Busque abaixo ou diga "Cassandra, toca …"';
  const cover=document.getElementById("muCover");
  if(t&&(t.image_large||t.image)){cover.src=t.image_large||t.image;cover.classList.remove("empty");}else{cover.removeAttribute("src");cover.classList.add("empty");}
  document.getElementById("muToggleIcon").innerHTML=v.is_playing?'<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>':'<path d="M8 5v14l11-7z"/>';
  document.getElementById("muShuffle").classList.toggle("on",!!v.shuffle);
  document.getElementById("muRepeat").classList.toggle("on",!!(v.repeat&&v.repeat!=="off"));
  document.getElementById("muRepeatOne").style.display=v.repeat==="track"?"":"none";
  const like=document.getElementById("muLike");
  like.classList.toggle("liked",!!(t&&t.liked));
  document.getElementById("muLikeIcon").setAttribute("fill",t&&t.liked?"currentColor":"none");
  like.disabled=!t;
  if(v.device&&v.device.volume!=null&&document.activeElement!==document.getElementById("muVol")) document.getElementById("muVol").value=v.device.volume;
  const sel=document.getElementById("muDevice");
  if(document.activeElement!==sel){
    const devs=v.devices||[];
    sel.innerHTML=devs.length?devs.map(d=>`<option value="${esc(d.id)}" ${d.active?"selected":""}>${esc(d.name)}${d.active?" (tocando)":""}</option>`).join(""):'<option value="">Nenhum dispositivo</option>';
    if(!devs.some(d=>d.active)&&devs.length) sel.insertAdjacentHTML("afterbegin",'<option value="" selected>Escolher onde tocar…</option>');
  }
  if(v.error) muSay(v.error,"error");
  muProgress(true);
}
function muProgress(reset){
  clearInterval(muTick);
  const t=muView&&muView.track; if(!t) {document.getElementById("muFill").style.width="0";document.getElementById("muPos").textContent="0:00";document.getElementById("muDur").textContent="0:00";return;}
  const start=Date.now(), base=t.progress_ms;
  const draw=()=>{
    const pos=Math.min(t.duration_ms,base+(muView.is_playing?Date.now()-start:0));
    document.getElementById("muFill").style.width=(t.duration_ms?pos/t.duration_ms*100:0)+"%";
    document.getElementById("muPos").textContent=muFmt(pos);
    document.getElementById("muDur").textContent=muFmt(t.duration_ms);
    if(muView.is_playing&&pos>=t.duration_ms) setTimeout(loadMusic,1200);
  };
  draw(); if(muView.is_playing) muTick=setInterval(draw,1000);
}
async function loadMusic(){try{renderMusic(await api("/api/spotify/player"));}catch(e){muSay(e.message,"error");}}
async function loadMusicLibrary(){
  try{
    const d=await api("/api/spotify/library");
    document.getElementById("muPlaylists").innerHTML=(d.playlists||[]).length?d.playlists.map(muCard).join(""):'<div class="bt-empty">Nenhuma playlist na sua conta.</div>';
    document.getElementById("muQueueSec").style.display=(d.queue||[]).length?"":"none";
    document.getElementById("muQueue").innerHTML=(d.queue||[]).map(i=>muRow(i)).join("");
    document.getElementById("muRecentSec").style.display=(d.recent||[]).length?"":"none";
    document.getElementById("muRecent").innerHTML=(d.recent||[]).map(i=>muRow(i,i.context_uri)).join("");
    muLibLoaded=true;
  }catch(e){document.getElementById("muPlaylists").innerHTML=`<div class="bt-empty">${esc(e.message)}</div>`;}
}
function muOpen(){
  loadMusic().then(()=>{if(muView&&muView.connected&&!muView.expired&&!muLibLoaded) loadMusicLibrary();});
  clearInterval(muPoll); muPoll=setInterval(()=>{if(!document.getElementById("tab-music").classList.contains("hidden")) loadMusic(); else clearInterval(muPoll);},5000);
}
async function muControl(action,extra){
  try{const d=await api("/api/spotify/control","POST",{action,...(extra||{})});if(d.message)muSay(d.message,"ok");setTimeout(loadMusic,700);if(["play_uri","queue","liked","top"].includes(action))setTimeout(loadMusicLibrary,2500);}
  catch(e){muSay(e.message,"error");}
}
async function muAsk(text){
  muSay("Procurando…");
  try{const d=await api("/api/spotify/play","POST",{query:text});muSay(d.message,"ok");setTimeout(loadMusic,1200);}catch(e){muSay(e.message,"error");}
}
async function muSearch(){
  const q=document.getElementById("muQuery").value.trim(); if(!q) return;
  const box=document.getElementById("muResults"); box.innerHTML='<div class="bt-empty">Buscando…</div>';
  try{
    const d=await api("/api/spotify/search?q="+encodeURIComponent(q));
    const sec=(title,html)=>html?`<div class="mu-section"><div class="mu-section-title">${title}</div>${html}</div>`:"";
    box.innerHTML=
      sec("Músicas",(d.track||[]).length?`<div class="mu-list">${d.track.map(i=>muRow(i,i.context_uri)).join("")}</div>`:"")+
      sec("Artistas",(d.artist||[]).length?`<div class="mu-grid">${d.artist.map(muCard).join("")}</div>`:"")+
      sec("Álbuns",(d.album||[]).length?`<div class="mu-grid">${d.album.map(muCard).join("")}</div>`:"")+
      sec("Playlists",(d.playlist||[]).length?`<div class="mu-grid">${d.playlist.map(muCard).join("")}</div>`:"")
      ||'<div class="bt-empty">Nada encontrado.</div>';
  }catch(e){box.innerHTML=`<div class="bt-empty">${esc(e.message)}</div>`;}
}
document.getElementById("muSearchBtn").addEventListener("click",muSearch);
enter(document.getElementById("muQuery"),muSearch);
document.getElementById("muConnectBtn").addEventListener("click",spLogin);
document.getElementById("muLinkBtn").addEventListener("click",async e=>{
  const b=e.currentTarget; b.disabled=true; muSay("Conectando a caixa… (até 15 s)");
  await muControl("link_device"); b.disabled=false;
});
document.getElementById("muToggle").addEventListener("click",()=>muControl(muView&&muView.is_playing?"pause":"resume"));
document.getElementById("muShuffle").addEventListener("click",()=>muControl("shuffle",{on:!(muView&&muView.shuffle)}));
document.getElementById("muRepeat").addEventListener("click",()=>{
  const next={off:"context",context:"track",track:"off"}[(muView&&muView.repeat)||"off"];
  muControl("repeat",{mode:next});
});
document.getElementById("muLike").addEventListener("click",()=>muControl(muView&&muView.track&&muView.track.liked?"unlike":"like"));
document.getElementById("muBar").addEventListener("click",e=>{
  const t=muView&&muView.track; if(!t||!t.duration_ms) return;
  const r=e.currentTarget.getBoundingClientRect();
  const pos=Math.round((e.clientX-r.left)/r.width*t.duration_ms);
  t.progress_ms=pos; muProgress(); muControl("seek",{position_ms:pos});
});
document.getElementById("muVol").addEventListener("input",e=>{
  clearTimeout(muVolTimer); muVolTimer=setTimeout(()=>muControl("volume",{level:+e.target.value}),250);
});
document.getElementById("muDevice").addEventListener("change",e=>{if(e.target.value) muControl("transfer",{device_id:e.target.value});});
document.getElementById("tab-music").addEventListener("click",e=>{
  const act=e.target.closest("[data-mu-act]");
  if(act){e.stopPropagation();muControl(act.dataset.muAct,{uri:act.dataset.uri,name:act.dataset.name,context_uri:act.dataset.ctx||null});return;}
  const b=e.target.closest("[data-mu]"); if(b){muControl(b.dataset.mu);return;}
  const ask=e.target.closest("[data-mu-ask]"); if(ask) muAsk(ask.dataset.muAsk);
});

// ── Agentes que a Cassandra usa (Configurações) ──
const AG_STATE={online:"no ar",offline:"desligado",cli:"sob demanda",degraded:"instável"};
function renderAgentsAccess(d){
  const el=document.getElementById("agAccessList"); if(!el) return;
  const msg=t=>`<div class="settings-row" style="border-bottom:none"><div class="settings-row-desc">${t}</div></div>`;
  if(!d.connected){el.innerHTML=msg("O Maestro não está respondendo (o computador pode estar desligado). A lista aparece quando ele voltar.");return;}
  if(!d.agents.length){el.innerHTML=msg("O Maestro não tem outros agentes.");return;}
  el.innerHTML=d.agents.map((a,i)=>{
    const st=a.enabled===false?"desligado no Maestro":(AG_STATE[a.status]||a.status);
    const last=i===d.agents.length-1?' style="border-bottom:none"':"";
    return `<div class="settings-row ag-row${a.allowed?"":" ag-off"}"${last}>
      <div class="settings-row-info"><div class="settings-row-label"><span class="ag-dot ${a.enabled===false?"":esc(a.status)}"></span>${esc(a.name)} <span class="ag-state">${esc(st)}</span></div>
      <div class="settings-row-desc">${esc(a.tagline||"")}</div></div>
      <div class="settings-row-control"><label class="toggle" title="Acesso da Cassandra a ${esc(a.name)}"><input type="checkbox" data-ag-access="${esc(a.name)}" ${a.allowed?"checked":""}/><span class="toggle-slider"></span></label></div>
    </div>`;
  }).join("");
  el.querySelectorAll("[data-ag-access]").forEach(cb=>cb.addEventListener("change",async()=>{
    cb.disabled=true;
    try{renderAgentsAccess(await api("/api/agents/access","POST",{name:cb.dataset.agAccess,allowed:cb.checked}));}
    catch(e){cb.checked=!cb.checked;alertUnlessTimeout(e);}
    finally{cb.disabled=false;}
  }));
}
async function loadAgentsAccess(){
  const el=document.getElementById("agAccessList");
  try{renderAgentsAccess(await api("/api/agents"));}
  catch(e){if(el) el.innerHTML=`<div class="settings-row" style="border-bottom:none"><div class="settings-row-desc">Não consegui carregar: ${esc(e.message)}</div></div>`;}
}
document.getElementById("agAccessRefresh").addEventListener("click",e=>{e.stopPropagation();loadAgentsAccess();});

// ── Configurações: cada seção recolhível (começam fechadas; o navegador lembra as abertas) ──
const SC_KEY="cassSettingsOpen";
function scOpenSet(){try{return new Set(JSON.parse(localStorage.getItem(SC_KEY)||"[]"));}catch(e){return new Set();}}
function scSave(set){try{localStorage.setItem(SC_KEY,JSON.stringify([...set]));}catch(e){}}
function scSetOpen(card,open){
  card.classList.toggle("sc-collapsed",!open);
  const key=card.dataset.scKey, set=scOpenSet();
  if(open) set.add(key); else set.delete(key);
  scSave(set);
}
function openSettingsCard(el){const card=el&&el.closest(".settings-card");if(card&&card.dataset.scKey) scSetOpen(card,true);}
(function initSettingsCollapsibles(){
  const open=scOpenSet();
  document.querySelectorAll("#tab-settings .settings-card").forEach(card=>{
    const title=card.querySelector(":scope > .settings-card-title");
    if(!title||card.dataset.scKey) return;
    const body=document.createElement("div");
    body.className="sc-body";
    while(title.nextSibling) body.appendChild(title.nextSibling);
    card.appendChild(body);
    card.dataset.scKey=title.textContent.trim();
    title.classList.add("sc-toggle");
    title.setAttribute("role","button"); title.tabIndex=0;
    title.insertAdjacentHTML("beforeend",'<svg class="sc-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>');
    card.classList.toggle("sc-collapsed",!open.has(card.dataset.scKey));
    const toggle=()=>scSetOpen(card,card.classList.contains("sc-collapsed"));
    title.addEventListener("click",toggle);
    title.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();toggle();}});
  });
})();

(function(){ // volta do login do Spotify
  const p=new URLSearchParams(window.location.search).get("spotify");
  if(!p) return;
  spMsg(p==="ok"?"Spotify conectado!":"Não deu para conectar o Spotify: "+p, p==="ok"?"ok":"error");
  openSettingsCard(document.getElementById("sp-msg"));
  history.replaceState(null,"",window.location.pathname+window.location.hash);
})();

// ── Init ──
async function init(){
  try{const s=await api("/api/settings");applySettingsToForm(s);}
  catch(e){console.error("Settings:",e);rebuildNavs();}
  await loadLlm();
  await refresh();
  checkWebAgentStatus();
  loadAgentsAccess();
  loadCalendarStatus();
  loadAudio();
  loadBluetooth();
  loadSpotify();
}
init();
setInterval(refresh,5000);

// ── Modo conversa (botão no header) ──
function renderConv(d){
  const b=document.getElementById("convBtn");
  const on=!!(d&&d.active);
  b.classList.toggle("on",on);
  b.title=on?"Modo conversa ligado — toque para desligar":"Modo conversa: ela bate papo, puxa assunto e espera mais por você";
}
async function loadConv(){try{renderConv(await api("/api/conversation"));}catch(e){}}
document.getElementById("convBtn").addEventListener("click",async e=>{
  const on=!e.currentTarget.classList.contains("on");
  renderConv({active:on});
  try{renderConv(await api("/api/conversation","POST",{active:on}));}catch(err){loadConv();}
});
loadConv();setInterval(loadConv,5000);
setInterval(loadAlarmRinging,2000);  // o aviso de alarme aparece em até 2 s
setInterval(()=>{if(tmList.length) loadTimers();},2000);
setInterval(checkWebAgentStatus,30000);
setInterval(()=>{loadAudio();if(!btPoll)loadBluetooth();loadSpotify();},15000);
</script>
</body>
</html>"""

# Rosto/cores da Cassandra: cópia do kit do maestro (orchestrator/static/persona.js, sincronizada por
# orchestrator/plugin/sync_copies.py). Vai embutido na página: a mesma página é servida pelo túnel e pelo Netlify.
_PERSONA_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cassandra", "web", "persona.js")
try:
    with open(_PERSONA_JS_PATH, encoding="utf-8") as _fh:
        _PERSONA_JS = _fh.read().replace("</script", "<\\/script")
except OSError:
    _PERSONA_JS = "window.AgentPersona={face:function(){return ''},mount:function(){}};"
HTML_PAGE = HTML_PAGE.replace("<!--PERSONA_JS-->", "<script>" + _PERSONA_JS + "</script>", 1)


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

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.FOUND.value)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _devices_post(self, action: str, data: dict) -> None:
            mgr = network_devices.manager
            try:
                if action == "scan":
                    mgr.scan()
                elif action == "connect":
                    mgr.start_connect(str(data.get("host", "")))
                else:
                    m = re.match(r"^([a-z0-9-]+)/(command|forget|rename|default|category)$", action)
                    if not m:
                        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
                        return
                    device_id, what = m.groups()
                    if not mgr.get(device_id):
                        self._send_json({"error": "Aparelho não encontrado."}, status=HTTPStatus.NOT_FOUND)
                        return
                    if what == "command":
                        cmd = str(data.get("action", ""))
                        if cmd not in network_devices.ACTIONS:
                            self._send_json({"error": "ação inválida"}, status=HTTPStatus.BAD_REQUEST)
                            return
                        message = mgr.command(device_id, cmd, data.get("value"))
                        self._send_json({"ok": True, "message": message})
                        return
                    if what == "forget":
                        mgr.forget(device_id)
                    elif what == "rename":
                        mgr.rename(device_id, str(data.get("name", "")))
                    elif what == "category":
                        mgr.set_category(device_id, str(data.get("category", "")))
                    else:
                        mgr.set_default(device_id)
            except network_devices.DeviceError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return
            except Exception as exc:  # noqa: BLE001 — TV desligada/fora da rede
                self._send_json({"error": f"A TV não respondeu ({type(exc).__name__}: {exc})"},
                                status=HTTPStatus.BAD_GATEWAY)
                return
            self._send_json(mgr.status())

        @staticmethod
        def _spotify_control(sp, skill, what: str, data: dict) -> str | None:
            """Botões da aba Música. None = ação desconhecida."""
            if what in ("pause", "resume", "next", "previous"):
                return skill._run({"action": what})
            if what == "shuffle":
                return skill._run({"action": "shuffle", "on": bool(data.get("on"))})
            if what == "repeat":
                return skill._run({"action": "repeat", "mode": str(data.get("mode", "off"))})
            if what == "volume":
                return f"Volume da música em {sp.set_volume(int(data.get('level', 50)))}%."
            if what == "seek":
                sp.seek(int(data.get("position_ms", 0)))
                return ""
            if what in ("like", "unlike"):
                return skill._run({"action": "save" if what == "like" else "unsave"})
            if what == "transfer":
                device_id = str(data.get("device_id", ""))
                if not device_id:
                    return None
                sp.transfer(device_id, play=True)
                return "Tocando no dispositivo escolhido."
            if what == "link_device":
                result = sp.link_device()
                if result.get("device"):
                    return "Caixa Cassandra conectada."
                if result.get("pair"):
                    return f"Abra spotify.com/pair e digite o código {result['pair']['code']}."
                raise spotify_api.SpotifyError(
                    "A caixa Cassandra não respondeu. Veja se o Raspberry Pi está ligado e tente de novo.")
            if what in ("liked", "top"):
                return skill._run({"action": "play", "kind": what})
            if what in ("play_uri", "queue"):
                uri = str(data.get("uri", ""))
                if not uri.startswith("spotify:"):
                    return None
                name = str(data.get("name", "")).strip()
                if what == "queue":
                    sp.queue(uri)
                    return f"{name or 'Música'} vai tocar em seguida."
                context = str(data.get("context_uri") or "")
                if uri.split(":")[1] in ("track", "episode"):
                    if context.startswith("spotify:"):
                        sp.play(context_uri=context, offset={"uri": uri})
                    else:
                        sp.play(uris=[uri])
                else:
                    sp.play(context_uri=uri)
                return f"Tocando {name}." if name else "Tocando."
            return None

        def _spotify_post(self, action: str, data: dict) -> None:
            sp = spotify_api.client
            if action == "disconnect":
                sp.disconnect()
                self._send_json(sp.status())
                return
            skill = assistant.spotify_skill
            try:
                if action == "control":
                    if not sp.connected:
                        raise spotify_api.SpotifyError("Conecte a conta do Spotify primeiro.")
                    message = self._spotify_control(sp, skill, str(data.get("action", "")), data)
                    if message is None:
                        self._send_json({"error": "action inválida"}, status=HTTPStatus.BAD_REQUEST)
                        return
                elif action == "play":
                    query = str(data.get("query", "")).strip()
                    if not query:
                        self._send_json({"error": "query is required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    if not sp.connected:
                        raise spotify_api.SpotifyError("Conecte a conta do Spotify primeiro.")
                    text = query if skill.can_handle(query) else f"toca {query}"
                    message = skill._run(skill.intent(text))  # erros viram 502 com a mensagem (não "ok")
                else:
                    self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
                    return
            except spotify_api.SpotifyError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return
            self._send_json({"ok": True, "message": message})

        def _spotify_get(self, parsed) -> None:
            sp = spotify_api.client
            if parsed.path == "/api/spotify/player":
                self._send_json(sp.player_view())
                return
            if not sp.connected:
                self._send_json({"error": "Conecte a conta do Spotify primeiro."}, status=HTTPStatus.CONFLICT)
                return
            view = spotify_api.item_view
            try:
                if parsed.path == "/api/spotify/search":
                    q = (parse_qs(parsed.query).get("q") or [""])[0].strip()
                    if not q:
                        self._send_json({"error": "q is required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    found = sp.search_all(q)
                    self._send_json({kind: [view(i) for i in items] for kind, items in found.items()})
                    return
                # library: suas playlists, a fila e as tocadas recentemente
                self._send_json({
                    "playlists": [view(p) for p in sp.my_playlists(100)],
                    "queue": [view(i) for i in sp.queue_items()[:10]],
                    "recent": [view(t) for t in sp.recently_played(12)],
                })
            except spotify_api.SpotifyError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTML_PAGE)
                return
            if parsed.path == "/api/history":
                self._send_json({"history": assistant.get_conversation_history()})
                return
            if parsed.path == "/api/alarms/ringing":
                self._send_json({"ringing": assistant.alarm_manager.ringing()})
                return
            if parsed.path == "/api/timers":
                self._send_json({"timers": assistant.timer_manager.snapshot(), "now": time.time()})
                return
            if parsed.path == "/api/conversation":
                self._send_json(assistant.get_conversation_mode())
                return
            if parsed.path == "/api/dashboard":
                self._send_json({
                    "history":       assistant.get_conversation_history(),
                    "shopping":      assistant.get_shopping_items(),
                    "todos":         assistant.get_todos(),
                    "alarms":        assistant.list_alarms(),
                    "alarm_ringing": assistant.is_alarm_ringing(),
                    "alarms_ringing": assistant.alarm_manager.ringing(),
                    "timers":        assistant.timer_manager.snapshot(),
                    "now":           time.time(),
                })
                return
            if parsed.path == "/api/settings":
                self._send_json(assistant.get_ui_settings())
                return
            if parsed.path == "/api/llm":
                self._send_json(llm_settings.get_public())
                return
            if parsed.path == "/api/habits":
                from cassandra import habits  # noqa: PLC0415

                try:
                    year = int((parse_qs(parsed.query).get("year") or ["0"])[0])
                except ValueError:
                    year = 0
                self._send_json(habits.overview(year or None))
                return
            if parsed.path == "/api/usage":
                from cassandra import usage_log  # noqa: PLC0415

                try:
                    days = max(1, min(365, int((parse_qs(parsed.query).get("days") or ["30"])[0])))
                except ValueError:
                    days = 30
                self._send_json(usage_log.summary(days))
                return
            if parsed.path == "/api/llm/local-models":
                try:
                    self._send_json({"models": llm_settings.local_models()})
                except Exception as exc:  # noqa: BLE001 — PC desligado, Llama Desk fora do ar...
                    self._send_json({"models": [], "error": str(exc)[:160]})
                return
            if parsed.path == "/api/azure/voices":
                from cassandra.voice import azure_voices  # noqa: PLC0415

                try:
                    self._send_json({"voices": azure_voices()})
                except Exception as exc:  # noqa: BLE001 — chave errada, sem rede...: a UI mostra só a voz atual
                    self._send_json({"voices": [], "error": str(exc)[:200]})
                return
            if parsed.path == "/api/routines":
                self._send_json({"routines": assistant.get_routines()})
                return
            if parsed.path == "/api/calendar/status":
                self._send_json(assistant.get_calendar_status())
                return
            if parsed.path == "/api/agenda/events":
                qs = parse_qs(parsed.query)
                days = int((qs.get("days", ["7"])[0]))
                status = assistant.get_calendar_status()
                if not status.get("configured"):
                    self._send_json({"configured": False, "events": []})
                    return
                events = assistant.list_calendar_events(days=days)
                self._send_json({"configured": True, "events": events})
                return
            if parsed.path == "/api/audio":
                self._send_json(audio_devices.audio_status())
                return
            m = re.match(r"^/api/btaudio/([0-9A-Fa-f:]{17})$", parsed.path)
            if m:
                try:
                    self._send_json(bt_audio.state(m.group(1)))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return
            if parsed.path == "/api/mic":
                try:
                    after = int((parse_qs(parsed.query).get("after") or ["0"])[0])
                except ValueError:
                    after = 0
                self._send_json(mic_monitor.snapshot(after))
                return
            if parsed.path == "/api/devices":
                self._send_json(network_devices.manager.status())
                return
            m = re.match(r"^/api/devices/([a-z0-9-]+)/state$", parsed.path)
            if m:
                try:
                    self._send_json(network_devices.manager.light_state(m.group(1)))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return
            m = re.match(r"^/api/devices/([a-z0-9-]+)/apps$", parsed.path)
            if m:
                try:
                    self._send_json({"apps": network_devices.manager.apps(m.group(1))})
                except network_devices.DeviceError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/spotify/status":
                self._send_json(spotify_api.client.status())
                return
            if parsed.path in ("/api/spotify/player", "/api/spotify/search", "/api/spotify/library"):
                self._spotify_get(parsed)
                return
            if parsed.path == "/api/spotify/login":
                origin = (parse_qs(parsed.query).get("origin") or [""])[0]
                try:
                    url = spotify_api.client.login_url(origin)
                except spotify_api.SpotifyError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._redirect(url)
                return
            if parsed.path == "/api/spotify/callback":
                q = parse_qs(parsed.query)
                result = "ok"
                if q.get("error"):
                    result = q["error"][0]
                else:
                    try:
                        spotify_api.client.finish_login((q.get("code") or [""])[0], (q.get("state") or [""])[0])
                    except spotify_api.SpotifyError as exc:
                        result = str(exc)
                self._redirect("/?" + urlencode({"spotify": result}))
                return
            if parsed.path == "/api/bluetooth":
                self._send_json(audio_devices.bluetooth.status())
                return
            if parsed.path == "/api/agents":
                from cassandra.agents_bridge import bridge  # noqa: PLC0415

                self._send_json(bridge.catalog())
                return
            if parsed.path in ("/api/maestro-status", "/api/orchestrator-status", "/api/web-agent-status"):  # nomes antigos
                from skills.web_search.skill import _client as maestro_client

                status = maestro_client.status()
                agents = []
                if status["connected"]:
                    try:
                        agents = [
                            {k: a.get(k) for k in ("name", "status", "enabled", "tagline")}
                            for a in maestro_client._link.agents()
                        ]
                    except Exception:  # noqa: BLE001 — a lista é só informativa
                        agents = []
                self._send_json({**status, "agents": agents})
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

            if parsed.path == "/api/audio/volume":
                # {volume: 0-100} | {delta: +-N} | {muted: bool} (podem vir juntos)
                data = self._read_json_body()
                try:
                    if "volume" in data:
                        audio_devices.set_volume(int(data["volume"]))
                    elif "delta" in data:
                        audio_devices.change_volume(int(data["delta"]))
                except (TypeError, ValueError):
                    self._send_json({"error": "volume/delta must be numbers"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if "muted" in data:
                    audio_devices.set_mute(bool(data["muted"]))
                self._send_json(audio_devices.audio_status())
                return

            if parsed.path == "/api/audio/output":
                try:
                    sink_id = int(self._read_json_body().get("id"))
                except (TypeError, ValueError):
                    self._send_json({"error": "id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not audio_devices.set_output(sink_id):
                    self._send_json({"error": "Saída de áudio não encontrada."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(audio_devices.audio_status())
                return

            if parsed.path.startswith("/api/bluetooth/"):
                bt = audio_devices.bluetooth
                action = parsed.path[len("/api/bluetooth/"):]
                data = self._read_json_body()
                if not bt.available():
                    self._send_json({"error": "Bluetooth indisponível neste aparelho."}, status=HTTPStatus.CONFLICT)
                    return
                if action == "power":
                    bt.set_power(bool(data.get("on")))
                elif action == "scan":
                    if not bt.start_scan(data.get("seconds")):
                        self._send_json({"error": "Já existe uma busca ou conexão em andamento."}, status=HTTPStatus.CONFLICT)
                        return
                elif action == "scan/stop":
                    bt.stop_scan()
                elif action in ("connect", "disconnect", "forget"):
                    mac = audio_devices.valid_mac(str(data.get("mac", "")))
                    if not mac:
                        self._send_json({"error": "mac inválido"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    if action == "connect" and not bt.start_connect(mac):
                        self._send_json({"error": "Já existe uma conexão em andamento."}, status=HTTPStatus.CONFLICT)
                        return
                    if action == "disconnect":
                        bt.disconnect(mac)
                    if action == "forget":
                        bt.forget(mac)
                else:
                    self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(bt.status())
                return

            m = re.match(r"^/api/btaudio/([0-9A-Fa-f:]{17})$", parsed.path)
            if m:
                mac, data = m.group(1), self._read_json_body()
                try:
                    if "volume" in data:
                        bt_audio.set_volume(mac, int(data["volume"]))
                    if "muted" in data:
                        bt_audio.set_mute(mac, bool(data["muted"]))
                    if data.get("output"):
                        bt_audio.use_as_output(mac)
                    if any(k in data for k in ("eq_enabled", "bass", "treble", "preset")):
                        bt_audio.set_eq(mac, enabled=data.get("eq_enabled"), bass=data.get("bass"),
                                        treble=data.get("treble"), preset=data.get("preset"))
                    self._send_json(bt_audio.state(mac))
                except (TypeError, ValueError) as exc:
                    self._send_json({"error": f"valor inválido: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 — caixa desconectada, filtro que não subiu...
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
                return

            if parsed.path.startswith("/api/devices/"):
                self._devices_post(parsed.path[len("/api/devices/"):], self._read_json_body())
                return

            if parsed.path.startswith("/api/spotify/"):
                self._spotify_post(parsed.path[len("/api/spotify/"):], self._read_json_body())
                return

            if parsed.path == "/api/system/restart":
                # Responde antes e reinicia o serviço logo depois (o systemd sobe a Cassandra de novo).
                self._send_json({"ok": True, "message": "Reiniciando…"})

                def _restart() -> None:
                    time.sleep(0.8)
                    try:
                        subprocess.run(["systemctl", "--user", "--no-block", "restart", "cassandra-assistant"],
                                       timeout=10, check=True, capture_output=True)
                    except Exception:  # noqa: BLE001 — fora do serviço (ex.: rodando à mão): só encerra
                        os._exit(0)

                Thread(target=_restart, daemon=True).start()
                return

            if parsed.path == "/api/speak":
                # Aviso falado na casa: o texto exato, sem passar pelo LLM (ex.: o maestro avisando algo).
                text = str(self._read_json_body().get("text", "")).strip()
                if not text:
                    self._send_json({"error": "text is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if len(text) > 1000:
                    self._send_json({"error": "text too long (max 1000 chars)"}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(assistant.announce(text))
                return

            if parsed.path in ("/api/habits/save", "/api/habits/remove", "/api/habits/log"):
                from cassandra import habits  # noqa: PLC0415

                data = self._read_json_body()
                try:
                    if parsed.path.endswith("/save"):
                        habits.save(data)
                    elif parsed.path.endswith("/remove"):
                        habits.remove(str(data.get("id", "")))
                    else:
                        habits.log(str(data.get("id", "")), data.get("date"), amount=data.get("amount"),
                                   delta=data.get("delta"), toggle=bool(data.get("toggle")))
                except KeyError:
                    self._send_json({"error": "Hábito não encontrado."}, status=HTTPStatus.NOT_FOUND)
                    return
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    year = int(data.get("year") or 0)
                except (TypeError, ValueError):
                    year = 0
                self._send_json(habits.overview(year or None))
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

            if parsed.path == "/api/routines/add":
                data = self._read_json_body()
                name = str(data.get("name", "")).strip()
                trigger = data.get("trigger", {})
                actions = data.get("actions", [])
                if not name or not actions:
                    self._send_json({"error": "name and actions are required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                routine = assistant.add_routine(name, trigger, actions)
                self._send_json({"routine": routine, "routines": assistant.get_routines()})
                return

            if parsed.path == "/api/routines/remove":
                data = self._read_json_body()
                assistant.remove_routine(str(data.get("id", "")))
                self._send_json({"routines": assistant.get_routines()})
                return

            if parsed.path == "/api/routines/toggle":
                data = self._read_json_body()
                assistant.toggle_routine(str(data.get("id", "")), bool(data.get("enabled", True)))
                self._send_json({"routines": assistant.get_routines()})
                return

            if parsed.path == "/api/routines/run":
                data = self._read_json_body()
                ok = assistant.run_routine(str(data.get("id", "")))
                self._send_json({"ok": ok})
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
                date_ymd = str(data.get("date_ymd") or "").strip() or None
                raw_dom = data.get("day_of_month")
                try:
                    day_of_month = int(raw_dom) if raw_dom not in (None, "") else None
                    assistant.add_alarm(
                        time_hhmm=time_hhmm,
                        recurring_daily=recurring_daily,
                        label=label,
                        days_of_week=days_of_week,
                        date_ymd=date_ymd,
                        day_of_month=day_of_month,
                    )
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

            if parsed.path == "/api/agents/access":
                from cassandra.agents_bridge import bridge  # noqa: PLC0415

                data = self._read_json_body()
                name = str(data.get("name", "")).strip()
                if not name:
                    self._send_json({"error": "name is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                bridge.set_allowed(name, bool(data.get("allowed")))
                self._send_json(bridge.catalog())
                return

            if parsed.path == "/api/timers/cancel":
                name = str(self._read_json_body().get("name", "")).strip()
                assistant.timer_manager.cancel(name)
                self._send_json({"timers": assistant.timer_manager.snapshot(), "now": time.time()})
                return

            if parsed.path == "/api/conversation":
                self._send_json(assistant.set_conversation_mode(bool(self._read_json_body().get("active"))))
                return

            if parsed.path == "/api/alarms/stop":
                assistant.stop_alarm_ringing()
                self._send_json({"alarm_ringing": assistant.is_alarm_ringing()})
                return

            if parsed.path == "/api/settings":
                data = self._read_json_body()
                self._send_json(assistant.save_ui_settings(data))
                return

            if parsed.path == "/api/settings/reset":
                self._send_json(assistant.reset_ui_settings())
                return

            if parsed.path == "/api/calendar/configure":
                data = self._read_json_body()
                url = str(data.get("url", "")).strip()
                username = str(data.get("username", "")).strip()
                password = str(data.get("password", ""))
                if not url or not username or not password:
                    self._send_json({"error": "url, username and password are required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                result = assistant.configure_calendar(url, username, password)
                self._send_json(result)
                return

            if parsed.path == "/api/calendar/disconnect":
                assistant.disconnect_calendar()
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/agenda/events/add":
                data = self._read_json_body()
                title = str(data.get("title", "")).strip()
                date_str = str(data.get("date", "")).strip()
                start_str = str(data.get("start", "")).strip()
                end_str = str(data.get("end", "")).strip()
                description = str(data.get("description", "")).strip()
                if not title or not date_str or not start_str or not end_str:
                    self._send_json({"error": "title, date, start and end are required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    start_iso = f"{date_str}T{start_str}"
                    end_iso = f"{date_str}T{end_str}"
                    event = assistant.create_calendar_event(title, start_iso, end_iso, description)
                    if event is None:
                        self._send_json({"error": "Falha ao criar evento no calendário"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                        return
                    self._send_json({"event": event})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            if parsed.path == "/api/agenda/events/delete":
                data = self._read_json_body()
                event_id = str(data.get("event_id", "")).strip()
                if not event_id:
                    self._send_json({"error": "event_id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                ok = assistant.delete_calendar_event(event_id)
                self._send_json({"ok": ok})
                return

            if parsed.path == "/api/llm":
                # Mesmo formato do maestro/editor: campos parciais; chave vazia/omitida nunca apaga a salva.
                try:
                    result = llm_settings.update(self._read_json_body())
                    assistant.voice_output.reset_failures()  # chave/voz nova: tenta o Azure de novo na hora
                    self._send_json(result)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:
            # PUT /api/llm, como nos outros sistemas (maestro, editor, web-agent).
            if urlparse(self.path).path == "/api/llm":
                self.do_POST()
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
    bt_audio.start()  # religa o equalizador da caixa Bluetooth (se estava ligado) e vigia a conexão
    print(f"Web chat running at http://{host}:{port}")
    return server


def main() -> None:
    assistant = CassandraAssistant()
    start_web_server(assistant)
    assistant.run()


if __name__ == "__main__":
    main()
