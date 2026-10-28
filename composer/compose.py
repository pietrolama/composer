"""The hand-off between the composer (brief) and the AI (composition).

  brief_markdown(project)   what the AI reads: form, intentions, instruments, palette, feedback
  run(project, script)      execute composition.py's compose(c), keep locked parts, archive a version
  set_status(...)           the composer's verdict on a version, read back by the next brief
"""

import hashlib
import json
import runpy
import time
from pathlib import Path

from . import analysis, catalog
from .gen import Composition, CompositionError
from .validate import validate

COMPOSITION_FIELDS = ("parts", "nodes", "connections", "events", "rules")


def _fmt(x):
    return f"{x:g}" if isinstance(x, float) else str(x)


def brief_markdown(project):
    b, p = project.brief, project
    lines = [f"# Brief — {p.title}", "",
             f"- progetto: `{p.path}`", f"- durata {p.duration_seconds:g} s · tempo {p.tempo:g} bpm · seed {p.seed}", ""]
    if b.notes.strip():
        lines += ["## Note del compositore", "", b.notes.strip(), ""]
    lines += ["## Struttura", "", "| sezione | id | tempo | energia | densità | intenzione |", "|---|---|---|---|---|---|"]
    for s in p.sections:
        lines.append(f"| {s.name} | `{s.id}` | {s.start:g}–{s.end:g} s | {s.energy:.2f} | {s.density:.2f} | "
                     f"{s.intent.strip() or '—'} |")
    lines += ["", "## Strumenti", ""]
    assets = {a.id: a for a in p.assets}
    for ins in b.instruments:
        src = ins.source
        made = (f"glitchLAB {src.get('character')} / {src.get('length')} · densità {src.get('density')} · "
                f"energia {src.get('energy')}" if src.get("type") == "glitchlab" else src.get("type", "file"))
        lines += [f"### {ins.name} (`{ins.id}`)", "", ins.description.strip() or "_nessuna descrizione_", "",
                  f"origine: {made}", "", "| asset | durata | centroide | transienti/s | rms |", "|---|---|---|---|---|"]
        for aid in ins.assets:
            d = assets[aid].provenance.get("descriptors") if aid in assets else {}
            if not d and aid in assets:
                try:
                    d = analysis.describe(p.asset_path(assets[aid]))
                except (OSError, ValueError) as exc:
                    d = {"duration": f"? ({exc})"}
            lines.append(f"| `{aid}` | {_fmt(d.get('duration', '?'))} s | {_fmt(d.get('centroid', '?'))} Hz | "
                         f"{_fmt(d.get('transients', '?'))} | {_fmt(d.get('rms', '?'))} dB |")
        lines.append("")
    lines += ["## Tavolozza", "", "Effetti ammessi (oltre a sorgenti e mix, sempre disponibili):", ""]
    for name in b.palette:
        m = catalog.MODULES[name]
        params = ", ".join(f"{q.name} {q.min}–{q.max} {q.unit}".strip() for q in m.params)
        lines.append(f"- **{name}** — {m.doc} ({params})")
    lines += ["", "Sorgenti: " + ", ".join(f"**{m.name}** ({m.doc})" for m in catalog.by_category("source")),
              "", "Mix: " + ", ".join(m.name for m in catalog.by_category("mix")), ""]
    locked = [x for x in p.parts if x.locked]
    meta = p.composition_meta
    if meta.get("version"):
        lines += ["## Versione corrente", "", f"v{meta['version']} · {meta.get('status', 'proposta')}"]
        if meta.get("feedback"):
            lines += ["", f"> {meta['feedback']}"]
        lines.append("")
    if locked:
        lines += ["## Parti bloccate (non toccarle)", ""] + [f"- `{x.id}` {x.name}" for x in locked] + [""]
    lines += ["## Come comporre", "",
              "Scrivi `composition.py` accanto al progetto con `def compose(c):` (vedi composer/gen.py), poi",
              "`python -m composer compose <progetto>`: valida, archivia la versione e compila.", ""]
    return "\n".join(lines)


def _locked_snapshot(project):
    locked = {x.id for x in project.parts if x.locked}
    nodes = [n for n in project.nodes if n.part_id in locked]
    ids = {n.id for n in nodes} | locked
    inside = lambda ep: ep.split(".")[0] in ids  # noqa: E731
    return {
        "parts": [x for x in project.parts if x.id in locked],
        "nodes": nodes,
        "connections": [c for c in project.connections if inside(c.source) and inside(c.target)],
        "events": [e for e in project.events if e.target in ids],
        "ids": ids,
    }


def run(project, script=None):
    """Replace the composition with the one built by `script` (default composition.py)."""
    script = Path(script or project.path.parent / "composition.py")
    keep = _locked_snapshot(project)
    for f in COMPOSITION_FIELDS:
        setattr(project, f, [])
    project.presentation["nodes"] = {}
    c = Composition(project)
    namespace = runpy.run_path(str(script))
    if "compose" not in namespace:
        raise CompositionError(f"{script} non definisce compose(c)")
    namespace["compose"](c)

    clash = keep["ids"] & ({x.id for x in project.parts} | {n.id for n in project.nodes})
    if clash:
        raise CompositionError(f"lo script ha toccato parti bloccate: {', '.join(sorted(clash))}")
    project.parts += keep["parts"]
    project.nodes += keep["nodes"]
    project.connections += keep["connections"]
    project.events += keep["events"]

    meta = project.composition_meta
    version = int(meta.get("version", 0)) + 1
    text = script.read_text()
    project.composition_meta = {
        "author": "claude-code", "version": version, "status": "proposta",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "seed": project.seed,
        "script": script.name, "script_sha": hashlib.sha256(text.encode()).hexdigest()[:16],
        "previous_feedback": meta.get("feedback", ""),
    }
    archive = project.path.parent / "compositions"
    archive.mkdir(exist_ok=True)
    (archive / f"v{version:03d}.py").write_text(text)
    snap = {f: project.to_dict()[f] for f in COMPOSITION_FIELDS}
    snap["composition_meta"] = project.composition_meta
    (archive / f"v{version:03d}.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n")
    project.save()
    return version, validate(project)


def set_status(project, status, feedback=""):
    if status not in ("proposta", "accettata", "rifiutata"):
        raise ValueError(f"stato sconosciuto: {status}")
    project.composition_meta["status"] = status
    project.composition_meta["feedback"] = feedback
