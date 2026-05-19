from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal

import requests

from sem_corpus.apps.corpus.models import Affiliation, CityLocation
from sem_corpus.apps.corpus.services import normalize_whitespace


@dataclass(frozen=True)
class CitySeed:
    display_name: str
    country: str
    latitude: float
    longitude: float
    region: str = ""
    aliases: tuple[str, ...] = ()


CITY_SEEDS: tuple[CitySeed, ...] = (
    CitySeed("Ижевск", "Россия", 56.852738, 53.211489, "Удмуртская Республика", ("ижевск", "ижевский", "ижевская", "ижгту", "удмуртский", "удмуртская", "удмуртнефтегеофизика", "национальный банк по удмуртской республике", "казначейства по удмуртской республике")),
    CitySeed("Сарапул", "Россия", 56.461611, 53.803696, "Удмуртская Республика", ("сарапул", "сарапульский")),
    CitySeed("Глазов", "Россия", 58.140965, 52.674417, "Удмуртская Республика", ("глазов", "глазовский")),
    CitySeed("Москва", "Россия", 55.755864, 37.617698, "Москва", ("москва", "московский", "мирэа", "мисис", "плеханова", "рудн", "российский университет дружбы", "патриса лумумбы", "виноградова", "государственный институт русского языка", "гаугн", "государственный академический университет гуманитарных наук", "ранхигс", "российская академия народного хозяйства", "внии центр", "внии «центр»", "фгуп внии", "всероссийский научно-исследовательский институт центр")),
    CitySeed("Санкт-Петербург", "Россия", 59.938951, 30.315635, "Санкт-Петербург", ("санкт-петербург", "санкт петербург", "санкт-петербургский", "санкт петербургский", "петербург", "петербургский", "герцена", "лэти")),
    CitySeed("Пушкин", "Россия", 59.721995, 30.416771, "Санкт-Петербург", ("ленинградский государственный университет им. а. с. пушкина",)),
    CitySeed("Казань", "Россия", 55.796127, 49.106405, "Республика Татарстан", ("казань", "казанский")),
    CitySeed("Кемерово", "Россия", 55.354968, 86.087314, "Кемеровская область", ("кемерово", "кемеровский")),
    CitySeed("Красноярск", "Россия", 56.009466, 92.852416, "Красноярский край", ("красноярск", "красноярский", "сибирский государственный университет науки")),
    CitySeed("Курган", "Россия", 55.441004, 65.341118, "Курганская область", ("курган", "курганский")),
    CitySeed("Луганск", "Россия", 48.574041, 39.307815, "Луганская Народная Республика", ("луганск", "луганский")),
    CitySeed("Саранск", "Россия", 54.180761, 45.186226, "Республика Мордовия", ("саранск", "мордовский")),
    CitySeed("Пермь", "Россия", 58.010455, 56.229443, "Пермский край", ("пермь", "пермский")),
    CitySeed("Йошкар-Ола", "Россия", 56.634366, 47.899970, "Республика Марий Эл", ("йошкар-ола", "поволжский государственный технологический университет")),
    CitySeed("Самара", "Россия", 53.195873, 50.100193, "Самарская область", ("самара", "самарский", "университет мир", "поволжский государственный университет телекоммуникаций")),
    CitySeed("Уфа", "Россия", 54.735152, 55.958736, "Республика Башкортостан", ("уфа", "уфимский", "уфиц ран", "институт социально-экономических исследований уфиц")),
    CitySeed("Екатеринбург", "Россия", 56.838011, 60.597474, "Свердловская область", ("екатеринбург", "уральский федеральный", "уральский государственный", "уро ран")),
    CitySeed("Челябинск", "Россия", 55.159897, 61.402554, "Челябинская область", ("челябинск", "челябинский")),
    CitySeed("Череповец", "Россия", 59.122612, 37.903461, "Вологодская область", ("череповец", "череповецкий")),
    CitySeed("Вологда", "Россия", 59.220492, 39.891568, "Вологодская область", ("вологда", "вологодский")),
    CitySeed("Сыктывкар", "Россия", 61.668797, 50.836497, "Республика Коми", ("сыктывкар", "сыктывкарский")),
    CitySeed("Томск", "Россия", 56.484703, 84.948173, "Томская область", ("томск", "томский")),
    CitySeed("Минск", "Беларусь", 53.902284, 27.561831, "", ("минск", "белорусский национальный")),
    CitySeed("Иджеван", "Армения", 40.878933, 45.148700, "Тавушская область", ("иджеван", "иджеванский")),
    CitySeed("Ереван", "Армения", 40.177628, 44.512546, "", ("ереван", "ереванский государственный университет")),
    CitySeed("Дьер", "Венгрия", 47.687456, 17.650397, "", ("дьер", "дьере", "университет святого иштвана")),
    CitySeed("Пула", "Хорватия", 44.866623, 13.849579, "", ("пула", "пулы")),
    CitySeed("Чжэнчжоу", "Китай", 34.746611, 113.625328, "Хэнань", ("чжэнчжоу", "чжэнчжоуский")),
)


