"""Бизнес-операции. Любое изменение данных идёт через эти функции:
здесь проверяются права и правила ТЗ, считаются деньги и пишется журнал.
"""
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from . import calc
from .models import (
    Attendance, AuditLog, Device, Employee, Expense, Payout, PaymentMethod, RecordStatus,
    Sale, Session, Shift, User,
)


# ---------- журнал ----------

def audit(actor, action, obj=None, *, old=None, new=None, reason="", ip=None):
    AuditLog.objects.create(
        actor=actor, action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        old=old, new=new, reason=reason, ip=ip,
    )


# ---------- права ----------

def require_manager(user):
    if not (user.is_authenticated and user.is_manager):
        raise PermissionDenied("Действие доступно только управляющему.")


def require_shift_admin(user, shift):
    if user.role != User.Role.ADMIN or shift.admin_id != user.id:
        raise PermissionDenied("Это не ваша смена.")
    # Статус берём из базы, а не из объекта в памяти: смену могли закрыть с другого устройства
    if not Shift.objects.filter(pk=shift.pk, status=Shift.Status.OPEN).exists():
        raise ValidationError("Смена закрыта. Исправления вносит управляющий.")


# ---------- смена ----------

@transaction.atomic
def open_shift(admin, opening_cash: int):
    if admin.role != User.Role.ADMIN or admin.archived_at:
        raise PermissionDenied("Открыть смену может только администратор точки.")
    if Shift.objects.filter(point=admin.point, status=Shift.Status.OPEN).exists():
        raise ValidationError("На точке уже открыта смена. Сначала закройте её.")
    shift = Shift.objects.create(point=admin.point, admin=admin, opening_cash=opening_cash)
    audit(admin, "Открыл смену", shift, new={"opening_cash": opening_cash})
    return shift


def mark_attendance(user, shift, employee, present=True):
    """Отметить мастера на смене. Можно в любой момент смены и мастера с другой точки (подмена).

    Отмечает администратор своей открытой смены или управляющий любой открытой смены.
    """
    if user.is_authenticated and user.is_manager:
        if not Shift.objects.filter(pk=shift.pk, status=Shift.Status.OPEN).exists():
            raise ValidationError("Смена уже закрыта.")
    else:
        require_shift_admin(user, shift)
    if employee.kind != Employee.Kind.MASTER or employee.is_archived:
        raise ValidationError("Отметить на смене можно только работающего мастера.")
    if present:
        busy = (Attendance.objects.filter(employee=employee, shift__status=Shift.Status.OPEN)
                .exclude(shift=shift).select_related("shift__point").first())
        if busy:
            raise ValidationError(f"{employee.name} уже на смене: {busy.shift.point.name}.")
        _, created = Attendance.objects.get_or_create(shift=shift, employee=employee)
        if created and (user.is_manager or employee.point_id != shift.point_id):
            audit(user, f"Добавил на смену: {employee.name}", shift,
                  new={"point": shift.point.name, "home_point": employee.point.name if employee.point_id else None})
    else:
        if shift.sessions.filter(master=employee, status=RecordStatus.OK).exists():
            raise ValidationError(f"У {employee.name} есть сеансы в этой смене. Снять с неё нельзя.")
        Attendance.objects.filter(shift=shift, employee=employee).delete()


def _admin_rates(admin):
    return calc.AdminRates(session=admin.rate_session,
                           session_with_dispatcher=admin.rate_session_dispatcher,
                           sauna=admin.rate_sauna)


