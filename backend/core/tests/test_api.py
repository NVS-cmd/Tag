"""API приложения администратора: `make test`."""
import json
import uuid
from datetime import timedelta

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Device, Employee, ExpenseCategory, Product, Room, User

RUB = 100
PASSWORD = "demo12345demo"


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        cache.clear()
        self.c = Client()
        self.olga = User.objects.get(username="olga")

    def post(self, url, data=None, client=None):
        return (client or self.c).post(url, json.dumps(data or {}), content_type="application/json")

    def login(self, username="olga", device_id=None, client=None):
        body = {"username": username, "password": PASSWORD, "device_label": "тест"}
        if device_id:
            body["device_id"] = device_id
        return self.post("/api/login/", body, client)

    def test_login_creates_device_and_logs_new_device(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        dev = Device.objects.get(pk=r.json()["device_id"])
        self.assertEqual(dev.user, self.olga)
        # повторный вход с тем же устройством — не новое
        self.c.post("/api/logout/")
        r2 = self.login(device_id=str(dev.pk))
        self.assertEqual(r2.json()["device_id"], str(dev.pk))
        self.assertEqual(Device.objects.filter(user=self.olga).count(), 1)

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            r = self.post("/api/login/", {"username": "olga", "password": "wrong"})
            self.assertEqual(r.status_code, 400)
        r = self.login()
        self.assertEqual(r.status_code, 429)

    def test_revoked_device_is_logged_out_and_told_to_wipe(self):
        dev_id = self.login().json()["device_id"]
        self.assertEqual(self.c.get("/api/admin/state/").status_code, 200)
        Device.objects.filter(pk=dev_id).update(is_active=False)
        r = self.c.get("/api/admin/state/")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()["wipe"])
        # и войти заново с этого устройства нельзя
        self.assertEqual(self.login(device_id=dev_id).status_code, 403)

    def test_requires_login_and_role(self):
        self.assertEqual(self.c.get("/api/admin/state/").status_code, 401)
        self.login("manager")
        self.assertEqual(self.c.get("/api/admin/state/").status_code, 403)

    def test_csrf_is_enforced(self):
        strict = Client(enforce_csrf_checks=True)
        strict.get("/api/me/")
        token = strict.cookies["csrftoken"].value
        r = strict.post("/api/login/", json.dumps({"username": "olga", "password": PASSWORD}),
                        content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        r = strict.post("/api/shift/open/", json.dumps({"opening_cash": 0}), content_type="application/json")
        self.assertEqual(r.status_code, 403)  # без заголовка X-CSRFToken

    def test_full_shift_via_api(self):
        self.login()
        state = self.c.get("/api/admin/state/").json()
        self.assertIsNone(state["shift"])
        self.assertEqual(len(state["rooms"]), 3)

        r = self.post("/api/shift/open/", {"opening_cash": 5000 * RUB})
        self.assertEqual(r.status_code, 200, r.content)
        alina = Employee.objects.get(name="Алина")
        self.post("/api/shift/attendance/", {"employee_id": alina.id, "present": True})

        room = Room.objects.get(point=self.olga.point, name="Комната 1")
        t0 = timezone.now().replace(second=0, microsecond=0)
        sid = str(uuid.uuid4())
        body = {"id": sid, "room_id": room.id, "master_id": alina.id, "start": t0.isoformat(),
                "end": (t0 + timedelta(hours=1)).isoformat(), "amount": 6000 * RUB, "payment_method": "cash"}
        r = self.post("/api/sessions/", body)
        self.assertEqual(r.status_code, 200, r.content)
        # повторная отправка той же записи (как после офлайна) не задваивает
        r = self.post("/api/sessions/", body)
        self.assertEqual(len(r.json()["shift"]["sessions"]), 1)
        # пересечение комнаты — понятная ошибка
        clash = dict(body, id=str(uuid.uuid4()))
        r = self.post("/api/sessions/", clash)
        self.assertEqual(r.status_code, 400)
        self.assertIn("занята", r.json()["detail"])

        self.post("/api/sales/", {"product_id": Product.objects.get(name="Коктейль").id, "quantity": 2,
                                  "payment_method": "cash"})
        self.post("/api/expenses/", {"category_id": ExpenseCategory.objects.get(name="Такси").id,
                                     "amount": 600 * RUB, "payment_method": "cash"})
        shift = self.c.get("/api/admin/state/").json()["shift"]
        self.assertEqual(shift["totals"]["revenue"], 7200 * RUB)
        keys = {a["key"]: a["amount"] for a in shift["accruals"]}
        self.assertEqual(keys[f"employee:{alina.id}"], 3000 * RUB)
        self.assertEqual(keys[f"admin:{self.olga.id}"], 720 * RUB)

        paid = [{"key": k, "paid": v} for k, v in keys.items()]
        # 5000 + 6000 + 1200 − 600 − 3720 = 7880
        r = self.post("/api/shift/close/", {"paid": paid, "actual_cash": 7880 * RUB})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["shift"]["discrepancy"], 0)
        mine = self.c.get("/api/shifts/mine/").json()["shifts"]
        self.assertEqual(mine[0]["revenue"], 7200 * RUB)

    def test_cancel_record(self):
        self.login()
        self.post("/api/shift/open/", {"opening_cash": 0})
        sale_state = self.post("/api/sales/", {"product_id": Product.objects.first().id, "quantity": 1,
                                               "payment_method": "card"}).json()
        sale_id = sale_state["shift"]["sales"][0]["id"]
        r = self.post(f"/api/sales/{sale_id}/cancel/", {"reason": ""})
        self.assertEqual(r.status_code, 400)
        r = self.post(f"/api/sales/{sale_id}/cancel/", {"reason": "ошибка"})
        self.assertEqual(r.json()["shift"]["sales"][0]["status"], "cancelled")

    def test_admin_adds_master_and_gets_marked(self):
        self.login()
        self.post("/api/shift/open/", {"opening_cash": 0})
        r = self.post("/api/employees/", {"name": "Новенькая", "rate": 45})
        self.assertEqual(r.status_code, 200, r.content)
        emp_id = r.json()["employee"]["id"]
        self.assertIn(emp_id, self.c.get("/api/admin/state/").json()["shift"]["attendance"])
        r = self.post("/api/employees/", {"name": "Дорогая", "rate": 70})
        self.assertEqual(r.status_code, 400)

    def test_other_admin_sees_open_shift_conflict(self):
        anna, irina = Client(), Client()
        self.login("anna", client=anna)
        self.login("irina", client=irina)
        self.post("/api/shift/open/", {"opening_cash": 0}, client=anna)
        r = irina.get("/api/admin/state/")
        self.assertEqual(r.status_code, 409)

    def test_app_page_and_service_worker(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        r = self.c.get("/sw.js")
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertEqual(self.c.get("/manifest.webmanifest").status_code, 200)
