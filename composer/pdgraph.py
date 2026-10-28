"""Intermediate Pd graph and .pd serializer.

Objects are added by key and connected by key; indices are assigned only when
the patch is serialized, so inserting or removing objects never breaks a cable.
"""

import re
from dataclasses import dataclass, field


def atom(a):
    """Escape one atom for a .pd file."""
    if a in (",", ";"):
        return "\\" + a
    if isinstance(a, bool):
        return "1" if a else "0"
    if isinstance(a, float):
        return f"{a:.6g}"
    s = str(a)
    if not s or re.search(r"\s", s):
        raise ValueError(f"atomo Pd non valido: {s!r}")
    return re.sub(r"([$,;])", r"\\\1", s)


@dataclass
class Box:
    key: str
    kind: str  # obj | msg | text
    atoms: list
    x: int
    y: int


@dataclass
class Patch:
    canvas: tuple = (40, 40, 1200, 800, 10)
    boxes: list = field(default_factory=list)
    cables: list = field(default_factory=list)
    _keys: dict = field(default_factory=dict)

    def add(self, key, kind, atoms, x, y):
        if key in self._keys:
            raise ValueError(f"chiave duplicata nel grafo: {key}")
        self._keys[key] = len(self.boxes)
        self.boxes.append(Box(key, kind, list(atoms), x, y))
        return key

    def obj(self, key, x, y, *atoms):
        return self.add(key, "obj", atoms, x, y)

    def msg(self, key, x, y, *atoms):
        return self.add(key, "msg", atoms, x, y)

    def text(self, key, x, y, words):
        return self.add(key, "text", [w.replace(",", "").replace(";", "") for w in words.split()], x, y)

    def connect(self, src, outlet, dst, inlet):
        for k in (src, dst):
            if k not in self._keys:
                raise KeyError(f"oggetto inesistente nel grafo: {k}")
        self.cables.append((src, outlet, dst, inlet))

    def index(self, key):
        return self._keys[key]

    def serialize(self):
        lines = ["#N canvas %d %d %d %d %d;" % self.canvas]
        for b in self.boxes:
            body = " ".join(atom(a) for a in b.atoms)
            lines.append(f"#X {b.kind} {b.x} {b.y}" + (f" {body};" if body else ";"))
        for s, o, d, i in self.cables:
            lines.append(f"#X connect {self._keys[s]} {o} {self._keys[d]} {i};")
        return "\n".join(lines) + "\n"