def create_session(admin, shift, *, room, start, end, amount: int, payment_method,
                   master=None, dispatcher=None, program=None, id=None, client_created_at=None):
    """Записать сеанс. Повторный вызов с тем же id вернёт уже созданную запись."""
    if id is not None:
        existing = Session.objects.filter(pk=id).first()
        if existing:
            return existing
    require_shift_admin(admin, shift)
    if room.point_id != shift.point_id:
        raise ValidationError("Комната с другой точки.")
    if payment_method not in PaymentMethod.values:
        raise ValidationError("Неизвестный способ оплаты.")
    if end <= start:
        raise ValidationError("Конец сеанса должен быть позже начала.")

    master_rates = None
    disp_rate = None
    if room.is_sauna:
        if master or dispatcher:
            raise ValidationError("В сауне нет мастера и диспетчера.")
        admin_rate = admin.rate_sauna
    else:
        if master is None:
            raise ValidationError("Выберите мастера.")
        if not Attendance.objects.filter(shift=shift, employee=master).exists():
            raise ValidationError(f"{master.name} не отмечен(а) на смене. Сначала отметьте мастера.")
        master_rates = calc.MasterRates(rate=master.rate, rate_with_dispatcher=master.rate_with_dispatcher,
                                        base_full=master.base_full)
        if dispatcher is not None:
            if dispatcher.kind != Employee.Kind.DISPATCHER or dispatcher.is_archived:
                raise ValidationError("Выбранный сотрудник не диспетчер.")
            disp_rate = dispatcher.rate
        admin_rate = admin.rate_session_dispatcher if dispatcher else admin.rate_session

    shares = calc.session_shares(amount, is_sauna=room.is_sauna, admin=_admin_rates(admin),
                                 master=master_rates, dispatcher_rate=disp_rate)
    session = Session(
        shift=shift, room=room, master=master, dispatcher=dispatcher, program=program,
        start=start, end=end, amount=amount, payment_method=payment_method,
        master_rate=(master.rate_with_dispatcher if dispatcher else master.rate) if master else None,
        master_base_full=master.base_full if (master and dispatcher) else None,
        dispatcher_rate=disp_rate, admin_rate=admin_rate,
        master_share=shares.master, dispatcher_share=shares.dispatcher, admin_share=shares.admin,
        created_by=admin, client_created_at=client_created_at,
    )
    if id is not None:
        session.id = id
    try:
        with transaction.atomic():
            session.save()
    except IntegrityError as exc:
        text = str(exc)
        if "session_room_no_overlap" in text:
            raise ValidationError(f"{room.name} в это время уже занята.") from exc
        if "session_master_no_overlap" in text:
            raise ValidationError(f"{master.name} в это время уже в другом сеансе.") from exc
        raise
    audit(admin, "Записал сеанс", session, new={"amount": amount, "room": room.name,
                                               "master": master.name if master else None})
    return session


def create_sale(admin, shift, *, product, quantity: int, payment_method, id=None, client_created_at=None):
    if id is not None and Sale.objects.filter(pk=id).exists():
        return Sale.objects.get(pk=id)
    require_shift_admin(admin, shift)
    if quantity < 1:
        raise ValidationError("Количество должно быть не меньше 1.")
    amount = product.price * quantity
    rate = admin.admin_rate_for(product.category)
    sale = Sale(shift=shift, product=product, quantity=quantity, price=product.price, amount=amount,
                payment_method=payment_method, admin_rate=rate,
                admin_share=calc.sale_admin_share(amount, rate),
                created_by=admin, client_created_at=client_created_at)
    if id is not None:
        sale.id = id
    sale.save()
    audit(admin, "Записал продажу", sale, new={"product": product.name, "amount": amount})
    return sale


def create_expense(admin, shift, *, category, amount: int, payment_method, comment="", id=None,
                   client_created_at=None):
    if id is not None and Expense.objects.filter(pk=id).exists():
        return Expense.objects.get(pk=id)
    require_shift_admin(admin, shift)
    if amount <= 0:
        raise ValidationError("Укажите сумму расхода.")
    exp = Expense(shift=shift, category=category, amount=amount, payment_method=payment_method,
                  comment=comment, created_by=admin, client_created_at=client_created_at)
    if id is not None:
        exp.id = id
    exp.save()
    audit(admin, "Записал расход", exp, new={"category": category.name, "amount": amount})
    return exp


def cancel_record(user, record, reason: str):
    """Отмена вместо удаления. Администратор — только в своей открытой смене."""
    if not reason.strip():
        raise ValidationError("Укажите причину отмены.")
    if user.is_manager:
        record.shift.corrected = record.shift.status == Shift.Status.CLOSED
        record.shift.save(update_fields=["corrected"])
    else:
        require_shift_admin(user, record.shift)
    if record.status == RecordStatus.CANCELLED:
        return record
    record.status = RecordStatus.CANCELLED
    record.cancel_reason = reason
    record.save(update_fields=["status", "cancel_reason"])
    audit(user, f"Отменил запись: {record._meta.verbose_name}", record, reason=reason)
    return record


# ---------- выплаты и закрытие ----------

