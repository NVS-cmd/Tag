"""Отдача приложения (PWA). Service worker отдаётся с корня, чтобы управлять всем сайтом."""
from pathlib import Path

from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

APP_DIR = Path(__file__).resolve().parent / "static" / "app"


@ensure_csrf_cookie
def app_index(request):
    return render(request, "app/index.html")


def _file(name, content_type, extra_headers=None):
    path = APP_DIR / name
    if not path.is_file():
        raise Http404
    resp = FileResponse(open(path, "rb"), content_type=content_type)
    resp["Cache-Control"] = "no-cache"
    for k, v in (extra_headers or {}).items():
        resp[k] = v
    return resp


def service_worker(_request):
    return _file("sw.js", "application/javascript", {"Service-Worker-Allowed": "/"})


def manifest(_request):
    return _file("manifest.webmanifest", "application/manifest+json")


# ---------- первичная настройка облачной базы (Vercel + Supabase) ----------
import hmac  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.http import HttpResponse  # noqa: E402


@transaction.non_atomic_requests
def cloud_setup(request):
    """Создать таблицы и залить демо-данные в облачной базе — открыть один раз в браузере.

    /setup/?token=<SETUP_TOKEN>. Работает, только пока в настройках Vercel задан SETUP_TOKEN;
    после настройки переменную нужно удалить — тогда адрес отвечает 404.
    """
    secret = os.environ.get("SETUP_TOKEN", "")
    given = request.GET.get("token", "")
    if len(secret) < 16 or not hmac.compare_digest(secret.encode(), given.encode()):
        raise Http404
    out = io.StringIO()
    with connection.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    out.write("Расширение btree_gist: OK\n")
    call_command("migrate", interactive=False, stdout=out, verbosity=1)
    from .models import Point
    if Point.objects.exists():
        out.write("\nДемо-данные уже есть — не трогаю.\n")
    else:
        call_command("seed_demo", stdout=out)
    out.write("\nГотово. Удалите SETUP_TOKEN в настройках Vercel и сделайте Redeploy.\n")
    return HttpResponse(out.getvalue(), content_type="text/plain; charset=utf-8")
