"""Денежные расчёты CRM.

Модуль намеренно не зависит от Django: его можно проверить отдельно,
и каждое правило ТЗ (раздел 5) живёт в одном месте.

Все суммы — целые копейки (int). Ставки — проценты (Decimal/int/str),
допускаются дробные, например Decimal("7.5").
Каждая доля округляется до копейки по правилу «половина — вверх».
Доля заведения считается как остаток, поэтому сумма всех долей
всегда точно равна сумме сеанса — копейки не теряются.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

HUNDRED = Decimal(100)


def _pct(value) -> Decimal:
    rate = Decimal(str(value))
    if rate < 0 or rate > HUNDRED:
        raise ValueError(f"Ставка должна быть от 0 до 100%, получено {value}")
    return rate


def percent_of(amount: int, rate) -> int:
    """Доля в копейках от суммы в копейках, с округлением до копейки."""
    if not isinstance(amount, int):
        raise TypeError("Сумма должна быть в копейках (int)")
    if amount < 0:
        raise ValueError("Сумма не может быть отрицательной")
    share = Decimal(amount) * _pct(rate) / HUNDRED
    return int(share.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class MasterRates:
    rate: Decimal                 # обычная ставка мастера, %
    rate_with_dispatcher: Decimal  # ставка, если клиент от диспетчера, %
    base_full: bool = True        # True — от полной суммы, False — от остатка после диспетчера


@dataclass(frozen=True)
class AdminRates:
    session: Decimal              # % с обычного сеанса
    session_with_dispatcher: Decimal  # % с сеанса, если есть диспетчер
    sauna: Decimal = Decimal(0)   # % с сауны


@dataclass(frozen=True)
class Shares:
    master: int
    dispatcher: int
    admin: int
    venue: int

    @property
    def staff_total(self) -> int:
        return self.master + self.dispatcher + self.admin


def session_shares(
    amount: int,
    *,
    is_sauna: bool,
    admin: AdminRates,
    master: Optional[MasterRates] = None,
    dispatcher_rate=None,
) -> Shares:
    """Начисления с одного сеанса (ТЗ, раздел 5, п. 1).

    - Сауна: мастера и диспетчера нет, администратору — его % с сауны.
    - Без диспетчера: мастеру — его ставка от суммы, админу — ставка с сеансов.
    - С диспетчером: диспетчеру — его ставка; мастеру — ставка «при диспетчере»
      от полной суммы или от остатка после диспетчера; админу — ставка
      «при диспетчере».
    """
    if is_sauna:
        if master is not None or dispatcher_rate is not None:
            raise ValueError("В сауне нет мастера и диспетчера")
        a = percent_of(amount, admin.sauna)
        return _finish(amount, 0, 0, a)

    if master is None:
        raise ValueError("Для сеанса в обычной комнате нужен мастер")

    if dispatcher_rate is None:
        m = percent_of(amount, master.rate)
        a = percent_of(amount, admin.session)
        return _finish(amount, m, 0, a)

    d = percent_of(amount, dispatcher_rate)
    base = amount if master.base_full else amount - d
    m = percent_of(base, master.rate_with_dispatcher)
    a = percent_of(amount, admin.session_with_dispatcher)
    return _finish(amount, m, d, a)


def _finish(amount: int, m: int, d: int, a: int) -> Shares:
    venue = amount - m - d - a
    return Shares(master=m, dispatcher=d, admin=a, venue=venue)


def sale_admin_share(amount: int, rate) -> int:
    """Доля администратора с доп. продажи (ставка по категории товара)."""
    return percent_of(amount, rate)


def max_staff_percent(master: MasterRates, dispatcher_rate, admin: AdminRates) -> Decimal:
    """Сколько % суммы уходит персоналу в худшем случае — сеанс с диспетчером.

    Нужно для предупреждения управляющему при сохранении ставок:
    если больше 100%, заведение уходит в минус.
    """
    d = _pct(dispatcher_rate)
    md = _pct(master.rate_with_dispatcher)
    m_with = md if master.base_full else md * (HUNDRED - d) / HUNDRED
    with_disp = m_with + d + _pct(admin.session_with_dispatcher)
    without = _pct(master.rate) + _pct(admin.session)
    return max(with_disp, without)


def rate_in_range(rate, min_rate, max_rate) -> bool:
    """Может ли администратор поставить такую ставку (ТЗ, раздел 5, п. 2)."""
    r = Decimal(str(rate))
    return Decimal(str(min_rate)) <= r <= Decimal(str(max_rate))


def expected_cash(
    *, opening: int, cash_sessions: int, cash_sales: int, cash_expenses: int, cash_payouts: int
) -> int:
    """Сколько наличных должно быть в кассе при закрытии (ТЗ, раздел 5, п. 5)."""
    for v in (opening, cash_sessions, cash_sales, cash_expenses, cash_payouts):
        if not isinstance(v, int) or v < 0:
            raise ValueError("Суммы кассы — неотрицательные копейки")
    return opening + cash_sessions + cash_sales - cash_expenses - cash_payouts


def cash_discrepancy(*, actual: int, expected: int) -> int:
    """Расхождение: плюс — излишек, минус — недостача (п. 6)."""
    return actual - expected


def debt(*, accrued: int, paid: int) -> int:
    """Долг перед сотрудником: начислено минус выплачено (п. 8)."""
    return accrued - paid


def intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Пересекаются ли полуинтервалы [start, end). Стык 12:00–13:00 и 13:00–14:00 — не пересечение."""
    if a_end <= a_start or b_end <= b_start:
        raise ValueError("Конец сеанса должен быть позже начала")
    return a_start < b_end and b_start < a_end


def profit(*, revenue: int, staff: int, expenses: int) -> int:
    """Прибыль за период (п. 7)."""
    return revenue - staff - expenses
