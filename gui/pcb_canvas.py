"""PCB canvas widget with DXF layer preview system."""
from __future__ import annotations

from typing import Optional, Set, List, Tuple, Callable
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox,
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsPolygonItem,
    QGraphicsLineItem, QGraphicsTextItem, QApplication
)
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QLineF
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath,
    QFont, QTransform, QCursor, QPolygonF
)
import math

from models.pcb_data import PCBData, Component, ScrewHole, BoardOutline
from models.avoidance import AvoidancePolygon
from avoidance.layout_hints import CandidateZone

# ── Constants ──────────────────────────────────────────────────────────────
GRID_SPACING = 19.05  # 1U in mm
GRID_COLOR = QColor(60, 60, 80)
BG_COLOR = QColor(30, 30, 46)

BOARD_OUTLINE_COLOR = QColor(255, 255, 255)
SCREW_HOLE_COLOR = QColor(100, 150, 255)
SWITCH_CUT_COLOR = QColor(255, 100, 100, 80)
SWITCH_CUT_BORDER = QColor(255, 100, 100)
STAB_COLOR = QColor(0, 200, 200, 120)
AVOIDANCE_CONFIRMED_COLOR = QColor(255, 0, 0, 100)
AVOIDANCE_SUSPECTED_COLOR = QColor(255, 200, 0, 80)
SELECTION_COLOR = QColor(255, 255, 0)

# Interaction modes
MODE_SELECT = "SELECT"
MODE_DRAW_RECT = "DRAW_RECT"
MODE_DRAW_POLYGON = "DRAW_POLYGON"
MODE_PLACE_HOLE = "PLACE_HOLE"
MODE_DRAW_OUTLINE = "DRAW_OUTLINE"

# Preview layer definitions
PREVIEW_LAYERS = [
    ("pcb_overview", "PCB 概览"),
    ("plate", "定位板"),
    ("sandwich_foam", "夹心棉"),
    ("switch_foam", "轴下垫"),
    ("ixpe_pad", "IXPE 声优垫"),
    ("bottom_foam", "底棉"),
]

# Standard stab spacing from plate_generator
STAB_SPACING = {
    "2u": 11.938,
    "2.25u": 15.875,
    "2.75u": 19.844,
    "6.25u": 50.0,
    "7u": 57.15,
}
STAB_WIRE_RADIUS = 0.85
STAB_INSERT_W = 3.0
STAB_INSERT_H = 3.5


