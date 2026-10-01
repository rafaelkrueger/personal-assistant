/* persona.js — identidade visual dos agentes (rosto, nome, cores).
 *
 * CÓPIA CANÔNICA: orchestrator/static/persona.js. Cada agente tem uma cópia
 * igual (ver orchestrator/plugin/sync_copies.py) — edite só a canônica e rode
 * `python plugin/sync_copies.py`.
 *
 * Uso na página de qualquer agente:
 *   <script src="persona.js"></script>
 *   <span data-agent-face="editor" data-size="44"></span>   (montado sozinho)
 *   AgentPersona.face("web-agent", { size: 40, state: "is-working" })  -> HTML
 *   AgentPersona.meta("ide")  -> { title: "Kode", role: "IDE", face, c, c2, ink, rgb }
 *   AgentPersona.mount(root)  -> (re)monta os [data-agent-face] dentro de root
 *
 * state: "" (parado), "is-working" (trabalhando: brilha, balança, olha em volta),
 * "is-off" (desligado: cinza, olhos fechados) ou "is-sad" (erro).
 * A classe .ag-<face> (ag-maestro, ag-editor, ag-web, ag-ide, ag-home, ag-health)
 * define --c, --c2, --c-ink e --c-rgb para a página pintar o resto com a cor do agente.
 */
