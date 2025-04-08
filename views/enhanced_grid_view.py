# --- START REFACTORED views/enhanced_grid_view.py ---
"""
拡張グリッドビューモジュール

効率的なサムネイル表示のための拡張グリッドビュークラスを提供します。
"""
from PySide6.QtWidgets import (
    QLabel, QGridLayout, QFrame # Removed unused imports like QHBoxLayout, QComboBox, QSlider, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QPoint
from PySide6.QtGui import QResizeEvent

from .base_image_grid_view import BaseImageGridView
from .lazy_image_label import LazyImageLabel
from utils import logger # Import logger

class EnhancedGridView(BaseImageGridView):
    """
    効率的なサムネイル表示のための拡張グリッドビュークラス

    遅延読み込みとスクロール連動による最適化機能を持つグリッドビュー。
    ページネーションと表示密度の調整にも対応しています。
    """

    def __init__(self, image_model, worker_manager, parent=None):
        """
        初期化

        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            parent: 親ウィジェット
        """
        # Initialize Base Class (handles common UI, timers, size logic)
        super().__init__(image_model, worker_manager, parent)

        # --- Grid Specific Settings ---
        # Columns are calculated dynamically based on size and density
        self.columns = self.config.get(f"display.grid_columns.{self._get_density_key()}", 4)
        self.load_batch_size = self.config.get("workers.load_batch_size", 8)

        # --- Grid Layout ---
        self.grid_layout = QGridLayout(self.content_widget) # Use the content_widget from base class
        spacing = self.config.get("display.ui.grid_spacing", 5)
        margins = self.config.get("display.ui.grid_margins", 10)
        self.grid_layout.setSpacing(spacing)
        self.grid_layout.setContentsMargins(margins, margins, margins, margins)
        # Make the last column and row stretchable if needed? Usually not for fixed grids.
        # self.grid_layout.setColumnStretch(self.columns, 1) # Example if needed

        # --- Visibility Check Timer ---
        # Use a separate timer for loading visible items if needed, or rely on scroll debounce
        self.visibility_check_timer = QTimer(self)
        vis_check_interval = self.config.get("display.ui.visibility_check_interval_ms", 150)
        self.visibility_check_timer.setInterval(vis_check_interval)
        self.visibility_check_timer.timeout.connect(self.load_visible_images) # Connect to the correct method
        self.visibility_check_timer.start()

        # Initial calculation of columns
        # QTimer.singleShot(0, self.calculate_columns) # Calculate after layout is established
        self.calculate_columns() # Calculate initially

        logger.debug("EnhancedGridView initialized.")

    def _get_density_key(self) -> str:
        """Helper to get density key string."""
        return {0: "small", 1: "medium", 2: "large"}.get(self.current_density_index, "medium")

    # --- Overridden Abstract Methods ---

    def place_images(self, images: list):
        """画像をグリッドに配置 (Implementation)"""
        logger.debug(f"Placing {len(images)} images in grid layout.")
        # Ensure layout is empty before placing new items
        self.clear_grid_widgets() # Clear only widgets, not self.image_labels yet

        for i, image_path in enumerate(images):
            row, col = divmod(i, self.columns)

            # Create lazy loading label
            # Ensure thumbnail_size is current before creating label
            label = LazyImageLabel(image_path, self.thumbnail_size)
            label.image_clicked.connect(self.on_image_click) # Connect click signal

            # Add to grid layout
            self.grid_layout.addWidget(label, row, col, Qt.AlignCenter) # Align center

            # Store mapping (overwrites if path exists, which shouldn't happen with clear_grid)
            self.image_labels[image_path] = label
        # Adjust layout after adding widgets
        self.grid_layout.activate()
        self.content_widget.adjustSize() # Adjust content widget size based on layout


    def load_visible_images(self):
        """可視状態のサムネイルを読み込む (Implementation)"""
        if not self.image_labels or not self.isVisible(): # Check if widget is visible
             return

        try:
            # Get viewport geometry in global coordinates
            viewport = self.scroll_area.viewport()
            if not viewport: return # Skip if viewport not ready
            # Get visible rectangle within the scroll area's viewport
            visible_rect_local = viewport.rect()
            # logger.debug(f"Viewport rect: {visible_rect_local}")

            # Define a buffer zone (e.g., one row above and below)
            buffer_y = self.thumbnail_size.height() + self.grid_layout.spacing()
            extended_visible_rect = visible_rect_local.adjusted(0, -buffer_y, 0, buffer_y)

            labels_to_load = []
            processed_count = 0
            max_process = 200 # Limit checks per cycle to avoid freezing

            for image_path, label in self.image_labels.items():
                processed_count += 1
                if processed_count > max_process:
                     logger.warning("Visibility check limit reached, will continue next cycle.")
                     break

                # Check if label is valid and not already loaded/loading
                if not label or label.parent() is None or label.loading_state != LazyImageLabel.STATE_NOT_LOADED:
                    continue

                # Get label geometry relative to the content_widget
                label_rect_in_content = label.geometry()
                # Map the top-left corner to the viewport coordinate system
                label_top_left_in_viewport = label.mapTo(viewport, QPoint(0, 0))
                label_rect_in_viewport = QRect(label_top_left_in_viewport, label_rect_in_content.size())

                # Check for intersection with the extended visible rectangle
                if extended_visible_rect.intersects(label_rect_in_viewport):
                    labels_to_load.append((image_path, label))

                    # Limit the number of loads initiated per cycle
                    if len(labels_to_load) >= self.load_batch_size:
                        break # Stop collecting once batch size is reached


            # Request thumbnails for the collected labels
            if labels_to_load:
                 logger.debug(f"Requesting thumbnails for {len(labels_to_load)} visible labels.")
                 for path, label_widget in labels_to_load:
                     if label_widget.loading_state == LazyImageLabel.STATE_NOT_LOADED:
                         label_widget.setLoadingState(LazyImageLabel.STATE_LOADING)
                         self.thumbnail_needed.emit(path, self.thumbnail_size) # Emit signal with current size

        except Exception as e:
            # Catch potential errors during mapping or geometry checks
            logger.error(f"Error during load_visible_images: {e}", exc_info=True)

    def clear_grid(self):
        """グリッドをクリア (Implementation)"""
        logger.debug("Clearing grid.")
        # Stop timers related to loading/checking
        self.visibility_check_timer.stop()
        self.scroll_debounce_timer.stop() # Stop scroll timer as well

        self.clear_grid_widgets() # Remove widgets first

        # Clear internal state AFTER removing widgets
        self.image_labels.clear()
        self.pending_updates.clear() # Clear pending updates as well

        # Restart timers
        self.visibility_check_timer.start()


    def clear_grid_widgets(self):
         """Helper to remove all widgets from the grid layout."""
         while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                # Disconnect signals to avoid issues during deletion? Maybe not needed.
                widget.deleteLater()

    def process_updates(self, update_keys: list):
        """サムネイル更新をバッチ処理 (Implementation)"""
        logger.debug(f"Processing {len(update_keys)} thumbnail updates.")
        batch_count = 0
        max_batch = 20 # Limit updates per cycle

        for image_path in update_keys:
            if batch_count >= max_batch:
                 logger.debug(f"Update batch limit ({max_batch}) reached.")
                 break

            if image_path in self.image_labels and image_path in self.pending_updates:
                thumbnail_or_error = self.pending_updates[image_path]
                label = self.image_labels[image_path]

                if label and label.parent() is not None: # Check if label still exists
                    if thumbnail_or_error == "ERROR":
                         label.setLoadingState(LazyImageLabel.STATE_ERROR)
                    elif not thumbnail_or_error.isNull():
                         # Ensure the label size matches the current thumbnail_size if needed
                         if label.size() != self.thumbnail_size:
                             label.update_size(self.thumbnail_size) # Update label size if density/zoom changed
                         label.set_thumbnail(thumbnail_or_error) # This sets state to LOADED
                    else:
                         # Handle case where thumbnail is unexpectedly null but not marked as error
                         logger.warning(f"Received null thumbnail for {image_path}, marking as error.")
                         label.setLoadingState(LazyImageLabel.STATE_ERROR)
                    batch_count += 1
                else:
                     logger.debug(f"Label for {image_path} no longer exists, skipping update.")
            # No need to remove from pending_updates here, base class handles it


        # Update layout if changes were made (might not be necessary if labels handle own updates)
        if batch_count > 0:
            # self.grid_layout.activate() # May force unnecessary relayout
            self.content_widget.update() # Request repaint
            pass


    # --- Overridden Resize Handling ---
    def handle_resize(self, event: QResizeEvent):
        """リサイズ適用（デバウンス後） - 列数を再計算"""
        super().handle_resize(event) # Call base class handler (optional)
        logger.debug("EnhancedGridView handling resize.")
        old_columns = self.columns
        self.calculate_columns()

        # Refresh the view only if the number of columns changed
        if old_columns != self.columns:
            logger.info(f"Columns changed from {old_columns} to {self.columns} due to resize. Refreshing.")
            self.refresh()
        # else:
        #     # Even if columns don't change, trigger visibility check as items might have shifted
        #     self.load_visible_images()


    # --- Grid Specific Methods ---
    def calculate_columns(self):
        """利用可能な幅に基づいて列数を計算"""
        try:
            # Use viewport width for calculation as it excludes scrollbar
            viewport_width = self.scroll_area.viewport().width()
            margins = self.grid_layout.contentsMargins()
            available_width = viewport_width - margins.left() - margins.right()

            thumbnail_width = self.thumbnail_size.width()
            spacing = self.grid_layout.horizontalSpacing() # Use horizontal spacing

            if thumbnail_width + spacing <= 0: # Avoid division by zero
                effective_item_width = 1
            else:
                effective_item_width = thumbnail_width + spacing

            new_columns = max(1, available_width // effective_item_width)

            # Density-based min/max limits (consider making configurable)
            density_key = self._get_density_key()
            min_cols = self.config.get(f"display.grid_min_columns.{density_key}", {"small": 4, "medium": 3, "large": 2}.get(density_key, 1))
            max_cols = self.config.get(f"display.grid_max_columns.{density_key}", {"small": 8, "medium": 6, "large": 4}.get(density_key, 10))


            self.columns = max(min_cols, min(new_columns, max_cols))
            logger.debug(f"Calculated columns: {self.columns} (Available Width: {available_width}, Thumb Width: {thumbnail_width}, Spacing: {spacing})")

            # Adjust page size based on columns (optional, could be fixed per density)
            target_rows = self.config.get("display.grid_target_rows", 5)
            new_page_size = self.columns * target_rows
            if self.page_size != new_page_size:
                self.page_size = new_page_size
                logger.debug(f"Adjusted page size based on columns: {self.page_size}")


        except Exception as e:
            logger.error(f"Error calculating columns: {e}", exc_info=True)
            self.columns = max(1, self.columns) # Fallback to previous or 1

# --- END REFACTORED views/enhanced_grid_view.py ---
