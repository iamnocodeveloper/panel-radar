"use strict";
const S = {
  tab: "resumen", state: null, convs: null, envios: null, graficos: null,
  kLine: "", kZona: "", kQ: "", kShow: {},
  cQ: "", cLine: "", cZona: "",
  gDias: 30,
};
const ESTADOS = [
  ["nuevo", "Nuevo"], ["contactado", "Contactado"], ["respondio", "Respondió"],
  ["interesado", "Interesado"], ["demo_enviado", "Demo enviado"],
  ["cotizacion_enviada", "Cotización enviada"], ["dijo_que_luego", "Dijo que luego"],
  ["dijo_que_no", "Dijo que no"], ["cliente", "Cliente"],
];
const ESTADO_LABEL = Object.fromEntries(ESTADOS);
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
  bars: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  funnel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 4h18l-7 8v6l-4 2v-8L3 4z"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
};
const $ = (q) => document.querySelector(q);
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const pct = (n) => (n == null ? "—" : Number(n).toFixed(1) + "%");
const nst = (e) => (ESTADO_LABEL[e] || cap((e || "").replace(/_/g, " ")));
const isoToDate = (v) => (v ? String(v).slice(0, 10) : "");

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = "HTTP " + r.status;
    try { const j = await r.json(); if (j && j.detail) msg = j.detail; } catch (e) {}
    throw new Error(msg);
  }
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
    ["Enviados hoy", envTotal, "acc", ICON.send, Object.entries(r.enviados_hoy).map(([k, v]) => k + ": " + v).join(" · ") + (r.radar.sentTodayNew != null ? ` · Radar: ${r.radar.sentTodayNew}` : "")],
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
  const key = esc(c.cliente_key || "");
  const dIn = isoToDate(c.interesado_el), dDe = isoToDate(c.demo_enviado_el), dCo = isoToDate(c.cotizacion_enviada_el);
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
    <div class="fechas">
      <span><b>Se interesó</b> ${c.interesado_fmt ? esc(c.interesado_fmt) : "—"}</span>
      <span><b>Demo enviado</b> ${c.demo_fmt ? esc(c.demo_fmt) : "—"}</span>
      <span><b>Cotización</b> ${c.cotizacion_fmt ? esc(c.cotizacion_fmt) : "—"}</span>
    </div>
    ${cv.ultimo ? `<div class="msg">${cv.desde_cliente ? ICON.in + " " : ICON.out + " "}${esc(cv.ultimo)}${cv.media ? " [" + esc(cv.media) + "]" : ""}</div>
      <div class="date">${esc(cv.ultimo_fmt || "")}</div>` : ""}
    ${c.nota ? `<div class="nota"><b>Nota:</b> ${esc(c.nota)}</div>` : ""}
    <div class="cardacts">
      <button class="ebtn" data-act="est" data-est="interesado" data-key="${key}">Interesado</button>
      <button class="ebtn" data-act="est" data-est="dijo_que_luego" data-key="${key}">Dijo que luego</button>
      <button class="ebtn" data-act="est" data-est="dijo_que_no" data-key="${key}">Dijo que no</button>
      <button class="ebtn ghost" data-act="est" data-est="" data-key="${key}" title="Quitar estado propio (volver a lo de Radar)">Auto</button>
    </div>
    <details class="edit">
      <summary>Editar nota / fechas</summary>
      <label>Nota<input type="text" class="notaIn" placeholder="nota corta…" value="${esc(c.nota || "")}"></label>
      <label>Se interesó<input type="date" class="dateIn" data-f="interesado_el" value="${esc(dIn)}"></label>
      <label>Demo enviado<input type="date" class="dateIn" data-f="demo_enviado_el" value="${esc(dDe)}"></label>
      <label>Cotización<input type="date" class="dateIn" data-f="cotizacion_enviada_el" value="${esc(dCo)}"></label>
      <button class="btn save" data-key="${key}">Guardar</button>
    </details>
  </div>`;
}

function filterCards(cards) {
  let out = cards;
  if (S.kLine) out = out.filter((c) => c.conversacion && c.conversacion.line === S.kLine);
  if (S.kZona) out = out.filter((c) => (c.zona || "—") === S.kZona);
  if (S.kQ) {
    const q = S.kQ.toLowerCase();
    out = out.filter((c) =>
      (c.nombre || "").toLowerCase().includes(q) ||
      (c.zona || "").toLowerCase().includes(q) ||
      (c.tipo || "").toLowerCase().includes(q) ||
      (c.nota || "").toLowerCase().includes(q) ||
      ((c.conversacion || {}).phone_last4 || "").includes(q)
    );
  }
  return out;
}

function renderKanban() {
  const k = S.state.kanban;
  const cards = filterCards(k.cards);
  const cols = ESTADOS.map(([id, label]) => {
    const list = cards.filter((c) => c.estado === id);
    const show = S.kShow[id] || 40;
    const vis = list.slice(0, show);
    return `<div class="col"><div class="ch">${esc(label)}<span class="cnt">${list.length}</span></div>
      <div class="cc">${vis.length ? vis.map(cardHTML).join("") : '<div class="empty">—</div>'}
      ${list.length > show ? `<button class="btn more" data-estado="${id}">Mostrar más (${list.length - show})</button>` : ""}</div></div>`;
  }).join("");
  return `<div class="filters">
      <label class="f">Línea<select id="kLine"><option value="">Todas</option><option value="principal">principal</option><option value="segunda">segunda</option></select></label>
      <label class="f">Zona<select id="kZona"><option value="">Todas</option>${k.zonas.map((z) => `<option>${esc(z)}</option>`).join("")}</select></label>
      <label class="f">Buscar<input type="search" id="kQ" placeholder="negocio, zona, nota…" value="${esc(S.kQ)}"></label>
      <span style="color:var(--dim);font-size:12.5px;margin-left:auto">${cards.length} tarjetas · ${k.counts.nuevo || 0} nuevos en cola</span>
    </div>
    <div class="kanban">${cols}</div>`;
}

// ---------------------------------------------------------------- CONVERSACIONES
function renderConv() {
  const items = S.convs.items;
  const zonas = S.state.kanban.zonas;
  const rows = items.map((it) => `<tr data-line="${esc(it.line)}" data-id="${esc(it.chat_id)}">
      <td>${esc(it.lead_nombre || it.nombre)}</td>
      <td>${lineBadge(it.line)}</td>
      <td><span class="badge ${esc(it.estado)}">${esc(nst(it.estado))}</span></td>
      <td>${esc(it.zona || "—")}</td>
      <td class="msg">${it.desde_cliente ? "↩ " : "→ "}${esc(it.ultimo || "")}${it.media ? " [" + esc(it.media) + "]" : ""}</td>
      <td>${esc(it.ultimo_fmt || "—")}</td>
      <td>${it.sent} / ${it.recv}</td>
      <td><button class="btn" style="padding:4px 9px">Ver hilo</button></td>
    </tr>`).join("");
  return `<div class="filters">
      <label class="f">Buscar<input type="search" id="cQ" placeholder="negocio, zona o últimos 4 dígitos" value="${esc(S.cQ)}"></label>
      <label class="f">Línea<select id="cLine"><option value="">Todas</option><option value="principal">principal</option><option value="segunda">segunda</option></select></label>
      <label class="f">Zona<select id="cZona"><option value="">Todas</option>${zonas.map((z) => `<option>${esc(z)}</option>`).join("")}</select></label>
      <span style="color:var(--dim);font-size:12.5px;margin-left:auto">${items.length} conversaciones</span>
    </div>
    <div class="card"><div class="tblwrap"><table>
      <thead><tr><th>Negocio</th><th>Línea</th><th>Estado</th><th>Zona</th><th>Último mensaje</th><th>Cuándo</th><th>Env/Rec</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="8" class="empty">Sin conversaciones</td></tr>'}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- ENVÍOS
