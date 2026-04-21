from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from sem_corpus.apps.accounts.models import Role
from sem_corpus.apps.corpus.models import (
    Affiliation,
    Article,
    ArticleAuthor,
    ArticleFile,
    ArticleText,
    Author,
    Issue,
    Journal,
    SavedQuery,
    Section,
)
from sem_corpus.apps.corpus.services import build_subcorpus, save_query, sync_keywords_for_article


User = get_user_model()


DEMO_ARTICLES = [
    {
        "issue": {"year": 2023, "volume": "19", "number": "2", "title": "Управленческие практики и региональная экономика"},
        "section": "Региональное управление",
        "slug": "regional-labor-productivity-2023",
        "title": "Оценка факторов роста производительности труда в промышленности региона",
        "abstract": "Статья рассматривает управленческие и институциональные факторы роста производительности труда в промышленных организациях региона.",
        "keywords": "производительность труда, региональное управление, промышленность, эффективность",
        "pages": "12-21",
        "doi": "10.12345/sem.2023.2.01",
        "authors": [
            ("Иван", "Петров", "Сергеевич", "ИжГТУ имени М. Т. Калашникова"),
            ("Ольга", "Соколова", "Владимировна", "Удмуртский государственный университет"),
        ],
        "body": (
            "Производительность труда в промышленности региона зависит от качества управленческих решений, "
            "доступности цифровой инфраструктуры и устойчивости кооперационных связей. В исследовании показано, "
            "что региональная политика поддержки модернизации влияет на снижение транзакционных издержек и рост "
            "выпуска. Авторы анализируют данные предприятий, сравнивают показатели эффективности и выделяют "
            "значение организационного обучения. Отдельно рассматривается управленческая координация между "
            "вузами, промышленными кластерами и органами власти."
        ),
        "references": "1. Методические подходы к оценке производительности. 2. Региональная промышленная политика.",
    },
    {
        "issue": {"year": 2023, "volume": "19", "number": "2", "title": "Управленческие практики и региональная экономика"},
        "section": "Цифровая экономика",
        "slug": "digital-services-municipal-management-2023",
        "title": "Цифровые сервисы как инструмент повышения прозрачности муниципального управления",
        "abstract": "Исследование посвящено внедрению цифровых сервисов в контур муниципального управления и их влиянию на прозрачность решений.",
        "keywords": "цифровые сервисы, муниципальное управление, прозрачность, цифровизация",
        "pages": "22-31",
        "doi": "10.12345/sem.2023.2.02",
        "authors": [
            ("Мария", "Кузнецова", "Игоревна", "ИжГТУ имени М. Т. Калашникова"),
        ],
        "body": (
            "Цифровые сервисы создают единое информационное окно для граждан, администрации и операторов услуг. "
            "Переход к цифровому взаимодействию позволяет фиксировать этапы принятия решения, улучшает "
            "контроль сроков и повышает доверие к муниципальному управлению. В статье обсуждаются барьеры "
            "цифровизации, вопросы информационной грамотности и требования к качеству данных."
        ),
        "references": "1. Электронное правительство. 2. Цифровые платформы в публичном секторе.",
    },
    {
        "issue": {"year": 2024, "volume": "20", "number": "1", "title": "Трансформация управленческих систем"},
        "section": "Лингвистика и цифровые исследования",
        "slug": "scientific-terminology-corpus-2024",
        "title": "Корпусный анализ терминологии социально-экономического управления в научных публикациях",
        "abstract": "Работа описывает подход к корпусному исследованию терминологии управления на материале статей научного журнала.",
        "keywords": "корпусный анализ, терминология, управление, лемма, словоформа",
        "pages": "8-19",
        "doi": "10.12345/sem.2024.1.01",
        "authors": [
            ("Елена", "Миронова", "Андреевна", "ИжГТУ имени М. Т. Калашникова"),
            ("Алексей", "Романов", "Павлович", "Казанский федеральный университет"),
        ],
        "body": (
            "Корпусный анализ позволяет описывать терминологию управления на уровне словоформ, лемм и типичных "
            "контекстов. Авторы рассматривают научный текст как источник повторяющихся моделей аргументации. "
            "На материале статей выделяются наиболее частотные единицы, сопоставляются устойчивые сочетания и "
            "показывается, как термин управленческая эффективность распределяется по разделам журнала. "
            "Лемматизация помогает объединить варианты употребления и сделать поиск устойчивым."
        ),
        "references": "1. Корпусная лингвистика. 2. Научная терминология и цифровые методы.",
    },
    {
        "issue": {"year": 2024, "volume": "20", "number": "1", "title": "Трансформация управленческих систем"},
        "section": "Региональное управление",
        "slug": "human-capital-governance-2024",
        "title": "Человеческий капитал как ресурс устойчивого развития региональной управленческой системы",
        "abstract": "В статье анализируется роль человеческого капитала в обеспечении устойчивости региональной системы управления.",
        "keywords": "человеческий капитал, устойчивое развитие, регион, управление",
        "pages": "20-29",
        "doi": "10.12345/sem.2024.1.02",
        "authors": [
            ("Наталья", "Белова", "Олеговна", "Удмуртский государственный университет"),
        ],
        "body": (
            "Человеческий капитал рассматривается как ключевой ресурс устойчивого развития региона. "
            "Автор показывает, что управленческая система выигрывает от инвестиций в образование, переподготовку "
            "и развитие исследовательских компетенций. Отмечается связь между качеством кадровой политики, "
            "инновационной активностью и адаптивностью институтов."
        ),
        "references": "1. Теория человеческого капитала. 2. Региональная политика развития кадров.",
    },
    {
        "issue": {"year": 2025, "volume": "21", "number": "1", "title": "Аналитические методы и управление данными"},
        "section": "Цифровая экономика",
        "slug": "data-governance-industrial-platforms-2025",
        "title": "Управление данными на промышленных платформах: организационные и экономические эффекты",
        "abstract": "Статья посвящена моделям data governance на промышленных цифровых платформах.",
        "keywords": "данные, цифровые платформы, промышленность, data governance",
        "pages": "14-26",
        "doi": "10.12345/sem.2025.1.01",
        "authors": [
            ("Мария", "Кузнецова", "Игоревна", "ИжГТУ имени М. Т. Калашникова"),
            ("Иван", "Петров", "Сергеевич", "ИжГТУ имени М. Т. Калашникова"),
        ],
        "body": (
            "Управление данными становится центральным элементом цифровой платформы предприятия. "
            "Авторы описывают регламенты доступа к данным, роль метаданных и механизмы контроля качества. "
            "Показано, что прозрачное управление данными повышает экономическую эффективность платформы, "
            "снижает дублирование операций и поддерживает аналитические сервисы для руководителей."
        ),
        "references": "1. Управление данными. 2. Цифровые платформы в промышленности.",
    },
    {
        "issue": {"year": 2025, "volume": "21", "number": "1", "title": "Аналитические методы и управление данными"},
        "section": "Лингвистика и цифровые исследования",
        "slug": "subcorpus-comparison-management-discourse-2025",
        "title": "Сравнение подкорпусов управленческого дискурса по тематическим разделам журнала",
        "abstract": "Работа демонстрирует возможности сравнения подкорпусов и выявления характерных единиц управленческого дискурса.",
        "keywords": "подкорпус, дискурс, сравнение, частотность, конкорданс",
        "pages": "27-38",
        "doi": "10.12345/sem.2025.1.02",
        "authors": [
            ("Елена", "Миронова", "Андреевна", "ИжГТУ имени М. Т. Калашникова"),
        ],
        "body": (
            "Сравнение подкорпусов позволяет увидеть, какие единицы характерны для разных тематических разделов журнала. "
            "Исследование опирается на частотный список лемм, анализ конкорданса и вычисление относительных различий. "
            "В разделе цифровой экономики чаще встречаются слова данные, платформа и цифровой, тогда как в разделе "
            "регионального управления преобладают единицы регион, развитие и политика. Такой подход удобен для "
            "повторного использования исследовательских выборок."
        ),
        "references": "1. Частотный анализ. 2. Методы сравнения подкорпусов.",
    },
]


