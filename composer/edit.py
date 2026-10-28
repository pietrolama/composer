"""Model edits shared by every front end (GUI, CLI, future AI proposals).

Each function changes the project in place and raises EditError when the edit
would make the model inconsistent. Undo lives above this layer (snapshots).
"""

import re

from . import catalog
from .model import Node, Part, Connection
from .validate import split_endpoint


class EditError(ValueError):
    pass


def new_id(project, prefix):
    taken = set(project.by_id())
    base = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "id"
    k = 1
    while f"{base}-{k}" in taken:
        k += 1
    return f"{base}-{k}"


def _node(project, node_id):
    node = next((n for n in project.nodes if n.id == node_id), None)
    if node is None:
        raise EditError(f"nodo inesistente: {node_id}")
    return node


def positions(project, layer="nodes"):
    return project.presentation.setdefault(layer, {})


def add_node(project, module, part_id=None, pos=(0, 0), params=None):
    mod = catalog.MODULES.get(module)
    if mod is None:
        raise EditError(f"modulo sconosciuto: {module}")
    if part_id is not None and not any(p.id == part_id for p in project.parts):
        raise EditError(f"parte inesistente: {part_id}")
    node = Node(new_id(project, f"node-{module}"), module, part_id, dict(params or {}))
    for name, value in node.params.items():
        problem = catalog.check_param(mod, name, value)
        if problem:
            raise EditError(problem)
    project.nodes.append(node)
    positions(project)[node.id] = {"x": round(pos[0]), "y": round(pos[1])}
    return node


def remove_node(project, node_id):
    """Remove a node with its cables and the events addressed to it."""
    _node(project, node_id)
    project.nodes = [n for n in project.nodes if n.id != node_id]
    project.connections = [c for c in project.connections
                           if split_endpoint(c.source)[0] != node_id and split_endpoint(c.target)[0] != node_id]
    project.events = [e for e in project.events if e.target != node_id]
    project.rules = [r for r in project.rules if node_id not in (r.source, r.target)]
    positions(project).pop(node_id, None)


def move_node(project, node_id, x, y):
    _node(project, node_id)
    positions(project)[node_id] = {"x": round(x), "y": round(y)}


def set_param(project, node_id, name, value):
    node = _node(project, node_id)
    mod = catalog.MODULES[node.type]
    spec = mod.param(name)
    if spec is not None and spec.kind == "float":
        value = float(value)
    problem = catalog.check_param(mod, name, value)
    if problem:
        raise EditError(problem)
    if spec.kind == "asset" and value and not any(a.id == value for a in project.assets):
        raise EditError(f"asset inesistente: {value}")
    if value in (None, "") and spec.kind == "asset":
        node.params.pop(name, None)
    else:
        node.params[name] = value


def set_node_part(project, node_id, part_id):
    node = _node(project, node_id)
    if part_id is not None and not any(p.id == part_id for p in project.parts):
        raise EditError(f"parte inesistente: {part_id}")
    node.part_id = part_id


def port_of(project, endpoint):
    nid, pname = split_endpoint(endpoint)
    node = _node(project, nid)
    port = catalog.MODULES[node.type].port(pname)
    if port is None:
        raise EditError(f"{node.type} non ha la porta '{pname}'")
    return port


def connect(project, source, target):
    """Audio cable from an output port to an input port ("node.port")."""
    sp, tp = port_of(project, source), port_of(project, target)
    if sp.direction != "out" or tp.direction != "in":
        raise EditError("un cavo va da un'uscita a un ingresso")
    if sp.type != tp.type:
        raise EditError(f"tipi incompatibili: {sp.type} → {tp.type}")
    if split_endpoint(source)[0] == split_endpoint(target)[0]:
        raise EditError("un nodo non può alimentare se stesso")
    if any(c.source == source and c.target == target for c in project.connections):
        raise EditError("collegamento già presente")
    if _reaches(project, split_endpoint(target)[0], split_endpoint(source)[0]):
        raise EditError("il collegamento creerebbe un ciclo audio")
    conn = Connection(new_id(project, "conn"), source, target)
    project.connections.append(conn)
    return conn