function renderEnvios() {
  const e = S.envios;
  const max = Math.max(1, ...e.dias.map((d) => e.lineas.reduce((a, l) => a + (e.series[l]?.[d] || 0), 0)));
  const bars = e.dias.map((d) => {
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
  const trows = e.tabla.map((r) => `<tr><td>${esc(r.fecha)}</td>${e.lineas.map((l) => `<td>${r.por_linea[l] || 0}</td>`).join("")}<td><b>${r.total}</b></td></tr>`).join("");
  const last = Object.entries(e.ultimo_envio).map(([l, v]) =>
    `<div class="linecard"><div class="nm">${lineBadge(l)} último envío</div><div class="val" style="font-size:18px;margin-top:6px;color:var(--acc)">${esc(v.fmt || "—")}</div></div>`).join("");
  return `<div class="lines">${last}</div>
    <div class="card" style="margin-top:14px"><h3>${ICON.bars}Envíos por día y por línea (14 días)</h3>
      <div class="body"><div class="chart">${bars}</div><div class="legend">${legend}<span style="margin-left:auto;color:var(--dim)">máximo del período: ${max}</span></div></div></div>
    <div class="card" style="margin-top:14px"><h3>${ICON.send}Detalle por día</h3>
      <div class="tblwrap"><table><thead><tr><th>Día</th>${e.lineas.map((l) => `<th>${esc(l)}</th>`).join("")}<th>Total</th></tr></thead><tbody>${trows}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- GRÁFICOS
function barsList(rows, keyName) {
  if (!rows.length) return '<div class="empty">Sin datos en el período</div>';
  const max = Math.max(1, ...rows.map((r) => r.enviados));
  return `<div class="hbars">` + rows.map((r) => `<div class="hbrow">
      <span class="hbk" title="${esc(r[keyName])}">${esc(r[keyName])}</span>
      <div class="hbbar"><i style="width:${Math.round((r.enviados / max) * 100)}%"></i></div>
      <span class="hbv">${r.enviados} prosp · ${pct(r.tasa)} resp</span>
    </div>`).join("") + `</div>`;
}

function chartSVG(labels, s1, s2, rate, opts) {
  opts = opts || {};
  const w = opts.w || 760, h = opts.h || 220;
  const padL = 34, padR = 40, padT = 14, padB = 34;
  const iw = w - padL - padR, ih = h - padT - padB;
  const n = labels.length || 1;
  const max = Math.max(1, ...s1, ...s2);
  const step = iw / n;
  const bw = Math.max(2.5, Math.min(16, step * 0.32));
  let body = "";
  // rejilla
  for (let g = 0; g <= 4; g++) {
    const y = padT + (ih * g) / 4;
    const val = Math.round(max * (1 - g / 4));
    body += `<line x1="${padL}" y1="${y}" x2="${padL + iw}" y2="${y}" stroke="#2c333d" stroke-width="1"/>`;
    body += `<text x="${padL - 6}" y="${y + 3}" text-anchor="end" fill="#6b7684" font-size="9">${val}</text>`;
  }
  labels.forEach((d, i) => {
    const x = padL + i * step + step / 2;
    const h1 = Math.round((s1[i] / max) * ih);
    const h2 = Math.round((s2[i] / max) * ih);
    body += `<rect x="${(x - bw - 1).toFixed(1)}" y="${padT + ih - h1}" width="${bw.toFixed(1)}" height="${h1}" fill="#3d8bfd" rx="1.5"><title>${esc(d)} · enviados ${s1[i]}</title></rect>`;
    body += `<rect x="${(x + 1).toFixed(1)}" y="${padT + ih - h2}" width="${bw.toFixed(1)}" height="${h2}" fill="#35c98a" rx="1.5"><title>${esc(d)} · respuestas ${s2[i]}</title></rect>`;
  });
  // línea de tasa (eje 0-100 a la derecha)
  const pts = labels.map((d, i) => {
    const x = padL + i * step + step / 2;
    const y = padT + ih - Math.min(rate[i], 100) / 100 * ih;
    return [x, y];
  });
  if (pts.length) {
    body += `<polyline points="${pts.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}" fill="none" stroke="#e0a53b" stroke-width="1.6"/>`;
    body += pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.2" fill="#e0a53b"><title>${esc(labels[i])} · tasa ${rate[i]}%</title></circle>`).join("");
  }
  // etiquetas x (hasta ~9)
  const every = Math.max(1, Math.ceil(n / 9));
  labels.forEach((d, i) => {
    if (i % every) return;
    const x = padL + i * step + step / 2;
    body += `<text x="${x}" y="${h - 12}" text-anchor="middle" fill="#9aa4b2" font-size="9">${esc(d)}</text>`;
  });
  return `<div class="chartwrap"><svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" style="width:100%;min-width:660px;height:auto">${body}</svg></div>`;
}