class PcbCanvas(QWidget):
    """Canvas with DXF layer preview and PCB interaction."""

    # Signals
    signal_preview_layer_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Preview layer selector
        self._preview_combo = QComboBox()
        for key, label in PREVIEW_LAYERS:
            self._preview_combo.addItem(label, key)
        self._preview_combo.currentIndexChanged.connect(self._on_preview_combo_changed)
        self._preview_combo.setVisible(False)  # Hidden until PCB loaded
        layout.addWidget(self._preview_combo)

        # Graphics view
        self._view = _PcbGraphicsView(self)
        layout.addWidget(self._view)

        # Data
        self._pcb_data: Optional[PCBData] = None
        self._current_layer: str = "pcb_overview"
        self._preview_params = {}  # avoidance, screw_holes, excluded_refs, etc.

    # ── Public API ──────────────────────────────────────────────────────

    def set_pcb_data(self, pcb: PCBData) -> None:
        """Load PCB data and show PCB overview."""
        self._pcb_data = pcb
        self._preview_combo.setVisible(True)
        self._preview_combo.setCurrentIndex(0)
        self._current_layer = "pcb_overview"
        self._refresh()

    def update_preview(self, **kwargs) -> None:
        """Update preview with current editor state. Re-renders current layer."""
        self._preview_params.update(kwargs)
        self._refresh()

    def get_current_layer(self) -> str:
        return self._current_layer

    def fit_to_content(self) -> None:
        self._view.fit_to_content()

    # ── Interaction delegation ──────────────────────────────────────────

    def set_interaction_mode(self, mode: str) -> None:
        self._view.set_interaction_mode(mode)

    def update_selection(self, refs: Set[str]) -> None:
        self._view._selected_refs = refs

    def add_avoidance_polygon(self, vertices, source="manual") -> None:
        pass  # Handled via update_preview

    def get_zoom_level(self) -> float:
        return self._view._zoom_level

    # ── Preview rendering ───────────────────────────────────────────────

    def _on_preview_combo_changed(self, index: int) -> None:
        key = self._preview_combo.currentData()
        if key and key != self._current_layer:
            self._current_layer = key
            self._refresh()
            self.signal_preview_layer_changed.emit(key)

    def _refresh(self) -> None:
        """Clear and re-render current preview layer."""
        self._view._clear_scene()
        if not self._pcb_data:
            return

        self._view._render_grid(self._pcb_data)

        renderer = {
            "pcb_overview": self._render_pcb_overview,
            "plate": self._render_plate,
            "sandwich_foam": self._render_sandwich_foam,
            "switch_foam": self._render_switch_foam,
            "ixpe_pad": self._render_ixpe,
            "bottom_foam": self._render_bottom_foam,
        }.get(self._current_layer)
        if renderer:
            renderer()

        # Reset zoom and fit view
        self._view._zoom_level = 1.0
        self._view.fit_to_content()
        t = QTransform()
        t.scale(1, -1)
        self._view.setTransform(t)

    def _get_switches(self) -> list:
        """Get filtered switch list based on excluded refs."""
        if not self._pcb_data:
            return []
        switches = self._pcb_data.get_switches()
        excluded = self._preview_params.get("excluded_switch_refs", set())
        if excluded:
            switches = [s for s in switches if s.ref not in excluded]
        return switches

    def _get_screw_holes(self) -> list:
        """Get screw holes from params or PCB data."""
        return self._preview_params.get("screw_holes") or (self._pcb_data.screw_holes if self._pcb_data else [])

    def _draw_outline(self) -> None:
        """Draw board outline."""
        if not self._pcb_data:
            return
        if self._pcb_data.outline_tracks or self._pcb_data.outline_arcs:
            self._view._render_outline_tracks(self._pcb_data)
        elif self._pcb_data.board_outline and self._pcb_data.board_outline.is_valid():
            self._view._render_board_outline(self._pcb_data.board_outline)

    def _draw_screw_holes(self) -> None:
        """Draw screw holes."""
        for hole in self._get_screw_holes():
            self._view._render_screw_hole(hole)

    def _draw_avoidance(self) -> None:
        """Draw avoidance zones."""
        polys = self._preview_params.get("avoidance_polygons", [])
        for poly in polys:
            if len(poly.vertices) < 3:
                continue
            self._view._render_avoidance_polygon(poly)

    # ── Per-layer renderers ─────────────────────────────────────────────

    def _render_pcb_overview(self) -> None:
        """PCB概览: outline + 14mm switch rects + screw holes."""
        self._draw_outline()
        self._draw_screw_holes()
        # Switch cutout rectangles
        switches = self._get_switches()
        hw = 7.0  # 14mm / 2
        pen = QPen(SWITCH_CUT_BORDER, 1.0)
        brush = QBrush(SWITCH_CUT_COLOR)
        for sw in switches:
            r = QGraphicsRectItem(sw.x - hw, sw.y - hw, 14.0, 14.0)
            r.setPen(pen)
            r.setBrush(brush)
            self._view.scene.addItem(r)

    def _render_plate(self) -> None:
        """定位板: outline + 14mm cutouts + stabs + avoidance + screw holes."""
        self._draw_outline()
        self._draw_screw_holes()
        self._draw_avoidance()
        # Switch cutouts
        switches = self._get_switches()
        hw = 7.0
        pen = QPen(SWITCH_CUT_BORDER, 1.0)
        brush = QBrush(QColor(255, 100, 100, 50))
        for sw in switches:
            r = QGraphicsRectItem(sw.x - hw, sw.y - hw, 14.0, 14.0)
            r.setPen(pen)
            r.setBrush(brush)
            self._view.scene.addItem(r)
        # Stabilizer positions
        self._draw_stabs(switches)

    def _render_sandwich_foam(self) -> None:
        """夹心棉: outline + 16mm rects + screw holes."""
        self._draw_outline()
        self._draw_screw_holes()
        switches = self._get_switches()
        hw = 8.0  # 16mm / 2
        pen = QPen(QColor(200, 160, 100), 1.0)
        brush = QBrush(QColor(200, 160, 100, 40))
        for sw in switches:
            r = QGraphicsRectItem(sw.x - hw, sw.y - hw, 16.0, 16.0)
            r.setPen(pen)
            r.setBrush(brush)
            self._view.scene.addItem(r)

    def _render_switch_foam(self) -> None:
        """轴下垫: outline + 4mm circles + screw holes."""
        self._draw_outline()
        self._draw_screw_holes()
        switches = self._get_switches()
        r = 2.0  # 4mm / 2
        pen = QPen(QColor(100, 200, 200), 1.0)
        brush = QBrush(QColor(100, 200, 200, 40))
        for sw in switches:
            e = QGraphicsEllipseItem(sw.x - r, sw.y - r, 4.0, 4.0)
            e.setPen(pen)
            e.setBrush(brush)
            self._view.scene.addItem(e)

    def _render_ixpe(self) -> None:
        """IXPE声优垫: outline + screw holes only (solid)."""
        self._draw_outline()
        self._draw_screw_holes()

    def _render_bottom_foam(self) -> None:
        """底棉: outline + 10mm sparse circles + screw holes."""
        self._draw_outline()
        self._draw_screw_holes()
        if not self._pcb_data:
            return

        from shapely.geometry import Polygon, Point
        outline_poly = None

        # Build outline polygon for containment checks
        if self._pcb_data.board_outline and self._pcb_data.board_outline.is_valid():
            outline_poly = Polygon(self._pcb_data.board_outline.vertices)
        elif self._pcb_data.outline_tracks:
            # Build a bounding polygon from outline track endpoints
            all_points = []
            for t in self._pcb_data.outline_tracks:
                all_points.append((t.x1, t.y1))
                all_points.append((t.x2, t.y2))
            if len(all_points) >= 3:
                from shapely.geometry import MultiPoint
                hull = MultiPoint(all_points).convex_hull
                if hull.geom_type == 'Polygon':
                    outline_poly = hull

        if outline_poly is None:
            return
        if not outline_poly.is_valid:
            outline_poly = outline_poly.buffer(0)

        diameter = 10.0
        spacing = diameter * 3
        r = diameter / 2
        pen = QPen(QColor(150, 100, 255), 1.0)
        brush = QBrush(QColor(150, 100, 255, 30))
        min_x, min_y, max_x, max_y = outline_poly.bounds
        x = min_x + spacing
        while x < max_x:
            y = min_y + spacing
            while y < max_y:
                pt = Point(x, y)
                if outline_poly.contains(pt):
                    e = QGraphicsEllipseItem(x - r, y - r, diameter, diameter)
                    e.setPen(pen)
                    e.setBrush(brush)
                    self._view.scene.addItem(e)
                y += spacing
            x += spacing

    def _draw_stabs(self, switches: list) -> None:
        """Draw stabilizer positions at standard spacing."""
        # Detect likely stab positions from switch X-distances
        pen = QPen(STAB_COLOR, 1.0)
        brush = QBrush(STAB_COLOR)
        r = STAB_WIRE_RADIUS
        hw, hh = STAB_INSERT_W / 2, STAB_INSERT_H / 2

        # Group switches by Y position (same row)
        rows: dict[float, list] = {}
        for sw in switches:
            row_key = round(sw.y, 0)
            rows.setdefault(row_key, []).append(sw)

        for row_y, row_sw in rows.items():
            row_sw.sort(key=lambda s: s.x)
            # Check for spacebar (bottom row, wide spacing)
            # Check pairs of switches for standard stab distances
            for i, sw in enumerate(row_sw):
                for size, spacing in STAB_SPACING.items():
                    # Check if there's a switch at +spacing
                    target_x = sw.x + spacing
                    for sw2 in row_sw:
                        if abs(sw2.x - target_x) < 1.0 and abs(sw2.y - sw.y) < 1.0:
                            # Found a stab pair - draw stab at midpoint
                            cx = (sw.x + sw2.x) / 2
                            cy = sw.y
                            # Left stab hole
                            lx, ly = cx - spacing / 2, cy
                            self._view.scene.addEllipse(lx - r, ly - r, r * 2, r * 2, pen, brush)
                            self._view.scene.addRect(lx - hw, ly - hh, STAB_INSERT_W, STAB_INSERT_H, pen, brush)
                            # Right stab hole
                            rx, ry = cx + spacing / 2, cy
                            self._view.scene.addEllipse(rx - r, ry - r, r * 2, r * 2, pen, brush)
                            self._view.scene.addRect(rx - hw, ry - hh, STAB_INSERT_W, STAB_INSERT_H, pen, brush)
                            break


