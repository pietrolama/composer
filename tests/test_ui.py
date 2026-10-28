import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPointF  # noqa: E402

from composer import model  # noqa: E402
from composer.ui.app import MainWindow  # noqa: E402

DEMO = Path(__file__).parent.parent / "examples" / "fracture-study" / "composer.project.json"


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, tmp_path):
    proj = model.load(DEMO)
    for a in proj.assets:  # keep asset paths valid from the copy
        a.path = str(proj.asset_path(a))
    proj.save(tmp_path / "composer.project.json")
    w = MainWindow(str(tmp_path / "composer.project.json"))
    yield w
    w.undo.setClean()
    w.close()


def test_opens_demo(win):
    assert set(win.scene.nodes) == {n.id for n in win.project.nodes}
    assert len(win.scene.cables) == len(win.project.connections) and set(win.scene.frames) == {p.id for p in win.project.parts}


def test_add_connect_undo_redo(win):
    win._add("lowpass", QPointF(100, 700), "part-impulses")
    new = next(n for n in win.project.nodes if n.type == "lowpass" and n.part_id == "part-impulses")
    assert win.scene.selected_ids() == [new.id]
    win.scene.connect_requested.emit("node-impulses-player.audio_out", f"{new.id}.audio_in")
    assert any(c.target == f"{new.id}.audio_in" for c in win.project.connections)
    win.undo.undo()
    assert not any(c.target == f"{new.id}.audio_in" for c in win.project.connections)
    win.undo.undo()
    assert new.id not in {n.id for n in win.project.nodes}
    win.undo.redo()
    win.undo.redo()
    assert any(c.target == f"{new.id}.audio_in" for c in win.project.connections)
    assert new.id in win.scene.nodes


def test_invalid_cable_is_refused(win):
    before = win.project.to_dict()
    win.scene.connect_requested.emit("node-out.audio_in", "node-master.audio_in")  # in -> in
    win.scene.connect_requested.emit("node-master.audio_out", "node-texture-player.control")
    win.scene.connect_requested.emit("node-master.audio_out", "node-texture-filter.audio_in")  # cycle
    assert win.project.to_dict() == before
    assert win.undo.count() == 0
    assert "ciclo" in win.statusBar().currentMessage()


def test_param_move_delete(win):
    win.inspector.param_changed.emit("node-texture-filter", "cutoff_hz", 1200.0)
    assert next(n for n in win.project.nodes if n.id == "node-texture-filter").params["cutoff_hz"] == 1200.0
    win.inspector.param_changed.emit("node-texture-filter", "cutoff_hz", 99999.0)  # out of range
    assert next(n for n in win.project.nodes if n.id == "node-texture-filter").params["cutoff_hz"] == 1200.0
    win.scene.moved.emit({"node-out": (900.0, 40.0)})
    assert win.project.presentation["nodes"]["node-out"] == {"x": 900, "y": 40}
    win.scene.delete_requested.emit(["node-master"])
    assert not any("node-master" in c.source + c.target for c in win.project.connections)
    win.undo.undo()
    assert any(n.id == "node-master" for n in win.project.nodes)
    assert len(win.project.connections) == len(model.load(DEMO).connections)


def test_part_edit_and_save_compile(win):
    win.inspector.part_changed.emit("part-impulses", {"section_ids": ["sec-fracture", "sec-residue"], "name": "Impulsi B"})
    part = next(p for p in win.project.parts if p.id == "part-impulses")
    assert part.name == "Impulsi B" and part.section_ids == ["sec-fracture", "sec-residue"]
    win.save()
    assert win.undo.isClean()
    assert model.load(win.project.path).to_dict() == win.project.to_dict()
    assert win.build()
    score = (win.out_dir() / "patches" / "score.txt").read_text()
    assert "c-part-impulses stop" in score


def test_duplicate_keeps_internal_cables(win):
    win.select("node-texture-player")
    win.scene.nodes["node-texture-filter"].setSelected(True)
    win._duplicate()
    original = {n.id for n in model.load(DEMO).nodes}
    new = [n for n in win.project.nodes if n.id not in original]
    assert len(new) == 2
    ids = {n.id for n in new}
    inner = [c for c in win.project.connections if c.source.split(".")[0] in ids and c.target.split(".")[0] in ids]
    assert inner == []  # player and filter are not directly cabled any more (fragment in between)
    win.scene.clearSelection()
    for nid in ("node-texture-player", "node-texture-fragment"):
        win.scene.nodes[nid].setSelected(True)
    win._duplicate()
    newer = {n.id for n in win.project.nodes} - original - ids
    assert len(newer) == 2 and len([c for c in win.project.connections
                                    if c.source.split(".")[0] in newer and c.target.split(".")[0] in newer]) == 1
    assert set(win.scene.selected_ids()) == newer


