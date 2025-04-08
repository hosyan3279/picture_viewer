"""
バッチ処理モジュール

画像の一括処理を行うクラスを提供します。
"""
from typing import List, Set, Tuple, Optional, Any, Dict, Union
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from .vips_thumbnail_worker import VipsThumbnailWorker  # libvipsを使用したサムネイル生成ワーカー
from utils import logger, get_config

class BatchProcessor(QObject):
    """
    画像の一括処理を行うクラス
    
    大量の画像をバッチ単位で効率的に処理します。
    libvipsを使用した高速サムネイル生成に対応しています。
    """
    # シグナル定義
    batch_progress = Signal(int, int)  # (processed_count, total_count)
    batch_completed = Signal()
    thumbnail_created = Signal(str, object)  # (image_path, thumbnail)
    error_occurred = Signal(str)  # エラーメッセージ
    
    def __init__(self, worker_manager, thumbnail_cache, batch_size=None, max_concurrent=None):
        """
        初期化
        
        Args:
            worker_manager: ワーカーマネージャー
            thumbnail_cache: サムネイルキャッシュ
            batch_size: 一度に処理するバッチのサイズ (Noneの場合は設定から取得)
            max_concurrent: 同時に処理するワーカーの最大数 (Noneの場合は設定から取得)
        """
        super().__init__()
        
        # 設定からパラメータを取得
        config = get_config()
        if batch_size is None:
            batch_size = config.get("workers.batch_size", 20)
        if max_concurrent is None:
            max_concurrent = config.get("workers.max_concurrent", 8)
        
        self.worker_manager = worker_manager
        self.thumbnail_cache = thumbnail_cache
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        
        # 処理状態
        self.queue: List[str] = []  # 処理待ちの画像パスのリスト
        self.processing: Set[str] = set()  # 処理中の画像パスのセット
        self.completed: Set[str] = set()  # 処理完了した画像パスのセット
        self.thumbnail_size: Tuple[int, int] = (0, 0)  # 初期化後に設定される
        self.total_count: int = 0
        self.is_processing: bool = False
        
        logger.debug(
            f"BatchProcessorを初期化: batch_size={batch_size}, max_concurrent={max_concurrent}"
        )
    
    def process_images(self, image_paths: List[str], thumbnail_size: Tuple[int, int]=(150, 150)) -> None:
        """
        画像のバッチ処理を開始
        
        Args:
            image_paths: 処理する画像パスのリスト
            thumbnail_size: サムネイルのサイズ (width, height)
        """
        try:
            # 前回の処理が完了していない場合は中止
            if self.is_processing:
                logger.info("前の処理が完了していないため、処理を中止してリセットします")
                self.cancel()
            
            # 入力の検証
            if not image_paths:
                logger.warning("処理する画像リストが空です")
                self.error_occurred.emit("処理する画像リストが空です")
                return
            
            # 状態のリセット
            self.queue = list(image_paths)
            self.processing.clear()
            self.completed.clear()
            self.thumbnail_size = thumbnail_size
            self.total_count = len(image_paths)
            
            logger.info(f"画像のバッチ処理を開始: {self.total_count}個の画像, サムネイルサイズ={thumbnail_size}")
            
            # 処理を開始
            self.is_processing = True
            self._process_next_batch()
            
        except Exception as e:
            logger.error(f"バッチ処理開始エラー: {e}")
            self.error_occurred.emit(f"バッチ処理の開始に失敗しました: {e}")
            self.is_processing = False
    
    def _process_next_batch(self) -> None:
        """次のバッチを処理"""
        try:
            # すべての処理が完了した場合
            if not self.queue and not self.processing:
                logger.info(f"すべての処理が完了しました: {len(self.completed)}/{self.total_count}画像")
                self.is_processing = False
                self.batch_completed.emit()
                return
            
            # 処理中のワーカーが最大数に達している場合は待機
            if len(self.processing) >= self.max_concurrent:
                logger.debug(f"同時処理上限に達しました: {len(self.processing)}/{self.max_concurrent}")
                return
            
            # 次のバッチを取得
            batch = []
            slots_available = self.max_concurrent - len(self.processing)
            batch_limit = min(self.batch_size, slots_available)
            
            logger.debug(f"次のバッチを準備: 最大{batch_limit}個のタスクをキューから取得")
            
            while self.queue and len(batch) < batch_limit:
                batch.append(self.queue.pop(0))
            
            if not batch:
                logger.debug("処理するバッチがありません")
                return
            
            logger.debug(f"バッチの処理を開始: {len(batch)}個のタスク")
            
            # バッチ内の各画像に対してワーカーを作成
            for image_path in batch:
                # すでに処理中の場合はスキップ
                if image_path in self.processing:
                    logger.warning(f"画像 {image_path} は既に処理中です")
                    continue
                
                # キャッシュをチェック
                cached_thumbnail = None
                if self.thumbnail_cache:
                    cached_thumbnail = self.thumbnail_cache.get_thumbnail(image_path, self.thumbnail_size)
                
                if cached_thumbnail:
                    # キャッシュがあれば直接結果を返す
                    logger.debug(f"キャッシュヒット: {image_path}")
                    self.thumbnail_created.emit(image_path, cached_thumbnail)
                    self.completed.add(image_path)
                    
                    # 進捗を更新
                    self._update_progress()
                    
                    # 次のバッチを処理
                    QTimer.singleShot(0, self._process_next_batch)
                    continue
                
                logger.debug(f"画像の処理を開始: {image_path}")
                
                # 処理中に追加
                self.processing.add(image_path)
                
                # libvipsを使用したワーカーを作成
                try:
                    worker = VipsThumbnailWorker(image_path, self.thumbnail_size, self.thumbnail_cache)
                    
                    # シグナルを接続
                    worker.signals.result.connect(self._on_thumbnail_created)
                    worker.signals.error.connect(lambda error, path=image_path: self._on_worker_error(path, error))
                    worker.signals.finished.connect(lambda path=image_path: self._on_worker_finished(path))
                    
                    # ワーカーを開始
                    worker_id = f"batch_{image_path}"
                    self.worker_manager.start_worker(worker_id, worker)
                    logger.debug(f"ワーカーを開始: {worker_id}")
                    
                except Exception as e:
                    logger.error(f"ワーカー作成エラー ({image_path}): {e}")
                    self.processing.discard(image_path)  # 処理中リストから削除
                    self._on_worker_error(image_path, str(e))
            
        except Exception as e:
            logger.error(f"バッチ処理エラー: {e}")
            self.error_occurred.emit(f"バッチ処理中にエラーが発生しました: {e}")
    
    def _on_thumbnail_created(self, result: Tuple[str, Any]) -> None:
        """
        サムネイル作成完了時の処理
        
        Args:
            result: (image_path, thumbnail) - 画像パスとサムネイル画像のタプル
        """
        try:
            image_path, thumbnail = result
            
            if not thumbnail or (hasattr(thumbnail, "isNull") and thumbnail.isNull()):
                logger.warning(f"生成されたサムネイルが無効です: {image_path}")
                self.error_occurred.emit(f"無効なサムネイルが生成されました: {image_path}")
                return
            
            logger.debug(f"サムネイル作成完了: {image_path}")
            
            # シグナルを発行
            self.thumbnail_created.emit(image_path, thumbnail)
            
        except Exception as e:
            logger.error(f"サムネイル作成結果処理エラー: {e}")
            self.error_occurred.emit(f"サムネイル処理中にエラーが発生しました: {e}")
    
    def _on_worker_error(self, image_path: str, error: str) -> None:
        """
        ワーカーエラー時の処理
        
        Args:
            image_path: エラーが発生した画像のパス
            error: エラーメッセージ
        """
        logger.error(f"ワーカーエラー ({image_path}): {error}")
        self.error_occurred.emit(f"画像処理エラー: {image_path} - {error}")
        
        # 処理中リストから削除
        self.processing.discard(image_path)
        
        # エラーがあっても完了リストに追加して進捗を更新
        self.completed.add(image_path)
        self._update_progress()
        
        # 次のバッチを処理
        QTimer.singleShot(0, self._process_next_batch)
    
    def _on_worker_finished(self, image_path: str) -> None:
        """
        ワーカー完了時の処理
        
        Args:
            image_path: 処理が完了した画像のパス
        """
        logger.debug(f"ワーカー完了: {image_path}")
        
        # 処理中リストから削除
        self.processing.discard(image_path)
        
        # 完了リストに追加
        self.completed.add(image_path)
        
        # 進捗を更新
        self._update_progress()
        
        # 次のバッチを処理
        QTimer.singleShot(0, self._process_next_batch)
    
    def _update_progress(self) -> None:
        """進捗状況を更新"""
        processed_count = len(self.completed)
        progress_percent = int(100 * processed_count / max(1, self.total_count))
        
        logger.debug(f"進捗更新: {processed_count}/{self.total_count} ({progress_percent}%)")
        self.batch_progress.emit(processed_count, self.total_count)
    
    def is_complete(self) -> bool:
        """
        すべての処理が完了したかどうかを返す
        
        Returns:
            bool: すべての処理が完了した場合はTrue
        """
        is_complete = not self.is_processing and len(self.completed) == self.total_count
        return is_complete
    
    def cancel(self) -> None:
        """処理を中止"""
        if not self.is_processing:
            logger.debug("処理は既に停止しています")
            return
        
        try:
            logger.info("バッチ処理を中止します")
            
            # プロセス中のワーカーをキャンセル
            cancelled_count = 0
            for image_path in self.processing:
                worker_id = f"batch_{image_path}"
                self.worker_manager.cancel_worker(worker_id)
                cancelled_count += 1
            
            # 状態をリセット
            queue_count = len(self.queue)
            self.queue.clear()
            self.processing.clear()
            self.is_processing = False
            
            logger.info(f"バッチ処理を中止しました: {cancelled_count}個のワーカーをキャンセル、{queue_count}個のタスクを破棄")
            
        except Exception as e:
            logger.error(f"処理中止エラー: {e}")
            # エラーが発生しても処理を停止状態にする
            self.is_processing = False
    
    def get_status(self) -> Dict[str, Any]:
        """
        現在の処理状態の情報を取得
        
        Returns:
            Dict: 処理状態の情報
        """
        return {
            "is_processing": self.is_processing,
            "queued": len(self.queue),
            "processing": len(self.processing),
            "completed": len(self.completed),
            "total": self.total_count,
            "progress_percent": int(100 * len(self.completed) / max(1, self.total_count))
        }
