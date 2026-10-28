"""Descriptors for any WAV, in the same units glitchLAB uses (so the brief reads uniformly)."""

from . import rules

_CACHE = {}


def describe(path):
    import numpy as np
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    x, sr = rules.read_mono(path)
    dur = len(x) / sr
    spec = np.abs(np.fft.rfft(x[: sr * 30]))
    freqs = np.fft.rfftfreq(min(len(x), sr * 30), 1 / sr)
    hits, _ = rules.onsets(path)
    out = {"duration": round(dur, 3),
           "centroid": round(float((spec * freqs).sum() / (spec.sum() + 1e-12)), 1),
           "transients": round(len(hits) / dur, 2) if dur else 0,
           "rms": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)), 1)}
    _CACHE[key] = out
    return out
