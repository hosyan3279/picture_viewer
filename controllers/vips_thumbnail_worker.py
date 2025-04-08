"""
libvipsを使用した高速サムネイル生成ワーカーモジュール

このモジュールは互換性のために維持されていますが、UnifiedThumbnailWorkerへの移行を推奨します。
"""
import warnings
from .unified_thumbnail_worker import UnifiedThumbnailWorker

class VipsThumbnailWorker(UnifiedThumbnailWorker):
    """
    libvipsを使用した高速サムネイル生成ワーカークラス（レガシー）
    
    この実装は互換性のために維持されていますが、代わりに統合版の
    UnifiedThumbnailWorkerを使用することを推奨します。
    """
    
    def __init__(self, image_path, size, thumbnail_cache=None, worker_id=None):
        """
        初期化
        
        Args:
            image_path: 原画像のパス
            size: 生成するサムネイルのサイズ (width, height)
            thumbnail_cache: サムネイルキャッシュ
            worker_id: ワーカーの識別子
        """
        warnings.warn(
            "VipsThumbnailWorkerは廃止予定です。代わりにUnifiedThumbnailWorkerを使用してください。",
            DeprecationWarning, stacklevel=2
        )
        
        # VIPSエンジンを強制利用
        super().__init__(
            image_path=image_path,
            size=size,
            thumbnail_cache=thumbnail_cache,
            use_vips=True,  # VIPSを常に使用
            worker_id=worker_id
        )
