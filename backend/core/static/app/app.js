/* Приложение администратора ресепшена.
 * Чистый JavaScript без сборки и библиотек. Сервер — единственный источник правды:
 * доли и касса здесь считаются только для предпросмотра, итог считает сервер.
 * Суммы в API — копейки.
 */
"use strict";

// ---------- утилиты ----------
const $app = document.getElementById("app");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rub = (k) => {
  const neg = k < 0, a = Math.abs(Math.round(k || 0));
  const r = Math.floor(a / 100), c = a % 100;
  return (neg ? "−" : "") + r.toLocaleString("ru-RU") + (c ? "," + String(c).padStart(2, "0") : "") + " ₽";
};
const toKop = (s) => {
  const n = parseFloat(String(s).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
};
const fromKop = (k) => (k % 100 ? (k / 100).toFixed(2).replace(".", ",") : String(k / 100));
const hm = (d) => new Date(d).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
const dayStr = (d) => new Date(d).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
const pct = (amount, rate) => Math.round((amount * rate) / 100);
const PAY = { cash: "Наличные", card: "Карта", transfer: "Перевод" };
const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
  : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* приватный режим */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
};
const cookie = (name) => (document.cookie.split("; ").find((c) => c.startsWith(name + "=")) || "").split("=")[1] || "";

// ---------- состояние ----------
const S = {
  view: "boot", me: null, st: null, tab: "s", q: "", mq: "", error: "", busy: false, toast: "",
  login: { username: store.get("crm.login") || "", password: "" },
  openCash: "", form: null, paid: {}, actual: "", comment: "", cancelId: null, cancelKind: null, cancelReason: "",
  history: null, detail: null, online: navigator.onLine,
};
const shift = () => S.st && S.st.shift;