class Command(BaseCommand):
    help = "Заполняет проект демонстрационными ролями, пользователями, статьями, запросами и подкорпусами."

    def handle(self, *args, **options):
        journal, _ = Journal.objects.get_or_create(
            short_title="Социально-экономическое управление: теория и практика",
            defaults={
                "title": "Научный журнал «Социально-экономическое управление: теория и практика»",
                "publisher": "ИжГТУ имени М. Т. Калашникова",
                "description": "Электронный корпус научного журнала для хранения, поиска и анализа публикаций.",
                "site_url": "https://izdat.istu.ru/index.php/social-economic-management",
                "integration_hint": "Отдельный путь /corpus/ или самостоятельный поддомен.",
            },
        )

        roles = {
            "researcher": Role.objects.get_or_create(
                slug="researcher",
                defaults={"name": "Исследователь", "can_save_queries": True},
            )[0],
            "editor": Role.objects.get_or_create(
                slug="editor",
                defaults={"name": "Редактор", "can_edit_content": True, "can_run_imports": True, "can_save_queries": True},
            )[0],
            "administrator": Role.objects.get_or_create(
                slug="administrator",
                defaults={
                    "name": "Администратор",
                    "can_manage_users": True,
                    "can_edit_content": True,
                    "can_run_imports": True,
                    "can_save_queries": True,
                },
            )[0],
        }

        researcher, _ = User.objects.get_or_create(
            username="researcher",
            defaults={"email": "researcher@example.com", "first_name": "Научный", "last_name": "Пользователь"},
        )
        researcher.set_password("research123")
        researcher.save()
        researcher.profile.institution = "ИжГТУ имени М. Т. Калашникова"
        researcher.profile.primary_role = roles["researcher"]
        researcher.profile.save()

        editor, _ = User.objects.get_or_create(
            username="editor",
            defaults={"email": "editor@example.com", "first_name": "Редактор", "last_name": "Корпуса", "is_staff": True},
        )
        editor.is_staff = True
        editor.set_password("editor123")
        editor.save()
        editor.profile.institution = "ИжГТУ имени М. Т. Калашникова"
        editor.profile.primary_role = roles["editor"]
        editor.profile.save()

        admin_user, _ = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "first_name": "Системный",
                "last_name": "Администратор",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password("admin123")
        admin_user.save()
        admin_user.profile.primary_role = roles["administrator"]
        admin_user.profile.save()

        section_map = {}
        for order, section_name in enumerate(
            ["Региональное управление", "Цифровая экономика", "Лингвистика и цифровые исследования"], start=1
        ):
            section_map[section_name], _ = Section.objects.get_or_create(
                journal=journal,
                slug=slugify(section_name),
                defaults={"name": section_name, "sort_order": order},
            )

        for item in DEMO_ARTICLES:
            issue, _ = Issue.objects.get_or_create(
                journal=journal,
                year=item["issue"]["year"],
                volume=item["issue"]["volume"],
                number=item["issue"]["number"],
                defaults={
                    "title": item["issue"]["title"],
                    "source_url": "https://izdat.istu.ru/index.php/social-economic-management",
                },
            )
            article, _ = Article.objects.get_or_create(
                slug=item["slug"],
                defaults={
                    "journal": journal,
                    "issue": issue,
                    "section": section_map[item["section"]],
                    "title": item["title"],
                    "language": Article.LANGUAGE_RU,
                    "pages": item["pages"],
                    "doi": item["doi"],
                    "abstract": item["abstract"],
                    "original_url": "https://izdat.istu.ru/index.php/social-economic-management",
                    "import_source": "seed_demo_data",
                    "is_published": True,
                },
            )
            article.journal = journal
            article.issue = issue
            article.section = section_map[item["section"]]
            article.title = item["title"]
            article.language = Article.LANGUAGE_RU
            article.pages = item["pages"]
            article.doi = item["doi"]
            article.abstract = item["abstract"]
            article.original_url = "https://izdat.istu.ru/index.php/social-economic-management"
            article.import_source = "seed_demo_data"
            article.is_published = True
            article.save()

            ArticleAuthor.objects.filter(article=article).delete()
            for order, (first_name, last_name, middle_name, affiliation_name) in enumerate(item["authors"], start=1):
                affiliation, _ = Affiliation.objects.get_or_create(name=affiliation_name)
                author, _ = Author.objects.get_or_create(
                    slug=slugify(f"{last_name}-{first_name}-{middle_name}"),
                    defaults={
                        "first_name": first_name,
                        "last_name": last_name,
                        "middle_name": middle_name,
                    },
                )
                author.first_name = first_name
                author.last_name = last_name
                author.middle_name = middle_name
                author.save()
                author.affiliations.add(affiliation)
                ArticleAuthor.objects.create(
                    article=article,
                    author=author,
                    affiliation=affiliation,
                    order=order,
                    display_name=f"{last_name} {first_name} {middle_name}".strip(),
                )

            article_text, _ = ArticleText.objects.update_or_create(
                article=article,
                defaults={
                    "title_text": item["title"],
                    "abstract_text": item["abstract"],
                    "keywords_text": item["keywords"],
                    "body_text": item["body"],
                    "references_text": item["references"],
                },
            )
            sync_keywords_for_article(article, item["keywords"])

            file_obj, _ = ArticleFile.objects.get_or_create(
                article=article,
                file_kind=ArticleFile.KIND_TXT,
                defaults={"original_filename": f"{article.slug}.txt"},
            )
            file_obj.original_filename = f"{article.slug}.txt"
            file_obj.file_kind = ArticleFile.KIND_TXT
            file_obj.external_url = article.original_url
            file_obj.file.save(
                f"{article.slug}.txt",
                ContentFile(
                    f"{article.title}\n\n{item['abstract']}\n\n{item['body']}\n\n{item['references']}",
                    name=f"{article.slug}.txt",
                ),
                save=True,
            )

            self.stdout.write(self.style.SUCCESS(f"Подготовлена статья: {article.title}"))

        SavedQuery.objects.filter(user=researcher).delete()
        researcher.saved_subcorpora.all().delete()

        save_query(
            researcher,
            "Лемма «управление» в разделе лингвистики",
            "Демонстрационный запрос для защиты.",
            (
                '{"text_query": "управление", "search_mode": "lemma", '
                f'"section": {section_map["Лингвистика и цифровые исследования"].pk}, '
                '"year_from": 2024, "year_to": 2025}'
            ),
            result_count=2,
        )
        build_subcorpus(
            researcher,
            "Лингвистический подкорпус 2024–2025",
            "Статьи раздела лингвистики и цифровых исследований за 2024–2025 годы.",
            (
                '{'
                f'"section": {section_map["Лингвистика и цифровые исследования"].pk}, '
                '"year_from": 2024, "year_to": 2025}'
            ),
            is_public=True,
        )
        build_subcorpus(
            researcher,
            "Цифровая экономика 2023–2025",
            "Публикации о цифровых сервисах, платформах и управлении данными.",
            (
                '{'
                f'"section": {section_map["Цифровая экономика"].pk}, '
                '"year_from": 2023, "year_to": 2025}'
            ),
            is_public=True,
        )

        self.stdout.write(self.style.SUCCESS("Демо-данные успешно загружены."))
        self.stdout.write("Пользователь researcher / пароль research123")
        self.stdout.write("Пользователь editor / пароль editor123")
        self.stdout.write("Пользователь admin / пароль admin123")