def shift_accruals(shift):
    """Начислено за смену: {("employee", id) | ("admin", id): копейки}."""
    acc = defaultdict(int)
    for s in shift.sessions.filter(status=RecordStatus.OK):
        if s.master_id:
            acc[("employee", s.master_id)] += s.master_share
        if s.dispatcher_id:
            acc[("employee", s.dispatcher_id)] += s.dispatcher_share
        acc[("admin", shift.admin_id)] += s.admin_share
    for sale in shift.sales.filter(status=RecordStatus.OK):
        acc[("admin", shift.admin_id)] += sale.admin_share
    acc.setdefault(("admin", shift.admin_id), 0)
    return dict(acc)


def _cash_sum(qs):
    return qs.filter(status=RecordStatus.OK, payment_method=PaymentMethod.CASH).aggregate(t=Sum("amount"))["t"] or 0


def expected_cash_for(shift, cash_payouts: int):
    return calc.expected_cash(
        opening=shift.opening_cash,
        cash_sessions=_cash_sum(shift.sessions),
        cash_sales=_cash_sum(shift.sales),
        cash_expenses=_cash_sum(shift.expenses),
        cash_payouts=cash_payouts,
    )


@transaction.atomic
def close_shift(admin, shift, *, paid: dict, actual_cash: int, comment=""):
    """Закрыть смену. paid = {ключ из shift_accruals: выплачено наличными, копейки}.

    Каждый, кому начислено, должен быть отмечен: выплачено полностью, частично или 0 (в долг).
    """
    shift = Shift.objects.select_for_update().get(pk=shift.pk)
    require_shift_admin(admin, shift)
    accruals = shift_accruals(shift)
    missing = [k for k in accruals if k not in paid]
    if missing:
        raise ValidationError("Отметьте выплату каждому: выплачено или в долг.")
    for key, value in paid.items():
        if key not in accruals:
            raise ValidationError("Выплата тому, кому ничего не начислено.")
        if value < 0 or value > accruals[key]:
            raise ValidationError("Выплата не может быть больше начисленного.")

    cash_payouts = sum(paid.values())
    expected = expected_cash_for(shift, cash_payouts)
    diff = calc.cash_discrepancy(actual=actual_cash, expected=expected)
    if diff != 0 and not comment.strip():
        raise ValidationError("Укажите причину расхождения кассы.")

    for (kind, pk), accrued in accruals.items():
        Payout.objects.create(
            shift=shift, accrued=accrued, paid=paid[(kind, pk)],
            employee_id=pk if kind == "employee" else None,
            admin_id=pk if kind == "admin" else None,
        )
    shift.status = Shift.Status.CLOSED
    shift.closed_at = timezone.now()
    shift.expected_cash = expected
    shift.actual_cash = actual_cash
    shift.discrepancy = diff
    shift.close_comment = comment
    shift.save()
    audit(admin, "Закрыл смену" + (" с расхождением" if diff else ""), shift,
          new={"expected": expected, "actual": actual_cash, "diff": diff}, reason=comment)
    return shift


def employee_debt(employee) -> int:
    agg = Payout.objects.filter(employee=employee).aggregate(a=Sum("accrued"), p=Sum("paid"))
    return calc.debt(accrued=agg["a"] or 0, paid=agg["p"] or 0)


# ---------- сотрудники ----------

def add_employee(user, *, kind, name, phone="", point=None, rate=None, rate_with_dispatcher=None,
                 base_full=True):
    name = name.strip()
    if not name:
        raise ValidationError("Укажите имя или псевдоним.")
    # Сравнение в Python: не зависит от того, как локаль базы понимает регистр кириллицы
    active_names = Employee.objects.filter(archived_at__isnull=True).values_list("name", flat=True)
    if any(n.casefold() == name.casefold() for n in active_names):
        raise ValidationError(f"Сотрудник «{name}» уже есть. Найдите его через поиск.")
    if user.role == User.Role.ADMIN:
        if kind != Employee.Kind.MASTER:
            raise PermissionDenied("Администратор добавляет только мастеров.")
        point = user.point
        rate = Decimal(str(rate if rate is not None else point.rate_default))
        if not calc.rate_in_range(rate, point.rate_min, point.rate_max):
            raise ValidationError(f"Ставка должна быть в диапазоне точки {point.rate_min}–{point.rate_max}%. "
                                  "Другую ставку может поставить только управляющий.")
        rate_with_dispatcher = rate
        base_full = True
    else:
        require_manager(user)
    emp = Employee.objects.create(
        kind=kind, name=name, phone=phone, point=point, rate=rate,
        rate_with_dispatcher=rate_with_dispatcher if rate_with_dispatcher is not None else rate,
        base_full=base_full, created_by=user,
    )
    audit(user, "Добавил сотрудника", emp, new={"name": name, "kind": kind, "rate": str(rate)})
    return emp


