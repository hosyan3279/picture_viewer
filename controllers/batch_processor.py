# --- START REFACTORED controllers/batch_processor.py ---
"""
バッチ処理モジュール

画像の一括処理を行うクラスを提供します。
"""
from typing import List, Set, Tuple, Optional, Any, Dict, Union
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QSize # Import QSize
from PySide6.QtGui import QPixmap # Import QPixmap for type hinting if needed
import os  # Import os module

# Use UnifiedThumbnailWorker
from .unified_thumbnail_worker import UnifiedThumbnailWorker
from utils import logger, get_config
from models import UnifiedThumbnailCache # Import cache for type hinting
from .worker_manager import WorkerManager # Import manager for type hinting

class BatchProcessor(QObject):
    """
    画像の一括処理を行うクラス

    大量の画像をバッチ単位で効率的に処理します。
    libvipsを使用した高速サムネイル生成に対応しています。
    """
    # シグナル定義
    batch_progress = Signal(int, int)  # (processed_count, total_count)
    batch_completed = Signal()
    thumbnail_created = Signal(str, object)  # (image_path, thumbnail: QPixmap)
    error_occurred = Signal(str)  # エラーメッセージ

    def __init__(self, worker_manager: WorkerManager, thumbnail_cache: UnifiedThumbnailCache, batch_size: int = None, max_concurrent: int = None):
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
        self.processing: Set[str] = set()  # 処理中の画像パスのセット (worker_id might be better?)
        self.completed: Set[str] = set()  # 処理完了した画像パスのセット
        self.thumbnail_size: Tuple[int, int] = (150, 150) # Default size
        self.total_count: int = 0
        self.is_processing: bool = False
        self.current_jobs: Dict[str, str] = {} # Maps worker_id to image_path

        logger.debug(
            f"BatchProcessor initialized: batch_size={batch_size}, max_concurrent={max_concurrent}"
        )

    def process_images(self, image_paths: List[str], thumbnail_size: Union[Tuple[int, int], QSize] =(150, 150)) -> None:
        """
        画像のバッチ処理を開始

        Args:
            image_paths: 処理する画像パスのリスト
            thumbnail_size: サムネイルのサイズ (width, height) or QSize
        """
        logger.info(f"Starting batch processing for {len(image_paths)} images.")
        try:
            # Convert QSize to tuple if necessary
            if isinstance(thumbnail_size, QSize):
                proc_thumbnail_size = (thumbnail_size.width(), thumbnail_size.height())
            else:
                proc_thumbnail_size = thumbnail_size

            # 前回の処理が完了していない場合は中止
            if self.is_processing:
                logger.warning("Previous batch processing is still running. Cancelling it.")
                self.cancel()

            # 入力の検証
            if not image_paths:
                logger.warning("Image list for batch processing is empty.")
                self.error_occurred.emit("処理する画像リストが空です")
                return

            # 状態のリセット
            self.queue = list(image_paths) # Make a copy
            self.processing.clear()
            self.completed.clear()
            self.current_jobs.clear()
            self.thumbnail_size = proc_thumbnail_size
            self.total_count = len(image_paths)

            logger.info(f"Batch processing started: {self.total_count} images, thumbnail size={self.thumbnail_size}")

            # 処理を開始
            self.is_processing = True
            # Emit initial progress
            self.batch_progress.emit(0, self.total_count)
            self._process_next_batch()

        except Exception as e:
            logger.exception(f"Error starting batch processing: {e}") # Log exception details
            self.error_occurred.emit(f"バッチ処理の開始に失敗しました: {e}")
            self.is_processing = False # Ensure state is reset on error

    def _process_next_batch(self) -> None:
        """次のバッチを処理"""
        # Use try-except block for safety
        try:
             # Check if processing should stop
            if not self.is_processing:
                logger.info("Processing stopped or cancelled.")
                return

            # すべての処理が完了した場合 (queue is empty AND no jobs are processing)
            if not self.queue and not self.current_jobs:
                logger.info(f"Batch processing completed: {len(self.completed)}/{self.total_count} images.")
                self.is_processing = False
                # Final progress update
                self._update_progress()
                self.batch_completed.emit()
                return

            # 処理中のワーカーが最大数に達している場合は待機
            active_workers = len(self.current_jobs)
            if active_workers >= self.max_concurrent:
                logger.debug(f"Max concurrent batch workers reached ({active_workers}/{self.max_concurrent}). Waiting.")
                return

            # 次のバッチを取得
            slots_available = self.max_concurrent - active_workers
            batch_limit = min(self.batch_size, slots_available, len(self.queue))

            if batch_limit <= 0:
                # No slots or no items in queue, but still processing jobs, so just return
                # logger.debug("No slots available or queue empty, waiting for jobs to finish.")
                return

            logger.debug(f"Preparing next batch: Trying to get up to {batch_limit} tasks.")

            batch_paths = [self.queue.pop(0) for _ in range(batch_limit)]

            logger.debug(f"Starting batch processing for {len(batch_paths)} tasks.")

            # バッチ内の各画像に対してワーカーを作成
            for image_path in batch_paths:
                # Check if processing should stop
                if not self.is_processing:
                    logger.info("Processing stopped during batch creation.")
                    # Put remaining paths back? Or just stop? Stopping for now.
                    self.queue.insert(0, image_path) # Put back the current one
                    return

                # Generate a unique worker ID
                worker_id = f"batch_{os.path.basename(image_path)}_{self.thumbnail_size[0]}x{self.thumbnail_size[1]}_{time.time()}"

                # Check cache first
                cached_thumbnail = None
                if self.thumbnail_cache:
                    cached_thumbnail = self.thumbnail_cache.get_thumbnail(image_path, self.thumbnail_size)

                if cached_thumbnail and not cached_thumbnail.isNull():
                    logger.debug(f"Cache hit (batch): {image_path}")
                    # Emit the result directly
                    self.thumbnail_created.emit(image_path, cached_thumbnail)
                    self.completed.add(image_path)
                    self._update_progress()
                    # Try to process next immediately if cache hit
                    QTimer.singleShot(0, self._process_next_batch)
                    continue # Skip worker creation

                # If cache miss, start worker
                logger.debug(f"Starting worker {worker_id} for image: {image_path}")

                # Add to processing BEFORE starting worker
                self.current_jobs[worker_id] = image_path
                self.processing.add(image_path) # Keep track of image paths being processed

                try:
                    # Use UnifiedThumbnailWorker
                    worker = UnifiedThumbnailWorker(image_path, self.thumbnail_size, self.thumbnail_cache, worker_id=worker_id)

                    # Connect signals using lambda to capture worker_id
                    worker.signals.result.connect(lambda result, w_id=worker_id: self._on_thumbnail_created(w_id, result))
                    worker.signals.error.connect(lambda error, w_id=worker_id: self._on_worker_error(w_id, error))
                    # Finished signal might not be needed if handled by WorkerManager
                    # worker.signals.finished.connect(lambda w_id=worker_id: self._on_worker_finished(w_id))

                    # Start worker via WorkerManager
                    if not self.worker_manager.start_worker(worker_id, worker):
                         logger.error(f"Failed to start worker {worker_id} for image {image_path}")
                         # Clean up if worker failed to start
                         self.current_jobs.pop(worker_id, None)
                         self.processing.discard(image_path)
                         self._on_worker_error(worker_id, f"Failed to start worker") # Simulate error

                except Exception as e:
                    logger.exception(f"Error creating worker {worker_id} for {image_path}: {e}")
                    # Clean up on creation error
                    self.current_jobs.pop(worker_id, None)
                    self.processing.discard(image_path)
                    self._on_worker_error(worker_id, f"Worker creation failed: {e}")

            # After submitting a batch, check if more can be processed immediately
            # This helps fill slots quickly if cache hits occur
            if len(self.current_jobs) < self.max_concurrent and self.queue:
                 QTimer.singleShot(0, self._process_next_batch)


        except Exception as e:
             logger.exception(f"Error in _process_next_batch loop: {e}")
             self.error_occurred.emit(f"バッチ処理ループ中にエラーが発生しました: {e}")
             # Attempt to recover or stop cleanly
             self.is_processing = False # Stop processing on loop error


    # These slots receive worker_id now
    @Slot(str, tuple) # worker_id, result=(image_path, thumbnail)
    def _on_thumbnail_created(self, worker_id: str, result: Tuple[str, QPixmap]) -> None:
        """
        サムネイル作成完了時の処理 (Worker ID aware)
        """
        if worker_id not in self.current_jobs:
            logger.warning(f"Received result for unknown or finished worker: {worker_id}")
            return # Ignore stale signals

        image_path, thumbnail = result
        logger.debug(f"Worker {worker_id} completed successfully for {image_path}.")

        if not thumbnail or thumbnail.isNull():
            logger.warning(f"Worker {worker_id} returned invalid thumbnail for {image_path}")
            self.error_occurred.emit(f"無効なサムネイルが生成されました: {image_path}")
            # Treat as error for completion logic
            self._handle_worker_completion(worker_id, success=False)
            return

        # Emit signal
        self.thumbnail_created.emit(image_path, thumbnail)
        self._handle_worker_completion(worker_id, success=True)


    @Slot(str, str) # worker_id, error_message
    def _on_worker_error(self, worker_id: str, error: str) -> None:
        """
        ワーカーエラー時の処理 (Worker ID aware)
        """
        if worker_id not in self.current_jobs:
             logger.warning(f"Received error for unknown or finished worker: {worker_id}")
             return # Ignore stale signals

        image_path = self.current_jobs.get(worker_id, "Unknown Image")
        logger.error(f"Worker {worker_id} error for {image_path}: {error}")
        self.error_occurred.emit(f"画像処理エラー: {image_path} - {error}")

        self._handle_worker_completion(worker_id, success=False)

    def _handle_worker_completion(self, worker_id: str, success: bool) -> None:
        """Handles common logic when a worker finishes (success or error)."""
        if worker_id not in self.current_jobs:
             return # Already handled or unknown

        image_path = self.current_jobs.pop(worker_id, None)
        if image_path:
             self.processing.discard(image_path)
             self.completed.add(image_path) # Mark as completed regardless of success for progress

        self._update_progress()

        # Trigger processing the next batch if processing is still active
        if self.is_processing:
            QTimer.singleShot(0, self._process_next_batch) # Use QTimer for safety


    # This slot might not be needed if WorkerManager handles finish notification
    # @Slot(str) # worker_id
    # def _on_worker_finished(self, worker_id: str) -> None:
    #     """ワーカー完了時の処理 (Worker ID aware)"""
    #     logger.debug(f"Worker finished signal received: {worker_id}")
    #     # Completion logic is handled in _on_thumbnail_created or _on_worker_error
    #     # This slot could be used for cleanup if needed, but might be redundant.
    #     pass


    def _update_progress(self) -> None:
        """進捗状況を更新"""
        # Ensure thread safety if needed, though likely called from main thread via signals
        processed_count = len(self.completed)
        try:
            progress_percent = int(100 * processed_count / max(1, self.total_count)) if self.total_count > 0 else 0
        except ZeroDivisionError:
            progress_percent = 0

        logger.debug(f"Batch progress: {processed_count}/{self.total_count} ({progress_percent}%)")
        self.batch_progress.emit(processed_count, self.total_count)

    def is_complete(self) -> bool:
        """
        すべての処理が完了したかどうかを返す
        """
        return not self.is_processing and len(self.completed) == self.total_count and not self.current_jobs

    def cancel(self) -> None:
        """処理を中止"""
        if not self.is_processing:
            logger.debug("Batch processing is not currently active.")
            return

        logger.info("Attempting to cancel batch processing.")
        self.is_processing = False # Stop scheduling new tasks immediately

        try:
            # Cancel running workers managed by WorkerManager
            cancelled_count = 0
            # Make a copy of keys to avoid modification during iteration
            worker_ids_to_cancel = list(self.current_jobs.keys())
            logger.debug(f"Cancelling {len(worker_ids_to_cancel)} active workers.")

            for worker_id in worker_ids_to_cancel:
                if self.worker_manager.cancel_worker(worker_id):
                    cancelled_count += 1
                # Remove from current_jobs even if cancel fails, as we're stopping
                image_path = self.current_jobs.pop(worker_id, None)
                if image_path:
                     self.processing.discard(image_path)
                     # Don't add to completed on cancel

            # Clear the queue
            queue_count = len(self.queue)
            self.queue.clear()

            # Reset remaining state variables
            self.processing.clear()
            self.current_jobs.clear() # Should be empty now

            logger.info(f"Batch processing cancelled: {cancelled_count} workers cancelled, {queue_count} tasks discarded.")
            # Emit completed signal on cancellation? Or a specific cancelled signal?
            # Emitting completed might be confusing. Let's skip it.
            # self.batch_completed.emit()

        except Exception as e:
            logger.exception(f"Error during batch processing cancellation: {e}")
            # Ensure processing state is false even if cancel encounters errors
            self.is_processing = False
            self.processing.clear()
            self.current_jobs.clear()
            self.queue.clear()


    def get_status(self) -> Dict[str, Any]:
        """
        現在の処理状態の情報を取得
        """
        processed_count = len(self.completed)
        try:
             progress_percent = int(100 * processed_count / max(1, self.total_count)) if self.total_count > 0 else 0
        except ZeroDivisionError:
             progress_percent = 0

        return {
            "is_processing": self.is_processing,
            "queued": len(self.queue),
            "processing": len(self.current_jobs), # Use current_jobs length
            "completed": processed_count,
            "total": self.total_count,
            "progress_percent": progress_percent
        }
# --- END REFACTORED controllers/batch_processor.py ---
