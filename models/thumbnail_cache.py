"""
サムネイルキャッシュモジュール

サムネイル画像のメモリキャッシュとディスクキャッシュを管理します。
"""
import os
import hashlib
import time
import json
import shutil
from PySide6.QtCore import QObject, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImage

class ThumbnailCache(QObject):
    """
    サムネイル画像のキャッシュを管理するクラス
    
    メモリキャッシュとディスクキャッシュの両方を使用して、
    サムネイル画像の効率的な再利用を実現します。
    """
    
    def __init__(self, memory_limit=100, disk_cache_dir=None, disk_cache_limit_mb=500):
        """
        初期化
        
        Args:
            memory_limit (int): メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir (str, optional): ディスクキャッシュのディレクトリパス
            disk_cache_limit_mb (int): ディスクキャッシュの上限（MB）
        """
        super().__init__()
        self.memory_cache = {}  # メモリキャッシュ
        self.memory_limit = memory_limit  # メモリに保持するサムネイル数
        self.access_order = []  # LRU順序を追跡
        
        # ディスクキャッシュの設定
        if disk_cache_dir is None:
            disk_cache_dir = os.path.join(os.path.expanduser("~"), ".picture_viewer_cache")
        self.disk_cache_dir = disk_cache_dir
        os.makedirs(self.disk_cache_dir, exist_ok=True)
        
        # メタデータファイルのパス
        self.metadata_file = os.path.join(self.disk_cache_dir, "metadata.json")
        
        # ディスクキャッシュのメタデータ
        self.disk_metadata = self._load_metadata()
        
        # ディスクキャッシュの上限（バイト単位）
        self.disk_cache_limit = disk_cache_limit_mb * 1024 * 1024
        
        # キャッシュの整理
        self._cleanup_disk_cache()
    
    def get_thumbnail(self, image_path, size):
        """
        サムネイルを取得
        
        まずメモリキャッシュをチェックし、次にディスクキャッシュをチェックします。
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            
        Returns:
            QPixmap or None: サムネイル画像。キャッシュにない場合はNone
        """
        # メモリキャッシュをチェック
        cache_key = self._make_cache_key(image_path, size)
        if cache_key in self.memory_cache:
            self._update_access_order(cache_key)
            return self.memory_cache[cache_key]
        
        # ディスクキャッシュをチェック
        disk_thumbnail = self._load_from_disk(image_path, size)
        if disk_thumbnail is not None:
            self._add_to_memory_cache(cache_key, disk_thumbnail)
            return disk_thumbnail
        
        return None
    
    def store_thumbnail(self, image_path, size, thumbnail):
        """
        サムネイルをキャッシュに保存
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            thumbnail (QPixmap): サムネイル画像
        """
        cache_key = self._make_cache_key(image_path, size)
        
        # メモリキャッシュに追加
        self._add_to_memory_cache(cache_key, thumbnail)
        
        # ディスクキャッシュに保存
        self._save_to_disk(image_path, size, thumbnail)
        
        # ディスクキャッシュの整理（必要に応じて）
        self._cleanup_disk_cache_if_needed()
    
    def get_stats(self):
        """
        キャッシュの統計情報を取得
        
        Returns:
            dict: キャッシュの統計情報を含む辞書
        """
        # ディスクキャッシュのサイズを計算
        disk_size = 0
        for entry in self.disk_metadata.values():
            disk_size += entry.get("size", 0)
        
        return {
            "memory_cache_count": len(self.memory_cache),
            "memory_cache_limit": self.memory_limit,
            "disk_cache_count": len(self.disk_metadata),
            "disk_cache_size_mb": disk_size / (1024 * 1024),
            "disk_cache_limit_mb": self.disk_cache_limit / (1024 * 1024)
        }
    
    def clear(self, clear_disk=True):
        """
        キャッシュをクリア
        
        Args:
            clear_disk (bool): ディスクキャッシュもクリアするかどうか
        """
        # メモリキャッシュをクリア
        self.memory_cache.clear()
        self.access_order.clear()
        
        # ディスクキャッシュをクリア（オプション）
        if clear_disk:
            # メタデータをクリア
            self.disk_metadata.clear()
            self._save_metadata()
            
            # キャッシュディレクトリをクリア
            for filename in os.listdir(self.disk_cache_dir):
                if filename != "metadata.json":  # メタデータファイルは保持
                    try:
                        os.remove(os.path.join(self.disk_cache_dir, filename))
                    except:
                        pass
    
    def _make_cache_key(self, image_path, size):
        """キャッシュキーを生成"""
        try:
            # ファイルの最終更新時間を含める
            mtime = os.path.getmtime(image_path) if os.path.exists(image_path) else 0
            return f"{image_path}_{size[0]}x{size[1]}_{int(mtime)}"
        except:
            # エラー時は元の方法でキー生成
            return f"{image_path}_{size[0]}x{size[1]}"
    
    def _update_access_order(self, cache_key):
        """アクセス順序を更新（LRU）"""
        if cache_key in self.access_order:
            self.access_order.remove(cache_key)
        self.access_order.append(cache_key)
    
    def _add_to_memory_cache(self, cache_key, thumbnail):
        """メモリキャッシュに追加"""
        # キャッシュサイズが制限を超えた場合、古いアイテムを削除
        if len(self.memory_cache) >= self.memory_limit and cache_key not in self.memory_cache:
            oldest_key = self.access_order.pop(0)
            del self.memory_cache[oldest_key]
        
        self.memory_cache[cache_key] = thumbnail
        self._update_access_order(cache_key)
    
    def _get_disk_cache_path(self, image_path, size):
        """ディスクキャッシュのパスを取得"""
        hash_value = hashlib.md5(f"{image_path}_{size[0]}x{size[1]}".encode()).hexdigest()
        return os.path.join(self.disk_cache_dir, f"{hash_value}.png")
    
    def _load_from_disk(self, image_path, size):
        """ディスクキャッシュから読み込み"""
        cache_path = self._get_disk_cache_path(image_path, size)
        if os.path.exists(cache_path):
            # アクセス時間を更新
            cache_key = self._make_cache_key(image_path, size)
            if cache_key in self.disk_metadata:
                self.disk_metadata[cache_key]["last_access"] = time.time()
                self._save_metadata()
            
            return QPixmap(cache_path)
        return None
    
    def _save_to_disk(self, image_path, size, thumbnail):
        """ディスクキャッシュに保存"""
        cache_path = self._get_disk_cache_path(image_path, size)
        
        # サムネイルを保存
        thumbnail.save(cache_path, "PNG")
        
        # メタデータを更新
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
    
    def _load_metadata(self):
        """メタデータをロード"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # 読み込みエラー時は空の辞書を返す
                return {}
        return {}
    
    def _save_metadata(self):
        """メタデータを保存"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.disk_metadata, f)
        except IOError:
            pass
    
    def _cleanup_disk_cache_if_needed(self):
        """必要に応じてディスクキャッシュを整理"""
        # 現在のキャッシュサイズを計算
        cache_size = sum(entry.get("size", 0) for entry in self.disk_metadata.values())
        
        # 上限を超えていたら整理
        if cache_size > self.disk_cache_limit:
            self._cleanup_disk_cache()
    
    def _cleanup_disk_cache(self):
        """ディスクキャッシュを整理"""
        if not self.disk_metadata:
            return
        
        # アクセス時間でソート
        sorted_entries = sorted(
            self.disk_metadata.items(), 
            key=lambda x: x[1].get("last_access", 0)
        )
        
        # キャッシュサイズを計算
        cache_size = sum(entry.get("size", 0) for _, entry in sorted_entries)
        
        # 上限の80%になるまで古いエントリを削除
        target_size = self.disk_cache_limit * 0.8
        
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
                    del self.disk_metadata[cache_key]
                except:
                    pass
        
        # メタデータを保存
        self._save_metadata()
    
    def purge_invalid_entries(self):
        """無効なキャッシュエントリを削除"""
        # ソースファイルが存在しないエントリを削除
        invalid_keys = []
        
        for cache_key, entry in self.disk_metadata.items():
            source_path = entry.get("source_path", "")
            cache_path = entry.get("path", "")
            
            # ソースファイルが存在しないか、キャッシュファイルが存在しない場合
            if not os.path.exists(source_path) or not os.path.exists(cache_path):
                invalid_keys.append(cache_key)
                
                # キャッシュファイルを削除
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                    except:
                        pass
        
        # 無効なエントリをメタデータから削除
        for key in invalid_keys:
            if key in self.disk_metadata:
                del self.disk_metadata[key]
        
        # メタデータを保存
        if invalid_keys:
            self._save_metadata()
        
        return len(invalid_keys)
