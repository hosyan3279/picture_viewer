"""
基本サムネイルキャッシュモジュール

サムネイルキャッシュの基底クラスを提供します。
"""
import os
import hashlib
import time
from abc import abstractmethod
from typing import Dict, Tuple, Optional, Any, List, Union

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from utils import logger, get_config

class BaseThumbnailCache(QObject):
    """
    サムネイルキャッシュの基底抽象クラス
    
    メモリキャッシュとディスクキャッシュの基本機能を定義します。
    サブクラスはこの基底クラスを継承して具体的な実装を提供します。
    """
    # シグナル定義（オプション）
    cache_hit = Signal(str, tuple)  # キャッシュヒット (cache_key, size)
    cache_miss = Signal(str, tuple)  # キャッシュミス (image_path, size)
    
    def __init__(self, memory_limit: int = None, disk_cache_dir: str = None, disk_cache_limit_mb: int = None):
        """
        初期化
        
        Args:
            memory_limit: メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir: ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb: ディスクキャッシュの上限（MB）
        """
        super().__init__()
        
        # 設定から値を取得
        config = get_config()
        if memory_limit is None:
            memory_limit = config.get("cache.memory_limit", 100)
        if disk_cache_limit_mb is None:
            disk_cache_limit_mb = config.get("cache.disk_cache_limit_mb", 500)
        if disk_cache_dir is None:
            disk_cache_dir = config.get("cache.disk_cache_dir", 
                                        os.path.join(os.path.expanduser("~"), ".picture_viewer_cache"))
        
        # 共通の基本プロパティ
        self.memory_limit: int = memory_limit
        self.memory_cache: Dict[str, QPixmap] = {}
        self.access_order: List[str] = []
        self.disk_cache_dir: str = disk_cache_dir
        self.disk_cache_limit: int = disk_cache_limit_mb * 1024 * 1024  # バイト単位に変換
        
        # ディスクキャッシュディレクトリの作成
        self._ensure_cache_directory()
        
        # 統計情報の初期化
        self.stats = {
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "errors": 0,
        }
        
        logger.info(
            f"{self.__class__.__name__}を初期化: memory_limit={memory_limit}, "
            f"disk_cache_limit={disk_cache_limit_mb}MB"
        )
    
    def _ensure_cache_directory(self) -> bool:
        """
        ディスクキャッシュディレクトリが存在することを確認
        
        Returns:
            bool: ディレクトリが利用可能な場合はTrue
        """
        try:
            os.makedirs(self.disk_cache_dir, exist_ok=True)
            logger.info(f"ディスクキャッシュディレクトリを確認/作成: {self.disk_cache_dir}")
            return True
        except Exception as e:
            logger.error(f"ディスクキャッシュディレクトリの作成に失敗: {e}")
            # フォールバックとしてテンポラリディレクトリを使用
            import tempfile
            self.disk_cache_dir = os.path.join(tempfile.gettempdir(), "picture_viewer_cache")
            os.makedirs(self.disk_cache_dir, exist_ok=True)
            logger.warning(f"フォールバックディレクトリを使用: {self.disk_cache_dir}")
            return False
    
    @abstractmethod
    def get_thumbnail(self, image_path: str, size: Tuple[int, int]) -> Optional[QPixmap]:
        """
        サムネイルを取得
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            
        Returns:
            QPixmap or None: サムネイル画像。キャッシュにない場合はNone
        """
        pass
    
    @abstractmethod
    def store_thumbnail(self, image_path: str, size: Tuple[int, int], thumbnail: QPixmap) -> bool:
        """
        サムネイルをキャッシュに保存
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            thumbnail: サムネイル画像
            
        Returns:
            bool: 保存が成功した場合はTrue
        """
        pass
    
    @abstractmethod
    def clear(self, clear_disk: bool = True) -> bool:
        """
        キャッシュをクリア
        
        Args:
            clear_disk: ディスクキャッシュもクリアするかどうか
            
        Returns:
            bool: クリアが成功した場合はTrue
        """
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        キャッシュの統計情報を取得
        
        Returns:
            dict: キャッシュの統計情報を含む辞書
        """
        pass
    
    def _make_cache_key(self, image_path: str, size: Tuple[int, int]) -> str:
        """
        キャッシュキーを生成
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ
            
        Returns:
            str: キャッシュキー
        """
        try:
            # ファイルの最終更新時間を含める
            if os.path.exists(image_path):
                mtime = os.path.getmtime(image_path)
                return f"{image_path}_{size[0]}x{size[1]}_{int(mtime)}"
            else:
                # ファイルが存在しない場合はパスと時刻のみで生成
                return f"{image_path}_{size[0]}x{size[1]}"
        except Exception as e:
            logger.warning(f"キャッシュキー生成エラー ({image_path}): {e}")
            # エラー時はシンプルなキーを生成
            return f"{image_path}_{size[0]}x{size[1]}"
    
    def _update_access_order(self, cache_key: str) -> None:
        """
        アクセス順序を更新（LRU）
        
        Args:
            cache_key: 更新するキャッシュキー
        """
        try:
            if cache_key in self.access_order:
                self.access_order.remove(cache_key)
            self.access_order.append(cache_key)
        except Exception as e:
            logger.warning(f"アクセス順序更新エラー: {e}")
    
    def _add_to_memory_cache(self, cache_key: str, thumbnail: QPixmap) -> None:
        """
        メモリキャッシュに追加
        
        Args:
            cache_key: キャッシュキー
            thumbnail: サムネイル画像
        """
        try:
            # キャッシュサイズが制限を超えた場合、古いアイテムを削除
            if len(self.memory_cache) >= self.memory_limit and cache_key not in self.memory_cache:
                if self.access_order:
                    oldest_key = self.access_order.pop(0)
                    if oldest_key in self.memory_cache:
                        del self.memory_cache[oldest_key]
                        logger.debug(f"古いアイテムをメモリキャッシュから削除: {oldest_key}")
            
            self.memory_cache[cache_key] = thumbnail
            self._update_access_order(cache_key)
            logger.debug(f"メモリキャッシュに追加: {cache_key}")
        
        except Exception as e:
            logger.error(f"メモリキャッシュ追加エラー: {e}")
            self.stats["errors"] += 1
    
    def _get_disk_cache_path(self, image_path: str, size: Tuple[int, int]) -> str:
        """
        ディスクキャッシュのパスを取得
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ
            
        Returns:
            str: キャッシュファイルのパス
        """
        try:
            # ハッシュ値を使用して一意のファイル名を生成
            hash_input = f"{image_path}_{size[0]}x{size[1]}"
            hash_value = hashlib.md5(hash_input.encode()).hexdigest()
            return os.path.join(self.disk_cache_dir, f"{hash_value}.png")
        except Exception as e:
            logger.error(f"ディスクキャッシュパス生成エラー: {e}")
            # フォールバックとして簡略化したパスを生成
            safe_name = os.path.basename(image_path).replace(" ", "_")
            return os.path.join(self.disk_cache_dir, f"{safe_name}_{size[0]}x{size[1]}.png")
    
    def purge_invalid_entries(self) -> int:
        """
        無効なキャッシュエントリを削除
        
        Returns:
            int: 削除されたエントリの数
        """
        # サブクラスでオーバーライドすることを想定
        return 0
    
    def _get_hit_ratio(self) -> float:
        """
        キャッシュヒット率を計算
        
        Returns:
            float: ヒット率（0～100）
        """
        total = self.stats["hits"] + self.stats["misses"]
        if total == 0:
            return 0.0
        return (self.stats["hits"] / total) * 100.0
