"""
拡張グリッドビューモジュール

効率的なサムネイル表示のための拡張グリッドビュークラスを提供します。
"""
from PySide6.QtWidgets import (
    QLabel, QGridLayout, QHBoxLayout, QComboBox,
    QSlider, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QPoint
from PySide6.QtGui import QResizeEvent

from .base_image_grid_view import BaseImageGridView
from .lazy_image_label import LazyImageLabel

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
        super().__init__(image_model, worker_manager, parent)
        
        # 設定
        self.columns = 4  # 初期列数
        self.page_size = 32  # 一度に表示する画像の数
        
        # サムネイルサイズの設定 (基本サイズ、最小、最大)
        self.base_thumbnail_sizes = {
            0: QSize(100, 100),  # 小
            1: QSize(150, 150),  # 中
            2: QSize(200, 200)   # 大
        }
        self.min_thumbnail_size = 80
        self.max_thumbnail_size = 300
        self.thumbnail_size = self.base_thumbnail_sizes[1]  # デフォルトは「中」
        
        self.load_batch_size = 8  # 一度に読み込む画像の数

        # リサイズデバウンス用タイマー
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(200)  # 200ms
        self.resize_timer.timeout.connect(self.apply_resize)
        
        # 最後のリサイズパラメータを保存
        self.last_width = 0
        self.pending_resize = False
        
        # スクロールエリアの設定
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        # 拡張UIコンポーネント
        self.setup_enhanced_ui()

        # 可視ラベルの読み込みを定期的にチェック
        self.load_timer = QTimer(self)
        self.load_timer.setInterval(150)  # 150ms間隔
        self.load_timer.timeout.connect(self.load_visible_thumbnails)
        self.load_timer.start()
        
        # グリッドレイアウトを作成
        self.grid_layout = QGridLayout(self.content_widget)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
    
    def setup_enhanced_ui(self):
        """拡張UIコンポーネントを設定"""
        # 上部コントロールエリアをレイアウトの最初に追加
        top_controls = QHBoxLayout()
        self.layout().insertLayout(0, top_controls)

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
    
    def place_images(self, images):
        """
        画像をグリッドに配置
        
        Args:
            images (list): 画像パスのリスト
        """
        for i, image_path in enumerate(images):
            row, col = divmod(i, self.columns)

            # 遅延読み込みラベルを作成
            label = LazyImageLabel(image_path, self.thumbnail_size)

            # シグナルを接続
            label.image_clicked.connect(self.on_image_click)

            # グリッドに追加
            self.grid_layout.addWidget(label, row, col)

            # マッピングを保存
            self.image_labels[image_path] = label
    
    def load_visible_thumbnails(self):
        """可視状態のサムネイルを読み込む"""
        if not self.image_labels:
            return

        # 表示領域を取得 (少し上下に余裕を持たせる)
        viewport = self.scroll_area.viewport()
        visible_rect = viewport.rect().adjusted(0, -self.thumbnail_size.height(), 0, self.thumbnail_size.height())

        labels_to_load = []
        for image_path, label in self.image_labels.items():
            # ラベルが有効か確認
            if not label or label.parent() is None:
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
                self.thumbnail_needed.emit(path, self.thumbnail_size)
                load_count += 1
    
    def clear_grid(self):
        """グリッドをクリア"""
        # 読み込みタイマーを一時停止
        self.load_timer.stop()
        self.scroll_debounce_timer.stop()

        self.image_labels.clear()

        # グリッド内のすべてのウィジェットを削除
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # 読み込みタイマーを再開
        self.load_timer.start()
    
    def process_updates(self, update_keys):
        """
        サムネイル更新をバッチ処理
        
        Args:
            update_keys (list): 更新する画像パスのリスト
        """
        batch_count = 0
        
        for image_path in update_keys:
            if batch_count >= 10:  # 1回の更新で最大10件まで
                break
                
            if image_path in self.image_labels:
                thumbnail = self.pending_updates[image_path]
                label = self.image_labels[image_path]
                
                # ラベルが存在し、サムネイルが有効な場合のみ更新
                if label and not thumbnail.isNull():
                    label.set_thumbnail(thumbnail)
                    batch_count += 1
                elif label and thumbnail.isNull():
                    label.setLoadingState(LazyImageLabel.STATE_ERROR)
                    batch_count += 1
                
                # 処理済みの項目を削除
                del self.pending_updates[image_path]
        
        # 更新があった場合はレイアウトを調整
        if batch_count > 0:
            self.update()
    
    def on_density_changed(self, index):
        """
        表示密度変更時の処理

        Args:
            index (int): コンボボックスのインデックス
        """
        # インデックスに応じてサムネイルサイズと列数を変更
        old_thumbnail_size = self.thumbnail_size
        
        # 基本サイズを取得
        self.thumbnail_size = self.base_thumbnail_sizes[index]
        
        if index == 0:  # 小
            self.columns = 6
            self.page_size = 48
        elif index == 1:  # 中
            self.columns = 4
            self.page_size = 32
        elif index == 2:  # 大
            self.columns = 3
            self.page_size = 24
            
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
            
            # 列数を再計算
            self.calculate_columns()
            
            # ビューを更新
            self.refresh()
    
    def calculate_columns(self):
        """利用可能な幅に基づいて列数を計算"""
        width = self.width()
        
        # マージンとスペーシングを考慮して列数を計算
        thumbnail_width = self.thumbnail_size.width()
        spacing = self.grid_layout.spacing()
        margins = self.grid_layout.contentsMargins()
        available_width = width - margins.left() - margins.right()
        
        # 利用可能な幅を考慮して列数を計算
        new_columns = max(1, available_width // (thumbnail_width + spacing))
        
        # 密度に基づく最小列数と最大列数の制限
        density_idx = self.density_combo.currentIndex()
        if density_idx == 0:  # 小
            min_columns = 4
            max_columns = 8
        elif density_idx == 1:  # 中
            min_columns = 3
            max_columns = 6
        else:  # 大
            min_columns = 2
            max_columns = 4
        
        # 最終的な列数
        self.columns = max(min_columns, min(new_columns, max_columns))
        
        # ページサイズを調整（列数×行数で計算）
        target_rows = 5  # 目標表示行数
        self.page_size = self.columns * target_rows
            
    def resizeEvent(self, event):
        """
        リサイズイベント処理

        ウィンドウサイズに応じて列数を動的に調整します。

        Args:
            event: リサイズイベント
        """
        super().resizeEvent(event)
        
        # リサイズ中は高頻度の更新を避けるためにデバウンスする
        self.last_width = self.width()
        self.pending_resize = True
        self.resize_timer.start()
        
    def apply_resize(self):
        """リサイズ適用（デバウンス後）"""
        if not self.pending_resize:
            return
            
        # 列数を再計算
        old_columns = self.columns
        self.calculate_columns()
        
        # 列数が変わった場合のみ更新
        if old_columns != self.columns:
            self.refresh()
            
        self.pending_resize = False
        
        # リサイズ後にも可視性チェックをトリガー
        self.load_visible_thumbnails()
