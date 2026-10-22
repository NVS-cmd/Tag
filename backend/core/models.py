"""Модели данных (ТЗ, раздел 3).

Правила, которые закреплены на уровне базы, а не только кода:
- деньги — целые копейки (BigIntegerField);
- мастер и комната не могут быть заняты в пересекающихся сеансах
  (ExclusionConstraint, расширение btree_gist включается в docker/db-init.sql);
- на точке одновременно открыта максимум одна смена;
- записи не удаляются: отменяются или уходят в архив;
- журнал только дополняется.
"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Func, Q
from django.utils import timezone

PERCENT = [MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))]


def percent_field(default, verbose_name):
    return models.DecimalField(max_digits=5, decimal_places=2, default=Decimal(default), validators=PERCENT,
                               verbose_name=verbose_name)


def money_field(verbose_name, **kw):
    return models.BigIntegerField(validators=[MinValueValidator(0)], verbose_name=verbose_name,
                                  help_text="в копейках", **kw)


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Наличные"
    CARD = "card", "Карта"
    TRANSFER = "transfer", "Перевод"


class ProductCategory(models.TextChoices):
    HOOKAH = "hookah", "Кальян"
    BAR = "bar", "Бар"
    DRINKS = "drinks", "Напитки"
    OTHER = "other", "Прочее"


class Point(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)
    address = models.CharField("Адрес", max_length=255, blank=True)
    timezone = models.CharField("Часовой пояс", max_length=64, default="Europe/Moscow")
    rate_min = percent_field(30, "Мин. ставка мастера, %")
    rate_max = percent_field(60, "Макс. ставка мастера, %")
    rate_default = percent_field(50, "Ставка мастера по умолчанию, %")
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Точка"
        verbose_name_plural = "Точки"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(rate_min__lte=F("rate_max")), name="point_rate_range_valid"),
        ]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Учётная запись: суперадмин, управляющий или администратор ресепшена."""

    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Суперадмин"
        MANAGER = "manager", "Управляющий"
        ADMIN = "admin", "Администратор"

    role = models.CharField("Роль", max_length=20, choices=Role.choices, default=Role.ADMIN)
    point = models.ForeignKey(Point, on_delete=models.PROTECT, null=True, blank=True, related_name="admins",
                              verbose_name="Точка")
    phone = models.CharField("Телефон", max_length=32, blank=True)
    # Ставки администратора — задаёт управляющий в карточке (ТЗ, разделы 4–5)
    rate_session = percent_field(10, "% с сеансов")
    rate_session_dispatcher = percent_field(5, "% с сеанса при диспетчере")
    rate_sauna = percent_field(0, "% с сауны")
    archived_at = models.DateTimeField("Удалён (в архиве)", null=True, blank=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        constraints = [
            models.CheckConstraint(condition=~Q(role="admin") | Q(point__isnull=False),
                                   name="admin_must_have_point"),
        ]

    @property
    def is_manager(self):
        return self.role in (self.Role.MANAGER, self.Role.SUPERADMIN)

    def admin_rate_for(self, category):
        row = self.category_rates.filter(category=category).first()
        return row.rate if row else Decimal(0)


class AdminCategoryRate(models.Model):
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name="category_rates")
    category = models.CharField("Категория", max_length=20, choices=ProductCategory.choices)
    rate = percent_field(0, "%")

    class Meta:
        verbose_name = "Ставка админа с продаж"
        verbose_name_plural = "Ставки админа с продаж"
        constraints = [models.UniqueConstraint(fields=["admin", "category"], name="admin_category_rate_unique")]


class Room(models.Model):
    class Kind(models.TextChoices):
        ROOM = "room", "Комната"
        SAUNA = "sauna", "Сауна"

    point = models.ForeignKey(Point, on_delete=models.PROTECT, related_name="rooms", verbose_name="Точка")
    name = models.CharField("Название", max_length=100)
    kind = models.CharField("Тип", max_length=10, choices=Kind.choices, default=Kind.ROOM)
    hour_price = money_field("Цена часа (сауна)", default=0)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Комната"
        verbose_name_plural = "Комнаты"
        ordering = ["point", "name"]
        constraints = [models.UniqueConstraint(fields=["point", "name"], name="room_name_unique_per_point")]

    def __str__(self):
        return f"{self.point} · {self.name}"

    @property
    def is_sauna(self):
        return self.kind == self.Kind.SAUNA


