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
- Импорт архива: `requests + BeautifulSoup + pypdf`

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

## Что происходит при запуске Docker

Контейнер `web` автоматически:

- устанавливает зависимости;
- применяет миграции;
- удаляет старый демонстрационный контент;
- создает служебные роли и учетные записи;
- поднимает сайт на `8000` порту.

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

## Самопроверка

Проверка ключевых функций:

```powershell
docker compose exec web python manage.py selfcheck_corpus
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

## Служебные учетные записи

- `researcher` / `research123`
- `editor` / `editor123`
- `admin` / `admin123`

## Полезные команды

```powershell
docker compose exec web python manage.py sync_ojs_journal --skip-existing
docker compose exec web python manage.py repair_article_texts
docker compose exec web python manage.py rebuild_corpus_index
docker compose exec web python manage.py selfcheck_corpus
docker compose exec web python manage.py import_corpus_batch --source sample_data/batch_import
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
python manage.py seed_demo_data
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
