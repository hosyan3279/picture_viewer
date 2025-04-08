"""
設定管理モジュール

アプリケーション全体の設定を一元管理するためのクラスとユーティリティを提供します。
"""
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Tuple

from .logger import logger

class Config:
    """アプリケーション設定を管理するクラス"""
    
    # デフォルト設定値
    DEFAULT_CONFIG = {
        # アプリケーション全般
        "app": {
            "name": "画像ビューワー",
            "version": "0.1.0",
            "data_dir": "",  # 初期化時に設定される
            "window_size": (800, 600),
            "debug_mode": False,
            # 対応している画像ファイル拡張子
            "image_extensions": [
                ".jpg", ".jpeg", ".png", ".gif", ".bmp", 
                ".webp", ".tiff", ".tif", ".svg", ".heic", ".heif"
            ],
            # 画像フォーマット設定
            "image_format": {
                "save_format": "png",  # デフォルトの保存フォーマット
                "save_quality": 95,    # デフォルトの保存品質（0-100）
                "preview_quality": 90,  # プレビュー画質（0-100）
            },
        },
        
        # サムネイル関連
        "thumbnails": {
            "sizes": {
                "small": (100, 100),
                "medium": (150, 150),
                "large": (200, 200),
            },
            "min_size": 80,
            "max_size": 300,
            "default_size": "medium",
            "quality": 90,
            # サムネイル生成方法
            "generation": {
                "use_libvips": True,      # libvipsを使用する（可能な場合）
                "fallback_to_qt": True,   # libvipsが失敗した場合にQtにフォールバック
                "downscale_large": True,  # 大きな画像はまず縮小してからサムネイル生成
                "max_size_for_direct": 4096,  # 直接ロードする最大サイズ（ピクセル）
                "webp_quality": 85,       # WebP出力時の品質（0-100）
                "jpeg_quality": 90,       # JPEG出力時の品質（0-100）
                "use_webp": True,         # WebP形式を使用するか
                "concurrent_thumbnails": 8,  # 同時に処理するサムネイル数
                "thread_pool_size": 0,    # libvipsのスレッドプールサイズ（0=自動）
                "vips_cache_max_mb": 1024,  # libvipsのキャッシュサイズ（MB）
                "use_lanczos": True,      # Lanczos3リサンプリングを使用するか
                "strip_metadata": True,   # メタデータを除去するか（サイズ削減）
                "thumbnail_algorithm": "thumbnail",  # 'thumbnail'または'resize'
            },
        },
        
        # キャッシュ関連
        "cache": {
            "memory_limit": 500,  # メモリ内に保持するサムネイル数
            "disk_cache_limit_mb": 2000,  # ディスクキャッシュの最大サイズ（MB）
            "cleanup_interval_ms": 120000,  # クリーンアップ間隔（ms）
            "disk_cache_dir": "",  # 初期化時に設定される
            # キャッシュポリシー
            "policy": {
                "auto_cleanup": True,    # 自動クリーンアップを有効化
                "max_age_days": 30,      # キャッシュエントリの最大有効期間（日）
                "keep_frequent": True,   # 頻繁に使用されるエントリを保持
            },
        },
        
        # 表示関連
        "display": {
            "grid_columns": {
                "small": 6,
                "medium": 4,
                "large": 3,
            },
            "page_sizes": {
                "small": 48,
                "medium": 32,
                "large": 24,
            },
            "default_view": "grid",  # "grid" または "flow"
            # UI設定
            "ui": {
                "theme": "light",           # "light", "dark", または "system"
                "thumbnail_border": True,   # サムネイル枠線の表示
                "thumbnail_labels": True,   # サムネイル下のファイル名ラベル表示
                "show_file_info": True,     # ファイル情報の表示
                "smooth_scrolling": True,   # スムーススクロールの有効化
                "hover_preview": True,      # ホバー時のプレビュー表示
            },
        },
        
        # ワーカー関連
        "workers": {
            "max_concurrent": 8,  # 同時実行ワーカーの最大数
            "batch_size": 20,     # バッチ処理サイズ
            "load_batch_size": 8, # 1回の読込バッチサイズ
            "progress_update_interval_ms": 500,  # 進捗更新間隔（ミリ秒）
            "worker_timeout_ms": 30000,  # ワーカータイムアウト（ミリ秒）
        },
        
        # メモリ管理
        "memory": {
            "threshold_percent": 80,  # 最適化を開始するメモリ使用率閾値
            "auto_optimize": True,    # 自動メモリ最適化
            "check_interval_ms": 60000,  # メモリチェック間隔（ミリ秒）
        },
        
        # パフォーマンス設定
        "performance": {
            "lazy_loading": True,      # 遅延読み込みを有効化
            "preload_next_page": True, # 次のページを事前読み込み
            "background_scanning": True,  # バックグラウンドでのフォルダスキャン
            "hardware_acceleration": True,  # ハードウェアアクセラレーションを使用
            "vips": {
                "enable": True,           # libvipsを有効化
                "concurrency": 0,         # 0=自動、N=スレッド数
                "cache_max_mb": 1024,     # キャッシュサイズ（MB）
                "cache_max_files": 100,   # キャッシュするファイル数
                "operation_cache": True,   # 操作キャッシュを有効化
            },
        },
    }
    
    def __init__(self, config_file: Optional[str] = None):
        """
        設定を初期化
        
        Args:
            config_file: 設定ファイルのパス（省略時はデフォルト位置）
        """
        # デフォルト設定をコピー
        self._config = self.DEFAULT_CONFIG.copy()
        
        # アプリケーションデータディレクトリを設定
        self._app_data_dir = os.path.join(os.path.expanduser("~"), ".picture_viewer")
        os.makedirs(self._app_data_dir, exist_ok=True)
        
        # デフォルト設定ファイルのパス
        self._config_file = config_file or os.path.join(self._app_data_dir, "config.json")
        
        # 動的パスを設定
        self._config["app"]["data_dir"] = self._app_data_dir
        self._config["cache"]["disk_cache_dir"] = os.path.join(self._app_data_dir, "cache")
        
        # 設定ファイルから読み込み
        self.load()
        
        logger.debug(f"設定を初期化: {self._config_file}")
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        設定値を取得
        
        Args:
            key_path: ドット区切りのキーパス (例: "cache.memory_limit")
            default: キーが存在しない場合のデフォルト値
        
        Returns:
            設定値、またはデフォルト値
        """
        parts = key_path.split('.')
        current = self._config
        
        try:
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return default
            return current
        except Exception as e:
            logger.error(f"設定値の取得エラー: {key_path} - {e}")
            return default
    
    def set(self, key_path: str, value: Any) -> bool:
        """
        設定値を変更
        
        Args:
            key_path: ドット区切りのキーパス (例: "cache.memory_limit")
            value: 新しい設定値
        
        Returns:
            bool: 成功した場合はTrue
        """
        parts = key_path.split('.')
        current = self._config
        
        try:
            # 最後のキー以外をたどる
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # 最後のキーに値を設定
            current[parts[-1]] = value
            logger.debug(f"設定を更新: {key_path} = {value}")
            return True
        except Exception as e:
            logger.error(f"設定値の更新エラー: {key_path} = {value} - {e}")
            return False
    
    def load(self) -> bool:
        """
        設定ファイルから設定を読み込む
        
        Returns:
            bool: 成功した場合はTrue
        """
        if not os.path.exists(self._config_file):
            logger.info(f"設定ファイルが存在しないためデフォルト設定を使用: {self._config_file}")
            self.save()  # デフォルト設定を保存
            return False
        
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
            
            # 読み込んだ設定を現在の設定にマージ
            self._merge_config(self._config, loaded_config)
            logger.info(f"設定を読み込みました: {self._config_file}")
            return True
        except Exception as e:
            logger.error(f"設定ファイルの読み込みエラー: {self._config_file} - {e}")
            return False
    
    def save(self) -> bool:
        """
        現在の設定をファイルに保存
        
        Returns:
            bool: 成功した場合はTrue
        """
        try:
            # 設定ファイルのディレクトリが存在するか確認
            os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
            
            # タプルをリストに変換（JSONシリアライズのため）
            config_copy = self._convert_tuples_to_lists(self._config)
            
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(config_copy, f, ensure_ascii=False, indent=2)
            
            logger.info(f"設定を保存しました: {self._config_file}")
            return True
        except Exception as e:
            logger.error(f"設定ファイルの保存エラー: {self._config_file} - {e}")
            return False
    
    def _convert_tuples_to_lists(self, obj: Any) -> Any:
        """
        オブジェクト内のタプルをリストに変換（JSONシリアライズのため）
        
        Args:
            obj: 変換するオブジェクト
            
        Returns:
            変換後のオブジェクト
        """
        if isinstance(obj, tuple):
            return list(obj)
        elif isinstance(obj, list):
            return [self._convert_tuples_to_lists(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._convert_tuples_to_lists(value) for key, value in obj.items()}
        else:
            return obj
    
    def reset(self) -> None:
        """設定をデフォルト値にリセット"""
        self._config = self.DEFAULT_CONFIG.copy()
        # 動的パスを再設定
        self._config["app"]["data_dir"] = self._app_data_dir
        self._config["cache"]["disk_cache_dir"] = os.path.join(self._app_data_dir, "cache")
        
        logger.info("設定をデフォルト値にリセットしました")
        self.save()
    
    def _merge_config(self, target: Dict, source: Dict) -> None:
        """
        設定を再帰的にマージ
        
        Args:
            target: マージ先の辞書
            source: マージ元の辞書
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                # 両方が辞書の場合は再帰的にマージ
                self._merge_config(target[key], value)
            else:
                # それ以外の場合は値を上書き
                target[key] = value
    
    def get_thumbnail_size(self, size_name: str = None) -> Tuple[int, int]:
        """
        サムネイルサイズを取得
        
        Args:
            size_name: サイズ名 ("small", "medium", "large") または None（デフォルト値を使用）
        
        Returns:
            Tuple[int, int]: サムネイルサイズ (width, height)
        """
        if size_name is None:
            size_name = self.get("thumbnails.default_size")
        
        sizes = self.get("thumbnails.sizes")
        if size_name in sizes:
            return tuple(sizes[size_name])
        
        # デフォルトサイズを返す
        return tuple(sizes[self.get("thumbnails.default_size")])
    
    def get_grid_columns(self, size_name: str = None) -> int:
        """
        グリッド列数を取得
        
        Args:
            size_name: サイズ名 ("small", "medium", "large") または None（デフォルト値を使用）
        
        Returns:
            int: グリッド列数
        """
        if size_name is None:
            size_name = self.get("thumbnails.default_size")
        
        columns = self.get("display.grid_columns")
        if size_name in columns:
            return columns[size_name]
        
        # デフォルト列数を返す
        return columns[self.get("thumbnails.default_size")]
    
    def get_page_size(self, size_name: str = None) -> int:
        """
        ページサイズを取得
        
        Args:
            size_name: サイズ名 ("small", "medium", "large") または None（デフォルト値を使用）
        
        Returns:
            int: ページサイズ
        """
        if size_name is None:
            size_name = self.get("thumbnails.default_size")
        
        page_sizes = self.get("display.page_sizes")
        if size_name in page_sizes:
            return page_sizes[size_name]
        
        # デフォルトページサイズを返す
        return page_sizes[self.get("thumbnails.default_size")]
    
    def get_supported_extensions(self) -> List[str]:
        """
        サポートされている画像ファイル拡張子のリストを取得
        
        Returns:
            List[str]: 画像ファイル拡張子のリスト
        """
        extensions = self.get("app.image_extensions", [])
        return [ext.lower() for ext in extensions]  # 小文字に正規化
    
    def is_supported_extension(self, file_path: str) -> bool:
        """
        ファイルがサポートされている画像形式かどうかを判定
        
        Args:
            file_path: チェックするファイルパス
            
        Returns:
            bool: サポートされている場合はTrue
        """
        if not file_path:
            return False
            
        ext = os.path.splitext(file_path.lower())[1]
        return ext in self.get_supported_extensions()
    
    def add_supported_extension(self, extension: str) -> bool:
        """
        サポートする画像ファイル拡張子を追加
        
        Args:
            extension: 追加する拡張子（.jpgのように先頭のドットを含む）
            
        Returns:
            bool: 追加に成功した場合はTrue
        """
        if not extension.startswith('.'):
            extension = '.' + extension
            
        extension = extension.lower()  # 小文字に正規化
        
        extensions = self.get("app.image_extensions", [])
        if extension not in extensions:
            extensions.append(extension)
            self.set("app.image_extensions", extensions)
            logger.info(f"サポートする拡張子を追加: {extension}")
            return True
            
        return False
    
    def remove_supported_extension(self, extension: str) -> bool:
        """
        サポートする画像ファイル拡張子を削除
        
        Args:
            extension: 削除する拡張子（.jpgのように先頭のドットを含む）
            
        Returns:
            bool: 削除に成功した場合はTrue
        """
        if not extension.startswith('.'):
            extension = '.' + extension
            
        extension = extension.lower()  # 小文字に正規化
        
        extensions = self.get("app.image_extensions", [])
        if extension in extensions:
            extensions.remove(extension)
            self.set("app.image_extensions", extensions)
            logger.info(f"サポートする拡張子を削除: {extension}")
            return True
            
        return False
    
    def configure_vips(self) -> None:
        """
        libvipsの設定を適用
        
        環境変数を通じてlibvipsの動作を設定します。
        """
        # 設定を取得
        vips_config = self.get("performance.vips", {})
        enable = vips_config.get("enable", True)
        
        if not enable:
            return
            
        # スレッドプールサイズを設定
        concurrency = vips_config.get("concurrency", 0)
        os.environ["VIPS_CONCURRENCY"] = str(concurrency)
        
        # キャッシュサイズを設定
        cache_max_mb = vips_config.get("cache_max_mb", 1024)
        os.environ["VIPS_CACHE_MAX"] = str(cache_max_mb)
        
        # キャッシュするファイル数を設定
        cache_max_files = vips_config.get("cache_max_files", 100)
        os.environ["VIPS_CACHE_MAX_FILES"] = str(cache_max_files)
        
        # オペレーションキャッシュを設定
        operation_cache = vips_config.get("operation_cache", True)
        os.environ["VIPS_CACHE_TRACE"] = "1" if operation_cache else "0"
        
        logger.debug(
            f"libvips設定: concurrency={concurrency}, "
            f"cache_max_mb={cache_max_mb}, cache_max_files={cache_max_files}"
        )

# 設定インスタンスのシングルトン
_instance = None

def get_config() -> Config:
    """
    設定インスタンスを取得
    
    Returns:
        Config: 設定インスタンス
    """
    global _instance
    if _instance is None:
        _instance = Config()
    return _instance

def reset_config() -> None:
    """設定をデフォルト値にリセット"""
    get_config().reset()

def configure_vips() -> None:
    """libvipsの設定を適用"""
    get_config().configure_vips()

# エクスポートする関数とクラス
__all__ = ['Config', 'get_config', 'reset_config', 'configure_vips']
