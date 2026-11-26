import json
import re
from dataclasses import asdict, dataclass
from threading import RLock

MAX_ENTITIES = 24


@dataclass(frozen=True)
class Entity:
    id: str
    label: str


def parse_entities(raw):
    if not isinstance(raw, list) or len(raw) > MAX_ENTITIES:
        raise ValueError(f"entities must be a list with at most {MAX_ENTITIES} entries")
    entities = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each entity must have an id and optional label")
        entity_id = item.get("id")
        if not isinstance(entity_id, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", entity_id):
            raise ValueError("invalid entity id; use domain.object_id")
        label = item.get("label") or entity_id
        if not isinstance(label, str) or len(label) > 120:
            raise ValueError("entity label must be a string of at most 120 characters")
        if any(entity.id == entity_id for entity in entities):
            raise ValueError("entity already added")
        entities.append(Entity(entity_id, label))
    return tuple(entities)


class Selection:
    def __init__(self, initial, path=None):
        self.path = path
        self.lock = RLock()
        if path is not None and path.is_file():
            self.entities = parse_entities(json.loads(path.read_text(encoding="utf-8")))
        else:
            self.write(initial)

    def write(self, entities):
        if self.path is not None:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(entity) for entity in entities], ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        self.entities = entities

    def add(self, entity_id, label):
        with self.lock:
            entries = [asdict(entity) for entity in self.entities]
            self.write(parse_entities([*entries, {"id": entity_id, "label": label}]))

    def rename(self, entity_id, label):
        with self.lock:
            if not any(entity.id == entity_id for entity in self.entities):
                raise ValueError("entity is not on the panel")
            self.write(parse_entities([
                {"id": entity.id, "label": label if entity.id == entity_id else entity.label}
                for entity in self.entities
            ]))

    def remove(self, entity_id):
        with self.lock:
            self.write(tuple(entity for entity in self.entities if entity.id != entity_id))
