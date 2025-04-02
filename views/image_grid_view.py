"""
画像グリッドビューモジュール

サムネイル画像をグリッド形式で表示するビュークラスを提供します。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QGridLayout, QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QSize
from PySide6.QtGui import QPixmap, QResizeEvent

class ImageGridView(QWidget):
    """
    サムネイル画像をグリッド形式で表示するビュークラス
    
    画像のサムネイルをグリッドレイアウトで表示し、
    ページネーション機能とクリックイベントをサポートします。
    また、スクロール位置に応じた遅延読み込みを実装しています。
    """
    # シグナル定義
    image_selected = Signal(str)  # 選択された画像のパス
    
    def __init__(self, image_model, worker_manager, parent=None):
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
        self.columns = 4
        self.page_size = 20
        self.current_page = 0
        self.total_pages = 0
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        self.loaded_images = set()  # すでに読み込まれた画像のパスのセット
        self.scroll_debounce_timer = None  # スクロールのデバウンスタイマー
        
        # バッチ更新用の変数
        self.pending_updates = {}  # 保留中の更新（画像パス -> サムネイル）
        self.update_timer = QTimer()  # 定期的なUI更新タイマー
        self.update_timer.setInterval(100)  # 100ms間隔で更新
        self.update_timer.timeout.connect(self.apply_pending_updates)
        self.update_timer.start()
        
        # UIコンポーネント
        self.setup_ui()
        
        # モデルの変更を監視
        self.image_model.data_changed.connect(self.refresh)
    
    def setup_ui(self):
        """UIコンポーネントを設定"""
        # メインレイアウト
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        # スクロールイベントの追跡
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)
        
        # 画像グリッドウィジェット
        self.content_widget = QWidget()
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(10)  # ウィジェット間のスペースを設定
        self.scroll_area.setWidget(self.content_widget)
        
        # ページネーションコントロール
        page_controls = QHBoxLayout()
        self.prev_button = QPushButton("前へ")
        self.page_label = QLabel("0 / 0")
        self.next_button = QPushButton("次へ")
        
        self.prev_button.clicked.connect(self.prev_page)
        self.next_button.clicked.connect(self.next_page)
        
        page_controls.addWidget(self.prev_button)
        page_controls.addWidget(self.page_label)
        page_controls.addWidget(self.next_button)
        page_controls.addStretch()
        
        # レイアウトに追加
        layout.addWidget(self.scroll_area)
        layout.addLayout(page_controls)
        
        # デフォルトでボタンを無効化
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        
        # スクロールのデバウンスタイマー
        self.scroll_debounce_timer = QTimer()
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.timeout.connect(self.load_visible_images)
    
    def refresh(self):
        """表示を更新"""
        # ページ数を更新
        total_images = self.image_model.image_count()
        self.total_pages = max(1, (total_images + self.page_size - 1) // self.page_size)
        
        # カレントページをリセット（必要に応じて）
        if self.current_page >= self.total_pages:
            self.current_page = max(0, self.total_pages - 1)
        
        # 読み込み済み画像のリストをクリア
        self.loaded_images.clear()
        
        # 現在のページを表示
        self.display_current_page()
        
        # ページコントロールを更新
        self.update_page_controls()
    
    def display_current_page(self):
        """現在のページを表示"""
        # 既存のアイテムをクリア
        self.clear_grid()
        
        # 画像がない場合は何もしない
        if self.image_model.image_count() == 0:
            return
        
        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)
        
        # グリッドに画像を配置
        for i, image_path in enumerate(images):
            row, col = divmod(i, self.columns)
            
            # ラベルを作成
            label = QLabel()
            label.setFixedSize(150, 150)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("border: 1px solid #cccccc; background-color: #f9f9f9;")
            
            # プレースホルダーの設定
            label.setText("...")
            
            # パスを保存
            label.image_path = image_path
            label.is_loaded = False
            
            # クリックイベントを設定
            label.mousePressEvent = lambda event, path=image_path: self.on_image_click(path)
            
            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)
            
            # マッピングを保存
            self.image_labels[image_path] = label
        
        # 遅延読み込みを開始
        QTimer.singleShot(100, self.load_visible_images)
    
    def resizeEvent(self, event: QResizeEvent):
        """ウィンドウリサイズ時にグリッドの列数を調整"""
        super().resizeEvent(event)
        
        # 前の列数を保存
        old_columns = self.columns
        
        # ウィンドウ幅に応じて列数を調整
        width = event.size().width()
        if width < 500:
            self.columns = 2
        elif width < 800:
            self.columns = 3
        elif width < 1200:
            self.columns = 4
        else:
            self.columns = 5
        
        # 列数が変わった場合は再表示
        if old_columns != self.columns and self.image_model.image_count() > 0:
            self.display_current_page()
    
    def on_scroll_changed(self):
        """スクロール位置が変更されたときの処理"""
        # デバウンスのためにタイマーをリセット
        self.scroll_debounce_timer.stop()
        self.scroll_debounce_timer.start(200)  # 200ms後に実行
    
    def load_visible_images(self):
        """現在表示されている画像を読み込む"""
        viewport_rect = self.scroll_area.viewport().rect()
        
        # 画像パス -> ラベルの辞書がなければ何もしない
        if not self.image_labels:
            return
        
        for image_path, label in self.image_labels.items():
            # すでに読み込み済みの場合はスキップ
            if image_path in self.loaded_images or getattr(label, 'is_loaded', False):
                continue
            
            # ラベルの位置を取得
            label_geometry = label.geometry()
            label_pos = label.mapTo(self.scroll_area.viewport(), label_geometry.topLeft())
            label_rect = QRect(label_pos, label_geometry.size())
            
            # ラベルが表示領域内にあるか、または少し上下に表示領域を広げる（先読み）
            extended_viewport = viewport_rect.adjusted(0, -150, 0, 150)
            if extended_viewport.intersects(label_rect):
                self.load_thumbnail(image_path, label)
    
    def load_thumbnail(self, image_path, label):
        """
        サムネイルを非同期で読み込む
        
        Args:
            image_path (str): 画像のパス
            label (QLabel): サムネイルを表示するラベル
        """
        # すでに読み込み済みならスキップ
        if image_path in self.loaded_images:
            return
        
        # プレースホルダーを表示
        label.setText("読み込み中...")
        
        # ワーカーを作成して読み込みを開始（最適化されたワーカーを使用）
        from ..controllers.optimized_thumbnail_worker import OptimizedThumbnailWorker
        from ..controllers.workers import ThumbnailWorker
        worker = OptimizedThumbnailWorker(image_path, (140, 140))
        
        def on_thumbnail_created(result):
            path, thumbnail = result
            if path == label.image_path and not thumbnail.isNull():
                # 直接更新する代わりに更新キューに追加
                self.update_thumbnail(path, thumbnail)
                label.setToolTip(path)
        
        worker.signals.result.connect(on_thumbnail_created)
        self.worker_manager.start_worker(f"thumbnail_{image_path}", worker)
    
    def on_image_click(self, image_path):
        """
        画像クリック時の処理
        
        Args:
            image_path (str): クリックされた画像のパス
        """
        self.image_selected.emit(image_path)
    
    def clear_grid(self):
        """グリッドをクリア"""
        self.image_labels.clear()
        
        # グリッド内のすべてのウィジェットを削除
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
    
    def prev_page(self):
        """前のページに移動"""
        print("DEBUG: prev_page called in image_grid_view", flush=True)
        if self.current_page > 0:
            self.current_page -= 1
            self.display_current_page()
            self.update_page_controls()
    
    def next_page(self):
        """次のページに移動"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_current_page()
            self.update_page_controls()
    
    def update_page_controls(self):
        """ページコントロールを更新"""
        self.page_label.setText(f"{self.current_page + 1} / {self.total_pages}")
        
        # ボタンの有効/無効状態を更新
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(self.current_page < self.total_pages - 1)
    
    def update_thumbnail(self, image_path, thumbnail):
        """
        特定の画像のサムネイルを更新
        
        更新はキューに追加され、バッチ処理されます。
        
        Args:
            image_path (str): 画像のパス
            thumbnail (QPixmap): 新しいサムネイル
        """
        # 更新をキューに追加（直接UIを更新せず）
        self.pending_updates[image_path] = thumbnail
    
    def apply_pending_updates(self):
        """保留中のサムネイル更新をバッチ処理で適用"""
        # 保留中の更新が無ければ何もしない
        if not self.pending_updates:
            return
        
        # バッチ処理でUI更新（最大20件ずつ処理）
        batch_count = 0
        update_keys = list(self.pending_updates.keys())
        
        for image_path in update_keys:
            if batch_count >= 20:  # 1回の更新で最大20件まで
                break
                
            if image_path in self.image_labels:
                thumbnail = self.pending_updates[image_path]
                label = self.image_labels[image_path]
                
                # UIを更新
                label.setPixmap(thumbnail)
                label.is_loaded = True
                self.loaded_images.add(image_path)
                
                # 処理済みの項目を削除
                del self.pending_updates[image_path]
                batch_count += 1
        
        # 更新があった場合はレイアウトを調整
        if batch_count > 0:
            self.update()
