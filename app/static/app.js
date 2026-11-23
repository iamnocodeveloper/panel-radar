"use strict";
const S = {
  tab: "resumen", state: null, convs: null, envios: null,
  kLine: "", kZona: "", kShow: {}, cQ: "", cLine: "",
};
const ESTADOS = [
  ["nuevo", "Nuevo"], ["contactado", "Contactado"], ["respondio", "Respondió"],
  ["reunion", "Reunión"], ["cliente", "Cliente"], ["descartado", "Descartado"],
  ["sin_ficha", "Sin ficha en Radar"],
];
const ICON = {
  radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 12l6-3"/><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L3 21l1.1-3.3A8.4 8.4 0 1 1 21 11.5z"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>',
  out: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12h13"/><path d="M12 5l7 7-7 7"/></svg>',
  in: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 12H7"/><path d="M12 5l-7 7 7 7"/></svg>',
  wait: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 3 4.2 2 2 0 0 1 5 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.9a2 2 0 0 1-.5 2.1L9 9.9a16 16 0 0 0 6 6l1.2-1.2a2 2 0 0 1 2.1-.5c.9.3 1.9.6 2.9.7a2 2 0 0 1 1.8 2z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  bars: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
};
const $ = (q) => document.querySelector(q);
const el = (h) => { const t = document.createElement("template"); t.innerHTML = h.trim(); return t.content.firstChild; };
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const pct = (n) => (n == null ? "—" : n + "%");

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 3200);
}
function lineBadge(line) {
  if (!line) return "";
  return `<span class="pill ${line === "principal" ? "l1" : "l2"}">${esc(line)}</span>`;
}

// ---------------------------------------------------------------- RESÚMEN
function renderResumen() {
  const r = S.state.resumen, ln = r.lineas;
  const envTotal = Object.values(r.enviados_hoy).reduce((a, b) => a + b, 0);
  const respTotal = Object.values(r.respuestas_hoy).reduce((a, b) => a + b, 0);
  const kpis = [
    ["Enviados hoy", envTotal, "acc", ICON.send, Object.entries(r.enviados_hoy).map(([k, v]) => k + ": " + v).join(" · ")],
    ["Respuestas hoy", respTotal, "ok", ICON.in, "mensajes recibidos de clientes"],
    ["Esperando respuesta", r.esperando_respuesta, "warn", ICON.wait, "sin contestar todavía"],
    ["Tasa de respuesta", pct(r.tasa_respuesta), "", ICON.check, `${r.prospectos_respondieron} de ${r.prospectos_contactados} prospectos`],
    ["Clientes cerrados", r.clientes_cerrados, "ok", ICON.check, "estado: cliente"],
    ["Por contactar (cola)", r.radar.queuedNew ?? "—", "", ICON.grid, "nuevos en Radar"],
  ];
  let html = `<div class="grid kpis">` + kpis.map((k) =>
    `<div class="kpi ${k[2]}"><div class="lbl">${k[3]}${esc(k[0])}</div><div class="val">${esc(k[1])}</div><div class="sub">${esc(k[4])}</div></div>`
  ).join("") + `</div>`;

  html += `<div class="lines">` + Object.entries(ln).map(([name, s]) => {
    const ok = s.status === "WORKING";
    const dot = ok ? "ok" : (s.status === "STARTING" ? "mut" : "bad");
    const num = s.me ? s.me.split("@")[0] : "";
    return `<div class="linecard"><div class="nm"><span class="dot ${dot}"></span>${esc(cap(name))}
      <span class="st ${esc(s.status || "")}" style="margin-left:auto">${esc(s.status || "—")}</span></div>
      <div class="sub" style="color:var(--dim);font-size:12.5px;margin-top:6px">${num ? "+" + esc(num.slice(0, 4)) + " … " + esc(num.slice(-4)) : "sin datos"}</div>
      <div style="margin-top:8px;color:var(--mut);font-size:13px">Enviados hoy: <b>${r.enviados_hoy[name] || 0}</b> · Respuestas: <b>${r.respuestas_hoy[name] || 0}</b></div></div>`;
  }).join("") + `</div>`;
  return html;
}

