"""Тесты денежных правил (ТЗ, раздел 5).

Не требуют Django и базы: `python -m unittest core.tests.test_calc`.
Django-раннер (`make test`) тоже их находит.
"""
from datetime import datetime
from decimal import Decimal
from unittest import TestCase

from core.calc import (
    AdminRates,
    MasterRates,
    cash_discrepancy,
    debt,
    expected_cash,
    intervals_overlap,
    max_staff_percent,
    percent_of,
    profit,
    rate_in_range,
    sale_admin_share,
    session_shares,
)

RUB = 100  # копеек в рубле

# Ставки по умолчанию из прежнего шаблона
ADMIN = AdminRates(session=Decimal(10), session_with_dispatcher=Decimal(5), sauna=Decimal(0))
MASTER = MasterRates(rate=Decimal(50), rate_with_dispatcher=Decimal(50), base_full=True)


class PercentTests(TestCase):
    def test_simple(self):
        self.assertEqual(percent_of(6000 * RUB, 50), 3000 * RUB)

    def test_rounding_half_up_to_kopeck(self):
        # 333,33 ₽ × 7,5% = 24,99975 ₽ → 25,00 ₽
        self.assertEqual(percent_of(33333, Decimal("7.5")), 2500)
        # 1 копейка × 50% = 0,5 коп. → 1 коп.
        self.assertEqual(percent_of(1, 50), 1)

    def test_rejects_floats_and_bad_rates(self):
        with self.assertRaises(TypeError):
            percent_of(10.5, 10)
        with self.assertRaises(ValueError):
            percent_of(100, 101)
        with self.assertRaises(ValueError):
            percent_of(100, -1)
        with self.assertRaises(ValueError):
            percent_of(-100, 10)


class SessionSharesTests(TestCase):
    def test_without_dispatcher(self):
        s = session_shares(6000 * RUB, is_sauna=False, admin=ADMIN, master=MASTER)
        self.assertEqual(s.master, 3000 * RUB)
        self.assertEqual(s.dispatcher, 0)
        self.assertEqual(s.admin, 600 * RUB)
        self.assertEqual(s.venue, 2400 * RUB)

    def test_with_dispatcher_full_base_like_template(self):
        # Шаблон: 50% мастеру, 30% диспетчеру, 5% админу → заведению 15%
        s = session_shares(10000 * RUB, is_sauna=False, admin=ADMIN, master=MASTER, dispatcher_rate=30)
        self.assertEqual((s.master, s.dispatcher, s.admin, s.venue), (5000 * RUB, 3000 * RUB, 500 * RUB, 1500 * RUB))

    def test_with_dispatcher_rest_base(self):
        master = MasterRates(rate=Decimal(50), rate_with_dispatcher=Decimal(50), base_full=False)
        s = session_shares(10000 * RUB, is_sauna=False, admin=ADMIN, master=master, dispatcher_rate=30)
        # 50% от 7000 ₽ = 3500 ₽ (пример из чата)
        self.assertEqual(s.master, 3500 * RUB)
        self.assertEqual(s.venue, 3000 * RUB)

    def test_admin_gets_dispatcher_rate_instead_of_session_rate(self):
        s = session_shares(1000 * RUB, is_sauna=False, admin=ADMIN, master=MASTER, dispatcher_rate=30)
        self.assertEqual(s.admin, 50 * RUB)

    def test_sauna_has_no_master_and_uses_sauna_rate(self):
        admin = AdminRates(session=Decimal(10), session_with_dispatcher=Decimal(5), sauna=Decimal(5))
        s = session_shares(3000 * RUB, is_sauna=True, admin=admin)
        self.assertEqual((s.master, s.dispatcher, s.admin, s.venue), (0, 0, 150 * RUB, 2850 * RUB))

    def test_sauna_default_admin_zero(self):
        s = session_shares(3000 * RUB, is_sauna=True, admin=ADMIN)
        self.assertEqual(s.venue, 3000 * RUB)

    def test_sauna_rejects_master(self):
        with self.assertRaises(ValueError):
            session_shares(100, is_sauna=True, admin=ADMIN, master=MASTER)

    def test_room_requires_master(self):
        with self.assertRaises(ValueError):
            session_shares(100, is_sauna=False, admin=ADMIN)

    def test_shares_always_sum_to_amount(self):
        master = MasterRates(rate=Decimal("47.5"), rate_with_dispatcher=Decimal("43.3"), base_full=False)
        admin = AdminRates(session=Decimal("9.9"), session_with_dispatcher=Decimal("4.7"))
        for amount in (1, 7, 99, 101, 33333, 123457, 999999):
            for disp in (None, Decimal("27.5")):
                s = session_shares(amount, is_sauna=False, admin=admin, master=master, dispatcher_rate=disp)
                self.assertEqual(s.master + s.dispatcher + s.admin + s.venue, amount, (amount, disp))

    def test_staff_total(self):
        s = session_shares(10000 * RUB, is_sauna=False, admin=ADMIN, master=MASTER, dispatcher_rate=30)
        self.assertEqual(s.staff_total, 8500 * RUB)