// ---------- сеть ----------
async function api(method, url, body) {
  let resp;
  try {
    resp = await fetch(url, {
      method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(cookie("csrftoken")) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error("Нет связи с сервером. Проверьте интернет и повторите.");
  }
  let data = {};
  try { data = await resp.json(); } catch (e) { /* не JSON */ }
  if (resp.status === 401) {
    if (data.wipe) wipeDevice(data.detail);
    else if (S.view !== "login") { S.view = "login"; S.error = data.detail || "Сессия истекла. Войдите снова."; render(); }
    // (из кабинета управляющего тоже попадаем на экран входа)
    throw new Error(data.detail || "Войдите в систему.");
  }
  if (resp.status === 403 && !data.detail) throw new Error("Запрос отклонён. Обновите страницу и войдите снова.");
  if (!resp.ok) throw new Error(data.detail || "Ошибка сервера (" + resp.status + ").");
  return data;
}

function wipeDevice(message) {
  // Управляющий отключил устройство: стираем всё локальное
  ["crm.login", "crm.queue"].forEach(store.del);
  S.st = null; S.me = null; S.view = "login"; S.error = message || "Устройство отключено управляющим.";
  render();
}

async function run(fn) {
  if (S.busy) return;
  S.busy = true; S.error = "";
  try { await fn(); } catch (e) { if (e === null) return; S.error = e.message; }
  S.busy = false;
  render();
}

function flash(text) {
  S.toast = text; render();
  clearTimeout(flash.t); flash.t = setTimeout(() => { S.toast = ""; render(); }, 2200);
}

async function loadState() {
  S.st = await api("GET", "/api/admin/state/");
  if (!shift()) S.view = "open";
  else if (S.view === "boot" || S.view === "login" || S.view === "open") S.view = shift().attendance.length ? "shift" : "staff";
}

function applyShift(resp) { if (S.st) S.st.shift = resp.shift; }

// ---------- расчёты для предпросмотра (итог считает сервер) ----------
function previewShares(f) {
  const st = S.st, amount = toKop(f.amount) || 0;
  const room = st.rooms.find((r) => r.id === f.room_id);
  const ar = st.admin_rates;
  if (!room) return null;
  if (room.is_sauna) return { master: 0, disp: 0, admin: pct(amount, ar.sauna), amount };
  const m = st.masters.find((x) => x.id === f.master_id);
  const d = st.dispatchers.find((x) => x.id === f.dispatcher_id);
  const ds = d ? pct(amount, d.rate) : 0;
  let ms = 0;
  if (m) ms = d ? pct(m.base_full ? amount : amount - ds, m.rate_with_dispatcher) : pct(amount, m.rate);
  return { master: ms, disp: ds, admin: pct(amount, d ? ar.session_dispatcher : ar.session), amount };
}

function cashSummary() {
  const sh = shift(), c = sh.cash;
  const paidCash = sh.accruals.reduce((a, x) => a + (S.paid[x.key] ?? 0), 0);
  const expected = c.opening + c.sessions + c.sales - c.expenses - paidCash;
  return { c, paidCash, expected };
}

// ---------- кусочки разметки ----------
const chip = (on, action, label, attrs = "", cls = "") =>
  `<button class="chip ${cls} ${on ? "on" : ""}" data-a="${action}" ${attrs}>${label}</button>`;
const err = () => (S.error ? `<div class="alert err" role="alert">${esc(S.error)}</div>` : "");
const bar = (title, backAction = "toShift", backLabel = "‹ Назад") =>
  `<div class="bar"><button class="back" data-a="${backAction}">${backLabel}</button><h1>${esc(title)}</h1></div>`;
const field = (label, name, value, extra = "") =>
  `<label class="field">${label}<input data-f="${name}" value="${esc(value)}" ${extra}></label>`;
const moneyField = (label, name, value) =>
  field(label, name, value, 'class="money" inputmode="decimal" autocomplete="off"');

// ---------- экраны ----------
const V = {};

V.boot = () => `<div class="boot">Загрузка…</div>`;

V.login = () => `
<div class="screen" style="justify-content:center;padding:32px 28px">
  <div class="row" style="justify-content:flex-start;gap:12px"><div class="logo">CRM</div><div class="sub">Учёт смен · все точки</div></div>
  <h1 class="big">Вход</h1>
  <form class="stack" data-submit="doLogin" style="gap:14px">
    ${field("Логин", "login.username", S.login.username, 'autocomplete="username" autocapitalize="none"')}
    ${field("Пароль", "login.password", S.login.password, 'type="password" autocomplete="current-password"')}
    ${err()}
    <button class="btn" type="submit" ${S.busy ? "disabled" : ""}>${S.busy ? "Входим…" : "Войти"}</button>
  </form>
  <p class="note">Вход с нового устройства увидит управляющий.</p>
</div>`;

V.blocked = () => `
<div class="screen">
  <h1 class="big">Смена занята</h1>
  ${err()}
  <div class="grow"></div>
  <button class="btn" data-a="retry">Проверить ещё раз</button>
  <button class="btn ghost" data-a="logout">Выйти</button>
</div>`;

V.manager = () => `
<div class="screen">
  <h1 class="big">Здравствуйте, ${esc(S.me.name)}</h1>
  <div class="alert ok">Кабинет управляющего появится на этапе 4. Сейчас приложение рассчитано на администраторов точек.</div>
  <div class="grow"></div>
  <button class="btn ghost" data-a="logout">Выйти</button>
</div>`;

V.open = () => `
<div class="screen">
  <div class="row"><div><div class="sub">${esc(S.st.point.name)}${S.st.point.address ? " · " + esc(S.st.point.address) : ""}</div>
  <h1 class="big">Добрый день, ${esc(S.st.user.name)}</h1></div><button class="logout" data-a="logout">Выйти</button></div>
  <div class="card big">
    <div class="title" style="font-size:17px">Открытие смены</div>
    ${moneyField("Наличные в кассе на начало, ₽", "openCash", S.openCash)}
    <p class="note">Пересчитайте кассу. С этой суммы начнётся сверка при закрытии.</p>
  </div>
  ${err()}
  <div class="grow"></div>
  <button class="btn ghost" data-a="history">Мои смены</button>
  <button class="btn" data-a="openShift" ${S.busy ? "disabled" : ""}>Открыть смену</button>
</div>`;

V.staff = () => {
  const sh = shift(), q = S.q.trim().toLowerCase();
  const on = (id) => sh.attendance.includes(id);
  // Свои мастера видны всегда; мастера других точек — те, кто уже на смене, или по поиску (подмена)
  const list = S.st.masters.filter((m) => (m.home || on(m.id) || q) && (!q || m.name.toLowerCase().includes(q)));
  return `
<div class="screen">
  <div class="row" style="align-items:flex-end">
    <div><div class="sub">Смена открыта в ${hm(sh.opened_at)}</div><h1 class="big">Кто сегодня на смене?</h1></div>
    <button class="btn outline small" data-a="addMaster">+ Новый</button>
  </div>
  ${field("Поиск мастера", "q", S.q, 'type="search" placeholder="Начните вводить имя" autocomplete="off"')}
  <div class="stack" id="staffList">${list.map((m) => chip(on(m.id), "toggleStaff", `<span>${esc(m.name)}${m.home ? "" : ` <small style="opacity:.8">· ${esc(m.point)}</small>`}</span><span style="font-size:13px">${on(m.id) ? "На смене" : "Не вышел"}</span>`, `data-id="${m.id}"`, "wide")).join("")}
    ${list.length ? "" : `<div class="empty">Мастер не найден.<br><br><button class="btn outline small" data-a="addMaster" data-name="${esc(S.q.trim())}">Добавить «${esc(S.q.trim())}»</button></div>`}
  </div>
  <p class="note">Мастера с другой точки на подмену — найдите через поиск. Диспетчеров выбирают в сеансе.</p>
  ${err()}
  <div class="grow"></div>
  <button class="btn" data-a="toShift">Готово · ${sh.attendance.length} на смене</button>
</div>`;
};

V.addMaster = () => {
  const f = S.form, p = S.st.point;
  return `
<div class="screen tight">${bar("Новый мастер", "toStaff")}
  <div class="scroll">
    ${field("Имя или псевдоним", "form.name", f.name, 'placeholder="Как называть в системе" autocomplete="off"')}
    ${field("Телефон", "form.phone", f.phone, 'type="tel" placeholder="+7"')}
    ${field("Ставка, %", "form.rate", f.rate, 'inputmode="decimal" class="money"')}
    <div class="card" style="font-size:14px;color:var(--ink2);line-height:1.5">Диапазон точки: <b>${p.rate_min}–${p.rate_max}%</b>. Ставку вне диапазона, ставку при диспетчере и базу расчёта задаёт управляющий.</div>
    ${err()}
  </div>
  <div class="footer"><button class="btn" data-a="saveMaster" ${S.busy ? "disabled" : ""}>Добавить и отметить на смене</button></div>
</div>`;
};

V.shift = () => {
  const sh = shift(), t = sh.totals, c = sh.cash;
  const live = sh.sessions.filter((s) => s.status === "ok");
  const tab = (id, label) => `<button class="${S.tab === id ? "on" : ""}" data-a="tab" data-id="${id}">${label}</button>`;
  let body = "";
  if (S.tab === "s") {
    body = sh.sessions.map((s) => {
      const x = s.status !== "ok";
      const who = s.is_sauna ? "Сауна · без мастера" : `${esc(s.master)}${s.program ? " · " + esc(s.program) : ""}${s.dispatcher ? " · " + esc(s.dispatcher) : ""}`;
      const split = s.is_sauna ? `Админ ${rub(s.admin_share)}`
        : `Мастер ${rub(s.master_share)}${s.dispatcher ? " · Дисп. " + rub(s.dispatcher_share) : ""} · Админ ${rub(s.admin_share)}`;
      return `<div class="card ${x ? "cancelled" : ""}">
        <div class="row strike"><div class="title">${hm(s.start)}–${hm(s.end)} · ${esc(s.room)}</div><div class="title">${rub(s.amount)}</div></div>
        <div class="strike" style="font-size:14px;color:var(--ink2)">${who} · ${PAY[s.payment_method].toLowerCase()}</div>
        <div class="row"><div class="meta">${x ? "Отменён: " + esc(s.cancel_reason) : split}</div>
        ${x ? "" : `<button class="small-btn" data-a="askCancel" data-kind="sessions" data-id="${s.id}">Отменить</button>`}</div>
        ${cancelBox("sessions", s.id)}</div>`;
    }).join("") || `<div class="empty">Сеансов пока нет</div>`;
  } else if (S.tab === "p") {
    body = sh.sales.map((x) => `<div class="card ${x.status !== "ok" ? "cancelled" : ""}">
      <div class="row strike"><div class="title">${esc(x.product)} × ${x.quantity}</div><div class="title">${rub(x.amount)}</div></div>
      <div class="row"><div class="meta">${x.status !== "ok" ? "Отменена: " + esc(x.cancel_reason) : PAY[x.payment_method] + " · админу " + rub(x.admin_share)}</div>
      ${x.status === "ok" ? `<button class="small-btn" data-a="askCancel" data-kind="sales" data-id="${x.id}">Отменить</button>` : ""}</div>
      ${cancelBox("sales", x.id)}</div>`).join("") || `<div class="empty">Продаж пока нет</div>`;
  } else {
    body = sh.expenses.map((e) => `<div class="card ${e.status !== "ok" ? "cancelled" : ""}">
      <div class="row strike"><div class="title">${esc(e.category)}</div><div class="title red">−${rub(e.amount)}</div></div>
      <div class="row"><div class="meta">${e.status !== "ok" ? "Отменён: " + esc(e.cancel_reason) : PAY[e.payment_method] + (e.comment ? " · " + esc(e.comment) : "")}</div>
      ${e.status === "ok" ? `<button class="small-btn" data-a="askCancel" data-kind="expenses" data-id="${e.id}">Отменить</button>` : ""}</div>
      ${cancelBox("expenses", e.id)}</div>`).join("") || `<div class="empty">Расходов пока нет</div>`;
  }
  return `
<div class="screen tight">
  <div class="top"><div><div class="sub">${esc(S.st.point.name)} · смена с ${hm(sh.opened_at)}</div><div class="name">${esc(S.st.user.name)}</div></div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
      <span class="pill ${S.online ? "ok" : "off"}"><span class="dot"></span>${S.online ? "Онлайн" : "Нет сети"}</span>
      </div></div>
  <div style="padding:0 16px 12px"><button class="btn ghost small" style="width:100%" data-a="toStaff">Сотрудники на смене · ${sh.attendance.length} — добавить или снять</button></div>
  <div class="hero">
    <div><div class="k">Выручка смены</div><div class="v">${rub(t.revenue)}</div></div>
    <div class="grid3" style="font-size:13px">
      <div><div class="k">В кассе</div><div>${rub(c.opening + c.sessions + c.sales - c.expenses)}</div></div>
      <div><div class="k">Карта</div><div>${rub(t.by_method.card)}</div></div>
      <div><div class="k">Перевод</div><div>${rub(t.by_method.transfer)}</div></div>
    </div>
    <div class="row foot">Начислено персоналу<b>${rub(t.staff)}</b></div>
  </div>
  <div class="tabs">${tab("s", "Сеансы " + live.length)}${tab("p", "Продажи " + sh.sales.filter((x) => x.status === "ok").length)}${tab("e", "Расходы " + sh.expenses.filter((x) => x.status === "ok").length)}</div>
  <div class="scroll" style="gap:8px">${err()}${body}</div>
  <div class="footer">
    <div style="display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:8px">
      <button class="btn small" data-a="newSession">+ Сеанс</button>
      <button class="btn ghost small" data-a="newSale">+ Продажа</button>
      <button class="btn ghost small" data-a="newExpense">+ Расход</button>
    </div>
    <button class="btn link" data-a="toPay">Выплаты и закрытие смены →</button>
  </div>
</div>`;
};

function cancelBox(kind, id) {
  if (S.cancelId !== id || S.cancelKind !== kind) return "";
  return `<div class="stack" style="margin-top:6px">
    ${field("Причина отмены (обязательно)", "cancelReason", S.cancelReason, 'autocomplete="off"')}
    <div class="grid2"><button class="btn small dark" data-a="doCancel">Отменить запись</button>
    <button class="btn ghost small" data-a="closeCancel">Не отменять</button></div></div>`;
}

V.session = () => {
  const f = S.form, st = S.st, sh = shift();
  const room = st.rooms.find((r) => r.id === f.room_id);
  const mq = S.mq.trim().toLowerCase();
  const masters = st.masters.filter((m) => sh.attendance.includes(m.id) && (!mq || m.name.toLowerCase().includes(mq)));
  const len = (f.end - f.start) / 60000;
  return `
<div class="screen tight">${bar("Новый сеанс")}
  <div class="scroll">
    <div class="stack"><div class="label">Комната</div><div class="chips">
      ${st.rooms.map((r) => chip(r.id === f.room_id, "pickRoom", esc(r.name), `data-id="${r.id}"`)).join("")}</div></div>
    ${room && room.is_sauna ? `<div class="alert ok">Сауна без мастера. Сумма считается по времени: ${rub(room.hour_price)} в час.</div>` : `
    <div class="stack"><div class="label">Мастер (на смене)</div>
      <input data-f="mq" value="${esc(S.mq)}" type="search" placeholder="Поиск по имени" aria-label="Поиск мастера" autocomplete="off"
        style="height:44px;border:1px solid var(--field);border-radius:10px;padding:0 14px;font-size:16px">
      <div class="chips">${masters.map((m) => chip(m.id === f.master_id, "pickMaster", esc(m.name), `data-id="${m.id}"`)).join("")
        || `<span class="sub" style="padding:10px 0">${sh.attendance.length ? "Никого с таким именем на смене" : "Сначала отметьте мастеров на смене"}</span>`}</div></div>
    <div class="stack"><div class="label">Программа</div>
      ${st.programs.map((p) => chip(p.id === f.program_id, "pickProgram", `<span>${esc(p.name)}</span><span>${p.duration_min} мин · ${rub(p.price)}</span>`, `data-id="${p.id}"`, "wide")).join("")}</div>
    <div class="stack"><div class="label">Клиент от диспетчера</div><div class="chips">
      ${chip(!f.dispatcher_id, "pickDisp", "Нет", 'data-id=""')}
      ${st.dispatchers.map((d) => chip(d.id === f.dispatcher_id, "pickDisp", esc(d.name), `data-id="${d.id}"`)).join("")}</div></div>`}
    <div class="grid2">
      <div class="card"><div class="sub">Начало</div><div class="stepper">
        <button data-a="step" data-w="start" data-d="-15" aria-label="Начало на 15 минут раньше">−</button><span>${hm(f.start)}</span>
        <button data-a="step" data-w="start" data-d="15" aria-label="Начало на 15 минут позже">+</button></div></div>
      <div class="card"><div class="sub">Конец · ${len >= 60 ? Math.floor(len / 60) + " ч " : ""}${len % 60 ? (len % 60) + " мин" : ""}</div><div class="stepper">
        <button data-a="step" data-w="end" data-d="-15" aria-label="Конец на 15 минут раньше">−</button><span>${hm(f.end)}</span>
        <button data-a="step" data-w="end" data-d="15" aria-label="Конец на 15 минут позже">+</button></div></div>
    </div>
    ${moneyField("Внесено клиентом, ₽", "form.amount", f.amount)}
    <div class="stack"><div class="label">Оплата</div><div class="grid3">
      ${Object.entries(PAY).map(([k, v]) => chip(f.payment_method === k, "pickPay", v, `data-id="${k}"`)).join("")}</div></div>
    <div class="card lines" id="preview">${previewHtml()}</div>
    ${err()}
  </div>
  <div class="footer"><button class="btn" data-a="saveSession" ${S.busy ? "disabled" : ""}>${S.busy ? "Записываем…" : "Записать сеанс"}</button></div>
</div>`;
};

function previewHtml() {
  const p = previewShares(S.form);
  if (!p) return "";
  const room = S.st.rooms.find((r) => r.id === S.form.room_id);
  const rows = [];
  if (!room.is_sauna) rows.push(["Мастеру", p.master]);
  if (S.form.dispatcher_id) rows.push(["Диспетчеру", p.disp]);
  rows.push(["Администратору", p.admin], ["Заведению", p.amount - p.master - p.disp - p.admin]);
  return `<div class="title">Начисления с сеанса</div>` + rows.map(([l, v]) => `<div class="row"><span>${l}</span><b>${rub(v)}</b></div>`).join("");
}

V.sale = () => {
  const f = S.form, st = S.st, g = st.products.find((p) => p.id === f.product_id);
  const total = g.price * f.quantity;
  return `
<div class="screen tight">${bar("Доп. продажа")}
  <div class="scroll">
    <div class="grid2">${st.products.map((p) => chip(p.id === f.product_id, "pickProduct", `<b>${esc(p.name)}</b><span>${rub(p.price)}</span>`, `data-id="${p.id}"`, "tile")).join("")}</div>
    <div class="card row"><span class="sub">Количество</span><div class="stepper" style="gap:16px;margin:0">
      <button data-a="qty" data-d="-1" aria-label="Меньше">−</button><span style="min-width:24px;text-align:center">${f.quantity}</span>
      <button data-a="qty" data-d="1" aria-label="Больше">+</button></div></div>
    <div class="grid3">${Object.entries(PAY).map(([k, v]) => chip(f.payment_method === k, "pickPay", v, `data-id="${k}"`)).join("")}</div>
    <div class="card lines"><div class="row total" style="border:0;padding:0"><span>Итого</span><span>${rub(total)}</span></div>
      <div class="row"><span>Администратору (${g.admin_rate}%)</span><b>${rub(pct(total, g.admin_rate))}</b></div></div>
    ${err()}
  </div>
  <div class="footer"><button class="btn" data-a="saveSale" ${S.busy ? "disabled" : ""}>Записать продажу</button></div>
</div>`;
};

V.expense = () => {
  const f = S.form;
  return `
<div class="screen tight">${bar("Расход")}
  <div class="scroll">
    <div class="chips">${S.st.expense_categories.map((c) => chip(c.id === f.category_id, "pickCategory", esc(c.name), `data-id="${c.id}"`)).join("")}</div>
    ${moneyField("Сумма, ₽", "form.amount", f.amount)}
    ${field("Комментарий", "form.comment", f.comment, 'placeholder="На что потрачено" autocomplete="off"')}
    <div class="grid2">${["cash", "card"].map((k) => chip(f.payment_method === k, "pickPay", PAY[k], `data-id="${k}"`)).join("")}</div>
    ${err()}
  </div>
  <div class="footer"><button class="btn" data-a="saveExpense" ${S.busy ? "disabled" : ""}>Записать расход</button></div>
</div>`;
};

V.pay = () => {
  const sh = shift(), { paidCash } = cashSummary();
  return `
<div class="screen tight">${bar("Выплаты за смену", "toShift", "‹ К смене")}
  <div class="scroll" style="gap:8px">
    <p class="note" style="font-size:14px;color:var(--ink2)">Отметьте каждого. Невыплаченное уйдёт в долг и будет видно управляющему.</p>
    ${sh.accruals.map((a) => {
      const v = S.paid[a.key];
      const mark = v === undefined ? null : v === a.amount ? "paid" : v === 0 ? "debt" : "part";
      return `<div class="card" style="gap:10px">
        <div class="row"><div><div class="title">${esc(a.name)}</div><div class="meta">${esc(a.role)}</div></div><div class="title" style="font-size:18px">${rub(a.amount)}</div></div>
        <div class="grid2">${chip(mark === "paid", "setPaid", "Выплачено", `data-key="${a.key}" data-v="full"`)}
          ${chip(mark === "debt", "setPaid", "В долг", `data-key="${a.key}" data-v="0"`, mark === "debt" ? "debt" : "")}</div>
        ${mark === "part" ? `<div class="meta">Выплачено ${rub(v)}, в долг ${rub(a.amount - v)}</div>` : ""}
      </div>`;
    }).join("")}
    ${err()}
  </div>
  <div class="footer">
    <div class="row" style="font-size:14px;color:var(--ink2)"><span>Выдать наличными</span><b style="color:var(--ink)">${rub(paidCash)}</b></div>
    <div class="grid2">
      <button class="btn ghost" data-a="payAll">Всем выплачено</button>
      <button class="btn" data-a="toClose">К сверке кассы</button></div>
  </div>
</div>`;
};

V.close = () => {
  const { c, paidCash, expected } = cashSummary();
  const actual = toKop(S.actual);
  const diff = actual === null || S.actual === "" ? null : actual - expected;
  const lines = [["На начало смены", c.opening], ["+ наличные за сеансы", c.sessions], ["+ наличные за продажи", c.sales],
    ["− расходы наличными", c.expenses], ["− выплаты персоналу", paidCash]];
  return `
<div class="screen tight">${bar("Сверка кассы", "toPay", "‹ Выплаты")}
  <div class="scroll">
    <div class="card lines">${lines.map(([l, v]) => `<div class="row"><span>${l}</span><b>${rub(v)}</b></div>`).join("")}
      <div class="row total"><span>Должно быть</span><span>${rub(expected)}</span></div></div>
    ${moneyField("Фактически в кассе, ₽", "actual", S.actual)}
    <div id="diffBadge">${diffBadge(diff)}</div>
    <div id="diffComment">${diff ? diffComment() : ""}</div>
    ${err()}
  </div>
  <div class="footer"><button class="btn dark" data-a="closeShift" ${S.busy ? "disabled" : ""}>${S.busy ? "Закрываем…" : "Закрыть смену"}</button></div>
</div>`;
};

function diffBadge(diff) {
  if (diff === null) return "";
  return diff === 0 ? `<div class="alert ok"><b>Касса сходится</b></div>`
    : `<div class="alert warn"><b>${diff > 0 ? "Излишек " + rub(diff) : "Недостача " + rub(-diff)}</b> — управляющий получит уведомление</div>`;
}
const diffComment = () => field("Причина расхождения (обязательно)", "comment", S.comment, 'autocomplete="off"');

V.done = () => {
  const sh = S.detail, t = sh.totals;
  return `
<div class="screen">
  <div><div class="sub" style="color:var(--accent);font-weight:500">Смена закрыта · данные на сервере</div><h1 class="big">Итоги смены</h1></div>
  <div class="card big lines" style="gap:8px">
    <div class="row"><span>Выручка</span><b>${rub(t.revenue)}</b></div>
    <div class="row"><span>· наличными</span><b>${rub(t.by_method.cash)}</b></div>
    <div class="row"><span>· картой</span><b>${rub(t.by_method.card)}</b></div>
    <div class="row"><span>· переводом</span><b>${rub(t.by_method.transfer)}</b></div>
    <div class="row"><span>Начислено персоналу</span><b>${rub(t.staff)}</b></div>
    <div class="row"><span>Расходы</span><b>${rub(t.expenses)}</b></div>
    <div class="row"><span>Остаётся заведению</span><b>${rub(t.revenue - t.staff - t.expenses)}</b></div>
    <div class="row"><span>Касса: ожидалось / факт</span><b>${rub(sh.expected_cash)} / ${rub(sh.actual_cash)}</b></div>
    <div class="row"><span>Расхождение</span><b>${sh.discrepancy ? rub(sh.discrepancy) : "нет"}</b></div>
  </div>
  <div class="grow"></div>
  <button class="btn ghost" data-a="history">Мои смены</button>
  <button class="btn" data-a="restart">Готово</button>
</div>`;
};

V.history = () => `
<div class="screen tight">${bar("Мои смены", "fromHistory")}
  <div class="scroll" style="gap:8px">
    ${S.history === null ? `<div class="empty">Загрузка…</div>` : S.history.map((s) => `
      <button class="card" data-a="openDetail" data-id="${s.id}" style="border:0;text-align:left">
        <div class="row"><div class="title">${dayStr(s.opened_at)} · ${esc(s.point)}</div><div class="title">${rub(s.revenue)}</div></div>
        <div class="meta">${hm(s.opened_at)}–${s.closed_at ? hm(s.closed_at) : "…"} · ${s.discrepancy ? "расхождение " + rub(s.discrepancy) : "касса сошлась"} · только просмотр</div>
      </button>`).join("") || `<div class="empty">Закрытых смен пока нет</div>`}
    ${err()}
  </div>
</div>`;

// ---------- рендер ----------
function render() {
  if (S.view === "manager-app") return; // экраном управляет manager.js
  document.body.classList.remove("mgr");
  const view = V[S.view] || V.boot;
  const focused = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.f;
  const caret = focused ? document.activeElement.selectionStart : null;
  $app.innerHTML = view() + (S.toast ? `<div class="toast" role="status">${esc(S.toast)}</div>` : "");
  if (focused) {
    const el = $app.querySelector(`[data-f="${focused}"]`);
    if (el) { el.focus(); try { el.setSelectionRange(caret, caret); } catch (e) { /* type=number */ } }
  }
}

function setPath(path, value) {
  const parts = path.split(".");
  let o = S;
  for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]];
  o[parts[parts.length - 1]] = value;
}

