# Инструкция редактора и администратора

## Редактор

Редактор работает с корпусом двумя основными способами:

1. Через пользовательскую форму загрузки статьи:

```text
/corpus/articles/upload/
```

2. Через административную панель Django:

```text
/admin/
```

Через форму загрузки редактор может:

- добавить выпуск, если его ещё нет;
- добавить новую статью;
- указать авторов и аффилиации;
- загрузить файл статьи;
- вставить очищенный текст;
- заполнить аннотацию, ключевые слова, DOI и другие метаданные.

## Автоматическое пополнение корпуса

Для синхронизации с архивом OJS журнала используется команда:

```bash
python manage.py sync_ojs_journal
```

Полезные опции:

```bash
python manage.py sync_ojs_journal --skip-existing
python manage.py sync_ojs_journal --skip-pdf-download
python manage.py sync_ojs_journal --limit-issues 2
```

## Администратор

Администратор дополнительно:

- управляет пользователями и ролями;
- проверяет корректность данных;
- запускает индексацию;
- выполняет самопроверку корпуса;
- настраивает окружение и базу данных;
- очищает устаревший демо-контент, если он был загружен ранее.

## Полезные команды

```bash
python manage.py purge_demo_content
python manage.py seed_demo_data
python manage.py import_corpus_batch --source sample_data/batch_import
python manage.py sync_ojs_journal --skip-existing
python manage.py rebuild_corpus_index
python manage.py selfcheck_corpus
```
