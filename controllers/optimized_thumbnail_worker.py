"""
最適化されたサムネイル生成ワーカーモジュール

このモジュールは互換性のために維持されていますが、UnifiedThumbnailWorkerへの移行を推奨します。
"""
import warnings
from .unified_thumbnail_worker import UnifiedThumbnailWorker

class OptimizedThumbnailWorker(UnifiedThumbnailWorker):
    """
    メモリ使用を最適化したサムネイル生成ワーカークラス（レガシー）
    
    この実装は互換性のために維持されていますが、代わりに統合版の
    UnifiedThumbnailWorkerを使用することを推奨します。
    """
    
    def __init__(self, image_path, size, thumbnail_cache=None):
        """
        初期化
        
        Args:
            image_path: 原画像のパス
            size: 生成するサムネイルのサイズ (width, height)
            thumbnail_cache: サムネイルキャッシュ
        """
        warnings.warn(
            "OptimizedThumbnailWorkerは廃止予定です。代わりにUnifiedThumbnailWorkerを使用してください。",
            DeprecationWarning, stacklevel=2
        )
        
        # PILエンジンを優先して利用
        super().__init__(
            image_path=image_path,
            size=size,
            thumbnail_cache=thumbnail_cache,
            use_vips=False  # VIPSは使わずPILを優先
        )
