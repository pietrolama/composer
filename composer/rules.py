"""Composition rules -> timed events, computed at compile time from the seed.

A rule says *when* something happens (triggers taken from its source) and
*what* it does to its target. Every rule draws from its own random stream,
random.Random(f"{seed}:{rule.id}"), so the same project and seed always give
the same score, and editing one rule never reshuffles the others.

when
  on_onset   attacks in the source part's samples, following its loops
             (a rise of 12 - 9*sensitivity dB within 5 ms, within 45 dB of the peak)
  every      a pulse every period_ms (± jitter) while the source is active
  random     Poisson triggers at rate_hz while the source is active
effect
  fragment   a burst on the target's fragment modules: repeat a slice of
             slice_ms_min..max for window_ms, with the given probability
"""

import random
import wave
from dataclasses import dataclass

from . import catalog

WHEN = {
    "on_onset": {"sensitivity": (0.0, 1.0, 0.5)},
    "every": {"period_ms": (20.0, 60000.0, 1000.0), "jitter": (0.0, 1.0, 0.0)},
    "random": {"rate_hz": (0.01, 50.0, 1.0)},
}
EFFECT = {
    "fragment": {"window_ms": (30.0, 10000.0, 800.0), "probability": (0.0, 1.0, 0.5),
                 "slice_ms_min": (5.0, 1000.0, 20.0), "slice_ms_max": (5.0, 1000.0, 120.0),
                 "min_gap_ms": (0.0, 60000.0, None)},
}


@dataclass
class Expansion:
    triggers: int
    events: list  # (seconds, node id, [message words])


def params(rule):
    """Rule parameters with defaults filled in (min_gap_ms defaults to window_ms)."""
    spec = {**WHEN.get(rule.when, {}), **EFFECT.get(rule.effect, {})}
    out = {k: rule.params.get(k, d) for k, (_, _, d) in spec.items()}
    if "min_gap_ms" in out and out["min_gap_ms"] is None:
        out["min_gap_ms"] = out["window_ms"]
    return out


def check(project, rule):
    """Return a list of (level, message) for one rule."""
    problems = []
    if rule.when not in WHEN:
        problems.append(("error", f"'when' sconosciuto: {rule.when} (ammessi: {', '.join(WHEN)})"))
    if rule.effect not in EFFECT:
        problems.append(("error", f"'effect' sconosciuto: {rule.effect} (ammessi: {', '.join(EFFECT)})"))
    if problems:
        return problems
    spec = {**WHEN[rule.when], **EFFECT[rule.effect]}
    for k, v in rule.params.items():
        if k not in spec:
            problems.append(("error", f"parametro sconosciuto '{k}' per {rule.when}/{rule.effect}"))
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or not spec[k][0] <= v <= spec[k][1]:
            problems.append(("error", f"{k}={v} fuori dai limiti [{spec[k][0]}, {spec[k][1]}]"))
    p = params(rule)
    if rule.effect == "fragment" and p["slice_ms_min"] > p["slice_ms_max"]:
        problems.append(("error", "slice_ms_min maggiore di slice_ms_max"))
    if not targets(project, rule):
        problems.append(("error", f"il bersaglio {rule.target} non contiene un modulo '{rule.effect}'"))
    if rule.when == "on_onset" and not _players(project, rule.source):
        problems.append(("error", f"la sorgente {rule.source} non ha sample_player da cui ricavare gli attacchi"))
    if rule.when != "on_onset" and _span(project, rule.source) is None:
        problems.append(("error", f"la sorgente {rule.source} deve essere una parte o una sezione"))
    return problems


def targets(project, rule):
    nodes = [n for n in project.nodes if n.type == rule.effect]
    return [n for n in nodes if n.id == rule.target or n.part_id == rule.target]


def _players(project, source):
    return [n for n in project.nodes if n.type == "sample_player" and (n.id == source or n.part_id == source)]


def intervals(project, part_id):
    """Merged active intervals (seconds) of a part; top level = whole piece."""
    if part_id is None:
        return [[0.0, float(project.duration_seconds)]]
    part = next((p for p in project.parts if p.id == part_id), None)
    secs = sorted((s.start, s.end) for s in project.sections if part and s.id in part.section_ids)
    merged = []
    for a, b in secs:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([float(a), float(b)])
    return merged


