"""
拡張サムネイルキャッシュモジュール

メモリ使用量を自動管理する拡張サムネイルキャッシュを提供します。
"""
import os
import time
import gc
from threading import Lock
from PySide6.QtCore import QTimer
from .thumbnail_cache import ThumbnailCache
from utils import logger, get_config

class EnhancedThumbnailCache(ThumbnailCache):
    """
    拡張サムネイルキャッシュクラス
    
    メモリ使用量を監視し、定期的なクリーンアップを行うことで
    メモリ使用量を自動的に管理する機能を追加したキャッシュクラスです。
    """
    
    def __init__(self, memory_limit=None, disk_cache_dir=None, disk_cache_limit_mb=None, cleanup_interval=None):
        """
        初期化
        
        Args:
            memory_limit (int, optional): メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir (str, optional): ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb (int, optional): ディスクキャッシュの上限（MB）
            cleanup_interval (int, optional): クリーンアップ間隔（ミリ秒）
        """
        # 設定から値を取得
        config = get_config()
        if memory_limit is None:
            memory_limit = config.get("cache.memory_limit", 200)
        if disk_cache_limit_mb is None:
            disk_cache_limit_mb = config.get("cache.disk_cache_limit_mb", 1000)
        if disk_cache_dir is None:
            disk_cache_dir = config.get("cache.disk_cache_dir")
        if cleanup_interval is None:
            cleanup_interval = config.get("cache.cleanup_interval_ms", 60000)
        
        logger.debug(
            "EnhancedThumbnailCache初期化: memory_limit=%s, disk_cache_limit_mb=%s, cleanup_interval=%s",
            memory_limit, disk_cache_limit_mb, cleanup_interval
        )
        
        super().__init__(memory_limit, disk_cache_dir, disk_cache_limit_mb)
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
                logger.debug(f"キャッシュヒット: {image_path}, size={size}")
            else:
                self.cache_misses += 1
                logger.debug(f"キャッシュミス: {image_path}, size={size}")
            
            return result
    
    def cleanup_memory_if_needed(self):
        """メモリ使用量が閾値を超えている場合にキャッシュを整理"""
        with self.cache_lock:
            try:
                # 無効なエントリを先に削除
                invalid_count = self.purge_invalid_entries()
                if invalid_count > 0:
                    logger.info(f"{invalid_count}個の無効なキャッシュエントリを削除しました")
                
                # メモリキャッシュサイズが制限の80%を超えた場合
                cache_count = len(self.memory_cache)
                threshold = self.memory_limit * 0.8
                
                if cache_count > threshold:
                    logger.debug(f"メモリキャッシュのサイズが閾値を超えています ({cache_count} > {threshold})")
                    
                    # キャッシュサイズを70%に削減
                    target_size = int(self.memory_limit * 0.7)
                    items_to_remove = cache_count - target_size
                    
                    if items_to_remove > 0:
                        logger.info(f"キャッシュからアイテムを削除します: {items_to_remove}個")
                        
                        # 最も古いアイテムを削除
                        removed_count = 0
                        for _ in range(items_to_remove):
                            if self.access_order:
                                oldest_key = self.access_order.pop(0)
                                if oldest_key in self.memory_cache:
                                    del self.memory_cache[oldest_key]
                                    removed_count += 1
                        
                        logger.debug(f"実際に削除されたアイテム: {removed_count}個")
                    
                    # 明示的にガベージコレクションを実行
                    gc.collect()
                    
                    # ディスクキャッシュも必要に応じて整理
                    self._cleanup_disk_cache_if_needed()
            except Exception as e:
                logger.error(f"キャッシュクリーンアップ中にエラーが発生しました: {e}")
    
    def clear(self, clear_disk=True):
        """
        キャッシュをクリア（オーバーライド）
        
        Args:
            clear_disk (bool): ディスクキャッシュもクリアするかどうか
        """
        with self.cache_lock:
            try:
                before_memory = len(self.memory_cache)
                disk_stats = self.get_stats()
                before_disk = disk_stats.get("disk_cache_count", 0)
                
                super().clear(clear_disk)
                
                # 統計情報をリセット
                self.cache_hits = 0
                self.cache_misses = 0
                
                logger.info(
                    f"キャッシュクリア完了: メモリキャッシュ {before_memory} → 0, "
                    f"ディスクキャッシュ {before_disk} → 0")
            except Exception as e:
                logger.error(f"キャッシュクリア中にエラーが発生しました: {e}")
    
    def get_stats(self):
        """
        キャッシュの統計情報を取得（拡張）
        
        Returns:
            dict: キャッシュの統計情報を含む辞書
        """
        with self.cache_lock:
            try:
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
                
                logger.debug(f"キャッシュ統計: ヒット率 {hit_ratio:.1f}%, メモリ使用率 {len(self.memory_cache)}/{self.memory_limit}")
                
                return stats
            except Exception as e:
                logger.error(f"キャッシュ統計取得中にエラーが発生しました: {e}")
                return {"error": str(e)}
    
    def store_thumbnail(self, image_path, size, thumbnail):
        """
        サムネイルをキャッシュに保存
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            thumbnail (QPixmap): 保存するサムネイル画像
        """
        if not image_path or thumbnail is None or thumbnail.isNull():
            logger.warning(f"無効なサムネイルは保存できません: {image_path}")
            return
        
        with self.cache_lock:
            try:
                super().store_thumbnail(image_path, size, thumbnail)
                logger.debug(f"サムネイルをキャッシュに保存: {image_path}, size={size}")
            except Exception as e:
                logger.error(f"サムネイル保存中にエラーが発生しました: {image_path}, {e}")

    def __del__(self):
        """デストラクタ - タイマーを停止"""
        try:
            if hasattr(self, 'cleanup_timer'):
                if self.cleanup_timer and self.cleanup_timer.isActive():
                    self.cleanup_timer.stop()
                    logger.debug("クリーンアップタイマーを停止しました")
        except (RuntimeError, AttributeError, Exception) as e:
            # オブジェクトが既に削除されている場合は無視
            pass
