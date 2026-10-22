"""Админка суперадмина: точки, учётные записи, справочники.

Деньги (сеансы, продажи, расходы, выплаты, смены) здесь только для просмотра:
менять их можно лишь через приложение, где работают проверки и журнал.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AdminCategoryRate, AuditLog, Device, Employee, Expense, ExpenseCategory, Payout, Point, Product,
    Program, Room, Sale, Session, Shift, User,
)

admin.site.site_header = "CRM — администрирование"
admin.site.site_title = "CRM"
admin.site.index_title = "Справочники и учётные записи"


def rub(kopecks):
    return "" if kopecks is None else f"{kopecks / 100:,.2f} ₽".replace(",", " ")


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0


@admin.register(Point)
class PointAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "rate_min", "rate_max", "rate_default", "is_active")
    inlines = [RoomInline]


class CategoryRateInline(admin.TabularInline):
    model = AdminCategoryRate
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "role", "point", "is_active", "archived_at")
    list_filter = ("role", "point", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Роль и точка", {"fields": ("role", "point", "phone", "archived_at")}),
        ("Ставки администратора", {"fields": ("rate_session", "rate_session_dispatcher", "rate_sauna")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Роль и точка", {"fields": ("role", "point", "first_name")}),
    )
    inlines = [CategoryRateInline]


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "point", "rate", "rate_with_dispatcher", "base_full", "archived_at")
    list_filter = ("kind", "point")
    search_fields = ("name", "phone")


admin.site.register(Program)
admin.site.register(Product)
admin.site.register(ExpenseCategory)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shift)
class ShiftAdmin(ReadOnlyAdmin):
    list_display = ("point", "admin", "status", "opened_at", "closed_at", "discrepancy_rub", "corrected")
    list_filter = ("point", "status")

    @admin.display(description="Расхождение")
    def discrepancy_rub(self, obj):
        return rub(obj.discrepancy)


@admin.register(Session)
class SessionAdmin(ReadOnlyAdmin):
    list_display = ("start", "room", "master", "dispatcher", "amount_rub", "payment_method", "status")
    list_filter = ("status", "payment_method", "room__point")

    @admin.display(description="Сумма")
    def amount_rub(self, obj):
        return rub(obj.amount)


@admin.register(Sale)
class SaleAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "product", "quantity", "amount", "payment_method", "status")


@admin.register(Expense)
class ExpenseAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "category", "amount", "payment_method", "comment", "status")


@admin.register(Payout)
class PayoutAdmin(ReadOnlyAdmin):
    list_display = ("shift", "employee", "admin", "accrued", "paid")


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("at", "actor", "action", "object_type", "reason")
    list_filter = ("action",)
    search_fields = ("action", "reason")


@admin.register(Device)
class DeviceAdmin(ReadOnlyAdmin):
    list_display = ("user", "label", "last_seen", "is_active")