// Ввод текста: обновляем состояние без полного перерисовывания, чтобы не прыгал курсор
document.addEventListener("input", (e) => {
  const f = e.target.dataset && e.target.dataset.f;
  if (!f) return;
  setPath(f, e.target.value);
  if (S.error) { S.error = ""; const a = $app.querySelector(".alert.err"); if (a) a.remove(); }
  if (f === "q" && S.view === "staff") render();
  if (f === "mq" && S.view === "session") render();
  if (f === "form.amount" && S.view === "session") { const p = document.getElementById("preview"); if (p) p.innerHTML = previewHtml(); }
  if (f === "actual" && S.view === "close") {
    const { expected } = cashSummary(), a = toKop(S.actual);
    const diff = a === null || S.actual === "" ? null : a - expected;
    document.getElementById("diffBadge").innerHTML = diffBadge(diff);
    const box = document.getElementById("diffComment"), need = !!diff;
    if (need && !box.innerHTML) box.innerHTML = diffComment();
    if (!need) box.innerHTML = "";
  }
});

document.addEventListener("submit", (e) => {
  const a = e.target.dataset.submit;
  if (a) { e.preventDefault(); A[a](e.target.dataset); }
});

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-a]");
  if (!el || !A[el.dataset.a]) return;
  e.preventDefault();
  A[el.dataset.a](el.dataset);
});

