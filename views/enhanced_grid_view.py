# --- START OF FILE enhanced_grid_view.py ---

"""
拡張グリッドビューモジュール

効率的なサムネイル表示のための拡張グリッドビュークラスを提供します。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QGridLayout, QLabel, QPushButton, QComboBox,
    QSpacerItem, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect, QPoint
from PySide6.QtGui import QPixmap

from .lazy_image_label import LazyImageLabel

class EnhancedGridView(QWidget):
    """
    効率的なサムネイル表示のための拡張グリッドビュークラス

    遅延読み込みとスクロール連動による最適化機能を持つグリッドビュー。
    ページネーションと表示密度の調整にも対応しています。
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
        self.columns = 4
        self.page_size = 64  # 一度に表示する画像の数
        self.current_page = 0
        self.total_pages = 0
        self.thumbnail_size = QSize(150, 150)
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        # self.visible_labels = set() # visible_labels は不要になったため削除
        self.load_batch_size = 8  # 一度に読み込む画像の数を増やす

        # UIコンポーネント
        self.setup_ui()

        # モデルの変更を監視
        self.image_model.data_changed.connect(self.refresh)

        # 可視ラベルの読み込みを定期的にチェック
        self.load_timer = QTimer(self)
        self.load_timer.setInterval(150)  # 150ms間隔 (少し長めに)
        self.load_timer.timeout.connect(self.load_visible_thumbnails)
        self.load_timer.start()

        # スクロールイベントにも接続してタイマーをリスタート
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)
        self.scroll_debounce_timer = QTimer(self)
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.setInterval(100) # スクロール後の待機時間
        self.scroll_debounce_timer.timeout.connect(self.load_visible_thumbnails)


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

        # スクロールエリアにスタイルを適用
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        # 画像グリッドウィジェット
        self.content_widget = QWidget()
        # self.content_widget.setStyleSheet("background-color: #f0f0f0;") # 背景色はスクロールエリアに依存させる
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_area.setWidget(self.content_widget)

        # 上部コントロールエリア
        top_controls = QHBoxLayout()

        # 表示密度選択
        density_label = QLabel("表示密度:")
        self.density_combo = QComboBox()
        self.density_combo.addItems(["小", "中", "大"])
        self.density_combo.setCurrentIndex(1)  # デフォルトは「中」
        self.density_combo.currentIndexChanged.connect(self.on_density_changed)

        top_controls.addWidget(density_label)
        top_controls.addWidget(self.density_combo)
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
            # 空の場合のメッセージ表示など（任意）
            # placeholder_label = QLabel("画像がありません")
            # placeholder_label.setAlignment(Qt.AlignCenter)
            # self.grid_layout.addWidget(placeholder_label, 0, 0, 1, self.columns)
            self.update_page_controls() # ページラベルを更新
            return

        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)

        # グリッドに画像を配置
        for i, image_path in enumerate(images):
            row, col = divmod(i, self.columns)

            # 遅延読み込みラベルを作成
            label = LazyImageLabel(image_path, self.thumbnail_size)

            # シグナルを接続 (修正箇所)
            label.image_clicked.connect(self.on_image_click)
            # label.visible_changed.connect(self.on_label_visibility_changed) # 不要なため削除

            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)

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

    # visible_changed シグナルが存在しないため、このメソッドは不要
    # def on_label_visibility_changed(self, is_visible, image_path):
    #     """
    #     ラベルの可視状態変更時の処理

    #     Args:
    #         is_visible (bool): 可視状態
    #         image_path (str): 画像のパス
    #     """
    #     if is_visible:
    #         self.visible_labels.add(image_path)
    #     else:
    #         if image_path in self.visible_labels:
    #             self.visible_labels.remove(image_path)

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

            # 読み込み状態を確認 (修正箇所)
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
            # print("DEBUG: No labels to load in viewport.", flush=True)
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
                self.thumbnail_needed.emit(path, self.thumbnail_size) # QSize オブジェクトを渡す
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
                # print(f"DEBUG: Thumbnail updated for: {image_path}", flush=True)
            elif label and thumbnail.isNull():
                 print(f"DEBUG: Received null thumbnail for: {image_path}", flush=True)
                 label.setLoadingState(LazyImageLabel.STATE_ERROR) # エラー状態にする
            # else:
                 # print(f"DEBUG: Label not found or already removed for: {image_path}", flush=True)

    def clear_grid(self):
        """グリッドをクリア"""
        # 読み込みタイマーを一時停止
        self.load_timer.stop()
        self.scroll_debounce_timer.stop()

        # print(f"DEBUG: Clearing grid. {len(self.image_labels)} labels to remove.", flush=True)
        self.image_labels.clear()
        # self.visible_labels.clear() # 不要

        # グリッド内のすべてのウィジェットを安全に削除
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # print("DEBUG: Grid cleared.", flush=True)
        # 読み込みタイマーを再開
        self.load_timer.start()


    def prev_page(self):
        """前のページに移動"""
        # print("DEBUG: prev_page called in enhanced_grid_view", flush=True)
        if self.current_page > 0:
            self.current_page -= 1
            self.display_current_page()
            self.update_page_controls()
            # print(f"DEBUG: prev_page finished, current_page={self.current_page}", flush=True)

            # スクロール位置をリセット
            self.scroll_area.verticalScrollBar().setValue(0)

    def next_page(self):
        """次のページに移動"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.display_current_page()
            self.update_page_controls()
            # print(f"DEBUG: next_page finished, current_page={self.current_page}", flush=True)

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
        # インデックスに応じてサムネイルサイズと列数を変更
        old_thumbnail_size = self.thumbnail_size
        if index == 0:  # 小
            self.thumbnail_size = QSize(100, 100)
            self.columns = 6
            self.page_size = 48
        elif index == 1:  # 中
            self.thumbnail_size = QSize(150, 150)
            self.columns = 4
            self.page_size = 32
        elif index == 2:  # 大
            self.thumbnail_size = QSize(200, 200)
            self.columns = 3
            self.page_size = 24

        # サイズが変わった場合のみリフレッシュ
        if old_thumbnail_size != self.thumbnail_size:
            self.refresh()


    def resizeEvent(self, event):
        """
        リサイズイベント処理

        ウィンドウサイズに応じて列数を動的に調整します。

        Args:
            event: リサイズイベント
        """
        super().resizeEvent(event)

        # # --- 動的な列数調整 (オプション) ---
        # # 有効にする場合は以下のコメントアウトを解除し、
        # # on_density_changed での columns 設定を基本値とする
        # width = self.width()
        # density_idx = self.density_combo.currentIndex()

        # # 密度に応じた基本サイズ
        # base_size = self.thumbnail_size.width()

        # # マージンとスペーシングを考慮して列数を計算
        # # (マージン 2*10 + 列間のスペース (columns-1)*5)
        # available_width = width - 20 - (self.columns - 1) * 5
        # new_columns = max(1, available_width // (base_size + 5)) # 5はスペーシング

        # # 列数が変わった場合は更新
        # if new_columns != self.columns:
        #     print(f"DEBUG: Resizing - Width: {width}, New Columns: {new_columns}")
        #     self.columns = new_columns
        #     self.refresh()
        # # --- 動的な列数調整ここまで ---

        # リサイズ後にも可視性チェックをトリガー
        self.load_visible_thumbnails()