(function () {
  "use strict";

  const PERSONAS = {
    maestro: { title: "Maestro", role: "Líder da orquestra", face: "maestro", leader: true, c: "#9aaeff", c2: "#c4a1ff", ink: "#0d0a22", rgb: "154,174,255" },
    editor: { title: "Frame", role: "Editor de vídeo", face: "editor", c: "#fb7185", c2: "#f472b6", ink: "#23070f", rgb: "251,113,133" },
    "web-agent": { title: "Orbit", role: "Web agent", face: "web", c: "#5eead4", c2: "#22d3ee", ink: "#03282b", rgb: "94,234,212" },
    ide: { title: "Kode", role: "IDE", face: "ide", c: "#c084fc", c2: "#8b5cf6", ink: "#1c0b33", rgb: "192,132,252" },
    "personal-assistant": { title: "Cassandra", role: "Assistente pessoal", face: "home", c: "#fb923c", c2: "#f472b6", ink: "#4a1a06", rgb: "251,146,60" },
    health: { title: "Pulse", role: "Saúde", face: "health", c: "#60a5fa", c2: "#34d399", ink: "#062a3a", rgb: "96,165,250" },
  };

  // Rostos em SVG (viewBox 64×64). Classes f-* são animadas pelo CSS abaixo:
  // f-eye pisca, f-eyes olha em volta quando trabalha, e cada rosto tem o seu
  // detalhe (halo e coroa, claquete, satélite, cursor, brilho, batimento).
  const FACES = {
    maestro: `
      <circle class="f-halo" cx="32" cy="35" r="29.5" fill="none" stroke="#fcd34d" stroke-width="1.4" stroke-dasharray="2 5" opacity=".8"/>
      <g class="f-crown">
        <path fill="url(#ap-crown-gold)" d="M19 16.5 L20.5 5.5 L26.5 11.5 L32 3 L37.5 11.5 L43.5 5.5 L45 16.5 Z"/>
        <circle cx="32" cy="3.6" r="1.7" fill="#fff6d6"/><circle cx="20.6" cy="5.6" r="1.3" fill="#fff6d6"/><circle cx="43.4" cy="5.6" r="1.3" fill="#fff6d6"/>
      </g>
      <path class="f-body" fill="url(#ap-skin-maestro)" d="M32 14 L50 21 Q54 22.6 54 27 V41 Q54 46 50 49 L36 57.5 Q32 60 28 57.5 L14 49 Q10 46 10 41 V27 Q10 22.6 14 21 Z"/>
      <rect x="16" y="28" width="32" height="14" rx="7" fill="#0d0a22"/>
      <g class="f-eyes"><rect class="f-eye" x="21.5" y="31.5" width="7" height="7" rx="3.5" fill="#fde68a"/><rect class="f-eye" x="35.5" y="31.5" width="7" height="7" rx="3.5" fill="#fde68a"/></g>
      <path d="M27 48.5 Q32 52.2 37 48.5" fill="none" stroke="#0d0a22" stroke-width="2.2" stroke-linecap="round"/>`,
    editor: `
      <rect class="f-body" x="8" y="15" width="48" height="42" rx="12" fill="url(#ap-skin-editor)"/>
      <g class="f-clap"><rect x="9" y="6" width="46" height="9" rx="2.5" fill="#23070f"/><path d="M17 6 L13 15 M27 6 L23 15 M37 6 L33 15 M47 6 L43 15" stroke="#ffe4ea" stroke-width="3"/></g>
      <g class="f-eyes">
        <g class="f-eye"><circle cx="23" cy="33" r="6.5" fill="#23070f"/><circle cx="23" cy="33" r="2.8" fill="#fff"/><circle cx="21.4" cy="31.4" r="1" fill="#fff" opacity=".7"/></g>
        <g class="f-eye"><circle cx="41" cy="33" r="6.5" fill="#23070f"/><circle cx="41" cy="33" r="2.8" fill="#fff"/><circle cx="39.4" cy="31.4" r="1" fill="#fff" opacity=".7"/></g>
      </g>
      <rect x="26" y="43.5" width="12" height="3.2" rx="1.6" fill="#23070f"/>
      <g fill="#23070f" opacity=".3"><rect x="14" y="51" width="4" height="3" rx=".8"/><rect x="22" y="51" width="4" height="3" rx=".8"/><rect x="30" y="51" width="4" height="3" rx=".8"/><rect x="38" y="51" width="4" height="3" rx=".8"/><rect x="46" y="51" width="4" height="3" rx=".8"/></g>`,
    web: `
      <g class="f-orbit"><ellipse cx="32" cy="34" rx="30" ry="9.5" transform="rotate(-20 32 34)" fill="none" stroke="#5eead4" stroke-width="1.8" opacity=".6"/></g>
      <path d="M32 14 V7" stroke="#5eead4" stroke-width="2" stroke-linecap="round"/>
      <circle class="f-blip" cx="32" cy="5.4" r="2.8" fill="#a5f3fc"/>
      <circle class="f-body" cx="32" cy="34" r="20" fill="url(#ap-skin-web)"/>
      <g class="f-eyes">
        <g class="f-eye"><ellipse cx="25" cy="32" rx="4.2" ry="5.2" fill="#03282b"/><circle cx="26.4" cy="30.2" r="1.5" fill="#fff"/></g>
        <g class="f-eye"><ellipse cx="39" cy="32" rx="4.2" ry="5.2" fill="#03282b"/><circle cx="40.4" cy="30.2" r="1.5" fill="#fff"/></g>
      </g>
      <path d="M27 41.5 Q32 45.5 37 41.5" fill="none" stroke="#03282b" stroke-width="2.2" stroke-linecap="round"/>
      <circle class="f-sat" cx="60" cy="24" r="2.4" fill="#e0fffa"/>`,
    ide: `
      <rect class="f-body" x="7" y="11" width="50" height="44" rx="9" fill="url(#ap-skin-ide)"/>
      <path d="M16 11 H48 A9 9 0 0 1 57 20 V21 H7 V20 A9 9 0 0 1 16 11 Z" fill="#1c0b33" opacity=".88"/>
      <circle cx="14" cy="16" r="1.7" fill="#fb7185"/><circle cx="19.5" cy="16" r="1.7" fill="#fbbf24"/><circle cx="25" cy="16" r="1.7" fill="#34d399"/>
      <g class="f-eyes">
        <path class="f-eye" d="M19 29 L25 33 L19 37" fill="none" stroke="#1c0b33" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <rect class="f-cursor" x="39" y="28.5" width="6" height="9" rx="1.2" fill="#1c0b33"/>
      </g>
      <path d="M26.5 46 H37.5" stroke="#1c0b33" stroke-width="2.6" stroke-linecap="round"/>
      <rect x="25" y="56" width="14" height="3" rx="1.5" fill="#8b5cf6" opacity=".7"/>`,
    home: `
      <path class="f-spark" fill="#fde68a" d="M49 3 L50.5 7 L54.5 8.5 L50.5 10 L49 14 L47.5 10 L43.5 8.5 L47.5 7 Z"/>
      <path class="f-body" fill="url(#ap-skin-home)" d="M32 12 C45 12 55 20 55.5 33 C56 46 46 56.5 32 56.5 C18 56.5 8 46 8.5 33 C9 20 19 12 32 12 Z"/>
      <path class="f-gem" d="M32 16 L35.8 20.6 L32 25.2 L28.2 20.6 Z" fill="#fff4e0" stroke="#7c2d12" stroke-width="1.1"/>
      <g class="f-eyes">
        <path class="f-eye" d="M19.5 35 Q23.5 30 27.5 35" fill="none" stroke="#4a1a06" stroke-width="2.6" stroke-linecap="round"/>
        <path class="f-eye" d="M36.5 35 Q40.5 30 44.5 35" fill="none" stroke="#4a1a06" stroke-width="2.6" stroke-linecap="round"/>
      </g>
      <ellipse cx="18.5" cy="41.5" rx="3.6" ry="2.2" fill="#ff5d7a" opacity=".45"/><ellipse cx="45.5" cy="41.5" rx="3.6" ry="2.2" fill="#ff5d7a" opacity=".45"/>
      <path d="M28.5 44 Q32 47.8 35.5 44" fill="none" stroke="#4a1a06" stroke-width="2.2" stroke-linecap="round"/>`,
    health: `
      <path class="f-body" fill="url(#ap-skin-health)" d="M32 57 C15 45 7 35.5 7 25 C7 15.5 13.8 9 22 9 C26.6 9 30 11.4 32 14.5 C34 11.4 37.4 9 42 9 C50.2 9 57 15.5 57 25 C57 35.5 49 45 32 57 Z"/>
      <g class="f-eyes">
        <g class="f-eye"><circle cx="23" cy="26" r="3.7" fill="#062a3a"/><circle cx="24.2" cy="24.8" r="1.2" fill="#fff"/></g>
        <g class="f-eye"><circle cx="41" cy="26" r="3.7" fill="#062a3a"/><circle cx="42.2" cy="24.8" r="1.2" fill="#fff"/></g>
      </g>
      <path class="f-ecg" d="M14 36 H22.5 L25.5 31 L30 42 L33.5 34 L35.5 37 H50" pathLength="100" fill="none" stroke="#062a3a" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
      <g class="f-badge"><circle cx="51" cy="11" r="6" fill="#fff"/><path d="M51 7.8 V14.2 M47.8 11 H54.2" stroke="#ef4444" stroke-width="2.4" stroke-linecap="round"/></g>`,
    generic: `
      <circle class="f-body" cx="32" cy="33" r="22" fill="#5c6680"/>
      <g class="f-eyes"><circle class="f-eye" cx="25" cy="31" r="3.5" fill="#0b0e1a"/><circle class="f-eye" cx="39" cy="31" r="3.5" fill="#0b0e1a"/></g>
      <path d="M26 41 H38" stroke="#0b0e1a" stroke-width="2.4" stroke-linecap="round"/>`,
  };

  const DEFS = `<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true" id="ap-defs">
<linearGradient id="ap-skin-maestro" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#c9d3ff"/><stop offset="55%" stop-color="#8da2ff"/><stop offset="100%" stop-color="#a77bff"/>
  </linearGradient>
  <linearGradient id="ap-crown-gold" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#fff1b8"/><stop offset="100%" stop-color="#f5b73b"/>
  </linearGradient>
  <linearGradient id="ap-skin-editor" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#ffb4c0"/><stop offset="100%" stop-color="#f0507a"/>
  </linearGradient>
  <linearGradient id="ap-skin-web" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#b6fff0"/><stop offset="100%" stop-color="#1fc8d8"/>
  </linearGradient>
  <linearGradient id="ap-skin-ide" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#e2c2ff"/><stop offset="100%" stop-color="#8b5cf6"/>
  </linearGradient>
  <linearGradient id="ap-skin-home" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#ffd3a8"/><stop offset="100%" stop-color="#fb7d3c"/>
  </linearGradient>
  <linearGradient id="ap-skin-health" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="#a7f3d0"/><stop offset="100%" stop-color="#3b9cf6"/>
  </linearGradient>
</svg>`;

  const CSS = `  .ag-maestro { --c: #9aaeff; --c2: #c4a1ff; --c-ink: #0d0a22; --c-rgb: 154,174,255; }
  .ag-editor  { --c: #fb7185; --c2: #f472b6; --c-ink: #23070f; --c-rgb: 251,113,133; }
  .ag-web     { --c: #5eead4; --c2: #22d3ee; --c-ink: #03282b; --c-rgb: 94,234,212; }
  .ag-ide     { --c: #c084fc; --c2: #8b5cf6; --c-ink: #1c0b33; --c-rgb: 192,132,252; }
  .ag-home    { --c: #fb923c; --c2: #f472b6; --c-ink: #4a1a06; --c-rgb: 251,146,60; }
  .ag-health  { --c: #60a5fa; --c2: #34d399; --c-ink: #062a3a; --c-rgb: 96,165,250; }
  .ag-generic { --c: #8b95b2; --c2: #5c6680; --c-ink: #0b0e1a; --c-rgb: 139,149,178; }
  :root { --gold: #fcd34d; }

  .ap-face {
    width: var(--s); height: var(--s); flex: none; display: inline-grid; position: relative;
    filter: drop-shadow(0 4px 10px rgba(var(--c-rgb), .3));
    animation: faceFloat 6s ease-in-out infinite;
    transition: filter .3s, opacity .3s;
  }
  .ap-face svg { width: 100%; height: 100%; display: block; overflow: visible; }
  .ap-face .f-eye { transform-box: fill-box; transform-origin: center; animation: faceBlink 5.2s infinite; }
  .ap-face.ag-editor .f-eye { animation-delay: .9s; }
  .ap-face.ag-web .f-eye { animation-delay: 1.7s; animation-duration: 4.4s; }
  .ap-face.ag-ide .f-eye { animation-delay: 2.4s; }
  .ap-face.ag-home .f-eye { animation-delay: 3.1s; animation-duration: 6s; }
  .ap-face.ag-health .f-eye { animation-delay: .4s; animation-duration: 4.8s; }
  .ap-face .f-eyes { transition: transform .3s; }

  .ap-face .f-halo { transform-origin: 32px 35px; animation: faceSpin 24s linear infinite; }
  .ap-face .f-crown { transform-origin: 32px 16px; animation: crownBob 3.4s ease-in-out infinite; }
  .ap-face .f-clap { transform-origin: 9px 15px; }
  .ap-face .f-blip { transform-box: fill-box; transform-origin: center; animation: blip 2.2s ease-in-out infinite; }
  .ap-face .f-sat { transform-origin: 32px 34px; animation: faceSpin 10s linear infinite; }
  .ap-face .f-orbit { transform-origin: 32px 34px; }
  .ap-face .f-cursor { animation: cursorBlink 1.05s steps(1) infinite; }
  .ap-face .f-spark { transform-box: fill-box; transform-origin: center; animation: twinkle 2.8s ease-in-out infinite; }
  .ap-face .f-ecg { stroke-dasharray: 100 100; animation: ecg 2.6s linear infinite; }
  .ap-face.ag-health .f-body { transform-origin: 32px 33px; animation: heartBeat 2.6s ease-in-out infinite; }

  /* Trabalhando: brilha, balança, olha em volta, e cada um tem seu tique. */
  .ap-face.is-working { animation: faceBob 1.1s ease-in-out infinite; filter: drop-shadow(0 0 12px rgba(var(--c-rgb), .8)); }
  .ap-face.is-working .f-eyes { animation: faceLook 2.2s ease-in-out infinite; }
  .ap-face.is-working .f-halo { animation-duration: 3.5s; }
  .ap-face.is-working .f-clap { animation: clap .8s ease-in-out infinite; }
  .ap-face.is-working .f-sat { animation-duration: 1.8s; }
  .ap-face.is-working .f-orbit { animation: faceSpin 6s linear infinite; }
  .ap-face.is-working .f-cursor { animation-duration: .45s; }
  .ap-face.is-working .f-ecg, .ap-face.is-working.ag-health .f-body { animation-duration: 1s; }
  .ap-face.is-working .f-spark { animation-duration: 1s; }
  /* Desligado/offline: cinza, olhos fechados. Triste: olhos pra baixo. */
  .ap-face.is-off { filter: grayscale(.85) brightness(.9); opacity: .7; animation: none; }
  .ap-face.is-off .f-eye { animation: none; transform: scaleY(.15); }
  .ap-face.is-off * { animation-play-state: paused; }
  .ap-face.is-sad .f-eyes { transform: translateY(2px); }

  @keyframes faceBlink { 0%, 93%, 100% { transform: scaleY(1); } 95.5% { transform: scaleY(.1); } }
  @keyframes faceFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
  @keyframes faceBob { 0%, 100% { transform: translateY(0) rotate(0); } 25% { transform: translateY(-2px) rotate(-4deg); } 75% { transform: translateY(-1px) rotate(4deg); } }
  @keyframes faceLook { 0%, 100% { transform: translateX(0); } 30% { transform: translateX(-2.4px); } 65% { transform: translateX(2.4px); } }
  @keyframes faceSpin { to { transform: rotate(360deg); } }
  @keyframes crownBob { 0%, 100% { transform: translateY(0) rotate(0); } 50% { transform: translateY(-1.2px) rotate(-3deg); } }
  @keyframes clap { 0%, 55%, 100% { transform: rotate(0); } 22% { transform: rotate(-16deg); } }
  @keyframes blip { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.35); opacity: .55; } }
  @keyframes cursorBlink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: .15; } }
  @keyframes twinkle { 0%, 100% { transform: scale(1) rotate(0); opacity: 1; } 50% { transform: scale(.55) rotate(45deg); opacity: .6; } }
  @keyframes ecg { 0% { stroke-dashoffset: 100; } 55% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: -100; } }
  @keyframes heartBeat { 0%, 30%, 60%, 100% { transform: scale(1); } 12% { transform: scale(1.06); } 42% { transform: scale(1.04); } }
  @media (prefers-reduced-motion: reduce) {
    .ap-face, .ap-face * { animation: none !important; }
  }

  .ap-leader-tag {
    display: inline-block; font: 700 9px ui-monospace, "IBM Plex Mono", monospace; letter-spacing: .12em; text-transform: uppercase;
    color: #1a1206; background: linear-gradient(180deg, #fff1b8, #f5b73b);
    padding: 2px 7px; border-radius: 999px; vertical-align: middle;
  }
`;

  function meta(name) {
    return PERSONAS[name] || { title: name || "?", role: "", face: "generic", c: "#8b95b2", c2: "#5c6680", ink: "#0b0e1a", rgb: "139,149,178" };
  }

  function skin(name) {
    return "ag-" + meta(name).face;
  }

  function face(name, opts) {
    const o = opts || {};
    const size = o.size || 36;
    const m = meta(name);
    const kind = FACES[m.face] ? m.face : "generic";
    const cls = ["ap-face", "face", "ag-" + kind];
    if (m.leader) cls.push("is-leader");
    if (o.state) cls.push(o.state);
    return `<span class="${cls.join(" ")}" style="--s:${size}px" aria-hidden="true"><svg viewBox="0 0 64 64">${FACES[kind]}</svg></span>`;
  }

  function mount(root) {
    (root || document).querySelectorAll("[data-agent-face]").forEach((el) => {
      const html = face(el.getAttribute("data-agent-face"), {
        size: Number(el.getAttribute("data-size")) || 36,
        state: el.getAttribute("data-state") || "",
      });
      if (el._apHtml !== html) { el.innerHTML = html; el._apHtml = html; }
    });
  }

  function install() {
    if (!document.getElementById("ap-css")) {
      const style = document.createElement("style");
      style.id = "ap-css";
      style.textContent = CSS;
      document.head.appendChild(style);
    }
    if (document.body && !document.getElementById("ap-defs")) {
      document.body.insertAdjacentHTML("afterbegin", DEFS);
    }
  }

  install();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { install(); mount(); });
  } else {
    mount();
  }

  window.AgentPersona = { PERSONAS, meta, skin, face, mount };
})();
