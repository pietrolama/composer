"""Canvas: nodes, audio cables and part frames drawn from the model.

The scene never edits the model itself: it reports gestures (move, connect,
delete, add) to the window, which applies them as undoable edits and rebuilds.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView, QMenu)

from .. import catalog
from ..validate import split_endpoint

NODE_W = 190
HEADER = 26
ROW = 17
PORT_R = 6

PART_COLORS = ["#c8794f", "#5f9ea0", "#b5a24a", "#8f73b8", "#6f9f5a", "#b8607a", "#5f7fb8"]
TOP_COLOR = "#7d8590"
INK = QColor("#e6e6e6")
MUTED = QColor("#9aa0a6")
BODY = QColor("#24272c")
CABLE = QColor("#d0d4d9")
SELECT = QColor("#f2c14e")
ERROR = QColor("#e5534b")


def part_color(project, part_id):
    ids = [p.id for p in project.parts]
    return QColor(PART_COLORS[ids.index(part_id) % len(PART_COLORS)] if part_id in ids else TOP_COLOR)


def _fmt(value):
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class PortItem(QGraphicsEllipseItem):
    def __init__(self, parent, endpoint, port, x, y):
        super().__init__(-PORT_R, -PORT_R, 2 * PORT_R, 2 * PORT_R, parent)
        self.endpoint, self.port = endpoint, port
        self.setPos(x, y)
        self.setBrush(QBrush(QColor("#3a3f46")))
        self.setPen(QPen(CABLE, 1.5))
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{port.name} ({port.type}, {'uscita' if port.direction == 'out' else 'ingresso'})")
        self.setCursor(Qt.CrossCursor)

    def hoverEnterEvent(self, e):
        self.setBrush(QBrush(SELECT))

    def hoverLeaveEvent(self, e):
        self.setBrush(QBrush(QColor("#3a3f46")))


class NodeItem(QGraphicsItem):
    def __init__(self, project, node, issues):
        super().__init__()
        self.node = node
        self.element_id = node.id
        self.module = catalog.MODULES.get(node.type)
        self.color = part_color(project, node.part_id)
        self.has_error = any(i.level == "error" for i in issues)
        self.tooltip = "\n".join(i.message for i in issues)
        self.lines = []
        if self.module:
            for spec in self.module.params:
                value = node.params.get(spec.name, spec.default)
                if spec.kind == "asset_list":
                    value = f"{len(value)} campioni"
                elif spec.kind == "asset":
                    part = next((p for p in project.parts if p.id == node.part_id), None)
                    value = value or (f"{part.source_id} (parte)" if part and part.source_id else "—")
                unit = f" {spec.unit}" if spec.unit and spec.unit != "lin" else ""
                self.lines.append(f"{spec.name}  {_fmt(value)}{unit}")
        audio = [p for p in self.module.ports if p.type == "audio"] if self.module else []
        ins = [p for p in audio if p.direction == "in"]
        outs = [p for p in audio if p.direction == "out"]
        rows = max(len(self.lines), len(ins), len(outs), 1)
        self.h = HEADER + 10 + ROW * rows
        for k, p in enumerate(ins):
            PortItem(self, f"{node.id}.{p.name}", p, 0, HEADER + 14 + ROW * k)
        for k, p in enumerate(outs):
            PortItem(self, f"{node.id}.{p.name}", p, NODE_W, HEADER + 14 + ROW * k)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setToolTip(self.tooltip or node.id)
        self.setZValue(2)

    def ports(self):
        return [c for c in self.childItems() if isinstance(c, PortItem)]

    def boundingRect(self):
        return QRectF(-PORT_R, -2, NODE_W + 2 * PORT_R, self.h + 4)

    def paint(self, painter, option, widget=None):
        rect = QRectF(0, 0, NODE_W, self.h)
        painter.setRenderHint(QPainter.Antialiasing)
        border = SELECT if self.isSelected() else (ERROR if self.has_error else QColor("#3d424a"))
        painter.setPen(QPen(border, 2 if self.isSelected() or self.has_error else 1))
        painter.setBrush(BODY)
        painter.drawRoundedRect(rect, 6, 6)
        head = QPainterPath()
        head.addRoundedRect(QRectF(0, 0, NODE_W, HEADER), 6, 6)
        head.addRect(QRectF(0, HEADER - 6, NODE_W, 6))
        painter.fillPath(head, self.color.darker(160))
        painter.setPen(INK)
        f = QFont()
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(QRectF(10, 0, NODE_W - 20, HEADER), Qt.AlignVCenter, self.node.type)
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() * 0.85)
        painter.setFont(f)
        painter.setPen(MUTED)
        painter.drawText(QRectF(10, 0, NODE_W - 20, HEADER), Qt.AlignVCenter | Qt.AlignRight,
                         self.node.id.removeprefix("node-"))
        painter.setPen(INK)
        for k, line in enumerate(self.lines):
            painter.drawText(QRectF(14, HEADER + 6 + ROW * k, NODE_W - 28, ROW), Qt.AlignVCenter, line)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().geometry_changed()
        return super().itemChange(change, value)


class CableItem(QGraphicsPathItem):
    def __init__(self, conn, src, dst):
        super().__init__()
        self.conn, self.element_id = conn, conn.id
        self.src, self.dst = src, dst
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.setToolTip(f"{conn.id}: {conn.source} → {conn.target}")
        self.update_path()

    def update_path(self):
        self.setPath(cable_path(self.src.scenePos(), self.dst.scenePos()))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(SELECT if self.isSelected() else CABLE, 3 if self.isSelected() else 2))
        painter.drawPath(self.path())

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(self.path())


def cable_path(a, b):
    dx = max(60.0, abs(b.x() - a.x()) * 0.5)
    path = QPainterPath(a)
    path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
    return path


class PartFrame(QGraphicsRectItem):
    def __init__(self, part, color, issues):
        super().__init__()
        self.part, self.element_id, self.color = part, part.id, color
        self.has_error = any(i.level == "error" for i in issues)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(0)
        self.setToolTip("\n".join(i.message for i in issues) or part.id)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(self.color)
        fill.setAlpha(28)
        pen = QPen(SELECT if self.isSelected() else (ERROR if self.has_error else self.color), 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(self.rect(), 10, 10)
        painter.setPen(self.color.lighter(130))
        f = QFont()
        f.setBold(True)
        painter.setFont(f)
        label = self.part.name + (f"  ·  {self.part.role}" if self.part.role else "") + ("  🔒" if self.part.locked else "")
        painter.drawText(self.rect().adjusted(12, 6, -12, 0), Qt.AlignTop | Qt.AlignLeft, label)


RULE = QColor("#b48ead")


class RuleItem(QGraphicsPathItem):
    """A composition rule: a behavioural relation between parts, not a cable."""

    def __init__(self, rule, src_item, dst_item, events):
        super().__init__()
        self.rule, self.element_id = rule, rule.id
        self.src_item, self.dst_item = src_item, dst_item
        self.label = f"{rule.when} → {rule.effect}" + (f"  ({events})" if events is not None else "")
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1.5)
        self.setToolTip(f"{rule.id}: {rule.source} {rule.when} → {rule.effect} su {rule.target}")
        self.update_path()

    def update_path(self):
        a, b = self.src_item.sceneBoundingRect(), self.dst_item.sceneBoundingRect()
        p0, p1 = QPointF(a.left(), a.center().y()), QPointF(b.left(), b.center().y())
        bow = 90 + abs(p1.y() - p0.y()) * 0.25
        path = QPainterPath(p0)
        path.cubicTo(QPointF(p0.x() - bow, p0.y()), QPointF(p1.x() - bow, p1.y()), p1)
        self.setPath(path)

    def shape(self):
        from PySide6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(12)
        return s.createStroke(self.path())

    def boundingRect(self):
        return super().boundingRect().adjusted(-200, -20, 20, 20)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = SELECT if self.isSelected() else RULE
        painter.setPen(QPen(color, 2, Qt.DashDotLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())
        end = self.path().pointAtPercent(1.0)
        before = self.path().pointAtPercent(0.97)
        d = end - before
        n = max((d.x() ** 2 + d.y() ** 2) ** 0.5, 1e-6)
        ux, uy = d.x() / n, d.y() / n
        head = QPainterPath(end)
        head.lineTo(end.x() - 11 * ux + 6 * uy, end.y() - 11 * uy - 6 * ux)
        head.lineTo(end.x() - 11 * ux - 6 * uy, end.y() - 11 * uy + 6 * ux)
        head.closeSubpath()
        painter.fillPath(head, color)
        mid = self.path().pointAtPercent(0.5)
        painter.setPen(color)
        painter.drawText(QRectF(mid.x() - 190, mid.y() - 9, 180, 18), Qt.AlignRight | Qt.AlignVCenter, self.label)


class CanvasScene(QGraphicsScene):
    moved = Signal(dict)                 # node id -> (x, y)
    connect_requested = Signal(str, str)  # source endpoint, target endpoint
    delete_requested = Signal(list)       # element ids
    add_requested = Signal(str, QPointF, object)  # module, scene pos, part id or None
    part_requested = Signal(str, object)  # node id, part id or None
    rule_requested = Signal(str, str)     # source part, target part

    def __init__(self):
        super().__init__()
        self.setBackgroundBrush(QColor("#1b1d21"))
        self.project = None
        self.nodes, self.cables, self.frames, self.rules = {}, [], {}, []
        self._drag = None
        self._rebuilding = False

    # -- building --------------------------------------------------------------
    def rebuild(self, project, issues, selected=(), rule_counts=None):
        self._rebuilding = True
        self.clear()
        self.project = project
        self.nodes, self.cables, self.frames = {}, [], {}
        by_el = {}
        for i in issues:
            by_el.setdefault(i.element, []).append(i)
        pos = project.presentation.get("nodes", {})
        auto = _auto_layout(project)
        for n in project.nodes:
            item = NodeItem(project, n, by_el.get(n.id, []))
            p = pos.get(n.id) or auto[n.id]
            item.setPos(p["x"], p["y"])
            self.addItem(item)
            self.nodes[n.id] = item
        for c in project.connections:
            s, t = self._port(c.source), self._port(c.target)
            if s and t:
                cable = CableItem(c, s, t)
                self.addItem(cable)
                self.cables.append(cable)
        for part in project.parts:
            frame = PartFrame(part, part_color(project, part.id), by_el.get(part.id, []))
            self.addItem(frame)
            self.frames[part.id] = frame
        self._update_frames()
        self.rules = []
        for r in project.rules:
            src, dst = self.frames.get(r.source) or self.nodes.get(r.source), \
                self.frames.get(r.target) or self.nodes.get(r.target)
            if src and dst:
                item = RuleItem(r, src, dst, rule_counts.get(r.id) if rule_counts else None)
                self.addItem(item)
                self.rules.append(item)
        for el in selected:
            item = self.item_for(el)
            if item:
                item.setSelected(True)
        self._rebuilding = False

    def _port(self, endpoint):
        nid, _ = split_endpoint(endpoint)
        item = self.nodes.get(nid)
        return next((p for p in item.ports() if p.endpoint == endpoint), None) if item else None

    def item_for(self, element_id):
        if element_id in self.nodes:
            return self.nodes[element_id]
        if element_id in self.frames:
            return self.frames[element_id]
        return next((c for c in self.cables + self.rules if c.element_id == element_id), None)

    def selected_ids(self):
        return [i.element_id for i in self.selectedItems() if hasattr(i, "element_id")]

    def geometry_changed(self):
        if self._rebuilding:
            return
        for c in self.cables:
            c.update_path()
        self._update_frames()
        for r in self.rules:
            r.update_path()

    def _update_frames(self):
        pres = self.project.presentation.get("parts", {}) if self.project else {}
        for pid, frame in self.frames.items():
            members = [self.nodes[n.id] for n in self.project.nodes if n.part_id == pid and n.id in self.nodes]
            if members:
                r = members[0].sceneBoundingRect()
                for m in members[1:]:
                    r = r.united(m.sceneBoundingRect())
                frame.setRect(r.adjusted(-22, -36, 22, 20))
            else:
                p = pres.get(pid, {"x": -320, "y": 60 + 120 * list(self.frames).index(pid)})
                frame.setRect(QRectF(p["x"], p["y"], 240, 90))

    # -- gestures ----------------------------------------------------------------
    def mousePressEvent(self, e):
        item = self.itemAt(e.scenePos(), self.views()[0].transform()) if self.views() else None
        if isinstance(item, PortItem) and e.button() == Qt.LeftButton:
            self._drag = (item, QGraphicsPathItem())
            self._drag[1].setPen(QPen(SELECT, 2, Qt.DashLine))
            self.addItem(self._drag[1])
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag:
            port, line = self._drag
            a, b = port.scenePos(), e.scenePos()
            line.setPath(cable_path(a, b) if port.port.direction == "out" else cable_path(b, a))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag:
            port, line = self._drag
            self._drag = None
            self.removeItem(line)
            target = next((i for i in self.items(e.scenePos()) if isinstance(i, PortItem)), None)
            if target and target is not port:
                a, b = (port, target) if port.port.direction == "out" else (target, port)
                self.connect_requested.emit(a.endpoint, b.endpoint)
            return
        super().mouseReleaseEvent(e)
        pres = self.project.presentation.get("nodes", {}) if self.project else {}
        moved = {nid: (it.pos().x(), it.pos().y()) for nid, it in self.nodes.items()
                 if (round(it.pos().x()), round(it.pos().y())) != tuple(pres.get(nid, {}).get(k) for k in ("x", "y"))}
        if moved:
            self.moved.emit(moved)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_ids():
            self.delete_requested.emit(self.selected_ids())
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        item = next((i for i in self.items(e.scenePos())
                     if isinstance(i, (NodeItem, PartFrame, CableItem, RuleItem))), None)
        menu = QMenu()
        if isinstance(item, NodeItem):
            sub = menu.addMenu("Assegna alla parte")
            for part in [None] + list(self.project.parts):
                act = sub.addAction("— primo livello —" if part is None else part.name)
                act.triggered.connect(lambda _=False, p=part, n=item.node.id:
                                      self.part_requested.emit(n, p.id if p else None))
            menu.addAction("Elimina", lambda: self.delete_requested.emit([item.element_id]))
        elif isinstance(item, CableItem):
            menu.addAction("Scollega", lambda: self.delete_requested.emit([item.element_id]))
        elif isinstance(item, RuleItem):
            menu.addAction("Elimina regola", lambda: self.delete_requested.emit([item.element_id]))
        else:
            part_id = item.part.id if isinstance(item, PartFrame) else None
            sub = menu.addMenu("Aggiungi modulo" + (f" in «{item.part.name}»" if part_id else ""))
            if part_id:
                rules = menu.addMenu("Nuova regola verso")
                for target in self.project.parts:
                    act = rules.addAction(target.name)
                    act.triggered.connect(lambda _=False, t=target.id, s=part_id: self.rule_requested.emit(s, t))
            for name, mod in catalog.MODULES.items():
                act = sub.addAction(name)
                act.setToolTip(mod.doc)
                act.triggered.connect(lambda _=False, m=name, p=e.scenePos(), pid=part_id:
                                      self.add_requested.emit(m, p, pid))
        menu.exec(e.screenPos())


def _auto_layout(project):
    """For nodes without a saved position: one horizontal band per part,
    columns by depth in the audio graph, top-level nodes centred on the right."""
    depth = {n.id: 0 for n in project.nodes}
    for _ in range(len(project.nodes)):
        for c in project.connections:
            s, t = split_endpoint(c.source)[0], split_endpoint(c.target)[0]
            if s in depth and t in depth and depth[t] < depth[s] + 1:
                depth[t] = depth[s] + 1
    band = {p.id: k for k, p in enumerate(project.parts)}
    band_h = 210
    top_depth = max((depth[n.id] for n in project.nodes if n.part_id is not None), default=-1) + 1
    centre = 60 + band_h * max(len(project.parts) - 1, 0) / 2
    out, stacked = {}, {}
    for n in project.nodes:
        if n.part_id in band:
            x, y = 60 + 280 * depth[n.id], 60 + band_h * band[n.part_id]
        else:
            col = max(depth[n.id], top_depth)
            x, y = 60 + 280 * col, centre
        k = stacked.get((x, y), 0)
        stacked[(x, y)] = k + 1
        out[n.id] = {"x": x, "y": y + 150 * k}
    return out


class CanvasView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._pan = None

    def wheelEvent(self, e):
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.2 < scale < 3:
            self.scale(factor, factor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(e)

    def fit(self):
        r = self.scene().itemsBoundingRect().adjusted(-60, -60, 60, 60)
        self.setSceneRect(r.adjusted(-2000, -2000, 2000, 2000))
        self.fitInView(r, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.resetTransform()
        self.centerOn(r.center())
