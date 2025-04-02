"""
最適化されたサムネイル生成ワーカーモジュール

メモリ使用を最適化したサムネイル生成ワーカークラスを提供します。
特に大きなサイズの画像を効率的に処理します。
"""
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap, QImage
from .workers import BaseWorker

class OptimizedThumbnailWorker(BaseWorker):
    """
    メモリ使用を最適化したサムネイル生成ワーカークラス
    
    大きなサイズの画像を効率的にサムネイル化し、
    メモリ使用量を削減します。
    """
    
    def __init__(self, image_path, size, thumbnail_cache=None):
        """
        初期化
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): 生成するサムネイルのサイズ (width, height)
            thumbnail_cache (ThumbnailCache, optional): サムネイルキャッシュ
        """
        super().__init__()
        self.image_path = image_path
        self.size = size
        self.thumbnail_cache = thumbnail_cache
    
    @Slot()
    def work(self):
        """
        サムネイルを生成
        
        メモリ使用量を最適化しながらサムネイルを生成します。
        特に大きなサイズの画像に対して効率的に動作します。
        
        Returns:
            tuple: (image_path, thumbnail) - 画像パスとサムネイル画像のタプル
        """
        print(f"サムネイル生成開始: {self.image_path}")
        # キャッシュをチェック
        if self.thumbnail_cache:
            thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
            if thumbnail is not None:
                print(f"キャッシュヒット: {self.image_path}")
                return (self.image_path, thumbnail)
        
        try:
            print(f"DEBUG: Starting to load {self.image_path}")
            
            # 低解像度でまず読み込み（メタデータだけを取得して実際のサイズを確認）
            image_info = QImage(self.image_path)
            print(f"DEBUG: image_info loaded. width={image_info.width()}, height={image_info.height()}, target_size={self.size}")
            
            # 非常に大きな画像の場合は、低解像度で読み込み直す
            if (not image_info.isNull() and
                (image_info.width() > self.size[0] * 4 or image_info.height() > self.size[1] * 4)):
                if (not image_info.isNull() and
                    (image_info.width() > self.size[0] * 4 or image_info.height() > self.size[1] * 4)):
                    # 低解像度なフォーマットで読み込み直し、8ビットインデックスカラーモードに変換
                    image = QImage(self.image_path)
                    if not image.isNull():
                        image = image.convertToFormat(QImage.Format_Indexed8)
                else:
                    image = image_info
            
            if image.isNull():
                raise ValueError(f"画像を読み込めません: {self.image_path}")
            
            # サムネイル生成
            pixmap = QPixmap.fromImage(image)
            thumbnail = pixmap.scaled(
                self.size[0], self.size[1],
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # キャッシュに保存
            if self.thumbnail_cache:
                self.thumbnail_cache.store_thumbnail(self.image_path, self.size, thumbnail)
            print(f"サムネイル生成完了: {self.image_path}")
            return (self.image_path, thumbnail)
            
        except Exception as e:
            print(f"エラー発生: {self.image_path}, 理由: {e}")
            # エラーが発生した場合はプレースホルダーを返す
            pixmap = QPixmap(self.size[0], self.size[1])
            pixmap.fill(Qt.lightGray)
            return (self.image_path, pixmap)