def _reaches(project, start, goal):
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n == goal:
            return True
        if n in seen:
            continue
        seen.add(n)
        todo += [split_endpoint(c.target)[0] for c in project.connections if split_endpoint(c.source)[0] == n]
    return False


def disconnect(project, conn_id):
    before = len(project.connections)
    project.connections = [c for c in project.connections if c.id != conn_id]
    if len(project.connections) == before:
        raise EditError(f"collegamento inesistente: {conn_id}")


def add_part(project, name, source_id=None, section_ids=()):
    part = Part(new_id(project, f"part-{name}"), name, source_id=source_id, section_ids=list(section_ids))
    project.parts.append(part)
    return part


def remove_part(project, part_id):
    """Remove a part; its nodes move to the top level rather than disappearing."""
    if not any(p.id == part_id for p in project.parts):
        raise EditError(f"parte inesistente: {part_id}")
    project.parts = [p for p in project.parts if p.id != part_id]
    for n in project.nodes:
        if n.part_id == part_id:
            n.part_id = None
    project.events = [e for e in project.events if e.target != part_id]
    project.rules = [r for r in project.rules if part_id not in (r.source, r.target)]


def update_part(project, part_id, name=None, role=None, source_id=..., section_ids=None, locked=None):
    part = next((p for p in project.parts if p.id == part_id), None)
    if part is None:
        raise EditError(f"parte inesistente: {part_id}")
    if source_id is not ... and source_id and not any(a.id == source_id for a in project.assets):
        raise EditError(f"asset inesistente: {source_id}")
    if section_ids is not None:
        known = {s.id for s in project.sections}
        missing = [s for s in section_ids if s not in known]
        if missing:
            raise EditError(f"sezioni inesistenti: {', '.join(missing)}")
        part.section_ids = list(section_ids)
    if name is not None:
        part.name = name.strip() or part.name
    if role is not None:
        part.role = role.strip()
    if source_id is not ...:
        part.source_id = source_id or None
    if locked is not None:
        part.locked = bool(locked)


def duplicate_nodes(project, node_ids, offset=(40, 40)):
    """Copy nodes with the cables between them; return old id -> new node."""
    pos = positions(project)
    copies = {}
    for nid in node_ids:
        src = _node(project, nid)
        p = pos.get(nid, {"x": 0, "y": 0})
        copies[nid] = add_node(project, src.type, src.part_id, (p["x"] + offset[0], p["y"] + offset[1]),
                               dict(src.params))
    for c in list(project.connections):
        (s, sp), (t, tp) = split_endpoint(c.source), split_endpoint(c.target)
        if s in copies and t in copies:
            connect(project, f"{copies[s].id}.{sp}", f"{copies[t].id}.{tp}")
    return copies


def add_rule(project, source, target, when="on_onset", effect="fragment", params=None):
    from .model import Rule
    from . import rules
    rule = Rule(new_id(project, "rule"), source, target, when, effect, dict(params or {}))
    problems = [m for level, m in rules.check(project, rule) if level == "error"]
    if problems:
        raise EditError(problems[0])
    project.rules.append(rule)
    return rule


def update_rule(project, rule_id, when=None, effect=None, params=None):
    """Change a rule; params entries set to None fall back to the default."""
    from . import rules
    rule = next((r for r in project.rules if r.id == rule_id), None)
    if rule is None:
        raise EditError(f"regola inesistente: {rule_id}")
    if when is not None:
        rule.when = when
        allowed = {**rules.WHEN.get(when, {}), **rules.EFFECT.get(rule.effect, {})}
        rule.params = {k: v for k, v in rule.params.items() if k in allowed}
    if effect is not None:
        rule.effect = effect
    for k, v in (params or {}).items():
        if v is None:
            rule.params.pop(k, None)
        else:
            rule.params[k] = float(v)
    problems = [m for level, m in rules.check(project, rule) if level == "error"]
    if problems:
        raise EditError(problems[0])


def remove_rule(project, rule_id):
    before = len(project.rules)
    project.rules = [r for r in project.rules if r.id != rule_id]
    if len(project.rules) == before:
        raise EditError(f"regola inesistente: {rule_id}")