def normalize_city_name(value: str) -> str:
    normalized = normalize_whitespace(value).lower().replace("ё", "е")
    normalized = normalized.replace("г.", "").replace("город ", "")
    normalized = re.sub(r"[^a-zа-я0-9 -]+", " ", normalized)
    return normalize_whitespace(normalized)


def ensure_seed_city(seed: CitySeed, *, source: str = "gazetteer") -> CityLocation:
    city, _created = CityLocation.objects.update_or_create(
        normalized_name=normalize_city_name(seed.display_name),
        country=seed.country,
        defaults={
            "display_name": seed.display_name,
            "region": seed.region,
            "latitude": Decimal(str(seed.latitude)),
            "longitude": Decimal(str(seed.longitude)),
            "geocode_source": source,
            "is_verified": True,
            "needs_review": False,
        },
    )
    return city


def seed_city_locations() -> dict[str, CityLocation]:
    return {seed.display_name: ensure_seed_city(seed) for seed in CITY_SEEDS}


def detect_city_seed(text: str) -> tuple[CitySeed | None, float, str]:
    normalized_text = normalize_city_name(text)
    if not normalized_text:
        return None, 0, ""

    candidates: list[tuple[int, CitySeed, str]] = []
    for seed in CITY_SEEDS:
        aliases = (seed.display_name, *seed.aliases)
        for alias in aliases:
            normalized_alias = normalize_city_name(alias)
            if not normalized_alias:
                continue
            if re.search(rf"(^|\s){re.escape(normalized_alias)}(\s|$)", normalized_text):
                candidates.append((len(normalized_alias), seed, normalized_alias))

    if not candidates:
        return None, 0, ""
    _length, seed, alias = max(candidates, key=lambda item: item[0])
    confidence = 0.95 if normalize_city_name(seed.display_name) == alias else 0.82
    return seed, confidence, alias


def assign_affiliation_geography(affiliation: Affiliation, *, use_geocoder: bool = False) -> bool:
    seed, confidence, _alias = detect_city_seed(f"{affiliation.city} {affiliation.country} {affiliation.name}")
    city_location = None
    source = ""

    if seed:
        city_location = ensure_seed_city(seed)
        source = "gazetteer"
    elif use_geocoder:
        city_location = geocode_city_or_affiliation(affiliation.name)
        confidence = 0.62 if city_location else 0
        source = "nominatim" if city_location else ""

    changed = False
    if city_location:
        changed = (
            affiliation.city_location_id != city_location.pk
            or affiliation.city != city_location.display_name
            or affiliation.country != city_location.country
            or affiliation.geography_source != source
            or affiliation.geography_confidence != confidence
        )
        affiliation.city_location = city_location
        affiliation.city = city_location.display_name
        affiliation.country = city_location.country
        affiliation.geography_source = source
        affiliation.geography_confidence = confidence
    elif affiliation.geography_source != "unresolved":
        affiliation.geography_source = "unresolved"
        affiliation.geography_confidence = 0
        changed = True

    if changed:
        affiliation.save(
            update_fields=[
                "city",
                "country",
                "city_location",
                "geography_source",
                "geography_confidence",
                "updated_at",
            ]
        )
    return bool(city_location)


def geocode_city_or_affiliation(query: str) -> CityLocation | None:
    cleaned = normalize_whitespace(query)
    if not cleaned:
        return None
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": cleaned, "format": "json", "limit": 1, "accept-language": "ru"},
        headers={"User-Agent": "sem-corpus-geocoder/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    items = response.json()
    if not items:
        return None

    item = items[0]
    display_parts = [part.strip() for part in (item.get("display_name") or cleaned).split(",") if part.strip()]
    display_name = display_parts[0] if display_parts else cleaned
    country = display_parts[-1] if len(display_parts) > 1 else "Россия"
    city, _created = CityLocation.objects.update_or_create(
        normalized_name=normalize_city_name(display_name),
        country=country,
        defaults={
            "display_name": display_name,
            "latitude": Decimal(str(item["lat"])),
            "longitude": Decimal(str(item["lon"])),
            "geocode_source": "nominatim",
            "is_verified": False,
            "needs_review": True,
        },
    )
    time.sleep(1.1)
    return city
