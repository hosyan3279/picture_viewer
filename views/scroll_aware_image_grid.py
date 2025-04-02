"""
スクロール認識イメージグリッドモジュール

スクロール動作を最適化したイメージグリッドビューを提供します。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGridLayout, QLabel,
    QPushButton, QHBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QTime, QRect, QPoint
from PySide6.QtGui import QResizeEvent, QPixmap

class ScrollAwareImageGrid(QWidget):
    """
    スクロール認識イメージグリッドクラス

    スクロール位置や速度を考慮して、画像の読み込みを最適化した
    イメージグリッドビューを提供します。
    """
    # シグナル定義
    image_selected = Signal(str)  # 選択された画像のパス

    def __init__(self, image_model, worker_manager, thumbnail_cache=None, parent=None):
        """
        初期化

        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            thumbnail_cache: サムネイルキャッシュ (オプション)
            parent: 親ウィジェット
        """
        super().__init__(parent)
        self.image_model = image_model
        self.worker_manager = worker_manager
        self.thumbnail_cache = thumbnail_cache  # サムネイルキャッシュを保存
        self.columns = 4
        self.page_size = 20
        self.current_page = 0
        self.total_pages = 0

        # 画像ラベル管理用
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        self.loaded_images = set()  # すでに読み込まれた画像のパスのセット

        # スクロール速度検出用
        self.last_scroll_pos = 0
        self.last_scroll_time = QTime.currentTime()
        self.scroll_speed = 0

        # 遅延読み込み用キュー
        self.load_queue = []
        self.is_loading = False

        # バッチ更新用
        self.pending_updates = {}

        # UIコンポーネント
        self.setup_ui()

        # モデルの変更を監視
        self.image_model.data_changed.connect(self.refresh)

        # タイマー設定
        self.setup_timers()

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

    def setup_timers(self):
        """タイマーを設定"""
        # スクロールのデバウンスタイマー
        self.scroll_debounce_timer = QTimer()
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.timeout.connect(self.load_visible_images)

        # UI更新タイマー
        self.update_timer = QTimer()
        self.update_timer.setInterval(100)  # 100ms間隔で更新
        self.update_timer.timeout.connect(self.apply_pending_updates)
        self.update_timer.start()

        # 読み込みキュー処理タイマー
        self.load_timer = QTimer()
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(self.process_load_queue)

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
        print(f"DEBUG: scroll_aware_image_grid display_current_page start, current_page={self.current_page}", flush=True)
        # 既存のアイテムをクリア
        self.clear_grid()

        # 画像がない場合は何もしない
        if self.image_model.image_count() == 0:
            return

        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)
        print(f"DEBUG: Displaying images from index {start_idx} to {start_idx + self.page_size - 1}")

        # グリッドに画像を配置
        for i, image_path in enumerate(images):
            row, col = divmod(i, self.columns)

            # ラベルを作成
            label = QLabel()
            print(f"DEBUG: Creating label for {image_path}, initial size: {label.size()}, styleSheet: {label.styleSheet()}")
            label.setFixedSize(150, 150)
            print(f"DEBUG: After setFixedSize, size: {label.size()}")
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)  # 一時的に左上揃えに変更
            label.setStyleSheet("border: 1px solid #cccccc;")  # background-colorを一時的に削除
            print(f"DEBUG: After styleSheet, styleSheet: {label.styleSheet()}")

            # プレースホルダーの設定
            label.setText("...")
            print(f"DEBUG: After setText, text: '{label.text()}', pixmap: {label.pixmap() is not None}")

            # パスを保存
            label.image_path = image_path
            label.is_loaded = False
            label.is_loading = False

            # まずキャッシュをチェック
            if self.thumbnail_cache:
                thumbnail = self.thumbnail_cache.get_thumbnail(image_path, (140, 140))
                if thumbnail and not thumbnail.isNull():
                    print(f"DEBUG: Found in cache for {image_path}")
                    label.setPixmap(thumbnail)
                    label.setScaledContents(True)
                    label.is_loaded = True
                    self.loaded_images.add(image_path)
                else:
                    print(f"DEBUG: Not found in cache for {image_path}")

            # クリックイベントを設定
            label.mousePressEvent = lambda event, path=image_path: self.on_image_click(path)

            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)

            # マッピングを保存
            self.image_labels[image_path] = label
        print(f"DEBUG: scroll_aware_image_grid display_current_page end, num images={len(images)}", flush=True)

        # 最初のページの場合はすぐに読み込みを開始
        if self.current_page == 0:
            # 最初のページの画像を優先的にキャッシュ
            for image_path in images:
                if image_path not in self.loaded_images:
                    self.load_queue.insert(0, (image_path, self.image_labels[image_path]))
            self.process_load_queue()
        else:
            # 他のページは通常通り遅延読み込み
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

        # ワーカーを作成して読み込みを開始（デバッグ出力を追加）
        try:
            from ..controllers.optimized_thumbnail_worker import OptimizedThumbnailWorker

            # サムネイルキャッシュをワーカーに渡す（デバッグ出力）
            print(f"サムネイル読み込み開始: {image_path}")
            print(f"サムネイルキャッシュ: {self.thumbnail_cache is not None}")

            worker = OptimizedThumbnailWorker(image_path, (140, 140), self.thumbnail_cache)

            def on_thumbnail_created(result):
                path, thumbnail = result
                if path == image_path:
                    print(f"サムネイル読み込み完了: {path}")
                    if thumbnail is None or thumbnail.isNull():
                        print(f"警告: サムネイルが無効 - {path}")
                        label.setText("Error")
                    else:
                        # 更新キューに追加
                        self.update_thumbnail(path, thumbnail)
                        label.setToolTip(path)

                    label.is_loading = False
                    # 次のアイテムを処理
                    QTimer.singleShot(10, self.process_load_queue)

            def on_error(error_msg):
                print(f"サムネイル読み込みエラー: {image_path} - {error_msg}")
                label.setText("Error")
                label.is_loading = False
                QTimer.singleShot(10, self.process_load_queue)

            worker.signals.result.connect(on_thumbnail_created)
            worker.signals.error.connect(on_error)
            self.worker_manager.start_worker(f"thumbnail_{image_path}", worker)

        except ImportError as e:
            # インポートエラーのトラブルシューティング
            print(f"インポートエラー: {e}")
            # 絶対インポートを試みる
            try:
                import sys, os
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from controllers.optimized_thumbnail_worker import OptimizedThumbnailWorker

                worker = OptimizedThumbnailWorker(image_path, (140, 140), self.thumbnail_cache)
                # 以下、同じコールバック設定...
                # Note: コールバック設定の重複を避けるため、ここでは省略
                worker.signals.result.connect(on_thumbnail_created)
                worker.signals.error.connect(on_error)
                self.worker_manager.start_worker(f"thumbnail_{image_path}", worker)
            except Exception as e2:
                print(f"絶対インポートも失敗: {e2}")
                label.setText("Import Error")
                label.is_loading = False
                QTimer.singleShot(10, self.process_load_queue)

    def update_thumbnail(self, image_path, thumbnail):
        """
        特定の画像のサムネイルを更新

        Args:
            image_path (str): 画像のパス
            thumbnail (QPixmap): 新しいサムネイル
        """
        # 更新をキューに追加
        self.pending_updates[image_path] = thumbnail

    def apply_pending_updates(self):
        """保留中のサムネイル更新をバッチ処理で適用"""
        # 保留中の更新が無ければ何もしない
        if not self.pending_updates:
            return

        print(f"DEBUG: Applying {len(self.pending_updates)} pending updates")

        # バッチ処理でUI更新（最大10件ずつ処理）
        batch_count = 0
        update_keys = list(self.pending_updates.keys())

        for image_path in update_keys:
            if batch_count >= 10:  # 1回の更新で最大10件まで
                break
                
            if image_path in self.image_labels:
                thumbnail = self.pending_updates[image_path]
                label = self.image_labels[image_path]
                print(f"DEBUG: Before setPixmap - image_path: {image_path}, thumbnail valid: {not thumbnail.isNull()}, label exists: {label is not None}")

                # UIを更新（デバッグ出力）
                print(f"サムネイル表示: {image_path}")
                print(f"DEBUG: Thumbnail size - width: {thumbnail.width()}, height: {thumbnail.height()}")
                
                # ラベルの状態を確認
                print(f"DEBUG: Label state before update - is_loaded: {getattr(label, 'is_loaded', False)}, is_loading: {getattr(label, 'is_loading', False)}")
                
                label.setPixmap(thumbnail)
                label.setScaledContents(True)  # ピックスマップをラベルサイズに合わせてスケーリング
                print(f"DEBUG: setPixmap applied to label for {image_path}. Label text: '{label.text()}', Pixmap set: {not label.pixmap().isNull()}")
                label.is_loaded = True
                self.loaded_images.add(image_path)

                # 処理済みの項目を削除
                del self.pending_updates[image_path]
                batch_count += 1

        # 更新があった場合はレイアウトを調整
        if batch_count > 0:
            print(f"DEBUG: Applied {batch_count} updates")
            self.update()

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
        self.pending_updates.clear()

        # グリッド内のすべてのウィジェットを削除
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

    def prev_page(self):
        """前のページに移動"""
        print("DEBUG: prev_page called in scroll_aware_image_grid")
        if self.current_page > 0:
            print(f"DEBUG: Moving from page {self.current_page} to {self.current_page - 1}")
            self.current_page -= 1
            
            # キャッシュの状態を確認
            if self.thumbnail_cache:
                stats = self.thumbnail_cache.get_stats()
                print(f"DEBUG: Cache stats before display - memory: {stats['memory_cache_count']}/{stats['memory_cache_limit']}, disk: {stats['disk_cache_count']}")
            
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
