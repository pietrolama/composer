"""Module catalog: the only building blocks the compiler may use.

Each module is described in data (ports, parameters with units and limits) and
realised by a tested abstraction in pd_modules/. Every abstraction follows one
convention: inlet 0 is control; an audio port is a stereo pair of signal
inlets/outlets, numbered as listed in `ports`.
"""

from dataclasses import dataclass, field
from pathlib import Path

PD_MODULES = Path(__file__).parent / "pd_modules"
CATALOG_VERSION = 2


@dataclass(frozen=True)
class Param:
    name: str
    unit: str
    default: object
    min: float | None = None
    max: float | None = None
    kind: str = "float"  # float | bool | asset | asset_list


@dataclass(frozen=True)
class Port:
    name: str
    direction: str  # in | out
    type: str       # audio | control
    pd: tuple       # Pd inlet/outlet indices (L, R) for audio, (i,) for control


@dataclass(frozen=True)
class Module:
    name: str
    abstraction: str
    params: tuple   # in creation-argument order
    ports: tuple
    source: bool = False  # receives start/stop from the timeline
    doc: str = ""
    category: str = "effect"  # source (plays an instrument) | effect (palette) | mix (always available)

    def port(self, name):
        return next((p for p in self.ports if p.name == name), None)

    def param(self, name):
        return next((p for p in self.params if p.name == name), None)

    def pd_file(self):
        return PD_MODULES / f"{self.abstraction}.pd"


CONTROL = Port("control", "in", "control", (0,))

MODULES = {m.name: m for m in (
    # -- Nuovi Moduli Intenzionali (DAW) --------------------------------------
    Module(
        "texture", "composer.texture",
        params=(Param("density", "", 0.5, 0.0, 1.0),
                Param("grain", "", 0.4, 0.0, 1.0),
                Param("evolution", "", 0.3, 0.0, 1.0),
                Param("brightness", "", 0.5, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        source=True,
        doc="Generatore di texture continua, tappeti ed evoluzione timbrica.",
        category="intent"),
    Module(
        "granulation", "composer.granulation",
        params=(Param("grain_size_ms", "ms", 80.0, 10.0, 500.0),
                Param("density", "g/s", 15.0, 1.0, 60.0),
                Param("spray", "", 0.3, 0.0, 1.0),
                Param("pitch_dispersion", "st", 0.0, 0.0, 24.0)),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        source=True,
        doc="Granulatore / dispersione e spray di particelle sonore.",
        category="intent"),
    Module(
        "impulses", "composer.impulses",
        params=(Param("rate_hz", "Hz", 2.0, 0.2, 20.0),
                Param("burst", "", 0.2, 0.0, 1.0),
                Param("sharpness", "", 0.7, 0.0, 1.0),
                Param("drop_prob", "", 0.1, 0.0, 0.9)),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        source=True,
        doc="Generatore di impulsi, raffiche ritmiche e transitori percussivi.",
        category="intent"),
    Module(
        "drone", "composer.drone",
        params=(Param("freq_hz", "Hz", 55.0, 20.0, 440.0),
                Param("instability", "", 0.2, 0.0, 1.0),
                Param("saturation", "", 0.3, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        source=True,
        doc="Fondamento sonoro continuo, masse armoniche e basse frequenze.",
        category="intent"),
    Module(
        "fracture", "composer.fracture",
        params=(Param("frequency", "", 0.3, 0.0, 1.0),
                Param("gap_ms", "ms", 120.0, 10.0, 1500.0),
                Param("harshness", "", 0.8, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1))),
        doc="Processore di glitch, fratture, tagli netti e silenzi improvvisi.",
        category="intent"),
    Module(
        "space", "composer.space",
        params=(Param("decay_s", "s", 3.5, 0.2, 20.0),
                Param("damping", "", 0.5, 0.0, 1.0),
                Param("diffusion", "", 0.7, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1))),
        doc="Diffusione stereo, risonanze ambientali e decadimento.",
        category="intent"),

    # -- Moduli Campionatori & Utilities --------------------------------------
    Module(
        "sample_player", "composer.sample_player",
        params=(Param("asset", "", None, kind="asset"),
                Param("gain", "lin", 1.0, 0.0, 4.0),
                Param("playback_rate", "ratio", 1.0, 0.01, 16.0),
                Param("loop", "", True, kind="bool")),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        source=True,
        doc="Legge un campione (mono o stereo); loop fino a stop.",
        category="source"),
    Module(
        "lowpass", "composer.lowpass",
        params=(Param("cutoff_hz", "Hz", 1800.0, 10.0, 20000.0),),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1)))),
    Module(
        "fragment", "composer.fragment",
        params=(Param("slice_ms", "ms", 60.0, 5.0, 1000.0),
                Param("mix", "lin", 1.0, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1))),
        doc="Stutter: a ogni burst ripete l'ultimo frammento d'ingresso (pilotato dalle regole)."),
    Module(
        "bank", "composer.bank",
        params=(Param("samples", "", (), kind="asset_list"),),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        doc="Fino a 16 campioni one-shot: 'play indice velocità'.",
        category="source"),
    Module(
        "scrub", "composer.scrub",
        params=(Param("asset", "", None, kind="asset"),
                Param("amp", "lin", 0.0, 0.0, 4.0)),
        ports=(CONTROL, Port("audio_out", "out", "audio", (0, 1))),
        doc="Testina a nastro su un campione: 'pos campione ms' (velocità = pendenza, indietro se negativa), 'amp v ms'.",
        category="source"),
    Module(
        "gain", "composer.gain",
        params=(Param("gain", "lin", 1.0, 0.0, 4.0),),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1))),
        doc="'gain v' con rampa di 20 ms; 'hard v' moltiplicatore istantaneo (0 = taglio netto).",
        category="mix"),
    Module(
        "clip", "composer.clip",
        params=(Param("low", "lin", -0.99, -1.0, 0.0), Param("high", "lin", 0.99, 0.0, 1.0)),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2)),
               Port("audio_out", "out", "audio", (0, 1))),
        category="mix"),
    Module(
        "output", "composer.out",
        params=(),
        ports=(CONTROL, Port("audio_in", "in", "audio", (1, 2))),
        doc="Bus principale: tutte le uscite si sommano.",
        category="mix"),
)}


def by_category(category):
    return [m for m in MODULES.values() if m.category == category]


def check_param(module, name, value):
    """Return an error string, or None if the value is acceptable."""
    spec = module.param(name)
    if spec is None:
        return f"parametro sconosciuto '{name}' per {module.name}"
    if spec.kind == "bool":
        return None if isinstance(value, bool) or value in (0, 1) else f"{name} deve essere booleano"
    if spec.kind == "asset":
        return None if isinstance(value, str) else f"{name} deve essere l'id di un asset"
    if spec.kind == "asset_list":
        if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
            return f"{name} deve essere una lista di id di asset"
        return None if len(value) <= 16 else f"{name}: al massimo 16 campioni"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"{name} deve essere un numero ({spec.unit})"
    if spec.min is not None and value < spec.min or spec.max is not None and value > spec.max:
        return f"{name}={value} fuori dai limiti [{spec.min}, {spec.max}] {spec.unit}"
    return None