function renderGraficos() {
  const g = S.graficos;
  if (!g) return '<div class="empty"><span class="spin"></span> Cargando…</div>';
  const k = g.kpis;
  const kpis = [
    ["Mensajes enviados", k.enviados, "acc", ICON.send, `últimos ${g.dias} días`],
    ["Mensajes recibidos", k.respuestas, "ok", ICON.in, `últimos ${g.dias} días`],
    ["Tasa de respuesta", pct(k.tasa), "", ICON.check, "prospectos que respondieron"],
    ["Interesados", k.interesados, "warn", ICON.funnel, "llegaron a interesado"],
    ["Demos enviados", k.demos, "", ICON.grid, "con demo enviado"],
    ["Cotizaciones", k.cotizaciones, "warn", ICON.bars, "propuesta enviada"],
    ["Clientes", k.clientes, "ok", ICON.check, "estado cliente en Radar"],
  ];
  let html = `<div class="filters"><span style="color:var(--mut);font-size:12.5px">Período</span>
    ${[7, 14, 30].map((d) => `<button class="btn seg ${S.gDias === d ? "primary" : ""}" data-dias="${d}">${d} días</button>`).join("")}
    <span style="margin-left:auto;color:var(--dim);font-size:12px">los KPIs del período son de ${S.gDias} días</span></div>`;
  html += `<div class="grid kpis">` + kpis.map((x) =>
    `<div class="kpi ${x[2]}"><div class="lbl">${x[3]}${esc(x[0])}</div><div class="val">${esc(x[1])}</div><div class="sub">${esc(x[4])}</div></div>`
  ).join("") + `</div>`;

  // 1. Embudo
  const fu = g.embudo, ftop = fu[0] ? fu[0].n : 0;
  html += `<div class="card" style="margin-top:16px"><h3>${ICON.funnel}Embudo de prospección</h3>
    <div class="body"><div class="funnel">` + fu.map((s, i) => {
      const w = ftop ? Math.max(2, Math.round((s.n / ftop) * 100)) : 0;
      const conv = i === 0 ? "" : `${s.n} de ${fu[i - 1].n} · ${pct(s.pct_prev)} del paso anterior`;
      return `<div class="frow"><span class="fl">${esc(s.paso)}</span>
        <div class="fbar"><i style="width:${w}%"></i><b>${s.n}</b></div>
        <span class="fv">${pct(s.pct_total)} del total${conv ? " · " + conv : ""}</span></div>`;
    }).join("") + `</div></div></div>`;

  // 2. Evolución diaria
  const dd = g.diaria;
  html += `<div class="card" style="margin-top:16px"><h3>${ICON.bars}Evolución diaria · enviados, respuestas y tasa (${g.dias} días)</h3>
    <div class="body"><div class="legend"><span><i style="background:#3d8bfd"></i>Mensajes enviados</span><span><i style="background:#35c98a"></i>Mensajes recibidos</span><span><i style="background:#e0a53b"></i>Tasa de respuesta (cohorte contactada ese día, 0-100%)</span></div>
    ${chartSVG(dd.dias.map((d) => d.slice(8) + "/" + d.slice(5, 7)), dd.enviados, dd.respuestas, dd.tasa)}</div></div>`;

  // 3. Comparativa de líneas
  const lg = g.lineas, lmax = Math.max(1, ...lg.flatMap((l) => [l.enviados, l.respuestas]));
  html += `<div class="card" style="margin-top:16px"><h3>${ICON.grid}Comparativa de líneas · prospectos contactados (${g.dias} días)</h3>
    <div class="body"><div class="linecmp">` + lg.map((l) => `<div class="lc">
        <div class="lcn">${lineBadge(l.line)}</div>
        <div class="lcb"><span>Contactados</span><div class="hbbar"><i style="width:${Math.round((l.enviados / lmax) * 100)}%"></i></div><b>${l.enviados}</b></div>
        <div class="lcb"><span>Respondieron</span><div class="hbbar alt"><i style="width:${Math.round((l.respuestas / lmax) * 100)}%"></i></div><b>${l.respuestas}</b></div>
        <div class="lct">tasa de respuesta: <b>${pct(l.tasa)}</b></div>
      </div>`).join("") + `</div></div></div>`;

  // 4 y 5. Zona y rubro
  html += `<div class="twocol">
    <div class="card"><h3>${ICON.radar}Por zona / país (${g.dias} días)</h3><div class="body">${barsList(g.zonas, "zona")}</div></div>
    <div class="card"><h3>${ICON.grid}Por rubro / tipo de negocio (${g.dias} días)</h3><div class="body">${barsList(g.rubros, "tipo")}</div></div>
  </div>`;

  // 6. Mejores momentos
  html += `<div class="twocol">
    <div class="card"><h3>${ICON.clock}Por hora del día · bloques de 2 h (30 días)</h3><div class="body">
      <div class="legend"><span><i style="background:#3d8bfd"></i>Prospectos contactados</span><span><i style="background:#35c98a"></i>Respondieron</span><span><i style="background:#e0a53b"></i>Tasa</span></div>
      ${chartSVG(g.horas.map((x) => x.bloque), g.horas.map((x) => x.enviados), g.horas.map((x) => x.respuestas), g.horas.map((x) => x.tasa))}</div></div>
    <div class="card"><h3>${ICON.clock}Por día de la semana (30 días)</h3><div class="body">
      <div class="legend"><span><i style="background:#3d8bfd"></i>Prospectos contactados</span><span><i style="background:#35c98a"></i>Respondieron</span><span><i style="background:#e0a53b"></i>Tasa</span></div>
      ${chartSVG(g.diasemana.map((x) => x.dia), g.diasemana.map((x) => x.enviados), g.diasemana.map((x) => x.respuestas), g.diasemana.map((x) => x.tasa))}</div></div>
  </div>`;

  html += `<div class="foot">Datos de las dos líneas de WhatsApp (envíos y respuestas, vía WAHA) y del estado de los leads en Radar. Barras del gráfico diario: mensajes. La «tasa de respuesta» (embudo, líneas, zona, rubro, hora y día) es: de los prospectos contactados, cuántos respondieron.</div>`;
  return html;
}

