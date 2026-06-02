# Электронный корпус журнала «Социально-экономическое управление: теория и практика»

Веб-приложение на `Python + Django + PostgreSQL` для хранения, поиска, анализа и повторного использования текстов научного журнала ИжГТУ имени М. Т. Калашникова.

## Что реализовано

- каталог выпусков и статей;
- карточка статьи с метаданными, текстом и доступом к файлу;
- поиск по метаданным;
- полнотекстовый поиск;
- поиск по словоформе, лемме и фразе;
- сохраненные запросы с повторным открытием, редактированием и удалением;
- подкорпуса с обновлением состава, редактированием и удалением;
- частотные списки, биграммы и сравнение материалов;
- ручная загрузка статьи для редактора;
- синхронизация архива журнала с OJS;
- восстановление пропущенных текстов из PDF;
- встроенная самопроверка ключевых страниц и функций.

## Текущее состояние корпуса

- в архив импортировано `21` выпуск;
- в корпусе `265` опубликованных статей;
- тексты извлечены для всех `265` статей;
- если локальный PDF недоступен, ссылка на файл статьи автоматически ведет на рабочий внешний URL журнала.

## Архитектура

- Backend: `Django`
- База данных: `PostgreSQL`
- Интерфейс: `Django templates + Bootstrap 5`
- Аналитика: `Chart.js`
- Токенизация: `razdel`
- Лемматизация: `pymorphy3 + simplemma`
- Импорт архива: `requests + BeautifulSoup + PyMuPDF + pypdf fallback`

## Быстрый запуск через Docker

1. Скопируйте `.env.example` в `.env`.
2. Запустите проект:

```powershell
docker compose up --build
```

3. Откройте в браузере:

```text
http://127.0.0.1:8000/
```

Фоновый запуск:

```powershell
docker compose up -d --build
```

Остановка:

```powershell
docker compose down
```

Полная остановка с удалением томов БД и media:

```powershell
docker compose down -v
```

## Production-запуск через Docker

Для серверного размещения подготовлен отдельный compose-файл с PostgreSQL, Gunicorn, сбором статики и Nginx:

```powershell
copy .env.production.example .env
```

Заполните в `.env` домен, секреты, пароль БД и SMTP-настройки, затем выполните:

```powershell
docker compose -f docker-compose.prod.yml up -d --build
```

В production-режиме контейнер `web` автоматически:

- применяет миграции;
- подготавливает роли и права;
- выполняет `collectstatic`;
- запускает приложение через `gunicorn`.

Контейнер `nginx`:

- принимает HTTP-запросы;
- отдает `/static/` и `/media/`;
- проксирует Django-приложение на `web:8000`;
- передает заголовки `X-Forwarded-*` для корректной работы HTTPS за reverse proxy.

Если HTTPS завершается на Nginx, используйте пример `nginx/sem_corpus.ssl.conf.example`.
Если HTTPS завершается внешним прокси, например на стороне хостинга, оставьте обычный Nginx-конфиг и включите в `.env`:

```text
DJANGO_SECURE_PROXY_SSL_HEADER=1
DJANGO_USE_X_FORWARDED_HOST=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
```

## Что происходит при запуске Docker

Контейнер `web` автоматически:

- применяет миграции;
- удаляет старый демонстрационный контент;
- создает и синхронизирует роли, группы Django и права доступа;
- поднимает сайт на `8000` порту.

Зависимости устанавливаются на этапе `docker compose build`, поэтому старт контейнера не зависит от доступности PyPI.

## Загрузка полного архива журнала

После запуска сайта выполните:

```powershell
docker compose exec web python manage.py sync_ojs_journal --skip-existing
```

Эта команда:

- проходит по архиву OJS журнала;
- добавляет новые выпуски и статьи;
- загружает PDF;
- извлекает текст и строит поисковый индекс.

## Восстановление текстов из PDF

Если какие-то статьи были импортированы без текста, выполните:

```powershell
docker compose exec web python manage.py repair_article_texts
```

После доработки проекта эта команда уже успешно восстановила тексты для всех статей корпуса.

Проверка качества извлеченного текста:

```powershell
docker compose exec web python manage.py audit_article_texts --check-pdf-pages
```

Точечный ремонт только проблемных текстов:

```powershell
docker compose exec web python manage.py repair_article_texts --quality-only --skip-download
```

## Самопроверка

Проверка ключевых функций:

```powershell
docker compose exec web python manage.py selfcheck_corpus
```

Production-ready проверка перед выкладкой:

```powershell
docker compose exec web python manage.py production_check --strict
```

Автотесты критичных сценариев:

```powershell
docker compose exec web python manage.py test sem_corpus.apps.corpus
```

Проверка структуры Django:

