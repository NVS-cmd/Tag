"""JSON API для приложения администратора.

Все суммы — копейки. Права проверяются здесь и ещё раз в services.py.
CSRF: приложение берёт токен из cookie `csrftoken` и шлёт в заголовке X-CSRFToken.
"""
import json
import uuid
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import services
from .middleware import DEVICE_SESSION_KEY
from .models import (
    AuditLog, Device, Employee, Expense, ExpenseCategory, PaymentMethod, Product, Program, RecordStatus,
    Room, Sale, Session, Shift, User,
)

LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 15 * 60
SESSION_SECONDS = {User.Role.ADMIN: 12 * 3600, User.Role.MANAGER: 30 * 60, User.Role.SUPERADMIN: 30 * 60}


# ---------- обвязка ----------

def _error(detail, status):
    return JsonResponse({"detail": detail}, status=status)


def api(roles=None):
    """Проверка входа и роли, разбор JSON, перевод ошибок правил в понятные ответы."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _error("Войдите в систему.", 401)
            if roles and request.user.role not in roles:
                return _error("Недостаточно прав.", 403)
            if request.method == "POST":
                try:
                    request.data = json.loads(request.body or b"{}")
                except ValueError:
                    return _error("Неверный формат запроса.", 400)
            try:
                return view(request, *args, **kwargs)
            except ValidationError as exc:
                return _error(" ".join(exc.messages), 400)
            except PermissionDenied as exc:
                return _error(str(exc) or "Недостаточно прав.", 403)
            except ObjectDoesNotExist:
                return _error("Запись не найдена.", 404)
        return wrapper
    return deco


def _int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Поле «{field}» должно быть целым числом копеек.")
    return value


def _dt(value, field):
    dt = parse_datetime(value) if isinstance(value, str) else None
    if dt is None:
        raise ValidationError(f"Поле «{field}»: неверная дата и время.")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _uuid(value):
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValidationError("Неверный идентификатор записи.") from exc


def _client_ip(request):
    return request.META.get("REMOTE_ADDR")


# ---------- вход ----------

def _user_json(user):
    return {
        "id": user.id, "username": user.username, "name": user.first_name or user.username, "role": user.role,
        "point": {"id": user.point_id, "name": user.point.name} if user.point_id else None,
    }


@require_GET
@ensure_csrf_cookie
def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})
    return JsonResponse({"authenticated": True, "user": _user_json(request.user)})


@require_POST
def login_view(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return _error("Неверный формат запроса.", 400)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    lock_key = f"login-fails:{username.lower()}:{_client_ip(request)}"
    if cache.get(lock_key, 0) >= LOGIN_MAX_FAILS:
        return _error("Слишком много неудачных попыток. Попробуйте через 15 минут.", 429)

    user = authenticate(request, username=username, password=password)
    if user is None or user.archived_at:
        cache.set(lock_key, cache.get(lock_key, 0) + 1, LOGIN_LOCK_SECONDS)
        return _error("Неверный логин или пароль.", 400)

    device = None
    device_id = _uuid(data.get("device_id")) if data.get("device_id") else None
    if device_id:
        device = Device.objects.filter(pk=device_id).first()
        if device and device.user_id != user.id:
            device = None
            device_id = None
        if device and not device.is_active:
            return _error("Это устройство отключено управляющим. Обратитесь к управляющему.", 403)
    is_new = device is None
    if is_new:
        device = Device.objects.create(pk=device_id or uuid.uuid4(), user=user,
                                       label=str(data.get("device_label", ""))[:200], last_ip=_client_ip(request))

    cache.delete(lock_key)
    login(request, user)
    request.session[DEVICE_SESSION_KEY] = str(device.pk)
    request.session.set_expiry(SESSION_SECONDS.get(user.role, 1800))
    if is_new:
        AuditLog.objects.create(actor=user, action="Вход с нового устройства", object_type="Device",
                                object_id=str(device.pk), new={"label": device.label}, ip=_client_ip(request))
    return JsonResponse({"user": _user_json(user), "device_id": str(device.pk)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


# ---------- состояние для администратора ----------

def _session_json(s):
    return {
        "id": str(s.id), "room_id": s.room_id, "room": s.room.name, "is_sauna": s.room.is_sauna,
        "master_id": s.master_id, "master": s.master.name if s.master_id else None,
        "dispatcher_id": s.dispatcher_id, "dispatcher": s.dispatcher.name if s.dispatcher_id else None,
        "program": s.program.name if s.program_id else None,
        "start": s.start.isoformat(), "end": s.end.isoformat(), "amount": s.amount,
        "payment_method": s.payment_method, "status": s.status, "cancel_reason": s.cancel_reason,
        "master_share": s.master_share, "dispatcher_share": s.dispatcher_share, "admin_share": s.admin_share,
    }


def _sale_json(x):
    return {"id": str(x.id), "product": x.product.name, "quantity": x.quantity, "amount": x.amount,
            "payment_method": x.payment_method, "admin_share": x.admin_share, "status": x.status,
            "cancel_reason": x.cancel_reason}


def _expense_json(e):
    return {"id": str(e.id), "category": e.category.name, "amount": e.amount, "comment": e.comment,
            "payment_method": e.payment_method, "status": e.status, "cancel_reason": e.cancel_reason}


def _sum(qs, **flt):
    return qs.filter(status=RecordStatus.OK, **flt).aggregate(t=Sum("amount"))["t"] or 0


def shift_json(shift):
    sessions = shift.sessions.select_related("room", "master", "dispatcher", "program").order_by("start")
    sales = shift.sales.select_related("product").order_by("created_at")
    expenses = shift.expenses.select_related("category").order_by("created_at")
    names = {e.id: e for e in Employee.objects.filter(
        id__in=[pk for kind, pk in services.shift_accruals(shift) if kind == "employee"])}
    accruals = []
    for (kind, pk), amount in services.shift_accruals(shift).items():
        if kind == "employee":
            emp = names[pk]
            role = ("Мастер" if emp.kind == Employee.Kind.MASTER else "Диспетчер") + f" · {emp.rate.normalize()}%"
            accruals.append({"key": f"employee:{pk}", "name": emp.name, "role": role, "amount": amount})
        else:
            accruals.append({"key": f"admin:{pk}", "name": f"{shift.admin.first_name} (вы)",
                             "role": "Администратор · по карточке", "amount": amount})
    by_method = {m: _sum(shift.sessions, payment_method=m) + _sum(shift.sales, payment_method=m)
                 for m in PaymentMethod.values}
    return {
        "id": shift.id, "status": shift.status, "opened_at": shift.opened_at.isoformat(),
        "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
        "opening_cash": shift.opening_cash,
        "attendance": list(shift.attendance.values_list("employee_id", flat=True)),
        "sessions": [_session_json(s) for s in sessions],
        "sales": [_sale_json(x) for x in sales],
        "expenses": [_expense_json(e) for e in expenses],
        "accruals": accruals,
        "cash": {
            "opening": shift.opening_cash,
            "sessions": _sum(shift.sessions, payment_method=PaymentMethod.CASH),
            "sales": _sum(shift.sales, payment_method=PaymentMethod.CASH),
            "expenses": _sum(shift.expenses, payment_method=PaymentMethod.CASH),
        },
        "totals": {
            "revenue": sum(by_method.values()), "by_method": by_method,
            "staff": sum(a["amount"] for a in accruals), "expenses": _sum(shift.expenses),
        },
        "expected_cash": shift.expected_cash, "actual_cash": shift.actual_cash,
        "discrepancy": shift.discrepancy, "close_comment": shift.close_comment,
    }


@require_GET
@api(roles=[User.Role.ADMIN])
def admin_state(request):
    user = request.user
    point = user.point
    shift = Shift.objects.filter(point=point, status=Shift.Status.OPEN).first()
    if shift and shift.admin_id != user.id:
        other = shift.admin.first_name or shift.admin.username
        return _error(f"На точке открыта смена администратора {other}. Сначала её нужно закрыть.", 409)
    pct = lambda d: float(d)  # noqa: E731 — ставки в JSON как числа
    return JsonResponse({
        "user": _user_json(user),
        "point": {"id": point.id, "name": point.name, "address": point.address,
                  "rate_min": pct(point.rate_min), "rate_max": pct(point.rate_max),
                  "rate_default": pct(point.rate_default)},
        "rooms": [{"id": r.id, "name": r.name, "is_sauna": r.is_sauna, "hour_price": r.hour_price}
                  for r in point.rooms.filter(is_active=True)],
        "programs": [{"id": p.id, "name": p.name, "duration_min": p.duration_min, "price": p.price}
                     for p in Program.objects.filter(is_active=True)],
        "products": [{"id": p.id, "name": p.name, "category": p.category, "price": p.price,
                      "admin_rate": pct(user.admin_rate_for(p.category))}
                     for p in Product.objects.filter(is_active=True)],
        "expense_categories": [{"id": c.id, "name": c.name} for c in ExpenseCategory.objects.all()],
        "admin_rates": {"session": pct(user.rate_session), "session_dispatcher": pct(user.rate_session_dispatcher),
                        "sauna": pct(user.rate_sauna)},
        # Все работающие мастера: свои точки — в списке, с других точек — для подмены через поиск
        "masters": [{"id": e.id, "name": e.name, "rate": pct(e.rate), "rate_with_dispatcher": pct(e.rate_with_dispatcher),
                     "base_full": e.base_full, "home": e.point_id == point.id, "point": e.point.name if e.point_id else ""}
                    for e in Employee.objects.filter(kind=Employee.Kind.MASTER, archived_at__isnull=True)
                    .select_related("point").order_by("name")],
        "dispatchers": [{"id": e.id, "name": e.name, "rate": pct(e.rate)} for e in Employee.objects.filter(
            kind=Employee.Kind.DISPATCHER, archived_at__isnull=True)],
        "shift": shift_json(shift) if shift else None,
    })


def _my_open_shift(user):
    shift = Shift.objects.filter(point=user.point, status=Shift.Status.OPEN, admin=user).first()
    if not shift:
        raise ValidationError("Смена не открыта.")
    return shift


def _state_response(request):
    shift = Shift.objects.filter(point=request.user.point, admin=request.user).order_by("-opened_at").first()
    return JsonResponse({"shift": shift_json(shift) if shift else None})


@require_POST
@api(roles=[User.Role.ADMIN])
def shift_open(request):
    services.open_shift(request.user, _int(request.data.get("opening_cash"), "Касса на начало"))
    return _state_response(request)


@require_POST
@api(roles=[User.Role.ADMIN])
def shift_attendance(request):
    shift = _my_open_shift(request.user)
    emp = Employee.objects.get(pk=request.data.get("employee_id"))
    services.mark_attendance(request.user, shift, emp, present=bool(request.data.get("present", True)))
    return _state_response(request)


@require_POST
@api(roles=[User.Role.ADMIN])
def employee_add(request):
    d = request.data
    emp = services.add_employee(request.user, kind=Employee.Kind.MASTER, name=str(d.get("name", "")),
                                phone=str(d.get("phone", ""))[:32], rate=d.get("rate"))
    shift = Shift.objects.filter(point=request.user.point, status=Shift.Status.OPEN, admin=request.user).first()
    if shift:
        services.mark_attendance(request.user, shift, emp, present=True)
    return JsonResponse({"employee": {"id": emp.id, "name": emp.name, "rate": float(emp.rate)}})


@require_POST
@api(roles=[User.Role.ADMIN])
def session_create(request):
    d = request.data
    shift = _my_open_shift(request.user)
    services.create_session(
        request.user, shift,
        room=Room.objects.get(pk=d.get("room_id"), point=shift.point),
        master=Employee.objects.get(pk=d["master_id"]) if d.get("master_id") else None,
        dispatcher=Employee.objects.get(pk=d["dispatcher_id"]) if d.get("dispatcher_id") else None,
        program=Program.objects.get(pk=d["program_id"]) if d.get("program_id") else None,
        start=_dt(d.get("start"), "Начало"), end=_dt(d.get("end"), "Конец"),
        amount=_int(d.get("amount"), "Сумма"), payment_method=d.get("payment_method"),
        id=_uuid(d.get("id")),
        client_created_at=_dt(d["client_created_at"], "Время") if d.get("client_created_at") else None,
    )
    return _state_response(request)


@require_POST
@api(roles=[User.Role.ADMIN])
def sale_create(request):
    d = request.data
    shift = _my_open_shift(request.user)
    if d.get("payment_method") not in PaymentMethod.values:
        raise ValidationError("Неизвестный способ оплаты.")
    services.create_sale(request.user, shift, product=Product.objects.get(pk=d.get("product_id")),
                         quantity=_int(d.get("quantity"), "Количество"), payment_method=d.get("payment_method"),
                         id=_uuid(d.get("id")))
    return _state_response(request)


@require_POST
@api(roles=[User.Role.ADMIN])
def expense_create(request):
    d = request.data
    shift = _my_open_shift(request.user)
    if d.get("payment_method") not in PaymentMethod.values:
        raise ValidationError("Неизвестный способ оплаты.")
    services.create_expense(request.user, shift, category=ExpenseCategory.objects.get(pk=d.get("category_id")),
                            amount=_int(d.get("amount"), "Сумма"), payment_method=d.get("payment_method"),
                            comment=str(d.get("comment", ""))[:255], id=_uuid(d.get("id")))
    return _state_response(request)


RECORD_MODELS = {"sessions": Session, "sales": Sale, "expenses": Expense}


@require_POST
@api(roles=[User.Role.ADMIN])
def record_cancel(request, kind, pk):
    model = RECORD_MODELS.get(kind)
    if model is None:
        raise ObjectDoesNotExist
    record = model.objects.select_related("shift").get(pk=_uuid(pk))
    services.cancel_record(request.user, record, str(request.data.get("reason", "")))
    return _state_response(request)


@require_POST
@api(roles=[User.Role.ADMIN])
def shift_close(request):
    d = request.data
    shift = _my_open_shift(request.user)
    paid = {}
    for row in d.get("paid", []):
        kind, _, pk = str(row.get("key", "")).partition(":")
        if kind not in ("employee", "admin") or not pk.isdigit():
            raise ValidationError("Неверная строка выплат.")
        paid[(kind, int(pk))] = _int(row.get("paid"), "Выплачено")
    shift = services.close_shift(request.user, shift, paid=paid,
                                 actual_cash=_int(d.get("actual_cash"), "Фактически в кассе"),
                                 comment=str(d.get("comment", ""))[:500])
    return JsonResponse({"shift": shift_json(shift)})


@require_GET
@api(roles=[User.Role.ADMIN])
def my_shifts(request):
    rows = []
    for s in Shift.objects.filter(admin=request.user, status=Shift.Status.CLOSED).order_by("-opened_at")[:60]:
        revenue = _sum(s.sessions) + _sum(s.sales)
        rows.append({"id": s.id, "point": s.point.name, "opened_at": s.opened_at.isoformat(),
                     "closed_at": s.closed_at.isoformat() if s.closed_at else None,
                     "revenue": revenue, "discrepancy": s.discrepancy})
    return JsonResponse({"shifts": rows})


@require_GET
@api(roles=[User.Role.ADMIN])
def shift_detail(request, pk):
    shift = Shift.objects.get(pk=pk, admin=request.user)
    return JsonResponse({"shift": shift_json(shift)})
