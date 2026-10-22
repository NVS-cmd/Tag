# Все действия — одной командой. На Windows без make — команды из README.
DC = docker compose
RUN = $(DC) exec backend

.PHONY: up down logs test test-calc seed demo-reset shell migrate ps

up:            ## Поднять систему (база + сервер) на http://localhost:8000
	$(DC) up -d --build --wait
	@echo "Готово: http://localhost:$${APP_PORT:-8000}/"

down:          ## Остановить (данные сохраняются)
	$(DC) down

logs:          ## Логи сервера
	$(DC) logs -f backend

ps:
	$(DC) ps

test:          ## Все тесты на настоящей PostgreSQL
	$(RUN) python manage.py test core -v 2

test-calc:     ## Только расчёты (быстро)
	$(RUN) python -m unittest core.tests.test_calc -v

seed:          ## Заполнить пустую базу демо-данными
	$(RUN) python manage.py seed_demo

demo-reset:    ## Стереть всё и заново заполнить демо (только DEMO_MODE=1)
	$(RUN) python manage.py seed_demo --reset

migrate:
	$(RUN) python manage.py makemigrations core
	$(RUN) python manage.py migrate

shell:
	$(RUN) python manage.py shell
