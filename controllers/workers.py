"""
ワーカーモジュール

バックグラウンド処理を行うワーカークラスを提供します。
"""
import os
from PySide6.QtCore import QObject, Signal, Slot, QRunnable
from PySide6.QtGui import QPixmap, Qt

class WorkerSignals(QObject):
    """
    ワーカーが発行するシグナルを定義するクラス
    
    QRunnableはQObjectを継承していないため、このクラスを通じてシグナルを発行します。
    """
    finished = Signal()
    error = Signal(str)
    result = Signal(object)
    progress = Signal(int)

class BaseWorker(QRunnable):
    """
    基本ワーカークラス
    
    すべてのワーカークラスの基底クラスとして使用します。
    """
    
    def __init__(self):
        """初期化"""
        super().__init__()
        self.signals = WorkerSignals()
        self.is_cancelled = False
    
    def cancel(self):
        """処理をキャンセル"""
        self.is_cancelled = True
    
    @Slot()
    def run(self):
        """ワーカーの実行"""
        try:
            if not self.is_cancelled:
                result = self.work()
                if not self.is_cancelled:
                    self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
    
    def work(self):
        """
        実際の処理を行うメソッド
        
        サブクラスで実装する必要があります。
        """
        raise NotImplementedError("サブクラスで実装する必要があります")

class FolderScanWorker(BaseWorker):
    """
    フォルダ内の画像ファイルをスキャンするワーカー
    """
    
    def __init__(self, folder_path):
        """
        初期化
        
        Args:
            folder_path (str): スキャンするフォルダのパス
        """
        super().__init__()
        self.folder_path = folder_path
    
    def work(self):
        """
        フォルダ内の画像ファイルをスキャン
        
        Returns:
            list: 画像ファイルのパスのリスト
        """
        # 画像ファイルの拡張子
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
        
        # 画像ファイルの検索
        image_files = []
        for root, dirs, files in os.walk(self.folder_path):
            if self.is_cancelled:
                break
                
            for file in files:
                if self.is_cancelled:
                    break
                    
                # 拡張子をチェック
                ext = os.path.splitext(file.lower())[1]
                if ext in image_extensions:
                    image_path = os.path.join(root, file)
                    image_files.append(image_path)
                    
                    # 進捗を報告（オプション）
                    # ここでは単純化のため進捗報告は省略
        
        return image_files

class ThumbnailWorker(BaseWorker):
    """
    サムネイル画像を生成するワーカー
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
    
    def work(self):
        """
        サムネイルを生成
        
        Returns:
            tuple: (image_path, thumbnail) - 画像パスとサムネイル画像のタプル
        """
        # キャッシュをチェック
        if self.thumbnail_cache:
            thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
            if thumbnail is not None:
                return (self.image_path, thumbnail)
        
        # サムネイルの生成
        pixmap = QPixmap(self.image_path)
        if pixmap.isNull():
            raise ValueError(f"画像を読み込めません: {self.image_path}")
        
        # リサイズ
        thumbnail = pixmap.scaled(
            self.size[0], self.size[1],
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # キャッシュに保存
        if self.thumbnail_cache:
            self.thumbnail_cache.store_thumbnail(self.image_path, self.size, thumbnail)
        
        return (self.image_path, thumbnail)
