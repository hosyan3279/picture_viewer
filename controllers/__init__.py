# --- START REFACTORED controllers/__init__.py ---
"""
コントローラーモジュールの初期化ファイル

アプリケーションのビジネスロジック、非同期処理、
モデルとビュー間の連携を担当するクラスを提供します。
"""
from .worker_manager import WorkerManager
# BaseWorker と CancellationError のみを workers からインポート
from .workers import BaseWorker, CancellationError
from .directory_scanner import DirectoryScannerWorker # Use this for scanning
from .unified_thumbnail_worker import UnifiedThumbnailWorker # Use this for thumbnails
from .enhanced_image_loader import EnhancedImageLoader
from .batch_processor import BatchProcessor

__all__ = [
    'WorkerManager',
    'BaseWorker',
    'DirectoryScannerWorker',
    'UnifiedThumbnailWorker',
    'EnhancedImageLoader',
    'BatchProcessor',
    'CancellationError',
]
# --- END REFACTORED controllers/__init__.py ---
