# Демо в интернете: GitHub + Supabase + Vercel

Только для показа MVP на демо-данных. Серверы за рубежом — реальные данные сотрудников
сюда не загружать (152-ФЗ). Рабочая версия — на сервере в РФ (этап 5).

## 0. Перед началом
- В папке `backend\core\migrations` должны быть файлы `0001_initial.py` (и, возможно, `0002_...`).
  Они создаются автоматически при локальном запуске (`docker compose up -d`). Без них база в облаке не создастся.
- Сгенерируйте два случайных значения (PowerShell), сохраните их у себя:
  ```powershell
  -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 50 | % {[char]$_})   # DJANGO_SECRET_KEY
  -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | % {[char]$_})   # SETUP_TOKEN
  ```

## 1. GitHub
1. Создайте **приватный** репозиторий `banya-crm` на github.com (без README).
2. В папке проекта:
   ```powershell
   git init
   git add -A
   git status          # убедитесь, что .env в списке НЕТ
   git commit -m "CRM MVP"
   git branch -M main
   git remote add origin https://github.com/ВАШ_ЛОГИН/banya-crm.git
   git push -u origin main
   ```

## 2. Supabase (база)
1. supabase.com → New project. Регион: **Central EU (Frankfurt)**.
   Пароль базы — **только латинские буквы и цифры** (спецсимволы ломают строку подключения).
2. Кнопка **Connect** → **Transaction pooler** (порт **6543**) → скопируйте строку вида
   `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`
   и замените `[YOUR-PASSWORD]` на пароль базы.

## 3. Vercel (сайт)
1. vercel.com → войти через GitHub → **Add New → Project** → выбрать `banya-crm`.
2. **Root Directory: `backend`**. Framework Preset: **Other**.
3. **Environment Variables**:

   | Имя | Значение |
   |---|---|
   | `DATABASE_URL` | строка из Supabase (шаг 2) |
   | `DJANGO_SECRET_KEY` | первое случайное значение |
   | `DJANGO_DEBUG` | `0` |
   | `DJANGO_ALLOWED_HOSTS` | `.vercel.app` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://*.vercel.app` |
   | `DEMO_PASSWORD` | пароль демо-входов (от 10 символов) |
   | `SETUP_TOKEN` | второе случайное значение |

4. **Deploy**. Через 1–2 минуты будет адрес `https://banya-crm-xxxx.vercel.app`.

## 4. Создать таблицы и демо-данные — один раз
Откройте в браузере:
```
https://ВАШ_АДРЕС.vercel.app/setup/?token=ВАШ_SETUP_TOKEN
```
Должен появиться текст с `OK` по миграциям и «Готово».

Затем в Vercel: **Settings → Environment Variables** → удалите `SETUP_TOKEN` →
**Deployments → … → Redeploy**. После этого адрес `/setup/` отвечает 404.

## 5. Перед показом
- Войдите в `/admin/` как `superadmin` → вверху «Изменить пароль».
- Проверьте ссылку **с мобильного интернета** (не Wi-Fi): Vercel в РФ иногда режется у операторов.
- Клиентам: ссылка + входы `manager` (кабинет) и `olga` (смена), пароль — ваш `DEMO_PASSWORD`.

## Обновления
`git add -A && git commit -m "..." && git push` — Vercel пересоберёт сам.
Если в обновлении есть новые миграции: снова задайте `SETUP_TOKEN`, Redeploy, откройте `/setup/?token=...`,
затем удалите токен (демо-данные повторно не заливаются).

## Ограничения бесплатных тарифов
- Supabase Free засыпает после ~7 дней без запросов — разбудить в панели Supabase.
- Vercel Hobby — для некоммерческого использования; первая загрузка после простоя — 2–5 секунд.
- Блокировка после 5 неверных паролей работает в пределах одного экземпляра функции — для демо достаточно.
