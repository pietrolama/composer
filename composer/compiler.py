"""Deterministic compiler: project model -> self-contained Pd folder.

  <out>/composer.project.json   snapshot of the model, asset paths made local
  <out>/assets/                 referenced samples
  <out>/patches/main.pd         transport, parts, top-level nodes, main bus
  <out>/patches/part_<id>.pd    one abstraction per part
  <out>/patches/score.txt       qlist timeline (sections + events)
  <out>/patches/composer.*.pd   catalog modules used
  <out>/manifest.json           versions, modules, id map, file hashes
  <out>/reports/validation.json

The canvas layer (presentation) is never read: moving a node does not change a patch.
"""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import __version__, catalog, rules
from .model import sha256_file
from .pdgraph import Patch, atom
from .validate import report, split_endpoint, validate

PD_VERSION = "0.55"
START_DELAY_MS = 300  # lets every soundfiler finish loading before the timeline starts


class CompileError(Exception):
    def __init__(self, issues):
        self.issues = issues
        lines = [f"  {i.element}: {i.message}" for i in issues if i.level == "error"]
        super().__init__("compilazione interrotta:\n" + "\n".join(lines))


def slug(text):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def recv(element_id):
    """Receive name that addresses a part or a node at runtime."""
    return f"c-{slug(element_id)}"


@dataclass
class Endpoint:
    box: str      # key of the Pd box in the patch that holds the cable
    pd: tuple     # (L, R) inlet/outlet indices on that box


