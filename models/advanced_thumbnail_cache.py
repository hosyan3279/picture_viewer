"""
高度なサムネイルキャッシュモジュール

メモリとディスクの二層キャッシュとデータベースベースのメタデータ管理を実装した
効率的なサムネイルキャッシュシステムを提供します。
"""
import os
import hashlib
import sqlite3
import time
import threading
from PIL import Image, ImageFile
from io import BytesIO
from PySide6.QtCore import QObject, Signal, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QImage

# PIL の切り捨てエラーを防止
ImageFile.LOAD_TRUNCATED_IMAGES = True

class AdvancedThumbnailCache(QObject):
    """
    高度なサムネイルキャッシュクラス
    
    メモリとディスクの二層キャッシュにより高速なサムネイル取得を実現し、
    SQLiteデータベースでメタデータを管理します。
    """
    # シグナル定義
    cache_hit = Signal(str, tuple)  # キャッシュヒット (cache_key, size)
    cache_miss = Signal(str, tuple)  # キャッシュミス (image_path, size)
    
    def __init__(self, memory_limit=100, disk_cache_dir=None, db_path=None):
        """
        初期化
        
        Args:
            memory_limit (int): メモリキャッシュに保持するサムネイル数の上限
            disk_cache_dir (str, optional): ディスクキャッシュのディレクトリパス
            db_path (str, optional): SQLiteデータベースのパス
        """
        super().__init__()
        self.memory_cache = {}  # メモリキャッシュ
        self.memory_limit = memory_limit  # メモリに保持するサムネイル数
        self.access_order = []  # LRU順序を追跡
        
        # スレッドセーフ操作のためのロック
        self.cache_lock = threading.RLock()
        
        # ディスクキャッシュの設定
        if disk_cache_dir is None:
            disk_cache_dir = os.path.join(os.path.expanduser("~"), ".advanced_picture_viewer_cache")
        self.disk_cache_dir = disk_cache_dir
        
        # ディスクキャッシュディレクトリを作成
        os.makedirs(self.disk_cache_dir, exist_ok=True)
        
        # データベースのパスを設定
        if db_path is None:
            db_path = os.path.join(self.disk_cache_dir, "thumbnail_cache.db")
        self.db_path = db_path
        
        # データベースを初期化
        self._init_database()
    
    def _init_database(self):
        """データベースを初期化"""
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
                created_at INTEGER NOT NULL,
                last_accessed INTEGER NOT NULL,
                access_count INTEGER DEFAULT 0
            )
            ''')
            
            # 画像パス、幅、高さの複合インデックスを作成
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_image_size 
            ON thumbnails (image_path, width, height)
            ''')
            
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"データベース初期化エラー: {e}")
    
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
        if not image_path or not os.path.exists(image_path):
            return None
            
        with self.cache_lock:
            # メモリキャッシュをチェック
            cache_key = self._make_cache_key(image_path, size)
            if cache_key in self.memory_cache:
                self._update_access_order(cache_key)
                self._update_db_access_time(image_path, size)
                self.cache_hit.emit(cache_key, size)
                return self.memory_cache[cache_key]
            
            # ディスクキャッシュをチェック
            disk_thumbnail = self._load_from_disk(image_path, size)
            if disk_thumbnail is not None:
                self._add_to_memory_cache(cache_key, disk_thumbnail)
                self.cache_hit.emit(cache_key, size)
                return disk_thumbnail
            
            # キャッシュミスを通知
            self.cache_miss.emit(image_path, size)
            return None
    
    def store_thumbnail(self, image_path, size, thumbnail):
        """
        サムネイルをキャッシュに保存
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            thumbnail (QPixmap): サムネイル画像
        """
        if not image_path or thumbnail.isNull():
            return
        
        with self.cache_lock:
            cache_key = self._make_cache_key(image_path, size)
            
            # メモリキャッシュに追加
            self._add_to_memory_cache(cache_key, thumbnail)
            
            # ディスクキャッシュに保存
            cache_path = self._save_to_disk(image_path, size, thumbnail)
            
            # データベースにメタデータを追加
            if cache_path:
                self._add_to_database(image_path, size, cache_path)
    
    def generate_thumbnail(self, image_path, size):
        """
        サムネイルを生成
        
        PILを使用して効率的にサムネイルを生成します。
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): サムネイルのサイズ (width, height)
            
        Returns:
            QPixmap or None: 生成されたサムネイル
        """
        if not os.path.exists(image_path):
            return None
        
        try:
            # PILで画像を開く
            with Image.open(image_path) as img:
                # サムネイルを生成（PILのresizeは非常に効率的）
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # PythonオブジェクトからQPixmapへの変換
                byte_arr = BytesIO()
                img.save(byte_arr, format="PNG")
                qimg = QImage.fromData(byte_arr.getvalue())
                pixmap = QPixmap.fromImage(qimg)
                
                return pixmap
        except Exception as e:
            print(f"サムネイル生成エラー: {e}")
            return None
    
    def clear(self, older_than=None):
        """
        キャッシュをクリア
        
        Args:
            older_than (int, optional): この時間（秒）より古いキャッシュのみ削除
        """
        with self.cache_lock:
            # メモリキャッシュをクリア
            self.memory_cache.clear()
            self.access_order.clear()
            
            try:
                # データベースとディスクキャッシュをクリア
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                if older_than:
                    # 特定の時間より古いキャッシュのみ削除
                    threshold_time = int(time.time()) - older_than
                    cursor.execute("SELECT cache_path FROM thumbnails WHERE created_at < ?", (threshold_time,))
                    old_cache_files = cursor.fetchall()
                    
                    # ディスクからファイルを削除
                    for (cache_path,) in old_cache_files:
                        if os.path.exists(cache_path):
                            try:
                                os.remove(cache_path)
                            except:
                                pass
                    
                    # データベースからエントリを削除
                    cursor.execute("DELETE FROM thumbnails WHERE created_at < ?", (threshold_time,))
                else:
                    # すべてのキャッシュを削除
                    cursor.execute("SELECT cache_path FROM thumbnails")
                    all_cache_files = cursor.fetchall()
                    
                    # ディスクからファイルを削除
                    for (cache_path,) in all_cache_files:
                        if os.path.exists(cache_path):
                            try:
                                os.remove(cache_path)
                            except:
                                pass
                    
                    # データベースをクリア
                    cursor.execute("DELETE FROM thumbnails")
                
                conn.commit()
                conn.close()
            
            except sqlite3.Error as e:
                print(f"キャッシュクリアエラー: {e}")
    
    def get_cache_size(self):
        """
        キャッシュサイズを取得
        
        Returns:
            tuple: (メモリキャッシュサイズ, ディスクキャッシュサイズ, エントリ数)
        """
        memory_size = len(self.memory_cache)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # エントリ数を取得
            cursor.execute("SELECT COUNT(*) FROM thumbnails")
            entry_count = cursor.fetchone()[0]
            
            # ディスクキャッシュのサイズを取得
            disk_size = 0
            for root, dirs, files in os.walk(self.disk_cache_dir):
                for f in files:
                    if f.endswith('.png'):  # サムネイルファイルのみカウント
                        disk_size += os.path.getsize(os.path.join(root, f))
            
            conn.close()
            
            return (memory_size, disk_size, entry_count)
        
        except sqlite3.Error:
            return (memory_size, 0, 0)
    
    def _make_cache_key(self, image_path, size):
        """キャッシュキーを生成"""
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
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # データベースからキャッシュパスを取得
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
                    
                    # キャッシュから読み込み
                    pixmap = QPixmap(cache_path)
                    if not pixmap.isNull():
                        conn.close()
                        return pixmap
            
            conn.close()
            return None
            
        except sqlite3.Error as e:
            print(f"ディスクキャッシュ読み込みエラー: {e}")
            return None
    
    def _save_to_disk(self, image_path, size, thumbnail):
        """ディスクキャッシュに保存"""
        cache_path = self._get_disk_cache_path(image_path, size)
        
        try:
            # QPixmapをファイルに保存
            thumbnail.save(cache_path, "PNG")
            return cache_path
        except:
            return None
    
    def _add_to_database(self, image_path, size, cache_path):
        """データベースにメタデータを追加"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 現在時刻を取得
            current_time = int(time.time())
            
            # 既存エントリを確認
            cursor.execute(
                "SELECT id FROM thumbnails WHERE image_path = ? AND width = ? AND height = ?",
                (image_path, size[0], size[1])
            )
            result = cursor.fetchone()
            
            if result:
                # 既存エントリを更新
                cursor.execute(
                    "UPDATE thumbnails SET cache_path = ?, created_at = ?, last_accessed = ? "
                    "WHERE image_path = ? AND width = ? AND height = ?",
                    (cache_path, current_time, current_time, image_path, size[0], size[1])
                )
            else:
                # 新規エントリを追加
                cursor.execute(
                    "INSERT INTO thumbnails "
                    "(image_path, width, height, cache_path, created_at, last_accessed) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (image_path, size[0], size[1], cache_path, current_time, current_time)
                )
            
            conn.commit()
            conn.close()
            
        except sqlite3.Error as e:
            print(f"データベース更新エラー: {e}")
    
    def _update_db_access_time(self, image_path, size):
        """データベースのアクセス時間を更新"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # アクセス時間とカウントを更新
            cursor.execute(
                "UPDATE thumbnails SET last_accessed = ?, access_count = access_count + 1 "
                "WHERE image_path = ? AND width = ? AND height = ?",
                (int(time.time()), image_path, size[0], size[1])
            )
            
            conn.commit()
            conn.close()
            
        except sqlite3.Error as e:
            print(f"アクセス時間更新エラー: {e}")
