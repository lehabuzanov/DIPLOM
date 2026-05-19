from django.contrib import admin

from sem_corpus.apps.corpus.models import (
    Affiliation,
    Article,
    ArticleAuthor,
    ArticleFile,
    ArticleHighlight,
    ArticleText,
    ArticleToken,
    Author,
    CityLocation,
    Issue,
    Journal,
    Keyword,
    Lemma,
    SavedQuery,
    SavedSubcorpus,
    SavedSubcorpusArticle,
    SearchHistory,
    Section,
)


class ArticleAuthorInline(admin.TabularInline):
    model = ArticleAuthor
    extra = 1


class ArticleFileInline(admin.TabularInline):
    model = ArticleFile
    extra = 1


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("short_title", "publisher", "site_url", "is_active")


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("journal", "year", "volume", "number", "publication_date")
    list_filter = ("journal", "year")
    search_fields = ("title", "number", "volume")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("name", "journal", "sort_order")
    list_filter = ("journal",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Affiliation)
class AffiliationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "country", "city_location", "geography_confidence", "geography_source")
    list_filter = ("country", "geography_source", "city_location__country")
    search_fields = ("name", "city", "city_location__display_name")


@admin.register(CityLocation)
class CityLocationAdmin(admin.ModelAdmin):
    list_display = ("display_name", "region", "country", "latitude", "longitude", "geocode_source", "is_verified")
    list_filter = ("country", "geocode_source", "is_verified", "needs_review")
    search_fields = ("display_name", "normalized_name", "region", "country")


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("full_name", "orcid", "email")
    search_fields = ("first_name", "last_name", "middle_name", "orcid")
    prepopulated_fields = {"slug": ("last_name", "first_name")}


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("name", "normalized", "language")
    search_fields = ("name", "normalized")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "issue", "section", "language", "is_published")
    list_filter = ("language", "is_published", "section", "issue__year")
    search_fields = ("title", "doi", "abstract", "import_source")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ArticleAuthorInline, ArticleFileInline]


@admin.register(ArticleText)
class ArticleTextAdmin(admin.ModelAdmin):
    list_display = ("article", "token_count", "lemma_count", "updated_at")
    search_fields = ("article__title", "cleaned_text", "body_text")


@admin.register(ArticleHighlight)
class ArticleHighlightAdmin(admin.ModelAdmin):
    list_display = ("article", "user", "char_start", "char_end", "created_at")
    list_filter = ("created_at",)
    search_fields = ("article__title", "user__username", "selected_text", "note_text")


@admin.register(Lemma)
class LemmaAdmin(admin.ModelAdmin):
    list_display = ("normalized", "language", "part_of_speech")
    search_fields = ("normalized",)


@admin.register(ArticleToken)
class ArticleTokenAdmin(admin.ModelAdmin):
    list_display = ("token", "article", "position", "lemma", "source_section")
    list_filter = ("source_section", "article__language")
    search_fields = ("token", "normalized", "lemma__normalized", "article__title")


@admin.register(SavedQuery)
class SavedQueryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "last_result_count", "updated_at")
    search_fields = ("name", "user__username")


@admin.register(SavedSubcorpus)
class SavedSubcorpusAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "article_count", "token_count", "is_public")
    search_fields = ("name", "user__username")


@admin.register(SavedSubcorpusArticle)
class SavedSubcorpusArticleAdmin(admin.ModelAdmin):
    list_display = ("subcorpus", "article", "source")
    list_filter = ("source",)


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ("query_text", "search_type", "result_count", "created_at")
    list_filter = ("search_type", "created_at")
    search_fields = ("query_text",)
