#!/bin/sh
set -e
# Этап разработки: миграции создаются автоматически и попадают в папку проекта.
# Закоммитьте папку backend/core/migrations после первого запуска.
python manage.py makemigrations core --noinput
python manage.py migrate --noinput
exec "$@"