class _PcbGraphicsView(QGraphicsView):
    """Internal graphics view for PCB rendering and interaction."""

    signal_avoidance_created = pyqtSignal(list, str)
    signal_hole_placed = pyqtSignal(float, float)
    signal_outline_point_added = pyqtSignal(float, float)
    signal_component_clicked = pyqtSignal(str)
    signal_cursor_position = pyqtSignal(float, float)
    signal_zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.setBackgroundBrush(BG_COLOR)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        self._pcb_data: Optional[PCBData] = None
        self._selected_refs: Set[str] = set()
        self._grid_items: List[QGraphicsItem] = []
        self._interaction_mode = MODE_SELECT
        self._temp_drawing_item: Optional[QGraphicsItem] = None
        self._drawing_start_pos: Optional[QPointF] = None
        self._polygon_vertices: List[QPointF] = []
        self._outline_vertices: List[QPointF] = []
        self._zoom_level = 1.0
        self._min_zoom = 0.1
        self._max_zoom = 10.0
        self.setMouseTracking(True)

    def fit_to_content(self) -> None:
        if not self.scene.items():
            return
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        padding = 20
        rect.adjust(-padding, -padding, padding, padding)
        self.fitInView(rect, Qt.KeepAspectRatio)

    def set_interaction_mode(self, mode: str) -> None:
        self._interaction_mode = mode
        self._cancel_drawing()
        if mode == MODE_SELECT:
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.setCursor(QCursor(Qt.ArrowCursor))
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(QCursor(Qt.CrossCursor))

    def _clear_scene(self) -> None:
        self.scene.clear()
        self._grid_items.clear()

    def _render_grid(self, pcb: PCBData) -> None:
        if pcb and pcb.components:
            min_x = min(c.x for c in pcb.components)
            max_x = max(c.x for c in pcb.components)
            min_y = min(c.y for c in pcb.components)
            max_y = max(c.y for c in pcb.components)
        else:
            min_x = max_x = min_y = max_y = 0
        padding = GRID_SPACING * 3
        min_x -= padding; max_x += padding
        min_y -= padding; max_y += padding
        min_x = math.floor(min_x / GRID_SPACING) * GRID_SPACING
        max_x = math.ceil(max_x / GRID_SPACING) * GRID_SPACING
        min_y = math.floor(min_y / GRID_SPACING) * GRID_SPACING
        max_y = math.ceil(max_y / GRID_SPACING) * GRID_SPACING
        dot = 2
        for x in [min_x + i * GRID_SPACING for i in range(int((max_x - min_x) / GRID_SPACING) + 1)]:
            for y in [min_y + j * GRID_SPACING for j in range(int((max_y - min_y) / GRID_SPACING) + 1)]:
                d = QGraphicsEllipseItem(x - dot / 2, y - dot / 2, dot, dot)
                d.setBrush(QBrush(GRID_COLOR))
                d.setPen(QPen(Qt.NoPen))
                self.scene.addItem(d)
                self._grid_items.append(d)

    def _render_outline_tracks(self, pcb: PCBData) -> None:
        pen = QPen(BOARD_OUTLINE_COLOR, 1.5)
        for track in pcb.outline_tracks:
            self.scene.addLine(track.x1, track.y1, track.x2, track.y2, pen)
        for arc in pcb.outline_arcs:
            n = 32
            sr = math.radians(arc.start_angle)
            er = math.radians(arc.end_angle)
            if er <= sr:
                er += 2 * math.pi
            step = (er - sr) / n
            px = arc.cx + arc.radius * math.cos(sr)
            py = arc.cy + arc.radius * math.sin(sr)
            for i in range(1, n + 1):
                a = sr + i * step
                nx = arc.cx + arc.radius * math.cos(a)
                ny = arc.cy + arc.radius * math.sin(a)
                self.scene.addLine(px, py, nx, ny, pen)
                px, py = nx, ny

    def _render_board_outline(self, outline: BoardOutline) -> None:
        if not outline.vertices or len(outline.vertices) < 3:
            return
        pen = QPen(BOARD_OUTLINE_COLOR, 2.0)
        path = QPainterPath()
        first = outline.vertices[0]
        path.moveTo(first[0], first[1])
        for vx, vy in outline.vertices[1:]:
            path.lineTo(vx, vy)
        path.lineTo(first[0], first[1])
        self.scene.addPath(path, pen, QBrush(Qt.NoBrush))

    def _render_screw_hole(self, hole) -> None:
        r = hole.diameter / 2
        e = QGraphicsEllipseItem(hole.x - r, hole.y - r, hole.diameter, hole.diameter)
        e.setPen(QPen(SCREW_HOLE_COLOR, 1.5))
        e.setBrush(QBrush(Qt.NoBrush))
        self.scene.addItem(e)

    def _render_avoidance_polygon(self, polygon) -> None:
        if len(polygon.vertices) < 3:
            return
        verts = [QPointF(x, y) for x, y in polygon.vertices]
        item = QGraphicsPolygonItem(QPolygonF(verts))
        color = AVOIDANCE_CONFIRMED_COLOR if polygon.confidence == "confirmed" else AVOIDANCE_SUSPECTED_COLOR
        item.setPen(QPen(color.lighter(), 1.5))
        item.setBrush(QBrush(color))
        self.scene.addItem(item)

    def _scene_to_mm(self, pos: QPointF) -> Tuple[float, float]:
        return pos.x(), -pos.y()

    def _cancel_drawing(self) -> None:
        if self._temp_drawing_item:
            self.scene.removeItem(self._temp_drawing_item)
            self._temp_drawing_item = None
        self._drawing_start_pos = None
        self._polygon_vertices.clear()
        self._outline_vertices.clear()

    # ── Mouse events ────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event.accept()
            return
        scene_pos = self.mapToScene(event.pos())
        x, y = self._scene_to_mm(scene_pos)
        self.signal_cursor_position.emit(x, y)

        if self._interaction_mode == MODE_DRAW_RECT and event.button() == Qt.LeftButton:
            self._drawing_start_pos = scene_pos
            self._temp_drawing_item = QGraphicsRectItem(scene_pos.x(), scene_pos.y(), 0, 0)
            self._temp_drawing_item.setPen(QPen(AVOIDANCE_CONFIRMED_COLOR.lighter(), 1.5, Qt.DashLine))
            self._temp_drawing_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
            self.scene.addItem(self._temp_drawing_item)
        elif self._interaction_mode == MODE_DRAW_POLYGON:
            if event.button() == Qt.LeftButton:
                self._polygon_vertices.append(scene_pos)
                if len(self._polygon_vertices) == 1:
                    self._temp_drawing_item = QGraphicsPolygonItem()
                    self._temp_drawing_item.setPen(QPen(AVOIDANCE_CONFIRMED_COLOR.lighter(), 1.5, Qt.DashLine))
                    self._temp_drawing_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
                    self.scene.addItem(self._temp_drawing_item)
                else:
                    self._temp_drawing_item.setPolygon(QPolygonF(self._polygon_vertices + [scene_pos]))
            elif event.button() == Qt.RightButton and len(self._polygon_vertices) >= 3:
                verts = [(v.x(), -v.y()) for v in self._polygon_vertices]
                self.signal_avoidance_created.emit(verts, "manual")
                self._cancel_drawing()
        elif self._interaction_mode == MODE_PLACE_HOLE and event.button() == Qt.LeftButton:
            self.signal_hole_placed.emit(x, y)
        elif self._interaction_mode == MODE_DRAW_OUTLINE and event.button() == Qt.LeftButton:
            self._outline_vertices.append(scene_pos)
            self.signal_outline_point_added.emit(x, y)
            m = QGraphicsEllipseItem(scene_pos.x() - 2, scene_pos.y() - 2, 4, 4)
            m.setPen(QPen(BOARD_OUTLINE_COLOR, 1.0))
            m.setBrush(QBrush(BOARD_OUTLINE_COLOR))
            self.scene.addItem(m)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        x, y = self._scene_to_mm(scene_pos)
        self.signal_cursor_position.emit(x, y)
        if self._interaction_mode == MODE_DRAW_RECT and self._temp_drawing_item and self._drawing_start_pos:
            self._temp_drawing_item.setRect(QRectF(self._drawing_start_pos, scene_pos).normalized())
        elif self._interaction_mode == MODE_DRAW_POLYGON and self._temp_drawing_item and self._polygon_vertices:
            self._temp_drawing_item.setPolygon(QPolygonF(self._polygon_vertices + [scene_pos]))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.NoDrag if self._interaction_mode != MODE_SELECT else QGraphicsView.RubberBandDrag)
            event.accept()
            return
        if self._interaction_mode == MODE_DRAW_RECT and event.button() == Qt.LeftButton and self._drawing_start_pos:
            scene_pos = self.mapToScene(event.pos())
            rect = QRectF(self._drawing_start_pos, scene_pos).normalized()
            verts = [(rect.left(), -rect.top()), (rect.right(), -rect.top()),
                     (rect.right(), -rect.bottom()), (rect.left(), -rect.bottom())]
            self.signal_avoidance_created.emit(verts, "manual")
            self._cancel_drawing()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._interaction_mode == MODE_DRAW_POLYGON and len(self._polygon_vertices) >= 3:
            verts = [(-v.x(), -v.y()) for v in self._polygon_vertices]
            self.signal_avoidance_created.emit(verts, "manual")
            self._cancel_drawing()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
            new_zoom = self._zoom_level * factor
            if self._min_zoom <= new_zoom <= self._max_zoom:
                self.scale(factor, factor)
                self._zoom_level = new_zoom
                self.signal_zoom_changed.emit(self._zoom_level)
        else:
            super().wheelEvent(event)
