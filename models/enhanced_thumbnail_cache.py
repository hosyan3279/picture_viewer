"""
拡張サムネイルキャッシュモジュール

このモジュールは互換性のために維持されていますが、UnifiedThumbnailCacheへの移行を推奨します。
"""
import warnings
from .unified_thumbnail_cache import UnifiedThumbnailCache

class EnhancedThumbnailCache(UnifiedThumbnailCache):
    """
    拡張サムネイルキャッシュクラス（レガシー）
    
    この実装は互換性のために維持されていますが、代わりに統合版の
    UnifiedThumbnailCacheを使用することを推奨します。
    """
    
    def __init__(self, memory_limit=None, disk_cache_dir=None, disk_cache_limit_mb=None, cleanup_interval=None):
        """
        初期化
        
        Args:
            memory_limit: メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir: ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb: ディスクキャッシュの上限（MB）
            cleanup_interval: クリーンアップ間隔（ミリ秒）
        """
        warnings.warn(
            "EnhancedThumbnailCacheは廃止予定です。代わりにUnifiedThumbnailCacheを使用してください。",
            DeprecationWarning, stacklevel=2
        )
        
        super().__init__(
            memory_limit=memory_limit,
            disk_cache_dir=disk_cache_dir,
            disk_cache_limit_mb=disk_cache_limit_mb,
            cleanup_interval=cleanup_interval
        )
