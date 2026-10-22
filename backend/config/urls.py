from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from core import api, api_manager as m, views


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", views.app_index, name="app"),
    path("sw.js", views.service_worker),
    path("manifest.webmanifest", views.manifest),
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/me/", api.me),
    path("api/login/", api.login_view),
    path("api/logout/", api.logout_view),
    path("api/admin/state/", api.admin_state),
    path("api/shift/open/", api.shift_open),
    path("api/shift/attendance/", api.shift_attendance),
    path("api/shift/close/", api.shift_close),
    path("api/shifts/mine/", api.my_shifts),
    path("api/shifts/<int:pk>/", api.shift_detail),
    path("api/employees/", api.employee_add),
    path("api/sessions/", api.session_create),
    path("api/sales/", api.sale_create),
    path("api/expenses/", api.expense_create),
    path("api/<str:kind>/<str:pk>/cancel/", api.record_cancel),
    # кабинет управляющего
    path("api/m/summary/", m.summary),
    path("api/m/points/", m.points_list),
    path("api/m/points/<int:pk>/", m.point_update),
    path("api/m/staff/", m.staff_list),
    path("api/m/staff/new/", m.staff_create),
    path("api/m/staff/<int:pk>/", m.staff_update),
    path("api/m/staff/<int:pk>/archive/", m.staff_archive),
    path("api/m/shifts/<int:pk>/", m.shift_view),
    path("api/m/shifts/<int:pk>/staff/", m.shift_add_staff),
    path("api/m/admins/", m.admins_list),
    path("api/m/admins/new/", m.admin_create),
    path("api/m/admins/<int:pk>/", m.admin_update),
    path("api/m/admins/<int:pk>/<str:action>/", m.admin_action),
    path("api/m/devices/", m.devices_list),
    path("api/m/devices/revoke-all/", m.devices_revoke_all),
    path("api/m/devices/<str:pk>/toggle/", m.device_toggle),
    path("api/m/report/", m.report),
    path("api/m/report.xlsx", m.report_xlsx),
    path("api/m/log/", m.log),
]
