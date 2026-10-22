"""Демо-данные для показа клиентам. Никаких реальных имён, телефонов и денег.

    python manage.py seed_demo           — заполнить пустую базу
    python manage.py seed_demo --reset   — стереть ВСЁ и заполнить заново
"""
import os
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    AdminCategoryRate, Employee, ExpenseCategory, Point, Product, ProductCategory, Program, Room, User,
)

RUB = 100


class Command(BaseCommand):
    help = "Заполнить базу демо-данными (3 точки, мастера, администраторы, справочники)"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Стереть все данные перед заполнением")

    def handle(self, *args, reset=False, **opts):
        if reset:
            if not os.environ.get("DEMO_MODE") == "1":
                raise CommandError("--reset работает только при DEMO_MODE=1, чтобы не стереть рабочую базу.")
            call_command("flush", interactive=False, verbosity=0)
        elif Point.objects.exists():
            raise CommandError("База уже заполнена. Для пересоздания: seed_demo --reset (только DEMO_MODE=1).")
        password = os.environ.get("DEMO_PASSWORD", "demo12345demo")
        self._seed(password)
        self.stdout.write(self.style.SUCCESS(
            "Готово. Входы: superadmin, manager, olga, irina, anna, svetlana — пароль из DEMO_PASSWORD."))

    @transaction.atomic
    def _seed(self, password):
        points = []
        for i, address in enumerate(["[адрес точки 1]", "[адрес точки 2]", "[адрес точки 3]"], start=1):
            p = Point.objects.create(name=f"Точка {i}", address=address, rate_min=Decimal(30), rate_max=Decimal(60),
                                     rate_default=Decimal(50))
            Room.objects.create(point=p, name="Комната 1")
            Room.objects.create(point=p, name="Комната 2")
            Room.objects.create(point=p, name="Сауна", kind=Room.Kind.SAUNA, hour_price=1500 * RUB)
            points.append(p)

        for name, dur, price in [("Программа А", 30, 3000), ("Программа Б", 60, 6000), ("Программа В", 90, 9000)]:
            Program.objects.create(name=name, duration_min=dur, price=price * RUB)
        for name, cat, price in [("Кальян", ProductCategory.HOOKAH, 1500), ("Коктейль", ProductCategory.BAR, 600),
                                 ("Пиво", ProductCategory.BAR, 350), ("Чай", ProductCategory.DRINKS, 300),
                                 ("Вода", ProductCategory.DRINKS, 150)]:
            Product.objects.create(name=name, category=cat, price=price * RUB)
        for name in ["Такси", "Хозтовары", "Продукты", "Ремонт", "Прочее"]:
            ExpenseCategory.objects.create(name=name)

        def make_user(username, first_name, role, point=None, **rates):
            u = User(username=username, first_name=first_name, role=role, point=point,
                     is_staff=role == User.Role.SUPERADMIN, is_superuser=role == User.Role.SUPERADMIN, **rates)
            u.set_password(password)
            u.save()
            return u

        make_user("superadmin", "Суперадмин", User.Role.SUPERADMIN)
        make_user("manager", "Управляющий", User.Role.MANAGER)
        admins = [
            ("olga", "Ольга", points[0], 10, {"bar": 10, "hookah": 0, "drinks": 10}, 0),
            ("irina", "Ирина", points[1], 10, {"bar": 10, "hookah": 5, "drinks": 10}, 0),
            ("anna", "Анна", points[1], 10, {"bar": 10, "hookah": 5, "drinks": 10}, 0),
            ("svetlana", "Светлана", points[2], 8, {"bar": 10, "hookah": 0, "drinks": 10}, 5),
        ]
        for username, name, point, rate, cats, sauna in admins:
            u = make_user(username, name, User.Role.ADMIN, point, rate_session=Decimal(rate),
                          rate_session_dispatcher=Decimal(5), rate_sauna=Decimal(sauna))
            for cat, r in cats.items():
                AdminCategoryRate.objects.create(admin=u, category=cat, rate=Decimal(r))

        masters = [("Алина", 0, 50, True), ("Виктория", 0, 50, True), ("Полина", 0, 50, True),
                   ("Марина", 1, 45, False), ("Диана", 1, 50, True), ("Валерия", 1, 50, True),
                   ("Карина", 2, 50, True), ("Ксения", 2, 50, True)]
        for name, pi, rate, full in masters:
            Employee.objects.create(kind=Employee.Kind.MASTER, name=name, point=points[pi],
                                    rate=Decimal(rate), rate_with_dispatcher=Decimal(rate), base_full=full)
        for name in ["Диспетчер 1", "Диспетчер 2"]:
            Employee.objects.create(kind=Employee.Kind.DISPATCHER, name=name, rate=Decimal(30),
                                    rate_with_dispatcher=Decimal(30))