class Program(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)
    duration_min = models.PositiveIntegerField("Длительность, мин")
    price = money_field("Цена")
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Программа"
        verbose_name_plural = "Программы"
        ordering = ["duration_min"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)
    category = models.CharField("Категория", max_length=20, choices=ProductCategory.choices)
    price = money_field("Цена")
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class ExpenseCategory(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)

    class Meta:
        verbose_name = "Категория расхода"
        verbose_name_plural = "Категории расходов"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    """Мастер или диспетчер. Входа в систему у сотрудников пока нет."""

    class Kind(models.TextChoices):
        MASTER = "master", "Мастер"
        DISPATCHER = "dispatcher", "Диспетчер"

    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.MASTER)
    name = models.CharField("Имя или псевдоним", max_length=100)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    point = models.ForeignKey(Point, on_delete=models.PROTECT, null=True, blank=True, related_name="employees",
                              verbose_name="Точка", help_text="У диспетчера пусто — работает на все точки")
    rate = percent_field(50, "Ставка, %")
    rate_with_dispatcher = percent_field(50, "Ставка при диспетчере, %")
    base_full = models.BooleanField("При диспетчере считать от полной суммы", default=True)
    archived_at = models.DateTimeField("Удалён (в архиве)", null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=Q(archived_at__isnull=True),
                                    name="employee_active_name_unique"),
            models.CheckConstraint(condition=~Q(kind="master") | Q(point__isnull=False),
                                   name="master_must_have_point"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_archived(self):
        return self.archived_at is not None


class Shift(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        CLOSED = "closed", "Закрыта"

    point = models.ForeignKey(Point, on_delete=models.PROTECT, related_name="shifts", verbose_name="Точка")
    admin = models.ForeignKey(User, on_delete=models.PROTECT, related_name="shifts", verbose_name="Администратор")
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField("Открыта", default=timezone.now)
    closed_at = models.DateTimeField("Закрыта", null=True, blank=True)
    opening_cash = money_field("Касса на начало")
    expected_cash = models.BigIntegerField("Касса расчётная", null=True, blank=True)
    actual_cash = models.BigIntegerField("Касса фактическая", null=True, blank=True)
    discrepancy = models.BigIntegerField("Расхождение", null=True, blank=True)
    close_comment = models.TextField("Комментарий к закрытию", blank=True)
    corrected = models.BooleanField("Исправлена управляющим", default=False)

    class Meta:
        verbose_name = "Смена"
        verbose_name_plural = "Смены"
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(fields=["point"], condition=Q(status="open"), name="one_open_shift_per_point"),
        ]

    def __str__(self):
        return f"{self.point} · {timezone.localtime(self.opened_at):%d.%m %H:%M}"


class Attendance(models.Model):
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="attendance")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    came_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Выход на смену"
        verbose_name_plural = "Выходы на смену"
        constraints = [models.UniqueConstraint(fields=["shift", "employee"], name="attendance_unique")]


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class RecordStatus(models.TextChoices):
    OK = "ok", "Действует"
    CANCELLED = "cancelled", "Отменена"


