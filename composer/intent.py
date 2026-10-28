"""Intentional composition categories and parameters.

Defines the expressive, musical vocabulary for the Intentional DAW:
- texture: continuous material, spectral density, timbre evolution
- granulation: grain size, spray/jitter, density, dispersion
- impulses: cadences, bursts, transient attacks, drop probability
- fracture: glitches, sudden mutes, cuts, silent gaps
- drone: tonal foundation, spectral instability, harmonics
- space: decay, resonance, stereo diffusion
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntentParam:
    name: str
    label: str
    unit: str
    default: float
    min: float
    max: float
    step: float = 0.05
    doc: str = ""


@dataclass(frozen=True)
class IntentCategory:
    name: str
    label: str
    color: str
    doc: str
    params: tuple[IntentParam, ...]

    def param(self, name: str) -> IntentParam | None:
        return next((p for p in self.params if p.name == name), None)


INTENT_CATEGORIES: dict[str, IntentCategory] = {
    "texture": IntentCategory(
        name="texture",
        label="Texture",
        color="#5f9ea0",
        doc="Materia continua, tappeti sonori ed evoluzione spettrale",
        params=(
            IntentParam("density", "Densità", "", 0.5, 0.0, 1.0, 0.05, "Rarefatta o satura"),
            IntentParam("grain", "Grana / Rugosità", "", 0.4, 0.0, 1.0, 0.05, "Liscia o abrasiva"),
            IntentParam("evolution", "Evoluzione", "", 0.3, 0.0, 1.0, 0.05, "Statica o con moto interno"),
            IntentParam("brightness", "Brillanza", "", 0.5, 0.0, 1.0, 0.05, "Cupo o chiaro/spettrale"),
        ),
    ),
    "granulation": IntentCategory(
        name="granulation",
        label="Granulazione",
        color="#c8794f",
        doc="Frammentazione in grani, dispersione e spray temporale",
        params=(
            IntentParam("grain_size_ms", "Dimensione grano", "ms", 80.0, 10.0, 500.0, 5.0, "Micro-scatti o frammenti"),
            IntentParam("density", "Grani / sec", "g/s", 15.0, 1.0, 60.0, 1.0, "Frequenza di emissione grani"),
            IntentParam("spray", "Spray temporale", "", 0.3, 0.0, 1.0, 0.05, "Regolarità o dispersione casuale"),
            IntentParam("pitch_dispersion", "Dispersione pitch", "st", 0.0, 0.0, 24.0, 1.0, "Variazione semitoni"),
        ),
    ),
    "impulses": IntentCategory(
        name="impulses",
        label="Impulsi",
        color="#b5a24a",
        doc="Eventi percussivi, cadenze ritmiche e raffiche",
        params=(
            IntentParam("rate_hz", "Cadenza base", "Hz", 2.0, 0.2, 20.0, 0.2, "Velocità media degli impulsi"),
            IntentParam("burst", "Raffiche / Irregolarità", "", 0.2, 0.0, 1.0, 0.05, "Cadenza fissa o raffiche sincopate"),
            IntentParam("sharpness", "Attacco transiente", "", 0.7, 0.0, 1.0, 0.05, "Morbido o secco/tagliente"),
            IntentParam("drop_prob", "Probabilità pause", "", 0.1, 0.0, 0.9, 0.05, "Silenzio improvviso o continuità"),
        ),
    ),
    "fracture": IntentCategory(
        name="fracture",
        label="Fratture / Glitch",
        color="#e5534b",
        doc="Tagli improvvisi, silenzi violenti e interruzioni di flusso",
        params=(
            IntentParam("frequency", "Frequenza tagli", "", 0.3, 0.0, 1.0, 0.05, "Rari o continui"),
            IntentParam("gap_ms", "Durata silenzio", "ms", 120.0, 10.0, 1500.0, 10.0, "Durata dell'interruzione"),
            IntentParam("harshness", "Durezza taglio", "", 0.8, 0.0, 1.0, 0.05, "Dissolvenza micro o taglio a zero"),
        ),
    ),
    "drone": IntentCategory(
        name="drone",
        label="Drone / Peso",
        color="#8f73b8",
        doc="Fondamento sonoro continuo, masse armoniche e basse frequenze",
        params=(
            IntentParam("freq_hz", "Frequenza base", "Hz", 55.0, 20.0, 440.0, 1.0, "Tono fondamentale"),
            IntentParam("instability", "Instabilità spettrale", "", 0.2, 0.0, 1.0, 0.05, "Battimenti e micro-variazioni"),
            IntentParam("saturation", "Armonici / Saturazione", "", 0.3, 0.0, 1.0, 0.05, "Puro sinusoidale o ferroso"),
        ),
    ),
    "space": IntentCategory(
        name="space",
        label="Spazio / Coda",
        color="#5f7fb8",
        doc="Diffusione stereo, risonanze ambientali e decadimento",
        params=(
            IntentParam("decay_s", "Decadimento", "s", 3.5, 0.2, 20.0, 0.5, "Tempo di riverbero/coda"),
            IntentParam("damping", "Smorzamento", "", 0.5, 0.0, 1.0, 0.05, "Scuro o brillante"),
            IntentParam("diffusion", "Diffusione stereo", "", 0.7, 0.0, 1.0, 0.05, "Focalizzato o immersivo"),
        ),
    ),
}
