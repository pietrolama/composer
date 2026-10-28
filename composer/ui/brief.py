"""Brief editor: what the composer declares before the AI composes.

Form (sections with an intention, energy, density), instruments (glitchLAB
families or files), effect palette and notes. Every change goes through the
window's undoable apply().
"""

import random
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import catalog, edit
from ..integrations.glitchlab import GlitchLabAdapter
from ..model import Asset, sha256_file
from .canvas import PART_COLORS

CHARACTERS = {
    "organico": "materia che si disgrega",
    "digitale": "tagli, impulsi, precisione",
    "spettrale": "code, risonanze, vuoti",
    "violento": "burst, saturazione, collisioni",
    "microstrutturale": "dettagli microscopici e densità",
    "ibrido": "combinazioni fuori categoria",
}
LENGTHS = {"micro": "micro-eventi < 1 s", "frammento": "frammenti 1–5 s",
           "texture": "texture 5–15 s", "evoluzione": "evoluzioni 15–60 s"}


class FormStrip(QWidget):
    """The form at a glance: width = duration, height = energy, shade = density."""

    section_clicked = Signal(object)  # Section or None

    def __init__(self, compact=False):
        super().__init__()
        self.sections = []
        self.compact = compact
        self.setMinimumHeight(38 if compact else 90)
        self.selected_index = None

    def set_selected_id(self, section_id):
        new_index = next((k for k, s in enumerate(self.sections) if s.id == section_id), None)
        if new_index != self.selected_index:
            self.selected_index = new_index
            self.update()

    def set_sections(self, sections):
        old_id = self.sections[self.selected_index].id if self.selected_index is not None and self.selected_index < len(self.sections) else None
        self.sections = sections
        if old_id:
            self.selected_index = next((k for k, s in enumerate(sections) if s.id == old_id), None)
        elif self.selected_index is not None and self.selected_index >= len(sections):
            self.selected_index = None
        self.update()

    def mousePressEvent(self, e):
        total = sum(s.end - s.start for s in self.sections) or 1
        w, x = self.width() - 2, 1.0
        click_x = e.position().x()
        for k, s in enumerate(self.sections):
            sw = w * (s.end - s.start) / total
            if x <= click_x <= x + sw:
                self.selected_index = k
                self.section_clicked.emit(s)
                self.update()
                return
            x += sw
        self.selected_index = None
        self.section_clicked.emit(None)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1b1d21"))
        total = sum(s.end - s.start for s in self.sections) or 1
        label_h = 14 if self.compact else 22
        w, h, x = self.width() - 2, self.height() - label_h, 1.0
        for k, s in enumerate(self.sections):
            sw = w * (s.end - s.start) / total
            bh = max(4, h * s.energy)
            col = QColor(PART_COLORS[k % len(PART_COLORS)])
            col.setAlphaF(0.35 + 0.6 * s.density)
            rect = QRectF(x + 1, 3 + h - bh, max(1.0, sw - 2), bh)
            p.fillRect(rect, col)
            if self.selected_index == k:
                p.setPen(QPen(QColor("#f2c14e"), 2))
                p.drawRect(QRectF(x + 1, 2, max(1.0, sw - 2), self.height() - 4))
            p.setPen(QColor("#e6e6e6"))
            if not self.compact or sw > 45:
                dur = f" {s.end - s.start:g}s" if sw > 60 else ""
                p.drawText(QRectF(x + 4, h + 1, max(1.0, sw - 8), label_h - 2),
                           Qt.AlignLeft | Qt.AlignVCenter, f"{s.name}{dur}")
            x += sw


class GenerateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Genera strumento con glitchLAB")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("es. Glitch secchi")
        self.character = QComboBox()
        for k, hint in CHARACTERS.items():
            self.character.addItem(f"{k} — {hint}", k)
        self.length = QComboBox()
        for k, hint in LENGTHS.items():
            self.length.addItem(f"{k} — {hint}", k)
        self.density, self.energy = QDoubleSpinBox(), QDoubleSpinBox()
        for w in (self.density, self.energy):
            w.setRange(0, 1)
            w.setSingleStep(0.05)
            w.setValue(0.5)
        self.count = QSpinBox()
        self.count.setRange(1, 16)
        self.count.setValue(8)
        self.description = QLineEdit()
        self.description.setPlaceholderText("cosa deve essere per il pezzo (lo legge l'IA)")
        for label, w in (("nome", self.name), ("carattere", self.character), ("durata", self.length),
                         ("densità", self.density), ("energia", self.energy), ("quanti", self.count),
                         ("descrizione", self.description)):
            form.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {"name": self.name.text().strip() or self.character.currentData(),
                "character": self.character.currentData(), "length": self.length.currentData(),
                "density": self.density.value(), "energy": self.energy.value(),
                "count": self.count.value(), "description": self.description.text().strip()}


