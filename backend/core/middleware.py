from django.contrib.auth import logout
from django.http import JsonResponse
from django.utils import timezone

from .models import Device

DEVICE_SESSION_KEY = "device_id"


class DeviceGuardMiddleware:
    """Если управляющий отключил устройство, следующий же запрос с него выходит из системы.

    Устройство привязывается к сессии при входе через приложение (этап 2).
    Вход в админку суперадмина устройство не создаёт и здесь не проверяется.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        device_id = request.session.get(DEVICE_SESSION_KEY) if hasattr(request, "session") else None
        if device_id and request.user.is_authenticated:
            device = Device.objects.filter(pk=device_id, user=request.user).first()
            if device is None or not device.is_active:
                logout(request)
                # Приложение получит 401 с флагом и сотрёт локальную офлайн-очередь
                return JsonResponse({"detail": "Устройство отключено управляющим.", "wipe": True}, status=401)
            now = timezone.now()
            if (now - device.last_seen).total_seconds() > 60:
                Device.objects.filter(pk=device.pk).update(last_seen=now, last_ip=request.META.get("REMOTE_ADDR"))
        return self.get_response(request)
