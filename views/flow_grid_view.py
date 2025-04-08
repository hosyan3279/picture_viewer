# --- START REFACTORED views/flow_grid_view.py ---
"""
フローグリッドビューモジュール

FlowLayoutを使用した画像ギャラリービューを提供します。
ウィンドウサイズに応じて自然に「流れる」ように画像を配置します。
"""
from PySide6.QtWidgets import QWidget # Keep QWidget for content_widget
# Import Slot from PySide6.QtCore
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QPoint, Slot
from PySide6.QtGui import QPixmap, QResizeEvent

# Import necessary components
from .base_image_grid_view import BaseImageGridView
from .lazy_image_label import LazyImageLabel
from .flow_layout import FlowLayout # Keep FlowLayout
from utils import logger # Import logger

class FlowGridView(BaseImageGridView):
    """
    FlowLayoutを使用した画像ギャラリービュー

    ウィンドウサイズに応じて自然に「流れる」ように画像を配置します。
    遅延読み込みやページネーションなどの機能も備えています。
    """

    def __init__(self, image_model, worker_manager, parent=None):
        """
        初期化

        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            parent: 親ウィジェット
        """
        # Initialize Base Class (handles common UI, timers, size/page logic)
        super().__init__(image_model, worker_manager, parent)

        # --- Flow Specific Settings ---
        self.load_batch_size = self.config.get("workers.load_batch_size", 10) # Flow might load more

        # --- Flow Layout ---
        self.flow_layout = FlowLayout(self.content_widget) # Use the content_widget from base class
        spacing = self.config.get("display.ui.flow_spacing", 10)
        margins = self.config.get("display.ui.flow_margins", 10)
        self.flow_layout.setSpacing(spacing)
        self.flow_layout.setContentsMargins(margins, margins, margins, margins)

        # --- Visibility Check Timer ---
        # Flow layout might benefit from slightly different timing
        self.visibility_check_timer = QTimer(self)
        vis_check_interval = self.config.get("display.ui.visibility_check_interval_ms", 150)
        self.visibility_check_timer.setInterval(vis_check_interval)
        self.visibility_check_timer.timeout.connect(self.load_visible_images) # Connect to the correct method
        self.visibility_check_timer.start()

        # Override page size calculation based on density/zoom if needed
        self._update_flow_page_size() # Initial calculation

        logger.debug("FlowGridView initialized.")

    # Override density change to recalculate page size for flow
    @Slot(int) # Add Slot decorator
    def on_density_changed(self, index: int):
        super().on_density_changed(index) # Call base class logic first
        self._update_flow_page_size() # Recalculate page size for flow layout
        self.refresh() # Refresh is needed because page size changed

    # Override zoom change to recalculate page size for flow
    @Slot() # Add Slot decorator
    def on_zoom_slider_released(self):
        old_page_size = self.page_size
        super().on_zoom_slider_released() # Call base class logic first (updates thumbnail size)
        self._update_flow_page_size() # Recalculate page size based on new thumbnail size
        if old_page_size != self.page_size:
             self.refresh() # Refresh if page size changed

    def _update_flow_page_size(self):
        """Calculate page size based on current thumbnail size for flow layout."""
        # Example logic: Larger thumbnails -> smaller page size
        base_thumb_width = 150 # Reference size
        base_page_size = 80    # Reference page size
        current_thumb_width = self.thumbnail_size.width()

        if current_thumb_width <= 0: current_thumb_width = base_thumb_width # Avoid division by zero

        scale_factor = base_thumb_width / current_thumb_width
        new_page_size = max(20, int(base_page_size * scale_factor)) # Ensure a minimum page size
        if self.page_size != new_page_size:
            self.page_size = new_page_size
            logger.debug(f"Updated flow page size based on zoom/density: {self.page_size}")


    # --- Overridden Abstract Methods ---

    def place_images(self, images: list):
        """画像をフローレイアウトに配置 (Implementation)"""
        logger.debug(f"Placing {len(images)} images in flow layout.")
        self.clear_grid_widgets() # Clear widgets first

        for image_path in images:
            # Create lazy loading label with current thumbnail size
            label = LazyImageLabel(image_path, self.thumbnail_size)
            label.image_clicked.connect(self.on_image_click) # Connect click signal

            # Add to flow layout
            self.flow_layout.addWidget(label)

            # Store mapping
            self.image_labels[image_path] = label
         # Flow layout updates automatically, but adjustSize might be needed
        self.content_widget.adjustSize()


    def load_visible_images(self):
        """可視状態のサムネイルを読み込む (Implementation)"""
        if not self.image_labels or not self.isVisible():
             return

        try:
            viewport = self.scroll_area.viewport()
            if not viewport: return
            visible_rect_local = viewport.rect()

            # Use a larger buffer for flow layout as items wrap unpredictably
            buffer_y = viewport.height() # Use full viewport height as buffer
            extended_visible_rect = visible_rect_local.adjusted(0, -buffer_y, 0, buffer_y)

            labels_to_load = []
            processed_count = 0
            max_process = 200 # Limit checks per cycle

            for image_path, label in self.image_labels.items():
                processed_count += 1
                if processed_count > max_process:
                     logger.warning("Visibility check limit reached, will continue next cycle.")
                     break

                if not label or label.parent() is None or label.loading_state != LazyImageLabel.STATE_NOT_LOADED:
                    continue

                try:
                     # Map top-left to viewport coordinates
                     label_top_left_in_viewport = label.mapTo(viewport, QPoint(0, 0))
                     label_rect_in_viewport = QRect(label_top_left_in_viewport, label.size())

                     if extended_visible_rect.intersects(label_rect_in_viewport):
                         labels_to_load.append((image_path, label))
                         if len(labels_to_load) >= self.load_batch_size:
                             break # Stop collecting once batch size is reached
                except RuntimeError as map_error:
                     # mapTo can fail if widget is being deleted, log and continue
                     logger.warning(f"Could not map label for {image_path} to viewport: {map_error}")
                     continue


            if labels_to_load:
                 logger.debug(f"Requesting thumbnails for {len(labels_to_load)} visible labels (flow).")
                 for path, label_widget in labels_to_load:
                     if label_widget.loading_state == LazyImageLabel.STATE_NOT_LOADED:
                         label_widget.setLoadingState(LazyImageLabel.STATE_LOADING)
                         self.thumbnail_needed.emit(path, self.thumbnail_size)

        except Exception as e:
            logger.error(f"Error during flow load_visible_images: {e}", exc_info=True)


    def clear_grid(self):
        """フローレイアウトをクリア (Implementation)"""
        logger.debug("Clearing flow grid.")
        # Stop timers
        self.visibility_check_timer.stop()
        self.scroll_debounce_timer.stop()

        self.clear_grid_widgets() # Remove widgets

        # Clear internal state
        self.image_labels.clear()
        self.pending_updates.clear() # Clear pending updates

        # Restart timers
        self.visibility_check_timer.start()


    def clear_grid_widgets(self):
         """Helper to remove all widgets from the flow layout."""
         while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item: # Check if item exists
                 widget = item.widget()
                 if widget:
                     widget.deleteLater()


    def process_updates(self, update_keys: list):
        """サムネイル更新をバッチ処理 (Implementation for Flow)"""
        # FlowGridView updates thumbnails directly via receive_thumbnail -> label.set_thumbnail
        # The batch processing mechanism of the base class isn't strictly needed here.
        # We override it to simply log, as the base class requires implementation.
        logger.debug(f"FlowGridView received {len(update_keys)} updates (processed directly).")
        # If direct update causes issues, implement batching logic here similar to EnhancedGridView
        # For now, assume direct update in receive_thumbnail is sufficient.
        pass # Base class clears pending_updates after calling this.

    # Override receive_thumbnail to update label directly (no batching needed for Flow?)
    @Slot(str, object)
    def receive_thumbnail(self, image_path: str, thumbnail):
         """Receive thumbnail and update label directly."""
         if image_path in self.image_labels:
             label = self.image_labels[image_path]
             if label and label.parent() is not None:
                 if not thumbnail or (hasattr(thumbnail, 'isNull') and thumbnail.isNull()):
                      logger.warning(f"Received invalid thumbnail for {image_path} in FlowView.")
                      label.setLoadingState(LazyImageLabel.STATE_ERROR)
                 else:
                      # Update label size if needed
                      if label.size() != self.thumbnail_size:
                           label.update_size(self.thumbnail_size)
                      label.set_thumbnail(thumbnail) # Update label directly
             else:
                  logger.debug(f"Label for {image_path} no longer exists in FlowView.")
         # Do not add to self.pending_updates


    # --- Overridden Resize Handling ---
    def handle_resize(self, event: QResizeEvent):
        """リサイズ適用（デバウンス後） - FlowLayout handles reflow"""
        super().handle_resize(event)
        logger.debug("FlowGridView handling resize - triggering visibility check.")
        # Flow layout reflows automatically, just need to check visibility
        # Use QTimer to ensure layout changes are processed before checking visibility
        QTimer.singleShot(0, self.load_visible_images)


# --- END REFACTORED views/flow_grid_view.py ---
