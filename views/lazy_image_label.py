"""
遅延読み込み画像ラベルモジュール

スクロール領域内で可視状態に応じて画像を遅延読み込みするラベルウィジェット。
"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, Signal, QSize, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen

class LazyImageLabel(QLabel):
    """
    スクロール領域内で可視状態に応じて画像を遅延読み込みするラベルウィジェット
    
    画像の読み込み状態に応じて異なる表示を行い、可視状態になったときに
    画像の読み込みを開始するシグナルを発行します。
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
    
    def setPixmap(self, pixmap):
        """
        画像を設定
        
        Args:
            pixmap (QPixmap): 設定する画像
        """
        self.pixmap_data = pixmap
        self.loading_state = self.STATE_LOADED
        super().setPixmap(pixmap)
        print(f"DEBUG: setPixmap called, image_path={self.image_path}")
        
        # ツールチップを設定
        if self.image_path:
            self.setToolTip(self.image_path)

    def set_thumbnail(self, pixmap):
        """
        サムネイルを設定するためのラッパー
        
        Args:
            pixmap (QPixmap): サムネイル画像
        """
        print(f"DEBUG: set_thumbnail called for {self.image_path}", flush=True)
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
            print(f"DEBUG: setVisibleInViewport called with visible={visible}, image_path={self.image_path}, loading_state={self.loading_state}")
        
            # 可視状態になり、まだ読み込まれていない場合は読み込みを開始
            if visible and self.loading_state == self.STATE_NOT_LOADED:
                self.setLoadingState(self.STATE_LOADING)
                if self.image_path:
                    self.load_image_request.emit(self.image_path)
    
    def paintEvent(self, event):
        """
        描画イベント
        
        読み込み状態に応じて異なる表示を行います。
        """
        if self.loading_state == self.STATE_LOADED and self.pixmap_data:
            # 画像が読み込まれている場合は通常の描画
            super().paintEvent(event)
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
            
            # 枠線描画
            pen = QPen(QColor(204, 204, 204))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(QRect(0, 0, self.width() - 1, self.height() - 1))
            
            # 状態に応じたテキスト表示
            text = ""
            if self.loading_state == self.STATE_NOT_LOADED:
                text = "未読み込み"
            elif self.loading_state == self.STATE_LOADING:
                text = "読み込み中..."
            elif self.loading_state == self.STATE_ERROR:
                text = "エラー"
            
            if text:
                # テキスト描画
                painter.setPen(QColor(100, 100, 100))
                painter.drawText(self.rect(), Qt.AlignCenter, text)
    
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
