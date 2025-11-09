"""
Mind Map Module
Visualizes file structure and relationships in a mind map format
"""

import os
from collections import deque
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal, QThread, QObject
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QIcon, QPainterPath
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QSpinBox, QComboBox, QGraphicsView, QGraphicsScene,
                               QGraphicsItem, QGraphicsEllipseItem, QGraphicsTextItem,
                               QGraphicsLineItem, QMessageBox, QProgressBar, QTextEdit,
                               QSplitter, QGroupBox, QFormLayout, QCheckBox, QSlider)


class FileNode(QGraphicsItem):
    """Represents a file or directory node in the mind map."""
    
    def __init__(self, name, is_directory=False, size=0, path="", parent=None):
        super().__init__(parent)
        self.name = name
        self.is_directory = is_directory
        self.size = size
        self.path = path
        self.children = []
        self.level = 0
        self.expanded = False
        
        # Node dimensions
        self.width = 120
        self.height = 60
        self.padding = 10
        
        # Colors
        if is_directory:
            self.bg_color = QColor(100, 150, 255)  # Blue for directories
            self.text_color = QColor(255, 255, 255)
        else:
            self.bg_color = QColor(150, 200, 150)  # Green for files
            self.text_color = QColor(0, 0, 0)
        
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setAcceptHoverEvents(True)
        
        # Create bounding rectangle
        self.rect = QRectF(0, 0, self.width, self.height)
        
    def boundingRect(self):
        return self.rect
    
    def paint(self, painter, option, widget=None):
        # Draw node background
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw rounded rectangle
        path = QPainterPath()
        path.addRoundedRect(self.rect, 10, 10)
        
        # Fill with color
        brush = QBrush(self.bg_color)
        if self.isSelected():
            brush = QBrush(self.bg_color.darker(120))
        painter.fillPath(path, brush)
        
        # Draw border
        pen = QPen(QColor(0, 0, 0), 2)
        if self.isSelected():
            pen = QPen(QColor(255, 200, 0), 3)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # Draw text
        painter.setPen(QPen(self.text_color))
        font = QFont("Arial", 9, QFont.Bold if self.is_directory else QFont.Normal)
        painter.setFont(font)
        
        # Truncate name if too long
        display_name = self.name
        if len(display_name) > 15:
            display_name = display_name[:12] + "..."
        
        # Center text
        text_rect = QRectF(self.padding, self.padding, 
                          self.width - 2 * self.padding, 
                          self.height - 2 * self.padding)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, display_name)
        
        # Draw size if file
        if not self.is_directory and self.size > 0:
            size_text = self._format_size(self.size)
            font_small = QFont("Arial", 7)
            painter.setFont(font_small)
            painter.setPen(QPen(self.text_color))
            size_rect = QRectF(self.padding, self.height - 20, 
                              self.width - 2 * self.padding, 15)
            painter.drawText(size_rect, Qt.AlignCenter, size_text)
    
    def _format_size(self, size_bytes):
        """Format size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    def add_child(self, child):
        """Add a child node."""
        self.children.append(child)
        child.level = self.level + 1
    
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.LeftButton:
            self.setSelected(True)
        super().mousePressEvent(event)


class MindMapView(QGraphicsView):
    """Custom graphics view for the mind map."""
    
    node_clicked = Signal(object)  # Signal emitted when a node is clicked
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Enable scrolling
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Background color
        self.setBackgroundBrush(QBrush(QColor(240, 240, 240)))
        
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 3.0
        
    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        # Zoom with Ctrl+Wheel
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            super().wheelEvent(event)
    
    def zoom_in(self):
        """Zoom in."""
        if self.scale_factor < self.max_scale:
            self.scale_factor *= 1.15
            self.scale(1.15, 1.15)
    
    def zoom_out(self):
        """Zoom out."""
        if self.scale_factor > self.min_scale:
            self.scale_factor /= 1.15
            self.scale(1.0 / 1.15, 1.0 / 1.15)
    
    def reset_zoom(self):
        """Reset zoom to 100%."""
        self.scale(1.0 / self.scale_factor, 1.0 / self.scale_factor)
        self.scale_factor = 1.0
    
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and isinstance(item, FileNode):
                self.node_clicked.emit(item)
        super().mousePressEvent(event)


class MindMapWorker(QThread):
    """Worker thread for building mind map structure."""
    
    # Signals to communicate with main thread
    node_created = Signal(str, str, bool, int, str)  # name, path, is_directory, size, parent_path
    status_update = Signal(str)  # Status message
    finished_signal = Signal(bool, str)  # Success, message
    
    def __init__(self, image_handler, start_offset, max_depth, max_children):
        super().__init__()
        self.image_handler = image_handler
        self.start_offset = start_offset
        self.max_depth = max_depth
        self.max_children = max_children
        self.cancelled = False
        self.nodes_data = []  # Store node data to emit
        
    def cancel(self):
        """Cancel the generation."""
        self.cancelled = True
    
    def run(self):
        """Run the mind map generation."""
        try:
            self.status_update.emit("Starting mind map generation...")
            
            # Traverse file system and collect node data
            self._traverse_directory(self.start_offset, "/", None, 0, None)
            
            # Emit all collected nodes
            for node_data in self.nodes_data:
                if self.cancelled:
                    break
                name, path, is_directory, size, parent_path = node_data
                self.node_created.emit(name, path, is_directory, size, parent_path)
            
            if not self.cancelled:
                self.status_update.emit("Mind map generation completed!")
                self.finished_signal.emit(True, "Mind map generated successfully!")
            else:
                self.finished_signal.emit(False, "Mind map generation cancelled.")
                
        except Exception as e:
            self.finished_signal.emit(False, f"Error: {str(e)}")
    
    def _traverse_directory(self, start_offset, path, parent_path, current_depth, parent_inode):
        """Recursively traverse directory structure."""
        if self.cancelled or current_depth >= self.max_depth:
            return
        
        try:
            # Get directory contents
            entries = self.image_handler.get_directory_contents(start_offset, parent_inode)
            if not entries:
                return
            
            # Limit number of children
            entries = entries[:self.max_children]
            
            child_count = 0
            for entry in entries:
                if self.cancelled or child_count >= self.max_children:
                    break
                
                try:
                    name = entry.get("name", "")
                    if not name:
                        continue
                    
                    is_directory = entry.get("is_directory", False)
                    size = entry.get("size", 0)
                    entry_inode = entry.get("inode_number")
                    
                    # Create full path
                    if path == "/":
                        full_path = f"/{name}"
                    else:
                        full_path = f"{path}/{name}"
                    
                    # Store node data
                    self.nodes_data.append((name, full_path, is_directory, size, path))
                    
                    # Recursively traverse if directory
                    if is_directory and entry_inode:
                        self._traverse_directory(start_offset, full_path, path, current_depth + 1, entry_inode)
                    
                    child_count += 1
                    
                except Exception as e:
                    # Skip problematic entries
                    continue
                    
        except Exception as e:
            # Skip problematic directories
            pass


class MindMapWidget(QWidget):
    """Main widget for the mind map visualization."""
    
    def __init__(self, image_handler=None, parent=None):
        super().__init__(parent)
        self.image_handler = image_handler
        self.scene = QGraphicsScene(self)
        self.nodes = {}  # Dictionary to store nodes by path
        self.inode_map = {}  # Dictionary to store inode numbers by path
        self.root_node = None
        self.max_depth = 3  # Maximum depth to traverse
        self.max_children = 50  # Maximum children per node
        self.layout_spacing = 200  # Horizontal spacing between levels
        self.level_spacing = 100  # Vertical spacing between nodes
        
        self.worker_thread = None
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.generate_btn = QPushButton("Generate Mind Map")
        self.generate_btn.clicked.connect(self.generate_mind_map)
        toolbar.addWidget(self.generate_btn)
        
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_map)
        toolbar.addWidget(self.clear_btn)
        
        toolbar.addStretch()
        
        # Zoom controls
        zoom_label = QLabel("Zoom:")
        toolbar.addWidget(zoom_label)
        
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setMaximumWidth(30)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        toolbar.addWidget(self.zoom_in_btn)
        
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setMaximumWidth(30)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        toolbar.addWidget(self.zoom_out_btn)
        
        self.reset_zoom_btn = QPushButton("Reset")
        self.reset_zoom_btn.setMaximumWidth(50)
        self.reset_zoom_btn.clicked.connect(self.reset_zoom)
        toolbar.addWidget(self.reset_zoom_btn)
        
        toolbar.addStretch()
        
        # Settings
        settings_label = QLabel("Max Depth:")
        toolbar.addWidget(settings_label)
        
        self.depth_spin = QSpinBox()
        self.depth_spin.setMinimum(1)
        self.depth_spin.setMaximum(10)
        self.depth_spin.setValue(self.max_depth)
        self.depth_spin.valueChanged.connect(self.set_max_depth)
        toolbar.addWidget(self.depth_spin)
        
        children_label = QLabel("Max Children:")
        toolbar.addWidget(children_label)
        
        self.children_spin = QSpinBox()
        self.children_spin.setMinimum(10)
        self.children_spin.setMaximum(500)
        self.children_spin.setValue(self.max_children)
        self.children_spin.valueChanged.connect(self.set_max_children)
        toolbar.addWidget(self.children_spin)
        
        layout.addLayout(toolbar)
        
        # Splitter for view and details
        splitter = QSplitter(Qt.Horizontal)
        
        # Graphics view
        self.view = MindMapView()
        self.view.setScene(self.scene)
        self.view.node_clicked.connect(self.on_node_clicked)
        splitter.addWidget(self.view)
        
        # Details panel
        details_group = QGroupBox("Node Details")
        details_layout = QVBoxLayout()
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumWidth(300)
        details_layout.addWidget(self.details_text)
        
        details_group.setLayout(details_layout)
        splitter.addWidget(details_group)
        
        splitter.setSizes([800, 300])
        layout.addWidget(splitter)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.setVisible(False)
        layout.addWidget(self.status_text)
        
        self.setLayout(layout)
    
    def set_image_handler(self, image_handler):
        """Set the image handler."""
        self.image_handler = image_handler
    
    def set_max_depth(self, depth):
        """Set maximum traversal depth."""
        self.max_depth = depth
    
    def set_max_children(self, children):
        """Set maximum children per node."""
        self.max_children = children
    
    def clear_map(self):
        """Clear the mind map."""
        self.scene.clear()
        self.nodes = {}
        self.inode_map = {}
        self.root_node = None
        self.status_text.clear()
    
    def zoom_in(self):
        """Zoom in the view."""
        self.view.zoom_in()
    
    def zoom_out(self):
        """Zoom out the view."""
        self.view.zoom_out()
    
    def reset_zoom(self):
        """Reset zoom to 100%."""
        self.view.reset_zoom()
    
    def generate_mind_map(self):
        """Generate the mind map from the file system."""
        if not self.image_handler:
            QMessageBox.warning(self, "No Image", "Please load an image first.")
            return
        
        # Clear existing map
        self.clear_map()
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.status_text.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_text.append("Starting mind map generation...")
        
        # Get partitions
        partitions = self.image_handler.get_partitions()
        if not partitions:
            QMessageBox.warning(self, "No Partitions", "No partitions found in the image.")
            self.progress_bar.setVisible(False)
            return
        
        # Use first partition with filesystem
        partition = None
        for addr, desc, start, length in partitions:
            if self.image_handler.has_filesystem(start):
                partition = (addr, desc, start, length)
                break
        
        if not partition:
            QMessageBox.warning(self, "No Filesystem", "No filesystem found in the partitions.")
            self.progress_bar.setVisible(False)
            return
        
        addr, desc, start_offset, length = partition
        
        # Generate in background thread
        self.generate_btn.setEnabled(False)
        
        # Create and start worker thread
        self.worker_thread = MindMapWorker(
            self.image_handler, 
            start_offset, 
            self.max_depth, 
            self.max_children
        )
        
        # Connect signals
        self.worker_thread.node_created.connect(self._on_node_created)
        self.worker_thread.status_update.connect(self._on_status_update)
        self.worker_thread.finished_signal.connect(self._on_generation_complete)
        
        # Start thread
        self.worker_thread.start()
    
    def _on_node_created(self, name, path, is_directory, size, parent_path):
        """Handle node creation signal from worker thread."""
        # Create root node if needed
        if not self.root_node:
            root_name = "Root"
            root_node = FileNode(root_name, is_directory=True, path="/")
            root_node.level = 0
            self.root_node = root_node
            self.scene.addItem(root_node)
            root_node.setPos(0, 0)
            self.nodes["/"] = root_node
            self.inode_map["/"] = None
        
        # Get parent node
        parent_node = self.nodes.get(parent_path) if parent_path else self.root_node
        if not parent_node:
            return
        
        # Create node
        node = FileNode(name, is_directory, size, path)
        node.level = parent_node.level + 1
        
        # Add to scene
        self.scene.addItem(node)
        self.nodes[path] = node
        
        # Add as child
        parent_node.add_child(node)
    
    def _on_status_update(self, message):
        """Handle status update from worker thread."""
        self.status_text.append(message)
    
    def _layout_nodes(self, root_node):
        """Layout nodes in a hierarchical tree structure."""
        if not root_node:
            return
        
        # First pass: calculate positions using recursive layout
        def calculate_positions(node, x, y, level_widths):
            """Recursively calculate node positions."""
            if node.level not in level_widths:
                level_widths[node.level] = []
            
            # Position node
            node.setPos(x * self.layout_spacing, y * self.level_spacing)
            level_widths[node.level].append(x)
            
            # Position children
            if node.children:
                child_y = y + 1
                num_children = len(node.children)
                child_x_start = x - (num_children - 1) / 2
                
                for i, child in enumerate(node.children):
                    child_x = child_x_start + i
                    calculate_positions(child, child_x, child_y, level_widths)
        
        level_widths = {}
        calculate_positions(root_node, 0, 0, level_widths)
        
        # Second pass: draw connection lines
        def draw_connections(node):
            """Recursively draw connection lines."""
            for child in node.children:
                # Create connection line
                line = self.scene.addLine(
                    node.pos().x() + node.width / 2,
                    node.pos().y() + node.height,
                    child.pos().x() + child.width / 2,
                    child.pos().y(),
                    QPen(QColor(100, 100, 100), 2)
                )
                line.setZValue(-1)  # Behind nodes
                
                # Recursively draw connections for children
                draw_connections(child)
        
        draw_connections(root_node)
        
        # Adjust scene rect
        self.scene.setSceneRect(self.scene.itemsBoundingRect())
    
    def _on_generation_complete(self, success, message):
        """Handle mind map generation completion."""
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Layout nodes after all nodes are created
        if success and self.root_node:
            self._layout_nodes(self.root_node)
        
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)
        
        # Clean up thread
        if self.worker_thread:
            self.worker_thread.wait()
            self.worker_thread = None
    
    def on_node_clicked(self, node):
        """Handle node click event."""
        if not node:
            return
        
        # Update details text
        details = f"Name: {node.name}\n"
        details += f"Type: {'Directory' if node.is_directory else 'File'}\n"
        details += f"Path: {node.path}\n"
        details += f"Level: {node.level}\n"
        
        if not node.is_directory:
            details += f"Size: {node._format_size(node.size)}\n"
        
        details += f"Children: {len(node.children)}\n"
        
        self.details_text.setText(details)
        
        # Highlight node
        node.setSelected(True)

