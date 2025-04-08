"""
スクロール認識イメージグリッドモジュール

スクロール動作を最適化したイメージグリッドビューを提供します。
"""
from PySide6.QtWidgets import QLabel, QGridLayout
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QTime

from .base_image_grid_view import BaseImageGridView

class ScrollAwareImageGrid(BaseImageGridView):
    """
    スクロール認識イメージグリッドクラス

    スクロール位置や速度を考慮して、画像の読み込みを最適化した
    イメージグリッドビューを提供します。
    """
    
    def __init__(self, image_model, worker_manager, thumbnail_cache=None, parent=None):
        """
        初期化

        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            thumbnail_cache: サムネイルキャッシュ (オプション)
            parent: 親ウィジェット
        """
        super().__init__(image_model, worker_manager, parent)
        self.thumbnail_cache = thumbnail_cache  # サムネイルキャッシュを保存
        self.columns = 4
        self.page_size = 20
        
        # スクロール速度検出用
        self.last_scroll_pos = 0
        self.last_scroll_time = QTime.currentTime()
        self.scroll_speed = 0

        # 遅延読み込み用キュー
        self.load_queue = []
        self.is_loading = False
        
        # グリッドレイアウトを作成
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        
        # 読み込みキュー処理タイマー
        self.load_timer = QTimer()
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(self.process_load_queue)

    def place_images(self, images):
        """
        画像をグリッドに配置
        
        Args:
            images (list): 画像パスのリスト
        """
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
            label.is_loading = False
            
            # まずキャッシュをチェック
            if self.thumbnail_cache:
                thumbnail = self.thumbnail_cache.get_thumbnail(image_path, (140, 140))
                if thumbnail and not thumbnail.isNull():
                    label.setPixmap(thumbnail)
                    label.setScaledContents(True)
                    label.is_loaded = True
                    self.loaded_images.add(image_path)
            
            # クリックイベントを設定
            label.mousePressEvent = lambda event, path=image_path: self.on_image_click(path)
            
            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)
            
            # マッピングを保存
            self.image_labels[image_path] = label
        
        # 最初のページの場合はすぐに読み込みを開始
        if self.current_page == 0:
            # 最初のページの画像を優先的にキャッシュ
            for image_path in images:
                if image_path not in self.loaded_images:
                    self.load_queue.insert(0, (image_path, self.image_labels[image_path]))
            self.process_load_queue()

    def on_scroll_changed(self, value):
        """
        スクロール位置が変更されたときの処理

        スクロール速度を計算し、速度に応じたデバウンス時間を設定します。
        """
        # スクロール速度を計算
        current_time = QTime.currentTime()
        time_diff = self.last_scroll_time.msecsTo(current_time)
        if time_diff > 0:
            pos_diff = abs(value - self.last_scroll_pos)
            self.scroll_speed = pos_diff / time_diff
        self.last_scroll_pos = value
        self.last_scroll_time = current_time
        
        # デバウンスのためにタイマーをリセット
        self.scroll_debounce_timer.stop()
        
        # スクロール速度が速い場合は遅延を長くする
        if self.scroll_speed > 2.0:  # スクロールが速い
            self.scroll_debounce_timer.start(500)  # 500ms後に読み込み
        else:
            self.scroll_debounce_timer.start(100)  # 通常は100ms

    def load_visible_images(self):
        """
        現在表示されている画像を読み込む

        視野内のラベルを特定し、未読み込みの画像を読み込みキューに追加します。
        """
        # 表示領域を取得
        viewport_rect = self.scroll_area.viewport().rect()
        visible_rect = QRect(
            0,
            self.scroll_area.verticalScrollBar().value(),
            viewport_rect.width(),
            viewport_rect.height()
        )

        # 読み込みキューをクリア
        self.load_queue.clear()

        # 表示されているアイテムを特定しキューに追加
        for image_path, label in list(self.image_labels.items()):
            if image_path in self.loaded_images or getattr(label, 'is_loading', False):
                continue

            label_geometry = label.geometry()
            label_pos = label.mapTo(self.scroll_area.viewport(), QPoint(0, 0))
            label_rect = QRect(label_pos, label_geometry.size())

            # ラベルが表示領域内にあるか
            if visible_rect.intersects(label_rect):
                # 可視領域内のアイテムは高優先度
                self.load_queue.insert(0, (image_path, label))
            elif (label_geometry.top() > visible_rect.bottom() and
                  label_geometry.top() < visible_rect.bottom() + 300):
                # スクロール方向の先読み（下方向）
                self.load_queue.append((image_path, label))
            elif (label_geometry.bottom() < visible_rect.top() and
                  label_geometry.bottom() > visible_rect.top() - 300):
                # スクロール方向の先読み（上方向）
                self.load_queue.append((image_path, label))

        # 読み込み開始
        if not self.is_loading and self.load_queue:
            self.process_load_queue()

    def process_load_queue(self):
        """読み込みキューの処理"""
        if not self.load_queue:
            self.is_loading = False
            return

        self.is_loading = True
        image_path, label = self.load_queue.pop(0)

        # 既に読み込み中または読み込み済みならスキップ
        if image_path in self.loaded_images or getattr(label, 'is_loading', False):
            QTimer.singleShot(10, self.process_load_queue)
            return

        # 読み込み中フラグを設定
        label.is_loading = True
        label.setText("読み込み中...")

        # サムネイル読み込みをリクエスト
        self.thumbnail_needed.emit(image_path, self.thumbnail_size)
        
        # 次のアイテムを処理
        QTimer.singleShot(50, self.process_load_queue)

    def clear_grid(self):
        """グリッドをクリア"""
        self.image_labels.clear()
        self.loaded_images.clear()
        self.load_queue.clear()
        self.is_loading = False

        # グリッド内のすべてのウィジェットを削除
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def process_updates(self, update_keys):
        """
        サムネイル更新をバッチ処理
        
        Args:
            update_keys (list): 更新する画像パスのリスト
        """
        batch_count = 0
        
        for image_path in update_keys:
            if batch_count >= 20:  # 1回の更新で最大20件まで
                break
                
            if image_path in self.image_labels:
                thumbnail = self.pending_updates[image_path]
                label = self.image_labels[image_path]
                
                # UIを更新
                label.setPixmap(thumbnail)
                label.is_loaded = True
                label.is_loading = False
                self.loaded_images.add(image_path)
                
                # 処理済みの項目を削除
                del self.pending_updates[image_path]
                batch_count += 1
        
        # 更新があった場合はレイアウトを調整
        if batch_count > 0:
            self.update()

    def resizeEvent(self, event):
        """ウィンドウリサイズ時のイベント処理"""
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
