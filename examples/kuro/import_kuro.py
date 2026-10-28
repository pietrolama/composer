"""Reverse-engineer Kuro (pureDataMCP/kuro) into a Composer project.

Level 1, "flattened": the score Kuro's generator wrote (kuro_score.txt) becomes
explicit Composer events, its sample banks and tape head become catalog
modules. The sound is reproduced; the generator's intent (Euclidean patterns,
the four-glitch motif, the accelerando) is not: it survives only as events.

python3 examples/kuro/import_kuro.py [~/projects/pureDataMCP/kuro]
"""

import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from composer import edit  # noqa: E402
from composer.model import Asset, Event, Node, Part, Project, Section, sha256_file  # noqa: E402

HERE = Path(__file__).resolve().parent
KURO = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "projects/pureDataMCP/kuro").resolve()
SAMPLES = KURO / "kuro_samples_fx"
BANKS = {"sub": 8, "glitch": 14, "metal": 12, "texture": 4}
MOVEMENTS = ["Scan", "Accretion", "Rupture", "Residue", "Rescan"]
VISUAL_ONLY = {"imp", "bar", "frz"}  # cues for the Godot visualizer: no sound of their own


def read_score(path):
    t, out = 0.0, []
    for line in path.read_text().splitlines():
        line = line.strip().rstrip(";")
        if not line:
            continue
        delta, receiver, *args = line.split()
        t += float(delta) / 1000.0
        out.append((round(t, 4), receiver, args))
    return out


def asset(aid, path, **prov):
    return Asset(aid, os.path.relpath(path, HERE), sha256_file(path), {"source": "kuro", **prov})


def main():
    score = read_score(KURO / "kuro_score.txt")
    end = next(t for t, r, _ in score if r == "end")
    starts = [t for t, r, _ in score if r == "sec"]
    p = Project(id="kuro", title="Kuro (reverse engineering)", duration_seconds=round(end + 0.5, 3), seed=7)
    for k, (a, name) in enumerate(zip(starts, MOVEMENTS)):
        b = starts[k + 1] if k + 1 < len(starts) else end
        p.sections.append(Section(f"sec-{name.lower()}", name, a, b))
    every = [s.id for s in p.sections]

    p.assets.append(asset("asset-tape", SAMPLES / "subassemblies_full.wav", role="tape"))
    p.parts.append(Part("part-tape", "Nastro", "testina", "asset-tape", every))
    p.nodes.append(Node("node-tape", "scrub", "part-tape", {"amp": 0.0}))
    for bank, n in BANKS.items():
        ids = []
        for k in range(n):
            aid = f"asset-{bank}-{k}"
            p.assets.append(asset(aid, SAMPLES / bank / f"{bank}_{k}.wav", bank=bank, index=k))
            ids.append(aid)
        p.parts.append(Part(f"part-{bank}", bank.capitalize(), "banco one-shot", None, every))
        p.nodes.append(Node(f"node-{bank}", "bank", f"part-{bank}", {"samples": ids}))
    p.nodes += [Node("node-master", "gain", None, {"gain": 0.5}),
                Node("node-clip", "clip", None, {"low": -0.99, "high": 0.99}),
                Node("node-out", "output", None, {})]
    for src in ["node-tape"] + [f"node-{b}" for b in BANKS]:
        edit.connect(p, f"{src}.audio_out", "node-master.audio_in")
    edit.connect(p, "node-master.audio_out", "node-clip.audio_in")
    edit.connect(p, "node-clip.audio_out", "node-out.audio_in")

    translate = {
        "scrub_pos": ("node-tape", lambda a: ["pos", *a]),
        "scrub_amp": ("node-tape", lambda a: ["amp", *a]),
        "mute": ("node-master", lambda a: ["hard", *a]),
        **{f"play_{b}": (f"node-{b}", lambda a: ["play", *a]) for b in BANKS},
    }
    dropped = collections.Counter()
    for k, (t, receiver, args) in enumerate(score):
        if receiver in translate:
            target, msg = translate[receiver]
            p.events.append(Event(f"ev-{k:04d}", t, target, " ".join(msg(args))))
        elif receiver not in ("sec", "end"):
            dropped[receiver] += 1
    out = p.save(HERE / "composer.project.json")
    kinds = collections.Counter(e.target for e in p.events)
    print(f"→ {out}")
    print(f"  {len(p.sections)} sezioni, {len(p.parts)} parti, {len(p.assets)} campioni, {len(p.events)} eventi")
    print("  eventi per nodo: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    print("  solo visivi, non importati: " + ", ".join(f"{k} {v}" for k, v in dropped.items()))


if __name__ == "__main__":
    main()
