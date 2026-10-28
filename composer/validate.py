"""Semantic validation: every issue names the element it belongs to."""

from dataclasses import asdict, dataclass

from . import catalog, rules
from .model import sha256_file


@dataclass
class Issue:
    level: str  # error | warning
    element: str
    message: str


def split_endpoint(text):
    node, _, port = text.partition(".")
    return node, port


def validate(project):
    issues = []

    def err(el, msg):
        issues.append(Issue("error", el, msg))

    def warn(el, msg):
        issues.append(Issue("warning", el, msg))

    seen = set()
    for group in (project.sections, project.parts, project.assets, project.nodes,
                  project.connections, project.events, project.rules):
        for item in group:
            if item.id in seen:
                err(item.id, "id duplicato")
            seen.add(item.id)

    ids = project.by_id()
    sections = {s.id: s for s in project.sections}
    parts = {p.id: p for p in project.parts}
    assets = {a.id: a for a in project.assets}
    nodes = {n.id: n for n in project.nodes}

    if project.duration_seconds <= 0:
        err(project.id, "durata non positiva")
    for s in project.sections:
        if not 0 <= s.start < s.end <= project.duration_seconds:
            err(s.id, f"sezione {s.start}-{s.end}s fuori da 0-{project.duration_seconds}s o vuota")

    for a in project.assets:
        path = project.asset_path(a)
        if not path.exists():
            err(a.id, f"file mancante: {path}")
        elif not a.sha256:
            warn(a.id, "asset senza hash: provenienza non verificabile")
        elif sha256_file(path) != a.sha256:
            warn(a.id, "il file è cambiato dopo l'importazione (hash diverso)")

    for p in project.parts:
        for sid in p.section_ids:
            if sid not in sections:
                err(p.id, f"sezione inesistente: {sid}")
        if p.source_id and p.source_id not in assets:
            err(p.id, f"asset inesistente: {p.source_id}")
        if not project.part_nodes(p.id):
            warn(p.id, "parte senza moduli: non produce suono")

    for n in project.nodes:
        mod = catalog.MODULES.get(n.type)
        if mod is None:
            err(n.id, f"modulo sconosciuto '{n.type}' (catalogo: {', '.join(catalog.MODULES)})")
            continue
        if n.part_id is not None and n.part_id not in parts:
            err(n.id, f"parte inesistente: {n.part_id}")
        for name, value in n.params.items():
            problem = catalog.check_param(mod, name, value)
            if problem:
                err(n.id, problem)
        for spec in mod.params:
            if spec.kind == "asset_list":
                for aid in n.params.get(spec.name, ()):
                    if aid != "-" and aid not in assets:
                        err(n.id, f"{spec.name}: asset inesistente {aid}")
            if spec.kind == "asset":
                aid = n.params.get(spec.name) or (parts[n.part_id].source_id if n.part_id in parts else None)
                if not aid:
                    err(n.id, f"{spec.name}: nessun asset (né nel nodo né nella parte)")
                elif aid not in assets:
                    err(n.id, f"{spec.name}: asset inesistente {aid}")

    for c in project.connections:
        if c.kind != "audio_connection":
            err(c.id, f"tipo di connessione sconosciuto: {c.kind} (le relazioni vanno in 'rules')")
            continue
        ends = []
        for text, direction in ((c.source, "out"), (c.target, "in")):
            nid, pname = split_endpoint(text)
            node = nodes.get(nid)
            mod = catalog.MODULES.get(node.type) if node else None
            port = mod.port(pname) if mod else None
            if node is None:
                err(c.id, f"nodo inesistente: {nid}")
            elif mod is None:
                pass  # already reported on the node
            elif port is None or port.direction != direction:
                kind = "uscita" if direction == "out" else "ingresso"
                err(c.id, f"{text}: {node.type} non ha un'{kind} '{pname}'")
            ends.append(port)
        if all(ends) and ends[0].type != ends[1].type:
            err(c.id, f"tipi incompatibili: {ends[0].type} → {ends[1].type}")

    for e in project.events:
        if e.target not in parts and e.target not in nodes:
            err(e.id, f"destinazione inesistente: {e.target}")
        if not 0 <= e.time <= project.duration_seconds:
            err(e.id, f"evento a {e.time}s fuori dalla durata")
        if not e.message.split():
            err(e.id, "messaggio vuoto")

    for r in project.rules:
        missing = [ref for ref in (r.source, r.target) if ref not in ids]
        for ref in missing:
            err(r.id, f"riferimento inesistente: {ref}")
        if not missing:
            for level, msg in rules.check(project, r):
                (err if level == "error" else warn)(r.id, msg)

    # the composition may use only what the brief offers
    brief = project.brief
    if brief.palette:
        for n in project.nodes:
            mod = catalog.MODULES.get(n.type)
            if mod and mod.category == "effect" and n.type not in brief.palette:
                err(n.id, f"l'effetto '{n.type}' non è nella tavolozza del brief")
    if brief.instruments:
        offered = {a for i in brief.instruments for a in i.assets}
        for n in project.nodes:
            mod = catalog.MODULES.get(n.type)
            for spec in (mod.params if mod else ()):
                used = n.params.get(spec.name)
                if spec.kind == "asset" and used is None and n.part_id in parts:
                    used = parts[n.part_id].source_id
                ids_ = [used] if spec.kind == "asset" and used else (
                    [a for a in n.params.get(spec.name, ()) if a != "-"] if spec.kind == "asset_list" else [])
                for aid in ids_:
                    if aid not in offered:
                        err(n.id, f"{aid} non appartiene a nessuno strumento del brief")
    for ins in brief.instruments:
        for aid in ins.assets:
            if aid not in assets:
                err(ins.id, f"asset inesistente: {aid}")
        if not ins.assets:
            warn(ins.id, "strumento senza campioni")
    for s_ in project.sections:
        for k in ("energy", "density"):
            v = getattr(s_, k)
            if not isinstance(v, (int, float)) or not 0 <= v <= 1:
                err(s_.id, f"{k}={v} fuori da 0..1")
    for a, b in zip(project.sections, project.sections[1:]):
        if abs(a.end - b.start) > 1e-6:
            warn(b.id, f"la sezione non inizia dove finisce {a.id} ({a.end} ≠ {b.start})")

    if not project.nodes:
        warn(project.id, "nessuna composizione: il brief aspetta l'IA")
        return issues
    if not any(n.type == "output" for n in project.nodes):
        err(project.id, "nessun nodo 'output': la composizione non suonerebbe")
    return issues


def report(issues):
    return {"errors": sum(i.level == "error" for i in issues),
            "warnings": sum(i.level == "warning" for i in issues),
            "issues": [asdict(i) for i in issues]}
