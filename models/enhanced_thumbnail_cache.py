"""
拡張サムネイルキャッシュモジュール

メモリ使用量を自動管理する拡張サムネイルキャッシュを提供します。
"""
import os
import time
import gc
from PySide6.QtCore import QTimer
from .thumbnail_cache import ThumbnailCache

class EnhancedThumbnailCache(ThumbnailCache):
    """
    拡張サムネイルキャッシュクラス
    
    メモリ使用量を監視し、定期的なクリーンアップを行うことで
    メモリ使用量を自動的に管理する機能を追加したキャッシュクラスです。
    """
    
    def __init__(self, memory_limit=200, disk_cache_dir=None, disk_cache_limit_mb=1000, cleanup_interval=60000):
        """
        初期化
        
        Args:
            memory_limit (int): メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir (str, optional): ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb (int): ディスクキャッシュの上限（MB）
            cleanup_interval (int): クリーンアップ間隔（ミリ秒）
        """
        super().__init__(memory_limit, disk_cache_dir, disk_cache_limit_mb)
        from threading import Lock
        self.cache_lock = Lock()  # キャッシュ操作用のスレッドセーフロック
        
        # 統計情報
        self.cache_hits = 0
        self.cache_misses = 0
        
        # 定期的なクリーンアップタイマー
        self.cleanup_timer = QTimer()
        self.cleanup_timer.setInterval(cleanup_interval)  # デフォルトは1分ごと
        self.cleanup_timer.timeout.connect(self.cleanup_memory_if_needed)
        self.cleanup_timer.start()
    
    def get_thumbnail(self, image_path, size):
        """
        サムネイルを取得（オーバーライド）
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            
        Returns:
            QPixmap or None: サムネイル画像。キャッシュにない場合はNone
        """
        with self.cache_lock:
            result = super().get_thumbnail(image_path, size)
            
            # キャッシュヒット率の統計を更新
            if result is not None:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            
            return result
    
    def cleanup_memory_if_needed(self):
        """メモリ使用量が閾値を超えている場合にキャッシュを整理"""
        # 無効なエントリを先に削除
        invalid_count = self.purge_invalid_entries()
        if invalid_count > 0:
            print(f"DEBUG: Removed {invalid_count} invalid cache entries")
        
        # メモリキャッシュサイズが制限の80%を超えた場合
        if len(self.memory_cache) > self.memory_limit * 0.8:
            # キャッシュサイズを70%に削減
            target_size = int(self.memory_limit * 0.7)
            items_to_remove = len(self.memory_cache) - target_size
            
            if items_to_remove > 0:
                # 最も古いアイテムを削除
                for _ in range(items_to_remove):
                    if self.access_order:
                        oldest_key = self.access_order.pop(0)
                        if oldest_key in self.memory_cache:
                            del self.memory_cache[oldest_key]
            
            # 明示的にガベージコレクションを実行
            gc.collect()
            
            # ディスクキャッシュも必要に応じて整理
            self._cleanup_disk_cache_if_needed()
    
    def clear(self, clear_disk=True):
        """
        キャッシュをクリア（オーバーライド）
        
        Args:
            clear_disk (bool): ディスクキャッシュもクリアするかどうか
        """
        super().clear(clear_disk)
        
        # 統計情報をリセット
        self.cache_hits = 0
        self.cache_misses = 0
    
    def get_stats(self):
        """
        キャッシュの統計情報を取得（拡張）
        
        Returns:
            dict: キャッシュの統計情報を含む辞書
        """
        stats = super().get_stats()
        
        # ヒット率の計算
        total_access = self.cache_hits + self.cache_misses
        hit_ratio = self.cache_hits / max(1, total_access) * 100.0
        
        # 追加の統計情報
        stats.update({
            "enhanced": True,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_ratio": hit_ratio,
            "cleanup_interval_ms": self.cleanup_timer.interval(),
        })
        
        return stats
    
    def store_thumbnail(self, image_path, size, thumbnail):
        """
        サムネイルをキャッシュに保存
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            thumbnail (QPixmap): 保存するサムネイル画像
        """
        with self.cache_lock:
            super().store_thumbnail(image_path, size, thumbnail)

    def cleanup_memory_if_needed(self):
        """メモリ使用量が閾値を超えている場合にキャッシュを整理"""
        with self.cache_lock:
            # 無効なエントリを先に削除
            invalid_count = self.purge_invalid_entries()
            if invalid_count > 0:
                print(f"DEBUG: Removed {invalid_count} invalid cache entries")
            
            # メモリキャッシュサイズが制限の80%を超えた場合
            if len(self.memory_cache) > self.memory_limit * 0.8:
                # キャッシュサイズを70%に削減
                target_size = int(self.memory_limit * 0.7)
                items_to_remove = len(self.memory_cache) - target_size
                
                if items_to_remove > 0:
                    # 最も古いアイテムを削除
                    for _ in range(items_to_remove):
                        if self.access_order:
                            oldest_key = self.access_order.pop(0)
                            if oldest_key in self.memory_cache:
                                del self.memory_cache[oldest_key]
                
                # 明示的にガベージコレクションを実行
                gc.collect()
                
                # ディスクキャッシュも必要に応じて整理
                self._cleanup_disk_cache_if_needed()

    def __del__(self):
        """デストラクタ - タイマーを停止"""
        try:
            if hasattr(self, 'cleanup_timer'):
                if self.cleanup_timer and self.cleanup_timer.isActive():
                    self.cleanup_timer.stop()
        except (RuntimeError, AttributeError, Exception):
            # オブジェクトが既に削除されている場合は無視
            pass
