import json
import re
from dataclasses import asdict, dataclass, replace
from threading import RLock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ENTITIES = 24
COLUMNS = 4
CELLS = MAX_ENTITIES * 4
ENTITY_ID = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")


@dataclass(frozen=True)
class Entity:
    id: str
    label: str
    cell: int = 0
    width: int = 1
    height: int = 1


def parse_entities(raw):
    if not isinstance(raw, list) or len(raw) > MAX_ENTITIES:
        raise ValueError(f"The panel holds up to {MAX_ENTITIES} widgets.")
    occupied = set()
    ids = set()
    entities = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each widget needs an entity ID.")
        entity_id = item.get("id")
        if not isinstance(entity_id, str) or len(entity_id) > 255 or not ENTITY_ID.fullmatch(entity_id):
            raise ValueError("Invalid entity ID.")
        label = item.get("label") or entity_id
        if not isinstance(label, str) or len(label) > 120:
            raise ValueError("Widget labels must be at most 120 characters.")
        if entity_id in ids:
            raise ValueError("This entity is already on the panel.")
        width, height = item.get("width", 1), item.get("height", 1)
        if type(width) is not int or type(height) is not int or width not in (1, 2) or height not in (1, 2):
            raise ValueError("A widget does not fit in the grid.")
        def footprint(cell):
            return {cell + row * COLUMNS + col for row in range(height) for col in range(width)}
        def fits(cell):
            return (type(cell) is int and 0 <= cell < CELLS and cell % COLUMNS + width <= COLUMNS
                    and cell + (height - 1) * COLUMNS < CELLS)
        cell = item["cell"] if "cell" in item else next(
            (pos for pos in range(CELLS) if fits(pos) and not occupied & footprint(pos)), CELLS)
        if not fits(cell):
            raise ValueError("A widget does not fit in the grid.")
        cells = footprint(cell)
        if occupied & cells:
            raise ValueError("Widgets cannot overlap.")
        occupied.update(cells)
        ids.add(entity_id)
        entities.append(Entity(entity_id, label, cell, width, height))
    return tuple(sorted(entities, key=lambda entity: entity.cell))


@dataclass(frozen=True)
class Layout:
    entities: tuple[Entity, ...]
    weather: str = "auto"
    theme: str = "dark"
    demo_entities: tuple[Entity, ...] | None = None
    demo_weather: str = "weather.demo"
    timezone: str = ""
    ha_timezone: str = ""


def checked_zone(value):
    if not isinstance(value, str) or not value or len(value) > 100 or value.startswith(("/", "posix/", "right/")):
        raise ValueError("Choose a valid time zone.")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Choose a valid time zone.") from error


def preferences(weather, theme):
    if (not isinstance(weather, str) or
            (weather not in ("", "auto") and (len(weather) > 255 or not weather.startswith("weather.") or not ENTITY_ID.fullmatch(weather)))):
        raise ValueError("Select a weather entity or hide the weather card.")
    if theme not in ("light", "dark"):
        raise ValueError("Choose a light or dark theme.")


class Selection:
    def __init__(self, initial, path=None):
        self.path = path
        self.lock = RLock()
        if path is not None and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):  # v0.2 saved just the entity list.
                self.write(Layout(parse_entities(data)))
            else:
                stored_weather = data.get("weather")
                weather = "" if stored_weather == "hidden" else (stored_weather or "auto")
                theme = data.get("theme", "dark")
                preferences(weather, theme)
                demo_entities, demo_weather = data.get("demo_entities"), data.get("demo_weather", "weather.demo")
                preferences(demo_weather, theme)
                zone, ha_zone = data.get("timezone", ""), data.get("ha_timezone", "")
                if zone and zone != "auto":
                    checked_zone(zone)
                if ha_zone:
                    checked_zone(ha_zone)
                self.layout = Layout(parse_entities(data["entities"]), weather, theme,
                                     parse_entities(demo_entities) if demo_entities is not None else None,
                                     demo_weather, zone, ha_zone)
        else:
            self.write(Layout(tuple(initial)))

    @property
    def entities(self):
        return self.layout.entities

    @property
    def weather(self):
        return self.layout.weather

    @property
    def theme(self):
        return self.layout.theme

    def write(self, layout):
        if self.path is not None:
            tmp = self.path.with_suffix(".tmp")
            data = asdict(layout)
            if not layout.weather:
                data["weather"] = "hidden"
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        self.layout = layout

    def save(self, entities, weather, demo=False):
        with self.lock:
            preferences(weather, self.theme)
            if demo:
                self.write(replace(self.layout, demo_entities=parse_entities(entities), demo_weather=weather))
            else:
                self.write(replace(self.layout, entities=parse_entities(entities), weather=weather))

    def set_timezone(self, value):
        if value != "auto":
            checked_zone(value)
        with self.lock:
            self.write(replace(self.layout, timezone=value))

    def cache_timezone(self, value):
        checked_zone(value)
        with self.lock:
            if self.layout.ha_timezone != value:
                self.write(replace(self.layout, ha_timezone=value))

    def set_theme(self, theme):
        with self.lock:
            preferences(self.weather, theme)
            self.write(replace(self.layout, theme=theme))

    def add(self, entity_id, label):
        with self.lock:
            self.save([*[asdict(entity) for entity in self.entities], {"id": entity_id, "label": label}], self.weather)

    def rename(self, entity_id, label):
        with self.lock:
            if not any(entity.id == entity_id for entity in self.entities):
                raise ValueError("Entity is not on the panel.")
            self.save([asdict(replace(entity, label=label) if entity.id == entity_id else entity)
                       for entity in self.entities], self.weather)

    def remove(self, entity_id):
        with self.lock:
            self.write(replace(self.layout, entities=tuple(entity for entity in self.entities if entity.id != entity_id)))