// ---------------------------------------------------------------- render
function render() {
  const body = $("#view");
  if (!S.state) { body.innerHTML = '<div class="empty"><span class="spin"></span> Cargando datos…</div>'; return; }
  if (S.tab === "resumen") body.innerHTML = renderResumen();
  else if (S.tab === "kanban") body.innerHTML = renderKanban();
  else if (S.tab === "graficos") body.innerHTML = renderGraficos();
  else if (S.tab === "conversaciones") body.innerHTML = S.convs ? renderConv() : '<div class="empty"><span class="spin"></span> Cargando…</div>';
  else if (S.tab === "envios") body.innerHTML = S.envios ? renderEnvios() : '<div class="empty"><span class="spin"></span> Cargando…</div>';
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === S.tab));
  $("#updated").innerHTML = S.state ? `Actualizado ${esc(S.state.last_refresh_fmt || "—")}` : "";
  wire();
}

function wire() {
  document.querySelectorAll(".tab").forEach((t) => t.onclick = () => { S.tab = t.dataset.tab; loadTab(); });
  const kl = $("#kLine"), kz = $("#kZona"), kq = $("#kQ");
  if (kl) { kl.value = S.kLine; kl.onchange = () => { S.kLine = kl.value; S.kShow = {}; render(); }; }
  if (kz) { kz.value = S.kZona; kz.onchange = () => { S.kZona = kz.value; S.kShow = {}; render(); }; }
  if (kq) { let h; kq.oninput = () => { clearTimeout(h); h = setTimeout(() => { S.kQ = kq.value; render(); }, 250); }; }
  document.querySelectorAll(".more").forEach((b) => b.onclick = () => { S.kShow[b.dataset.estado] = (S.kShow[b.dataset.estado] || 40) + 60; render(); });
  document.querySelectorAll(".ebtn[data-act=est]").forEach((b) => b.onclick = () => setExtra(b.dataset.key, { estado_extra: b.dataset.est }));
  document.querySelectorAll(".kcard .save").forEach((b) => b.onclick = () => {
    const card = b.closest(".kcard");
    const body = { nota: card.querySelector(".notaIn").value };
    card.querySelectorAll(".dateIn").forEach((inp) => { body[inp.dataset.f] = inp.value; });
    setExtra(b.dataset.key, body);
  });
  const cQ = $("#cQ"), cL = $("#cLine"), cZ = $("#cZona");
  if (cL) { cL.value = S.cLine; cL.onchange = () => { S.cLine = cL.value; loadConv(); }; }
  if (cZ) { cZ.value = S.cZona; cZ.onchange = () => { S.cZona = cZ.value; loadConv(); }; }
  if (cQ) { let h; cQ.oninput = () => { clearTimeout(h); h = setTimeout(() => { S.cQ = cQ.value; loadConv(); }, 300); }; }
  document.querySelectorAll(".seg[data-dias]").forEach((b) => b.onclick = () => { S.gDias = +b.dataset.dias; loadGraficos(); });
  document.querySelectorAll("tbody tr[data-id]").forEach((tr) => tr.onclick = () => openThread(tr.dataset.line, tr.dataset.id));
}