def test_mouse_drag_between_ports_creates_cable(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win.resize(1400, 900)
    win.show()
    win.scene.connect_requested.emit("node-impulses-player.audio_out", "node-texture-filter.audio_in")
    win.undo.undo()  # start from the original graph, but with the window laid out
    win.view.fit()
    QtWidgets.QApplication.processEvents()
    src = next(p for p in win.scene.nodes["node-fracture-player"].ports() if p.port.direction == "out")
    dst = next(p for p in win.scene.nodes["node-texture-filter"].ports() if p.port.direction == "in")
    a, b = win.view.mapFromScene(src.scenePos()), win.view.mapFromScene(dst.scenePos())
    vp = win.view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(vp, (a + b) / 2)
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)
    assert any(c.source == "node-fracture-player.audio_out" and c.target == "node-texture-filter.audio_in"
               for c in win.project.connections)


def test_mouse_drag_moves_node_as_one_undo_step(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    win.resize(1400, 900)
    win.show()
    win.view.fit()
    QtWidgets.QApplication.processEvents()
    item = win.scene.nodes["node-out"]
    start = win.view.mapFromScene(item.scenePos() + QPointF(60, 12))
    vp = win.view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
    for k in range(1, 6):
        QTest.mouseMove(vp, start + QPoint(10 * k, 8 * k))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(50, 40))
    assert "node-out" in win.project.presentation["nodes"]
    assert win.undo.count() == 1 and win.undo.undoText() == "sposta"


def test_rules_on_canvas_and_inspector(win):
    assert [r.element_id for r in win.scene.rules] == ["rule-001"]
    n0 = len(win.expansions["rule-001"].events)
    assert n0 > 0
    win.inspector.rule_changed.emit("rule-001", {"params": {"probability": 1.0}})
    assert len(win.expansions["rule-001"].events) > n0
    win.inspector.rule_changed.emit("rule-001", {"params": {"probability": 5.0}})  # refused
    assert win.project.rules[0].params["probability"] == 1.0


def test_seed_changes_variant_and_undoes(win):
    events = list(win.expansions["rule-001"].events)
    win.inspector.seed_changed.emit(win.project.seed + 1)
    assert win.expansions["rule-001"].events != events
    win.undo.undo()
    assert win.expansions["rule-001"].events == events


def test_new_rule_from_part_menu_and_delete(win):
    win.scene.rule_requested.emit("part-fracture", "part-texture")
    new = [r for r in win.project.rules if r.id != "rule-001"]
    assert len(new) == 1 and new[0].source == "part-fracture"
    assert win.scene.selected_ids() == [new[0].id]
    win.scene.rule_requested.emit("part-fracture", "part-impulses")  # no fragment there
    assert len(win.project.rules) == 2
    assert "fragment" in win.statusBar().currentMessage()
    win.scene.delete_requested.emit([new[0].id])
    assert [r.id for r in win.project.rules] == ["rule-001"]


def test_composition_strip_sync_and_selection(win):
    assert hasattr(win, "comp_strip")
    assert len(win.comp_strip.sections) == len(win.project.sections)
    sec = win.project.sections[0]
    win.comp_strip.section_clicked.emit(sec)
    assert sec.name in win.statusBar().currentMessage()
    # Inspector is showing section details
    assert win.inspector.body is not None


def test_select_ensures_canvas_tab_and_browser_sync(win):
    win.tabs.setCurrentIndex(0)
    assert win.tabs.currentIndex() == 0
    part = win.project.parts[0]
    win.select(part.id)
    assert win.tabs.currentIndex() == 1
    # Browser item is synchronized
    curr = win.browser.currentItem()
    assert curr is not None


def test_section_click_simulated_mouse_press(win):
    win.comp_strip.resize(600, 40)
    strip = win.comp_strip
    # Click near the left edge inside the first section
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF, Qt
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 20), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    strip.mousePressEvent(ev)
    assert strip.selected_index == 0
    assert win.inspector.body is not None


def test_action_states_based_on_project_status(win):
    # Fracture demo has nodes but no AI version meta
    assert not win.act_accept.isEnabled()
    assert not win.act_reject.isEnabled()
    # Mocking version meta
    win.project.composition_meta["version"] = 1
    win._comp_info()
    assert win.act_accept.isEnabled()
    assert win.act_reject.isEnabled()