def set_seed(project, seed):
    project.seed = int(seed)


# -- brief: what the composer (human) declares -----------------------------------------
def _retime(project):
    """Sections are contiguous: recompute start/end from their order and durations."""
    t = 0.0
    for s in project.sections:
        d = s.end - s.start
        s.start, s.end = round(t, 3), round(t + d, 3)
        t += d
    if project.sections:
        project.duration_seconds = round(t, 3)


def add_section(project, name, duration=30.0, intent="", energy=0.5, density=0.5, index=None):
    from .model import Section
    if duration <= 0:
        raise EditError("la durata deve essere positiva")
    sec = Section(new_id(project, f"sec-{name}"), name, 0.0, float(duration), intent, energy, density)
    project.sections.insert(len(project.sections) if index is None else index, sec)
    _retime(project)
    return sec


def update_section(project, section_id, name=None, duration=None, intent=None, energy=None, density=None):
    sec = project.section(section_id)
    if sec is None:
        raise EditError(f"sezione inesistente: {section_id}")
    for k, v in (("energy", energy), ("density", density)):
        if v is not None and not 0 <= float(v) <= 1:
            raise EditError(f"{k} deve stare tra 0 e 1")
    if duration is not None:
        if float(duration) <= 0:
            raise EditError("la durata deve essere positiva")
        sec.end = sec.start + float(duration)
    if name is not None:
        sec.name = name.strip() or sec.name
    if intent is not None:
        sec.intent = intent
    if energy is not None:
        sec.energy = float(energy)
    if density is not None:
        sec.density = float(density)
    _retime(project)


def move_section(project, section_id, delta):
    i = next((k for k, s in enumerate(project.sections) if s.id == section_id), None)
    if i is None:
        raise EditError(f"sezione inesistente: {section_id}")
    j = i + delta
    if not 0 <= j < len(project.sections):
        return
    project.sections[i], project.sections[j] = project.sections[j], project.sections[i]
    _retime(project)


def remove_section(project, section_id):
    if project.section(section_id) is None:
        raise EditError(f"sezione inesistente: {section_id}")
    project.sections = [s for s in project.sections if s.id != section_id]
    for p in project.parts:
        p.section_ids = [x for x in p.section_ids if x != section_id]
    _retime(project)


def add_instrument(project, name, assets, description="", source=None):
    from .model import Instrument
    for a in assets:
        if not any(x.id == a.id for x in project.assets):
            project.assets.append(a)
    ins = Instrument(new_id(project, f"ins-{name}"), name, description, [a.id for a in assets], dict(source or {}))
    project.brief.instruments.append(ins)
    return ins


def update_instrument(project, instrument_id, name=None, description=None):
    ins = project.instrument(instrument_id)
    if ins is None:
        raise EditError(f"strumento inesistente: {instrument_id}")
    if name is not None:
        ins.name = name.strip() or ins.name
    if description is not None:
        ins.description = description


def remove_instrument(project, instrument_id):
    """Drop an instrument and the assets nobody else uses (the files stay where they are)."""
    ins = project.instrument(instrument_id)
    if ins is None:
        raise EditError(f"strumento inesistente: {instrument_id}")
    project.brief.instruments = [i for i in project.brief.instruments if i.id != instrument_id]
    still = {a for i in project.brief.instruments for a in i.assets}
    project.assets = [a for a in project.assets if a.id in still or a.id not in ins.assets]


def set_palette(project, modules):
    from . import catalog
    for m in modules:
        if m not in catalog.MODULES or catalog.MODULES[m].category != "effect":
            raise EditError(f"non è un effetto del catalogo: {m}")
    project.brief.palette = sorted(set(modules))


def set_brief_notes(project, notes):
    project.brief.notes = notes


def set_project_fields(project, title=None, tempo=None):
    if title is not None:
        project.title = title.strip() or project.title
    if tempo is not None:
        if not 20 <= float(tempo) <= 400:
            raise EditError("tempo fuori da 20..400 bpm")
        project.tempo = float(tempo)
