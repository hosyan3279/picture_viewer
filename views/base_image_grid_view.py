# --- START REFACTORED views/base_image_grid_view.py ---
"""
基本画像グリッドビューモジュール

画像グリッドビューの基底クラスを提供します。
様々なビュー実装で共通の機能を抽象化しています。
"""
from abc import abstractmethod
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QSizePolicy, QComboBox, QSlider, QFrame
)
# Import Slot from PySide6.QtCore
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect, Slot
from PySide6.QtGui import QResizeEvent
from utils import logger, get_config # Import logger and get_config
from models import ImageModel # Import ImageModel for type hinting
from controllers import WorkerManager # Import WorkerManager for type hinting

class BaseImageGridView(QWidget):
    """
    画像グリッドビューの基底クラス

    ページネーション、スクロール連動、サムネイル更新、表示オプション（密度、ズーム）など、
    画像グリッドビューに共通する機能を実装する基底クラスです。
    子クラスでグリッドレイアウト方式とサムネイル更新処理を実装する必要があります。
    """
    # シグナル定義
    image_selected = Signal(str)  # 選択された画像のパス
    thumbnail_needed = Signal(str, QSize)  # サムネイルが必要（子クラスで使用）

    def __init__(self, image_model: ImageModel, worker_manager: WorkerManager, parent: QWidget = None):
        """
        初期化

        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            parent: 親ウィジェット
        """
        super().__init__(parent)
        self.image_model = image_model
        self.worker_manager = worker_manager
        self.config = get_config() # Get config instance

        # --- Thumbnail Size and Density Settings ---
        self.base_thumbnail_sizes = {
            0: QSize(*self.config.get("thumbnails.sizes.small", (100, 100))),
            1: QSize(*self.config.get("thumbnails.sizes.medium", (150, 150))),
            2: QSize(*self.config.get("thumbnails.sizes.large", (200, 200)))
        }
        self.min_thumbnail_size = self.config.get("thumbnails.min_size", 80)
        self.max_thumbnail_size = self.config.get("thumbnails.max_size", 300)
        default_size_key = self.config.get("thumbnails.default_size", "medium")
        default_index = {"small": 0, "medium": 1, "large": 2}.get(default_size_key, 1)
        self.thumbnail_size = self.base_thumbnail_sizes[default_index]
        self.current_density_index = default_index # Store index for consistency

        # --- Common Settings ---
        # Page size might depend on density/zoom, initialize here, subclasses can adjust
        self.page_size = self.config.get(f"display.page_sizes.{default_size_key}", 32)
        self.current_page = 0
        self.total_pages = 0
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        # self.loaded_images = set() # This might be specific to how subclasses handle loading

        # --- Timers ---
        # Scroll debounce timer
        self.scroll_debounce_timer = QTimer(self)
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.setInterval(self.config.get("display.ui.scroll_debounce_ms", 150)) # Configurable debounce
        # Connect directly to the abstract method, subclasses must implement it
        self.scroll_debounce_timer.timeout.connect(self.load_visible_images)

        # Update batch processing timer
        self.pending_updates = {}  # 保留中の更新（画像パス -> サムネイル）
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(self.config.get("display.ui.update_interval_ms", 100)) # Configurable update interval
        self.update_timer.timeout.connect(self.apply_pending_updates)
        self.update_timer.start()

        # Resize debounce timer
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(self.config.get("display.ui.resize_debounce_ms", 250)) # Configurable resize debounce
        self.resize_timer.timeout.connect(self.apply_resize)
        self.pending_resize_event = None # Store the event

        # --- UI Components ---
        self.setup_ui()

        # --- Model Connection ---
        self.image_model.data_changed.connect(self.refresh)

        logger.debug(f"{self.__class__.__name__} initialized.")


    def setup_ui(self):
        """UIコンポーネントを設定"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5) # Adjust spacing

        # --- Top Controls Area ---
        self.setup_top_controls(main_layout)

        # --- Scroll Area ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Use Qt.ScrollBarPolicy enum
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame) # Use QFrame.Shape enum

        # Scroll event tracking
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

        # --- Content Widget (Managed by Subclass Layout) ---
        self.content_widget = QWidget()
        # self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) # Let layout manage size policy
        self.scroll_area.setWidget(self.content_widget)

        # --- Pagination Controls ---
        page_controls_layout = QHBoxLayout()
        page_controls_layout.setContentsMargins(5, 0, 5, 5) # Add some margin
        self.prev_button = QPushButton("前へ")
        self.page_label = QLabel("0 / 0")
        self.next_button = QPushButton("次へ")

        self.prev_button.clicked.connect(self.prev_page)
        self.next_button.clicked.connect(self.next_page)

        page_controls_layout.addStretch()
        page_controls_layout.addWidget(self.prev_button)
        page_controls_layout.addWidget(self.page_label)
        page_controls_layout.addWidget(self.next_button)
        page_controls_layout.addStretch()

        # Add widgets/layouts to main layout
        main_layout.addWidget(self.scroll_area) # Scroll area takes most space
        main_layout.addLayout(page_controls_layout)

        # Disable buttons initially
        self.update_page_controls() # Call this to set initial state


    def setup_top_controls(self, parent_layout: QVBoxLayout):
        """Sets up the top control widgets (density, zoom)."""
        top_controls_layout = QHBoxLayout()
        top_controls_layout.setContentsMargins(5, 5, 5, 0) # Add some margin

        # --- Density Control ---
        density_label = QLabel("表示密度:")
        self.density_combo = QComboBox()
        self.density_combo.addItems(["小", "中", "大"])
        self.density_combo.setCurrentIndex(self.current_density_index)
        self.density_combo.currentIndexChanged.connect(self.on_density_changed)

        # --- Zoom Control ---
        zoom_label = QLabel("ズーム:")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal) # Use Qt.Orientation enum
        self.zoom_slider.setMinimum(self.min_thumbnail_size)
        self.zoom_slider.setMaximum(self.max_thumbnail_size)
        self.zoom_slider.setValue(self.thumbnail_size.width())
        self.zoom_slider.setTickPosition(QSlider.TickPosition.TicksBelow) # Use QSlider.TickPosition enum
        self.zoom_slider.setTickInterval( (self.max_thumbnail_size - self.min_thumbnail_size) // 10 ) # Dynamic interval
        # Connect valueChanged for live feedback (optional, can be slow)
        # self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        self.zoom_slider.sliderReleased.connect(self.on_zoom_slider_released)

        self.zoom_slider.setMinimumWidth(100) # Ensure slider is usable
        self.zoom_slider.setMaximumWidth(200)
        self.zoom_slider.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed) # Use QSizePolicy.Policy enum

        # Add to layout
        top_controls_layout.addWidget(density_label)
        top_controls_layout.addWidget(self.density_combo)
        top_controls_layout.addSpacing(20)
        top_controls_layout.addWidget(zoom_label)
        top_controls_layout.addWidget(self.zoom_slider)
        top_controls_layout.addStretch()

        # Add the top controls layout to the parent layout
        parent_layout.addLayout(top_controls_layout)

    @Slot()
    def refresh(self):
        """表示を更新"""
        logger.debug(f"{self.__class__.__name__}: Refreshing view.")
        # ページ数を更新
        total_images = self.image_model.image_count()
        # Calculate total pages based on current page_size (might change with density)
        self.total_pages = max(1, (total_images + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1

        # カレントページをリセット（必要に応じて）
        if self.current_page >= self.total_pages:
            self.current_page = max(0, self.total_pages - 1)

        # 読み込み済み画像のリストをクリア (Subclasses might handle this differently)
        # self.loaded_images.clear() # Removed, subclass responsibility

        # 現在のページを表示
        self.display_current_page()

        # ページコントロールを更新
        self.update_page_controls()

    @Slot()
    def display_current_page(self):
        """
        現在のページを表示 (Clears grid and places images)
        """
        logger.debug(f"Displaying page {self.current_page + 1}/{self.total_pages}")
        # 既存のアイテムをクリア (Abstract method)
        self.clear_grid()

        # 画像がない場合は何もしない
        if self.image_model.image_count() == 0:
            self.update_page_controls() # Ensure controls are updated
            logger.debug("No images to display.")
            return

        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)
        logger.debug(f"Placing {len(images)} images for page {self.current_page + 1}")

        if images:
            # 画像を配置（子クラスで実装 - Abstract method）
            self.place_images(images)

            # 遅延読み込みを開始 (Use QTimer for safety after layout)
            QTimer.singleShot(50, self.load_visible_images)
        else:
             logger.debug("No images found for the current page.")


    @abstractmethod
    def place_images(self, images: list):
        """
        画像をビューに配置 (子クラスで実装)

        Args:
            images (list): 画像パスのリスト
        """
        raise NotImplementedError("Subclasses must implement place_images")

    @Slot()
    def on_scroll_changed(self):
        """スクロール位置が変更されたときの処理"""
        # logger.debug("Scroll changed, restarting debounce timer.")
        # デバウンスのためにタイマーをリセット/スタート
        self.scroll_debounce_timer.start() # Restart (it's single shot)

    @abstractmethod
    def load_visible_images(self):
        """
        現在表示されている画像を読み込む (子クラスで実装)
        This method will be called after scroll debounce.
        """
        raise NotImplementedError("Subclasses must implement load_visible_images")

    # Make this slot connectable from labels in subclasses
    @Slot(str)
    def on_image_click(self, image_path: str):
        """
        画像クリック時の処理

        Args:
            image_path (str): クリックされた画像のパス
        """
        logger.debug(f"Image clicked: {image_path}")
        self.image_selected.emit(image_path)

    @abstractmethod
    def clear_grid(self):
        """
        グリッドをクリア (子クラスで実装)
        Should remove all image widgets/items from the content layout.
        """
        raise NotImplementedError("Subclasses must implement clear_grid")

    @Slot()
    def prev_page(self):
        """前のページに移動"""
        if self.current_page > 0:
            logger.debug("Navigating to previous page.")
            self.current_page -= 1
            self.display_current_page()
            self.update_page_controls()
            # スクロール位置をリセット
            self.scroll_area.verticalScrollBar().setValue(0)
        else:
             logger.debug("Already on the first page.")


    @Slot()
    def next_page(self):
        """次のページに移動"""
        if self.current_page < self.total_pages - 1:
            logger.debug("Navigating to next page.")
            self.current_page += 1
            self.display_current_page()
            self.update_page_controls()
            # スクロール位置をリセット
            self.scroll_area.verticalScrollBar().setValue(0)
        else:
             logger.debug("Already on the last page.")

    def update_page_controls(self):
        """ページコントロールを更新"""
        count = self.image_model.image_count()
        if count > 0 and self.total_pages > 0 :
            self.page_label.setText(f"{self.current_page + 1} / {self.total_pages}")
            self.prev_button.setEnabled(self.current_page > 0)
            self.next_button.setEnabled(self.current_page < self.total_pages - 1)
        else:
            self.page_label.setText("0 / 0")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)

    # Renamed from update_thumbnail to avoid confusion with the signal
    @Slot(str, object) # Accepts QPixmap or similar
    def receive_thumbnail(self, image_path: str, thumbnail):
        """
        特定の画像のサムネイル更新リクエストを受け取る (バッチ処理用)

        Args:
            image_path (str): 画像のパス
            thumbnail: 新しいサムネイル (e.g., QPixmap)
        """
        if not thumbnail or (hasattr(thumbnail, 'isNull') and thumbnail.isNull()):
             logger.warning(f"Received invalid thumbnail for {image_path}, adding error placeholder.")
             # Handle error case, maybe add a specific placeholder or state
             self.pending_updates[image_path] = "ERROR" # Use a special marker
        else:
             # 更新をキューに追加
             self.pending_updates[image_path] = thumbnail
        # Timer will trigger apply_pending_updates

    @Slot()
    def apply_pending_updates(self):
        """
        保留中のサムネイル更新をバッチ処理で適用
        """
        if not self.pending_updates:
            return

        # Make a copy of keys to process to avoid issues if dict changes during processing
        update_keys = list(self.pending_updates.keys())
        # logger.debug(f"Applying {len(update_keys)} pending thumbnail updates.")

        if update_keys:
             # Let subclass handle the actual UI update (Abstract method)
             self.process_updates(update_keys)
             # Clear processed updates (important!)
             for key in update_keys:
                 self.pending_updates.pop(key, None)


    @abstractmethod
    def process_updates(self, update_keys: list):
        """
        サムネイル更新をバッチ処理する (子クラスで実装)
        This method should take the thumbnails from self.pending_updates
        and apply them to the corresponding widgets in the grid.

        Args:
            update_keys (list): 更新する画像パスのキーリスト
        """
        raise NotImplementedError("Subclasses must implement process_updates")

    # --- Density and Zoom Handlers ---
    @Slot(int)
    def on_density_changed(self, index: int):
        """表示密度変更時の処理"""
        logger.debug(f"Density changed to index {index}")
        old_thumbnail_size = self.thumbnail_size
        old_page_size = self.page_size

        self.current_density_index = index
        self.thumbnail_size = self.base_thumbnail_sizes[index]

        # Adjust page size based on density - Subclasses might override this logic
        density_key = {0: "small", 1: "medium", 2: "large"}.get(index, "medium")
        self.page_size = self.config.get(f"display.page_sizes.{density_key}", self.page_size) # Keep current if not found

        # Update zoom slider to reflect the new base size
        self.zoom_slider.setValue(self.thumbnail_size.width())

        # Refresh view if size or page size changed significantly
        if old_thumbnail_size != self.thumbnail_size or old_page_size != self.page_size:
             logger.info(f"Density changed: New Thumb Size={self.thumbnail_size}, New Page Size={self.page_size}")
             self.refresh()


    # @Slot(int) # Connected to sliderReleased instead
    # def on_zoom_changed(self, value: int):
    #     """ズームスライダーの値が変更されたときの処理 (Live update - potentially slow)"""
    #     # This can be used for live preview if desired, but might be slow.
    #     # For now, we only update on sliderReleased.
    #     pass

    @Slot()
    def on_zoom_slider_released(self):
        """ズームスライダーがリリースされたときの処理"""
        value = self.zoom_slider.value()
        logger.debug(f"Zoom slider released at value {value}")
        new_size = QSize(value, value) # Assuming square thumbnails

        if self.thumbnail_size != new_size:
             self.thumbnail_size = new_size
             logger.info(f"Zoom changed: New Thumb Size={self.thumbnail_size}")

             # Optional: Adjust page size based on zoom? Maybe not necessary.
             # Example: self.page_size = max(10, int(base_page_size * (base_thumb_width / value)))

             # Refresh the view to apply the new thumbnail size
             self.refresh()

    # --- Resize Handling ---
    def resizeEvent(self, event: QResizeEvent):
        """リサイズイベントのデバウンス処理"""
        super().resizeEvent(event)
        self.pending_resize_event = event # Store the latest event
        self.resize_timer.start() # Restart the timer

    @Slot()
    def apply_resize(self):
        """リサイズ適用（デバウンス後）"""
        if self.pending_resize_event is None:
            return

        logger.debug(f"{self.__class__.__name__} applying resize.")
        # Subclasses might need to recalculate columns or relayout here
        self.handle_resize(self.pending_resize_event)

        # Trigger loading visible images after resize stabilizes
        # Use QTimer to ensure layout changes are processed before checking visibility
        QTimer.singleShot(0, self.load_visible_images)
        self.pending_resize_event = None # Clear pending event


    # Allow subclasses to implement specific resize logic
    def handle_resize(self, event: QResizeEvent):
        """Subclasses can override this to handle resize event after debounce."""
        logger.debug(f"{self.__class__.__name__} handled resize event.")
        pass # Default implementation does nothing


# --- END REFACTORED views/base_image_grid_view.py ---