class LibraryDialog(QDialog):
    """Pick existing glitchLAB samples (multi-selection)."""

    def __init__(self, parent, adapter):
        super().__init__(parent)
        self.setWindowTitle("Scegli dalla libreria glitchLAB")
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.description = QLineEdit()
        form.addRow("nome", self.name)
        form.addRow("descrizione", self.description)
        lay.addLayout(form)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for m in sorted(adapter.list_assets(), key=lambda m: (m["character"], m["descriptors"]["duration"])):
            d = m["descriptors"]
            it = QListWidgetItem(f"{'★ ' if m['kept'] else ''}{m['character']} · {d['duration']:.2f}s · "
                                 f"{d['centroid']:.0f} Hz · {m['id']}")
            it.setData(Qt.UserRole, m["id"])
            self.list.addItem(it)
        lay.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self):
        return (self.name.text().strip() or "Libreria", self.description.text().strip(),
                [it.data(Qt.UserRole) for it in self.list.selectedItems()])


class _Worker(QObject):
    done = Signal(object, object)  # metas, error

    def __init__(self, adapter, v):
        super().__init__()
        self.adapter, self.v = adapter, v

    def run(self):
        try:
            metas = self.adapter.generate(self.v["character"], count=self.v["count"], length=self.v["length"],
                                          density=self.v["density"], energy=self.v["energy"])
            self.done.emit(metas, None)
        except Exception as exc:  # reported in the UI, never crashes it
            self.done.emit(None, exc)


