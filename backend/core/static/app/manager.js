/* Кабинет управляющего. Подгружается из app.js, когда входит управляющий.
 * Свои атрибуты: data-m (действие), data-mf (поле) — чтобы не пересекаться с приложением администратора.
 */
"use strict";
(function () {
  const { api, esc, rub, toKop, hm, dayStr } = window.CRM;
  const $app = document.getElementById("app");
  const PAY = { cash: "наличные", card: "карта", transfer: "перевод" };
  const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const shiftDays = (iso, n) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const num = (v) => { const n = parseFloat(String(v).replace(",", ".")); return Number.isFinite(n) ? n : null; };
  const pct = (a, r) => Math.round((a * r) / 100);

  const M = {
    me: null, tab: "summary", busy: false, error: "", toast: "",
    summary: null, staff: null, admins: null, points: null, devices: null, report: null, log: null,
    staffQ: "", staffArch: false, staffSel: null, staffForm: null,
    adminSel: null, adminForm: null, adminNew: null, adminPass: "", adminArch: false,
    pointForms: {}, confirmAll: false, shiftOpen: null, shiftQ: "",
    rep: { from: today(), to: today() }, logQ: "",
  };

  const NAV = [["summary", "Сводка"], ["staff", "Мастера и диспетчеры"], ["admins", "Администраторы"],
    ["points", "Точки и ставки"], ["devices", "Устройства"], ["reports", "Отчёты"], ["log", "Журнал"]];

  async function load(tab) {
    if (tab === "summary") M.summary = await api("GET", "/api/m/summary/");
    if (tab === "staff") { const r = await api("GET", "/api/m/staff/"); M.staff = r.staff; M.points = r.points; }
    if (tab === "admins") M.admins = await api("GET", "/api/m/admins/");
    if (tab === "points") { M.points = (await api("GET", "/api/m/points/")).points; M.pointForms = {}; }
    if (tab === "devices") M.devices = (await api("GET", "/api/m/devices/")).devices;
    if (tab === "reports") M.report = await api("GET", `/api/m/report/?from=${M.rep.from}&to=${M.rep.to}`);
    if (tab === "log") M.log = (await api("GET", "/api/m/log/?q=" + encodeURIComponent(M.logQ))).log;
  }

  async function run(fn) {
    if (M.busy) return;
    M.busy = true; M.error = "";
    try { await fn(); } catch (e) { if (e) M.error = e.message; }
    M.busy = false;
    if (document.body.classList.contains("mgr")) render();
  }
  function flash(t) { M.toast = t; render(); clearTimeout(flash.t); flash.t = setTimeout(() => { M.toast = ""; render(); }, 2500); }

  const err = () => (M.error ? `<div class="alert err" role="alert">${esc(M.error)}</div>` : "");
  const btn = (action, label, cls = "", attrs = "") => `<button class="btn ${cls}" data-m="${action}" ${attrs}>${label}</button>`;
  const chip = (on, action, label, attrs = "") => `<button class="chip ${on ? "on" : ""}" data-m="${action}" ${attrs}>${label}</button>`;
  const input = (label, path, value, extra = "") =>
    `<label class="field">${label}<input data-mf="${path}" value="${esc(value ?? "")}" ${extra}></label>`;
  const pctIn = (label, path, value) => input(label, path, value, 'inputmode="decimal" autocomplete="off"');
  const loading = (x) => (x === null ? `<div class="empty">Загрузка…</div>` : "");

  // ---------- разделы ----------
  const T = {};

  T.summary = () => {
    const s = M.summary;
    if (!s) return loading(null);
    const status = { open: ["ok", "Смена открыта"], closed: ["off-n", "Смена закрыта"], stale: ["bad", "Не закрыта вовремя"] };
    return `
    <div class="m-head"><div><div class="sub">${dayStr(new Date())}</div><h1 class="big">Сводка по точкам</h1></div>
      ${btn("refresh", "Обновить", "ghost small")}</div>
    <div class="m-cards">${s.points.map((p) => `
      <div class="card big">
        <div class="row"><div class="title" style="font-size:17px">${esc(p.name)}</div><span class="badge ${status[p.status][0]}">${status[p.status][1]}</span></div>
        <div><div class="sub">Выручка за сегодня</div><div style="font-size:26px;font-weight:600">${rub(p.revenue)}</div></div>
        <div class="grid2 sub">
          <div>Администратор<div class="v">${esc(p.admin)}</div></div>
          <div>На смене<div class="v">${p.status === "closed" ? "—" : p.on_shift + " мастер(а)"}</div></div>
          <div>Сеансов<div class="v">${p.sessions}</div></div>
          <div>Касса<div class="v ${p.last_discrepancy ? "red" : ""}">${p.status !== "closed" ? "сверка при закрытии" : p.last_discrepancy ? "расхождение " + rub(p.last_discrepancy) : "сошлась"}</div></div>
        </div>
        ${p.shift_id ? btn("openShift", "Смена: состав и записи", "ghost small", `data-id="${p.shift_id}"`) : ""}
      </div>`).join("")}</div>
    ${M.shiftOpen ? shiftPanel() : ""}
    <div class="card big"><h2 class="h2">Требует внимания</h2>
      ${s.alerts.length ? s.alerts.map((a) => `<div class="alert ${a.level === "bad" ? "err" : a.level === "warn" ? "warn" : "ok"}"><b>${esc(a.tag)}.</b> ${esc(a.text)}</div>`).join("")
        : `<div class="sub">Всё спокойно.</div>`}</div>`;
  };

  function shiftPanel() {
    const { shift, masters } = M.shiftOpen, q = M.shiftQ.trim().toLowerCase();
    const on = (id) => shift.attendance.includes(id);
    const list = masters.filter((m) => on(m.id) || (q ? m.name.toLowerCase().includes(q) : m.home));
    const live = shift.sessions.filter((x) => x.status === "ok");
    return `<div class="card big" style="border:2px solid var(--accent)">
      <div class="row"><h2 class="h2">${esc(shift.point)} · смена ${esc(shift.admin)} с ${hm(shift.opened_at)}</h2>${btn("closeShiftPanel", "Закрыть", "ghost small")}</div>
      <div class="grid3 sub"><div>Выручка<div class="v">${rub(shift.totals.revenue)}</div></div>
        <div>Персоналу<div class="v">${rub(shift.totals.staff)}</div></div><div>Расходы<div class="v">${rub(shift.totals.expenses)}</div></div></div>
      <div class="label">Сотрудники на смене — добавить или снять (мастера других точек — через поиск)</div>
      <input data-mf="shiftQ" value="${esc(M.shiftQ)}" type="search" placeholder="Поиск мастера по имени" aria-label="Поиск мастера" class="m-input">
      <div class="chips">${list.map((m) => chip(on(m.id), "toggleShiftStaff", `${esc(m.name)}${m.home ? "" : ` · ${esc(m.point)}`}`, `data-id="${m.id}"`)).join("") || '<span class="sub">Никого не найдено</span>'}</div>
      <div class="label">Сеансы (${live.length})</div>
      <div class="m-table"><table><thead><tr><th>Время</th><th>Комната</th><th>Мастер</th><th class="r">Сумма</th><th>Оплата</th></tr></thead><tbody>
      ${shift.sessions.map((x) => `<tr class="${x.status !== "ok" ? "dim" : ""}"><td>${hm(x.start)}–${hm(x.end)}</td><td>${esc(x.room)}</td><td>${esc(x.master || "—")}${x.dispatcher ? " · " + esc(x.dispatcher) : ""}</td><td class="r">${rub(x.amount)}</td><td>${x.status !== "ok" ? "отменён" : PAY[x.payment_method]}</td></tr>`).join("") || '<tr><td colspan="5" class="sub">Сеансов пока нет</td></tr>'}
      </tbody></table></div>${err()}</div>`;
  }

  T.staff = () => {
    if (!M.staff) return loading(null);
    const q = M.staffQ.trim().toLowerCase();
    const rows = M.staff.filter((e) => e.archived === M.staffArch && (!q || e.name.toLowerCase().includes(q)));
    const act = M.staff.filter((e) => !e.archived).length, arch = M.staff.length - act;
    return `
    <div class="m-head"><h1 class="big">Мастера и диспетчеры</h1>${btn("newStaff", "+ Добавить")}</div>
    <div class="chips">${chip(!M.staffArch, "staffArch", "Работают · " + act, 'data-v="0"')}${chip(M.staffArch, "staffArch", "Удалённые · " + arch, 'data-v="1"')}</div>
    <div class="m-split"><div class="m-main">
      <input data-mf="staffQ" value="${esc(M.staffQ)}" type="search" placeholder="Поиск по имени" aria-label="Поиск по имени" class="m-input">
      <div class="m-table"><table><thead><tr><th>Имя</th><th>Точка</th><th class="r">Ставка</th><th>При диспетчере</th><th class="r">Долг</th></tr></thead><tbody>
      ${rows.map((e) => `<tr class="click ${M.staffSel === e.id ? "sel" : ""}" data-m="selStaff" data-id="${e.id}">
        <td><b>${esc(e.name)}</b><div class="sub">${e.kind === "master" ? "Мастер" : "Диспетчер"}</div></td><td>${esc(e.point)}</td>
        <td class="r">${e.rate}%</td><td>${e.kind === "master" ? `${e.rate_with_dispatcher}% от ${e.base_full ? "полной" : "остатка"}` : "—"}</td>
        <td class="r ${e.debt > 0 ? "warn-t" : "sub"}">${e.debt > 0 ? rub(e.debt) : "—"}</td></tr>`).join("") || `<tr><td colspan="5" class="sub">Никого не найдено${q ? ` по запросу «${esc(M.staffQ)}»` : ""}</td></tr>`}
      </tbody></table></div></div>
      ${M.staffForm ? `<div class="m-side">${staffCard()}</div>` : ""}</div>`;
  };

  function staffCard() {
    const f = M.staffForm, isNew = !f.id, isM = f.kind === "master";
    const disp = (M.staff.find((e) => e.kind === "dispatcher" && !e.archived) || { rate: 30 }).rate;
    const amount = 1000000, d = pct(amount, isM ? disp : num(f.rate) || 0);
    const m = isM ? pct(f.base_full ? amount : amount - d, num(f.rate_with_dispatcher) || 0) : pct(amount, 50);
    const a = pct(amount, 5), total = m + d + a;
    return `<div class="card big">
      <div><div class="sub">${isNew ? "Новый сотрудник" : (isM ? "Мастер" : "Диспетчер") + " · " + esc(f.pointName || "")}</div>
        <h2 class="h2">${isNew ? "Добавить" : esc(f.name)}</h2></div>
      ${f.archived ? `<div class="alert ok">Сотрудник удалён. История и отчёты сохранены. ${btn("restoreStaff", "Восстановить", "outline small")}</div>` : ""}
      ${isNew ? `<div class="grid2">${chip(isM, "staffKind", "Мастер", 'data-v="master"')}${chip(!isM, "staffKind", "Диспетчер", 'data-v="dispatcher"')}</div>` : ""}
      ${input("Имя или псевдоним", "staffForm.name", f.name, 'autocomplete="off"')}
      ${input("Телефон", "staffForm.phone", f.phone, 'type="tel"')}
      <div class="label">Точка</div><div class="chips">
        ${isM ? "" : chip(!f.point_id, "staffPoint", "Все точки", 'data-id=""')}
        ${M.points.map((p) => chip(f.point_id === p.id, "staffPoint", esc(p.name), `data-id="${p.id}"`)).join("")}</div>
      ${pctIn("Ставка, %", "staffForm.rate", f.rate)}
      ${isM ? `${pctIn("Ставка, если клиент от диспетчера, %", "staffForm.rate_with_dispatcher", f.rate_with_dispatcher)}
        <div class="label">Считать от</div><div class="grid2">${chip(f.base_full, "staffBase", "полной суммы", 'data-v="1"')}${chip(!f.base_full, "staffBase", "остатка после диспетчера", 'data-v="0"')}</div>` : ""}
      <div class="card lines" style="background:var(--bg)" id="staffExample">
        <div class="title">Пример: сеанс 10 000 ₽ с диспетчером</div>
        <div class="row"><span>Мастеру${isM ? ` (${num(f.rate_with_dispatcher) || 0}% от ${f.base_full ? "полной" : "остатка"})` : " (50%)"}</span><b>${rub(m)}</b></div>
        <div class="row"><span>Диспетчеру (${isM ? disp : num(f.rate) || 0}%)</span><b>${rub(d)}</b></div>
        <div class="row"><span>Администратору (5%)</span><b>${rub(a)}</b></div>
        <div class="row total"><span>Заведению</span><span class="${amount - total < 0 ? "red" : ""}">${rub(amount - total)}</span></div></div>
      ${total > amount ? `<div class="alert warn">Сумма долей — ${Math.round(total / amount * 100)}%. Заведение уходит в минус. Проверьте ставки.</div>` : ""}
      <div class="sub">Изменение ставок не меняет прошлые сеансы — в них сохранена ставка на момент записи.</div>
      ${err()}
      <div class="chips">${btn("saveStaff", isNew ? "Добавить" : "Сохранить")}${btn("closeStaff", "Отмена", "ghost")}</div>
      ${!isNew && !f.archived ? `<div class="m-danger">${f.confirm ? `<div class="alert err">${f.debt > 0 ? `Сначала погасите долг ${rub(f.debt)}: удалить сотрудника с невыплаченными деньгами нельзя.` : "Сотрудник пропадёт из списков на точках. Сеансы, выплаты и отчёты сохранятся. Восстановить можно в любой момент."}
        <div class="chips" style="margin-top:8px">${f.debt > 0 ? "" : btn("archiveStaff", "Да, удалить", "danger small")}${btn("cancelArchive", "Отмена", "ghost small")}</div></div>`
        : btn("askArchive", "Удалить сотрудника", "danger-ghost small")}</div>` : ""}
    </div>`;
  }

  T.admins = () => {
    const d = M.admins;
    if (!d) return loading(null);
    const rows = d.admins.filter((a) => a.archived === M.adminArch);
    const act = d.admins.filter((a) => !a.archived).length;
    return `
    <div class="m-head"><h1 class="big">Администраторы</h1>${btn("newAdmin", "+ Добавить")}</div>
    <div class="chips">${chip(!M.adminArch, "adminArch", "Работают · " + act, 'data-v="0"')}${chip(M.adminArch, "adminArch", "Удалённые · " + (d.admins.length - act), 'data-v="1"')}</div>
    <div class="m-split"><div class="m-main stack">
      ${rows.map((a) => `<button class="chip tile ${M.adminSel === a.id ? "on" : ""}" data-m="selAdmin" data-id="${a.id}" style="width:100%">
        <b>${esc(a.name)} <span style="font-weight:400">· ${esc(a.username)}</span></b>
        <span>${esc(a.point)} · ${a.rate_session}% с сеансов${a.shift ? (a.shift.stale ? " · смена не закрыта" : " · на смене") : ""} · устройств: ${a.devices}</span></button>`).join("") || '<div class="empty">Здесь пока никого нет</div>'}
    </div><div class="m-side">${M.adminNew ? adminNewCard() : M.adminForm ? adminCard() : ""}</div></div>`;
  };

  function adminCard() {
    const f = M.adminForm, a = M.admins.admins.find((x) => x.id === f.id);
    const busy = !!a.shift;
    return `<div class="card big">
      <div><div class="sub">Карточка администратора · ${esc(a.point)}</div><h2 class="h2">${esc(a.name)}</h2></div>
      ${a.archived ? `<div class="alert ok">Администратор удалён, вход закрыт. Чтобы восстановить, задайте новый пароль.</div>
        ${input("Новый пароль (от 10 символов)", "adminPass", M.adminPass, 'type="password" autocomplete="new-password"')}
        ${err()}${btn("restoreAdmin", "Восстановить")}` : `
      <div class="m-grid">
        ${pctIn("% с сеансов", "adminForm.rate_session", f.rate_session)}
        ${pctIn("% с сеанса при диспетчере", "adminForm.rate_session_dispatcher", f.rate_session_dispatcher)}
        ${pctIn("% с сауны", "adminForm.rate_sauna", f.rate_sauna)}
        ${M.admins.categories.map((c) => pctIn(`% с продаж: ${esc(c.name.toLowerCase())}`, `adminForm.cat_${c.id}`, f["cat_" + c.id])).join("")}
      </div>
      <div class="sub">Администратор видит в смене только итог начислений и не может менять ставки.</div>
      ${err()}
      <div class="chips">${btn("saveAdmin", "Сохранить")}${btn("revokeAdmin", "Завершить сессии", "ghost")}</div>
      <div class="m-danger stack">
        ${input("Новый пароль (от 10 символов)", "adminPass", M.adminPass, 'type="password" autocomplete="new-password"')}
        <div class="chips">${btn("passAdmin", "Сменить пароль", "ghost small")}
        ${f.confirm ? "" : btn("askArchiveAdmin", "Удалить администратора", "danger-ghost small")}</div>
        ${f.confirm ? `<div class="alert err">${busy ? "У администратора открыта смена. Сначала её нужно закрыть со сверкой кассы." : "Вход будет закрыт, все его устройства отключатся. Смены и отчёты сохранятся."}
          <div class="chips" style="margin-top:8px">${busy ? "" : btn("archiveAdmin", "Да, удалить", "danger small")}${btn("cancelArchiveAdmin", "Отмена", "ghost small")}</div></div>` : ""}
      </div>`}
    </div>`;
  }

  function adminNewCard() {
    const f = M.adminNew;
    return `<div class="card big"><h2 class="h2">Новый администратор</h2>
      ${input("Имя", "adminNew.first_name", f.first_name, 'autocomplete="off"')}
      ${input("Логин (латиницей)", "adminNew.username", f.username, 'autocomplete="off" autocapitalize="none"')}
      ${input("Пароль (от 10 символов)", "adminNew.password", f.password, 'type="password" autocomplete="new-password"')}
      <div class="label">Точка</div><div class="chips">${M.admins.points.map((p) => chip(f.point_id === p.id, "newAdminPoint", esc(p.name), `data-id="${p.id}"`)).join("")}</div>
      <div class="sub">Ставки по умолчанию: 10% с сеансов, 5% при диспетчере. Поменять можно сразу после создания.</div>
      ${err()}<div class="chips">${btn("createAdmin", "Добавить")}${btn("cancelNewAdmin", "Отмена", "ghost")}</div></div>`;
  }

  T.points = () => {
    if (!M.points) return loading(null);
    return `<div class="m-head"><h1 class="big">Точки и диапазоны ставок</h1></div>
    <p class="note">Администратор может поставить новому мастеру ставку только внутри диапазона своей точки. Вне диапазона ставку ставит управляющий в карточке мастера.</p>
    <div class="m-cards">${M.points.map((p) => {
      const f = M.pointForms[p.id] || { rate_min: p.rate_min, rate_max: p.rate_max, rate_default: p.rate_default };
      M.pointForms[p.id] = f;
      return `<div class="card big"><div class="title" style="font-size:17px">${esc(p.name)}</div>
        <div class="grid3">${pctIn("Мин., %", `pointForms.${p.id}.rate_min`, f.rate_min)}${pctIn("Макс., %", `pointForms.${p.id}.rate_max`, f.rate_max)}${pctIn("По умолч., %", `pointForms.${p.id}.rate_default`, f.rate_default)}</div>
        ${btn("savePoint", "Сохранить", "small", `data-id="${p.id}"`)}</div>`;
    }).join("")}</div>${err()}`;
  };

  T.devices = () => {
    if (!M.devices) return loading(null);
    const active = M.devices.filter((d) => d.active && !d.is_me).length;
    return `<div class="m-head"><div><h1 class="big">Устройства и сессии</h1><div class="sub">Активных устройств сотрудников: ${active}</div></div>
      ${btn("askAll", "Отключить все устройства", "danger")}</div>
    ${M.confirmAll ? `<div class="alert err" role="alertdialog"><b>Отключить все устройства?</b><br>Все сотрудники выйдут из системы, локальные данные на устройствах будут стёрты при следующем запросе. Данные на сервере останутся целы. Ваше устройство не отключится.
      <div class="chips" style="margin-top:10px">${btn("revokeAll", "Да, отключить все", "danger small")}${btn("cancelAll", "Отмена", "ghost small")}</div></div>` : ""}
    ${err()}
    <div class="m-table"><table><thead><tr><th>Сотрудник</th><th>Точка</th><th>Устройство</th><th>Последний вход</th><th>Статус</th><th></th></tr></thead><tbody>
    ${M.devices.map((d) => `<tr class="${d.active ? "" : "dim"}"><td><b>${esc(d.who)}</b><div class="sub">${esc(d.role)}</div></td><td>${esc(d.point)}</td>
      <td>${esc(d.label)}${d.is_new ? ' <span class="badge off-n">новое</span>' : ""}${d.is_me ? ' <span class="badge ok">это вы</span>' : ""}</td>
      <td class="sub">${dayStr(d.last_seen)} ${hm(d.last_seen)}</td><td class="${d.active ? "ok-t" : "red"}">${d.active ? "Разрешено" : "Отключено"}</td>
      <td class="r">${d.is_me ? "" : btn("toggleDevice", d.active ? "Отключить" : "Разрешить", "ghost small", `data-id="${d.id}"`)}</td></tr>`).join("") || '<tr><td colspan="6" class="sub">Устройств пока нет</td></tr>'}
    </tbody></table></div>
    <p class="note">Отключённое устройство при следующем запросе выходит из системы и стирает свои локальные данные. Каждое действие пишется в журнал.</p>`;
  };

  T.reports = () => {
    const r = M.report, t = r && r.totals;
    const preset = (n, label) => chip(false, "repPreset", label, `data-n="${n}"`);
    return `<div class="m-head"><h1 class="big">Отчёты</h1>
      <a class="btn ghost small" href="/api/m/report.xlsx?from=${M.rep.from}&to=${M.rep.to}" download>Выгрузить в Excel</a></div>
    <div class="chips" style="align-items:flex-end">${preset(0, "Сегодня")}${preset(6, "7 дней")}${preset(29, "30 дней")}
      <label class="field" style="width:170px">С<input type="date" data-mf="rep.from" value="${M.rep.from}"></label>
      <label class="field" style="width:170px">По<input type="date" data-mf="rep.to" value="${M.rep.to}"></label>
      ${btn("repLoad", "Показать", "small")}</div>
    ${err()}
    ${!r ? loading(null) : `
    <div class="m-kpis">${[["Выручка", t.revenue], ["Персоналу", t.staff], ["Расходы", t.expenses], ["Прибыль", t.profit]]
      .map(([l, v]) => `<div class="card"><div class="sub">${l}</div><div style="font-size:22px;font-weight:600">${rub(v || 0)}</div></div>`).join("")}</div>
    <div class="m-table"><table><thead><tr><th>Точка</th><th class="r">Смен</th><th class="r">Сеансы</th><th class="r">Доп. продажи</th><th class="r">Персоналу</th><th class="r">Расходы</th><th class="r">Прибыль</th><th class="r">Расхождения</th></tr></thead><tbody>
    ${r.points.map((p) => `<tr><td><b>${esc(p.point)}</b></td><td class="r">${p.shifts}</td><td class="r">${rub(p.sessions)}</td><td class="r">${rub(p.sales)}</td><td class="r">${rub(p.staff)}</td><td class="r">${rub(p.expenses)}</td><td class="r"><b>${rub(p.profit)}</b></td><td class="r ${p.discrepancy ? "red" : "sub"}">${p.discrepancy ? rub(p.discrepancy) : "нет"}</td></tr>`).join("")}
    </tbody></table></div>
    <h2 class="h2">Сотрудники за период</h2>
    <div class="m-table"><table><thead><tr><th>Имя</th><th>Роль</th><th class="r">Сеансов</th><th class="r">Начислено</th><th class="r">Выплачено</th><th class="r">Долг на сегодня</th></tr></thead><tbody>
    ${r.staff.map((s) => `<tr><td><b>${esc(s.name)}</b></td><td>${esc(s.role)}</td><td class="r">${s.sessions || "—"}</td><td class="r">${rub(s.accrued)}</td><td class="r">${rub(s.paid)}</td><td class="r ${s.debt_total > 0 ? "warn-t" : "sub"}">${s.debt_total === null ? "—" : s.debt_total > 0 ? rub(s.debt_total) : "нет"}</td></tr>`).join("") || '<tr><td colspan="6" class="sub">За период начислений нет</td></tr>'}
    </tbody></table></div>
    <p class="note">Начисления администраторов попадают в отчёт после закрытия смены.</p>`}`;
  };

  T.log = () => `<div class="m-head"><h1 class="big">Журнал действий</h1></div>
    <div class="chips"><input data-mf="logQ" value="${esc(M.logQ)}" type="search" placeholder="Поиск по действию или причине" aria-label="Поиск в журнале" class="m-input" style="max-width:360px">${btn("logLoad", "Найти", "small")}</div>
    ${err()}${!M.log ? loading(null) : `<div class="m-table"><table><thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Подробности</th></tr></thead><tbody>
    ${M.log.map((e) => `<tr><td class="sub" style="white-space:nowrap">${dayStr(e.at)} ${hm(e.at)}</td><td>${esc(e.who)}</td><td>${esc(e.action)}</td><td class="sub">${esc(details(e))}</td></tr>`).join("") || '<tr><td colspan="4" class="sub">Записей нет</td></tr>'}
    </tbody></table></div>`}`;

  function details(e) {
    const parts = [];
    const fmt = (o) => Object.entries(o || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
    if (e.old && Object.keys(e.old).length) parts.push("было " + fmt(e.old));
    if (e.new && Object.keys(e.new).length) parts.push((e.old ? "стало " : "") + fmt(e.new));
    if (e.reason) parts.push("причина: " + e.reason);
    return parts.join(" · ");
  }

  // ---------- рендер ----------
  function render() {
    document.body.classList.add("mgr");
    const focused = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.mf;
    const caret = focused ? document.activeElement.selectionStart : null;
    $app.innerHTML = `
    <header class="m-top"><div class="row" style="justify-content:flex-start;gap:12px"><div class="logo" style="width:36px;height:36px;font-size:13px">CRM</div><b>Кабинет управляющего</b></div>
      <div class="row" style="gap:12px"><span class="sub" style="color:#B9C0C8">${esc(M.me.name)}</span><button class="logout" style="color:#fff" data-m="logout">Выйти</button></div></header>
    <div class="m-wrap"><nav class="m-nav" aria-label="Разделы">${NAV.map(([id, label]) => `<button class="${M.tab === id ? "on" : ""}" data-m="tab" data-id="${id}">${label}</button>`).join("")}</nav>
      <main class="m-body">${T[M.tab]()}</main></div>
    ${M.toast ? `<div class="toast" role="status">${esc(M.toast)}</div>` : ""}`;
    if (focused) {
      const el = $app.querySelector(`[data-mf="${focused}"]`);
      if (el) { el.focus(); try { el.setSelectionRange(caret, caret); } catch (e) { /* date */ } }
    }
  }

  function setPath(path, value) {
    const parts = path.split(".");
    let o = M;
    for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]];
    o[parts[parts.length - 1]] = value;
  }

  document.addEventListener("input", (e) => {
    const f = e.target.dataset && e.target.dataset.mf;
    if (!f || !document.body.classList.contains("mgr")) return;
    setPath(f, e.target.value);
    if (M.error) { M.error = ""; const a = $app.querySelector(".alert.err[role=alert]"); if (a) a.remove(); }
    if (f === "staffQ" || f === "shiftQ") render();
    if (f.startsWith("staffForm.rate")) {
      const box = document.getElementById("staffExample");
      if (box) { const html = staffCard(); const tmp = document.createElement("div"); tmp.innerHTML = html; const nb = tmp.querySelector("#staffExample"); if (nb) box.innerHTML = nb.innerHTML; }
    }
  });

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-m]");
    if (!el || !A[el.dataset.m] || !document.body.classList.contains("mgr")) return;
    e.preventDefault();
    A[el.dataset.m](el.dataset);
  });

  const staffToForm = (e) => ({ ...e, pointName: e.point, confirm: false });
  const adminToForm = (a) => {
    const f = { id: a.id, rate_session: a.rate_session, rate_session_dispatcher: a.rate_session_dispatcher, rate_sauna: a.rate_sauna, confirm: false };
    Object.entries(a.categories).forEach(([k, v]) => { f["cat_" + k] = v; });
    return f;
  };
  const refreshAdminForm = () => { if (M.adminForm) { const a = M.admins.admins.find((x) => x.id === M.adminForm.id); if (a) M.adminForm = adminToForm(a); } };

  const A = {
    tab: (d) => run(async () => { M.tab = d.id; M.error = ""; M.confirmAll = false; render(); await load(d.id); }),
    refresh: () => run(() => load(M.tab)),
    logout: () => window.CRM.logout(),

    openShift: (d) => run(async () => { M.shiftQ = ""; M.shiftOpen = await api("GET", `/api/m/shifts/${d.id}/`); }),
    closeShiftPanel: () => { M.shiftOpen = null; render(); },
    toggleShiftStaff: (d) => run(async () => {
      const id = Number(d.id), sh = M.shiftOpen.shift;
      const r = await api("POST", `/api/m/shifts/${sh.id}/staff/`, { employee_id: id, present: !sh.attendance.includes(id) });
      M.shiftOpen.shift = Object.assign(sh, r.shift);
      await load("summary");
    }),

    staffArch: (d) => { M.staffArch = d.v === "1"; M.staffForm = null; M.staffSel = null; render(); },
    selStaff: (d) => { const e = M.staff.find((x) => x.id === Number(d.id)); M.staffSel = e.id; M.staffForm = staffToForm(e); M.error = ""; render(); },
    newStaff: () => {
      const p = M.points[0];
      M.staffSel = null; M.error = "";
      M.staffForm = { kind: "master", name: M.staffQ.trim(), phone: "", point_id: p ? p.id : null, rate: p ? p.rate_default : 50, rate_with_dispatcher: p ? p.rate_default : 50, base_full: true };
      render();
    },
    staffKind: (d) => { const f = M.staffForm; f.kind = d.v; if (d.v === "dispatcher") { f.point_id = null; f.rate = 30; } else { f.point_id = M.points[0].id; f.rate = 50; } render(); },
    staffPoint: (d) => { M.staffForm.point_id = d.id ? Number(d.id) : null; render(); },
    staffBase: (d) => { M.staffForm.base_full = d.v === "1"; render(); },
    closeStaff: () => { M.staffForm = null; M.staffSel = null; render(); },
    saveStaff: () => run(async () => {
      const f = M.staffForm;
      const body = { name: f.name, phone: f.phone, point_id: f.point_id, rate: num(f.rate), rate_with_dispatcher: num(f.rate_with_dispatcher ?? f.rate), base_full: f.base_full };
      if ([body.rate, body.rate_with_dispatcher].some((v) => v === null)) throw new Error("Ставки — числа от 0 до 100.");
      const r = f.id ? await api("POST", `/api/m/staff/${f.id}/`, body) : await api("POST", "/api/m/staff/new/", { ...body, kind: f.kind });
      await load("staff");
      const e = M.staff.find((x) => x.id === r.employee.id);
      M.staffSel = e.id; M.staffForm = staffToForm(e);
      flash(f.id ? "Сохранено и записано в журнал" : `${e.name} добавлен(а)`);
    }),
    askArchive: () => { M.staffForm.confirm = true; render(); },
    cancelArchive: () => { M.staffForm.confirm = false; render(); },
    archiveStaff: () => run(async () => {
      await api("POST", `/api/m/staff/${M.staffForm.id}/archive/`, {});
      await load("staff"); M.staffForm = null; M.staffSel = null; flash("Сотрудник перенесён в архив");
    }),
    restoreStaff: () => run(async () => {
      await api("POST", `/api/m/staff/${M.staffForm.id}/archive/`, { restore: true });
      await load("staff"); M.staffArch = false; const e = M.staff.find((x) => x.id === M.staffForm.id); M.staffForm = staffToForm(e); flash("Сотрудник восстановлен");
    }),

    adminArch: (d) => { M.adminArch = d.v === "1"; M.adminForm = null; M.adminSel = null; M.adminNew = null; render(); },
    selAdmin: (d) => { const a = M.admins.admins.find((x) => x.id === Number(d.id)); M.adminSel = a.id; M.adminNew = null; M.adminForm = adminToForm(a); M.adminPass = ""; M.error = ""; render(); },
    saveAdmin: () => run(async () => {
      const f = M.adminForm, cats = {};
      M.admins.categories.forEach((c) => { cats[c.id] = num(f["cat_" + c.id]); });
      const body = { rate_session: num(f.rate_session), rate_session_dispatcher: num(f.rate_session_dispatcher), rate_sauna: num(f.rate_sauna), categories: cats };
      if ([body.rate_session, body.rate_session_dispatcher, body.rate_sauna, ...Object.values(cats)].some((v) => v === null)) throw new Error("Ставки — числа от 0 до 100.");
      M.admins = await api("POST", `/api/m/admins/${f.id}/`, body); refreshAdminForm(); flash("Ставки сохранены и записаны в журнал");
    }),
    revokeAdmin: () => run(async () => { M.admins = await api("POST", `/api/m/admins/${M.adminForm.id}/revoke/`, {}); refreshAdminForm(); flash("Все сессии администратора завершены"); }),
    passAdmin: () => run(async () => {
      if (M.adminPass.length < 10) throw new Error("Пароль — не короче 10 символов.");
      M.admins = await api("POST", `/api/m/admins/${M.adminForm.id}/password/`, { password: M.adminPass }); M.adminPass = ""; refreshAdminForm(); flash("Пароль изменён, старые сессии завершены");
    }),
    askArchiveAdmin: () => { M.adminForm.confirm = true; render(); },
    cancelArchiveAdmin: () => { M.adminForm.confirm = false; render(); },
    archiveAdmin: () => run(async () => { M.admins = await api("POST", `/api/m/admins/${M.adminForm.id}/archive/`, {}); M.adminForm = null; M.adminSel = null; flash("Администратор удалён, вход закрыт"); }),
    restoreAdmin: () => run(async () => {
      if (M.adminPass.length < 10) throw new Error("Задайте новый пароль — не короче 10 символов.");
      M.admins = await api("POST", `/api/m/admins/${M.adminForm.id}/restore/`, { password: M.adminPass });
      M.adminPass = ""; M.adminArch = false; refreshAdminForm(); flash("Администратор восстановлен");
    }),
    newAdmin: () => { M.adminForm = null; M.adminSel = null; M.error = ""; M.adminNew = { first_name: "", username: "", password: "", point_id: M.admins.points[0] && M.admins.points[0].id }; render(); },
    newAdminPoint: (d) => { M.adminNew.point_id = Number(d.id); render(); },
    cancelNewAdmin: () => { M.adminNew = null; render(); },
    createAdmin: () => run(async () => {
      const f = M.adminNew;
      if (!f.first_name.trim() || !f.username.trim()) throw new Error("Укажите имя и логин.");
      if (f.password.length < 10) throw new Error("Пароль — не короче 10 символов.");
      M.admins = await api("POST", "/api/m/admins/new/", f);
      const a = M.admins.admins.find((x) => x.username === f.username.trim().toLowerCase());
      M.adminNew = null; if (a) { M.adminSel = a.id; M.adminForm = adminToForm(a); }
      flash("Администратор добавлен");
    }),

    savePoint: (d) => run(async () => {
      const f = M.pointForms[d.id];
      const body = { rate_min: num(f.rate_min), rate_max: num(f.rate_max), rate_default: num(f.rate_default) };
      if (Object.values(body).some((v) => v === null)) throw new Error("Укажите числа.");
      M.points = (await api("POST", `/api/m/points/${d.id}/`, body)).points; M.pointForms = {}; flash("Диапазон сохранён");
    }),

    askAll: () => { M.confirmAll = true; render(); },
    cancelAll: () => { M.confirmAll = false; render(); },
    revokeAll: () => run(async () => { M.devices = (await api("POST", "/api/m/devices/revoke-all/", { confirm: true })).devices; M.confirmAll = false; flash("Все устройства сотрудников отключены"); }),
    toggleDevice: (d) => run(async () => { M.devices = (await api("POST", `/api/m/devices/${d.id}/toggle/`, {})).devices; }),

    repPreset: (d) => run(async () => { M.rep.to = today(); M.rep.from = shiftDays(M.rep.to, -Number(d.n)); M.report = null; render(); await load("reports"); }),
    repLoad: () => run(async () => { M.report = null; render(); await load("reports"); }),
    logLoad: () => run(() => load("log")),
  };

  window.ManagerApp = {
    start(me) {
      M.me = me;
      render();
      run(() => load("summary"));
    },
  };
})();
