# Электронный корпус журнала «Социально-экономическое управление: теория и практика»

Веб-приложение на `Python + Django + PostgreSQL` для хранения, структурирования, поиска, анализа и повторного использования текстов научного журнала ИжГТУ имени М. Т. Калашникова.

## Архитектура

- Backend: `Django`
- Основная СУБД: `PostgreSQL`
- Интерфейс: `Django templates + Bootstrap 5`
- Аналитика: `Chart.js`
- Лингвистическая обработка: `razdel + pymorphy3`
- Импорт архива журнала: `requests + BeautifulSoup + pypdf`

## Что реализовано

- каталог выпусков и статей;
- карточка статьи с метаданными, аннотацией, файлами и очищенным текстом;
- поиск по метаданным;
- полнотекстовый поиск;
- поиск по словоформе, лемме и фразе;
- сохранение запросов;
- сохранение подкорпусов;
- частотные списки, биграммы и сравнение подкорпусов;
- ручная загрузка статьи через пользовательский интерфейс;
- пакетный импорт;
- синхронизация архива журнала из OJS;
- самопроверка ключевых страниц и сценариев.

## Структура проекта

- `sem_corpus/config/` — настройки Django.
- `sem_corpus/apps/core/` — главная страница, страницы «О корпусе» и инструкции.
- `sem_corpus/apps/accounts/` — регистрация, кабинет, роли и история действий.
- `sem_corpus/apps/corpus/` — модели корпуса, поиск, импорт, подкорпуса, редакторская загрузка.
- `sem_corpus/apps/analytics/` — частотность, графики, сравнение подкорпусов.
- `sample_data/` — тестовые данные для пакетного импорта.
- `docs/` — техническая и пользовательская документация.

## Быстрый запуск

### Вариант 1. Docker Compose

1. Скопируйте `.env.example` в `.env`.
2. Запустите:

```bash
docker compose up
```

3. Откройте в браузере:

```text
http://127.0.0.1:8000/
```

### Вариант 2. Локальный запуск через Python и PostgreSQL

1. Создайте базу данных PostgreSQL `sem_corpus`.
2. Скопируйте `.env.example` в `.env` и укажите параметры подключения.
3. Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

4. Выполните миграции:

```bash
python manage.py migrate
```

5. Загрузите стартовые данные:

```bash
python manage.py seed_demo_data
```

6. При необходимости синхронизируйте реальный архив журнала:

```bash
python manage.py sync_ojs_journal --skip-existing
```

7. Запустите сервер:

```bash
python manage.py runserver
```

## Где загружать статью

После входа под редактором или администратором в верхнем меню появляется пункт `Загрузка статьи`.

Прямой адрес формы:

```text
/corpus/articles/upload/
```

Для расширенной работы с данными также доступна админ-панель:

```text
/admin/
```

## Автоматическое пополнение корпуса из OJS

Полная синхронизация архива журнала:

```bash
python manage.py sync_ojs_journal
```

Только новые статьи:

```bash
python manage.py sync_ojs_journal --skip-existing
```

Только метаданные, без скачивания PDF:

```bash
python manage.py sync_ojs_journal --skip-pdf-download
```

## Самопроверка

Проверка ключевых страниц и основных функций:

```bash
python manage.py selfcheck_corpus
```

## Демо-учетные записи

- `researcher` / `research123`
- `editor` / `editor123`
- `admin` / `admin123`

## Полезные команды

```bash
python manage.py seed_demo_data
python manage.py import_corpus_batch --source sample_data/batch_import
python manage.py sync_ojs_journal --skip-existing
python manage.py rebuild_corpus_index
python manage.py selfcheck_corpus
```
