"""
サムネイルキャッシュモジュール

サムネイル画像のメモリキャッシュとディスクキャッシュを管理します。
"""
import os
import hashlib
import time
import json
import shutil
from typing import Dict, Tuple, Optional, List, Any, Union
from PySide6.QtCore import QObject, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImage

from utils import logger, get_config

class ThumbnailCache(QObject):
    """
    サムネイル画像のキャッシュを管理するクラス
    
    メモリキャッシュとディスクキャッシュの両方を使用して、
    サムネイル画像の効率的な再利用を実現します。
    """
    
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
        
        self.memory_cache: Dict[str, QPixmap] = {}  # メモリキャッシュ
        self.memory_limit: int = memory_limit  # メモリに保持するサムネイル数
        self.access_order: List[str] = []  # LRU順序を追跡
        
        # ディスクキャッシュの設定
        self.disk_cache_dir: str = disk_cache_dir
        try:
            os.makedirs(self.disk_cache_dir, exist_ok=True)
            logger.info(f"ディスクキャッシュディレクトリを確認/作成しました: {self.disk_cache_dir}")
        except Exception as e:
            logger.error(f"ディスクキャッシュディレクトリの作成に失敗しました: {e}")
            # フォールバックとしてテンポラリディレクトリを使用
            import tempfile
            self.disk_cache_dir = os.path.join(tempfile.gettempdir(), "picture_viewer_cache")
            os.makedirs(self.disk_cache_dir, exist_ok=True)
            logger.warning(f"フォールバックディレクトリを使用します: {self.disk_cache_dir}")
        
        # メタデータファイルのパス
        self.metadata_file: str = os.path.join(self.disk_cache_dir, "metadata.json")
        
        # ディスクキャッシュのメタデータ
        self.disk_metadata: Dict[str, Dict[str, Any]] = self._load_metadata()
        
        # ディスクキャッシュの上限（バイト単位）
        self.disk_cache_limit: int = disk_cache_limit_mb * 1024 * 1024
        
        logger.info(
            f"ThumbnailCacheを初期化しました: memory_limit={memory_limit}, "
            f"disk_cache_limit={disk_cache_limit_mb}MB, entries={len(self.disk_metadata)}"
        )
        
        # キャッシュの整理
        self._cleanup_disk_cache()
    
    def get_thumbnail(self, image_path: str, size: Tuple[int, int]) -> Optional[QPixmap]:
        """
        サムネイルを取得
        
        まずメモリキャッシュをチェックし、次にディスクキャッシュをチェックします。
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ (width, height)
            
        Returns:
            サムネイル画像。キャッシュにない場合はNone
        """
        if not image_path or not os.path.exists(image_path):
            logger.debug(f"無効または存在しない画像パス: {image_path}")
            return None
        
        try:
            # メモリキャッシュをチェック
            cache_key = self._make_cache_key(image_path, size)
            if cache_key in self.memory_cache:
                self._update_access_order(cache_key)
                logger.debug(f"メモリキャッシュヒット: {image_path}")
                return self.memory_cache[cache_key]
            
            # ディスクキャッシュをチェック
            disk_thumbnail = self._load_from_disk(image_path, size)
            if disk_thumbnail is not None:
                self._add_to_memory_cache(cache_key, disk_thumbnail)
                logger.debug(f"ディスクキャッシュヒット: {image_path}")
                return disk_thumbnail
            
            logger.debug(f"キャッシュミス: {image_path}")
            return None
        
        except Exception as e:
            logger.error(f"サムネイル取得エラー ({image_path}): {e}")
            return None
    
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
        if not image_path or thumbnail.isNull():
            logger.warning(f"無効なサムネイルは保存できません: {image_path}")
            return False
        
        try:
            cache_key = self._make_cache_key(image_path, size)
            
            # メモリキャッシュに追加
            self._add_to_memory_cache(cache_key, thumbnail)
            
            # ディスクキャッシュに保存
            disk_path = self._save_to_disk(image_path, size, thumbnail)
            
            # ディスクキャッシュの整理（必要に応じて）
            self._cleanup_disk_cache_if_needed()
            
            return disk_path is not None
        
        except Exception as e:
            logger.error(f"サムネイル保存エラー ({image_path}): {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        キャッシュの統計情報を取得
        
        Returns:
            キャッシュの統計情報を含む辞書
        """
        try:
            # ディスクキャッシュのサイズを計算
            disk_size = 0
            for entry in self.disk_metadata.values():
                disk_size += entry.get("size", 0)
            
            stats = {
                "memory_cache_count": len(self.memory_cache),
                "memory_cache_limit": self.memory_limit,
                "disk_cache_count": len(self.disk_metadata),
                "disk_cache_size_mb": disk_size / (1024 * 1024),
                "disk_cache_limit_mb": self.disk_cache_limit / (1024 * 1024)
            }
            
            logger.debug(f"キャッシュ統計: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"統計情報取得エラー: {e}")
            return {
                "memory_cache_count": 0,
                "memory_cache_limit": self.memory_limit,
                "disk_cache_count": 0,
                "disk_cache_size_mb": 0,
                "disk_cache_limit_mb": self.disk_cache_limit / (1024 * 1024)
            }
    
    def clear(self, clear_disk: bool = True) -> bool:
        """
        キャッシュをクリア
        
        Args:
            clear_disk: ディスクキャッシュもクリアするかどうか
        
        Returns:
            bool: クリアが成功した場合はTrue
        """
        try:
            # メモリキャッシュをクリア
            self.memory_cache.clear()
            self.access_order.clear()
            logger.info("メモリキャッシュをクリアしました")
            
            # ディスクキャッシュをクリア（オプション）
            if clear_disk:
                # メタデータをクリア
                self.disk_metadata.clear()
                self._save_metadata()
                
                # キャッシュディレクトリをクリア
                cleared_files = 0
                for filename in os.listdir(self.disk_cache_dir):
                    if filename != "metadata.json":  # メタデータファイルは保持
                        try:
                            file_path = os.path.join(self.disk_cache_dir, filename)
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                cleared_files += 1
                        except Exception as e:
                            logger.warning(f"ファイル削除エラー ({filename}): {e}")
                
                logger.info(f"ディスクキャッシュをクリアしました: {cleared_files}ファイル削除")
            
            return True
            
        except Exception as e:
            logger.error(f"キャッシュクリアエラー: {e}")
            return False
    
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
    
    def _load_from_disk(self, image_path: str, size: Tuple[int, int]) -> Optional[QPixmap]:
        """
        ディスクキャッシュから読み込み
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ
            
        Returns:
            読み込まれたサムネイル画像、またはNone
        """
        try:
            cache_path = self._get_disk_cache_path(image_path, size)
            if not os.path.exists(cache_path):
                logger.debug(f"ディスクキャッシュにサムネイルが見つかりません: {cache_path}")
                return None
            
            # アクセス時間を更新
            cache_key = self._make_cache_key(image_path, size)
            if cache_key in self.disk_metadata:
                self.disk_metadata[cache_key]["last_access"] = time.time()
                self._save_metadata()
            
            # ファイルからピクスマップを読み込み
            pixmap = QPixmap(cache_path)
            if pixmap.isNull():
                logger.warning(f"破損したキャッシュファイル: {cache_path}")
                return None
            
            logger.debug(f"ディスクキャッシュからサムネイル読み込み: {cache_path}")
            return pixmap
            
        except Exception as e:
            logger.error(f"ディスクキャッシュ読み込みエラー ({image_path}): {e}")
            return None
    
    def _save_to_disk(self, image_path: str, size: Tuple[int, int], thumbnail: QPixmap) -> Optional[str]:
        """
        ディスクキャッシュに保存
        
        Args:
            image_path: 原画像のパス
            size: サムネイルのサイズ
            thumbnail: サムネイル画像
            
        Returns:
            str or None: 保存に成功した場合はキャッシュファイルのパス、失敗した場合はNone
        """
        try:
            cache_path = self._get_disk_cache_path(image_path, size)
            
            # サムネイルを保存
            if not thumbnail.save(cache_path, "PNG"):
                logger.warning(f"サムネイル保存に失敗: {cache_path}")
                return None
            
            # メタデータを更新
            if os.path.exists(cache_path):
                file_size = os.path.getsize(cache_path)
                cache_key = self._make_cache_key(image_path, size)
                
                self.disk_metadata[cache_key] = {
                    "path": cache_path,
                    "size": file_size,
                    "created": time.time(),
                    "last_access": time.time(),
                    "source_path": image_path,
                    "thumb_size": size
                }
                
                # メタデータを保存
                self._save_metadata()
                logger.debug(f"ディスクキャッシュに保存しました: {cache_path} ({file_size} bytes)")
                return cache_path
            else:
                logger.warning(f"保存されたファイルが見つかりません: {cache_path}")
                return None
                
        except Exception as e:
            logger.error(f"ディスクキャッシュ保存エラー ({image_path}): {e}")
            return None
    
    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        メタデータをロード
        
        Returns:
            Dict: メタデータ辞書
        """
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.debug(f"メタデータをロードしました: {len(data)}エントリ")
                return data
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"メタデータ読み込みエラー: {e}")
                # 読み込みエラー時は空の辞書を返す
                return {}
        
        logger.debug("メタデータファイルが存在しないため、新規作成します")
        return {}
    
    def _save_metadata(self) -> bool:
        """
        メタデータを保存
        
        Returns:
            bool: 保存に成功した場合はTrue
        """
        try:
            # ディレクトリを確認
            os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.disk_metadata, f, ensure_ascii=False)
            logger.debug(f"メタデータを保存しました: {len(self.disk_metadata)}エントリ")
            return True
            
        except (IOError, Exception) as e:
            logger.error(f"メタデータ保存エラー: {e}")
            return False
    
    def _cleanup_disk_cache_if_needed(self) -> bool:
        """
        必要に応じてディスクキャッシュを整理
        
        Returns:
            bool: クリーンアップが実行された場合はTrue
        """
        try:
            # 現在のキャッシュサイズを計算
            cache_size = sum(entry.get("size", 0) for entry in self.disk_metadata.values())
            
            # 上限を超えていたら整理
            if cache_size > self.disk_cache_limit:
                logger.info(
                    f"ディスクキャッシュが上限を超えています: {cache_size/(1024*1024):.2f}MB > "
                    f"{self.disk_cache_limit/(1024*1024):.2f}MB"
                )
                return self._cleanup_disk_cache()
            
            return False
            
        except Exception as e:
            logger.error(f"ディスクキャッシュ確認エラー: {e}")
            return False
    
    def _cleanup_disk_cache(self) -> bool:
        """
        ディスクキャッシュを整理
        
        Returns:
            bool: クリーンアップが成功した場合はTrue
        """
        if not self.disk_metadata:
            logger.debug("ディスクキャッシュが空のため、クリーンアップは不要です")
            return False
        
        try:
            # アクセス時間でソート
            sorted_entries = sorted(
                self.disk_metadata.items(), 
                key=lambda x: x[1].get("last_access", 0)
            )
            
            # キャッシュサイズを計算
            cache_size = sum(entry.get("size", 0) for _, entry in sorted_entries)
            target_size = self.disk_cache_limit * 0.8
            
            if cache_size <= target_size:
                logger.debug("ディスクキャッシュサイズが目標以下のため、クリーンアップは不要です")
                return False
            
            logger.info(
                f"ディスクキャッシュを整理します: {cache_size/(1024*1024):.2f}MB → "
                f"{target_size/(1024*1024):.2f}MB"
            )
            
            # 削除するエントリを収集
            removed_count = 0
            removed_size = 0
            
            for cache_key, entry in sorted_entries:
                if cache_size <= target_size:
                    break
                    
                # エントリを削除
                file_path = entry.get("path", "")
                file_size = entry.get("size", 0)
                
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        cache_size -= file_size
                        removed_size += file_size
                        del self.disk_metadata[cache_key]
                        removed_count += 1
                        logger.debug(f"古いキャッシュファイルを削除: {file_path}")
                    except Exception as e:
                        logger.warning(f"キャッシュファイル削除エラー ({file_path}): {e}")
                else:
                    # ファイルが存在しない場合はメタデータだけ削除
                    del self.disk_metadata[cache_key]
                    cache_size -= file_size
                    removed_count += 1
            
            # メタデータを保存
            self._save_metadata()
            
            logger.info(
                f"ディスクキャッシュクリーンアップ完了: {removed_count}ファイル削除, "
                f"{removed_size/(1024*1024):.2f}MB解放"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"ディスクキャッシュクリーンアップエラー: {e}")
            return False
    
    def purge_invalid_entries(self) -> int:
        """
        無効なキャッシュエントリを削除
        
        Returns:
            int: 削除されたエントリの数
        """
        try:
            # ソースファイルが存在しないエントリを削除
            invalid_keys = []
            
            for cache_key, entry in list(self.disk_metadata.items()):
                source_path = entry.get("source_path", "")
                cache_path = entry.get("path", "")
                
                # ソースファイルが存在しないか、キャッシュファイルが存在しない場合
                if not os.path.exists(source_path) or not os.path.exists(cache_path):
                    invalid_keys.append(cache_key)
                    
                    # キャッシュファイルを削除
                    if os.path.exists(cache_path):
                        try:
                            os.remove(cache_path)
                            logger.debug(f"無効なキャッシュファイルを削除: {cache_path}")
                        except Exception as e:
                            logger.warning(f"キャッシュファイル削除エラー ({cache_path}): {e}")
            
            # 無効なエントリをメタデータから削除
            for key in invalid_keys:
                if key in self.disk_metadata:
                    del self.disk_metadata[key]
            
            # メタデータを保存
            if invalid_keys:
                logger.info(f"{len(invalid_keys)}個の無効なエントリを削除しました")
                self._save_metadata()
            
            return len(invalid_keys)
            
        except Exception as e:
            logger.error(f"無効エントリ削除エラー: {e}")
            return 0