// ---------------------------------------------------------------- KANBAN
function cardHTML(c) {
  const cv = c.conversacion || {};
  const canChange = !!c.lead_id;
  return `<div class="kcard" data-key="${esc(c.key)}">
    <div class="t">${esc(c.nombre || "—")}</div>
    ${c.zona ? `<div class="z">${esc(c.zona)}</div>` : (c.tipo ? `<div class="z">${esc(c.tipo)}</div>` : "")}
    <div class="meta">
      ${cv.line ? lineBadge(cv.line) : ""}
      ${cv.phone_last4 ? `<span class="pill">…${esc(cv.phone_last4)}</span>` : ""}
      ${cv.responded ? `<span class="pill resp">respondió</span>` : ""}
      ${c.radar_estado && c.radar_estado !== c.estado ? `<span class="pill">Radar: ${esc(c.radar_estado)}</span>` : ""}
      ${!c.lead_id ? `<span class="pill">sin ficha</span>` : ""}
    </div>
    ${cv.ultimo ? `<div class="msg">${cv.desde_cliente ? ICON.in + " " : ICON.out + " "}${esc(cv.ultimo)}${cv.media ? " [" + esc(cv.media) + "]" : ""}</div>
      <div class="date">${esc(cv.ultimo_fmt || "")}</div>` : ""}
    ${canChange ? `<button class="btn estadoBtn" data-key="${esc(c.key)}">Cambiar estado</button>
      <div class="estadoMenu hide" data-menu="${esc(c.key)}">${ESTADOS.filter(e => e[0] !== "sin_ficha").map(e => `<button data-est="${e[0]}" data-id="${esc(c.lead_id)}">${esc(e[1])}</button>`).join("")}</div>` : ""}
  </div>`;
}

function renderKanban() {
  const k = S.state.kanban;
  let cards = k.cards;
  if (S.kLine) cards = cards.filter(c => c.conversacion && c.conversacion.line === S.kLine);
  if (S.kZona) cards = cards.filter(c => (c.zona || "—") === S.kZona);

  const cols = ESTADOS.map(([id, label]) => {
    const list = cards.filter(c => c.estado === id);
    const show = S.kShow[id] || 40;
    const vis = list.slice(0, show);
    return `<div class="col"><div class="ch">${esc(label)}<span class="cnt">${list.length}</span></div>
      <div class="cc">${vis.length ? vis.map(cardHTML).join("") : '<div class="empty">—</div>'}
      ${list.length > show ? `<button class="btn more" data-estado="${id}">Mostrar más (${list.length - show})</button>` : ""}</div></div>`;
  }).join("");

  const zonas = k.zonas;
  return `<div class="filters">
      <label class="f">Línea<select id="kLine"><option value="">Todas</option><option value="principal">principal</option><option value="segunda">segunda</option></select></label>
      <label class="f">Zona<select id="kZona"><option value="">Todas</option>${zonas.map(z => `<option>${esc(z)}</option>`).join("")}</select></label>
      <span style="color:var(--dim);font-size:12.5px;margin-left:auto">${cards.length} tarjetas · ${k.counts.nuevo || 0} nuevos en cola</span>
    </div>
    <div class="kanban">${cols}</div>`;
}