class SaleTests(TestCase):
    def test_bar_ten_percent(self):
        self.assertEqual(sale_admin_share(600 * RUB, 10), 60 * RUB)

    def test_hookah_zero(self):
        self.assertEqual(sale_admin_share(1500 * RUB, 0), 0)


class RatesWarningTests(TestCase):
    def test_template_rates_are_85_percent(self):
        self.assertEqual(max_staff_percent(MASTER, 30, ADMIN), Decimal(85))

    def test_over_100_detected(self):
        greedy = MasterRates(rate=Decimal(60), rate_with_dispatcher=Decimal(70), base_full=True)
        self.assertGreater(max_staff_percent(greedy, 30, ADMIN), 100)

    def test_rest_base_lowers_total(self):
        rest = MasterRates(rate=Decimal(50), rate_with_dispatcher=Decimal(50), base_full=False)
        self.assertEqual(max_staff_percent(rest, 30, ADMIN), Decimal(70))

    def test_range(self):
        self.assertTrue(rate_in_range(50, 40, 55))
        self.assertTrue(rate_in_range(40, 40, 55))
        self.assertFalse(rate_in_range("55.5", 40, 55))
        self.assertFalse(rate_in_range(39, 40, 55))


class CashTests(TestCase):
    def test_expected_cash_formula(self):
        exp = expected_cash(
            opening=5000 * RUB, cash_sessions=6000 * RUB, cash_sales=1500 * RUB,
            cash_expenses=600 * RUB, cash_payouts=9650 * RUB,
        )
        self.assertEqual(exp, 2250 * RUB)

    def test_discrepancy_sign(self):
        self.assertEqual(cash_discrepancy(actual=2050 * RUB, expected=2250 * RUB), -200 * RUB)
        self.assertEqual(cash_discrepancy(actual=2250 * RUB, expected=2250 * RUB), 0)
        self.assertEqual(cash_discrepancy(actual=2300 * RUB, expected=2250 * RUB), 50 * RUB)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            expected_cash(opening=-1, cash_sessions=0, cash_sales=0, cash_expenses=0, cash_payouts=0)

    def test_debt_and_profit(self):
        self.assertEqual(debt(accrued=3000 * RUB, paid=500 * RUB), 2500 * RUB)
        self.assertEqual(profit(revenue=19500 * RUB, staff=9650 * RUB, expenses=600 * RUB), 9250 * RUB)


class OverlapTests(TestCase):
    def t(self, h, m=0):
        return datetime(2026, 10, 19, h, m)

    def test_overlap(self):
        self.assertTrue(intervals_overlap(self.t(12), self.t(13), self.t(12, 30), self.t(14)))
        self.assertTrue(intervals_overlap(self.t(12), self.t(14), self.t(12, 30), self.t(13)))

    def test_touching_is_not_overlap(self):
        self.assertFalse(intervals_overlap(self.t(12), self.t(13), self.t(13), self.t(14)))

    def test_bad_interval(self):
        with self.assertRaises(ValueError):
            intervals_overlap(self.t(13), self.t(12), self.t(12), self.t(14))
