"""Toolkit the AI composes with: a composition script is `compose(c)` over a Composition.

The script decides everything musical; this module only guarantees that what it
builds respects the brief (instruments, palette) and the catalog, and that its
randomness is reproducible: c.rng("name") is seeded by the project seed + name.

    def compose(c):
        tex = c.part("texture", "Texture", sections=["sec-1", "sec-2"])
        pl = c.player(tex, "ins-pad", "sample_player", gain=0.6)
        c.to_bus(c.chain(pl, c.effect(tex, "lowpass", cutoff_hz=900)))
        c.at(12.0, pl, "gain", 0.3)
"""

import random

from . import catalog, edit
from .model import Event, Part


class CompositionError(ValueError):
    pass


class Composition:
    def __init__(self, project):
        self.p = project
        self.brief = project.brief
        self._bus = None
        self._n_events = 0

    # -- reading the brief --------------------------------------------------------
    @property
    def sections(self):
        return list(self.p.sections)

    def section(self, key):
        s = next((s for s in self.p.sections if key in (s.id, s.name)), None)
        if s is None:
            raise CompositionError(f"sezione sconosciuta: {key}")
        return s

    def instrument(self, key):
        i = next((i for i in self.brief.instruments if key in (i.id, i.name)), None)
        if i is None:
            raise CompositionError(f"strumento non nel brief: {key}")
        return i

    def rng(self, name):
        return random.Random(f"{self.p.seed}:{name}")

    # -- graph -------------------------------------------------------------------
    def part(self, key, name, role="", sections=None, instrument=None):
        pid = f"part-{key}"
        secs = [self.section(s).id for s in (sections or [s.id for s in self.p.sections])]
        src = None
        if instrument:
            ins = self.instrument(instrument)
            src = ins.assets[0] if ins.assets else None
        part = Part(pid, name, role, src, secs)
        self.p.parts.append(part)
        return part

    def _node(self, part, module, key, params):
        node = edit.add_node(self.p, module, part.id if part else None, params=params)
        if key:
            want = f"node-{key}"
            if any(n.id == want for n in self.p.nodes):
                raise CompositionError(f"id già usato: {want}")
            self.p.presentation.get("nodes", {}).pop(node.id, None)
            node.id = want
        return node

    def player(self, part, instrument, kind="sample_player", key=None, **params):
        """Make `part` play `instrument` with a source module (sample_player, bank, scrub)."""
        mod = catalog.MODULES.get(kind)
        if mod is None or mod.category != "source":
            raise CompositionError(f"{kind} non è un modulo sorgente")
        ins = self.instrument(instrument)
        if kind == "bank":
            params.setdefault("samples", list(ins.assets[:16]))
        elif "asset" not in params:
            params["asset"] = ins.assets[0]
        return self._node(part, kind, key, params)

    def effect(self, part, module, key=None, **params):
        if module not in self.brief.palette:
            raise CompositionError(f"l'effetto '{module}' non è nella tavolozza del brief")
        return self._node(part, module, key, params)

    def mix(self, part, module, key=None, **params):
        if catalog.MODULES[module].category != "mix":
            raise CompositionError(f"{module} non è un modulo di mix")
        return self._node(part, module, key, params)

    def chain(self, *nodes):
        for a, b in zip(nodes, nodes[1:]):
            edit.connect(self.p, f"{a.id}.audio_out", f"{b.id}.audio_in")
        return nodes[-1]

    def bus(self, gain=None):
        """Master: gain -> clip -> output, created once; a later gain= updates it."""
        if self._bus is None:
            g = self._node(None, "gain", "master", {"gain": 0.8 if gain is None else gain})
            c = self._node(None, "clip", "clip", {})
            o = self._node(None, "output", "out", {})
            self.chain(g, c, o)
            self._bus = g
        elif gain is not None:
            edit.set_param(self.p, self._bus.id, "gain", gain)
        return self._bus

    def to_bus(self, node):
        edit.connect(self.p, f"{node.id}.audio_out", f"{self.bus().id}.audio_in")
        return node

    # -- time --------------------------------------------------------------------
    def at(self, t, target, *message):
        tid = target if isinstance(target, str) else target.id
        if not 0 <= t <= self.p.duration_seconds:
            raise CompositionError(f"evento a {t:.3f}s fuori dalla durata")
        self._n_events += 1
        words = [f"{w:.4g}" if isinstance(w, float) else str(w) for w in message]
        self.p.events.append(Event(f"ev-{self._n_events:05d}", round(t, 4), tid, " ".join(words)))

    def span(self, section):
        s = self.section(section)
        return s.start, s.end

    def step(self):
        """Sixteenth note at the project tempo (seconds)."""
        return 60.0 / self.p.tempo / 4

    def grid(self, section, step=None):
        a, b = self.span(section)
        step = step or self.step()
        n = int((b - a) / step + 1e-9)
        return [a + k * step for k in range(n)]


def euclid(k, n=16, rot=0):
    """k onsets spread as evenly as possible over n steps, rotated."""
    return [((i + rot) * k) % n < k for i in range(n)]


def curve(u, a, b, shape="lin"):
    """Value at position u (0..1) between a and b: lin, exp (slow start) or log (fast start)."""
    u = min(max(u, 0.0), 1.0)
    if shape == "exp":
        u = u ** 2
    elif shape == "log":
        u = 1 - (1 - u) ** 2
    return a + (b - a) * u
