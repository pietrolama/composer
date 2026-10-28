"""python -m composer <command> ..."""

import argparse
import json
import sys
from pathlib import Path

from . import compose, model, pdrun
from .compiler import CompileError, compile_project
from .gen import CompositionError
from .integrations.glitchlab import GlitchLabAdapter, GlitchLabUnavailable
from .validate import validate


def _issues(issues):
    for i in issues:
        mark = "✗" if i.level == "error" else "!"
        print(f"{mark} {i.element}: {i.message}")
    errors = sum(i.level == "error" for i in issues)
    print(f"{errors} errori, {len(issues) - errors} avvisi")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="composer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="controlla il progetto")
    s.add_argument("project")

    s = sub.add_parser("compile", help="genera la cartella Pd")
    s.add_argument("project")
    s.add_argument("-o", "--out", help="cartella di destinazione (default: build/<id>)")

    s = sub.add_parser("check", help="carica main.pd in Pd e riporta gli errori")
    s.add_argument("out")

    s = sub.add_parser("render", help="render offline in WAV")
    s.add_argument("out")
    s.add_argument("-w", "--wav", help="default: <out>/render.wav")
    s.add_argument("-s", "--seconds", type=float)

    s = sub.add_parser("assets", help="elenca i campioni glitchLAB")
    s.add_argument("--character")
    s.add_argument("--kept", action="store_true")
    s.add_argument("--max-duration", type=float)
    s.add_argument("--min-duration", type=float)

    s = sub.add_parser("brief", help="scrive brief.md per l'IA (e lo stampa)")
    s.add_argument("project")

    s = sub.add_parser("compose", help="esegue composition.py, archivia la versione e compila")
    s.add_argument("project")
    s.add_argument("--script")

    s = sub.add_parser("verdict", help="accetta/rifiuta la versione corrente con un commento")
    s.add_argument("project")
    s.add_argument("status", choices=["accettata", "rifiutata", "proposta"])
    s.add_argument("feedback", nargs="?", default="")

    s = sub.add_parser("instrument", help="genera uno strumento con glitchLAB e lo aggiunge al brief")
    s.add_argument("project")
    s.add_argument("name")
    s.add_argument("character")
    s.add_argument("-l", "--length", default="micro")
    s.add_argument("-n", "--count", type=int, default=8)
    s.add_argument("-d", "--density", type=float, default=0.5)
    s.add_argument("-e", "--energy", type=float, default=0.5)
    s.add_argument("--description", default="")

    s = sub.add_parser("import", help="aggiunge un campione glitchLAB al progetto")
    s.add_argument("project")
    s.add_argument("glitchlab_id")
    s.add_argument("--as", dest="asset_id")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "validate":
            return _issues(validate(model.load(args.project)))

        if args.cmd == "compile":
            project = model.load(args.project)
            out = args.out or Path(args.project).resolve().parent / "build" / project.id
            res = compile_project(project, out)
            print(f"→ {res['out']}")
            for f in res["changed"] or ["(nessun file cambiato)"]:
                print(f"  {f}")
            rep = res["report"]
            print(f"{rep['errors']} errori, {rep['warnings']} avvisi")
            return 0

        if args.cmd == "check":
            res = pdrun.check(args.out)
            print(f"Pd {res['pd']}: " + ("caricamento ok" if res["ok"] else "problemi"))
            for line in res["problems"]:
                print(f"  {line}")
            return 0 if res["ok"] else 1

        if args.cmd == "render":
            wav = args.wav or Path(args.out) / "render.wav"
            res = pdrun.render(args.out, wav, args.seconds)
            print(("→ " if res["ok"] else "✗ ") + res["wav"])
            for line in res["problems"]:
                print(f"  {line}")
            return 0 if res["ok"] else 1

        if args.cmd == "assets":
            items = GlitchLabAdapter().list_assets(args.character, True if args.kept else None,
                                                   args.max_duration, args.min_duration)
            for m in items:
                d = m["descriptors"]
                print(f"{'★' if m['kept'] else ' '} {m['id']}  {m['character']:16s} "
                      f"{d.get('duration', 0):6.2f}s  centroid {d.get('centroid', 0):7.0f}  "
                      f"rms {d.get('rms', 0):6.1f}")
            print(f"{len(items)} campioni")
            return 0

        if args.cmd == "brief":
            project = model.load(args.project)
            text = compose.brief_markdown(project)
            (project.path.parent / "brief.md").write_text(text)
            print(text)
            return 0

        if args.cmd == "compose":
            project = model.load(args.project)
            version, issues = compose.run(project, args.script)
            print(f"composizione v{version}")
            if _issues(issues):
                return 1
            res = compile_project(project, project.path.parent / "build" / project.id)
            print(f"→ {res['out']}")
            return 0

        if args.cmd == "verdict":
            project = model.load(args.project)
            compose.set_status(project, args.status, args.feedback)
            project.save()
            print(f"v{project.composition_meta.get('version')}: {args.status}")
            return 0

        if args.cmd == "instrument":
            from .integrations.glitchlab import generate_instrument
            project = model.load(args.project)
            ins = generate_instrument(project, args.name, args.character, args.length, args.density,
                                      args.energy, args.count, args.description)
            project.save()
            print(f"+ {ins.id}: {len(ins.assets)} campioni")
            return 0

        if args.cmd == "import":
            project = model.load(args.project)
            asset = GlitchLabAdapter().import_asset(args.glitchlab_id, args.asset_id, project.path.parent)
            if any(a.id == asset.id for a in project.assets):
                print(f"asset già presente: {asset.id}", file=sys.stderr)
                return 1
            project.assets.append(asset)
            project.save()
            print(f"+ {asset.id} → {asset.path}")
            return 0
    except CompositionError as exc:
        print(f"errore nella composizione: {exc}", file=sys.stderr)
        return 1
    except CompileError as exc:
        return _issues(exc.issues)
    except (GlitchLabUnavailable, KeyError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1