```powershell
python manage.py check
```

## Автодобавление новых статей

Для автоматического пополнения корпуса подходит команда:

```powershell
docker compose exec web python manage.py sync_ojs_journal --skip-existing
```

Рекомендуемый способ внедрения:

- развернуть проект на сервере;
- запускать эту команду по расписанию через `cron`, `systemd timer` или планировщик задач;
- после синхронизации при необходимости запускать `repair_article_texts`.

Важно:

- текущий механизм рассчитан на сайт журнала на OJS;
- он будет работать стабильно, пока сохраняются архивная страница, ссылки на выпуски и метатеги статей;
- если тема OJS или HTML-разметка сайта журнала сильно изменится, парсер нужно будет быстро адаптировать.

## Где загружать статью вручную

После входа под редактором или администратором в верхнем меню доступен пункт:

```text
Загрузка статьи
```

Прямой адрес:

```text
/corpus/articles/upload/
```

Также доступна административная панель:

```text
/admin/
```

## Пользователи, роли и пароли

При обычном запуске Docker больше не создает и не сбрасывает пароли демонстрационных пользователей.
Команда запуска только подготавливает роли и права:

```powershell
docker compose exec web python manage.py prepare_access_control --assign-missing-researcher
```

Роли:

- `Исследователь` — сохраняет запросы, подкорпуса и пометки, использует аналитику;
- `Редактор` — имеет права исследователя, открывает `/admin/`, редактирует модели корпуса и загружает статьи;
- `Администратор` — управляет пользователями, ролями, группами и всеми данными корпуса.

Новые пользователи после регистрации автоматически получают роль `Исследователь`.
Роли редактора и администратора назначаются только через административную панель.

Первого администратора для нового развертывания создайте штатной командой Django:

```powershell
docker compose exec web python manage.py createsuperuser
```

Если в локальной демонстрационной БД уже есть старые учетные записи `admin`, `editor`, `researcher`,
сначала можно синхронизировать их роли без изменения паролей:

```powershell
docker compose exec web python manage.py prepare_access_control --assign-missing-researcher --sync-service-users
```

После этого смените им пароли через `/accounts/password/change/`, через `/admin/` или командой:

```powershell
docker compose exec web python manage.py changepassword admin
```

Для локальной демонстрации можно явно создать/обновить старые демо-аккаунты, но эту команду нельзя использовать в production:

```powershell
docker compose exec web python manage.py seed_demo_data --reset-passwords
```

## Настройки для размещения

Перед публикацией на хостинге журнала в `.env` нужно задать боевые значения:

- `DJANGO_DEBUG=0`;
- длинный случайный `DJANGO_SECRET_KEY`;
- реальные `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS`;
- `LEAFLET_TILE_URL`, если хостер использует свой источник картографических тайлов вместо OpenStreetMap;
- `DJANGO_SECURE_SSL_REDIRECT=1`, `DJANGO_SESSION_COOKIE_SECURE=1`, `DJANGO_CSRF_COOKIE_SECURE=1` при работе через HTTPS;
- `DJANGO_SECURE_HSTS_SECONDS`, если домен полностью обслуживается по HTTPS;
- SMTP-параметры `DJANGO_EMAIL_*`, если будет включаться отправка писем.

Подтверждение email включается только при реальном SMTP:

```text
ACCOUNTS_REQUIRE_EMAIL_CONFIRMATION=1
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

Восстановление пароля также использует эти SMTP-настройки.

## Полезные команды

```powershell
docker compose exec web python manage.py prepare_access_control --assign-missing-researcher
docker compose exec web python manage.py sync_ojs_journal --skip-existing
docker compose exec web python manage.py audit_article_texts --check-pdf-pages
docker compose exec web python manage.py repair_article_texts
docker compose exec web python manage.py rebuild_corpus_index
docker compose exec web python manage.py refresh_author_geography
docker compose exec web python manage.py selfcheck_corpus
docker compose exec web python manage.py production_check --strict
docker compose exec web python manage.py import_corpus_batch --source sample_data/batch_import
docker compose exec web python manage.py changepassword admin
```

## Локальный запуск без Docker

1. Создайте БД PostgreSQL `sem_corpus`.
2. Скопируйте `.env.example` в `.env` и укажите параметры подключения.
3. Создайте виртуальное окружение и установите зависимости:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

4. Примените миграции и подготовьте служебные записи:

```powershell
python manage.py migrate
python manage.py purge_demo_content
python manage.py prepare_access_control --assign-missing-researcher
```

5. Импортируйте архив:

```powershell
python manage.py sync_ojs_journal --skip-existing
python manage.py repair_article_texts
```

6. Запустите сервер:

```powershell
python manage.py runserver
```