def archive_employee(manager, employee):
    require_manager(manager)
    d = employee_debt(employee)
    if d > 0:
        raise ValidationError(f"Сначала погасите долг {d / 100:.2f} ₽.")
    employee.archived_at = timezone.now()
    employee.save(update_fields=["archived_at"])
    audit(manager, "Удалил сотрудника (в архив)", employee)


def restore_employee(manager, employee):
    require_manager(manager)
    employee.archived_at = None
    try:
        with transaction.atomic():
            employee.save(update_fields=["archived_at"])
    except IntegrityError as exc:
        raise ValidationError("Среди работающих уже есть сотрудник с таким именем.") from exc
    audit(manager, "Восстановил сотрудника", employee)


def archive_admin(manager, admin):
    require_manager(manager)
    if Shift.objects.filter(admin=admin, status=Shift.Status.OPEN).exists():
        raise ValidationError("У администратора открыта смена. Сначала закройте её со сверкой кассы.")
    admin.archived_at = timezone.now()
    admin.is_active = False
    admin.save(update_fields=["archived_at", "is_active"])
    revoke_devices(manager, Device.objects.filter(user=admin), reason="администратор удалён")
    audit(manager, "Удалил администратора (в архив)", admin)


# ---------- устройства ----------

def revoke_devices(manager, devices, reason=""):
    require_manager(manager)
    now = timezone.now()
    n = devices.filter(is_active=True).update(is_active=False, revoked_at=now)
    if n:
        audit(manager, f"Отключил устройства: {n}", reason=reason)
    return n


def revoke_all_devices(manager):
    """Кнопка «Отключить все». Данные на сервере не трогаются."""
    return revoke_devices(manager, Device.objects.exclude(user=manager), reason="отключены все устройства")


# ---------- кабинет управляющего ----------

EMPLOYEE_FIELDS = ("name", "phone", "point_id", "rate", "rate_with_dispatcher", "base_full")
ADMIN_RATE_FIELDS = ("rate_session", "rate_session_dispatcher", "rate_sauna")


def _pct_value(value, label):
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception as exc:  # noqa: BLE001 — любое нечисло
        raise ValidationError(f"{label}: нужно число.") from exc
    if d < 0 or d > 100:
        raise ValidationError(f"{label}: от 0 до 100%.")
    return d.quantize(Decimal("0.01"))


@transaction.atomic
def update_employee(manager, employee, data):
    """Правка карточки сотрудника управляющим. Прошлые сеансы не меняются: ставки в них — снимок."""
    require_manager(manager)
    old = {f: str(getattr(employee, f)) for f in EMPLOYEE_FIELDS}
    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            raise ValidationError("Укажите имя.")
        others = Employee.objects.filter(archived_at__isnull=True).exclude(pk=employee.pk).values_list("name", flat=True)
        if any(n.casefold() == name.casefold() for n in others):
            raise ValidationError(f"Сотрудник «{name}» уже есть.")
        employee.name = name
    if "phone" in data:
        employee.phone = str(data["phone"])[:32]
    if "point_id" in data:
        if employee.kind == Employee.Kind.MASTER and not data["point_id"]:
            raise ValidationError("Мастеру нужна точка.")
        employee.point_id = data["point_id"] or None
    if "rate" in data:
        employee.rate = _pct_value(data["rate"], "Ставка")
    if "rate_with_dispatcher" in data:
        employee.rate_with_dispatcher = _pct_value(data["rate_with_dispatcher"], "Ставка при диспетчере")
    if "base_full" in data:
        employee.base_full = bool(data["base_full"])
    employee.save()
    new = {f: str(getattr(employee, f)) for f in EMPLOYEE_FIELDS}
    changed = {k: v for k, v in new.items() if old[k] != v}
    if changed:
        audit(manager, f"Изменил карточку: {employee.name}", employee,
              old={k: old[k] for k in changed}, new=changed)
    return employee


