"""PCB canvas widget for rendering and interacting with PCB data."""
from __future__ import annotations

from typing import Optional, Set, List, Tuple, Callable
from PyQt5.QtWidgets import (
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


# Constants
GRID_SPACING = 19.05  # 1U key spacing in mm
GRID_COLOR = QColor(60, 60, 80)
BG_COLOR = QColor(30, 30, 46)  # #1e1e2e
BOARD_OUTLINE_COLOR = QColor(255, 255, 255)
AVOIDANCE_CONFIRMED_COLOR = QColor(255, 0, 0, 100)  # Red semi-transparent
AVOIDANCE_SUSPECTED_COLOR = QColor(255, 200, 0, 80)  # Yellow semi-transparent
SCREW_HOLE_COLOR = QColor(100, 150, 255)
SELECTION_COLOR = QColor(255, 255, 0)  # Bright yellow
CANDIDATE_ZONE_COLOR = QColor(100, 150, 255)

# Component colors by classification
COMPONENT_COLORS = {
    "switch": QColor(100, 200, 100),  # Green
    "ic": QColor(255, 165, 0),        # Orange
    "mechanical": QColor(100, 150, 255),  # Blue
    "unclassified": QColor(150, 150, 150),  # Gray
}

# Interaction modes
MODE_SELECT = "SELECT"
MODE_DRAW_RECT = "DRAW_RECT"
MODE_DRAW_POLYGON = "DRAW_POLYGON"
MODE_PLACE_HOLE = "PLACE_HOLE"
MODE_DRAW_OUTLINE = "DRAW_OUTLINE"


class PcbCanvas(QGraphicsView):
    """Interactive canvas for rendering and editing PCB data."""

    # Signals
    signal_avoidance_created = pyqtSignal(list, str)  # vertices, source
    signal_hole_placed = pyqtSignal(float, float)  # x, y
    signal_outline_point_added = pyqtSignal(float, float)  # x, y
    signal_component_clicked = pyqtSignal(str)  # ref designator
    signal_cursor_position = pyqtSignal(float, float)  # x, y in mm
    signal_zoom_changed = pyqtSignal(float)  # zoom level

    def __init__(self, parent=None):
        super().__init__(parent)

        # Scene setup
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.setBackgroundBrush(BG_COLOR)

        # Render settings
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        # Data
        self._pcb_data: Optional[PCBData] = None
        self._selected_refs: Set[str] = set()
        self._avoidance_polygons: List[AvoidancePolygon] = []
        self._candidate_zones: List[CandidateZone] = []

        # Graphics items storage
        self._grid_items: List[QGraphicsItem] = []
        self._component_items: dict[str, QGraphicsItem] = {}
        self._hole_items: List[QGraphicsItem] = []
        self._outline_item: Optional[QGraphicsItem] = None
        self._avoidance_items: List[QGraphicsItem] = []
        self._candidate_items: List[QGraphicsItem] = []

        # Interaction state
        self._interaction_mode = MODE_SELECT
        self._temp_drawing_item: Optional[QGraphicsItem] = None
        self._drawing_start_pos: Optional[QPointF] = None
        self._polygon_vertices: List[QPointF] = []
        self._outline_vertices: List[QPointF] = []

        # Zoom state
        self._zoom_level = 1.0
        self._min_zoom = 0.1
        self._max_zoom = 10.0

        # Enable mouse tracking for cursor position updates
        self.setMouseTracking(True)

    def set_pcb_data(self, pcb: PCBData) -> None:
        """Load and render PCB data."""
        self._pcb_data = pcb
        self._clear_scene()
        self._render_grid()
        self._render_pcb()
        self.fit_to_content()
        # Flip Y-axis: Altium uses Y-up, Qt uses Y-down
        self.scale(1, -1)

    def update_selection(self, selected_refs: Set[str]) -> None:
        """Highlight selected switches."""
        self._selected_refs = selected_refs
        self._update_selection_highlights()

    def set_interaction_mode(self, mode: str) -> None:
        """Set interaction mode."""
        self._interaction_mode = mode
        self._cancel_drawing()

        # Update drag mode
        if mode == MODE_SELECT:
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.setCursor(QCursor(Qt.ArrowCursor))
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            if mode == MODE_DRAW_RECT:
                self.setCursor(QCursor(Qt.CrossCursor))
            elif mode == MODE_DRAW_POLYGON:
                self.setCursor(QCursor(Qt.CrossCursor))
            elif mode == MODE_PLACE_HOLE:
                self.setCursor(QCursor(Qt.PointingHandCursor))
            elif mode == MODE_DRAW_OUTLINE:
                self.setCursor(QCursor(Qt.CrossCursor))

    def get_selected_items(self) -> List:
        """Return currently selected items."""
        return list(self._selected_refs)

    def fit_to_content(self) -> None:
        """Zoom to show all content."""
        if not self.scene.items():
            return

        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return

        # Add padding
        padding = 20
        rect.adjust(-padding, -padding, padding, padding)

        self.fitInView(rect, Qt.KeepAspectRatio)

    def add_avoidance_polygon(self, vertices: List[Tuple[float, float]], source: str = "manual") -> None:
        """Programmatically add an avoidance polygon."""
        if len(vertices) < 3:
            return

        polygon = AvoidancePolygon(
            vertices=vertices,
            confidence="confirmed",
            source=source,
            label=f"Manual {len(self._avoidance_polygons) + 1}"
        )
        self._avoidance_polygons.append(polygon)
        self._render_avoidance_polygon(polygon)

    def _clear_scene(self) -> None:
        """Clear all rendered items."""
        self.scene.clear()
        self._grid_items.clear()
        self._component_items.clear()
        self._hole_items.clear()
        self._outline_item = None
        self._avoidance_items.clear()
        self._candidate_items.clear()

    def _render_grid(self) -> None:
        """Render dot grid."""
        # Determine grid size based on PCB bounds
        if self._pcb_data and self._pcb_data.components:
            min_x = min(c.x for c in self._pcb_data.components)
            max_x = max(c.x for c in self._pcb_data.components)
            min_y = min(c.y for c in self._pcb_data.components)
            max_y = max(c.y for c in self._pcb_data.components)
        else:
            min_x = max_x = min_y = max_y = 0

        # Add padding
        padding = GRID_SPACING * 3
        min_x -= padding
        max_x += padding
        min_y -= padding
        max_y += padding

        # Round to grid spacing
        min_x = math.floor(min_x / GRID_SPACING) * GRID_SPACING
        max_x = math.ceil(max_x / GRID_SPACING) * GRID_SPACING
        min_y = math.floor(min_y / GRID_SPACING) * GRID_SPACING
        max_y = math.ceil(max_y / GRID_SPACING) * GRID_SPACING

        # Draw dots
        dot_size = 2
        for x in [min_x + i * GRID_SPACING for i in range(int((max_x - min_x) / GRID_SPACING) + 1)]:
            for y in [min_y + j * GRID_SPACING for j in range(int((max_y - min_y) / GRID_SPACING) + 1)]:
                dot = QGraphicsEllipseItem(x - dot_size/2, y - dot_size/2, dot_size, dot_size)
                dot.setBrush(QBrush(GRID_COLOR))
                dot.setPen(QPen(Qt.NoPen))
                self.scene.addItem(dot)
                self._grid_items.append(dot)

    def _render_pcb(self) -> None:
        """Render all PCB elements."""
        if not self._pcb_data:
            return

        # Render board outline
        if self._pcb_data.board_outline and self._pcb_data.board_outline.is_valid():
            self._render_board_outline(self._pcb_data.board_outline)

        # Render components
        for component in self._pcb_data.components:
            self._render_component(component)

        # Render screw holes
        for hole in self._pcb_data.screw_holes:
            self._render_screw_hole(hole)

    def _render_board_outline(self, outline: BoardOutline) -> None:
        """Render board outline."""
        if not outline.vertices:
            return

        polygon_item = QGraphicsPolygonItem()
        path = QPainterPath()

        # Create polygon from vertices
        qt_vertices = [QPointF(x, y) for x, y in outline.vertices]
        polygon_item.setPolygon(QPolygonF(qt_vertices))

        pen = QPen(BOARD_OUTLINE_COLOR)
        pen.setWidthF(2.0)
        polygon_item.setPen(pen)
        polygon_item.setBrush(QBrush(Qt.NoBrush))

        self.scene.addItem(polygon_item)
        self._outline_item = polygon_item

    def _render_component(self, component: Component) -> None:
        """Render a single component."""
        if not component.pads:
            # Create a simple box if no pads
            x, y = component.x - 5, component.y - 5
            w, h = 10, 10
        else:
            # Calculate bounding box
            min_x = min(p.x - p.width/2 for p in component.pads)
            max_x = max(p.x + p.width/2 for p in component.pads)
            min_y = min(p.y - p.height/2 for p in component.pads)
            max_y = max(p.y + p.height/2 for p in component.pads)
            x, y = min_x, min_y
            w, h = max_x - min_x, max_y - min_y

        # Get color based on classification
        color = COMPONENT_COLORS.get(component.classification, COMPONENT_COLORS["unclassified"])

        # Create rectangle
        rect_item = QGraphicsRectItem(x, y, w, h)
        rect_item.setPen(QPen(Qt.black, 0.5))
        rect_item.setBrush(QBrush(color))

        # Add ref designator as tooltip
        rect_item.setToolTip(f"{component.ref}\n{component.footprint_name}\nPos: ({component.x:.2f}, {component.y:.2f})")

        # Store reference
        rect_item.setData(0, component.ref)  # Store ref in data

        self.scene.addItem(rect_item)
        self._component_items[component.ref] = rect_item

        # Add label if component is a switch
        if component.classification == "switch":
            label = QGraphicsTextItem(component.ref)
            label.setDefaultTextColor(QColor(255, 255, 255))
            label.setFont(QFont("Arial", 8))
            label.setPos(component.x - 10, component.y - 5)
            label.setVisible(False)  # Hide until zoomed in
            self.scene.addItem(label)

            # Link label to component
            rect_item.setData(1, label)  # Store label reference

    def _render_screw_hole(self, hole: ScrewHole) -> None:
        """Render a screw hole."""
        radius = hole.diameter / 2
        ellipse = QGraphicsEllipseItem(
            hole.x - radius,
            hole.y - radius,
            hole.diameter,
            hole.diameter
        )
        ellipse.setPen(QPen(SCREW_HOLE_COLOR, 1.5))
        ellipse.setBrush(QBrush(Qt.NoBrush))

        self.scene.addItem(ellipse)
        self._hole_items.append(ellipse)

    def _render_avoidance_polygon(self, polygon: AvoidancePolygon) -> None:
        """Render an avoidance polygon."""
        if len(polygon.vertices) < 3:
            return

        qt_vertices = [QPointF(x, y) for x, y in polygon.vertices]
        poly_item = QGraphicsPolygonItem(qt_vertices)

        # Set color based on confidence
        if polygon.confidence == "confirmed":
            color = AVOIDANCE_CONFIRMED_COLOR
        else:
            color = AVOIDANCE_SUSPECTED_COLOR

        poly_item.setPen(QPen(color.lighter(), 1.5))
        poly_item.setBrush(QBrush(color))

        self.scene.addItem(poly_item)
        self._avoidance_items.append(poly_item)

    def _render_candidate_zones(self) -> None:
        """Render candidate split zones."""
        # Clear existing
        for item in self._candidate_items:
            self.scene.removeItem(item)
        self._candidate_items.clear()

        for zone in self._candidate_zones:
            # Draw dashed rectangle around zone
            rect = QRectF(zone.center_x - GRID_SPACING/2, zone.center_y - GRID_SPACING/2,
                         GRID_SPACING, GRID_SPACING)

            rect_item = QGraphicsRectItem(rect)
            pen = QPen(CANDIDATE_ZONE_COLOR)
            pen.setWidthF(2.0)
            pen.setStyle(Qt.DashLine)
            rect_item.setPen(pen)
            rect_item.setBrush(QBrush(Qt.NoBrush))
            rect_item.setToolTip(zone.description)

            self.scene.addItem(rect_item)
            self._candidate_items.append(rect_item)

    def _update_selection_highlights(self) -> None:
        """Update visual highlights for selected components."""
        for ref, item in self._component_items.items():
            if ref in self._selected_refs:
                item.setPen(QPen(SELECTION_COLOR, 2.0))
                item.setZValue(10)  # Bring to front
            else:
                item.setPen(QPen(Qt.black, 0.5))
                item.setZValue(0)

    def _cancel_drawing(self) -> None:
        """Cancel current drawing operation."""
        if self._temp_drawing_item:
            self.scene.removeItem(self._temp_drawing_item)
            self._temp_drawing_item = None

        self._drawing_start_pos = None
        self._polygon_vertices.clear()
        self._outline_vertices.clear()

    def _scene_to_mm(self, pos: QPointF) -> Tuple[float, float]:
        """Convert scene position to mm coordinates (Y-flipped for Altium convention)."""
        return pos.x(), -pos.y()

    # Mouse event handlers
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.MiddleButton:
            # Start panning
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())
        x, y = self._scene_to_mm(scene_pos)

        if self._interaction_mode == MODE_SELECT:
            if event.button() == Qt.LeftButton:
                # Check if clicked on a component
                item = self.scene.itemAt(scene_pos, QTransform())
                if item and item.data(0):
                    ref = item.data(0)
                    self.signal_component_clicked.emit(ref)

            super().mousePressEvent(event)

        elif self._interaction_mode == MODE_DRAW_RECT:
            if event.button() == Qt.LeftButton:
                self._drawing_start_pos = scene_pos
                # Create temporary rectangle
                self._temp_drawing_item = QGraphicsRectItem(scene_pos.x(), scene_pos.y(), 0, 0)
                self._temp_drawing_item.setPen(QPen(AVOIDANCE_CONFIRMED_COLOR.lighter(), 1.5, Qt.DashLine))
                self._temp_drawing_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
                self.scene.addItem(self._temp_drawing_item)

        elif self._interaction_mode == MODE_DRAW_POLYGON:
            if event.button() == Qt.LeftButton:
                self._polygon_vertices.append(scene_pos)

                if len(self._polygon_vertices) == 1:
                    # Start new polygon
                    self._temp_drawing_item = QGraphicsPolygonItem()
                    self._temp_drawing_item.setPen(QPen(AVOIDANCE_CONFIRMED_COLOR.lighter(), 1.5, Qt.DashLine))
                    self._temp_drawing_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
                    self.scene.addItem(self._temp_drawing_item)
                else:
                    # Update polygon
                    qt_vertices = self._polygon_vertices + [scene_pos]  # Close to cursor
                    self._temp_drawing_item.setPolygon(QPolygonF(qt_vertices))

            elif event.button() == Qt.RightButton:
                # Right-click to close polygon
                if len(self._polygon_vertices) >= 3:
                    vertices = [(v.x(), -v.y()) for v in self._polygon_vertices]
                    self.signal_avoidance_created.emit(vertices, "manual")
                    self._cancel_drawing()

        elif self._interaction_mode == MODE_PLACE_HOLE:
            if event.button() == Qt.LeftButton:
                self.signal_hole_placed.emit(x, y)

        elif self._interaction_mode == MODE_DRAW_OUTLINE:
            if event.button() == Qt.LeftButton:
                self._outline_vertices.append(scene_pos)
                self.signal_outline_point_added.emit(x, y)

                # Draw point marker
                marker = QGraphicsEllipseItem(scene_pos.x() - 2, scene_pos.y() - 2, 4, 4)
                marker.setPen(QPen(BOARD_OUTLINE_COLOR, 1.0))
                marker.setBrush(QBrush(BOARD_OUTLINE_COLOR))
                self.scene.addItem(marker)
                self._candidate_items.append(marker)  # Store for cleanup

    def mouseMoveEvent(self, event):
        """Handle mouse move events."""
        scene_pos = self.mapToScene(event.pos())
        x, y = self._scene_to_mm(scene_pos)

        # Emit cursor position
        self.signal_cursor_position.emit(x, y)

        # Update temporary drawing
        if self._interaction_mode == MODE_DRAW_RECT and self._temp_drawing_item:
            if self._drawing_start_pos:
                rect = QRectF(self._drawing_start_pos, scene_pos).normalized()
                self._temp_drawing_item.setRect(rect)

        elif self._interaction_mode == MODE_DRAW_POLYGON and self._temp_drawing_item:
            if self._polygon_vertices:
                # Update polygon to include cursor position
                qt_vertices = self._polygon_vertices + [scene_pos]
                self._temp_drawing_item.setPolygon(QPolygonF(qt_vertices))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        if event.button() == Qt.MiddleButton:
            # Stop panning
            if self._interaction_mode == MODE_SELECT:
                self.setDragMode(QGraphicsView.RubberBandDrag)
            else:
                self.setDragMode(QGraphicsView.NoDrag)
            event.accept()
            return

        if self._interaction_mode == MODE_DRAW_RECT and event.button() == Qt.LeftButton:
            if self._temp_drawing_item and self._drawing_start_pos:
                scene_pos = self.mapToScene(event.pos())
                rect = QRectF(self._drawing_start_pos, scene_pos).normalized()

                # Convert to vertices (negate Y for Altium coordinate system)
                vertices = [
                    (rect.left(), -rect.top()),
                    (rect.right(), -rect.top()),
                    (rect.right(), -rect.bottom()),
                    (rect.left(), -rect.bottom())
                ]

                self.signal_avoidance_created.emit(vertices, "manual")
                self._cancel_drawing()

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle mouse double-click events."""
        if self._interaction_mode == MODE_DRAW_POLYGON:
            if len(self._polygon_vertices) >= 3:
                vertices = [(v.x(), v.y()) for v in self._polygon_vertices]
                self.signal_avoidance_created.emit(vertices, "manual")
                self._cancel_drawing()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        if event.modifiers() & Qt.ControlModifier:
            # Zoom with Ctrl+Wheel
            factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
            self._zoom(factor)
        else:
            # Regular scrolling
            super().wheelEvent(event)

    def _zoom(self, factor: float) -> None:
        """Zoom by factor."""
        # Clamp zoom level
        new_zoom = self._zoom_level * factor
        if new_zoom < self._min_zoom or new_zoom > self._max_zoom:
            return

        self.scale(factor, factor)
        self._zoom_level = new_zoom

        # Emit zoom change
        self.signal_zoom_changed.emit(self._zoom_level)

        # Update label visibility based on zoom
        show_labels = self._zoom_level > 1.5
        for ref, item in self._component_items.items():
            label = item.data(1)
            if label:
                label.setVisible(show_labels)

    def get_zoom_level(self) -> float:
        """Get current zoom level."""
        return self._zoom_level
