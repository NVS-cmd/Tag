# CRM сети точек

Учёт смен, сеансов, доп. продаж, расходов, выплат и кассы.
Стек: Django + PostgreSQL в Docker. ТЗ и правила расчётов — в `PROJECT.md`.

## Первый запуск на Windows — одна команда

Нужен только Docker Desktop (запущенный). В папке проекта, в PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Скрипт сам создаст `.env` со случайными паролями, выберет свободный порт (8000 или 8080),
пропишет IP компьютера для телефона, соберёт, дождётся готовности базы и загрузит демо-данные.
Запускать повторно безопасно — например, когда сменилась сеть Wi-Fi.

## Первый запуск вручную (Mac, Linux)

```bash
cp .env.example .env        # затем откройте .env и поменяйте два пароля
docker compose up -d --build --wait
docker compose exec backend python manage.py seed_demo
```

- **Приложение:** http://localhost:8000/ — `olga` (или `irina`, `anna`, `svetlana`) — администратор,
  `manager` — кабинет управляющего.
- **Админка суперадмина:** http://localhost:8000/admin/ — вход `superadmin`.

Пароль у демо-входов — `DEMO_PASSWORD` из `.env`, по умолчанию `demo12345demo`.
Если порт 8000 занят, поставьте в `.env` `APP_PORT=8080` и открывайте :8080.

При первом запуске создастся папка `backend/core/migrations` — **закоммитьте её**:

```bash
git add -A && git commit -m "Этап 1: каркас, модели, демо-данные"
```

## Команды

| make | без make (Windows) | что делает |
|---|---|---|
| `make up` | `docker compose up -d --build` | поднять систему |
| `make down` | `docker compose down` | остановить, данные сохраняются |
| `make test` | `docker compose exec backend python manage.py test core -v 2` | все тесты на PostgreSQL |
| `make seed` | `docker compose exec backend python manage.py seed_demo` | демо-данные в пустую базу |
| `make demo-reset` | `docker compose exec backend python manage.py seed_demo --reset` | стереть всё и заполнить демо заново |
| `make logs` | `docker compose logs -f backend` | логи сервера |

## Демо-входы

| Логин | Роль | Точка |
|---|---|---|
| superadmin | суперадмин (админка) | — |
| manager | управляющий | все |
| olga | администратор | Точка 1 |
| irina, anna | администраторы | Точка 2 |
| svetlana | администратор | Точка 3 |

Пароль у всех — `DEMO_PASSWORD`. Только для показа: в рабочей базе демо-данных не будет.

## Если что-то не запускается

- **Образы не скачиваются** (`no such host`, таймаут) — по умолчанию они берутся через зеркало
  `mirror.gcr.io`. Если и оно недоступно, поменяйте в `.env` `PYTHON_IMAGE` и `POSTGRES_IMAGE`
  на `dockerhub.timeweb.cloud/library/...` или `dockerhub1.beget.com/library/...`.
- **`running scripts is disabled`** — запускайте именно так: `powershell -ExecutionPolicy Bypass -File setup.ps1`.
- **`/bin/sh^M` или `entrypoint.sh: not found`** (Windows) — файл получил окончания строк CRLF.
  Выполните `git add --renormalize . && git checkout -- backend/entrypoint.sh`.
- **Любая другая ошибка** — пришлите в чат вывод `docker compose logs backend` (без паролей).

## Демо в интернете

Пошагово: `DEPLOY_VERCEL.md` (GitHub + Supabase + Vercel, только демо-данные).

## Открыть с телефона

1. Телефон и компьютер в одной сети (общий Wi-Fi или раздача с одного из них).
2. Узнайте IP компьютера: `ipconfig` (Windows) → «IPv4-адрес», например `192.168.1.50`.
3. В `.env` допишите его:
   `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,192.168.1.50`
   `DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://192.168.1.50:8000` (порт — ваш `APP_PORT`)
4. `docker compose up -d --force-recreate backend`
5. Windows: откройте порт (PowerShell от администратора), сеть должна быть «Частная»:
   `New-NetFirewallRule -DisplayName "CRM" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow -Profile Private`
6. На телефоне: `http://192.168.1.50:8000/`

Установка иконкой на экран и работа без сети требуют HTTPS — это будет на сервере (этап 5).
По адресу `http://IP` приложение работает в браузере полностью, кроме этих двух функций.

## Безопасность

- `.env` не коммитится и не отправляется в чат.
- Порт базы наружу не открыт: к ней обращается только сервер внутри Docker.
