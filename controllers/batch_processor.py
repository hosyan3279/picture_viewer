"""
バッチ処理モジュール

画像の一括処理を行うクラスを提供します。
"""
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from ..controllers.workers import ThumbnailWorker

class BatchProcessor(QObject):
    """
    画像の一括処理を行うクラス
    
    大量の画像をバッチ単位で効率的に処理します。
    """
    # シグナル定義
    batch_progress = Signal(int, int)  # (processed_count, total_count)
    batch_completed = Signal()
    thumbnail_created = Signal(str, object)  # (image_path, thumbnail)
    
    def __init__(self, worker_manager, thumbnail_cache, batch_size=10, max_concurrent=4):
        """
        初期化
        
        Args:
            worker_manager: ワーカーマネージャー
            thumbnail_cache: サムネイルキャッシュ
            batch_size (int): 一度に処理するバッチのサイズ
            max_concurrent (int): 同時に処理するワーカーの最大数
        """
        super().__init__()
        self.worker_manager = worker_manager
        self.thumbnail_cache = thumbnail_cache
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        
        # 処理状態
        self.queue = []  # 処理待ちの画像パスのリスト
        self.processing = set()  # 処理中の画像パスのセット
        self.completed = set()  # 処理完了した画像パスのセット
        self.is_processing = False
        
    def process_images(self, image_paths, thumbnail_size=(150, 150)):
        """
        画像のバッチ処理を開始
        
        Args:
            image_paths (list): 処理する画像パスのリスト
            thumbnail_size (tuple): サムネイルのサイズ (width, height)
        """
        # 前回の処理が完了していない場合は中止
        if self.is_processing:
            self.worker_manager.cancel_all()
            self.is_processing = False
        
        # 状態のリセット
        self.queue = list(image_paths)
        self.processing.clear()
        self.completed.clear()
        self.thumbnail_size = thumbnail_size
        self.total_count = len(image_paths)
        
        # 処理を開始
        self.is_processing = True
        self._process_next_batch()
    
    def _process_next_batch(self):
        """次のバッチを処理"""
        # すべての処理が完了した場合
        if not self.queue and not self.processing:
            self.is_processing = False
            self.batch_completed.emit()
            return
        
        # 処理中のワーカーが最大数に達している場合は待機
        if len(self.processing) >= self.max_concurrent:
            return
        
        # 次のバッチを取得
        batch = []
        while self.queue and len(batch) < self.batch_size and len(self.processing) + len(batch) < self.max_concurrent:
            batch.append(self.queue.pop(0))
        
        # バッチ内の各画像に対してワーカーを作成
        for image_path in batch:
            # すでに処理中の場合はスキップ
            if image_path in self.processing:
                continue
            
            # キャッシュをチェック
            cached_thumbnail = self.thumbnail_cache.get_thumbnail(image_path, self.thumbnail_size)
            if cached_thumbnail:
                # キャッシュがあれば直接結果を返す
                self.thumbnail_created.emit(image_path, cached_thumbnail)
                self.completed.add(image_path)
                
                # 進捗を更新
                self._update_progress()
                
                # 次のバッチを処理
                QTimer.singleShot(0, self._process_next_batch)
                continue
            
            # 処理中に追加
            self.processing.add(image_path)
            
            # ワーカーを作成
            worker = ThumbnailWorker(image_path, self.thumbnail_size, self.thumbnail_cache)
            
            # シグナルを接続
            worker.signals.result.connect(self._on_thumbnail_created)
            worker.signals.finished.connect(lambda path=image_path: self._on_worker_finished(path))
            
            # ワーカーを開始
            self.worker_manager.start_worker(f"batch_{image_path}", worker)
    
    def _on_thumbnail_created(self, result):
        """
        サムネイル作成完了時の処理
        
        Args:
            result (tuple): (image_path, thumbnail) - 画像パスとサムネイル画像のタプル
        """
        image_path, thumbnail = result
        
        # シグナルを発行
        self.thumbnail_created.emit(image_path, thumbnail)
    
    def _on_worker_finished(self, image_path):
        """
        ワーカー完了時の処理
        
        Args:
            image_path (str): 処理が完了した画像のパス
        """
        # 処理中リストから削除
        if image_path in self.processing:
            self.processing.remove(image_path)
        
        # 完了リストに追加
        self.completed.add(image_path)
        
        # 進捗を更新
        self._update_progress()
        
        # 次のバッチを処理
        QTimer.singleShot(0, self._process_next_batch)
    
    def _update_progress(self):
        """進捗状況を更新"""
        processed_count = len(self.completed)
        self.batch_progress.emit(processed_count, self.total_count)
    
    def is_complete(self):
        """すべての処理が完了したかどうかを返す"""
        return not self.is_processing and len(self.completed) == self.total_count
    
    def cancel(self):
        """処理を中止"""
        if self.is_processing:
            # プロセス中のワーカーをキャンセル
            for image_path in self.processing:
                self.worker_manager.cancel_worker(f"batch_{image_path}")
            
            # 状態をリセット
            self.queue.clear()
            self.processing.clear()
            self.is_processing = False
