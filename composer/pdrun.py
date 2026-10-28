"""Run generated patches in a real Pd: load check and offline render."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from .pdgraph import Patch

PROBLEM = re.compile(r"couldn't create|error|can't open|bad arguments|no such|"
                     r"not found|stack overflow|failed", re.I)


def pd_binary():
    exe = shutil.which("pd")
    if not exe:
        raise RuntimeError("Pure Data (pd) non trovato nel PATH")
    return exe


def pd_version():
    out = subprocess.run([pd_binary(), "-version"], capture_output=True, text=True, timeout=10)
    m = re.search(r"Pd-(\d+\.\d+(?:\.\d+)?)", out.stdout + out.stderr)
    return m.group(1) if m else "?"


def _problems(text):
    return [line.strip() for line in text.splitlines() if PROBLEM.search(line)]


def check(out_dir, timeout=30):
    """Open main.pd headless, quit right after loading, collect Pd's complaints."""
    out = Path(out_dir).resolve()
    main = out / json.loads((out / "manifest.json").read_text())["entry"]
    proc = subprocess.run(
        [pd_binary(), "-nogui", "-nosound", "-nomidi", "-stderr", "-noprefs",
         "-open", str(main), "-send", "pd quit"],
        capture_output=True, text=True, timeout=timeout, cwd=main.parent)
    log = proc.stdout + proc.stderr
    return {"ok": proc.returncode == 0 and not _problems(log), "pd": pd_version(),
            "problems": _problems(log), "log": log}


def render(out_dir, wav_path, seconds=None, tail=1.0, timeout=600):
    """Render the whole piece to a 24-bit WAV, faster than real time (-batch)."""
    out = Path(out_dir).resolve()
    manifest = json.loads((out / "manifest.json").read_text())
    seconds = seconds or manifest["project"]["duration_seconds"]
    wav = Path(wav_path).resolve()
    wav.parent.mkdir(parents=True, exist_ok=True)

    from .compiler import START_DELAY_MS
    sr = 48000
    frames = int((seconds + tail) * sr)
    # Synchronous capture: writesf~ stalls under -batch, tabwrite~ does not.
    w = Patch()
    w.obj("main", 20, 20, "main")
    w.obj("tabL", 20, 50, "table", "composer-rec-L", frames)
    w.obj("tabR", 200, 50, "table", "composer-rec-R", frames)
    w.obj("busL", 20, 80, "r~", "composer-bus-L")
    w.obj("busR", 200, 80, "r~", "composer-bus-R")
    w.obj("wL", 20, 140, "tabwrite~", "composer-rec-L")
    w.obj("wR", 200, 140, "tabwrite~", "composer-rec-R")
    w.obj("lb", 380, 20, "loadbang")
    w.obj("start", 380, 50, "del", START_DELAY_MS)
    w.obj("end", 380, 80, "del", round((seconds + tail) * 1000) + 50)
    w.msg("write", 380, 110, "write", "-wave", "-bytes", 3, "-rate", sr, str(wav),
          "composer-rec-L", "composer-rec-R")
    w.obj("sf", 380, 140, "soundfiler")
    w.msg("quit", 380, 170, ";", "pd", "quit")
    w.connect("busL", 0, "wL", 0)
    w.connect("busR", 0, "wR", 0)
    w.connect("lb", 0, "start", 0)
    w.connect("start", 0, "wL", 0)
    w.connect("start", 0, "wR", 0)
    w.connect("start", 0, "end", 0)
    w.connect("end", 0, "write", 0)
    w.connect("write", 0, "sf", 0)
    w.connect("sf", 0, "quit", 0)
    wrapper = out / Path(manifest["entry"]).parent / "_render.pd"
    wrapper.write_text(w.serialize())
    try:
        proc = subprocess.run(
            [pd_binary(), "-batch", "-nogui", "-nosound", "-nomidi", "-stderr", "-noprefs",
             "-r", str(sr), str(wrapper)],
            capture_output=True, text=True, timeout=timeout, cwd=wrapper.parent)
    finally:
        wrapper.unlink(missing_ok=True)
    log = proc.stdout + proc.stderr
    return {"ok": proc.returncode == 0 and wav.exists() and not _problems(log),
            "wav": str(wav), "problems": _problems(log), "log": log}
