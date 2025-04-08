"""
高度なサムネイルキャッシュモジュール

このモジュールは互換性のために維持されていますが、UnifiedThumbnailCacheへの移行を推奨します。
"""
import warnings
from .unified_thumbnail_cache import UnifiedThumbnailCache

class AdvancedThumbnailCache(UnifiedThumbnailCache):
    """
    高度なサムネイルキャッシュクラス（レガシー）
    
    この実装は互換性のために維持されていますが、代わりに統合版の
    UnifiedThumbnailCacheを使用することを推奨します。
    """
    
    def __init__(self, memory_limit=100, disk_cache_dir=None, db_path=None):
        """
        初期化
        
        Args:
            memory_limit: メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir: ディスクキャッシュのディレクトリパス
            db_path: SQLiteデータベースのパス
        """
        warnings.warn(
            "AdvancedThumbnailCacheは廃止予定です。代わりにUnifiedThumbnailCacheを使用してください。",
            DeprecationWarning, stacklevel=2
        )
        
        super().__init__(
            memory_limit=memory_limit,
            disk_cache_dir=disk_cache_dir,
            db_path=db_path
        )
