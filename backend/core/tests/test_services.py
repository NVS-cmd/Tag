"""Проверка правил на настоящей базе PostgreSQL: `make test`."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core import services
from core.models import (
    AuditLog, Device, Employee, ExpenseCategory, PaymentMethod, Product, RecordStatus, Room, Shift, User,
)

RUB = 100


class ShiftFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.olga = User.objects.get(username="olga")
        cls.manager = User.objects.get(username="manager")
        cls.room1 = Room.objects.get(point=cls.olga.point, name="Комната 1")
        cls.room2 = Room.objects.get(point=cls.olga.point, name="Комната 2")
        cls.sauna = Room.objects.get(point=cls.olga.point, kind=Room.Kind.SAUNA)
        cls.alina = Employee.objects.get(name="Алина")
        cls.vika = Employee.objects.get(name="Виктория")
        cls.disp = Employee.objects.get(name="Диспетчер 1")

    def setUp(self):
        self.shift = services.open_shift(self.olga, 5000 * RUB)
        services.mark_attendance(self.olga, self.shift, self.alina)
        services.mark_attendance(self.olga, self.shift, self.vika)
        self.t0 = timezone.now().replace(minute=0, second=0, microsecond=0)

    def session(self, room=None, master="alina", start=0, end=60, amount=6000, pay=PaymentMethod.CASH, **kw):
        m = {"alina": self.alina, "vika": self.vika, None: None}[master]
        return services.create_session(
            self.olga, self.shift, room=room or self.room1, master=m,
            start=self.t0 + timedelta(minutes=start), end=self.t0 + timedelta(minutes=end),
            amount=amount * RUB, payment_method=pay, **kw)

    def test_shares_snapshot(self):
        s = self.session(dispatcher=self.disp, amount=10000)
        self.assertEqual((s.master_share, s.dispatcher_share, s.admin_share), (5000 * RUB, 3000 * RUB, 500 * RUB))
        # изменение ставки не меняет прошлый сеанс
        self.alina.rate_with_dispatcher = Decimal(40)
        self.alina.save()
        s.refresh_from_db()
        self.assertEqual(s.master_share, 5000 * RUB)

    def test_room_overlap_blocked_by_database(self):
        self.session()
        with self.assertRaisesMessage(ValidationError, "уже занята"):
            self.session(master="vika", start=30, end=90)

    def test_master_overlap_blocked_by_database(self):
        self.session()
        with self.assertRaisesMessage(ValidationError, "в другом сеансе"):
            self.session(room=self.room2, start=30, end=90)

    def test_back_to_back_is_allowed(self):
        self.session(start=0, end=60)
        self.session(start=60, end=120)

    def test_cancelled_session_frees_room(self):
        s = self.session()
        services.cancel_record(self.olga, s, "клиент не пришёл")
        self.session(master="vika")

    def test_master_must_be_on_shift(self):
        services.mark_attendance(self.olga, self.shift, self.vika, present=False)
        with self.assertRaisesMessage(ValidationError, "не отмечен"):
            self.session(master="vika")

    def test_sauna(self):
        s = self.session(room=self.sauna, master=None, amount=3000)
        self.assertEqual((s.master_share, s.admin_share), (0, 0))

    def test_idempotent_by_id(self):
        import uuid
        rid = uuid.uuid4()
        a = self.session(id=rid)
        b = self.session(id=rid)
        self.assertEqual(a.pk, b.pk)

    def test_full_close_with_debt_and_discrepancy(self):
        self.session(amount=6000)                                     # мастер 3000, админ 600
        services.create_sale(self.olga, self.shift, product=Product.objects.get(name="Коктейль"),
                             quantity=2, payment_method=PaymentMethod.CASH)  # 1200, админ 120
        services.create_expense(self.olga, self.shift, category=ExpenseCategory.objects.get(name="Такси"),
                                amount=600 * RUB, payment_method=PaymentMethod.CASH)
        acc = services.shift_accruals(self.shift)
        self.assertEqual(acc[("employee", self.alina.id)], 3000 * RUB)
        self.assertEqual(acc[("admin", self.olga.id)], 720 * RUB)
        paid = {("employee", self.alina.id): 2500 * RUB, ("admin", self.olga.id): 720 * RUB}
        # 5000 + 6000 + 1200 − 600 − 3220 = 8380
        with self.assertRaisesMessage(ValidationError, "причину расхождения"):
            services.close_shift(self.olga, self.shift, paid=paid, actual_cash=8300 * RUB)
        shift = services.close_shift(self.olga, self.shift, paid=paid, actual_cash=8300 * RUB, comment="сдача")
        self.assertEqual(shift.expected_cash, 8380 * RUB)
        self.assertEqual(shift.discrepancy, -80 * RUB)
        self.assertEqual(services.employee_debt(self.alina), 500 * RUB)

    def test_close_requires_everyone_marked(self):
        self.session()
        with self.assertRaisesMessage(ValidationError, "каждому"):
            services.close_shift(self.olga, self.shift, paid={("admin", self.olga.id): 0}, actual_cash=0)

    def test_closed_shift_is_read_only_for_admin(self):
        services.close_shift(self.olga, self.shift, paid={("admin", self.olga.id): 0}, actual_cash=5000 * RUB)
        with self.assertRaises(ValidationError):
            self.session()

    def test_master_from_other_point_can_cover(self):
        marina = Employee.objects.get(name="Марина")  # Точка 2
        services.mark_attendance(self.olga, self.shift, marina)
        services.create_session(self.olga, self.shift, room=self.room2, master=marina,
                                start=self.t0, end=self.t0 + timedelta(hours=1), amount=1000 * RUB,
                                payment_method=PaymentMethod.CASH)
        # нельзя снять мастера, у которого есть сеансы
        with self.assertRaisesMessage(ValidationError, "есть сеансы"):
            services.mark_attendance(self.olga, self.shift, marina, present=False)

    def test_master_cannot_be_on_two_open_shifts(self):
        irina = User.objects.get(username="irina")
        shift2 = services.open_shift(irina, 0)
        with self.assertRaisesMessage(ValidationError, "уже на смене"):
            services.mark_attendance(irina, shift2, self.alina)

    def test_manager_adds_to_open_shift(self):
        polina = Employee.objects.get(name="Полина")
        services.mark_attendance(self.manager, self.shift, polina)
        self.assertTrue(self.shift.attendance.filter(employee=polina).exists())

    def test_one_open_shift_per_point(self):
        with self.assertRaises(ValidationError):
            services.open_shift(self.olga, 0)

    def test_admin_cannot_touch_other_point(self):
        irina = User.objects.get(username="irina")
        with self.assertRaises(PermissionDenied):
            services.create_sale(irina, self.shift, product=Product.objects.first(), quantity=1,
                                 payment_method=PaymentMethod.CASH)

    def test_cancel_needs_reason(self):
        s = self.session()
        with self.assertRaises(ValidationError):
            services.cancel_record(self.olga, s, "  ")
        services.cancel_record(self.olga, s, "ошибка")
        s.refresh_from_db()
        self.assertEqual(s.status, RecordStatus.CANCELLED)


class EmployeeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.olga = User.objects.get(username="olga")
        cls.manager = User.objects.get(username="manager")

    def test_admin_adds_master_within_range_only(self):
        e = services.add_employee(self.olga, kind=Employee.Kind.MASTER, name="Новенькая", rate=45)
        self.assertEqual(e.point, self.olga.point)
        with self.assertRaisesMessage(ValidationError, "диапазоне"):
            services.add_employee(self.olga, kind=Employee.Kind.MASTER, name="Другая", rate=61)

    def test_duplicate_name(self):
        with self.assertRaisesMessage(ValidationError, "уже есть"):
            services.add_employee(self.olga, kind=Employee.Kind.MASTER, name="алина")

    def test_admin_cannot_add_dispatcher_or_archive(self):
        with self.assertRaises(PermissionDenied):
            services.add_employee(self.olga, kind=Employee.Kind.DISPATCHER, name="Д3")
        with self.assertRaises(PermissionDenied):
            services.archive_employee(self.olga, Employee.objects.get(name="Алина"))

    def test_archive_and_restore(self):
        e = Employee.objects.get(name="Алина")
        services.archive_employee(self.manager, e)
        self.assertTrue(e.is_archived)
        services.restore_employee(self.manager, e)
        self.assertFalse(e.is_archived)

    def test_archive_admin_blocked_with_open_shift_and_revokes_devices(self):
        services.open_shift(self.olga, 0)
        with self.assertRaisesMessage(ValidationError, "открыта смена"):
            services.archive_admin(self.manager, self.olga)
        anna = User.objects.get(username="anna")
        Device.objects.create(user=anna, label="телефон")
        services.archive_admin(self.manager, anna)
        self.assertFalse(Device.objects.get(user=anna).is_active)
        self.assertFalse(User.objects.get(pk=anna.pk).is_active)


class AuditTests(TestCase):
    def test_log_is_append_only(self):
        entry = AuditLog.objects.create(action="тест")
        entry.action = "подмена"
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()