// ---------------------------------------------------------------- CONVERSACIONES
function renderConv() {
  const items = S.convs.items;
  const rows = items.map(it => `<tr data-line="${esc(it.line)}" data-id="${esc(it.chat_id)}">
      <td>${esc(it.lead_nombre || it.nombre)}</td>
      <td>${lineBadge(it.line)}</td>
      <td><span class="badge ${esc(it.estado)}">${esc(cap(it.estado.replace("_", " ")))}</span></td>
      <td class="msg">${it.desde_cliente ? "↩ " : "→ "}${esc(it.ultimo || "")}${it.media ? " [" + esc(it.media) + "]" : ""}</td>
      <td>${esc(it.ultimo_fmt || "—")}</td>
      <td>${it.sent} / ${it.recv}</td>
      <td><button class="btn" style="padding:4px 9px">Ver hilo</button></td>
    </tr>`).join("");
  return `<div class="filters">
      <label class="f">Buscar<input type="search" id="cQ" placeholder="negocio o últimos 4 dígitos" value="${esc(S.cQ)}"></label>
      <label class="f">Línea<select id="cLine"><option value="">Todas</option><option value="principal">principal</option><option value="segunda">segunda</option></select></label>
      <span style="color:var(--dim);font-size:12.5px;margin-left:auto">${items.length} conversaciones</span>
    </div>
    <div class="card"><div class="tblwrap"><table>
      <thead><tr><th>Negocio</th><th>Línea</th><th>Estado</th><th>Último mensaje</th><th>Cuándo</th><th>Env/Rec</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="empty">Sin conversaciones</td></tr>'}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- ENVÍOS
function renderEnvios() {
  const e = S.envios;
  const max = Math.max(1, ...e.dias.map(d => e.lineas.reduce((a, l) => a + (e.series[l]?.[d] || 0), 0)));
  const bars = e.dias.map(d => {
    const total = e.lineas.reduce((a, l) => a + (e.series[l]?.[d] || 0), 0);
    const segs = e.lineas.map((l, i) => {
      const v = e.series[l]?.[d] || 0;
      const h = Math.round((v / max) * 150);
      return `<div class="seg l${i}" style="height:${h}px" title="${esc(l)}: ${v}"></div>`;
    }).join("");
    const dt = d.slice(8) + "/" + d.slice(5, 7);
    return `<div class="bar"><div style="font-size:11px;color:var(--mut)">${total || ""}</div><div class="bars">${segs}</div><div class="cap">${dt}</div></div>`;
  }).join("");
  const legend = e.lineas.map((l, i) => `<span><i class="l${i}" style="background:${i === 0 ? "#3d8bfd" : "#966eff"}"></i>${esc(l)}</span>`).join("");

  const trows = e.tabla.map(r => `<tr><td>${esc(r.fecha)}</td>${e.lineas.map(l => `<td>${r.por_linea[l] || 0}</td>`).join("")}<td><b>${r.total}</b></td></tr>`).join("");
  const last = Object.entries(e.ultimo_envio).map(([l, v]) =>
    `<div class="linecard"><div class="nm">${lineBadge(l)} último envío</div><div class="val" style="font-size:18px;margin-top:6px;color:var(--acc)">${esc(v.fmt || "—")}</div></div>`).join("");

  return `<div class="lines">${last}</div>
    <div class="card" style="margin-top:14px"><h3>${ICON.bars}Envíos por día y por línea (14 días)</h3>
      <div class="body"><div class="chart">${bars}</div><div class="legend">${legend}<span style="margin-left:auto;color:var(--dim)">máximo del período: ${max}</span></div></div></div>
    <div class="card" style="margin-top:14px"><h3>${ICON.send}Detalle por día</h3>
      <div class="tblwrap"><table><thead><tr><th>Día</th>${e.lineas.map(l => `<th>${esc(l)}</th>`).join("")}<th>Total</th></tr></thead><tbody>${trows}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- render
function render() {
  const body = $("#view");
  if (!S.state) { body.innerHTML = '<div class="empty"><span class="spin"></span> Cargando datos…</div>'; return; }
  if (S.tab === "resumen") body.innerHTML = renderResumen();
  else if (S.tab === "kanban") body.innerHTML = renderKanban();
  else if (S.tab === "conversaciones") body.innerHTML = S.convs ? renderConv() : '<div class="empty"><span class="spin"></span> Cargando…</div>';
  else if (S.tab === "envios") body.innerHTML = S.envios ? renderEnvios() : '<div class="empty"><span class="spin"></span> Cargando…</div>';
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.dataset.tab === S.tab));
  $("#updated").innerHTML = S.state ? `Actualizado ${esc(S.state.last_refresh_fmt || "—")}` : "";
  wire();
}

function wire() {
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => { S.tab = t.dataset.tab; loadTab(); });
  const kl = $("#kLine"), kz = $("#kZona");
  if (kl) { kl.value = S.kLine; kl.onchange = () => { S.kLine = kl.value; S.kShow = {}; render(); }; }
  if (kz) { kz.value = S.kZona; kz.onchange = () => { S.kZona = kz.value; S.kShow = {}; render(); }; }
  document.querySelectorAll(".more").forEach(b => b.onclick = () => { S.kShow[b.dataset.estado] = (S.kShow[b.dataset.estado] || 40) + 60; render(); });
  document.querySelectorAll(".estadoBtn").forEach(b => b.onclick = () => {
    const m = document.querySelector(`[data-menu="${b.dataset.key}"]`); if (m) m.classList.toggle("hide");
  });
  document.querySelectorAll(".estadoMenu button").forEach(b => b.onclick = () => changeEstado(b.dataset.id, b.dataset.est));
  const cQ = $("#cQ"), cL = $("#cLine");
  if (cL) { cL.value = S.cLine; cL.onchange = () => { S.cLine = cL.value; loadConv(); }; }
  if (cQ) { let h; cQ.oninput = () => { clearTimeout(h); h = setTimeout(() => { S.cQ = cQ.value; loadConv(); }, 300); }; }
  document.querySelectorAll("tbody tr[data-id]").forEach(tr => tr.onclick = (e) => openThread(tr.dataset.line, tr.dataset.id));
}

async function changeEstado(id, est) {
  try {
    const r = await api(`/api/lead/${encodeURIComponent(id)}/status`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ estado: est }),
    });
    toast(`Estado actualizado a «${est}»`);
    await loadState(); loadConv();
  } catch (e) {
    toast("No se pudo cambiar el estado: " + e.message);
  }
}

async function openThread(line, id) {
  $("#ovl").classList.add("on"); $("#drawer").classList.add("on");
  $("#dname").textContent = "Cargando…"; $("#thread").innerHTML = '<div class="empty"><span class="spin"></span></div>';
  try {
    const d = await api(`/api/chat/${encodeURIComponent(line)}/${encodeURIComponent(id)}`);
    $("#dname").textContent = d.nombre || "Conversación";
    $("#dsub").textContent = `${line} · ${d.mensajes.length} mensajes`;
    if (!d.mensajes.length) { $("#thread").innerHTML = '<div class="empty">Sin mensajes almacenados</div>'; return; }
    $("#thread").innerHTML = d.mensajes.map(m => `<div class="bub ${m.from_me ? "out" : "in"}">
        ${m.body ? esc(m.body) : ""}${m.media ? `<div class="md">[${esc(m.media)}]</div>` : ""}
        <div class="tm">${esc(m.fmt || "")} ${m.from_me ? "· enviado" : "· recibido"}</div></div>`).join("");
    $("#thread").scrollTop = $("#thread").scrollHeight;
  } catch (e) { $("#thread").innerHTML = '<div class="empty">Error al cargar el hilo</div>'; }
}

async function loadState() {
  try { S.state = await api("/api/state"); render(); } catch (e) { /* reintento por el intervalo */ }
}
async function loadConv() {
  const p = new URLSearchParams(); if (S.cQ) p.set("q", S.cQ); if (S.cLine) p.set("line", S.cLine);
  S.convs = await api("/api/conversations?" + p.toString());
  if (S.tab === "conversaciones") render();
}
async function loadEnvios() {
  S.envios = await api("/api/envios");
  if (S.tab === "envios") render();
}
async function loadTab() {
  if (!S.state) await loadState();
  if (S.tab === "conversaciones" && !S.convs) { try { await loadConv(); } catch (e) {} }
  if (S.tab === "envios" && !S.envios) { try { await loadEnvios(); } catch (e) {} }
  render();
}
async function refreshNow() {
  const b = $("#refreshBtn"); b.disabled = true; b.innerHTML = '<span class="spin"></span> Actualizando';
  try { await api("/api/refresh", { method: "POST" }); await loadState(); if (S.tab === "conversaciones") await loadConv(); if (S.tab === "envios") await loadEnvios(); toast("Datos actualizados"); }
  catch (e) { toast("Error al actualizar: " + e.message); }
  finally { b.disabled = false; b.innerHTML = ICON.refresh + " Actualizar"; }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#ovl").onclick = closeDrawer;
  $("#xBtn").onclick = closeDrawer;
  $("#refreshBtn").onclick = refreshNow;
  loadTab();
  setInterval(() => { if (S.tab === "resumen" || S.tab === "kanban") loadState(); }, 120000);
});
function closeDrawer() { $("#ovl").classList.remove("on"); $("#drawer").classList.remove("on"); }
