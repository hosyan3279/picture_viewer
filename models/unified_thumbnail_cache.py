"""
統合サムネイルキャッシュモジュール

各種サムネイルキャッシュ実装の最良部分を統合した高性能なキャッシュシステムを提供します。
- メモリとディスクの二層キャッシュ
- SQLiteデータベースによるメタデータ管理
- スレッドセーフな操作
- 自動メモリ使用量最適化
- 詳細な統計情報とモニタリング
"""
import os
import hashlib
import sqlite3
import time
import gc
import json
import threading
from typing import Dict, Tuple, Optional, List, Any, Union, Set

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap, QImage

from utils import logger, get_config
from .base_thumbnail_cache import BaseThumbnailCache

class UnifiedThumbnailCache(BaseThumbnailCache):
    """
    統合サムネイルキャッシュクラス
    
    すべてのキャッシュ実装の最良の部分を組み合わせた高性能なキャッシュシステム。
    SQLiteデータベースを使用したメタデータ管理、スレッドセーフな操作、
    自動メモリ最適化機能を備えています。
    """
    
    def __init__(self, memory_limit: int = None, disk_cache_dir: str = None, 
                 disk_cache_limit_mb: int = None, db_path: str = None,
                 cleanup_interval: int = None):
        """
        初期化
        
        Args:
            memory_limit: メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir: ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb: ディスクキャッシュの上限（MB）
            db_path: SQLiteデータベースのパス（省略時はdisk_cache_dir内に作成）
            cleanup_interval: 自動クリーンアップの間隔（ミリ秒）
        """
        # 基底クラスの初期化
        super().__init__(memory_limit, disk_cache_dir, disk_cache_limit_mb)
        
        # 設定から値を取得
        config = get_config()
        if cleanup_interval is None:
            cleanup_interval = config.get("cache.cleanup_interval_ms", 60000)
        
        # スレッドセーフなロック
        self.cache_lock = threading.RLock()
        
        # データベースのパスを設定
        if db_path is None:
            db_path = os.path.join(self.disk_cache_dir, "thumbnail_cache.db")
        self.db_path = db_path
        
        # データベースを初期化
        self._init_database()
        
        # 定期的なクリーンアップの設定
        self.cleanup_interval = cleanup_interval
        self.cleanup_timer = QTimer()
        self.cleanup_timer.setInterval(cleanup_interval)
        self.cleanup_timer.timeout.connect(self.cleanup_memory_if_needed)
        self.cleanup_timer.start()
        
        # キャッシュヒット/ミスの追跡用セット
        self.recently_accessed: Set[str] = set()
        self.prefetch_candidates: Set[str] = set()
        
        # 初期クリーンアップ
        self._cleanup_disk_cache()
        
        logger.info(
            f"UnifiedThumbnailCacheを初期化しました: memory_limit={self.memory_limit}, "
            f"disk_cache_limit={disk_cache_limit_mb}MB, cleanup_interval={cleanup_interval}ms"
        )
    
    def _init_database(self) -> bool:
        """
        データベースを初期化
        
        Returns:
            bool: 初期化に成功した場合はTrue
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # サムネイルメタデータテーブルを作成
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS thumbnails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                cache_path TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_accessed INTEGER NOT NULL,
                access_count INTEGER DEFAULT 0,
                cache_key TEXT UNIQUE
            )
            ''')
            
            # インデックスを作成
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_image_size 
            ON thumbnails (image_path, width, height)
            ''')
            
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_last_accessed 
            ON thumbnails (last_accessed)
            ''')
            
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cache_key 
            ON thumbnails (cache_key)
            ''')
            
            # 統計情報テーブルを作成
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache_stats (
                id INTEGER PRIMARY KEY,
                hits INTEGER DEFAULT 0,
                misses INTEGER DEFAULT 0,
                writes INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                cleanup_count INTEGER DEFAULT 0,
                last_cleanup INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            ''')
            
            # 統計情報がなければ初期データを挿入
            cursor.execute("SELECT COUNT(*) FROM cache_stats")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO cache_stats (hits, misses, writes, errors, created_at) VALUES (0, 0, 0, 0, ?)",
                    (int(time.time()),)
                )
            
            conn.commit()
            conn.close()
            
            logger.debug("データベースを初期化しました")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"データベース初期化エラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def get_thumbnail(self, image_path: str, size: Tuple[int, int]) -> Optional[QPixmap]:
        """
        サムネイルを取得（スレッドセーフに実装）
        
        まずメモリキャッシュをチェックし、次にディスクキャッシュをチェックします。
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            
        Returns:
            QPixmap or None: サムネイル画像。キャッシュにない場合はNone
        """
        if not image_path or not os.path.exists(image_path):
            logger.debug(f"無効または存在しない画像パス: {image_path}")
            return None
        
        try:
            with self.cache_lock:
                # メモリキャッシュをチェック
                cache_key = self._make_cache_key(image_path, size)
                if cache_key in self.memory_cache:
                    self._update_access_order(cache_key)
                    self._update_db_access_time(image_path, size, cache_key)
                    self.recently_accessed.add(cache_key)
                    logger.debug(f"メモリキャッシュヒット: {image_path}")
                    self.stats["hits"] += 1
                    self.cache_hit.emit(cache_key, size)
                    return self.memory_cache[cache_key]
                
                # ディスクキャッシュをチェック
                disk_thumbnail = self._load_from_disk(image_path, size, cache_key)
                if disk_thumbnail is not None:
                    self._add_to_memory_cache(cache_key, disk_thumbnail)
                    self.recently_accessed.add(cache_key)
                    logger.debug(f"ディスクキャッシュヒット: {image_path}")
                    self.stats["hits"] += 1
                    self.cache_hit.emit(cache_key, size)
                    return disk_thumbnail
                
                logger.debug(f"キャッシュミス: {image_path}")
                self.stats["misses"] += 1
                self.cache_miss.emit(image_path, size)
                
                # 近接ファイルを事前読み込み候補に追加（オプション）
                if self._should_add_prefetch_candidate(image_path):
                    self.prefetch_candidates.add(image_path)
                
                return None
                
        except Exception as e:
            logger.error(f"サムネイル取得エラー ({image_path}): {e}")
            self.stats["errors"] += 1
            return None
    
    def store_thumbnail(self, image_path: str, size: Tuple[int, int], thumbnail: QPixmap) -> bool:
        """
        サムネイルをキャッシュに保存（スレッドセーフに実装）
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            thumbnail: サムネイル画像
            
        Returns:
            bool: 保存が成功した場合はTrue
        """
        if not image_path or thumbnail.isNull():
            logger.warning(f"無効なサムネイルは保存できません: {image_path}")
            return False
        
        try:
            with self.cache_lock:
                cache_key = self._make_cache_key(image_path, size)
                
                # メモリキャッシュに追加
                self._add_to_memory_cache(cache_key, thumbnail)
                
                # ディスクキャッシュに保存
                result = self._save_to_disk(image_path, size, thumbnail, cache_key)
                
                if result:
                    self.stats["writes"] += 1
                    
                    # ディスクキャッシュの整理（必要に応じて）
                    self._cleanup_disk_cache_if_needed()
                    
                    logger.debug(f"サムネイルをキャッシュに保存: {image_path}")
                    return True
                    
                return False
                
        except Exception as e:
            logger.error(f"サムネイル保存エラー ({image_path}): {e}")
            self.stats["errors"] += 1
            return False
    
    def clear(self, clear_disk: bool = True) -> bool:
        """
        キャッシュをクリア（スレッドセーフに実装）
        
        Args:
            clear_disk: ディスクキャッシュもクリアするかどうか
            
        Returns:
            bool: クリアが成功した場合はTrue
        """
        try:
            with self.cache_lock:
                # メモリキャッシュをクリア
                self.memory_cache.clear()
                self.access_order.clear()
                self.recently_accessed.clear()
                self.prefetch_candidates.clear()
                logger.info("メモリキャッシュをクリアしました")
                
                # ディスクキャッシュをクリア
                if clear_disk:
                    try:
                        # SQLiteデータベースからすべてのキャッシュファイルパスを取得
                        conn = sqlite3.connect(self.db_path)
                        cursor = conn.cursor()
                        
                        cursor.execute("SELECT cache_path FROM thumbnails")
                        all_cache_files = cursor.fetchall()
                        
                        cleared_files = 0
                        for (cache_path,) in all_cache_files:
                            if os.path.exists(cache_path):
                                try:
                                    os.remove(cache_path)
                                    cleared_files += 1
                                except Exception as e:
                                    logger.warning(f"ファイル削除エラー ({cache_path}): {e}")
                        
                        # データベースをクリア
                        cursor.execute("DELETE FROM thumbnails")
                        
                        # 統計情報をリセット
                        cursor.execute(
                            "UPDATE cache_stats SET hits = 0, misses = 0, writes = 0, "
                            "cleanup_count = cleanup_count + 1, last_cleanup = ?",
                            (int(time.time()),)
                        )
                        
                        conn.commit()
                        conn.close()
                        
                        logger.info(f"ディスクキャッシュをクリアしました: {cleared_files}ファイル削除")
                        
                    except sqlite3.Error as e:
                        logger.error(f"データベースクリアエラー: {e}")
                        self.stats["errors"] += 1
                
                # 統計情報をリセット
                self.stats = {
                    "hits": 0,
                    "misses": 0,
                    "writes": 0,
                    "errors": 0,
                }
                
                return True
                
        except Exception as e:
            logger.error(f"キャッシュクリアエラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        キャッシュの統計情報を取得（スレッドセーフに実装）
        
        Returns:
            dict: キャッシュの統計情報を含む辞書
        """
        try:
            with self.cache_lock:
                # SQLiteから詳細な統計情報を取得
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # 基本的な統計情報
                cursor.execute("SELECT COUNT(*), SUM(file_size) FROM thumbnails")
                disk_count, disk_size = cursor.fetchone()
                disk_count = disk_count or 0
                disk_size = disk_size or 0
                
                # 永続的な統計情報
                cursor.execute("SELECT hits, misses, writes, errors, cleanup_count FROM cache_stats LIMIT 1")
                db_stats = cursor.fetchone()
                
                if db_stats:
                    db_hits, db_misses, db_writes, db_errors, cleanup_count = db_stats
                else:
                    db_hits = db_misses = db_writes = db_errors = cleanup_count = 0
                
                # 最もアクセスの多いエントリ
                cursor.execute(
                    "SELECT image_path, width, height, access_count FROM thumbnails "
                    "ORDER BY access_count DESC LIMIT 5"
                )
                popular_entries = [
                    {
                        "path": path,
                        "size": f"{width}x{height}",
                        "count": count
                    }
                    for path, width, height, count in cursor.fetchall()
                ]
                
                conn.close()
                
                # 合計アクセス数を計算
                total_hits = self.stats["hits"] + db_hits
                total_misses = self.stats["misses"] + db_misses
                total_access = total_hits + total_misses
                
                # ヒット率を計算
                if total_access > 0:
                    hit_ratio = (total_hits / total_access) * 100.0
                else:
                    hit_ratio = 0.0
                
                stats = {
                    "memory_cache_count": len(self.memory_cache),
                    "memory_cache_limit": self.memory_limit,
                    "disk_cache_count": disk_count,
                    "disk_cache_size_mb": disk_size / (1024 * 1024),
                    "disk_cache_limit_mb": self.disk_cache_limit / (1024 * 1024),
                    "hits": total_hits,
                    "misses": total_misses,
                    "hit_ratio": hit_ratio,
                    "writes": self.stats["writes"] + db_writes,
                    "errors": self.stats["errors"] + db_errors,
                    "cleanup_interval_ms": self.cleanup_interval,
                    "cleanup_count": cleanup_count,
                    "popular_entries": popular_entries,
                    "recently_accessed_count": len(self.recently_accessed),
                    "prefetch_candidates_count": len(self.prefetch_candidates),
                    "cache_type": "unified",
                    "enhanced": True,
                    "using_sqlite": True
                }
                
                logger.debug(f"キャッシュ統計: メモリ {len(self.memory_cache)}/{self.memory_limit}, "
                             f"ディスク {disk_count}アイテム ({disk_size/(1024*1024):.1f}MB)")
                
                return stats
                
        except Exception as e:
            logger.error(f"統計情報取得エラー: {e}")
            self.stats["errors"] += 1
            return {
                "memory_cache_count": len(self.memory_cache),
                "memory_cache_limit": self.memory_limit,
                "error": str(e),
                "cache_type": "unified"
            }
    
    def cleanup_memory_if_needed(self) -> bool:
        """
        メモリ使用量が閾値を超えている場合にキャッシュを整理
        
        Returns:
            bool: クリーンアップが実行された場合はTrue
        """
        try:
            with self.cache_lock:
                # 最近アクセスされたリストをクリア（定期的）
                self.recently_accessed.clear()
                
                # 事前読み込み候補の処理（オプション）
                self._process_prefetch_candidates()
                
                # 無効なエントリを削除
                invalid_count = self.purge_invalid_entries()
                if invalid_count > 0:
                    logger.info(f"{invalid_count}件の無効なキャッシュエントリを削除しました")
                
                # メモリキャッシュサイズが制限の80%を超えた場合
                memory_usage = len(self.memory_cache)
                threshold = int(self.memory_limit * 0.8)
                
                if memory_usage > threshold:
                    # キャッシュサイズを70%に削減
                    target_size = int(self.memory_limit * 0.7)
                    items_to_remove = memory_usage - target_size
                    
                    if items_to_remove > 0:
                        logger.info(f"メモリキャッシュを削減します: {memory_usage} → {target_size}")
                        
                        # 最も古いアイテムを削除
                        removed = 0
                        for _ in range(items_to_remove):
                            if not self.access_order:
                                break
                                
                            oldest_key = self.access_order.pop(0)
                            if oldest_key in self.memory_cache:
                                del self.memory_cache[oldest_key]
                                removed += 1
                        
                        # 明示的にガベージコレクションを実行
                        gc.collect()
                        
                        logger.debug(f"メモリキャッシュから{removed}アイテムを削除しました")
                        
                        # データベースに記録
                        self._update_db_stats()
                        
                        return True
                
                # ディスクキャッシュも必要に応じて整理
                return self._cleanup_disk_cache_if_needed()
                
        except Exception as e:
            logger.error(f"キャッシュクリーンアップエラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def purge_invalid_entries(self) -> int:
        """
        無効なキャッシュエントリを削除
        
        Returns:
            int: 削除されたエントリの数
        """
        try:
            with self.cache_lock:
                # SQLiteデータベースから無効なエントリを検出
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # ソースファイルが存在しないエントリを検索
                invalid_entries = []
                
                cursor.execute("SELECT id, image_path, cache_path, cache_key FROM thumbnails")
                for entry_id, image_path, cache_path, cache_key in cursor.fetchall():
                    # ソースファイルが存在しないか、キャッシュファイルが存在しない場合
                    if not os.path.exists(image_path) or not os.path.exists(cache_path):
                        invalid_entries.append((entry_id, cache_path, cache_key))
                
                # 無効なエントリを削除
                removed_count = 0
                
                for entry_id, cache_path, cache_key in invalid_entries:
                    # キャッシュファイルを削除
                    if os.path.exists(cache_path):
                        try:
                            os.remove(cache_path)
                            logger.debug(f"無効なキャッシュファイルを削除: {cache_path}")
                        except Exception as e:
                            logger.warning(f"キャッシュファイル削除エラー ({cache_path}): {e}")
                    
                    # メモリキャッシュからも削除
                    if cache_key in self.memory_cache:
                        del self.memory_cache[cache_key]
                        if cache_key in self.access_order:
                            self.access_order.remove(cache_key)
                    
                    # データベースから削除
                    cursor.execute("DELETE FROM thumbnails WHERE id = ?", (entry_id,))
                    removed_count += 1
                
                if removed_count > 0:
                    conn.commit()
                    
                conn.close()
                
                if removed_count > 0:
                    logger.info(f"{removed_count}件の無効なキャッシュエントリを削除しました")
                    
                return removed_count
                
        except Exception as e:
            logger.error(f"無効エントリ削除エラー: {e}")
            self.stats["errors"] += 1
            return 0
    
    def _load_from_disk(self, image_path: str, size: Tuple[int, int], cache_key: str) -> Optional[QPixmap]:
        """
        ディスクキャッシュから読み込み
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            cache_key: キャッシュキー
            
        Returns:
            QPixmap or None: 読み込まれたサムネイル画像、またはNone
        """
        try:
            # データベースからキャッシュパスを取得
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT cache_path FROM thumbnails WHERE image_path = ? AND width = ? AND height = ?",
                (image_path, size[0], size[1])
            )
            result = cursor.fetchone()
            
            if result:
                cache_path = result[0]
                if os.path.exists(cache_path):
                    # アクセス時間とカウントを更新
                    cursor.execute(
                        "UPDATE thumbnails SET last_accessed = ?, access_count = access_count + 1 "
                        "WHERE image_path = ? AND width = ? AND height = ?",
                        (int(time.time()), image_path, size[0], size[1])
                    )
                    conn.commit()
                    
                    # ファイルからピクスマップを読み込み
                    pixmap = QPixmap(cache_path)
                    if not pixmap.isNull():
                        conn.close()
                        return pixmap
                    else:
                        logger.warning(f"破損したキャッシュファイル: {cache_path}")
            
            conn.close()
            return None
            
        except sqlite3.Error as e:
            logger.error(f"ディスクキャッシュ読み込みエラー ({image_path}): {e}")
            self.stats["errors"] += 1
            return None
    
    def _save_to_disk(self, image_path: str, size: Tuple[int, int], thumbnail: QPixmap, cache_key: str) -> bool:
        """
        ディスクキャッシュに保存
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            thumbnail: サムネイル画像
            cache_key: キャッシュキー
            
        Returns:
            bool: 保存に成功した場合はTrue
        """
        try:
            cache_path = self._get_disk_cache_path(image_path, size)
            
            # サムネイルを保存
            if not thumbnail.save(cache_path, "PNG"):
                logger.warning(f"サムネイル保存に失敗: {cache_path}")
                return False
            
            # メタデータを更新
            file_size = os.path.getsize(cache_path) if os.path.exists(cache_path) else 0
            
            # データベースに保存
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 既存エントリを確認
            cursor.execute(
                "SELECT id FROM thumbnails WHERE image_path = ? AND width = ? AND height = ?",
                (image_path, size[0], size[1])
            )
            result = cursor.fetchone()
            
            current_time = int(time.time())
            
            if result:
                # 既存エントリを更新
                cursor.execute(
                    "UPDATE thumbnails SET cache_path = ?, file_size = ?, created_at = ?, "
                    "last_accessed = ?, cache_key = ? "
                    "WHERE image_path = ? AND width = ? AND height = ?",
                    (cache_path, file_size, current_time, current_time, cache_key,
                     image_path, size[0], size[1])
                )
            else:
                # 新規エントリを追加
                cursor.execute(
                    "INSERT INTO thumbnails "
                    "(image_path, width, height, cache_path, file_size, created_at, last_accessed, cache_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (image_path, size[0], size[1], cache_path, file_size, current_time, current_time, cache_key)
                )
            
            conn.commit()
            conn.close()
            
            logger.debug(f"ディスクキャッシュに保存しました: {cache_path} ({file_size} bytes)")
            return True
            
        except Exception as e:
            logger.error(f"ディスクキャッシュ保存エラー ({image_path}): {e}")
            self.stats["errors"] += 1
            return False
    
    def _update_db_access_time(self, image_path: str, size: Tuple[int, int], cache_key: str) -> bool:
        """
        データベースのアクセス時間を更新
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ
            cache_key: キャッシュキー
            
        Returns:
            bool: 更新に成功した場合はTrue
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # アクセス時間とカウントを更新
            cursor.execute(
                "UPDATE thumbnails SET last_accessed = ?, access_count = access_count + 1 "
                "WHERE image_path = ? AND width = ? AND height = ?",
                (int(time.time()), image_path, size[0], size[1])
            )
            
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            return affected > 0
            
        except sqlite3.Error as e:
            logger.error(f"アクセス時間更新エラー ({image_path}): {e}")
            self.stats["errors"] += 1
            return False
    
    def _update_db_stats(self) -> bool:
        """
        データベースの統計情報を更新
        
        Returns:
            bool: 更新に成功した場合はTrue
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 現在の統計情報に加算
            cursor.execute(
                "UPDATE cache_stats SET hits = hits + ?, misses = misses + ?, "
                "writes = writes + ?, errors = errors + ?",
                (self.stats["hits"], self.stats["misses"], self.stats["writes"], self.stats["errors"])
            )
            
            # 更新後にリセット
            self.stats = {
                "hits": 0,
                "misses": 0,
                "writes": 0,
                "errors": 0,
            }
            
            conn.commit()
            conn.close()
            
            return True
            
        except sqlite3.Error as e:
            logger.error(f"統計情報更新エラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def _cleanup_disk_cache_if_needed(self) -> bool:
        """
        必要に応じてディスクキャッシュを整理
        
        Returns:
            bool: クリーンアップが実行された場合はTrue
        """
        try:
            # 現在のキャッシュサイズを計算
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT SUM(file_size) FROM thumbnails")
            result = cursor.fetchone()
            conn.close()
            
            current_size = result[0] if result[0] is not None else 0
            
            # 上限を超えていたら整理
            if current_size > self.disk_cache_limit:
                logger.info(
                    f"ディスクキャッシュが上限を超えています: {current_size/(1024*1024):.2f}MB > "
                    f"{self.disk_cache_limit/(1024*1024):.2f}MB"
                )
                return self._cleanup_disk_cache()
            
            return False
            
        except sqlite3.Error as e:
            logger.error(f"ディスクキャッシュ確認エラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def _cleanup_disk_cache(self) -> bool:
        """
        ディスクキャッシュを整理
        
        Returns:
            bool: クリーンアップが成功した場合はTrue
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # キャッシュサイズを計算
            cursor.execute("SELECT SUM(file_size) FROM thumbnails")
            result = cursor.fetchone()
            current_size = result[0] if result[0] is not None else 0
            
            # 目標サイズを設定（上限の80%）
            target_size = self.disk_cache_limit * 0.8
            
            if current_size <= target_size:
                conn.close()
                return False
            
            logger.info(
                f"ディスクキャッシュを整理します: {current_size/(1024*1024):.2f}MB → "
                f"{target_size/(1024*1024):.2f}MB"
            )
            
            # アクセス日時の古い順に取得
            cursor.execute(
                "SELECT id, cache_path, file_size, cache_key FROM thumbnails "
                "ORDER BY last_accessed ASC"
            )
            
            entries = cursor.fetchall()
            
            # 削除するエントリを収集
            removed_count = 0
            removed_size = 0
            
            for entry_id, cache_path, file_size, cache_key in entries:
                if current_size <= target_size:
                    break
                
                # ファイルを削除
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                    except Exception as e:
                        logger.warning(f"キャッシュファイル削除エラー ({cache_path}): {e}")
                        continue
                
                # メモリキャッシュからも削除
                if cache_key in self.memory_cache:
                    del self.memory_cache[cache_key]
                    if cache_key in self.access_order:
                        self.access_order.remove(cache_key)
                
                # データベースから削除
                cursor.execute("DELETE FROM thumbnails WHERE id = ?", (entry_id,))
                
                # サイズを更新
                current_size -= file_size
                removed_size += file_size
                removed_count += 1
            
            # 統計情報を更新
            if removed_count > 0:
                cursor.execute(
                    "UPDATE cache_stats SET cleanup_count = cleanup_count + 1, last_cleanup = ?",
                    (int(time.time()),)
                )
            
            conn.commit()
            conn.close()
            
            if removed_count > 0:
                logger.info(
                    f"ディスクキャッシュクリーンアップ完了: {removed_count}ファイル削除, "
                    f"{removed_size/(1024*1024):.2f}MB解放"
                )
            
            return removed_count > 0
            
        except Exception as e:
            logger.error(f"ディスクキャッシュクリーンアップエラー: {e}")
            self.stats["errors"] += 1
            return False
    
    def _should_add_prefetch_candidate(self, image_path: str) -> bool:
        """
        事前読み込み候補に追加するべきかどうかを判断
        
        Args:
            image_path: 画像のパス
            
        Returns:
            bool: 事前読み込み候補に追加する場合はTrue
        """
        # 事前読み込み機能が必要ない場合はFalse
        if len(self.prefetch_candidates) >= 50:
            return False
            
        # すでに候補に含まれている場合はFalse
        if image_path in self.prefetch_candidates:
            return False
            
        # 実装例: 同じディレクトリの画像を事前読み込み候補にする
        try:
            directory = os.path.dirname(image_path)
            filename = os.path.basename(image_path)
            
            # 特定の条件に基づいて判断
            # 例: 連番ファイル（01.jpg, 02.jpg, ...）の場合は隣接ファイルを事前読み込み
            if self._is_sequential_filename(filename):
                return True
                
            return False
            
        except:
            return False
    
    def _is_sequential_filename(self, filename: str) -> bool:
        """
        ファイル名が連番かどうかを判断
        
        Args:
            filename: ファイル名
            
        Returns:
            bool: 連番ファイル名の場合はTrue
        """
        # 実装例: 数字を含むファイル名を連番と判断
        import re
        return bool(re.search(r'\d+', filename))
    
    def _process_prefetch_candidates(self) -> int:
        """
        事前読み込み候補を処理
        
        Returns:
            int: 処理された候補の数
        """
        # 実装例: 候補のうち最大5つまでを処理
        if not self.prefetch_candidates:
            return 0
            
        processed = 0
        candidates = list(self.prefetch_candidates)[:5]
        
        for image_path in candidates:
            self.prefetch_candidates.remove(image_path)
            processed += 1
            
            # ここで実際の事前読み込み処理を行う
            # 例: 別スレッドでサムネイル生成など
            
        return processed
    
    def __del__(self):
        """デストラクタ - タイマーを停止"""
        try:
            if hasattr(self, 'cleanup_timer'):
                if self.cleanup_timer and self.cleanup_timer.isActive():
                    self.cleanup_timer.stop()
                    logger.debug("クリーンアップタイマーを停止しました")
            
            # データベースに統計情報を保存
            self._update_db_stats()
            
        except Exception:
            pass