class ClientRecord(models.Model):
    """Запись, которую создаёт телефон администратора — в том числе офлайн.

    id генерирует устройство: повторная отправка той же записи ничего не задвоит.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="%(class)ss")
    payment_method = models.CharField("Оплата", max_length=10, choices=PaymentMethod.choices)
    status = models.CharField("Статус", max_length=10, choices=RecordStatus.choices, default=RecordStatus.OK)
    cancel_reason = models.CharField("Причина отмены", max_length=255, blank=True)
    created_at = models.DateTimeField("Записано на сервере", default=timezone.now)
    client_created_at = models.DateTimeField("Время на устройстве", null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True

    @property
    def was_offline(self):
        """Запись сделана без сети: время устройства и сервера разошлись больше чем на 10 минут."""
        if not self.client_created_at:
            return False
        return abs((self.created_at - self.client_created_at).total_seconds()) > 600


class Session(ClientRecord):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="sessions", verbose_name="Комната")
    master = models.ForeignKey(Employee, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="sessions_as_master", verbose_name="Мастер")
    dispatcher = models.ForeignKey(Employee, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="sessions_as_dispatcher", verbose_name="Диспетчер")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Программа")
    start = models.DateTimeField("Начало")
    end = models.DateTimeField("Конец")
    amount = money_field("Сумма")
    # Снимок ставок на момент записи — изменение ставок не трогает прошлое
    master_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    master_base_full = models.BooleanField(null=True, blank=True)
    dispatcher_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    admin_rate = models.DecimalField(max_digits=5, decimal_places=2)
    master_share = models.BigIntegerField("Мастеру", default=0)
    dispatcher_share = models.BigIntegerField("Диспетчеру", default=0)
    admin_share = models.BigIntegerField("Администратору", default=0)

    class Meta:
        verbose_name = "Сеанс"
        verbose_name_plural = "Сеансы"
        ordering = ["start"]
        constraints = [
            models.CheckConstraint(condition=Q(end__gt=F("start")), name="session_end_after_start"),
            models.CheckConstraint(
                condition=Q(master_share__gte=0, dispatcher_share__gte=0, admin_share__gte=0),
                name="session_shares_non_negative",
            ),
            ExclusionConstraint(
                name="session_room_no_overlap",
                expressions=[(TsTzRange("start", "end", RangeBoundary()), RangeOperators.OVERLAPS),
                             ("room", RangeOperators.EQUAL)],
                condition=Q(status="ok"),
            ),
            ExclusionConstraint(
                name="session_master_no_overlap",
                expressions=[(TsTzRange("start", "end", RangeBoundary()), RangeOperators.OVERLAPS),
                             ("master", RangeOperators.EQUAL)],
                condition=Q(status="ok") & Q(master__isnull=False),
            ),
        ]

    def clean(self):
        if self.room_id and self.room.is_sauna and (self.master_id or self.dispatcher_id):
            raise ValidationError("В сауне нет мастера и диспетчера.")
        if self.room_id and not self.room.is_sauna and not self.master_id:
            raise ValidationError("Выберите мастера.")


class Sale(ClientRecord):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Товар")
    quantity = models.PositiveIntegerField("Количество", default=1, validators=[MinValueValidator(1)])
    price = money_field("Цена за штуку")
    amount = money_field("Сумма")
    admin_rate = models.DecimalField(max_digits=5, decimal_places=2)
    admin_share = models.BigIntegerField("Администратору", default=0)

    class Meta:
        verbose_name = "Доп. продажа"
        verbose_name_plural = "Доп. продажи"
        constraints = [models.CheckConstraint(condition=Q(amount=F("price") * F("quantity")), name="sale_amount_matches")]


class Expense(ClientRecord):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, verbose_name="Категория")
    amount = money_field("Сумма")
    comment = models.CharField("Комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "Расход"
        verbose_name_plural = "Расходы"


class Payout(models.Model):
    """Выплата в конце смены. Получатель — сотрудник или сам администратор."""
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="payouts")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts")
    admin = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="payouts")
    accrued = money_field("Начислено за смену")
    paid = money_field("Выплачено")
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    comment = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Выплата"
        verbose_name_plural = "Выплаты"
        constraints = [
            models.CheckConstraint(
                condition=(Q(employee__isnull=False) & Q(admin__isnull=True)) | (Q(employee__isnull=True) & Q(admin__isnull=False)),
                name="payout_single_recipient",
            ),
            models.CheckConstraint(condition=Q(paid__lte=F("accrued")), name="payout_not_over_accrued"),
        ]

    @property
    def debt(self):
        return self.accrued - self.paid


class AuditLog(models.Model):
    """Журнал действий. Только дополняется: изменить или удалить запись нельзя."""
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    action = models.CharField("Действие", max_length=100)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    old = models.JSONField(null=True, blank=True)
    new = models.JSONField(null=True, blank=True)
    reason = models.CharField("Причина", max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал действий"
        ordering = ["-at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Журнал нельзя изменять.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Журнал нельзя удалять.")


class Device(models.Model):
    """Устройство, с которого входили. Управляющий может отключить любое или все сразу."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="devices")
    label = models.CharField("Устройство", max_length=200, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    is_active = models.BooleanField("Разрешено", default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Устройство"
        verbose_name_plural = "Устройства"
        ordering = ["-last_seen"]
