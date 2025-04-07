"""
フローグリッドビューモジュール

FlowLayoutを使用した画像ギャラリービューを提供します。
ウィンドウサイズに応じて自然に「流れる」ように画像を配置します。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QComboBox, QSlider, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect, QPoint, QMargins
from PySide6.QtGui import QPixmap

from .lazy_image_label import LazyImageLabel
from .flow_layout import FlowLayout

class FlowGridView(QWidget):
    """
    FlowLayoutを使用した画像ギャラリービュー
    
    ウィンドウサイズに応じて自然に「流れる」ように画像を配置します。
    遅延読み込みやページネーションなどの機能も備えています。
    """
    # シグナル定義
    image_selected = Signal(str)  # 選択された画像のパス
    thumbnail_needed = Signal(str, QSize)  # サムネイルが必要なとき (image_path, size)

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

        # 設定
        self.page_size = 100  # 一度に表示する画像の数
        self.current_page = 0
        self.total_pages = 0
        
        # サムネイルサイズの設定
        self.base_thumbnail_sizes = {
            0: QSize(100, 100),  # 小
            1: QSize(150, 150),  # 中
            2: QSize(200, 200)   # 大
        }
        self.min_thumbnail_size = 80
        self.max_thumbnail_size = 300
        self.thumbnail_size = self.base_thumbnail_sizes[1]  # デフォルトは「中」
        
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        self.load_batch_size = 10  # 一度に読み込む画像の数

        # リサイズデバウンス用タイマー
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(200)  # 200ms
        self.resize_timer.timeout.connect(self.on_resize_timeout)
        
        self.pending_resize = False

        # UIコンポーネント
        self.setup_ui()

        # モデルの変更を監視
        self.image_model.data_changed.connect(self.refresh)

        # 可視ラベルの読み込みを定期的にチェック
        self.load_timer = QTimer(self)
        self.load_timer.setInterval(150)  # 150ms間隔
        self.load_timer.timeout.connect(self.load_visible_thumbnails)
        self.load_timer.start()

        # スクロールイベントにも接続
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)
        self.scroll_debounce_timer = QTimer(self)
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.setInterval(100)
        self.scroll_debounce_timer.timeout.connect(self.load_visible_thumbnails)

    def refresh(self):
        """表示を更新"""
        # ページ数を更新
        total_images = self.image_model.image_count()
        self.total_pages = max(1, (total_images + self.page_size - 1) // self.page_size)

        # カレントページをリセット（必要に応じて）
        if self.current_page >= self.total_pages:
            self.current_page = max(0, self.total_pages - 1)

        # 現在のページを表示
        self.display_current_page()

        # ページコントロールを更新
        self.update_page_controls()
        
    def display_current_page(self):
        """現在のページを表示"""
        print(f"DEBUG: display_current_page start, current_page={self.current_page}", flush=True)
        # 既存のアイテムをクリア
        self.clear_grid()

        # 画像がない場合は何もしない
        if self.image_model.image_count() == 0:
            self.update_page_controls() # ページラベルを更新
            return

        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)

        # フローレイアウトに画像を配置
        for image_path in images:
            # 遅延読み込みラベルを作成
            label = LazyImageLabel(image_path, self.thumbnail_size)

            # シグナルを接続
            label.image_clicked.connect(self.on_image_click)

            # フローレイアウトに追加
            self.flow_layout.addWidget(label)

            # マッピングを保存
            self.image_labels[image_path] = label

        # ウィジェットが配置された後に可視性チェックをトリガー
        QTimer.singleShot(0, self.load_visible_thumbnails)
        print(f"DEBUG: display_current_page end, num images={len(images)}", flush=True)
        
    def on_image_click(self, image_path):
        """
        画像クリック時の処理

        Args:
            image_path (str): クリックされた画像のパス
        """
        self.image_selected.emit(image_path)

    def on_scroll_changed(self):
        """スクロール変更時の処理（デバウンス用）"""
        self.scroll_debounce_timer.start() # タイマーをリスタート

    def load_visible_thumbnails(self):
        """可視状態のサムネイルを読み込む"""
        if not self.image_labels:
            return

        # 表示領域を取得 (少し上下に余裕を持たせる)
        viewport = self.scroll_area.viewport()
        visible_rect = viewport.rect().adjusted(0, -viewport.height(), 0, viewport.height())

        labels_to_load = []
        for image_path, label in self.image_labels.items():
            # ラベルが有効か確認
            if not label or label.parent() is None:
                print(f"DEBUG: Skipping invalid label for {image_path}")
                continue

            # 読み込み状態を確認
            if label.loading_state == LazyImageLabel.STATE_NOT_LOADED:
                # ラベルの位置をビューポート座標系に変換
                try:
                    label_rect_in_viewport = QRect(label.mapTo(viewport, QPoint(0, 0)), label.size())

                    # 可視領域内にあるかチェック
                    if visible_rect.intersects(label_rect_in_viewport):
                        labels_to_load.append((image_path, label))
                except RuntimeError as e:
                    # mapToでエラーが発生することがある（ウィジェット削除中など）
                    print(f"DEBUG: Error mapping label for {image_path}: {e}")
                    continue # エラーの場合はスキップ

        # 読み込むラベルがなければ終了
        if not labels_to_load:
            return

        print(f"DEBUG: Found {len(labels_to_load)} labels to load.", flush=True)

        # 指定数のラベルだけ読み込む
        load_count = 0
        for path, label in labels_to_load:
            if load_count >= self.load_batch_size:
                break

            # 念のため再度状態を確認
            if label.loading_state == LazyImageLabel.STATE_NOT_LOADED:
                # 読み込み中状態に設定
                label.setLoadingState(LazyImageLabel.STATE_LOADING)

                # サムネイル読み込みをリクエスト
                print(f"DEBUG: Requesting thumbnail for {path}", flush=True)
                self.thumbnail_needed.emit(path, self.thumbnail_size)
                load_count += 1
                
    def update_thumbnail(self, image_path, thumbnail):
        """
        特定の画像のサムネイルを更新

        Args:
            image_path (str): 画像のパス
            thumbnail (QPixmap): 新しいサムネイル
        """
        if image_path in self.image_labels:
            label = self.image_labels[image_path]
            # ラベルが存在し、サムネイルが有効な場合のみ更新
            if label and not thumbnail.isNull():
                label.set_thumbnail(thumbnail)
            elif label and thumbnail.isNull():
                print(f"DEBUG: Received null thumbnail for: {image_path}", flush=True)
                label.setLoadingState(LazyImageLabel.STATE_ERROR) # エラー状態にする

    def clear_grid(self):
        """フローレイアウト内のすべてのアイテムをクリア"""
        # 読み込みタイマーを一時停止
        self.load_timer.stop()
        self.scroll_debounce_timer.stop()

        self.image_labels.clear()

        # レイアウト内のすべてのウィジェットを削除
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # 読み込みタイマーを再開
        self.load_timer.start()

    def prev_page(self):
        """前のページに移動"""
        if self.current_page > 0:
            self.current_page -= 1
            self.display_current_page()
            self.update_page_controls()

            # スクロール位置をリセット
            self.scroll_area.verticalScrollBar().setValue(0)

    def next_page(self):
        """次のページに移動"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_current_page()
            self.update_page_controls()

            # スクロール位置をリセット
            self.scroll_area.verticalScrollBar().setValue(0)
            
    def update_page_controls(self):
        """ページコントロールを更新"""
        if self.image_model.image_count() > 0:
            self.page_label.setText(f"{self.current_page + 1} / {self.total_pages}")
            self.prev_button.setEnabled(self.current_page > 0)
            self.next_button.setEnabled(self.current_page < self.total_pages - 1)
        else:
            self.page_label.setText("0 / 0")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)

    def on_density_changed(self, index):
        """
        表示密度変更時の処理

        Args:
            index (int): コンボボックスのインデックス
        """
        # インデックスに応じてサムネイルサイズを変更
        old_thumbnail_size = self.thumbnail_size
        
        # 基本サイズを取得
        self.thumbnail_size = self.base_thumbnail_sizes[index]
        
        # ページサイズを調整（密度に応じて）
        if index == 0:  # 小
            self.page_size = 100
        elif index == 1:  # 中
            self.page_size = 80
        elif index == 2:  # 大
            self.page_size = 50
            
        # ズームスライダーを更新
        self.zoom_slider.setValue(self.thumbnail_size.width())

        # サイズが変わった場合のみリフレッシュ
        if old_thumbnail_size != self.thumbnail_size:
            self.refresh()
            
    def on_zoom_changed(self, value):
        """
        ズームスライダーの値が変更されたときの処理
        
        Args:
            value (int): スライダーの値（サムネイルの幅）
        """
        # スライダードラッグ中は実際に適用せず、値の表示のみ更新
        pass
        
    def on_zoom_slider_released(self):
        """ズームスライダーがリリースされたときの処理"""
        # スライダーの現在の値を取得
        value = self.zoom_slider.value()
        
        # 新しいサムネイルサイズを設定
        old_size = self.thumbnail_size
        new_size = QSize(value, value)
        
        if old_size != new_size:
            self.thumbnail_size = new_size
            
            # ページサイズを再計算（サムネイルサイズに反比例）
            base_size = 150  # 基準サイズ
            scale_factor = base_size / value
            self.page_size = max(30, int(80 * scale_factor))
            
            # ビューを更新
            self.refresh()
    
    def resizeEvent(self, event):
        """
        リサイズイベント処理

        フローレイアウトは自動的に調整されるため、
        リサイズイベント後に可視サムネイルのチェックをトリガーします。

        Args:
            event: リサイズイベント
        """
        super().resizeEvent(event)
        
        # 可視性チェックをデバウンスして実行
        self.pending_resize = True
        self.resize_timer.start()
        
    def on_resize_timeout(self):
        """リサイズタイムアウト時の処理"""
        if self.pending_resize:
            # フローレイアウトは自動調整されるため、コンテンツ更新は不要
            # 可視サムネイルの読み込みをトリガー
            self.load_visible_thumbnails()
            self.pending_resize = False
        
    def setup_ui(self):
        """UIコンポーネントを設定"""
        # メインレイアウト
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        # コンテンツウィジェット
        self.content_widget = QWidget()
        
        # FlowLayoutを使用
        self.flow_layout = FlowLayout(self.content_widget)
        self.flow_layout.setSpacing(10)  # アイテム間のスペース
        self.flow_layout.setContentsMargins(10, 10, 10, 10)
        
        self.scroll_area.setWidget(self.content_widget)

        # 上部コントロールエリア
        top_controls = QHBoxLayout()

        # 表示密度選択
        density_label = QLabel("表示密度:")
        self.density_combo = QComboBox()
        self.density_combo.addItems(["小", "中", "大"])
        self.density_combo.setCurrentIndex(1)  # デフォルトは「中」
        self.density_combo.currentIndexChanged.connect(self.on_density_changed)

        # ズームスライダー
        zoom_label = QLabel("ズーム:")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(self.min_thumbnail_size)
        self.zoom_slider.setMaximum(self.max_thumbnail_size)
        self.zoom_slider.setValue(self.thumbnail_size.width())
        self.zoom_slider.setTickPosition(QSlider.TicksBelow)
        self.zoom_slider.setTickInterval(20)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        self.zoom_slider.sliderReleased.connect(self.on_zoom_slider_released)
        
        # スライダーのサイズポリシー設定
        self.zoom_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.zoom_slider.setMaximumWidth(200)  # 最大幅を制限

        top_controls.addWidget(density_label)
        top_controls.addWidget(self.density_combo)
        top_controls.addSpacing(20)
        top_controls.addWidget(zoom_label)
        top_controls.addWidget(self.zoom_slider)
        top_controls.addStretch()

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
        layout.addLayout(top_controls)
        layout.addWidget(self.scroll_area)
        layout.addLayout(page_controls)

        # デフォルトでボタンを無効化
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)