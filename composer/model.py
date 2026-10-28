"""Canonical composition model: the project file is the source of truth.

Who writes what:
  brief         the composer (human): instruments, effect palette, sections with
                an intention, notes. Composer prepares it; the AI reads it.
  composition   the AI (Claude Code): parts, nodes, connections, events, rules,
                built only from the brief's instruments and palette.
  presentation  canvas positions (never read by the compiler)

Every element has a persistent id; references between elements are by id only.
"""

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 2


@dataclass
class Section:
    """A section of the form, with the intention the AI has to realise."""
    id: str
    name: str
    start: float
    end: float
    intent: str = ""
    energy: float = 0.5
    density: float = 0.5


@dataclass
class Instrument:
    """A sound source the piece may use: one or more assets plus how they were made."""
    id: str
    name: str
    description: str = ""
    assets: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)  # e.g. {"type": "glitchlab", "character": ...}


@dataclass
class Brief:
    instruments: list[Instrument] = field(default_factory=list)
    palette: list[str] = field(default_factory=list)  # catalog modules the AI may use
    notes: str = ""


@dataclass
class Part:
    id: str
    name: str
    role: str = ""
    source_id: str | None = None  # default asset for the part's sample players
    section_ids: list[str] = field(default_factory=list)
    locked: bool = False


@dataclass
class Asset:
    id: str
    path: str  # relative to the project file, or absolute
    sha256: str = ""
    provenance: dict = field(default_factory=dict)


@dataclass
class Node:
    id: str
    type: str  # module name in the catalog
    part_id: str | None = None  # None: the node lives in main.pd
    params: dict = field(default_factory=dict)


@dataclass
class Connection:
    """audio_connection: a cable between module ports ("node.port")."""
    id: str
    source: str
    target: str
    kind: str = "audio_connection"


@dataclass
class Event:
    """A timed control message to a part or a node, e.g. "gain 0.2"."""
    id: str
    time: float
    target: str
    message: str


@dataclass
class Rule:
    """composition_rule: a behavioural relation, not a cable."""
    id: str
    source: str
    target: str
    when: str
    effect: str
    params: dict = field(default_factory=dict)


@dataclass
class Project:
    id: str
    title: str
    duration_seconds: float
    tempo: float = 120.0
    seed: int = 0
    sections: list[Section] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    presentation: dict = field(default_factory=dict)
    brief: Brief = field(default_factory=Brief)
    composition_meta: dict = field(default_factory=dict)  # author, version, status, feedback
    path: Path | None = field(default=None, repr=False, compare=False)

    # -- lookup ------------------------------------------------------------
    def by_id(self):
        out = {}
        for group in (self.sections, self.parts, self.assets, self.nodes,
                      self.connections, self.events, self.rules, self.brief.instruments):
            for item in group:
                out.setdefault(item.id, item)
        return out

    def instrument(self, instrument_id):
        return next((i for i in self.brief.instruments if i.id == instrument_id), None)

    def section(self, section_id):
        return next((s for s in self.sections if s.id == section_id), None)

    def part_nodes(self, part_id):
        return [n for n in self.nodes if n.part_id == part_id]

    def asset_path(self, asset):
        p = Path(asset.path)
        if not p.is_absolute() and self.path is not None:
            p = self.path.parent / p
        return p.resolve()

    # -- persistence ---------------------------------------------------------
    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "project": {"id": self.id, "title": self.title,
                        "duration_seconds": self.duration_seconds,
                        "tempo": self.tempo, "seed": self.seed},
            "sections": [asdict(s) for s in self.sections],
            "parts": [asdict(p) for p in self.parts],
            "assets": [asdict(a) for a in self.assets],
            "nodes": [asdict(n) for n in self.nodes],
            "connections": [asdict(c) for c in self.connections],
            "events": [asdict(e) for e in self.events],
            "rules": [asdict(r) for r in self.rules],
            "presentation": copy.deepcopy(self.presentation),
            "brief": {"instruments": [asdict(i) for i in self.brief.instruments],
                      "palette": list(self.brief.palette), "notes": self.brief.notes},
            "composition_meta": copy.deepcopy(self.composition_meta),
        }

    def save(self, path=None):
        path = Path(path or self.path)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        self.path = path
        return path


def migrate(data):
    """Bring an older project dict up to SCHEMA_VERSION."""
    version = data.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        raise ValueError(f"progetto con schema {version}, questo Composer legge fino a {SCHEMA_VERSION}")
    if version == 0:  # draft format: positions inside parts
        pres = data.setdefault("presentation", {}).setdefault("parts", {})
        for p in data.get("parts", []):
            if "position" in p:
                pres[p["id"]] = p.pop("position")
        data["schema_version"] = 1
    if data["schema_version"] == 1:  # brief introduced: the palette starts as what the piece uses
        used = sorted({n["type"] for n in data.get("nodes", [])})
        data["brief"] = {"instruments": [], "palette": used, "notes": ""}
        data["composition_meta"] = {"author": "human"}
        data["schema_version"] = 2
    return data


def from_dict(data, path=None):
    data = migrate(copy.deepcopy(data))  # the model never shares state with its source
    meta = data["project"]
    return Project(
        id=meta["id"], title=meta["title"], duration_seconds=meta["duration_seconds"],
        tempo=meta.get("tempo", 120.0), seed=meta.get("seed", 0),
        sections=[Section(**s) for s in data.get("sections", [])],
        parts=[Part(**p) for p in data.get("parts", [])],
        assets=[Asset(**a) for a in data.get("assets", [])],
        nodes=[Node(**n) for n in data.get("nodes", [])],
        connections=[Connection(**c) for c in data.get("connections", [])],
        events=[Event(**e) for e in data.get("events", [])],
        rules=[Rule(**r) for r in data.get("rules", [])],
        presentation=data.get("presentation", {}),
        brief=Brief(instruments=[Instrument(**i) for i in data["brief"].get("instruments", [])],
                    palette=list(data["brief"].get("palette", [])), notes=data["brief"].get("notes", "")),
        composition_meta=data.get("composition_meta", {}),
        path=Path(path).resolve() if path else None,
    )


def load(path):
    return from_dict(json.loads(Path(path).read_text()), path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
