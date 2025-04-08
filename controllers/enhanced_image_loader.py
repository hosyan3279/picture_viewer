# --- START REFACTORED controllers/enhanced_image_loader.py ---
"""
拡張画像ローダーモジュール

効率的な画像の読み込みと処理を管理するクラスを提供します。
"""
import os
# Import QTimer from PySide6.QtCore
from PySide6.QtCore import QObject, Signal, Slot, QSize, QThread, QMutex, QTimer
from PySide6.QtGui import QPixmap, Qt

# UnifiedThumbnailWorker をインポート
from .unified_thumbnail_worker import UnifiedThumbnailWorker
from .directory_scanner import DirectoryScannerWorker
from utils import logger # ロガーを追加

class ThumbnailRequest:
    """サムネイルリクエストを表すクラス"""

    def __init__(self, image_path, size, priority=0):
        """
        初期化

        Args:
            image_path (str): 画像のパス
            size (QSize): 生成するサムネイルのサイズ
            priority (int, optional): 優先度 (大きいほど優先)
        """
        self.image_path = image_path
        self.size = size
        self.priority = priority
        self.timestamp = 0  # 追跡用タイムスタンプ（あれば）

class EnhancedImageLoader(QObject):
    """
    効率的な画像の読み込みと処理を管理するクラス

    キャッシュの活用、優先度ベースの処理、バッチ処理を行います。
    libvipsを使用した高速サムネイル生成に対応しています。
    """
    # シグナル定義
    progress_updated = Signal(int)
    loading_finished = Signal()
    thumbnail_created = Signal(str, object)  # (image_path, thumbnail)
    error_occurred = Signal(str)

    def __init__(self, image_model, thumbnail_cache, worker_manager):
        """
        初期化

        Args:
            image_model: 画像データモデル
            thumbnail_cache: サムネイルキャッシュ
            worker_manager: ワーカーマネージャー
        """
        super().__init__()
        self.image_model = image_model
        self.thumbnail_cache = thumbnail_cache
        self.worker_manager = worker_manager

        # 基本設定
        self.thumbnail_size = (150, 150) # Default, might be overridden by request
        self.completed_tasks = 0
        self.total_tasks = 0

        # リクエスト管理
        self.pending_requests = []
        self.active_requests = set()
        self.request_mutex = QMutex() # Use QMutex for thread safety with Qt signals/slots

        # 同時処理数を増やす（libvipsの高速処理を活かすため）
        # TODO: Consider making this configurable
        self.max_concurrent_requests = 8

        logger.debug("EnhancedImageLoader initialized.")

    def load_images_from_folder(self, folder_path):
        """
        フォルダから画像を読み込む

        Args:
            folder_path (str): 画像を読み込むフォルダのパス
        """
        logger.info(f"Loading images from folder: {folder_path}")
        # 既存の画像をクリア (clear内でdata_changedが発行される)
        self.image_model.clear()

        # タスクカウンターをリセット
        self.completed_tasks = 0
        self.total_tasks = 0

        # 画像ファイルを検索 (DirectoryScannerWorker を使用)
        # Check if path exists and is a directory before starting worker
        if not os.path.isdir(folder_path):
            error_msg = f"指定されたパスは有効なディレクトリではありません: {folder_path}"
            logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self.loading_finished.emit() # Ensure loading finished is emitted even on error
            return

        worker = DirectoryScannerWorker(folder_path)

        # Connect signals appropriately
        # Use lambda to ensure correct argument handling if needed, or direct connection
        worker.signals.result.connect(self.process_file_list)
        worker.signals.error.connect(self.handle_scan_error) # Use a specific error handler
        worker.signals.progress.connect(self.handle_scan_progress) # Use a specific progress handler
        worker.signals.finished.connect(self.handle_scan_finished) # Handle worker finish

        if not self.worker_manager.start_worker("folder_scan", worker):
             error_msg = f"フォルダスキャンワーカーの起動に失敗: {folder_path}"
             logger.error(error_msg)
             self.error_occurred.emit(error_msg)
             self.loading_finished.emit()


    @Slot(list) # Explicitly define the expected type for the slot
    def process_file_list(self, file_list):
        """
        ファイルリストを一括で処理

        Args:
            file_list (list): 画像ファイルパスのリスト
        """
        logger.info(f"Processing {len(file_list)} files found by scanner.")
        # 結果が空の場合
        if not file_list:
            logger.warning("フォルダ内に画像ファイルが見つかりませんでした")
            # Emit error? Or just finish? Decided to just finish silently as scan completed.
            # self.error_occurred.emit("フォルダ内に画像ファイルが見つかりませんでした")
            return # Do not emit loading_finished here, wait for handle_scan_finished

        # 画像モデルにファイルを追加 (バッチ処理)
        self.image_model.add_images_batch(file_list)
        logger.info(f"Files added to model. Total images: {self.image_model.image_count()}")
        # Do not emit loading_finished here, wait for handle_scan_finished

    @Slot(int, str) # Adjust signature if DirectoryScannerWorker progress signal changes
    def handle_scan_progress(self, percentage, status_text=""):
        """Handles progress updates from the directory scanner."""
        # logger.debug(f"Scan progress: {percentage}% - {status_text}")
        self.progress_updated.emit(percentage) # Forward the percentage

    @Slot()
    def handle_scan_finished(self):
        """Handles the finished signal from the directory scanner worker."""
        logger.info("Directory scan worker finished.")
        self.loading_finished.emit() # Emit finished signal after scan worker completes

    @Slot(str, QSize, int) # Add priority to slot signature
    def request_thumbnail(self, image_path, size, priority=0):
        """
        サムネイルをリクエスト

        Args:
            image_path (str): 画像のパス
            size (QSize): 生成するサムネイルのサイズ
            priority (int, optional): 優先度 (大きいほど優先)
        """
        if not image_path or not os.path.exists(image_path):
             logger.warning(f"Invalid or non-existent image path requested: {image_path}")
             # Emit error or just ignore? Ignoring for now.
             # self.thumbnail_created.emit(image_path, QPixmap()) # Emit empty pixmap?
             return

        thumbnail_size_tuple = (size.width(), size.height())
        logger.debug(f"Thumbnail requested: {image_path} size {thumbnail_size_tuple} priority {priority}")

        # まずはキャッシュをチェック
        cached_thumbnail = self.thumbnail_cache.get_thumbnail(image_path, thumbnail_size_tuple)

        if cached_thumbnail and not cached_thumbnail.isNull():
            # キャッシュにあればすぐに返す
            logger.debug(f"Cache hit for: {image_path}")
            self.thumbnail_created.emit(image_path, cached_thumbnail)
            return
        else:
             logger.debug(f"Cache miss for: {image_path}")


        # キャッシュになければリクエストを追加 (using QMutex for thread safety)
        # self.request_mutex.lock() # Locking seems unnecessary if called from main thread only
        # try:
        request_key = (image_path, thumbnail_size_tuple)

        # Check if already active
        if request_key in self.active_requests:
            logger.debug(f"Request already active: {request_key}")
            # Optionally update priority if needed
            return

        # Check pending requests and update priority or add new
        found_pending = False
        for i, req in enumerate(self.pending_requests):
            # Check both path and size object (QSize comparison works)
            if req.image_path == image_path and req.size == size:
                # Update priority if higher
                if priority > req.priority:
                    self.pending_requests[i].priority = priority
                    # Re-sort pending requests based on new priority
                    self.pending_requests.sort(key=lambda r: -r.priority)
                    logger.debug(f"Updated priority for pending request: {request_key}")
                found_pending = True
                break

        if not found_pending:
            request = ThumbnailRequest(image_path, size, priority)
            self.pending_requests.append(request)
            # Sort after adding new request
            self.pending_requests.sort(key=lambda r: -r.priority)
            logger.debug(f"Added new pending request: {request_key}")

        # finally:
        #     self.request_mutex.unlock()

        # リクエスト処理を開始
        self._process_next_request()

    def _process_next_request(self):
        """次のサムネイルリクエストを処理"""
        # Check active requests limit
        if len(self.active_requests) >= self.max_concurrent_requests:
            logger.debug(f"Max concurrent thumbnail workers reached ({len(self.active_requests)}). Waiting.")
            return

        # Get next request (using QMutex for safety, although likely overkill if only called from main thread)
        # self.request_mutex.lock()
        # try:
        if not self.pending_requests:
            logger.debug("No pending thumbnail requests.")
            return

        request = self.pending_requests.pop(0)
        request_key = (request.image_path, (request.size.width(), request.size.height()))

        # Double check if already active (might happen in rare race conditions without proper locking)
        if request_key in self.active_requests:
             logger.warning(f"Request {request_key} somehow became active before processing. Skipping.")
             # QTimer.singleShot(0, self._process_next_request) # Try next immediately
             return


        # Add to active requests
        self.active_requests.add(request_key)
        # finally:
        #     self.request_mutex.unlock()

        logger.debug(f"Processing request: {request_key}")

        # Use UnifiedThumbnailWorker
        worker = UnifiedThumbnailWorker(request.image_path, request.size, self.thumbnail_cache)

        # Connect signals with lambda to pass the request key
        worker.signals.result.connect(lambda result, rk=request_key: self.on_thumbnail_created(result, rk))
        worker.signals.error.connect(lambda error, rk=request_key: self.on_thumbnail_error(error, rk))
        # No need to connect finished if WorkerManager handles it

        worker_id = f"thumbnail_{os.path.basename(request.image_path)}_{request.size.width()}x{request.size.height()}" # Use os.path.basename
        if not self.worker_manager.start_worker(worker_id, worker, request.priority): # Pass priority
             logger.error(f"Failed to start thumbnail worker for {request_key}")
             self.active_requests.discard(request_key) # Remove from active if start fails
             self.error_occurred.emit(f"サムネイルワーカーの起動に失敗: {request.image_path}")
             QTimer.singleShot(0, self._process_next_request) # Try next


    @Slot(tuple, tuple) # result is (str, QPixmap), request_key is (str, tuple)
    def on_thumbnail_created(self, result, request_key):
        """
        サムネイル生成完了時の処理

        Args:
            result (tuple): (image_path, thumbnail) のタプル
            request_key (tuple): Processed request key (image_path, size_tuple)
        """
        image_path, thumbnail = result
        logger.debug(f"Thumbnail created for: {request_key}")

        # 結果を通知
        # Check if thumbnail is valid before emitting
        if thumbnail and not thumbnail.isNull():
            self.thumbnail_created.emit(image_path, thumbnail)
        else:
             logger.warning(f"Received null/invalid thumbnail for {request_key}")
             # Optionally emit an error or a placeholder
             self.error_occurred.emit(f"無効なサムネイルを受信: {image_path}")


        # 処理中リストから削除
        self.active_requests.discard(request_key)

        # 次のリクエストを処理
        QTimer.singleShot(0, self._process_next_request) # Use QTimer for safety

    @Slot(str, tuple) # error is str, request_key is (str, tuple)
    def on_thumbnail_error(self, error, request_key):
        """
        サムネイル生成エラー時の処理

        Args:
            error (str): エラーメッセージ
            request_key (tuple): Processed request key (image_path, size_tuple)
        """
        image_path, size_tuple = request_key
        logger.error(f"Thumbnail generation error for {request_key}: {error}")

        # エラーを通知
        self.error_occurred.emit(f"サムネイル生成エラー ({image_path}): {error}")
        # Optionally emit an empty/placeholder pixmap for the UI
        # self.thumbnail_created.emit(image_path, QPixmap())

        # 処理中リストから削除
        self.active_requests.discard(request_key)

        # 次のリクエストを処理
        QTimer.singleShot(0, self._process_next_request) # Use QTimer for safety

    @Slot(str) # Slot for directory scanner errors
    def handle_scan_error(self, error_message):
        """
        ディレクトリ スキャン エラーの処理

        Args:
            error_message (str): エラーメッセージ
        """
        logger.error(f"Directory scan error: {error_message}")
        self.error_occurred.emit(error_message)
        # Do not emit loading_finished here, wait for handle_scan_finished
# --- END REFACTORED controllers/enhanced_image_loader.py ---
