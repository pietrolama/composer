"""Main window: browser | canvas | inspector, problems below, build actions on top.

python -m composer.ui [project.json]
"""

import random
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPointF, QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QUndoCommand, QUndoStack
from shiboken6 import isValid
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QTreeWidget, QTreeWidgetItem,
                               QSplitter, QTabWidget, QWidget, QVBoxLayout, QInputDialog, QLabel)

from .. import catalog, compose, edit, model, pdrun, rules
from ..compiler import CompileError, compile_project
from ..integrations.glitchlab import GlitchLabAdapter, GlitchLabUnavailable
from ..validate import validate
from .canvas import CanvasScene, CanvasView
from .brief import BriefEditor, FormStrip
from .inspector import Inspector


class Snapshot(QUndoCommand):
    """Undo by whole-model snapshots: projects are small, and it can never drift."""

    def __init__(self, window, label, before, after):
        super().__init__(label)
        self.window, self.before, self.after = window, before, after
        self._first = True

    def redo(self):
        if self._first:
            self._first = False
            return
        self.window.restore(self.after)

    def undo(self):
        self.window.restore(self.before)


class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.project = None
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(lambda _: self._title())
        self.pd = None
        self.glitchlab = GlitchLabAdapter()

        self.scene = CanvasScene()
        self.view = CanvasView(self.scene)
        self.brief = BriefEditor(self)
        comp = QWidget()
        cl = QVBoxLayout(comp)
        cl.setContentsMargins(0, 0, 0, 0)
        self.comp_info = QLabel()
        self.comp_info.setStyleSheet("padding:6px 10px; color:#c9d1d9; background:#24272c")
        self.comp_strip = FormStrip(compact=True)
        self.comp_strip.section_clicked.connect(self._on_section_clicked)
        cl.addWidget(self.comp_info)
        cl.addWidget(self.comp_strip)
        cl.addWidget(self.view, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.brief, "Brief")
        self.tabs.addTab(comp, "Composizione")
        self.tabs.currentChanged.connect(self._tab)
        self.setCentralWidget(self.tabs)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._changed_on_disk)
        self._own_write = False
        self.scene.selectionChanged.connect(self._selection)
        self.scene.moved.connect(self._moved)
        self.scene.connect_requested.connect(
            lambda s, t: self.apply("collega", lambda p: edit.connect(p, s, t)))
        self.scene.delete_requested.connect(self._delete)
        self.scene.add_requested.connect(self._add)
        self.scene.rule_requested.connect(self._new_rule)
        self.scene.part_requested.connect(
            lambda n, pid: self.apply("cambia parte", lambda p: edit.set_node_part(p, n, pid)))

        self.inspector = Inspector()
        self.inspector.param_changed.connect(
            lambda n, k, v: self.apply(f"{k}", lambda p: edit.set_param(p, n, k, v), keep=[n]))
        self.inspector.node_part_changed.connect(
            lambda n, pid: self.apply("cambia parte", lambda p: edit.set_node_part(p, n, pid), keep=[n]))
        self.inspector.part_changed.connect(
            lambda pid, f: self.apply("modifica parte", lambda p: edit.update_part(p, pid, **f), keep=[pid]))
        self.inspector.rule_changed.connect(
            lambda rid, f: self.apply("modifica regola", lambda p: edit.update_rule(p, rid, **f), keep=[rid]))
        self.inspector.seed_changed.connect(
            lambda v: self.apply("seed", lambda p: edit.set_seed(p, v), keep=[]))
        right = self._dock("Inspector", self.inspector, Qt.RightDockWidgetArea)

        self.browser = QTreeWidget()
        self.browser.setHeaderHidden(True)
        self.browser.itemDoubleClicked.connect(self._browser_activate)
        left = self._dock("Browser", self.browser, Qt.LeftDockWidgetArea)

        self.problems = QListWidget()
        self.problems.itemClicked.connect(lambda it: self.select(it.data(Qt.UserRole)))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        split = QSplitter()
        split.addWidget(self.problems)
        split.addWidget(self.log)
        split.setSizes([500, 500])
        bottom = self._dock("Problemi · Log", split, Qt.BottomDockWidgetArea)
        self.resizeDocks([left, right], [280, 320], Qt.Horizontal)
        self.resizeDocks([bottom], [150], Qt.Vertical)

        self._actions()
        self.resize(1500, 920)
        self._restore_settings()
        if path:
            self.open(path)
        else:
            self.statusBar().showMessage("Apri un progetto (Ctrl+O)")

    def _restore_settings(self):
        s = QSettings("Composer", "Composer")
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        state = s.value("windowState")
        if state:
            self.restoreState(state)

    def _save_settings(self):
        s = QSettings("Composer", "Composer")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())

    # -- setup ---------------------------------------------------------------------
    def _dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(area, dock)
        return dock

    def _actions(self):
        bar = self.addToolBar("Progetto")
        bar.setObjectName("toolbar")
        bar.setMovable(False)

        def act(text, slot, key=None, tip=""):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.setToolTip(tip or text)
            a.triggered.connect(slot)
            bar.addAction(a)
            return a

        act("Nuovo", self._new_project, QKeySequence.New, "Nuovo progetto: si parte dal brief")
        act("Apri", self._open_dialog, QKeySequence.Open)
        act("Salva", self.save, QKeySequence.Save)
        bar.addSeparator()
        u = self.undo.createUndoAction(self, "Annulla")
        u.setShortcut(QKeySequence.Undo)
        r = self.undo.createRedoAction(self, "Ripeti")
        r.setShortcut(QKeySequence.Redo)
        bar.addAction(u)
        bar.addAction(r)
        bar.addSeparator()
        act("Nuova parte", self._new_part, tip="Aggiunge una parte vuota")
        act("Duplica", self._duplicate, "Ctrl+D", "Duplica i nodi selezionati con i cavi tra loro")
        act("Adatta vista", lambda: self.view.fit(), "F")
        bar.addSeparator()
        act("Prepara brief per Claude", self.prepare_brief, "Ctrl+Shift+B",
            "Salva e scrive brief.md: poi chiedi a Claude Code di comporre")
        act("Ricomponi", self.recompose, "Ctrl+Shift+R",
            "Riesegue l'ultimo composition.py con il seed corrente: una variante senza passare dall'IA")
        act("Accetta", lambda: self.verdict("accettata"), tip="Accetta la versione corrente")
        act("Rifiuta…", lambda: self.verdict("rifiutata"), tip="Rifiuta con un commento: lo legge la prossima versione")
        bar.addSeparator()
        act("Genera patch", self.build, "Ctrl+B", "Compila il progetto in build/<id>")
        act("Verifica in Pd", self.check, tip="Carica main.pd in Pd headless")
        act("Render", self.render, "Ctrl+R", "Render offline in build/<id>/render.wav")
        self.play_action = act("▶ Ascolta", self.toggle_play, "Space", "Compila e apre main.pd con pw-jack pd -jack")

    # -- model plumbing ---------------------------------------------------------------
    def apply(self, label, fn, keep=None):
        """Run an edit on the model as one undoable step."""
        if self.project is None:
            return False
        before = self.project.to_dict()
        try:
            fn(self.project)
        except edit.EditError as exc:
            self.restore(before, keep=keep)
            self.statusBar().showMessage(f"✗ {exc}", 6000)
            return False
        after = self.project.to_dict()
        if after != before:
            self.undo.push(Snapshot(self, label, before, after))
            self.refresh(keep)
        return True

    def restore(self, data, keep=None):
        self.project = model.from_dict(data, self.project.path)
        self.refresh(keep)

    def refresh(self, keep=None):
        selected = keep if keep is not None else self.scene.selected_ids()
        issues = validate(self.project)
        self.expansions = {}
        broken = {i.element for i in issues if i.level == "error"}
        for r in self.project.rules:
            if r.id not in broken:
                try:
                    self.expansions[r.id] = rules.expand(self.project, r)
                except (OSError, ValueError) as exc:
                    self._say(f"regola {r.id}: {exc}")
        counts = {rid: len(e.events) for rid, e in self.expansions.items()}
        self.scene.blockSignals(True)
        self.scene.rebuild(self.project, issues, selected, counts)
        self.scene.blockSignals(False)
        self._selection()
        self._problems(issues)
        self._browser()
        self.brief.load(self.project)
        if hasattr(self, "comp_strip"):
            self.comp_strip.set_sections(self.project.sections)
        self._comp_info()
        self._title()

    def _title(self):
        if not isValid(self.undo):  # cleanChanged can fire during teardown
            return
        if self.project:
            dirty = "" if self.undo.isClean() else " •"
            self.setWindowTitle(f"Composer — {self.project.title}{dirty}  ({self.project.path})")

    def _problems(self, issues):
        self.problems.clear()
        for i in issues:
            it = QListWidgetItem(f"{'✗' if i.level == 'error' else '!'}  {i.element}: {i.message}")
            it.setForeground(QColor("#e5534b" if i.level == "error" else "#d6a13a"))
            it.setData(Qt.UserRole, i.element)
            self.problems.addItem(it)
        if not issues:
            self.problems.addItem("✓ nessun problema")
        errors = sum(i.level == "error" for i in issues)
        self.statusBar().showMessage(f"{len(self.project.nodes)} nodi · {len(self.project.connections)} cavi · "
                                     f"{errors} errori · {len(issues) - errors} avvisi")

    def _browser(self):
        self.browser.clear()
        mods = QTreeWidgetItem(self.browser, ["Moduli"])
        for name, mod in catalog.MODULES.items():
            it = QTreeWidgetItem(mods, [name])
            it.setToolTip(0, mod.doc or name)
            it.setData(0, Qt.UserRole, ("module", name))
        parts = QTreeWidgetItem(self.browser, ["Parti"])
        for p in self.project.parts:
            it = QTreeWidgetItem(parts, [f"{p.name}  ({len(self.project.part_nodes(p.id))})"])
            it.setData(0, Qt.UserRole, ("select", p.id))
        rl = QTreeWidgetItem(self.browser, ["Regole"])
        for r in self.project.rules:
            n = len(self.expansions[r.id].events) if r.id in self.expansions else "✗"
            it = QTreeWidgetItem(rl, [f"{r.source} → {r.target}  ({n})"])
            it.setToolTip(0, f"{r.id}: {r.when} → {r.effect}")
            it.setData(0, Qt.UserRole, ("select_rule", r.id))
        assets = QTreeWidgetItem(self.browser, ["Campioni del progetto"])
        for a in self.project.assets:
            prov = a.provenance
            it = QTreeWidgetItem(assets, [a.id])
            it.setToolTip(0, f"{a.path}\n{prov.get('source', '')} {prov.get('glitchlab_id', '')} "
                             f"{prov.get('character', '')}")
        gl = QTreeWidgetItem(self.browser, ["glitchLAB (doppio clic per importare)"])
        try:
            have = {a.provenance.get("glitchlab_id") for a in self.project.assets}
            for m in sorted(self.glitchlab.list_assets(), key=lambda m: (m["character"], -m["descriptors"]["duration"])):
                d = m["descriptors"]
                it = QTreeWidgetItem(gl, [f"{'★ ' if m['kept'] else ''}{m['character']} · {d['duration']:.2f}s · {m['id']}"])
                it.setToolTip(0, f"centroide {d['centroid']:.0f} Hz · transienti/s {d['transients']} · rms {d['rms']} dB")
                it.setData(0, Qt.UserRole, ("glitchlab", m["id"]))
                if m["id"] in have:
                    it.setForeground(0, QColor("#6f9f5a"))
        except GlitchLabUnavailable as exc:
            QTreeWidgetItem(gl, [str(exc)])
        for top in (mods, parts, rl, assets):
            top.setExpanded(True)

    def _browser_activate(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "module":
            centre = self.view.mapToScene(self.view.viewport().rect().center())
            part = next((i for i in self.scene.selected_ids() if i in self.scene.frames), None)
            self._add(value, centre, part)
        elif kind == "select":
            self.select(value)
        elif kind == "select_rule":
            item = self.scene.item_for(value)
            if item:
                self.select(value)
            else:  # rule driven by a section: no arrow on the canvas
                self.scene.clearSelection()
                rule = next(r for r in self.project.rules if r.id == value)
                self.inspector.show_rule(self.project, rule, self.expansions.get(value))
        elif kind == "glitchlab":
            def imp(p):
                asset = self.glitchlab.import_asset(value, project_dir=p.path.parent)
                if any(a.id == asset.id for a in p.assets):
                    raise edit.EditError(f"già nel progetto: {asset.id}")
                p.assets.append(asset)
            if self.apply("importa campione", imp):
                self.statusBar().showMessage(f"importato {value}", 4000)

    def select(self, element_id):
        self.tabs.setCurrentIndex(1)
        self.scene.clearSelection()
        item = self.scene.item_for(element_id)
        if item:
            item.setSelected(True)
            self.view.ensureVisible(item, 80, 80)
            self.view.centerOn(item)

    def _selection(self):
        if not isValid(self.scene):  # selectionChanged can fire during teardown
            return
        ids = self.scene.selected_ids()
        objs = self.project.by_id() if self.project else {}
        if len(ids) == 1 and ids[0] in objs:
            obj = objs[ids[0]]
            if isinstance(obj, model.Node):
                return self.inspector.show_node(self.project, obj)
            if isinstance(obj, model.Part):
                return self.inspector.show_part(self.project, obj)
            if isinstance(obj, model.Connection):
                return self.inspector.show_connection(obj)
            if isinstance(obj, model.Rule):
                return self.inspector.show_rule(self.project, obj, self.expansions.get(obj.id))
        self.inspector.show_none(len(ids), self.project,
                                 {rid: len(e.events) for rid, e in getattr(self, "expansions", {}).items()})

    # -- gestures --------------------------------------------------------------------
    def _moved(self, moved):
        def fn(p):
            for nid, (x, y) in moved.items():
                edit.move_node(p, nid, x, y)
        self.apply("sposta", fn)

    def _delete(self, ids):
        def fn(p):
            for el in ids:
                if any(n.id == el for n in p.nodes):
                    edit.remove_node(p, el)
                elif any(c.id == el for c in p.connections):
                    edit.disconnect(p, el)
                elif any(x.id == el for x in p.parts):
                    edit.remove_part(p, el)
                elif any(r.id == el for r in p.rules):
                    edit.remove_rule(p, el)
        self.apply("elimina", fn, keep=[])

    def _add(self, module, pos, part_id):
        holder = {}
        ok = self.apply(f"aggiungi {module}",
                        lambda p: holder.setdefault("n", edit.add_node(p, module, part_id, (pos.x(), pos.y()))))
        if ok:
            self.select(holder["n"].id)

    def _duplicate(self):
        ids = [i for i in self.scene.selected_ids() if i in self.scene.nodes]
        holder = {}
        if ids and self.apply("duplica", lambda p: holder.update(edit.duplicate_nodes(p, ids))):
            self.scene.clearSelection()
            for n in holder.values():
                self.scene.nodes[n.id].setSelected(True)

    def _new_rule(self, source, target):
        holder = {}
        if self.apply("nuova regola", lambda p: holder.setdefault("r", edit.add_rule(p, source, target))):
            self.select(holder["r"].id)

    def _new_part(self):
        holder = {}
        if self.apply("nuova parte", lambda p: holder.setdefault("p", edit.add_part(p, "Nuova parte"))):
            self.select(holder["p"].id)

    # -- files -------------------------------------------------------------------------
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri progetto", str(Path.cwd()), "Composer (*.json)")
        if path:
            self.open(path)

    def open(self, path):
        try:
            self.project = model.load(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Composer", f"Impossibile aprire {path}:\n{exc}")
            return
        self.undo.clear()
        self.refresh([])
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        self.watcher.addPath(str(self.project.path))
        self.tabs.setCurrentIndex(1 if self.project.nodes else 0)
        QTimer.singleShot(0, self.view.fit)

    def save(self):
        if self.project:
            self._own_write = True
            self.project.save()
            QTimer.singleShot(300, lambda: setattr(self, "_own_write", False))
            self.undo.setClean()
            self.statusBar().showMessage(f"salvato {self.project.path}", 4000)

    def closeEvent(self, e):
        if self.project and not self.undo.isClean():
            ans = QMessageBox.question(self, "Composer", "Salvare le modifiche?",
                                       QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                return e.ignore()
            if ans == QMessageBox.Save:
                self.save()
        self._stop_pd()
        self._save_settings()
        e.accept()

    def _new_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Nuovo progetto (cartella del pezzo)",
                                              str(Path.home() / "projects" / "composer" / "pieces" / "nuovo"
                                                  / "composer.project.json"), "Composer (*.json)")
        if not path:
            return
        title, ok = QInputDialog.getText(self, "Nuovo progetto", "Titolo del pezzo:")
        if not ok:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        p = model.Project(id=Path(path).parent.name, title=title.strip() or "Senza titolo",
                          duration_seconds=0, tempo=100, seed=random.randrange(1, 1_000_000))
        p.path = Path(path)
        edit.add_section(p, "Apertura", 30.0, "", 0.3, 0.3)
        p.brief.palette = [m.name for m in catalog.by_category("effect")]
        p.save()
        self.open(path)
        self.tabs.setCurrentIndex(0)

    def prepare_brief(self):
        if not self.project:
            return
        self.save()
        text = compose.brief_markdown(self.project)
        out = self.project.path.parent / "brief.md"
        out.write_text(text)
        QApplication.clipboard().setText(f"Componi il brief in {out}")
        self._say(f"brief → {out}")
        QMessageBox.information(self, "Composer", f"Brief salvato in\n{out}\n\nScrivi a Claude Code: «componi»"
                                " (la richiesta è già negli appunti). La nuova versione comparirà qui da sola.")

    def recompose(self):
        if not self.project or not (self.project.path.parent / "composition.py").exists():
            return self.statusBar().showMessage("nessun composition.py: prima chiedi a Claude Code di comporre", 5000)
        self.save()
        self._own_write = True
        try:
            version, issues = compose.run(self.project)
        except Exception as exc:  # the script is code: report, never crash the app
            self._say(f"ricomposizione fallita: {exc}")
            return
        finally:
            QTimer.singleShot(300, lambda: setattr(self, "_own_write", False))
        self.undo.clear()
        self.undo.setClean()
        self.refresh([])
        self.tabs.setCurrentIndex(1)
        self._say(f"v{version} ricomposta con seed {self.project.seed}")
        self.build()

    def verdict(self, status):
        if not self.project or not self.project.composition_meta.get("version"):
            return self.statusBar().showMessage("nessuna versione composta da valutare", 4000)
        feedback = ""
        if status == "rifiutata":
            feedback, ok = QInputDialog.getMultiLineText(self, "Rifiuta", "Cosa non va? (lo legge la prossima versione)")
            if not ok:
                return
        self.apply(status, lambda p: compose.set_status(p, status, feedback))
        self.save()

    def _on_section_clicked(self, section):
        if not section:
            return
        intent = f" — «{section.intent}»" if section.intent else ""
        self.statusBar().showMessage(f"Sezione: {section.name} [{section.start:g}s - {section.end:g}s] · "
                                     f"energia {section.energy:g} · densità {section.density:g}{intent}", 5000)

    def _comp_info(self):
        m = self.project.composition_meta
        if m.get("version"):
            fb = f" — «{m['feedback']}»" if m.get("feedback") else ""
            self.comp_info.setText(f"Versione v{m['version']} · {m.get('author', '')} · {m.get('created', '')} · "
                                   f"seed {m.get('seed', '')} · <b>{m.get('status', 'proposta')}</b>{fb}")
        elif self.project.nodes:
            self.comp_info.setText("Composizione scritta a mano (nessuna versione dell'IA)")
        else:
            self.comp_info.setText("Nessuna composizione: prepara il brief e chiedi a Claude Code di comporre.")

    def _tab(self, index):
        for dock in self.findChildren(QDockWidget):
            if dock.objectName() in ("Inspector", "Browser"):
                dock.setVisible(index == 1)

    def _changed_on_disk(self, path):
        if self._own_write or not Path(path).exists():
            QTimer.singleShot(200, lambda: self.watcher.addPath(path) if Path(path).exists() else None)
            return
        if not self.undo.isClean():
            ans = QMessageBox.question(self, "Composer", "Il progetto è cambiato su disco (nuova versione?). "
                                       "Ricaricare e perdere le modifiche non salvate?")
            if ans != QMessageBox.Yes:
                return
        self.open(path)
        self.tabs.setCurrentIndex(1)
        self._say(f"ricaricato: v{self.project.composition_meta.get('version', '?')}")

    # -- build -------------------------------------------------------------------------
    def out_dir(self):
        return self.project.path.parent / "build" / self.project.id

    def _say(self, text):
        self.log.appendPlainText(text)

    def build(self):
        if not self.project:
            return False
        try:
            res = compile_project(self.project, self.out_dir())
        except CompileError as exc:
            self._say(str(exc))
            self.statusBar().showMessage("✗ compilazione interrotta: vedi Problemi", 6000)
            return False
        self._say(f"→ {res['out']}\n  " + ("\n  ".join(res["changed"]) or "(nessun file cambiato)"))
        return True

    def check(self):
        if self.build():
            res = pdrun.check(self.out_dir())
            self._say(f"Pd {res['pd']}: " + ("caricamento ok" if res["ok"] else "problemi"))
            for line in res["problems"]:
                self._say(f"  {line}")

    def render(self):
        if self.build():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                res = pdrun.render(self.out_dir(), self.out_dir() / "render.wav")
            finally:
                QApplication.restoreOverrideCursor()
            self._say(("→ " if res["ok"] else "✗ ") + res["wav"])
            for line in res["problems"]:
                self._say(f"  {line}")

    def toggle_play(self):
        if self.pd:
            return self._stop_pd()
        if not self.build():
            return
        cmd = ["pd", "-jack", str(self.out_dir() / "patches" / "main.pd")]
        if shutil.which("pw-jack"):
            cmd = ["pw-jack"] + cmd
        self.pd = QProcess(self)
        self.pd.setProcessChannelMode(QProcess.MergedChannels)
        self.pd.readyRead.connect(lambda: self._say(bytes(self.pd.readAll()).decode(errors="replace").rstrip()))
        self.pd.finished.connect(self._pd_finished)
        self.pd.start(cmd[0], cmd[1:])
        self.play_action.setText("■ Ferma")
        self._say("$ " + " ".join(cmd))

    def _stop_pd(self):
        if self.pd:
            self.pd.terminate()
            if not self.pd.waitForFinished(2000):
                self.pd.kill()

    def _pd_finished(self, *_):
        self.pd = None
        self.play_action.setText("▶ Ascolta")


def dark(app):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, c in ((QPalette.Window, "#202328"), (QPalette.WindowText, "#e6e6e6"),
                    (QPalette.Base, "#181a1e"), (QPalette.AlternateBase, "#22252a"),
                    (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#2a2e34"),
                    (QPalette.ButtonText, "#e6e6e6"), (QPalette.Highlight, "#3f5f8a"),
                    (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#2a2e34"),
                    (QPalette.ToolTipText, "#e6e6e6"), (QPalette.PlaceholderText, "#7d8590")):
        pal.setColor(role, QColor(c))
    app.setPalette(pal)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Composer")
    dark(app)
    win = MainWindow(argv[1] if len(argv) > 1 else None)
    win.show()
    return app.exec()