async function setExtra(key, body) {
  try {
    await api(`/api/cliente/${encodeURIComponent(key)}/extra`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    toast("Guardado");
    await loadState();
  } catch (e) { toast("No se pudo guardar: " + e.message); }
}

async function openThread(line, id) {
  $("#ovl").classList.add("on"); $("#drawer").classList.add("on");
  $("#dname").textContent = "Cargando…"; $("#thread").innerHTML = '<div class="empty"><span class="spin"></span></div>';
  try {
    const d = await api(`/api/chat/${encodeURIComponent(line)}/${encodeURIComponent(id)}`);
    $("#dname").textContent = d.nombre || "Conversación";
    $("#dsub").textContent = `${line} · ${d.mensajes.length} mensajes`;
    if (!d.mensajes.length) { $("#thread").innerHTML = '<div class="empty">Sin mensajes almacenados</div>'; return; }
    $("#thread").innerHTML = d.mensajes.map((m) => `<div class="bub ${m.from_me ? "out" : "in"}">
        ${m.body ? esc(m.body) : ""}${m.media ? `<div class="md">[${esc(m.media)}]</div>` : ""}
        <div class="tm">${esc(m.fmt || "")} ${m.from_me ? "· enviado" : "· recibido"}</div></div>`).join("");
    $("#thread").scrollTop = $("#thread").scrollHeight;
  } catch (e) { $("#thread").innerHTML = '<div class="empty">Error al cargar el hilo</div>'; }
}

async function loadState() {
  try { S.state = await api("/api/state"); render(); } catch (e) { /* reintento por el intervalo */ }
}
async function loadConv() {
  const p = new URLSearchParams();
  if (S.cQ) p.set("q", S.cQ); if (S.cLine) p.set("line", S.cLine); if (S.cZona) p.set("zona", S.cZona);
  S.convs = await api("/api/conversations?" + p.toString());
  if (S.tab === "conversaciones") render();
}
async function loadEnvios() {
  S.envios = await api("/api/envios");
  if (S.tab === "envios") render();
}
async function loadGraficos() {
  S.graficos = await api("/api/graficos?dias=" + S.gDias);
  if (S.tab === "graficos") render();
}
async function loadTab() {
  if (!S.state) await loadState();
  if (S.tab === "conversaciones" && !S.convs) { try { await loadConv(); } catch (e) {} }
  if (S.tab === "envios" && !S.envios) { try { await loadEnvios(); } catch (e) {} }
  if (S.tab === "graficos" && !S.graficos) { try { await loadGraficos(); } catch (e) {} }
  render();
}
async function refreshNow() {
  const b = $("#refreshBtn"); b.disabled = true; b.innerHTML = '<span class="spin"></span> Actualizando';
  try {
    await api("/api/refresh", { method: "POST" });
    await loadState();
    if (S.tab === "conversaciones") await loadConv();
    if (S.tab === "envios") await loadEnvios();
    if (S.tab === "graficos") await loadGraficos();
    toast("Datos actualizados");
  } catch (e) { toast("Error al actualizar: " + e.message); }
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
