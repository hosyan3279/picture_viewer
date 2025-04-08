# --- START REFACTORED controllers/workers.py ---
"""
ワーカーモジュール

バックグラウンド処理を行うワーカークラスの基盤を提供します。
"""
import time
import traceback
from typing import Optional, Any, TypeVar, Generic
import os # Keep os for worker_id generation if needed
import logging # Import the logging module

from PySide6.QtCore import QObject, Signal, Slot, QRunnable
# Removed QPixmap, List, Tuple imports as specific workers are removed

from utils import logger, get_config

# 汎用型変数（戻り値型用）
T = TypeVar('T')

class WorkerSignals(QObject, Generic[T]):
    """
    ワーカーが発行するシグナルを定義するクラス

    QRunnableはQObjectを継承していないため、このクラスを通じてシグナルを発行します。
    型パラメータTを使用して、ワーカーの結果型を指定できます。
    """
    started = Signal()  # ワーカーが開始された
    finished = Signal()  # ワーカーが終了した（成功でもエラーでも）
    cancelled = Signal()  # ワーカーがキャンセルされた
    error = Signal(str)  # エラーメッセージ
    result = Signal(object)  # 処理結果 (型Tのオブジェクト)
    progress = Signal(int)  # 進捗率 (0-100)
    progress_status = Signal(str)  # 進捗状況の説明

class CancellationError(Exception):
    """ワーカーのキャンセルを示す例外"""
    pass

class BaseWorker(QRunnable):
    """
    基本ワーカークラス

    すべてのワーカークラスの基底クラスとして使用します。
    処理のキャンセル、進捗報告、エラー処理などの共通機能を提供します。
    """

    def __init__(self, worker_id: Optional[str] = None):
        """
        初期化

        Args:
            worker_id: ワーカーの識別子（省略時は自動生成）
        """
        super().__init__()
        # self.setAutoDelete(True) # Set auto delete to False if manager handles instance lifecycle? Let's keep it True for now.
        self.signals = WorkerSignals()
        self._is_cancelled = False # Use underscore for internal flag
        self._start_time = 0
        self.worker_id = worker_id or f"worker_{id(self)}"
        self._last_progress = -1 # Initialize to -1 to force first update
        self._last_progress_time = 0

        # 設定からタイムアウト値を取得
        config = get_config()
        self.progress_update_interval = config.get("workers.progress_update_interval_ms", 500) / 1000.0 # Ensure float division

    @property
    def is_cancelled(self) -> bool:
        """Check if the worker has been cancelled."""
        return self._is_cancelled

    def cancel(self) -> bool:
        """
        処理をキャンセル

        Returns:
            bool: キャンセルフラグが設定された場合はTrue, 既にキャンセル済みの場合はFalse
        """
        if self._is_cancelled:
            logger.debug(f"Worker {self.worker_id} already cancelled.")
            return False

        logger.info(f"Cancellation requested for worker: {self.worker_id}")
        self._is_cancelled = True
        # Emit cancelled signal immediately upon request
        try:
             self.signals.cancelled.emit()
        except RuntimeError as e:
             # This might happen if the event loop is not running or the object is deleted
             logger.warning(f"Could not emit cancelled signal for {self.worker_id}: {e}")
        return True

    def check_cancelled(self):
        """
        キャンセル状態をチェックし、キャンセルされていた場合は例外を発生させる

        Raises:
            CancellationError: キャンセルされた場合
        """
        if self._is_cancelled:
            # logger.debug(f"Worker {self.worker_id} check: Cancellation detected.")
            raise CancellationError(f"Worker {self.worker_id} was cancelled.")
        # No return value needed, exception is raised if cancelled

    def update_progress(self, progress: int, status: Optional[str] = None) -> None:
        """
        進捗状況を更新 (Emit signals)

        Args:
            progress: 進捗率（0-100）
            status: 状態の説明（オプション）
        """
        # Clamp progress value
        progress = max(0, min(100, progress))

        current_time = time.time()
        # Check if update should be skipped
        significant_change = abs(progress - self._last_progress) >= 5
        time_elapsed = current_time - self._last_progress_time > self.progress_update_interval

        # Update if 100%, or significant change, or enough time elapsed
        should_update = (progress == 100 and self._last_progress != 100) or significant_change or time_elapsed

        if not should_update:
            return

        try:
             self.signals.progress.emit(progress)
             if status:
                 self.signals.progress_status.emit(status)

             # Update last known values
             self._last_progress = progress
             self._last_progress_time = current_time
        except RuntimeError as e:
            logger.warning(f"Could not emit progress signal for {self.worker_id}: {e}")


    @Slot()
    def run(self) -> None:
        """ワーカーの実行スレッドエントリポイント"""
        self._start_time = time.time()
        logger.info(f"Worker '{self.worker_id}' started.")
        error_occurred = False # Flag to track if error happened

        try:
            # Emit started signal
            try:
                 self.signals.started.emit()
            except RuntimeError as e:
                 logger.warning(f"Could not emit started signal for {self.worker_id}: {e}")


            # Initial cancellation check before starting work
            self.check_cancelled()

            # Execute the main work method
            result = self.work()

            # Check cancellation again before emitting result
            self.check_cancelled()

            # Emit result if not cancelled
            try:
                 self.signals.result.emit(result)
                 logger.debug(f"Worker '{self.worker_id}' emitted result.")
            except RuntimeError as e:
                 logger.warning(f"Could not emit result signal for {self.worker_id}: {e}")


        except CancellationError:
            # Expected exception when cancelled
            logger.info(f"Worker '{self.worker_id}' cancelled.")
            # Do not emit error signal for cancellation

        except Exception as e:
            error_occurred = True
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"Worker '{self.worker_id}' encountered an error: {error_msg}")
            logger.debug(f"Error details for {self.worker_id}:", exc_info=True) # Log traceback

            # Emit error signal only if not cancelled
            if not self._is_cancelled:
                try:
                     self.signals.error.emit(error_msg)
                except RuntimeError as sig_e:
                     logger.warning(f"Could not emit error signal for {self.worker_id}: {sig_e}")

        finally:
            # Calculate elapsed time
            elapsed = time.time() - self._start_time
            # Determine log level based on whether an error occurred (excluding cancellation)
            log_level = logging.ERROR if error_occurred else logging.INFO
            logger.log(log_level, f"Worker '{self.worker_id}' finished. Elapsed: {elapsed:.3f}s")

            # Emit finished signal regardless of success, error, or cancellation
            try:
                 self.signals.finished.emit()
            except RuntimeError as e:
                 logger.warning(f"Could not emit finished signal for {self.worker_id}: {e}")


    def work(self) -> Any:
        """
        実際の処理を行うメソッド (Must be overridden by subclasses)

        処理中は定期的に check_cancelled() を呼び出して、キャンセル要求をチェックしてください。

        Returns:
            任意の型のオブジェクト（サブクラスでの実装による）

        Raises:
            NotImplementedError: オーバーライドされていない場合
        """
        raise NotImplementedError("Subclasses must implement the 'work' method.")

# Removed FolderScanWorker and ThumbnailWorker as they are replaced by
# DirectoryScannerWorker and UnifiedThumbnailWorker respectively.
# Ensure DirectoryScannerWorker and UnifiedThumbnailWorker inherit from BaseWorker.

# --- END REFACTORED controllers/workers.py ---