def _span(project, source):
    section = next((s for s in project.sections if s.id == source), None)
    if section:
        return [[float(section.start), float(section.end)]]
    if any(p.id == source for p in project.parts):
        return intervals(project, source)
    return None


def _inside(t, spans):
    return any(a <= t < b for a, b in spans)


# -- triggers ------------------------------------------------------------------
def read_mono(path):
    """Decode a PCM WAV (16/24/32-bit) to a mono float list via numpy."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        x = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        x = np.where(x >= 1 << 23, x - (1 << 24), x) / float(1 << 23)
    else:
        x = np.frombuffer(raw, {2: "<i2", 4: "<i4"}[width]) / float(1 << (8 * width - 1))
    return x.reshape(-1, ch).mean(axis=1), sr


_ONSETS = {}


def onsets(path, sensitivity=0.5):
    """Attack times (s) in a sample: rises of the 5 ms energy envelope."""
    key = (str(path), round(sensitivity, 3))
    if key in _ONSETS:
        return _ONSETS[key]
    import numpy as np
    x, sr = read_mono(path)
    hop = max(1, int(0.005 * sr))
    frames = len(x) // hop
    if frames < 3:
        return [], len(x) / sr
    env = np.sqrt(np.mean(x[:frames * hop].reshape(frames, hop) ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(env)
    rise = np.diff(db, prepend=db[0])
    thresh = 12.0 - 9.0 * sensitivity  # dB of rise within 5 ms: 12 (deaf) .. 3 (very sensitive)
    out, last = [], -1e9
    for i in np.flatnonzero((rise > thresh) & (db > db.max() - 45)):
        t = i * hop / sr
        if t - last >= 0.04:
            out.append(round(t, 4))
            last = t
    _ONSETS[key] = (out, len(x) / sr)
    return _ONSETS[key]


def _onset_triggers(project, rule, p):
    times = []
    for node in _players(project, rule.source):
        aid = node.params.get("asset") or next((x.source_id for x in project.parts if x.id == node.part_id), None)
        asset = next((a for a in project.assets if a.id == aid), None)
        if asset is None:
            continue
        hits, length = onsets(project.asset_path(asset), p["sensitivity"])
        rate = float(node.params.get("playback_rate", 1.0))
        loop = node.params.get("loop", True)
        period = length / rate
        for a, b in intervals(project, node.part_id):
            k = 0
            while a + k * period < b and (loop or k == 0):
                times += [a + k * period + h / rate for h in hits if a + k * period + h / rate < b]
                k += 1
    return sorted(times)


def _clock_triggers(project, rule, p, rng):
    spans = _span(project, rule.source) or []
    times = []
    for a, b in spans:
        if rule.when == "every":
            period, k = p["period_ms"] / 1000.0, 0
            while a + k * period < b:  # a + k*period: no drift from repeated sums
                hit = a + k * period + period * p["jitter"] * (rng.random() - 0.5)
                if a <= hit < b:
                    times.append(hit)
                k += 1
        else:
            t = a
            while True:
                t += rng.expovariate(p["rate_hz"])
                if t >= b:
                    break
                times.append(t)
    return sorted(times)


def expand(project, rule):
    p = params(rule)
    rng = random.Random(f"{project.seed}:{rule.id}")
    triggers = (_onset_triggers(project, rule, p) if rule.when == "on_onset"
                else _clock_triggers(project, rule, p, rng))
    events = []
    for node in targets(project, rule):
        active = intervals(project, node.part_id)
        last = -1e9
        for t in triggers:
            if not _inside(t, active) or (t - last) * 1000 < p["min_gap_ms"]:
                continue
            if rng.random() >= p["probability"]:
                continue
            end = next(b for a, b in active if a <= t < b)
            window = min(p["window_ms"], (end - t) * 1000)
            if window < 30:
                continue
            slice_ms = rng.uniform(p["slice_ms_min"], p["slice_ms_max"])
            events.append((round(t, 4), node.id, ["burst", round(window, 1), round(slice_ms, 1)]))
            last = t
    return Expansion(len(triggers), events)


def describe():
    """Vocabulary for UIs and docs."""
    return {"when": WHEN, "effect": EFFECT, "modules": [m for m in catalog.MODULES if m in EFFECT]}