window.addEventListener("online", () => { S.online = true; render(); });
window.addEventListener("offline", () => { S.online = false; render(); });

// ---------- действия ----------
const roundUp15 = (d) => { const t = new Date(d); t.setSeconds(0, 0); const m = t.getMinutes(); t.setMinutes(m + ((15 - (m % 15)) % 15)); return t.getTime(); };
const idOf = (v) => (v === "" || v === undefined ? null : Number(v));

const A = {
  doLogin: () => run(async () => {
    let device = store.get("crm.device");
    if (!device) { device = uuid(); store.set("crm.device", device); }
    const r = await api("POST", "/api/login/", {
      username: S.login.username.trim(), password: S.login.password, device_id: device,
      device_label: navigator.userAgent.slice(0, 200),
    });
    store.set("crm.device", r.device_id);
    store.set("crm.login", S.login.username.trim());
    S.login.password = ""; S.me = r.user;
    if (r.user.role !== "admin") { await api("GET", "/api/me/"); startManager(r.user); S.busy = false; throw null; }
    await api("GET", "/api/me/"); // новый CSRF-токен после входа
    try { await loadState(); } catch (e) { S.view = "blocked"; throw e; }
  }),
  logout: () => run(async () => { await api("POST", "/api/logout/"); S.st = null; S.view = "login"; }),

  openShift: () => run(async () => {
    const k = toKop(S.openCash);
    if (k === null || S.openCash === "") throw new Error("Введите сумму наличных в кассе. Если касса пуста — 0.");
    applyShift(await api("POST", "/api/shift/open/", { opening_cash: k }));
    S.openCash = ""; S.view = "staff";
  }),
  toggleStaff: (d) => run(async () => {
    const id = Number(d.id), present = !shift().attendance.includes(id);
    applyShift(await api("POST", "/api/shift/attendance/", { employee_id: id, present }));
  }),
  toStaff: () => { S.error = ""; S.view = "staff"; render(); },
  toShift: () => { S.error = ""; S.cancelId = null; S.view = "shift"; render(); },
  tab: (d) => { S.tab = d.id; S.cancelId = null; render(); },

  addMaster: (d) => { S.error = ""; S.form = { name: d.name || "", phone: "", rate: String(S.st.point.rate_default) }; S.view = "addMaster"; render(); },
  saveMaster: () => run(async () => {
    const f = S.form;
    if (!f.name.trim()) throw new Error("Укажите имя или псевдоним.");
    const rate = parseFloat(String(f.rate).replace(",", "."));
    const r = await api("POST", "/api/employees/", { name: f.name.trim(), phone: f.phone.trim(), rate });
    S.st = await api("GET", "/api/admin/state/");
    S.q = ""; S.view = "staff"; flash(`${r.employee.name} добавлен(а) и отмечен(а) на смене`);
  }),

  newSession: () => {
    const sh = shift(), st = S.st;
    const firstOn = st.masters.find((m) => sh.attendance.includes(m.id));
    const prog = st.programs[1] || st.programs[0];
    const start = roundUp15(Date.now());
    const room = st.rooms.find((r) => !r.is_sauna) || st.rooms[0];
    S.form = { id: uuid(), room_id: room.id, master_id: firstOn ? firstOn.id : null, dispatcher_id: null,
      program_id: prog ? prog.id : null, start, end: start + (prog ? prog.duration_min : 60) * 60000,
      amount: prog ? fromKop(prog.price) : "", payment_method: "cash" };
    S.mq = ""; S.error = ""; S.view = "session"; render();
  },
  pickRoom: (d) => {
    const f = S.form, r = S.st.rooms.find((x) => x.id === Number(d.id));
    f.room_id = r.id;
    if (r.is_sauna) { f.master_id = null; f.dispatcher_id = null; f.program_id = null; f.amount = fromKop(Math.round((f.end - f.start) / 3600000 * r.hour_price)); }
    else if (!f.master_id) { const m = S.st.masters.find((x) => shift().attendance.includes(x.id)); f.master_id = m ? m.id : null; }
    S.error = ""; render();
  },
  pickMaster: (d) => { S.form.master_id = Number(d.id); S.error = ""; render(); },
  pickDisp: (d) => { S.form.dispatcher_id = idOf(d.id); render(); },
  pickProgram: (d) => {
    const p = S.st.programs.find((x) => x.id === Number(d.id));
    Object.assign(S.form, { program_id: p.id, end: S.form.start + p.duration_min * 60000, amount: fromKop(p.price) });
    render();
  },
  pickPay: (d) => { S.form.payment_method = d.id; render(); },
  step: (d) => {
    const f = S.form, delta = Number(d.d) * 60000;
    if (d.w === "start") { f.start += delta; f.end += delta; } else { f.end = Math.max(f.start + 15 * 60000, f.end + delta); }
    const r = S.st.rooms.find((x) => x.id === f.room_id);
    if (r && r.is_sauna) f.amount = fromKop(Math.round((f.end - f.start) / 3600000 * r.hour_price));
    S.error = ""; render();
  },
  saveSession: () => run(async () => {
    const f = S.form, room = S.st.rooms.find((r) => r.id === f.room_id), amount = toKop(f.amount);
    if (!room.is_sauna && !f.master_id) throw new Error("Выберите мастера. Если списка нет — отметьте мастеров на смене.");
    if (!amount) throw new Error("Укажите сумму, которую внёс клиент.");
    applyShift(await api("POST", "/api/sessions/", {
      id: f.id, room_id: f.room_id, master_id: room.is_sauna ? null : f.master_id,
      dispatcher_id: room.is_sauna ? null : f.dispatcher_id, program_id: room.is_sauna ? null : f.program_id,
      start: new Date(f.start).toISOString(), end: new Date(f.end).toISOString(), amount,
      payment_method: f.payment_method, client_created_at: new Date().toISOString(),
    }));
    S.tab = "s"; S.view = "shift"; flash("Сеанс записан");
  }),

  newSale: () => { const p = S.st.products[0]; S.form = { id: uuid(), product_id: p.id, quantity: 1, payment_method: "cash" }; S.error = ""; S.view = "sale"; render(); },
  pickProduct: (d) => { S.form.product_id = Number(d.id); render(); },
  qty: (d) => { S.form.quantity = Math.max(1, S.form.quantity + Number(d.d)); render(); },
  saveSale: () => run(async () => {
    const f = S.form;
    applyShift(await api("POST", "/api/sales/", { id: f.id, product_id: f.product_id, quantity: f.quantity, payment_method: f.payment_method }));
    S.tab = "p"; S.view = "shift"; flash("Продажа записана");
  }),

  newExpense: () => { S.form = { id: uuid(), category_id: S.st.expense_categories[0].id, amount: "", comment: "", payment_method: "cash" }; S.error = ""; S.view = "expense"; render(); },
  pickCategory: (d) => { S.form.category_id = Number(d.id); render(); },
  saveExpense: () => run(async () => {
    const f = S.form, amount = toKop(f.amount);
    if (!amount) throw new Error("Укажите сумму расхода.");
    applyShift(await api("POST", "/api/expenses/", { id: f.id, category_id: f.category_id, amount, comment: f.comment.trim(), payment_method: f.payment_method }));
    S.tab = "e"; S.view = "shift"; flash("Расход записан");
  }),

  askCancel: (d) => { S.cancelId = d.id; S.cancelKind = d.kind; S.cancelReason = ""; S.error = ""; render(); },
  closeCancel: () => { S.cancelId = null; render(); },
  doCancel: () => run(async () => {
    if (!S.cancelReason.trim()) throw new Error("Укажите причину отмены.");
    applyShift(await api("POST", `/api/${S.cancelKind}/${S.cancelId}/cancel/`, { reason: S.cancelReason.trim() }));
    S.cancelId = null; flash("Запись отменена");
  }),

  toPay: () => { S.error = ""; S.view = "pay"; render(); },
  setPaid: (d) => { const a = shift().accruals.find((x) => x.key === d.key); S.paid[d.key] = d.v === "full" ? a.amount : 0; S.error = ""; render(); },
  payAll: () => { shift().accruals.forEach((a) => { S.paid[a.key] = a.amount; }); S.error = ""; render(); },
  toClose: () => {
    const missing = shift().accruals.filter((a) => S.paid[a.key] === undefined);
    if (missing.length) { S.error = "Отметьте каждого: выплачено или в долг. Осталось: " + missing.map((a) => a.name).join(", ") + "."; render(); return; }
    S.error = ""; S.view = "close"; render();
  },
  closeShift: () => run(async () => {
    const { expected } = cashSummary(), actual = toKop(S.actual);
    if (actual === null || S.actual === "") throw new Error("Введите, сколько наличных фактически в кассе.");
    if (actual !== expected && !S.comment.trim()) throw new Error("Укажите причину расхождения.");
    const r = await api("POST", "/api/shift/close/", {
      paid: shift().accruals.map((a) => ({ key: a.key, paid: S.paid[a.key] })), actual_cash: actual, comment: S.comment.trim(),
    });
    S.detail = r.shift; S.st.shift = null; S.paid = {}; S.actual = ""; S.comment = ""; S.view = "done";
  }),
  restart: () => { S.view = "open"; render(); },
  retry: () => run(async () => { try { await loadState(); } catch (e) { S.view = "blocked"; throw e; } }),

  history: () => run(async () => { S.history = null; S.view = "history"; render(); S.history = (await api("GET", "/api/shifts/mine/")).shifts; }),
  fromHistory: () => { S.view = shift() ? "shift" : "open"; render(); },
  openDetail: (d) => run(async () => { S.detail = (await api("GET", `/api/shifts/${d.id}/`)).shift; S.view = "done"; }),
};

// ---------- кабинет управляющего (отдельный файл) ----------
function startManager(me) {
  S.view = "manager-app";
  const go = () => window.ManagerApp.start(me);
  if (window.ManagerApp) return go();
  const tag = document.createElement("script");
  tag.src = "/static/app/manager.js?v=4";
  tag.onload = go;
  tag.onerror = () => { $app.innerHTML = '<div class="screen"><div class="alert err">Не удалось загрузить кабинет. Обновите страницу.</div></div>'; };
  document.body.appendChild(tag);
}
window.CRM = { api, esc, rub, toKop, fromKop, hm, dayStr, store, cookie, logout: async () => { await api("POST", "/api/logout/"); location.reload(); } };

// ---------- старт ----------
(async function start() {
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
  try {
    const me = await api("GET", "/api/me/");
    if (!me.authenticated) { S.view = "login"; render(); return; }
    S.me = me.user;
    if (me.user.role !== "admin") { startManager(me.user); return; }
    await loadState();
  } catch (e) {
    S.error = e.message;
    if (S.view === "boot") S.view = S.me ? "blocked" : "login";
  }
  render();
})();
