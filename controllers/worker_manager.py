# --- START REFACTORED controllers/worker_manager.py ---
"""
ワーカーマネージャーモジュール

マルチスレッド処理を管理するクラスを提供します。
"""
from typing import Dict, List, Optional, Any, Union
import time
import threading
from PySide6.QtCore import QThreadPool, QRunnable, QObject, Signal, Slot # Import Slot
from utils import logger, get_config
from .workers import BaseWorker # Import BaseWorker for type hinting and signal connection

class WorkerManagerSignals(QObject):
    """ワーカーマネージャーからのシグナルを定義するクラス"""
    worker_started = Signal(str)  # ワーカーID
    worker_finished = Signal(str, float)  # ワーカーID, 実行時間(秒)
    worker_cancelled = Signal(str)  # ワーカーID
    all_workers_done = Signal()  # すべてのワーカーが完了したときに発行
    error_occurred = Signal(str, str)  # (worker_id, error_message)

class WorkerManager(QObject):
    """
    マルチスレッド処理を管理するクラス

    QThreadPoolを使用してQRunnableベースのワーカーを管理します。
    ワーカーの起動、停止、監視、およびリソース管理を行います。
    """

    def __init__(self, max_threads: int = None):
        """
        初期化

        Args:
            max_threads: 最大スレッド数（Noneの場合は設定またはシステムデフォルト値を使用）
        """
        super().__init__()

        # 設定から最大スレッド数を取得
        config = get_config()
        if max_threads is None:
            # Use a sensible default if config is missing
            max_threads = config.get("workers.max_concurrent", QThreadPool.globalInstance().maxThreadCount())

        # スレッドプールの取得と設定
        self.threadpool = QThreadPool.globalInstance()
        ideal_thread_count = self.threadpool.maxThreadCount()
        if max_threads is not None and max_threads > 0:
             # Don't exceed system ideal thread count unless explicitly set higher than default
             effective_max_threads = min(max_threads, ideal_thread_count) if max_threads <= ideal_thread_count else max_threads
             self.threadpool.setMaxThreadCount(effective_max_threads)

        logger.info(f"WorkerManager initialized: Max Threads={self.threadpool.maxThreadCount()} (System Ideal: {ideal_thread_count})")


        # ワーカー管理用のデータ構造
        self.active_workers: Dict[str, QRunnable] = {}  # ワーカーID → ワーカーインスタンスのマッピング
        self.worker_start_times: Dict[str, float] = {}  # ワーカーID → 開始時間のマッピング
        self.mutex = threading.RLock()  # Use RLock for reentrant lock safety

        # シグナルオブジェクト
        self.signals = WorkerManagerSignals()


    def start_worker(self, worker_id: str, worker: BaseWorker, priority: int = 0) -> bool:
        """
        ワーカーを開始

        Args:
            worker_id: ワーカーの識別子
            worker: 実行するワーカー (Must inherit from BaseWorker)
            priority: 優先度 (値が大きいほど優先度が高い)

        Returns:
            bool: ワーカーの起動に成功した場合はTrue
        """
        if not isinstance(worker, BaseWorker):
             logger.error(f"Worker {worker_id} must inherit from BaseWorker.")
             self.signals.error_occurred.emit(worker_id, "Worker type mismatch")
             return False

        try:
            with self.mutex:
                # 既存のワーカーをキャンセル（IDが重複している場合）
                if worker_id in self.active_workers:
                    logger.warning(f"Worker with ID '{worker_id}' already active. Cancelling existing one.")
                    self.cancel_worker(worker_id) # This will remove it from active_workers

                # ワーカーの完了シグナルを接続して自動的にクリーンアップ
                # Use a lambda to pass worker_id to the slot
                worker.signals.finished.connect(lambda w_id=worker_id: self._handle_worker_finished(w_id))
                worker.signals.error.connect(lambda error, w_id=worker_id: self._handle_worker_error(w_id, error))

                # 新しいワーカーを登録して開始
                self.active_workers[worker_id] = worker
                start_time = time.time()
                self.worker_start_times[worker_id] = start_time

                # ワーカーの開始をログ記録
                logger.debug(f"Starting worker: {worker_id}, Priority={priority}")

                # スレッドプールでワーカーを開始
                self.threadpool.start(worker, priority)

                # シグナルを発行
                self.signals.worker_started.emit(worker_id)

                return True

        except Exception as e:
            logger.exception(f"Error starting worker {worker_id}: {e}") # Log full traceback
            # Ensure cleanup if start fails after adding to dicts
            self.active_workers.pop(worker_id, None)
            self.worker_start_times.pop(worker_id, None)
            self.signals.error_occurred.emit(worker_id, f"Failed to start worker: {e}")
            return False

    @Slot(str) # Connected to worker.signals.finished
    def _handle_worker_finished(self, worker_id: str):
         """Handles the finished signal from a worker."""
         self.mark_worker_finished(worker_id)

    @Slot(str, str) # Connected to worker.signals.error
    def _handle_worker_error(self, worker_id: str, error_message: str):
         """Handles the error signal from a worker."""
         # Error is already logged by the worker itself usually
         # We just need to mark it as finished in the manager
         self.mark_worker_finished(worker_id)
         # Forward the error signal if needed by other parts of the application
         self.signals.error_occurred.emit(worker_id, error_message)


    def cancel_worker(self, worker_id: str) -> bool:
        """
        ワーカーをキャンセル

        Args:
            worker_id: キャンセルするワーカーの識別子

        Returns:
            bool: キャンセル操作が試行された場合はTrue (成功を保証するものではない)
        """
        logger.debug(f"Attempting to cancel worker: {worker_id}")
        cancelled_attempted = False
        try:
            with self.mutex:
                if worker_id in self.active_workers:
                    worker = self.active_workers[worker_id]

                    # ワーカーのキャンセルを試行
                    try:
                        # BaseWorker guarantees the cancel method exists
                        worker.cancel()
                        cancelled_attempted = True
                        logger.debug(f"Cancel method called for worker: {worker_id}")
                    except Exception as e:
                        logger.error(f"Error calling cancel() on worker {worker_id}: {e}")

                    # Remove immediately after attempting cancel, regardless of success.
                    # The finished signal handler (_handle_worker_finished) will do the final cleanup.
                    # However, to prevent race conditions, let's remove it here if cancel was called.
                    # If the worker finishes normally *after* cancel is called but *before* finished signal,
                    # mark_worker_finished will handle it gracefully.
                    self.active_workers.pop(worker_id, None)
                    self.worker_start_times.pop(worker_id, None)


                    # シグナルを発行
                    self.signals.worker_cancelled.emit(worker_id)
                    return True # Indicates cancellation was attempted
                else:
                    logger.debug(f"Worker {worker_id} not found in active workers for cancellation.")
                    return False

        except Exception as e:
            logger.exception(f"Error during cancel_worker process for {worker_id}: {e}")
            return False


    def cancel_all(self) -> int:
        """
        すべてのワーカーをキャンセル

        Returns:
            int: キャンセルが試行されたワーカーの数
        """
        logger.info("Attempting to cancel all active workers.")
        cancelled_count = 0
        try:
            with self.mutex:
                # Create a list of keys to avoid issues with modifying dict during iteration
                worker_ids_to_cancel = list(self.active_workers.keys())
                logger.debug(f"Found {len(worker_ids_to_cancel)} active workers to cancel.")

                for worker_id in worker_ids_to_cancel:
                    if self.cancel_worker(worker_id):
                        cancelled_count += 1

            logger.info(f"Cancellation attempted for {cancelled_count} / {len(worker_ids_to_cancel)} workers.")
            # Check if all workers are done after attempting cancellation
            if not self.active_workers:
                 logger.info("All workers seem to be finished after cancel_all.")
                 self.signals.all_workers_done.emit()

            return cancelled_count

        except Exception as e:
            logger.exception(f"Error during cancel_all workers: {e}")
            return 0


    def wait_for_all(self, timeout_ms: int = -1) -> bool:
         """
         すべてのワーカーの完了を待機 (Uses QThreadPool.waitForDone)

         Args:
             timeout_ms: タイムアウト時間（ミリ秒）。-1で無限に待機。

         Returns:
             bool: タイムアウトせずにすべてのワーカーが完了した場合はTrue
         """
         logger.info(f"Waiting for all workers to complete (Timeout: {timeout_ms}ms)...")
         # Note: waitForDone waits for tasks submitted to the pool,
         # it doesn't directly track workers managed by this class.
         # However, if all our workers are submitted here, it should work.
         result = self.threadpool.waitForDone(timeout_ms)

         # Double check our internal tracking
         with self.mutex:
             active_count = len(self.active_workers)
             if result and active_count == 0:
                 logger.info("All workers completed successfully.")
                 # all_workers_done should have been emitted by the last finished worker
             elif result and active_count > 0:
                  logger.warning(f"waitForDone returned True, but {active_count} workers still marked active internally. Potential state inconsistency.")
                  # Force check and emit if needed
                  if not self.active_workers:
                       self.signals.all_workers_done.emit()
             elif not result:
                 logger.warning(f"waitForDone timed out. {active_count} workers potentially still active.")

         return result


    def get_active_workers_count(self) -> int:
        """現在アクティブなワーカーの数を取得"""
        with self.mutex:
            return len(self.active_workers)

    def is_worker_active(self, worker_id: str) -> bool:
        """指定されたワーカーがアクティブかどうかを確認"""
        with self.mutex:
            return worker_id in self.active_workers

    def get_worker_info(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """ワーカーの情報を取得"""
        with self.mutex:
            if worker_id in self.active_workers:
                worker = self.active_workers[worker_id]
                start_time = self.worker_start_times.get(worker_id, 0)
                elapsed_time = time.time() - start_time if start_time > 0 else 0

                info = {
                    'id': worker_id,
                    # 'worker_instance': worker, # Avoid returning instance directly
                    'worker_type': type(worker).__name__,
                    'start_time': start_time,
                    'elapsed_seconds': elapsed_time,
                    'has_cancel': hasattr(worker, 'cancel') # Should always be true for BaseWorker
                }
                # Add specific info if available
                if hasattr(worker, 'get_status'):
                     info['status'] = worker.get_status()
                return info
            return None

    def get_status(self) -> Dict[str, Any]:
        """ワーカーマネージャーの状態情報を取得"""
        with self.mutex:
            active_worker_count = len(self.active_workers)
            max_threads = self.threadpool.maxThreadCount()
            active_threads = self.threadpool.activeThreadCount() # Threads currently running tasks

            current_time = time.time()
            total_elapsed = 0
            longest_elapsed = 0
            active_ids = list(self.active_workers.keys()) # Get IDs under lock

            for worker_id in active_ids:
                 start_time = self.worker_start_times.get(worker_id)
                 if start_time:
                      elapsed = current_time - start_time
                      total_elapsed += elapsed
                      longest_elapsed = max(longest_elapsed, elapsed)

            avg_elapsed = total_elapsed / active_worker_count if active_worker_count > 0 else 0

            return {
                'active_workers': active_worker_count,
                'max_threads': max_threads,
                'active_threads_in_pool': active_threads,
                'longest_running_seconds': longest_elapsed,
                'avg_running_seconds': avg_elapsed,
                'active_worker_ids': active_ids
            }


    def mark_worker_finished(self, worker_id: str) -> None:
        """
        ワーカーを完了状態としてマーク（内部使用、スロットから呼び出される）

        Args:
            worker_id: 完了したワーカーの識別子
        """
        with self.mutex:
            if worker_id in self.active_workers:
                start_time = self.worker_start_times.pop(worker_id, 0)
                elapsed_time = time.time() - start_time if start_time > 0 else 0

                # ワーカーを管理リストから削除
                del self.active_workers[worker_id]

                # 完了をログ記録
                logger.debug(f"Worker '{worker_id}' marked as finished. Elapsed: {elapsed_time:.2f}s")

                # シグナルを発行
                self.signals.worker_finished.emit(worker_id, elapsed_time)

                # すべてのワーカーが完了した場合にシグナルを発行
                if not self.active_workers:
                    logger.info("All managed workers have finished.")
                    self.signals.all_workers_done.emit()
            else:
                 logger.debug(f"Worker '{worker_id}' already marked as finished or was cancelled.")

# --- END REFACTORED controllers/worker_manager.py ---