def _write(path, text):
    """Write only when the content changes; return True if written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def _intervals(project, part):
    secs = sorted((s.start, s.end) for s in project.sections if s.id in part.section_ids)
    merged = []
    for a, b in secs:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


class Compiler:
    def __init__(self, project, out_dir):
        self.p = project
        self.out = Path(out_dir).resolve()
        self.patches = self.out / "patches"
        self.nodes = {n.id: n for n in project.nodes}
        self.parts = {p.id: p for p in project.parts}
        self.assets = {a.id: a for a in project.assets}
        self.id_map = {}
        self.asset_files = {}

    # -- helpers -----------------------------------------------------------
    def module(self, node):
        return catalog.MODULES[node.type]

    def port(self, endpoint):
        nid, pname = split_endpoint(endpoint)
        node = self.nodes[nid]
        return node, self.module(node).port(pname)

    def node_args(self, node):
        mod = self.module(node)
        args = []
        for spec in mod.params:
            value = node.params.get(spec.name, spec.default)
            if spec.kind == "asset":
                aid = value or self.parts[node.part_id].source_id
                args.append(f"../assets/{self.asset_files[aid]}")
            elif spec.kind == "asset_list":
                paths = [f"../assets/{self.asset_files[a]}" if a != "-" else "-" for a in value]
                args += (paths + ["-"] * 16)[:16]
            elif spec.kind == "bool":
                args.append(1 if value else 0)
            else:
                args.append(float(value))
        return [mod.abstraction] + args

    def place_node(self, patch, node, x, y, file):
        patch.obj(f"r:{node.id}", x, y, "r", recv(node.id))
        patch.obj(node.id, x, y + 30, *self.node_args(node))
        patch.connect(f"r:{node.id}", 0, node.id, 0)
        self.id_map[node.id] = {"file": file, "object_index": patch.index(node.id)}

    # -- assets --------------------------------------------------------------
    def copy_assets(self):
        used = set()
        for n in self.p.nodes:
            for spec in self.module(n).params:
                if spec.kind == "asset":
                    used.add(n.params.get(spec.name) or self.parts[n.part_id].source_id)
                elif spec.kind == "asset_list":
                    used.update(a for a in n.params.get(spec.name, ()) if a != "-")
        dest = self.out / "assets"
        dest.mkdir(parents=True, exist_ok=True)
        changed = []
        for aid in sorted(used):
            src = self.p.asset_path(self.assets[aid])
            name = slug(aid) + src.suffix.lower()
            self.asset_files[aid] = name
            target = dest / name
            if not target.exists() or sha256_file(target) != sha256_file(src):
                shutil.copy2(src, target)
                changed.append(f"assets/{name}")
        for stale in dest.iterdir():
            if stale.name not in self.asset_files.values():
                stale.unlink()
        return changed

    # -- parts -------------------------------------------------------------
    def compile_part(self, part):
        file = f"part_{slug(part.id)}.pd"
        members = {n.id for n in self.p.part_nodes(part.id)}
        patch = Patch(canvas=(60, 60, 1000, 600, 10))
        patch.text("title", 20, 560, f"Composer part {part.id} - {part.name} - generated, do not edit")
        patch.obj("rx", 20, 20, "r", recv(part.id))

        ins, outs = [], []  # boundary ports, in order of first appearance
        for c in self.p.connections:
            s, t = split_endpoint(c.source)[0], split_endpoint(c.target)[0]
            if s in members and t not in members and c.source not in outs:
                outs.append(c.source)
            if t in members and s not in members and c.target not in ins:
                ins.append(c.target)
        # Pd numbers inlets/outlets by x position: lay them out left to right.
        for k, ep in enumerate(ins):
            patch.obj(f"in:{ep}:L", 300 + 140 * k, 20, "inlet~")
            patch.obj(f"in:{ep}:R", 360 + 140 * k, 20, "inlet~")
        for k, ep in enumerate(outs):
            patch.obj(f"out:{ep}:L", 20 + 140 * k, 500, "outlet~")
            patch.obj(f"out:{ep}:R", 80 + 140 * k, 500, "outlet~")

        for k, nid in enumerate(n.id for n in self.p.part_nodes(part.id)):
            self.place_node(patch, self.nodes[nid], 20 + 240 * k, 120 + 60 * (k % 2), file)
            patch.connect("rx", 0, nid, 0)

        for c in self.p.connections:
            s, t = split_endpoint(c.source)[0], split_endpoint(c.target)[0]
            if s in members and t in members:
                (_, sp), (_, tp) = self.port(c.source), self.port(c.target)
                for ch in (0, 1):
                    patch.connect(s, sp.pd[ch], t, tp.pd[ch])
        for ep in ins:
            node, port = self.port(ep)
            for ch, side in enumerate("LR"):
                patch.connect(f"in:{ep}:{side}", 0, node.id, port.pd[ch])
        for ep in outs:
            node, port = self.port(ep)
            for ch, side in enumerate("LR"):
                patch.connect(node.id, port.pd[ch], f"out:{ep}:{side}", 0)

        part_in = {ep: (2 * k, 2 * k + 1) for k, ep in enumerate(ins)}
        part_out = {ep: (2 * k, 2 * k + 1) for k, ep in enumerate(outs)}
        return file, patch.serialize(), part_in, part_out

    # -- timeline ------------------------------------------------------------
    def score(self):
        timed = []  # (seconds, order, receiver, message atoms)
        for order, part in enumerate(self.p.parts):
            for a, b in _intervals(self.p, part):
                timed.append((a, 0, recv(part.id), ["start"]))
                timed.append((b, 1, recv(part.id), ["stop"]))
        for e in self.p.events:
            timed.append((e.time, 2, recv(e.target), e.message.split()))
        self.rule_report = {}
        for r in self.p.rules:
            exp = rules.expand(self.p, r)
            self.rule_report[r.id] = {"when": r.when, "effect": r.effect, "triggers": exp.triggers,
                                      "events": [{"time": t, "target": n, "message": " ".join(map(str, m))}
                                                 for t, n, m in exp.events]}
            for t, node_id, words in exp.events:
                timed.append((t, 3, recv(node_id), [str(w) for w in words]))
        timed.append((self.p.duration_seconds, 9, "composer-stop", ["bang"]))
        timed.sort(key=lambda t: (t[0], t[1]))
        lines, now = [], 0.0
        for t, _, receiver, words in timed:
            delta = round((t - now) * 1000.0, 3)
            now = t
            lines.append(" ".join([f"{delta:.3f}".rstrip("0").rstrip("."), atom(receiver)]
                                  + [atom(_num(w)) for w in words]) + ";")
        return "\n".join(lines) + "\n"

    # -- main ----------------------------------------------------------------
    def compile_main(self, boundaries):
        file = "main.pd"
        patch = Patch(canvas=(40, 40, 1300, 820, 10))
        patch.text("title", 20, 10, f"Composer - {self.p.title} - generated from "
                   f"{self.p.id} - do not edit: change the project and recompile")
        patch.msg("play", 20, 40, ";", "composer-play", "bang")
        patch.msg("stop", 140, 40, ";", "composer-stop", "bang")
        patch.obj("lb", 20, 90, "loadbang")
        patch.obj("lbt", 20, 115, "t", "b", "b")
        patch.msg("dsp", 160, 140, ";", "pd", "dsp", 1)
        patch.msg("read", 100, 140, "read", "score.txt")
        patch.obj("delay", 20, 140, "del", START_DELAY_MS)
        patch.msg("go", 20, 165, ";", "composer-play", "bang")
        patch.obj("rplay", 300, 90, "r", "composer-play")
        patch.msg("rewind", 300, 115, "rewind", ",", "bang")
        patch.obj("rstop", 420, 90, "r", "composer-stop")
        patch.msg("qstop", 420, 115, "rewind")
        patch.obj("qlist", 300, 165, "qlist")
        sources = [recv(p.id) for p in self.p.parts] + [
            recv(n.id) for n in self.p.nodes if n.part_id is None and self.module(n).source]
        silence = []
        for r in sources:
            silence += [";", r, "stop"]
        if silence:
            patch.msg("silence", 500, 115, *silence)
        patch.connect("lb", 0, "lbt", 0)
        patch.connect("lbt", 1, "dsp", 0)
        patch.connect("lbt", 1, "read", 0)
        patch.connect("lbt", 0, "delay", 0)
        patch.connect("delay", 0, "go", 0)
        patch.connect("read", 0, "qlist", 0)
        patch.connect("rplay", 0, "rewind", 0)
        patch.connect("rewind", 0, "qlist", 0)
        patch.connect("rstop", 0, "qstop", 0)
        patch.connect("qstop", 0, "qlist", 0)
        if silence:
            patch.connect("rstop", 0, "silence", 0)

        for k, part in enumerate(self.p.parts):
            patch.obj(part.id, 20 + 200 * k, 260, f"part_{slug(part.id)}")
            self.id_map[part.id] = {"file": file, "object_index": patch.index(part.id)}
        top = [n for n in self.p.nodes if n.part_id is None]
        for k, node in enumerate(top):
            self.place_node(patch, node, 20 + 240 * k, 360, file)

        def endpoint(text, direction):
            node, port = self.port(text)
            if node.part_id is None:
                return Endpoint(node.id, port.pd)
            table = boundaries[node.part_id][0 if direction == "in" else 1]
            return Endpoint(node.part_id, table[text])

        for c in self.p.connections:
            s_node, _ = self.port(c.source)
            t_node, _ = self.port(c.target)
            if s_node.part_id is not None and s_node.part_id == t_node.part_id:
                continue  # inside a part
            src, dst = endpoint(c.source, "out"), endpoint(c.target, "in")
            for ch in (0, 1):
                patch.connect(src.box, src.pd[ch], dst.box, dst.pd[ch])
            self.id_map[c.id] = {"file": file}

        patch.obj("catchL", 20, 560, "catch~", "composer-L")
        patch.obj("catchR", 160, 560, "catch~", "composer-R")
        patch.obj("dac", 20, 620, "dac~", 1, 2)
        patch.obj("busL", 160, 620, "s~", "composer-bus-L")
        patch.obj("busR", 300, 620, "s~", "composer-bus-R")
        for ch, key in enumerate(("catchL", "catchR")):
            patch.connect(key, 0, "dac", ch)
            patch.connect(key, 0, ("busL", "busR")[ch], 0)
        return file, patch.serialize()

    # -- driver --------------------------------------------------------------
    def run(self):
        issues = validate(self.p)
        if not self.p.nodes:
            from .validate import Issue
            issues.append(Issue("error", self.p.id, "nessuna composizione da compilare: il brief aspetta l'IA"))
        rep = report(issues)
        _write(self.out / "reports" / "validation.json", json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
        if rep["errors"]:
            raise CompileError(issues)

        changed = self.copy_assets()
        files = {}
        boundaries = {}
        for part in self.p.parts:
            name, text, part_in, part_out = self.compile_part(part)
            files[name] = text
            boundaries[part.id] = (part_in, part_out)
        name, text = self.compile_main(boundaries)
        files[name] = text
        files["score.txt"] = self.score()

        modules = sorted({self.module(n).abstraction for n in self.p.nodes}
                         | ({"composer.bank_slot"} if any(n.type == "bank" for n in self.p.nodes) else set()))
        for m in modules:
            files[f"{m}.pd"] = (catalog.PD_MODULES / f"{m}.pd").read_text()

        for name, text in files.items():
            if _write(self.patches / name, text):
                changed.append(f"patches/{name}")
        for stale in self.patches.glob("*"):
            if stale.name not in files and not stale.name.startswith("_"):
                stale.unlink()
                changed.append(f"patches/{stale.name} (rimosso)")

        snapshot = self.p.to_dict()
        for a in snapshot["assets"]:
            if a["id"] in self.asset_files:
                a["path"] = f"assets/{self.asset_files[a['id']]}"
        if _write(self.out / "composer.project.json", json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"):
            changed.append("composer.project.json")

        _write(self.out / "reports" / "rules.json",
               json.dumps({"seed": self.p.seed, "rules": self.rule_report}, indent=2, ensure_ascii=False) + "\n")

        manifest = {
            "composer_version": __version__,
            "catalog_version": catalog.CATALOG_VERSION,
            "pure_data": {"version": PD_VERSION, "flavor": "vanilla", "externals": []},
            "project": {"id": self.p.id, "title": self.p.title, "seed": self.p.seed,
                        "duration_seconds": self.p.duration_seconds},
            "entry": "patches/main.pd",
            "modules": modules,
            "rules": {rid: {"triggers": r["triggers"], "events": len(r["events"])}
                      for rid, r in self.rule_report.items()},
            "id_map": self.id_map,
            "files": {name: hashlib.sha256(text.encode()).hexdigest()[:16]
                      for name, text in sorted(files.items())},
        }
        _write(self.out / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        return {"out": str(self.out), "changed": changed, "report": rep}


def _num(word):
    try:
        return float(word)
    except ValueError:
        return word


def compile_project(project, out_dir):
    return Compiler(project, out_dir).run()
