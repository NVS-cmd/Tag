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
