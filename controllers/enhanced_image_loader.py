"""
拡張画像ローダーモジュール

効率的な画像の読み込みと処理を管理するクラスを提供します。
"""
import os
from PySide6.QtCore import QObject, Signal, Slot, QSize, QThread, QMutex
from PySide6.QtGui import QPixmap, Qt

from ..controllers.workers import FolderScanWorker
from .directory_scanner import DirectoryScannerWorker
from .vips_thumbnail_worker import VipsThumbnailWorker  # 新しいlibvipsベースのサムネイルワーカー

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
        self.thumbnail_size = (150, 150)
        self.completed_tasks = 0
        self.total_tasks = 0
        
        # リクエスト管理
        self.pending_requests = []
        self.active_requests = set()
        self.request_mutex = QMutex()
        
        # 同時処理数を増やす（libvipsの高速処理を活かすため）
        self.max_concurrent_requests = 8  # 通常は4だが、libvipsの効率を考慮して増加
    
    def load_images_from_folder(self, folder_path):
        """
        フォルダから画像を読み込む

        Args:
            folder_path (str): 画像を読み込むフォルダのパス
        """
        # 既存の画像をクリア (clear内でdata_changedが発行される)
        self.image_model.clear()

        # タスクカウンターをリセット
        self.completed_tasks = 0
        self.total_tasks = 0

        # 画像ファイルを検索 (DirectoryScannerWorker を使用)
        worker = DirectoryScannerWorker(folder_path)

        worker.signals.result.connect(self.process_file_list)
        worker.signals.error.connect(self.handle_error)
        worker.signals.progress.connect(self.progress_updated)
        self.worker_manager.start_worker("folder_scan", worker)

    def process_file_list(self, file_list):
        """
        ファイルリストを一括で処理

        Args:
            file_list (list): 画像ファイルパスのリスト
        """
        # 結果が空の場合
        if not file_list:
            self.error_occurred.emit("フォルダ内に画像ファイルが見つかりませんでした")
            self.loading_finished.emit()
            return

        print(f"DEBUG: Processing {len(file_list)} files found by scanner.")
        # 画像モデルにファイルを追加 (バッチ処理)
        self.image_model.add_images_batch(file_list)
        print(f"DEBUG: Files added to model. Total images: {self.image_model.image_count()}")

        # フォルダスキャンとモデルへの追加が完了したことを通知
        self.loading_finished.emit()

    @Slot(str, QSize)
    def request_thumbnail(self, image_path, size, priority=0):
        """
        サムネイルをリクエスト
        
        Args:
            image_path (str): 画像のパス
            size (QSize): 生成するサムネイルのサイズ
            priority (int, optional): 優先度 (大きいほど優先)
        """
        # まずはキャッシュをチェック
        thumbnail_size = (size.width(), size.height())
        cached_thumbnail = self.thumbnail_cache.get_thumbnail(image_path, thumbnail_size)
        
        if cached_thumbnail:
            # キャッシュにあればすぐに返す
            self.thumbnail_created.emit(image_path, cached_thumbnail)
            return
        
        # キャッシュになければリクエストを追加
        self.request_mutex.lock()
        try:
            # 既に同じパスのリクエストがあるか確認
            for i, req in enumerate(self.pending_requests):
                if req.image_path == image_path and req.size.width() == size.width() and req.size.height() == size.height():
                    # 優先度を更新
                    self.pending_requests[i].priority = max(self.pending_requests[i].priority, priority)
                    # 既存リクエストが見つかったらソートし直す
                    self.pending_requests.sort(key=lambda r: -r.priority)
                    return
            
            # 新しいリクエストを追加
            request = ThumbnailRequest(image_path, size, priority)
            self.pending_requests.append(request)
            
            # 優先度順にソート
            self.pending_requests.sort(key=lambda req: -req.priority)
        finally:
            self.request_mutex.unlock()
        
        # リクエスト処理を開始
        self._process_next_request()
    
    def _process_next_request(self):
        """次のサムネイルリクエストを処理"""
        # 現在処理中のリクエストが多すぎる場合は待機
        if len(self.active_requests) >= self.max_concurrent_requests:
            return
        
        # 次のリクエストを取得
        self.request_mutex.lock()
        try:
            if not self.pending_requests:
                return
            
            request = self.pending_requests.pop(0)
            # 処理中リストに追加
            self.active_requests.add(request.image_path)
        finally:
            self.request_mutex.unlock()
        
        # libvipsを使用したサムネイル生成ワーカーを作成
        size = (request.size.width(), request.size.height())
        worker = VipsThumbnailWorker(request.image_path, size, self.thumbnail_cache)
        worker.signals.result.connect(lambda result: self.on_thumbnail_created(result, request))
        worker.signals.error.connect(lambda error: self.on_thumbnail_error(error, request))
        self.worker_manager.start_worker(f"thumbnail_{request.image_path}", worker)
    
    def on_thumbnail_created(self, result, request):
        """
        サムネイル生成完了時の処理
        
        Args:
            result (tuple): (image_path, thumbnail) のタプル
            request (ThumbnailRequest): 元のリクエスト
        """
        image_path, thumbnail = result
        
        # 結果を通知
        self.thumbnail_created.emit(image_path, thumbnail)
        
        # 処理中リストから削除
        self.active_requests.discard(image_path)
        
        # 次のリクエストを処理
        self._process_next_request()
    
    def on_thumbnail_error(self, error, request):
        """
        サムネイル生成エラー時の処理
        
        Args:
            error (str): エラーメッセージ
            request (ThumbnailRequest): 元のリクエスト
        """
        # エラーを通知
        self.error_occurred.emit(f"サムネイル生成エラー ({request.image_path}): {error}")
        
        # 処理中リストから削除
        self.active_requests.discard(request.image_path)
        
        # 次のリクエストを処理
        self._process_next_request()
    
    def handle_error(self, error_message):
        """
        エラーハンドリング

        Args:
            error_message (str): エラーメッセージ
        """
        self.error_occurred.emit(error_message)
        self.loading_finished.emit() # エラー時も完了シグナルを出す
