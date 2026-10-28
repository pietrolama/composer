"""Inspector: properties of the selected node or part, edited through callbacks."""

from PySide6.QtCore import Signal
import random

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import catalog, rules


class Inspector(QWidget):
    param_changed = Signal(str, str, object)   # node id, param, value
    node_part_changed = Signal(str, object)    # node id, part id or None
    part_changed = Signal(str, dict)           # part id, fields for edit.update_part
    rule_changed = Signal(str, dict)           # rule id, fields for edit.update_rule
    seed_changed = Signal(int)
    section_changed = Signal(str, dict)        # section id, fields for edit.update_section
    intent_block_changed = Signal(str, dict)   # block id, fields for edit.update_intent_block

    def __init__(self):
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(10, 10, 10, 10)
        self.body = None
        self.show_none()

    def _reset(self, title, subtitle=""):
        if self.body:
            self.box.removeWidget(self.body)
            self.body.hide()
            self.body.deleteLater()
        self.body = QWidget()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QLabel(f"<b>{title}</b><br><span style='color:#9aa0a6'>{subtitle}</span>")
        head.setWordWrap(True)
        lay.addWidget(head)
        form = QFormLayout()
        lay.addLayout(form)
        lay.addStretch(1)
        self.box.addWidget(self.body)
        return form

    def show_none(self, count=0, project=None, rule_counts=None):
        if count or project is None:
            self._reset("Nessuna selezione" if not count else f"{count} elementi selezionati",
                        "Clic destro sul canvas per aggiungere un modulo; trascina da un'uscita a un ingresso "
                        "per collegare; clic destro su una parte per una nuova regola.")
            return
        form = self._reset(project.title, f"{project.id} · {project.duration_seconds:g} s · "
                           f"{len(project.parts)} parti · {len(project.rules)} regole")
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        seed = QSpinBox()
        seed.setRange(0, 2 ** 31 - 1)
        seed.setValue(project.seed)
        seed.setKeyboardTracking(False)
        seed.valueChanged.connect(self.seed_changed.emit)
        reroll = QPushButton("nuovo")
        reroll.setToolTip("Estrae un altro seed: le regole generano un'altra variante, sempre riproducibile")
        reroll.clicked.connect(lambda: self.seed_changed.emit(random.randrange(1, 1_000_000)))
        lay.addWidget(seed, 1)
        lay.addWidget(reroll)
        form.addRow("seed", row)
        total = sum((rule_counts or {}).values())
        form.addRow("", QLabel(f"<span style='color:#9aa0a6'>le regole generano {total} eventi con questo seed</span>"))

    def show_rule(self, project, rule, expansion=None):
        form = self._reset(f"Regola {rule.id}",
                           f"{rule.source} → {rule.target}. Relazione compositiva: diventa eventi "
                           f"calcolati dal seed, non un cavo audio.")
        when = QComboBox()
        when.addItems(list(rules.WHEN))
        when.setCurrentText(rule.when)
        when.activated.connect(lambda _: self.rule_changed.emit(rule.id, {"when": when.currentText()}))
        form.addRow("quando", when)
        effect = QComboBox()
        effect.addItems(list(rules.EFFECT))
        effect.setCurrentText(rule.effect)
        effect.activated.connect(lambda _: self.rule_changed.emit(rule.id, {"effect": effect.currentText()}))
        form.addRow("effetto", effect)
        values = rules.params(rule)
        spec = {**rules.WHEN.get(rule.when, {}), **rules.EFFECT.get(rule.effect, {})}
        for name, (lo, hi, _) in spec.items():
            w = QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setDecimals(2 if hi <= 1 else 1)
            w.setSingleStep(0.05 if hi <= 1 else (10 if hi > 100 else 1))
            w.setKeyboardTracking(False)
            if name.endswith("_ms"):
                w.setSuffix(" ms")
            elif name.endswith("_hz"):
                w.setSuffix(" Hz")
            w.setValue(float(values[name]))
            w.valueChanged.connect(lambda v, n=name: self.rule_changed.emit(rule.id, {"params": {n: v}}))
            form.addRow(name, w)
        if expansion is not None:
            form.addRow("", QLabel(f"<span style='color:#9aa0a6'>{expansion.triggers} trigger → "
                                   f"{len(expansion.events)} eventi (seed {project.seed})</span>"))

    def show_connection(self, conn):
        form = self._reset("Collegamento audio", conn.id)
        form.addRow("da", QLabel(conn.source))
        form.addRow("a", QLabel(conn.target))

    def show_node(self, project, node):
        mod = catalog.MODULES.get(node.type)
        form = self._reset(node.type, node.id + (f" — {mod.doc}" if mod and mod.doc else ""))
        part = QComboBox()
        part.addItem("— primo livello —", None)
        for p in project.parts:
            part.addItem(p.name, p.id)
        part.setCurrentIndex(max(0, part.findData(node.part_id)))
        part.activated.connect(lambda _: self.node_part_changed.emit(node.id, part.currentData()))
        form.addRow("parte", part)
        if not mod:
            return
        for spec in mod.params:
            value = node.params.get(spec.name, spec.default)
            is_modified = spec.name in node.params and node.params[spec.name] != spec.default
            param_label = f"<b>{spec.name} *</b>" if is_modified else spec.name
            if spec.kind == "float":
                w = QDoubleSpinBox()
                w.setDecimals(3 if (spec.max or 0) <= 20 else 1)
                w.setRange(spec.min if spec.min is not None else -1e9, spec.max if spec.max is not None else 1e9)
                w.setSingleStep(0.05 if (spec.max or 0) <= 20 else 10)
                w.setKeyboardTracking(False)
                if spec.unit and spec.unit != "lin":
                    w.setSuffix(f" {spec.unit}")
                w.setValue(float(value))
                w.valueChanged.connect(lambda v, n=spec.name: self.param_changed.emit(node.id, n, v))
            elif spec.kind == "asset_list":
                w = QLabel("<br>".join(f"{k}: {a}" for k, a in enumerate(value)) or "—")
                w.setStyleSheet("color:#9aa0a6")
            elif spec.kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(value))
                w.toggled.connect(lambda v, n=spec.name: self.param_changed.emit(node.id, n, v))
            else:
                w = QComboBox()
                w.addItem("(campione della parte)", None)
                for a in project.assets:
                    w.addItem(a.id, a.id)
                w.setCurrentIndex(max(0, w.findData(node.params.get(spec.name))))
                w.activated.connect(lambda _, n=spec.name, c=w: self.param_changed.emit(node.id, n, c.currentData()))
            w.setToolTip(f"{spec.name}: default {spec.default} ({spec.min}–{spec.max} {spec.unit})" if spec.kind == "float" else spec.name)
            form.addRow(param_label, w)

    def show_part(self, project, part):
        form = self._reset(f"Parte «{part.name}»", part.id)
        name = QLineEdit(part.name)
        name.editingFinished.connect(lambda: name.text() != part.name and
                                     self.part_changed.emit(part.id, {"name": name.text()}))
        form.addRow("nome", name)
        role = QLineEdit(part.role)
        role.setPlaceholderText("background, foreground, interruzione…")
        role.editingFinished.connect(lambda: role.text() != part.role and
                                     self.part_changed.emit(part.id, {"role": role.text()}))
        form.addRow("ruolo", role)
        src = QComboBox()
        src.addItem("— nessuno —", None)
        for a in project.assets:
            src.addItem(a.id, a.id)
        src.setCurrentIndex(max(0, src.findData(part.source_id)))
        src.activated.connect(lambda _: self.part_changed.emit(part.id, {"source_id": src.currentData()}))
        form.addRow("campione", src)
        for s in project.sections:
            cb = QCheckBox(f"{s.name}  ({s.start:g}–{s.end:g} s)")
            cb.setChecked(s.id in part.section_ids)
            cb.toggled.connect(lambda on, sid=s.id: self.part_changed.emit(part.id, {"section_ids": (
                [x for x in part.section_ids if x != sid] + ([sid] if on else []))}))
            form.addRow("sezione" if s is project.sections[0] else "", cb)
        lock = QCheckBox("bloccata (l'IA non la modifica)")
        lock.setChecked(part.locked)
        lock.toggled.connect(lambda on: self.part_changed.emit(part.id, {"locked": on}))
        form.addRow("", lock)

    def show_section(self, project, section):
        form = self._reset(f"Sezione «{section.name}»", f"{section.id} · {section.start:g}s – {section.end:g}s")
        name = QLineEdit(section.name)
        name.editingFinished.connect(lambda: name.text() != section.name and
                                     self.section_changed.emit(section.id, {"name": name.text()}))
        form.addRow("nome", name)

        curr_dur = section.end - section.start
        dur = QDoubleSpinBox()
        dur.setRange(0.1, 3600)
        dur.setDecimals(1)
        dur.setSingleStep(1.0)
        dur.setSuffix(" s")
        dur.setKeyboardTracking(False)
        dur.setValue(curr_dur)
        dur.editingFinished.connect(lambda: dur.value() != curr_dur and
                                    self.section_changed.emit(section.id, {"duration": dur.value()}))
        form.addRow("durata", dur)

        energy = QDoubleSpinBox()
        energy.setRange(0, 1)
        energy.setDecimals(2)
        energy.setSingleStep(0.05)
        energy.setKeyboardTracking(False)
        energy.setValue(section.energy)
        energy.editingFinished.connect(lambda: energy.value() != section.energy and
                                       self.section_changed.emit(section.id, {"energy": energy.value()}))
        form.addRow("energia", energy)

        density = QDoubleSpinBox()
        density.setRange(0, 1)
        density.setDecimals(2)
        density.setSingleStep(0.05)
        density.setKeyboardTracking(False)
        density.setValue(section.density)
        density.editingFinished.connect(lambda: density.value() != section.density and
                                        self.section_changed.emit(section.id, {"density": density.value()}))
        form.addRow("densità", density)

        intent = QLineEdit(section.intent)
        intent.setPlaceholderText("cosa deve accadere in questa sezione...")
        intent.editingFinished.connect(lambda: intent.text() != section.intent and
                                       self.section_changed.emit(section.id, {"intent": intent.text()}))
        form.addRow("intenzione", intent)

        parts_in_sec = [p for p in project.parts if section.id in p.section_ids]
        part_names = ", ".join(p.name for p in parts_in_sec) or "nessuna parte attiva"
        form.addRow("parti attive", QLabel(f"<span style='color:#9aa0a6'>{part_names}</span>"))

    def show_intent_block(self, project, block):
        from ..intent import INTENT_CATEGORIES
        cat = INTENT_CATEGORIES.get(block.category)
        form = self._reset(f"Blocco Intenzionale «{block.name or block.category}»",
                           f"Categoria: {cat.label if cat else block.category} · Corsia {block.lane + 1}")
        name = QLineEdit(block.name)
        name.editingFinished.connect(lambda: name.text() != block.name and
                                     self.intent_block_changed.emit(block.id, {"name": name.text()}))
        form.addRow("nome", name)

        start = QDoubleSpinBox()
        start.setRange(0.0, 7200.0)
        start.setDecimals(2)
        start.setSingleStep(0.5)
        start.setSuffix(" s")
        start.setKeyboardTracking(False)
        start.setValue(block.start)
        start.editingFinished.connect(lambda: start.value() != block.start and
                                      self.intent_block_changed.emit(block.id, {"start": start.value()}))
        form.addRow("inizio", start)

        dur = QDoubleSpinBox()
        dur.setRange(0.1, 7200.0)
        dur.setDecimals(2)
        dur.setSingleStep(0.5)
        dur.setSuffix(" s")
        dur.setKeyboardTracking(False)
        dur.setValue(block.duration)
        dur.editingFinished.connect(lambda: dur.value() != block.duration and
                                    self.intent_block_changed.emit(block.id, {"duration": dur.value()}))
        form.addRow("durata", dur)

        lane = QSpinBox()
        lane.setRange(1, 16)
        lane.setValue(block.lane + 1)
        lane.valueChanged.connect(lambda v: self.intent_block_changed.emit(block.id, {"lane": v - 1}))
        form.addRow("corsia", lane)

        src = QComboBox()
        src.addItem("— sintetizzatore / generatore interno —", None)
        for a in project.assets:
            src.addItem(a.id, a.id)
        src.setCurrentIndex(max(0, src.findData(block.source_asset)))
        src.activated.connect(lambda _: self.intent_block_changed.emit(block.id, {"source_asset": src.currentData()}))
        form.addRow("campione", src)

        if cat:
            form.addRow("", QLabel(f"<b>Parametri Espressivi ({cat.label})</b>"))
            for param in cat.params:
                val = block.params.get(param.name, param.default)
                spin = QDoubleSpinBox()
                spin.setRange(param.min, param.max)
                spin.setDecimals(2 if param.step < 1 else 1)
                spin.setSingleStep(param.step)
                if param.unit:
                    spin.setSuffix(f" {param.unit}")
                spin.setKeyboardTracking(False)
                spin.setValue(float(val))
                spin.setToolTip(param.doc)
                spin.editingFinished.connect(
                    lambda p=param.name, s=spin: self.intent_block_changed.emit(
                        block.id, {"params": {p: s.value()}}))
                form.addRow(param.label, spin)
