"""
画像グリッドビューモジュール

サムネイル画像をグリッド形式で表示するビュークラスを提供します。
"""
from PySide6.QtWidgets import QLabel, QGridLayout
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QResizeEvent

from .base_image_grid_view import BaseImageGridView

class ImageGridView(BaseImageGridView):
    """
    サムネイル画像をグリッド形式で表示するビュークラス
    
    画像のサムネイルをグリッドレイアウトで表示し、
    ページネーション機能とクリックイベントをサポートします。
    また、スクロール位置に応じた遅延読み込みを実装しています。
    """
    
    def __init__(self, image_model, worker_manager, parent=None):
        """
        初期化
        
        Args:
            image_model: 画像データモデル
            worker_manager: ワーカーマネージャー
            parent: 親ウィジェット
        """
        super().__init__(image_model, worker_manager, parent)
        self.columns = 4  # 列数の初期値
        
        # 基底クラスの設定を上書き
        self.page_size = 20  # このビューでの一ページあたりの表示数
        
        # グリッドレイアウトを作成
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(10)  # ウィジェット間のスペースを設定
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
    
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
            
            # クリックイベントを設定
            label.mousePressEvent = lambda event, path=image_path: self.on_image_click(path)
            
            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)
            
            # マッピングを保存
            self.image_labels[image_path] = label
    
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
        
        # サムネイル読み込みをリクエスト
        self.thumbnail_needed.emit(image_path, self.thumbnail_size)
    
    def clear_grid(self):
        """グリッドをクリア"""
        self.image_labels.clear()
        
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
        # バッチ処理でUI更新（最大20件ずつ処理）
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
                self.loaded_images.add(image_path)
                
                # 処理済みの項目を削除
                del self.pending_updates[image_path]
                batch_count += 1
        
        # 更新があった場合はレイアウトを調整
        if batch_count > 0:
            self.update()
    
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
