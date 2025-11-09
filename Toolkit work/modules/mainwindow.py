import configparser
import hashlib
import os
import zipfile
import io
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QIcon, QFont, QPalette, QBrush, QAction, QActionGroup
from PySide6.QtWidgets import (QMainWindow, QMenuBar, QMenu, QToolBar, QDockWidget, QTreeWidget, QTabWidget,
                               QFileDialog, QTreeWidgetItem, QTableWidget, QMessageBox, QTableWidgetItem,
                               QDialog, QVBoxLayout, QInputDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
                               QFormLayout, QApplication)

from managers.database_manager import DatabaseManager
from managers.evidence_utils import ImageHandler
from managers.image_manager import ImageManager
from modules.about import AboutDialog
from modules.converter import Main
from modules.exif_tab import ExifViewer
from modules.file_carving import FileCarvingWidget
from modules.hex_tab import HexViewer
from modules.list_files import FileSearchWidget
from modules.metadata_tab import MetadataViewer
from modules.registry import RegistryExtractor
from modules.text_tab import TextViewer
from modules.unified_application_manager import UnifiedViewer
from modules.verification import VerificationWidget
from modules.veriphone_api import VeriphoneWidget
from modules.virus_total_tab import VirusTotal
from modules.file_acquisition import FileAcquisitionDialog, ImageToE01ConversionDialog
from modules.mind_map import MindMapWidget