@transaction.atomic
def update_admin(manager, admin, data):
    require_manager(manager)
    if admin.role != User.Role.ADMIN:
        raise ValidationError("Это не администратор.")
    old = {f: str(getattr(admin, f)) for f in ADMIN_RATE_FIELDS}
    labels = {"rate_session": "% с сеансов", "rate_session_dispatcher": "% при диспетчере", "rate_sauna": "% с сауны"}
    for f in ADMIN_RATE_FIELDS:
        if f in data:
            setattr(admin, f, _pct_value(data[f], labels[f]))
    if "first_name" in data and str(data["first_name"]).strip():
        admin.first_name = str(data["first_name"]).strip()[:150]
    if "point_id" in data and data["point_id"]:
        if Shift.objects.filter(admin=admin, status=Shift.Status.OPEN).exists():
            raise ValidationError("Нельзя перевести на другую точку во время открытой смены.")
        admin.point_id = data["point_id"]
    admin.save()
    cats = data.get("categories") or {}
    from .models import AdminCategoryRate, ProductCategory
    for cat, value in cats.items():
        if cat not in ProductCategory.values:
            raise ValidationError("Неизвестная категория товара.")
        AdminCategoryRate.objects.update_or_create(admin=admin, category=cat,
                                                   defaults={"rate": _pct_value(value, "Ставка с продаж")})
    new = {f: str(getattr(admin, f)) for f in ADMIN_RATE_FIELDS}
    audit(manager, f"Изменил ставки администратора: {admin.first_name or admin.username}", admin,
          old=old, new=dict(new, categories={k: str(v) for k, v in cats.items()}))
    return admin


def _check_password(password, user=None):
    from django.contrib.auth.password_validation import validate_password
    validate_password(password, user)


@transaction.atomic
def create_admin(manager, *, username, first_name, point, password):
    require_manager(manager)
    username = str(username).strip().lower()
    if not username or User.objects.filter(username__iexact=username).exists():
        raise ValidationError("Такой логин уже занят или пуст.")
    user = User(username=username, first_name=str(first_name).strip(), role=User.Role.ADMIN, point=point)
    _check_password(password, user)
    user.set_password(password)
    user.save()
    audit(manager, f"Добавил администратора: {user.first_name or username}", user, new={"point": point.name})
    return user


def set_password(manager, user, password):
    require_manager(manager)
    if user.role != User.Role.ADMIN:
        raise PermissionDenied("Управляющий меняет пароли только администраторам.")
    _check_password(password, user)
    user.set_password(password)
    user.save(update_fields=["password"])
    revoke_devices(manager, Device.objects.filter(user=user), reason="смена пароля")
    audit(manager, f"Сменил пароль: {user.first_name or user.username}", user)


@transaction.atomic
def restore_admin(manager, admin, password):
    require_manager(manager)
    _check_password(password, admin)
    admin.archived_at = None
    admin.is_active = True
    admin.set_password(password)
    admin.save(update_fields=["archived_at", "is_active", "password"])
    audit(manager, f"Восстановил администратора: {admin.first_name or admin.username}", admin)


def update_point_range(manager, point, *, rate_min, rate_max, rate_default):
    require_manager(manager)
    mn, mx = _pct_value(rate_min, "Минимум"), _pct_value(rate_max, "Максимум")
    df = _pct_value(rate_default, "По умолчанию")
    if not (mn <= df <= mx):
        raise ValidationError("Нужно: минимум ≤ по умолчанию ≤ максимум.")
    old = {"min": str(point.rate_min), "max": str(point.rate_max), "default": str(point.rate_default)}
    point.rate_min, point.rate_max, point.rate_default = mn, mx, df
    point.save(update_fields=["rate_min", "rate_max", "rate_default"])
    audit(manager, f"Изменил диапазон ставок: {point.name}", point, old=old,
          new={"min": str(mn), "max": str(mx), "default": str(df)})


def allow_device(manager, device):
    require_manager(manager)
    if device.user.archived_at:
        raise ValidationError("Пользователь удалён — сначала восстановите его.")
    device.is_active = True
    device.revoked_at = None
    device.save(update_fields=["is_active", "revoked_at"])
    audit(manager, f"Разрешил устройство: {device.user.first_name or device.user.username}", device)