class BriefEditor(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        self.glitchlab = GlitchLabAdapter()
        self.player = None
        self._thread = None
        self._loading = False

        # -- left: project, form, notes -----------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        head = QFormLayout()
        self.title = QLineEdit()
        self.title.editingFinished.connect(lambda: self._apply_if(
            self.title.text() != self.w.project.title, "titolo",
            lambda p: edit.set_project_fields(p, title=self.title.text())))
        self.tempo = QDoubleSpinBox()
        self.tempo.setRange(20, 400)
        self.tempo.setSuffix(" bpm")
        self.tempo.setKeyboardTracking(False)
        self.tempo.valueChanged.connect(lambda v: self._apply_if(
            v != self.w.project.tempo, "tempo", lambda p: edit.set_project_fields(p, tempo=v)))
        seed_row = QWidget()
        sr = QHBoxLayout(seed_row)
        sr.setContentsMargins(0, 0, 0, 0)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2 ** 31 - 1)
        self.seed.setKeyboardTracking(False)
        self.seed.valueChanged.connect(lambda v: self._apply_if(
            v != self.w.project.seed, "seed", lambda p: edit.set_seed(p, v)))
        reroll = QPushButton("nuovo")
        reroll.clicked.connect(lambda: self.seed.setValue(random.randrange(1, 1_000_000)))
        sr.addWidget(self.seed, 1)
        sr.addWidget(reroll)
        self.duration = QLabel()
        head.addRow("titolo", self.title)
        head.addRow("tempo", self.tempo)
        head.addRow("seed", seed_row)
        head.addRow("durata", self.duration)
        ll.addLayout(head)

        box = QGroupBox("Struttura — sezioni con intenzione")
        bl = QVBoxLayout(box)
        self.strip = FormStrip()
        bl.addWidget(self.strip)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["sezione", "durata s", "energia", "densità", "intenzione"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.cellChanged.connect(self._cell)
        bl.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (("+ sezione", self._add_section), ("↑", lambda: self._move(-1)),
                           ("↓", lambda: self._move(1)), ("elimina", self._remove_section)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        ll.addWidget(box, 3)

        nbox = QGroupBox("Note per l'IA — cosa deve essere il pezzo, cosa evitare")
        nl = QVBoxLayout(nbox)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("es. il pezzo parla di un edificio che esiste solo mentre lo ascolti; "
                                      "niente melodia; silenzi netti; la rottura deve essere un muro.")
        nl.addWidget(self.notes)
        save_notes = QPushButton("salva note")
        save_notes.clicked.connect(lambda: self._apply_if(
            self.notes.toPlainText() != self.w.project.brief.notes, "note",
            lambda p: edit.set_brief_notes(p, self.notes.toPlainText())))
        nl.addWidget(save_notes, 0, Qt.AlignRight)
        ll.addWidget(nbox, 2)

        # -- right: instruments and palette -------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        ibox = QGroupBox("Strumenti")
        il = QVBoxLayout(ibox)
        self.instruments = QListWidget()
        self.instruments.currentRowChanged.connect(self._show_instrument)
        il.addWidget(self.instruments, 2)
        row = QHBoxLayout()
        for text, slot in (("Genera con glitchLAB…", self._generate), ("Dalla libreria…", self._from_library),
                           ("Da file…", self._from_files), ("Rimuovi", self._remove_instrument)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        il.addLayout(row)
        self.ins_name = QLineEdit()
        self.ins_desc = QLineEdit()
        self.ins_desc.setPlaceholderText("ruolo nel pezzo, cosa deve fare (lo legge l'IA)")
        f = QFormLayout()
        f.addRow("nome", self.ins_name)
        f.addRow("descrizione", self.ins_desc)
        il.addLayout(f)
        for wdg in (self.ins_name, self.ins_desc):
            wdg.editingFinished.connect(self._instrument_fields)
        self.samples = QListWidget()
        self.samples.itemDoubleClicked.connect(self._play)
        self.samples.setToolTip("doppio clic per ascoltare")
        il.addWidget(self.samples, 2)
        self.gen_status = QLabel()
        self.gen_status.setStyleSheet("color:#d6a13a")
        il.addWidget(self.gen_status)
        rl.addWidget(ibox, 3)

        pbox = QGroupBox("Effetti — tavolozza che l'IA può usare")
        pl = QVBoxLayout(pbox)
        self.palette = QListWidget()
        for m in catalog.by_category("effect"):
            it = QListWidgetItem(f"{m.name} — {m.doc}" if m.doc else m.name)
            it.setData(Qt.UserRole, m.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.palette.addItem(it)
        self.palette.itemChanged.connect(self._palette)
        pl.addWidget(self.palette)
        pl.addWidget(QLabel("<span style='color:#9aa0a6'>Sorgenti (sample_player, bank, scrub) e mix "
                            "sono sempre disponibili.</span>"))
        rl.addWidget(pbox, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([800, 600])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(split)

    # -- sync from model ------------------------------------------------------------------
    def load(self, project):
        self._loading = True
        try:
            self.title.setText(project.title)
            self.tempo.setValue(project.tempo)
            self.seed.setValue(project.seed)
            self.duration.setText(f"{project.duration_seconds:g} s")
            self.strip.set_sections(project.sections)
            self.table.setRowCount(len(project.sections))
            for r, s in enumerate(project.sections):
                for c, v in enumerate((s.name, f"{s.end - s.start:g}", f"{s.energy:.2f}", f"{s.density:.2f}",
                                       s.intent)):
                    it = QTableWidgetItem(v)
                    it.setData(Qt.UserRole, s.id)
                    self.table.setItem(r, c, it)
            self.table.resizeRowsToContents()
            if self.notes.toPlainText() != project.brief.notes:
                self.notes.setPlainText(project.brief.notes)
            current = self.instruments.currentRow()
            self.instruments.clear()
            for ins in project.brief.instruments:
                src = ins.source
                how = f"{src.get('character')}/{src.get('length')}" if src.get("type") == "glitchlab" \
                    else src.get("type", "")
                it = QListWidgetItem(f"{ins.name}  ·  {len(ins.assets)} campioni  ·  {how}")
                it.setData(Qt.UserRole, ins.id)
                self.instruments.addItem(it)
            self.instruments.setCurrentRow(min(max(current, 0), self.instruments.count() - 1))
            self._show_instrument(self.instruments.currentRow())
            for k in range(self.palette.count()):
                it = self.palette.item(k)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in project.brief.palette else Qt.Unchecked)
        finally:
            self._loading = False

    # -- edits ------------------------------------------------------------------------------
    def _apply_if(self, changed, label, fn):
        if changed and not self._loading:
            self.w.apply(label, fn)

    def _cell(self, r, c):
        if self._loading:
            return
        it = self.table.item(r, c)
        sid, text = it.data(Qt.UserRole), it.text()
        field = ("name", "duration", "energy", "density", "intent")[c]
        try:
            value = text if field in ("name", "intent") else float(text.replace(",", "."))
        except ValueError:
            self.w.statusBar().showMessage(f"✗ {field}: numero non valido", 5000)
            return self.load(self.w.project)
        if not self.w.apply(f"sezione {field}", lambda p: edit.update_section(p, sid, **{field: value})):
            self.load(self.w.project)

    def _selected_section(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 and self.table.item(r, 0) else None

    def _add_section(self):
        n = len(self.w.project.sections) + 1
        self.w.apply("nuova sezione", lambda p: edit.add_section(p, f"Sezione {n}", 30.0))

    def _move(self, delta):
        sid = self._selected_section()
        if sid:
            row = self.table.currentRow()
            self.w.apply("sposta sezione", lambda p: edit.move_section(p, sid, delta))
            self.table.setCurrentCell(max(0, min(row + delta, self.table.rowCount() - 1)), 0)

    def _remove_section(self):
        sid = self._selected_section()
        if sid:
            self.w.apply("elimina sezione", lambda p: edit.remove_section(p, sid))

    def _palette(self, item):
        if self._loading:
            return
        chosen = [self.palette.item(k).data(Qt.UserRole) for k in range(self.palette.count())
                  if self.palette.item(k).checkState() == Qt.Checked]
        self.w.apply("tavolozza", lambda p: edit.set_palette(p, chosen))

    # -- instruments --------------------------------------------------------------------------
    def _current_instrument(self):
        it = self.instruments.currentItem()
        return self.w.project.instrument(it.data(Qt.UserRole)) if it else None

    def _show_instrument(self, row):
        ins = self._current_instrument()
        self.samples.clear()
        self.ins_name.setText(ins.name if ins else "")
        self.ins_desc.setText(ins.description if ins else "")
        if not ins:
            return
        assets = {a.id: a for a in self.w.project.assets}
        for aid in ins.assets:
            a = assets.get(aid)
            d = a.provenance.get("descriptors", {}) if a else {}
            text = f"▶ {aid}"
            if d:
                text += f"   {d.get('duration', 0):.2f}s · {d.get('centroid', 0):.0f} Hz · rms {d.get('rms', 0)} dB"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, aid)
            self.samples.addItem(it)

    def _instrument_fields(self):
        ins = self._current_instrument()
        if ins and (self.ins_name.text() != ins.name or self.ins_desc.text() != ins.description):
            iid, name, desc = ins.id, self.ins_name.text(), self.ins_desc.text()
            self.w.apply("strumento", lambda p: edit.update_instrument(p, iid, name, desc))

    def _remove_instrument(self):
        ins = self._current_instrument()
        if ins:
            iid = ins.id
            self.w.apply("rimuovi strumento", lambda p: edit.remove_instrument(p, iid))

    def _play(self, item):
        a = next((x for x in self.w.project.assets if x.id == item.data(Qt.UserRole)), None)
        exe = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
        if not a or not exe:
            return
        if self.player:
            self.player.kill()
        self.player = QProcess(self)
        self.player.start(exe, [str(self.w.project.asset_path(a))])

    def _generate(self):
        if self._thread:
            return self.w.statusBar().showMessage("glitchLAB sta già generando…", 4000)
        dlg = GenerateDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        self.gen_status.setText(f"glitchLAB genera {v['count']} × {v['character']}/{v['length']}…")
        self._thread = QThread(self)
        self._worker = _Worker(self.glitchlab, v)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(lambda metas, err: self._generated(v, metas, err))
        self._thread.start()

    def _generated(self, v, metas, err):
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.gen_status.setText("")
        if err or not metas:
            self.w.statusBar().showMessage(f"✗ glitchLAB: {err or 'nessun campione'}", 8000)
            return
        folder = self.w.project.path.parent

        def fn(p):
            assets = [self.glitchlab.import_asset(m["id"], project_dir=folder) for m in metas]
            edit.add_instrument(p, v["name"], assets, v["description"], {
                "type": "glitchlab", **{k: v[k] for k in ("character", "length", "density", "energy", "count")}})
        if self.w.apply("genera strumento", fn):
            self.instruments.setCurrentRow(self.instruments.count() - 1)

    def _from_library(self):
        dlg = LibraryDialog(self, self.glitchlab)
        if dlg.exec() != QDialog.Accepted:
            return
        name, desc, ids = dlg.values()
        if not ids:
            return
        folder = self.w.project.path.parent

        def fn(p):
            assets = [self.glitchlab.import_asset(i, project_dir=folder) for i in ids]
            edit.add_instrument(p, name, assets, desc, {"type": "glitchlab-libreria"})
        if self.w.apply("strumento dalla libreria", fn):
            self.instruments.setCurrentRow(self.instruments.count() - 1)

    def _from_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Campioni", str(Path.home()), "Audio (*.wav)")
        if not files:
            return
        folder = self.w.project.path.parent
        name = Path(files[0]).parent.name or "File"

        def fn(p):
            assets = []
            for f in files:
                aid = edit.new_id(p, f"asset-{Path(f).stem}")
                a = Asset(aid, str(Path(f).resolve().relative_to(folder)) if Path(f).resolve().is_relative_to(folder)
                          else str(Path(f).resolve()), sha256_file(f), {"source": "file", "file": Path(f).name})
                p.assets.append(a)
                assets.append(a)
            edit.add_instrument(p, name, assets, "", {"type": "file"})
        if self.w.apply("strumento da file", fn):
            self.instruments.setCurrentRow(self.instruments.count() - 1)