SECTOR_SIZE = 512


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Initialize instance attributes
        self.image_mounted = False
        self.current_offset = None
        self.current_image_path = None
        self.image_handler = None
        self.image_manager = ImageManager()
        self.db_manager = DatabaseManager('tools/new_database_mappings.db')
        self.current_selected_data = None

        self.evidence_files = []

        self.image_manager.operationCompleted.connect(
            lambda success, message: (
                QMessageBox.information(self, "Image Operation", message) if success else QMessageBox.critical(self,
                                                                                                               "Image "
                                                                                                               "Operation",
                                                                                                               message),
                setattr(self, "image_mounted", not self.image_mounted) if success else None)[1])

        # # Load existing API keys
        self.api_keys = configparser.ConfigParser()
        self.api_keys.read('config.ini')

        self.initialize_ui()

    def initialize_ui(self):
        self.setWindowTitle('Trace 1.0.1')
        self.setWindowIcon(QIcon('Icons/logo_prev_ui.png'))

        if os.name == 'nt':
            import ctypes
            myappid = 'Trace'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        self.setGeometry(100, 100, 1200, 800)

        menu_bar = QMenuBar(self)
        file_actions = {
            'Add Evidence File': self.load_image_evidence,
            'Remove Evidence File': self.remove_image_evidence,
            'separator': None,  # This will add a separator
            'File Acquisition': self.open_file_acquisition,
            'Convert to E01': self.open_convert_to_e01,
            'separator2': None,  # This will add a separator
            'Image Mounting': self.image_manager.mount_image,
            'Image Unmounting': self.image_manager.dismount_image,
            'separator3': None,  # This will add a separator
            'Exit': self.close
        }

        self.create_menu(menu_bar, 'File', file_actions)

        view_menu = QMenu('View', self)

        # Create the "Full Screen" action and connect it to the showFullScreen slot
        full_screen_action = QAction("Full Screen", self)
        full_screen_action.triggered.connect(self.showFullScreen)
        view_menu.addAction(full_screen_action)

        # Create the "Normal Screen" action and connect it to the showNormal slot
        normal_screen_action = QAction("Normal Screen", self)
        normal_screen_action.triggered.connect(self.showNormal)
        view_menu.addAction(normal_screen_action)

        # Add a separator
        view_menu.addSeparator()

        # **Add Theme Selection Actions**
        # Create an action group for themes
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)  # Only one theme can be selected at a time

        # Light Theme Action
        light_theme_action = QAction("Light Mode", self)
        light_theme_action.setCheckable(True)
        light_theme_action.setChecked(True)  # Set Light Theme as default
        light_theme_action.triggered.connect(lambda: self.apply_stylesheet('light'))
        theme_group.addAction(light_theme_action)
        view_menu.addAction(light_theme_action)

        # Dark Theme Action
        dark_theme_action = QAction("Dark Mode", self)
        dark_theme_action.setCheckable(True)
        dark_theme_action.triggered.connect(lambda: self.apply_stylesheet('dark'))
        theme_group.addAction(dark_theme_action)
        view_menu.addAction(dark_theme_action)

        # Add the view menu to the menu bar
        menu_bar.addMenu(view_menu)

        # **Apply the default stylesheet**
        self.apply_stylesheet('light')

        tools_menu = QMenu('Tools', self)

        verify_image_action = QAction("Verify Image", self)
        verify_image_action.triggered.connect(self.verify_image)
        tools_menu.addAction(verify_image_action)

        conversion_action = QAction("Convert E01 to DD/RAW", self)
        conversion_action.triggered.connect(self.show_conversion_widget)
        tools_menu.addAction(conversion_action)

        veriphone_api_action = QAction("Veriphone API", self)
        veriphone_api_action.triggered.connect(self.show_veriphone_widget)
        tools_menu.addAction(veriphone_api_action)

        help_menu = QMenu('Help', self)
        help_menu.addAction("About")
        help_menu.triggered.connect(lambda: AboutDialog(self).exec_())

        # Add "Options" menu for API key configuration
        options_menu = QMenu('Options', self)
        api_key_action = QAction("API Keys", self)
        api_key_action.triggered.connect(self.show_api_key_dialog)
        options_menu.addAction(api_key_action)

        menu_bar.addMenu(view_menu)
        menu_bar.addMenu(tools_menu)
        menu_bar.addMenu(help_menu)
        menu_bar.addMenu(options_menu)

        self.setMenuBar(menu_bar)

        self.main_toolbar = QToolBar('Main Toolbar', self)
        self.main_toolbar.setToolTip("Main Toolbar")

        # add load image button to the toolbar
        load_image_action = QAction(QIcon('Icons/icons8-evidence-48.png'), "Load Image", self)
        load_image_action.triggered.connect(self.load_image_evidence)
        self.main_toolbar.addAction(load_image_action)

        # add remove image button to the toolbar
        remove_image_action = QAction(QIcon('Icons/icons8-evidence-96.png'), "Remove Image", self)
        remove_image_action.triggered.connect(self.remove_image_evidence)
        self.main_toolbar.addAction(remove_image_action)

        # add the separator
        self.main_toolbar.addSeparator()

        # Initialize and add the verify image action
        self.verify_image_button = QAction(QIcon('Icons/icons8-verify-blue.png'), "Verify Image", self)
        self.verify_image_button.triggered.connect(self.verify_image)
        self.main_toolbar.addAction(self.verify_image_button)

        # add the separator
        self.main_toolbar.addSeparator()

        # Initialize and add the mount image action
        self.mount_image_button = QAction(QIcon('Icons/devices/icons8-hard-disk-48.png'), "Mount Image", self)
        self.mount_image_button.triggered.connect(self.image_manager.mount_image)
        self.main_toolbar.addAction(self.mount_image_button)

        # Initialize and add the unmount image action
        self.unmount_image_button = QAction(QIcon('Icons/devices/icons8-hard-disk-48_red.png'), "Unmount Image",
                                            self)
        self.unmount_image_button.triggered.connect(self.image_manager.dismount_image)
        self.main_toolbar.addAction(self.unmount_image_button)

        self.addToolBar(Qt.TopToolBarArea, self.main_toolbar)

        self.tree_viewer = QTreeWidget(self)
        self.tree_viewer.setIconSize(QSize(16, 16))
        self.tree_viewer.setHeaderHidden(True)
        self.tree_viewer.itemExpanded.connect(self.on_item_expanded)
        self.tree_viewer.itemClicked.connect(self.on_item_clicked)
        self.tree_viewer.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_viewer.customContextMenuRequested.connect(self.open_tree_context_menu)

        tree_dock = QDockWidget('Tree View', self)

        tree_dock.setWidget(self.tree_viewer)
        self.addDockWidget(Qt.LeftDockWidgetArea, tree_dock)

        self.result_viewer = QTabWidget(self)
        self.setCentralWidget(self.result_viewer)

        self.listing_table = QTableWidget()
        self.listing_table.setSortingEnabled(True)
        self.listing_table.verticalHeader().setVisible(False)

        # Use alternate row colors
        self.listing_table.setAlternatingRowColors(True)
        self.listing_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.listing_table.setIconSize(QSize(24, 24))
        self.listing_table.setColumnCount(8)

        # Set the horizontal header with dynamic resizing
        header = self.listing_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Name column stretches dynamically
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Inode column resizes based on content
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Type column resizes based on content
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Size column resizes based on content
        header.setSectionResizeMode(4, QHeaderView.Stretch)  # Created Date column stretches dynamically
        header.setSectionResizeMode(5, QHeaderView.Stretch)  # Accessed Date column stretches dynamically
        header.setSectionResizeMode(6, QHeaderView.Stretch)  # Modified Date column stretches dynamically
        header.setSectionResizeMode(7, QHeaderView.Stretch)  # Changed Date column stretches dynamically

        # Set the header labels
        self.listing_table.setHorizontalHeaderLabels(
            ['Name', 'Inode', 'Type', 'Size', 'Created Date', 'Accessed Date', 'Modified Date', 'Changed Date']
        )

        self.listing_table.itemDoubleClicked.connect(self.on_listing_table_item_clicked)
        self.listing_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listing_table.customContextMenuRequested.connect(self.open_listing_context_menu)
        self.listing_table.setSelectionBehavior(QTableWidget.SelectRows)

        # Set the color of the selected row
        palette = self.listing_table.palette()
        palette.setBrush(QPalette.Highlight, QBrush(Qt.lightGray))  # Change Qt.lightGray to your preferred color
        self.listing_table.setPalette(palette)

        header = self.listing_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft)

        self.result_viewer.addTab(self.listing_table, 'Listing')

        self.deleted_files_widget = FileCarvingWidget(self)
        self.result_viewer.addTab(self.deleted_files_widget, 'Deleted Files')

        self.registry_extractor_widget = RegistryExtractor(self.image_handler)
        self.result_viewer.addTab(self.registry_extractor_widget, 'Registry')

        # #add tab for displaying all files chosen by user
        self.file_search_widget = FileSearchWidget(self.image_handler)
        self.result_viewer.addTab(self.file_search_widget, 'File Search')

        self.viewer_tab = QTabWidget(self)

        self.hex_viewer = HexViewer(self)
        self.viewer_tab.addTab(self.hex_viewer, 'Hex')

        self.text_viewer = TextViewer(self)
        self.viewer_tab.addTab(self.text_viewer, 'Text')

        self.application_viewer = UnifiedViewer(self)
        self.application_viewer.layout.setContentsMargins(0, 0, 0, 0)
        self.application_viewer.layout.setSpacing(0)
        self.viewer_tab.addTab(self.application_viewer, 'Application')

        self.metadata_viewer = MetadataViewer(self.image_handler)
        self.viewer_tab.addTab(self.metadata_viewer, 'File Metadata')

        self.exif_viewer = ExifViewer(self)
        self.viewer_tab.addTab(self.exif_viewer, 'Exif Data')

        self.virus_total_api = VirusTotal()
        self.viewer_tab.addTab(self.virus_total_api, 'Virus Total API')

        # Set the API key if it exists
        virus_total_key = self.api_keys.get('API_KEYS', 'virustotal', fallback='')
        self.virus_total_api.set_api_key(virus_total_key)

        # Mind Map tab
        self.mind_map_widget = MindMapWidget(self.image_handler, self)
        self.viewer_tab.addTab(self.mind_map_widget, 'Mind Map')

        self.viewer_dock = QDockWidget('Utils', self)
        self.viewer_dock.setWidget(self.viewer_tab)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.viewer_dock)

        self.viewer_dock.setMinimumSize(1200, 222)
        self.viewer_dock.setMaximumSize(1200, 222)
        self.viewer_dock.visibilityChanged.connect(self.on_viewer_dock_focus)
        self.viewer_tab.currentChanged.connect(self.display_content_for_active_tab)

        # disable all tabs before loading an image file
        self.enable_tabs(False)

    def apply_stylesheet(self, theme='light'):
        if theme == 'dark':
            qss_file = 'styles/dark_theme.qss'
        else:
            qss_file = 'styles/light_theme.qss'  # Ensure your existing QSS file is named 'light_theme.qss'

        try:
            with open(qss_file, 'r') as f:
                stylesheet = f.read()
            QApplication.instance().setStyleSheet(stylesheet)
        except Exception as e:
            print(f"Error loading stylesheet {qss_file}: {e}")

    def show_api_key_dialog(self):
        # Create a dialog to get API keys from the user
        dialog = QDialog(self)
        dialog.setWindowTitle("API Key Configuration")
        dialog.setFixedWidth(600)  # Set a fixed width to accommodate longer API keys

        # Set layout as a form layout for better presentation
        layout = QFormLayout()
        layout.setSpacing(10)  # Add some spacing between fields
        layout.setContentsMargins(15, 15, 15, 15)  # Set content margins for better visual aesthetics

        # VirusTotal API Key
        virus_total_label = QLabel("VirusTotal API Key:")
        virus_total_input = QLineEdit()
        virus_total_input.setText(self.api_keys.get('API_KEYS', 'virustotal', fallback=''))
        virus_total_input.setMinimumWidth(400)  # Set a minimum width for the input field
        layout.addRow(virus_total_label, virus_total_input)

        # Veriphone API Key
        veriphone_label = QLabel("Veriphone API Key:")
        veriphone_input = QLineEdit()
        veriphone_input.setText(self.api_keys.get('API_KEYS', 'veriphone', fallback=''))
        veriphone_input.setMinimumWidth(400)  # Set a minimum width for the input field
        layout.addRow(veriphone_label, veriphone_input)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(
            lambda: self.save_api_keys(virus_total_input.text(), veriphone_input.text(), dialog))
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)

        # Set layout and execute dialog
        dialog.setLayout(layout)
        dialog.exec_()

    def save_api_keys(self, virus_total_key, veriphone_key, dialog):
        # Save the API keys in a configuration file
        if not self.api_keys.has_section('API_KEYS'):
            self.api_keys.add_section('API_KEYS')

        self.api_keys.set('API_KEYS', 'virustotal', virus_total_key)
        self.api_keys.set('API_KEYS', 'veriphone', veriphone_key)

        with open('config.ini', 'w') as config_file:
            self.api_keys.write(config_file)

        dialog.accept()

        # Pass the updated API keys to the appropriate modules
        self.virus_total_api.set_api_key(virus_total_key)

        # Set Veriphone API key only if the widget is created
        if hasattr(self, 'veriphone_widget'):
            self.veriphone_widget.set_api_key(veriphone_key)

    def show_conversion_widget(self):
        # Show the conversion widget
        self.select_dialog = Main()
        self.select_dialog.show()

    def show_veriphone_widget(self):
        # Create the VeriphoneWidget only if it hasn't been created yet
        if not hasattr(self, 'veriphone_widget'):
            self.veriphone_widget = VeriphoneWidget()
            # Set the API key after creating the widget
            veriphone_key = self.api_keys.get('API_KEYS', 'veriphone', fallback='')
            self.veriphone_widget.set_api_key(veriphone_key)
        self.veriphone_widget.show()

    def verify_image(self):
        if self.image_handler is None:
            QMessageBox.warning(self, "Verify Image", "No image is currently loaded.")
            return

        # Show the verification widget (assuming it handles its own verification logic)
        self.verification_widget = VerificationWidget(self.image_handler)
        self.verification_widget.show()

        if self.verification_widget.is_verified:
            self.verify_image_button.setIcon(QIcon('Icons/icons8-verify-48_gren.png'))
        else:
            self.verify_image_button.setIcon(QIcon('Icons/icons8-verify-blue.png'))

    def enable_tabs(self, state):
        self.result_viewer.setEnabled(state)
        self.viewer_tab.setEnabled(state)
        self.listing_table.setEnabled(state)
        self.deleted_files_widget.setEnabled(state)
        self.registry_extractor_widget.setEnabled(state)

    def create_menu(self, menu_bar, menu_name, actions):
        menu = QMenu(menu_name, self)
        for action_name, action_function in actions.items():
            if action_name.startswith('separator') or action_function is None:
                menu.addSeparator()
            else:
                action = menu.addAction(action_name)
                action.triggered.connect(action_function)
        menu_bar.addMenu(menu)
        return menu

    @staticmethod
    def create_tree_item(parent, text, icon_path, data):
        item = QTreeWidgetItem(parent)
        item.setText(0, text)
        item.setIcon(0, QIcon(icon_path))
        item.setData(0, Qt.UserRole, data)
        return item

    def on_viewer_dock_focus(self, visible):
        if visible:  # If the QDockWidget is focused/visible
            self.viewer_dock.setMaximumSize(16777215, 16777215)  # Remove size constraints
        else:  # If the QDockWidget loses focus
            current_height = self.viewer_dock.size().height()  # Get the current height
            self.viewer_dock.setMinimumSize(1200, current_height)
            self.viewer_dock.setMaximumSize(1200, current_height)

    def clear_ui(self):
        self.listing_table.clearContents()
        self.listing_table.setRowCount(0)
        self.clear_viewers()
        self.current_image_path = None
        self.current_offset = None
        self.image_mounted = False
        self.file_search_widget.clear()
        self.evidence_files.clear()
        self.deleted_files_widget.clear()

    def clear_viewers(self):
        self.hex_viewer.clear_content()
        self.text_viewer.clear_content()
        self.application_viewer.clear()
        self.metadata_viewer.clear()
        self.exif_viewer.clear_content()
        self.registry_extractor_widget.clear()

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Exit Confirmation', 'Are you sure you want to exit?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            if self.image_mounted:
                dismount_reply = QMessageBox.question(self, 'Dismount Image',
                                                      'Do you want to dismount the mounted image before exiting?',
                                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                      QMessageBox.StandardButton.Yes)

                if dismount_reply == QMessageBox.StandardButton.Yes:
                    # Assuming you have a method to dismount the image
                    self.image_manager.dismount_image()

            event.accept()
        else:
            event.ignore()

    def open_file_acquisition(self):
        """Open the file acquisition dialog."""
        dialog = FileAcquisitionDialog(self)
        dialog.exec()
    
    def open_convert_to_e01(self):
        """Open the convert to E01 dialog."""
        dialog = ImageToE01ConversionDialog(self)
        dialog.exec()
    
    def load_image_evidence(self):
        """Open an image with a specific filter on Kali Linux."""
        # Define the supported image file extensions, including both lowercase and uppercase variants
        supported_image_extensions = ["*.e01", "*.E01", "*.s01", "*.S01",
                                      "*.l01", "*.L01", "*.raw", "*.RAW",
                                      "*.img", "*.IMG", "*.dd", "*.DD",
                                      "*.iso", "*.ISO", "*.ad1", "*.AD1",
                                      "*.001", "*.s01", "*.ex01", "*.dmg",
                                      "*.sparse", "*.sparseimage"]

        # Construct the file filter string with both uppercase and lowercase extensions
        file_filter = "Supported Image Files ({})".format(" ".join(supported_image_extensions))

        # Open file dialog with the specified file filter
        image_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", file_filter)

        if image_path:
            image_path = os.path.normpath(image_path)
            # Create ImageHandler (now loads only basic info, much faster)
            self.image_handler = ImageHandler(image_path)
            self.evidence_files.append(image_path)
            self.current_image_path = image_path
            # Load partitions asynchronously to avoid blocking UI
            self.load_partitions_into_tree_async(image_path)

            # Pass the image handler to the widgets
            self.deleted_files_widget.set_image_handler(self.image_handler)
            self.registry_extractor_widget.image_handler = self.image_handler
            self.file_search_widget.image_handler = self.image_handler
            # Update mind map widget with new image handler
            if hasattr(self, 'mind_map_widget'):
                self.mind_map_widget.set_image_handler(self.image_handler)
            self.metadata_viewer.image_handler = self.image_handler

            self.enable_tabs(True)

    def remove_image_evidence(self):
        if not self.evidence_files:
            QMessageBox.warning(self, "Remove Evidence", "No evidence is currently loaded.")
            return

        # Prepare the options for the dialog
        options = self.evidence_files + ["Remove All"]
        selected_option, ok = QInputDialog.getItem(self, "Remove Evidence File",
                                                   "Select an evidence file to remove or 'Remove All':",
                                                   options, 0, False)

        if ok:
            if selected_option == "Remove All":
                # Remove all evidence files
                self.tree_viewer.invisibleRootItem().takeChildren()  # Remove all children from the tree viewer
                self.clear_ui()  # Clear the UI
                QMessageBox.information(self, "Remove Evidence", "All evidence files have been removed.")
            else:
                # Remove the selected evidence file
                self.evidence_files.remove(selected_option)
                self.remove_from_tree_viewer(selected_option)
                self.clear_ui()
                QMessageBox.information(self, "Remove Evidence", f"{selected_option} has been removed.")
        # clear all tabs if there are no evidence files loaded
        if not self.evidence_files:
            self.clear_ui()
            # disable all tabs
            self.enable_tabs(False)
            # set the icon back to the original
            self.verify_image_button.setIcon(QIcon('Icons/icons8-verify-blue.png'))

    def remove_from_tree_viewer(self, evidence_name):
        root = self.tree_viewer.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.text(0) == evidence_name:
                root.removeChild(item)
                break

    def load_partitions_into_tree_async(self, image_path):
        """Load partitions from an image into the tree viewer asynchronously."""
        # Pre-fetch icon paths on main thread (SQLite must be accessed on main thread)
        media_icon = self.db_manager.get_icon_path('device', 'media-optical')
        drive_icon = self.db_manager.get_icon_path('device', 'drive-harddisk')
        unknown_icon = self.db_manager.get_icon_path('file', 'unknown')
        
        # Create root item immediately for faster UI response
        root_item_tree = self.create_tree_item(self.tree_viewer, image_path,
                                               media_icon,
                                               {"start_offset": 0})
        
        # Use ThreadPoolExecutor to load partitions in background
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._load_partitions_worker, image_path)
        future.add_done_callback(lambda f: self._on_partitions_loaded(f, root_item_tree, drive_icon, unknown_icon))

    def _load_partitions_worker(self, image_path):
        """Worker function to load partitions in background thread."""
        try:
            partitions = self.image_handler.get_partitions()
            
            # Check if the image has partitions or a recognizable file system
            if not partitions:
                has_fs = self.image_handler.has_filesystem(0)
                return {
                    'has_partitions': False,
                    'has_filesystem': has_fs,
                    'partitions': []
                }
            
            # Load partition info (defer filesystem type checking)
            partition_data = []
            for addr, desc, start, length in partitions:
                end = start + length - 1
                size_in_bytes = length * SECTOR_SIZE
                readable_size = self.image_handler.get_readable_size(size_in_bytes)
                desc_str = desc.decode('utf-8') if isinstance(desc, bytes) else desc
                
                # Skip filesystem type check here - it's slow, do it lazily
                partition_data.append({
                    'addr': addr,
                    'desc': desc_str,
                    'start': start,
                    'end': end,
                    'length': length,
                    'readable_size': readable_size
                })
            
            return {
                'has_partitions': True,
                'has_filesystem': False,
                'partitions': partition_data
            }
        except Exception as e:
            import traceback
            return {
                'error': str(e),
                'traceback': traceback.format_exc(),
                'has_partitions': False,
                'partitions': []
            }

    def _on_partitions_loaded(self, future, root_item_tree, drive_icon, unknown_icon):
        """Callback when partitions are loaded - update UI on main thread."""
        try:
            result = future.result()
            
            if result.get('error'):
                # Show error with traceback if available
                error_msg = result.get('error', 'Unknown error')
                traceback_msg = result.get('traceback', '')
                print(f"Error loading partitions: {error_msg}")
                if traceback_msg:
                    print(f"Traceback: {traceback_msg}")
                return
            
            if not result.get('has_partitions'):
                # No partitions - check for filesystem or unallocated
                if result.get('has_filesystem'):
                    # The image has a filesystem but no partitions, populate root directory
                    self.populate_contents(root_item_tree, {"start_offset": 0})
                else:
                    # Entire image is considered as unallocated space
                    size_in_bytes = self.image_handler.get_size()
                    readable_size = self.image_handler.get_readable_size(size_in_bytes)
                    unallocated_item_text = f"Unallocated Space: Size: {readable_size}"
                    self.create_tree_item(root_item_tree, unallocated_item_text,
                                          unknown_icon,
                                          {"is_unallocated": True, "start_offset": 0,
                                           "end_offset": size_in_bytes // SECTOR_SIZE})
                return

            # Add partitions to tree (filesystem type will be checked lazily on expand)
            for part_data in result['partitions']:
                addr = part_data['addr']
                desc_str = part_data['desc']
                start = part_data['start']
                end = part_data['end']
                readable_size = part_data['readable_size']
                
                # Defer filesystem type check - just show "Loading..." or skip it
                item_text = f"vol{addr} ({desc_str}: {start}-{end}, Size: {readable_size})"
                data = {"inode_number": None, "start_offset": start, "end_offset": end}
                item = self.create_tree_item(root_item_tree, item_text, drive_icon, data)

                # Determine if the partition is special or contains unallocated space
                special_partitions = ["Primary Table", "Safety Table", "GPT Header"]
                is_special = any(special_case in desc_str for special_case in special_partitions)
                is_unallocated = "Unallocated" in desc_str or "Microsoft reserved" in desc_str

                if is_special:
                    item.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicator)
                elif is_unallocated:
                    item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                    # Directly add unallocated space under the partition
                    self.create_tree_item(item, f"Unallocated Space: Size: {readable_size}",
                                          unknown_icon,
                                          {"is_unallocated": True, "start_offset": start, "end_offset": end})
                else:
                    # Always show indicator - check contents lazily on expand
                    item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        except Exception as e:
            import traceback
            print(f"Error loading partitions: {e}")
            print(f"Traceback: {traceback.format_exc()}")

    def load_partitions_into_tree(self, image_path):
        """Load partitions from an image into the tree viewer (synchronous version for compatibility)."""
        self.load_partitions_into_tree_async(image_path)

    def populate_contents(self, item, data, inode=None):
        if self.current_image_path is None:
            return

        entries = self.image_handler.get_directory_contents(data["start_offset"], inode)

        for entry in entries:
            child_item = QTreeWidgetItem(item)
            child_item.setText(0, entry["name"])

            if entry["is_directory"]:
                sub_entries = self.image_handler.get_directory_contents(data["start_offset"], entry["inode_number"])
                has_sub_entries = bool(sub_entries)

                self.populate_item(child_item, entry["name"], entry["inode_number"], data["start_offset"],
                                   is_directory=True)
                child_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ShowIndicator if has_sub_entries else QTreeWidgetItem.DontShowIndicatorWhenChildless)
            else:
                self.populate_item(child_item, entry["name"], entry["inode_number"], data["start_offset"],
                                   is_directory=False)

    def populate_item(self, child_item, entry_name, inode_number, start_offset, is_directory):
        if is_directory:
            icon_key = 'folder'
        else:
            # For files, determine the icon based on the file extension
            file_extension = entry_name.split('.')[-1].lower() if '.' in entry_name else 'unknown'
            icon_key = file_extension

        icon_path = self.db_manager.get_icon_path('folder' if is_directory else 'file', icon_key)

        child_item.setIcon(0, QIcon(icon_path))
        
        # Check if file is a ZIP file
        is_zip = False
        if not is_directory:
            is_zip = self._is_zip_file(entry_name, inode_number, start_offset)
        
        child_item.setData(0, Qt.UserRole, {
            "inode_number": inode_number,
            "type": 'directory' if is_directory else ('zip' if is_zip else 'file'),
            "start_offset": start_offset,
            "name": entry_name,
            "is_zip": is_zip
        })
        
        # If it's a ZIP file, show indicator that it can be expanded
        if is_zip:
            child_item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)

    def on_item_expanded(self, item):
        # Check if the item already has children; if so, don't repopulate
        if item.childCount() > 0:
            return

        data = item.data(0, Qt.UserRole)
        if data is None:
            return

        if data.get("inode_number") is None:  # It's a partition
            # Update partition text with filesystem type if not already shown
            start_offset = data.get("start_offset")
            if start_offset is not None:
                fs_type = self.image_handler.get_fs_type(start_offset)
                if fs_type != "N/A":
                    current_text = item.text(0)
                    if "FS:" not in current_text:
                        item.setText(0, f"{current_text}, FS: {fs_type}")
            self.populate_contents(item, data)
        elif data.get("type") == "zip":  # It's a ZIP file
            self.populate_zip_contents(item, data)
        else:  # It's a directory
            self.populate_contents(item, data, data.get("inode_number"))

    def on_item_clicked(self, item, column):
        self.clear_viewers()

        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        
        self.current_selected_data = data

        if data.get("is_unallocated"):
            # Handle unallocated space
            unallocated_space = self.image_handler.read_unallocated_space(data["start_offset"], data["end_offset"])
            if unallocated_space is not None:
                # use the update_viewer_with_file_content method to display the unallocated space for hex and text tabs
                # self.update_viewer_with_file_content(unallocated_space, None, data)
                self.update_viewer_with_file_content(unallocated_space, data)  ######
            else:
                print("Invalid size for unallocated space or unable to read.")
        elif data.get("type") == "directory":
            # # Handle directories
            entries = self.image_handler.get_directory_contents(data["start_offset"], data.get("inode_number"))
            self.populate_listing_table(entries, data["start_offset"])
        elif data.get("type") == "zip":
            # Handle ZIP files - show contents in listing table
            zip_entries = self._get_zip_contents(data["inode_number"], data["start_offset"])
            if zip_entries:
                self.populate_listing_table(zip_entries, data["start_offset"], is_zip=True)
            else:
                # If ZIP extraction fails, show the ZIP file itself
                file_content, _ = self.image_handler.get_file_content(data["inode_number"], data["start_offset"])
                if file_content:
                    self.update_viewer_with_file_content(file_content, data)
        elif data.get("type") == "zip_entry":
            # Handle ZIP entry - extract and display
            zip_parent_inode = data.get("zip_parent_inode")
            zip_parent_offset = data.get("zip_parent_offset")
            zip_path = data.get("zip_path")
            
            if zip_parent_inode and zip_path:
                if data.get("is_directory"):
                    # For directories in ZIP, show contents
                    zip_entries = self._get_zip_contents(zip_parent_inode, zip_parent_offset)
                    if zip_entries:
                        # Filter entries that are in this directory
                        dir_entries = [e for e in zip_entries if e["zip_path"].startswith(zip_path) and e["zip_path"] != zip_path]
                        if dir_entries:
                            self.populate_listing_table(dir_entries, zip_parent_offset, is_zip=True)
                else:
                    # For files in ZIP, extract and display
                    entry_content = self._extract_zip_entry(zip_parent_inode, zip_parent_offset, zip_path)
                    if entry_content:
                        # Create a data dict for the extracted content
                        entry_data = data.copy()
                        entry_data["name"] = os.path.basename(zip_path)
                        self.update_viewer_with_file_content(entry_content, entry_data)
        elif data.get("inode_number") is not None:
            # Handle files
            file_content, _ = self.image_handler.get_file_content(data["inode_number"], data[
                "start_offset"])  ##################################
            if file_content:
                self.update_viewer_with_file_content(file_content, data)
            else:
                print("Unable to read file content.")
        elif data.get("start_offset") is not None:
            # Handle partitions
            entries = self.image_handler.get_directory_contents(data["start_offset"], 5)  # 5 is the root inode for NTFS
            self.populate_listing_table(entries, data["start_offset"])
        else:
            print("Clicked item is not a file, directory, or unallocated space.")

        self.display_content_for_active_tab()

    def display_content_for_active_tab(self):
        if not self.current_selected_data:
            return

        inode_number = self.current_selected_data.get("inode_number")
        offset = self.current_selected_data.get("start_offset", self.current_offset)

        if inode_number:
            file_content, _ = self.image_handler.get_file_content(inode_number, offset)
            if file_content:
                self.update_viewer_with_file_content(file_content, self.current_selected_data)  # Use the stored data

    def update_viewer_with_file_content(self, file_content, data):
        index = self.viewer_tab.currentIndex()
        if index == 0:  # Hex tab
            self.hex_viewer.display_hex_content(file_content)
        elif index == 1:  # Text tab
            self.text_viewer.display_text_content(file_content)
        elif index == 2:  # Application tab
            full_file_path = data.get("name", "")  # Retrieve the name from the data dictionary
            self.application_viewer.display_application_content(file_content, full_file_path)
        elif index == 3:  # File Metadata tab
            self.metadata_viewer.display_metadata(data)

        elif index == 4:  # Exif Data tab
            self.exif_viewer.load_and_display_exif_data(file_content)
        elif index == 5:  # Assuming VirusTotal tab is the 6th tab (0-based index)
            file_hash = hashlib.md5(file_content).hexdigest()
            self.virus_total_api.set_file_hash(file_hash)
            self.virus_total_api.set_file_content(file_content, data.get("name", ""))

    def populate_listing_table(self, entries, offset, is_zip=False):
        self.listing_table.setRowCount(0)

        for entry in entries:
            entry_name = entry["name"]
            # For ZIP entries, inode_number is None, use a placeholder
            inode_number = entry.get("inode_number") if not is_zip else -1
            description = "Directory" if entry["is_directory"] else "File"
            size_in_bytes = entry["size"] if "size" in entry else 0
            # readable_size = self.get_readable_size(size_in_bytes)
            readable_size = self.image_handler.get_readable_size(size_in_bytes)
            created = entry["created"] if "created" in entry else None
            accessed = entry["accessed"] if "accessed" in entry else None
            modified = entry["modified"] if "modified" in entry else None
            changed = entry["changed"] if "changed" in entry else None
            icon_name, icon_type = ('folder', 'folder') if entry["is_directory"] else (
                'file', entry_name.split('.')[-1].lower() if '.' in entry_name else 'unknown')

            # Store ZIP entry info in data if it's a ZIP entry
            zip_data = None
            if is_zip:
                zip_data = {
                    "type": "zip_entry",
                    "zip_path": entry.get("zip_path", entry_name),
                    "zip_parent_inode": entry.get("zip_parent_inode"),
                    "zip_parent_offset": entry.get("zip_parent_offset", offset),
                    "is_directory": entry["is_directory"]
                }

            self.insert_row_into_listing_table(entry_name, inode_number, description, icon_type, icon_name, offset,
                                               readable_size, created, accessed, modified, changed, zip_data=zip_data)

    def insert_row_into_listing_table(self, entry_name, entry_inode, description, icon_name, icon_type, offset, size,
                                      created, accessed, modified, changed, zip_data=None):
        icon_path = self.db_manager.get_icon_path(icon_type, icon_name)
        icon = QIcon(icon_path)
        row_position = self.listing_table.rowCount()
        self.listing_table.insertRow(row_position)

        name_item = QTableWidgetItem(entry_name)
        name_item.setIcon(icon)
        
        # Build data dictionary
        item_data = {
            "inode_number": entry_inode,
            "start_offset": offset,
            "type": "directory" if icon_type == 'folder' else 'file',
            "name": entry_name,
            "size": size,
        }
        
        # Add ZIP data if provided
        if zip_data:
            item_data.update(zip_data)
        
        name_item.setData(Qt.UserRole, item_data)

        self.listing_table.setItem(row_position, 0, name_item)
        self.listing_table.setItem(row_position, 1, QTableWidgetItem(str(entry_inode)))
        self.listing_table.setItem(row_position, 2, QTableWidgetItem(description))
        self.listing_table.setItem(row_position, 3, QTableWidgetItem(size))
        self.listing_table.setItem(row_position, 4, QTableWidgetItem(str(created)))
        self.listing_table.setItem(row_position, 5, QTableWidgetItem(str(accessed)))
        self.listing_table.setItem(row_position, 6, QTableWidgetItem(str(modified)))
        self.listing_table.setItem(row_position, 7, QTableWidgetItem(str(changed)))

    def on_listing_table_item_clicked(self, item):
        row = item.row()
        column = item.column()

        inode_item = self.listing_table.item(row, 1)
        if not inode_item:
            return
        
        try:
            inode_number = int(inode_item.text())
        except (ValueError, AttributeError):
            return
        
        name_item = self.listing_table.item(row, 0)
        if not name_item:
            return
        
        data = name_item.data(Qt.UserRole)
        if not data:
            return

        self.current_selected_data = data

        if data.get("type") == "directory":
            entries = self.image_handler.get_directory_contents(data["start_offset"], inode_number)
            self.populate_listing_table(entries, data["start_offset"])
        elif data.get("type") == "zip_entry":
            # Handle ZIP entry - extract and display
            zip_parent_inode = data.get("zip_parent_inode")
            zip_parent_offset = data.get("zip_parent_offset")
            zip_path = data.get("zip_path")
            
            if zip_parent_inode and zip_path:
                if data.get("is_directory"):
                    # For directories in ZIP, show contents
                    zip_entries = self._get_zip_contents(zip_parent_inode, zip_parent_offset)
                    if zip_entries:
                        # Filter entries that are in this directory
                        dir_entries = [e for e in zip_entries if e["zip_path"].startswith(zip_path) and e["zip_path"] != zip_path]
                        if dir_entries:
                            self.populate_listing_table(dir_entries, zip_parent_offset, is_zip=True)
                else:
                    # For files in ZIP, extract and display
                    entry_content = self._extract_zip_entry(zip_parent_inode, zip_parent_offset, zip_path)
                    if entry_content:
                        # Create a data dict for the extracted content
                        entry_data = data.copy()
                        entry_data["name"] = os.path.basename(zip_path)
                        self.update_viewer_with_file_content(entry_content, entry_data)
        elif data.get("type") == "zip":
            # Handle ZIP files - show contents in listing table
            zip_entries = self._get_zip_contents(inode_number, data["start_offset"])
            if zip_entries:
                self.populate_listing_table(zip_entries, data["start_offset"], is_zip=True)
            else:
                # If ZIP extraction fails, show the ZIP file itself
                file_content, metadata = self.image_handler.get_file_content(inode_number, data["start_offset"])
                if file_content:
                    self.update_viewer_with_file_content(file_content, data)
        else:
            file_content, metadata = self.image_handler.get_file_content(inode_number, data["start_offset"])
            if file_content:
                self.update_viewer_with_file_content(file_content, data)

        # Call this to make sure the content is displayed based on the active tab
        self.display_content_for_active_tab()

    def open_listing_context_menu(self, position):
        # Get the selected item
        indexes = self.listing_table.selectedIndexes()
        if indexes:
            selected_item = self.listing_table.item(indexes[0].row(),
                                                    0)  # Assuming the first column contains the item data
            data = selected_item.data(Qt.UserRole)
            menu = QMenu()

            # Add the 'Export' option for any file or folder
            export_action = menu.addAction("Export")
            export_action.triggered.connect(lambda: self.export_item_from_table(data))

            menu.exec_(self.listing_table.viewport().mapToGlobal(position))

    def export_item_from_table(self, data):
        dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Directory")
        if dest_dir:
            if data.get("type") == "directory":
                self.export_directory(data["inode_number"], data["start_offset"], dest_dir, data["name"])
            else:
                self.export_file(data["inode_number"], data["start_offset"], dest_dir, data["name"])

    def open_tree_context_menu(self, position):
        # Get the selected item
        indexes = self.tree_viewer.selectedIndexes()
        if indexes:
            selected_item = self.tree_viewer.itemFromIndex(indexes[0])
            menu = QMenu()

            # Check if the selected item is a root item
            if selected_item and selected_item.parent() is None:
                view_os_info_action = menu.addAction("View Image Information")
                view_os_info_action.triggered.connect(lambda: self.view_os_information(indexes[0]))

            # Add the 'Export' option for any file or folder
            export_action = menu.addAction("Export")
            export_action.triggered.connect(self.export_item)

            menu.exec_(self.tree_viewer.viewport().mapToGlobal(position))

    def export_item(self):
        indexes = self.tree_viewer.selectedIndexes()
        if indexes:
            selected_item = self.tree_viewer.itemFromIndex(indexes[0])
            data = selected_item.data(0, Qt.UserRole)
            dest_dir = QFileDialog.getExistingDirectory(self, "Select Destination Directory")
            if dest_dir:
                if data.get("type") == "directory":
                    self.export_directory(data["inode_number"], data["start_offset"], dest_dir, selected_item.text(0))
                else:
                    self.export_file(data["inode_number"], data["start_offset"], dest_dir, selected_item.text(0))

    def export_directory(self, inode_number, offset, dest_dir, dir_name):
        new_dest_dir = os.path.join(dest_dir, dir_name)
        os.makedirs(new_dest_dir, exist_ok=True)
        entries = self.image_handler.get_directory_contents(offset, inode_number)
        for entry in entries:
            entry_name = entry.get("name")
            if entry["is_directory"]:
                self.export_directory(entry["inode_number"], offset, new_dest_dir, entry_name)
            else:
                self.export_file(entry["inode_number"], offset, new_dest_dir, entry_name)

    def export_file(self, inode_number, offset, dest_dir, file_name):
        file_content, _ = self.image_handler.get_file_content(inode_number, offset)
        if file_content:
            file_path = os.path.join(dest_dir, file_name)
            with open(file_path, 'wb') as f:
                f.write(file_content)

    def view_os_information(self, index):
        item = self.tree_viewer.itemFromIndex(index)
        if item is None or item.parent() is not None:
            # Ensure that only the root item triggers the OS information display
            return

        partitions = self.image_handler.get_partitions()
        table = QTableWidget()

        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Partition", "OS Information", "File System Type"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setFont(QFont("Arial", 10, QFont.Bold))
        table.verticalHeader().setVisible(False)

        partition_icon = QIcon('Icons/devices/drive-harddisk.svg')  # Replace with your partition icon path
        os_icon = QIcon('Icons/start-here.svg')  # Replace with your OS icon path

        for row, part in enumerate(partitions):
            start_offset = part[2]  # Start offset of the partition
            fs_type = self.image_handler.get_fs_type(start_offset)

            os_version = None
            if fs_type == "NTFS":
                os_version = self.image_handler.get_windows_version(start_offset)

            table.insertRow(row)
            partition_item = QTableWidgetItem(f"Partition {part[0]}")
            partition_item.setIcon(partition_icon)
            os_version_item = QTableWidgetItem(os_version if os_version else "N/A")
            if os_version:
                os_version_item.setIcon(os_icon)
            fs_type_item = QTableWidgetItem(fs_type or "Unrecognized")

            table.setItem(row, 0, partition_item)
            table.setItem(row, 1, os_version_item)
            table.setItem(row, 2, fs_type_item)

        table.resizeRowsToContents()
        table.resizeColumnsToContents()

        # Dialog for displaying the table
        dialog = QDialog(self)
        dialog.setWindowTitle("OS and File System Information")
        dialog.resize(460, 320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(table)

        buttonBox = QDialogButtonBox(QDialogButtonBox.Ok)
        buttonBox.accepted.connect(dialog.accept)
        layout.addWidget(buttonBox)

        dialog.exec_()
    
    def _is_zip_file(self, entry_name, inode_number, start_offset):
        """Check if a file is a ZIP file by extension or magic bytes."""
        # Check by extension first (faster)
        if entry_name.lower().endswith(('.zip', '.jar', '.war', '.ear', '.apk')):
            return True
        
        # Check by magic bytes (ZIP files start with PK\x03\x04 or PK\x05\x06)
        try:
            file_content, _ = self.image_handler.get_file_content(inode_number, start_offset)
            if file_content and len(file_content) >= 4:
                # Check for ZIP magic bytes
                if file_content[:2] == b'PK':
                    # Could be ZIP, JAR, DOCX, XLSX, PPTX, etc.
                    # For now, treat all PK files as ZIP-like
                    return True
        except Exception:
            pass
        
        return False
    
    def _get_zip_contents(self, inode_number, start_offset):
        """Extract and return ZIP file contents as a list of entries."""
        try:
            file_content, _ = self.image_handler.get_file_content(inode_number, start_offset)
            if not file_content:
                return None
            
            # Check if it's actually a ZIP file
            if not (file_content[:2] == b'PK'):
                return None
            
            zip_entries = []
            zip_file = zipfile.ZipFile(io.BytesIO(file_content), 'r')
            
            for zip_info in zip_file.infolist():
                # Determine if it's a directory
                is_directory = zip_info.filename.endswith('/')
                
                # Get file size
                file_size = zip_info.file_size
                
                # Get timestamps
                date_time = zip_info.date_time
                if date_time:
                    # date_time is (year, month, day, hour, minute, second)
                    try:
                        from datetime import datetime
                        dt = datetime(*date_time)
                        created = dt.strftime('%Y-%m-%d %H:%M:%S')
                        modified = created
                        accessed = created
                        changed = created
                    except Exception:
                        created = "N/A"
                        modified = "N/A"
                        accessed = "N/A"
                        changed = "N/A"
                else:
                    created = "N/A"
                    modified = "N/A"
                    accessed = "N/A"
                    changed = "N/A"
                
                # Create entry similar to directory entries
                entry = {
                    "name": zip_info.filename.rstrip('/'),
                    "path": zip_info.filename,
                    "size": file_size,
                    "is_directory": is_directory,
                    "inode_number": None,  # ZIP entries don't have inodes
                    "created": created,
                    "accessed": accessed,
                    "modified": modified,
                    "changed": changed,
                    "zip_path": zip_info.filename,  # Store path in ZIP
                    "zip_parent_inode": inode_number,  # Store parent ZIP inode
                    "zip_parent_offset": start_offset  # Store parent ZIP offset
                }
                zip_entries.append(entry)
            
            zip_file.close()
            return zip_entries
            
        except zipfile.BadZipFile:
            return None
        except Exception as e:
            print(f"Error extracting ZIP contents: {e}")
            return None
    
    def populate_zip_contents(self, item, data):
        """Populate tree view with ZIP file contents."""
        inode_number = data.get("inode_number")
        start_offset = data.get("start_offset")
        
        zip_entries = self._get_zip_contents(inode_number, start_offset)
        if not zip_entries:
            return
        
        # Group entries by directory structure
        for entry in zip_entries:
            child_item = QTreeWidgetItem(item)
            child_item.setText(0, entry["name"])
            
            is_directory = entry["is_directory"]
            icon_key = 'folder' if is_directory else (entry["name"].split('.')[-1].lower() if '.' in entry["name"] else 'unknown')
            icon_path = self.db_manager.get_icon_path('folder' if is_directory else 'file', icon_key)
            child_item.setIcon(0, QIcon(icon_path))
            
            # Store ZIP entry data
            child_item.setData(0, Qt.UserRole, {
                "type": 'zip_entry',
                "name": entry["name"],
                "zip_path": entry["zip_path"],
                "zip_parent_inode": entry["zip_parent_inode"],
                "zip_parent_offset": entry["zip_parent_offset"],
                "is_directory": is_directory,
                "size": entry["size"],
                "start_offset": start_offset
            })
            
            # If it's a directory, show indicator
            if is_directory:
                child_item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
    
    def _extract_zip_entry(self, zip_parent_inode, zip_parent_offset, zip_path):
        """Extract a specific entry from a ZIP file."""
        try:
            file_content, _ = self.image_handler.get_file_content(zip_parent_inode, zip_parent_offset)
            if not file_content:
                return None
            
            zip_file = zipfile.ZipFile(io.BytesIO(file_content), 'r')
            entry_content = zip_file.read(zip_path)
            zip_file.close()
            return entry_content
        except Exception as e:
            print(f"Error extracting ZIP entry: {e}")
            return None
