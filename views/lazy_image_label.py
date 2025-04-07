"""
遅延読み込み画像ラベルモジュール - 改良版

スクロール領域内で可視状態に応じて画像を遅延読み込みするラベルウィジェット。
動的なサイズ調整に対応しています。
"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal, QSize, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QLinearGradient, QFont

class LazyImageLabel(QLabel):
    """
    スクロール領域内で可視状態に応じて画像を遅延読み込みするラベルウィジェット
    
    画像の読み込み状態に応じて異なる表示を行い、可視状態になったときに
    画像の読み込みを開始するシグナルを発行します。
    動的なサイズ調整に対応しています。
    """
    # シグナル定義
    load_image_request = Signal(str)  # 画像読み込みリクエスト（画像パスを引数に持つ）
    image_clicked = Signal(str)        # 画像クリック（画像パスを引数に持つ）
    
    # 読み込み状態の定数
    STATE_NOT_LOADED = 0    # 未読み込み
    STATE_LOADING = 1       # 読み込み中
    STATE_LOADED = 2        # 読み込み完了
    STATE_ERROR = 3         # エラー
    
    def __init__(self, image_path=None, size=None, parent=None):
        """
        初期化
        
        Args:
            image_path (str, optional): 画像ファイルパス
            size (QSize, optional): サムネイルサイズ
            parent (QWidget, optional): 親ウィジェット
        """
        super().__init__(parent)
        self.thumbnail_size = size if size else QSize(150, 150)
        self.image_path = image_path
        self.pixmap_data = None
        self.loading_state = self.STATE_NOT_LOADED
        self.is_visible_in_viewport = False
        self.hover = False
        
        # 表示スタイル設定
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(self.thumbnail_size)
        self.setStyleSheet("""
            LazyImageLabel {
                border: 1px solid #cccccc;
                background-color: #f9f9f9;
                border-radius: 3px;
            }
            LazyImageLabel:hover {
                border: 1px solid #aaaaaa;
                background-color: #f0f0f0;
            }
        """)
        
        # マウスカーソル追跡を有効化
        self.setMouseTracking(True)
    
    def update_size(self, new_size):
        """
        サイズを更新
        
        Args:
            new_size (QSize): 新しいサイズ
        """
        if self.thumbnail_size != new_size:
            self.thumbnail_size = new_size
            self.setFixedSize(self.thumbnail_size)
            
            # 画像が既に読み込まれている場合は、リサイズした画像を設定
            if self.loading_state == self.STATE_LOADED and self.pixmap_data:
                scaled_pixmap = self.pixmap_data.scaled(
                    self.thumbnail_size.width(), 
                    self.thumbnail_size.height(),
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                super().setPixmap(scaled_pixmap)
    
    def setPixmap(self, pixmap):
        """
        画像を設定
        
        Args:
            pixmap (QPixmap): 設定する画像
        """
        self.pixmap_data = pixmap
        self.loading_state = self.STATE_LOADED
        
        # サイズに合わせた画像を表示
        scaled_pixmap = pixmap.scaled(
            self.thumbnail_size.width(), 
            self.thumbnail_size.height(),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        super().setPixmap(scaled_pixmap)
        
        # ツールチップを設定
        if self.image_path:
            self.setToolTip(self.image_path)

    def set_thumbnail(self, pixmap):
        """
        サムネイルを設定するためのラッパー
        
        Args:
            pixmap (QPixmap): サムネイル画像
        """
        self.setPixmap(pixmap)
    
    def setLoadingState(self, state):
        """
        読み込み状態を設定
        
        Args:
            state (int): 読み込み状態
        """
        if self.loading_state != state:
            self.loading_state = state
            self.update()  # 再描画
    
    def setVisibleInViewport(self, visible):
        """
        可視状態を設定
        
        Args:
            visible (bool): 可視状態
        """
        if self.is_visible_in_viewport != visible:
            self.is_visible_in_viewport = visible
            
            # 可視状態になり、まだ読み込まれていない場合は読み込みを開始
            if visible and self.loading_state == self.STATE_NOT_LOADED:
                self.setLoadingState(self.STATE_LOADING)
                if self.image_path:
                    self.load_image_request.emit(self.image_path)
    
    def enterEvent(self, event):
        """マウスが入ったときのイベント"""
        self.hover = True
        self.update()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """マウスが出たときのイベント"""
        self.hover = False
        self.update()
        super().leaveEvent(event)
    
    def paintEvent(self, event):
        """
        描画イベント
        
        読み込み状態に応じて異なる表示を行います。
        """
        if self.loading_state == self.STATE_LOADED and self.pixmap_data:
            # 画像が読み込まれている場合は通常の描画
            super().paintEvent(event)
            
            # ホバー時のハイライト効果（オプション）
            if self.hover:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing, True)
                pen = QPen(QColor(70, 130, 180, 100))  # 半透明の青
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawRect(1, 1, self.width() - 2, self.height() - 2)
        else:
            # 自前で描画
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            
            # 背景描画
            if self.loading_state == self.STATE_ERROR:
                # エラー時は薄い赤色の背景
                painter.fillRect(self.rect(), QColor(255, 220, 220))
            else:
                # 通常は薄いグレーの背景
                painter.fillRect(self.rect(), QColor(249, 249, 249))
            
            # ホバー時の背景
            if self.hover:
                painter.fillRect(self.rect(), QColor(240, 240, 240))
            
            # 枠線描画
            pen = QPen(QColor(204, 204, 204))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(QRect(0, 0, self.width() - 1, self.height() - 1))
            
            # 状態に応じたテキストとアイコン表示
            text = ""
            if self.loading_state == self.STATE_NOT_LOADED:
                text = "未読み込み"
                self.draw_waiting_icon(painter)
            elif self.loading_state == self.STATE_LOADING:
                text = "読み込み中..."
                self.draw_loading_icon(painter)
            elif self.loading_state == self.STATE_ERROR:
                text = "エラー"
                self.draw_error_icon(painter)
            
            if text:
                # テキスト描画
                painter.setPen(QColor(100, 100, 100))
                painter.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignCenter, text)
    
    def draw_waiting_icon(self, painter):
        """
        待機アイコンの描画
        
        Args:
            painter (QPainter): 描画に使用するペインター
        """
        size = min(self.width(), self.height()) * 0.3
        center_x = self.width() / 2
        center_y = self.height() / 2 - 10
        
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.drawEllipse(center_x - size/2, center_y - size/2, size, size)
        
        # 時計の針
        painter.drawLine(center_x, center_y, center_x + size/2 * 0.6, center_y - size/2 * 0.6)
        painter.drawLine(center_x, center_y, center_x, center_y - size/2 * 0.8)
    
    def draw_loading_icon(self, painter):
        """
        読み込み中アイコンの描画
        
        Args:
            painter (QPainter): 描画に使用するペインター
        """
        size = min(self.width(), self.height()) * 0.3
        center_x = self.width() / 2
        center_y = self.height() / 2 - 10
        
        # 回転する円弧を描画
        import time
        angle = int((time.time() * 200) % 360)
        
        painter.setPen(QPen(QColor(70, 130, 180), 2))
        painter.drawArc(center_x - size/2, center_y - size/2, size, size, angle * 16, 120 * 16)
        painter.drawArc(center_x - size/2, center_y - size/2, size, size, (angle + 180) * 16, 120 * 16)
    
    def draw_error_icon(self, painter):
        """
        エラーアイコンの描画
        
        Args:
            painter (QPainter): 描画に使用するペインター
        """
        size = min(self.width(), self.height()) * 0.3
        center_x = self.width() / 2
        center_y = self.height() / 2 - 10
        
        painter.setPen(QPen(QColor(200, 0, 0), 2))
        
        # Xマークを描画
        painter.drawLine(
            center_x - size/2, center_y - size/2,
            center_x + size/2, center_y + size/2
        )
        painter.drawLine(
            center_x + size/2, center_y - size/2,
            center_x - size/2, center_y + size/2
        )
    
    def mousePressEvent(self, event):
        """
        マウスプレスイベント
        
        画像がクリックされたときにシグナルを発行します。
        """
        if event.button() == Qt.LeftButton and self.image_path:
            self.image_clicked.emit(self.image_path)
        super().mousePressEvent(event)
    
    def sizeHint(self):
        """デフォルトサイズのヒント"""
        return self.thumbnail_size
