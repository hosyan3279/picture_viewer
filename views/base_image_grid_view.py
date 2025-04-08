"""
基本画像グリッドビューモジュール

画像グリッドビューの基底クラスを提供します。
様々なビュー実装で共通の機能を抽象化しています。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRect
from PySide6.QtGui import QResizeEvent

class BaseImageGridView(QWidget):
    """
    画像グリッドビューの基底クラス
    
    ページネーション、スクロール連動、サムネイル更新など、
    画像グリッドビューに共通する機能を実装する抽象基底クラスです。
    子クラスでグリッドレイアウト方式を実装する必要があります。
    """
    # シグナル定義
    image_selected = Signal(str)  # 選択された画像のパス
    thumbnail_needed = Signal(str, QSize)  # サムネイルが必要（子クラスで使用）
    
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
        
        # 共通設定
        self.page_size = 20  # 一度に表示する画像の数
        self.current_page = 0
        self.total_pages = 0
        self.thumbnail_size = QSize(150, 150)  # デフォルトサムネイルサイズ
        self.image_labels = {}  # 画像パス → ラベルウィジェットのマッピング
        self.loaded_images = set()  # すでに読み込まれた画像のパスのセット
        
        # スクロールのデバウンスタイマー
        self.scroll_debounce_timer = QTimer(self)
        self.scroll_debounce_timer.setSingleShot(True)
        self.scroll_debounce_timer.setInterval(200)
        # スクロールタイマーは子クラスのメソッドに接続（派生クラスで定義されるまでは空関数を使用）
        self.scroll_debounce_timer.timeout.connect(self._safe_load_visible_images)
        
        # 更新バッチ処理用
        self.pending_updates = {}  # 保留中の更新（画像パス -> サムネイル）
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(100)  # 100ms間隔で更新
        self.update_timer.timeout.connect(self.apply_pending_updates)
        self.update_timer.start()
        
        # UIコンポーネント
        self.setup_ui()
        
        # モデルの変更を監視
        self.image_model.data_changed.connect(self.refresh)
    
    def _safe_load_visible_images(self):
        """
        安全に画像を読み込むためのラッパーメソッド
        子クラスが load_visible_images をオーバーライドしていない場合、
        この安全なメソッドが代わりに呼び出されます。
        """
        try:
            self.load_visible_images()
        except NotImplementedError:
            # 子クラスが実装していない場合は何もしない
            print("Warning: load_visible_images is not implemented in the child class")
    
    def setup_ui(self):
        """UIコンポーネントを設定"""
        # メインレイアウト
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # スクロールイベントの追跡
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)
        
        # 画像グリッドウィジェット - 子クラスで実装
        self.content_widget = QWidget()
        self.content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
    
    def create_content_layout(self):
        """
        コンテンツレイアウトを作成
        
        子クラスで実装する必要があります。
        """
        raise NotImplementedError("子クラスで実装する必要があります")
    
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
        """
        現在のページを表示
        """
        # 既存のアイテムをクリア
        self.clear_grid()
        
        # 画像がない場合は何もしない
        if self.image_model.image_count() == 0:
            return
        
        # 現在のページの画像を取得
        start_idx = self.current_page * self.page_size
        images = self.image_model.get_images_batch(start_idx, self.page_size)
        
        # 画像を配置（子クラスで実装）
        try:
            self.place_images(images)
        except NotImplementedError:
            print("Warning: place_images is not implemented in the child class")
        
        # 遅延読み込みを開始
        QTimer.singleShot(100, self._safe_load_visible_images)
    
    def place_images(self, images):
        """
        画像をビューに配置
        
        子クラスで実装する必要があります。
        
        Args:
            images (list): 画像パスのリスト
        """
        raise NotImplementedError("子クラスで実装する必要があります")
    
    def on_scroll_changed(self):
        """スクロール位置が変更されたときの処理"""
        # デバウンスのためにタイマーをリセット
        self.scroll_debounce_timer.stop()
        self.scroll_debounce_timer.start()
    
    def load_visible_images(self):
        """
        現在表示されている画像を読み込む
        
        子クラスで実装する必要があります。
        """
        raise NotImplementedError("子クラスで実装する必要があります")
    
    def on_image_click(self, image_path):
        """
        画像クリック時の処理
        
        Args:
            image_path (str): クリックされた画像のパス
        """
        self.image_selected.emit(image_path)
    
    def clear_grid(self):
        """
        グリッドをクリア
        
        子クラスで実装する必要があります。
        """
        raise NotImplementedError("子クラスで実装する必要があります")
    
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
    
    def update_thumbnail(self, image_path, thumbnail):
        """
        特定の画像のサムネイルを更新
        
        更新はキューに追加され、バッチ処理されます。
        
        Args:
            image_path (str): 画像のパス
            thumbnail: 新しいサムネイル
        """
        # 更新をキューに追加
        self.pending_updates[image_path] = thumbnail
    
    def apply_pending_updates(self):
        """
        保留中のサムネイル更新をバッチ処理で適用
        """
        # 保留中の更新が無ければ何もしない
        if not self.pending_updates:
            return
        
        # バッチ処理でUI更新（子クラスで実装）
        try:
            self.process_updates(list(self.pending_updates.keys()))
        except NotImplementedError:
            # 子クラスで実装されていない場合は何もしない
            self.pending_updates.clear()
            print("Warning: process_updates is not implemented in the child class")
    
    def process_updates(self, update_keys):
        """
        サムネイル更新をバッチ処理する
        
        子クラスで実装する必要があります。
        
        Args:
            update_keys (list): 更新する画像パスのリスト
        """
        raise NotImplementedError("子クラスで実装する必要があります")
    
    def resizeEvent(self, event: QResizeEvent):
        """
        ウィンドウリサイズ時に呼ばれるイベントハンドラ
        
        子クラスで必要に応じてオーバーライドしてください。
        
        Args:
            event (QResizeEvent): リサイズイベント
        """
        super().resizeEvent(event)
