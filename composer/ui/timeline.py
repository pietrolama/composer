"""Timeline view for Intentional DAW: lanes, time ruler, and intent blocks.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QComboBox)

from ..intent import INTENT_CATEGORIES

LANE_HEIGHT = 64
RULER_HEIGHT = 28
SEC_WIDTH = 24.0  # pixels per second (zoom factor default)


class IntentBlockItem(QGraphicsRectItem):
    def __init__(self, block, ppx=SEC_WIDTH):
        super().__init__()
        self.block = block
        self.ppx = ppx
        self.cat = INTENT_CATEGORIES.get(block.category)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self._resizing = False
        self._sync_rect()

    def _sync_rect(self):
        w = max(16.0, self.block.duration * self.ppx)
        h = LANE_HEIGHT - 6
        self.setRect(0, 0, w, h)
        self.setPos(self.block.start * self.ppx, RULER_HEIGHT + self.block.lane * LANE_HEIGHT + 3)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        base_color = QColor(self.cat.color if self.cat else "#888888")
        fill_color = QColor(base_color)
        fill_color.setAlpha(180 if self.isSelected() else 110)
        
        pen = QPen(QColor("#f2c14e") if self.isSelected() else base_color.lighter(130), 2 if self.isSelected() else 1.2)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))
        painter.drawRoundedRect(self.rect(), 6, 6)

        # Label: Title & Category
        painter.setPen(QColor("#ffffff" if self.isSelected() else "#e6e6e6"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        title = self.block.name or (self.cat.label if self.cat else self.block.category)
        dur_text = f" ({self.block.duration:g}s)"
        painter.drawText(self.rect().adjusted(8, 6, -8, -6), Qt.AlignTop | Qt.AlignLeft, title + dur_text)

        # Parameters summary
        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#cfd3d8"))
        p_summary = " · ".join(f"{k}: {v:g}" if isinstance(v, float) else f"{k}: {v}"
                               for k, v in list(self.block.params.items())[:3])
        painter.drawText(self.rect().adjusted(8, 24, -8, -4), Qt.AlignTop | Qt.AlignLeft, p_summary)


class TimelineScene(QGraphicsScene):
    block_selected = Signal(str)           # block id
    block_moved = Signal(str, float, int)  # block id, new_start, new_lane
    block_resized = Signal(str, float)     # block id, new_duration
    add_block_requested = Signal(str, float, int)  # category, start, lane
    delete_requested = Signal(list)        # block ids

    def __init__(self):
        super().__init__()
        self.project = None
        self.ppx = SEC_WIDTH
        self.items_by_id = {}
        self.num_lanes = 6
        self.selectionChanged.connect(self._on_selection_changed)

    def rebuild(self, project, selected_ids=None):
        self.clear()
        self.project = project
        self.items_by_id = {}
        if not project:
            return

        total_sec = max(project.duration_seconds or 60.0, 120.0)
        total_w = total_sec * self.ppx + 200.0
        total_h = RULER_HEIGHT + self.num_lanes * LANE_HEIGHT

        self.setSceneRect(0, 0, total_w, total_h)

        # Draw blocks
        for b in project.intent_blocks:
            item = IntentBlockItem(b, self.ppx)
            self.addItem(item)
            self.items_by_id[b.id] = item
            if selected_ids and b.id in selected_ids:
                item.setSelected(True)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#181a1e"))
        total_sec = max(self.project.duration_seconds if self.project else 60.0, 120.0)
        total_w = total_sec * self.ppx + 200.0

        # Ruler background
        ruler_rect = QRectF(0, 0, total_w, RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#22252a"))
        painter.setPen(QColor("#3a3f46"))
        painter.drawLine(0, RULER_HEIGHT, int(total_w), RULER_HEIGHT)

        # Seconds ticks
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#7d8590"))

        sec = 0
        while sec * self.ppx < total_w:
            x = sec * self.ppx
            is_major = (sec % 10 == 0)
            is_mid = (sec % 5 == 0)
            h = RULER_HEIGHT if is_major else (RULER_HEIGHT * 0.6 if is_mid else RULER_HEIGHT * 0.3)
            painter.drawLine(int(x), int(RULER_HEIGHT - h), int(x), RULER_HEIGHT)
            if is_major:
                mins = int(sec // 60)
                rem_sec = int(sec % 60)
                time_str = f"{mins}:{rem_sec:02d}"
                painter.drawText(QRectF(x + 3, 2, 45, RULER_HEIGHT - 4), Qt.AlignLeft | Qt.AlignVCenter, time_str)
                # Vertical grid line across lanes
                painter.setPen(QPen(QColor("#24272c"), 1, Qt.DashLine))
                painter.drawLine(int(x), RULER_HEIGHT, int(x), int(RULER_HEIGHT + self.num_lanes * LANE_HEIGHT))
                painter.setPen(QColor("#7d8590"))
            sec += 1

        # Lane dividers & labels
        for l in range(self.num_lanes):
            y = RULER_HEIGHT + l * LANE_HEIGHT
            painter.setPen(QPen(QColor("#2c3036"), 1))
            painter.drawLine(0, int(y), int(total_w), int(y))
            # Lane tag
            painter.setPen(QColor("#5c6370"))
            painter.drawText(QRectF(4, y + 4, 60, 16), Qt.AlignLeft | Qt.AlignVCenter, f"Corsia {l + 1}")

    def _on_selection_changed(self):
        sel = self.selectedItems()
        if len(sel) == 1 and isinstance(sel[0], IntentBlockItem):
            self.block_selected.emit(sel[0].block.id)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        for item in self.selectedItems():
            if isinstance(item, IntentBlockItem):
                new_start = max(0.0, item.pos().x() / self.ppx)
                new_lane = max(0, min(self.num_lanes - 1, int((item.pos().y() - RULER_HEIGHT + LANE_HEIGHT / 2) // LANE_HEIGHT)))
                if abs(new_start - item.block.start) > 0.05 or new_lane != item.block.lane:
                    self.block_moved.emit(item.block.id, new_start, new_lane)

    def contextMenuEvent(self, e):
        menu = QMenu()
        click_x = e.scenePos().x()
        click_y = e.scenePos().y()
        start_time = max(0.0, click_x / self.ppx)
        lane = max(0, min(self.num_lanes - 1, int((click_y - RULER_HEIGHT) // LANE_HEIGHT)))

        clicked_item = self.itemAt(e.scenePos(), self.views()[0].transform()) if self.views() else None
        while clicked_item and not isinstance(clicked_item, IntentBlockItem):
            clicked_item = clicked_item.parentItem()

        if isinstance(clicked_item, IntentBlockItem):
            del_act = menu.addAction(f"Elimina «{clicked_item.block.name}»")
            act = menu.exec(e.screenPos())
            if act == del_act:
                self.delete_requested.emit([clicked_item.block.id])
            return

        add_menu = menu.addMenu(f"+ Aggiungi Blocco a {start_time:.1f}s (Corsia {lane + 1})")
        for cat_id, cat in INTENT_CATEGORIES.items():
            a = add_menu.addAction(f"{cat.label} — {cat.doc}")
            a.setData(cat_id)

        chosen = menu.exec(e.screenPos())
        if chosen and chosen.data():
            self.add_block_requested.emit(chosen.data(), start_time, lane)


class TimelineView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
