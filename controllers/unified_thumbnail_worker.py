"""
統合サムネイル生成ワーカーモジュール

PILとlibvipsを両方サポートし、自動的に最適な方法でサムネイルを生成する
高性能ワーカークラスを提供します。
"""
import os
import time
from io import BytesIO
from typing import Tuple, Optional, Dict, Any, Union
import threading

from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QPixmap, QImage

from .workers import BaseWorker, CancellationError
from utils import logger, get_config

# PILをインポート
try:
    from PIL import Image, ImageFile, UnidentifiedImageError
    # PIL の切り捨てエラーを防止
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("PILがインストールされていません。PILベースの処理は無効化されます。")

# libvipsをインポート（オプション）
try:
    import pyvips
    HAS_VIPS = True
    # libvipsの設定
    os.environ["VIPS_CONCURRENCY"] = "0"  # システムのCPUコア数に基づいて最適化
    os.environ["VIPS_CACHE_MAX"] = "1024"  # キャッシュサイズ（MB）
    os.environ["VIPS_CACHE_MAX_FILES"] = "100"  # オペレーションキャッシュを有効化
    os.environ["VIPS_WARNING"] = "0"  # デバッグ情報の抑制
except ImportError:
    HAS_VIPS = False
    logger.warning("libvipsがインストールされていません。高速処理は無効化されます。")

class UnifiedThumbnailWorker(BaseWorker):
    """
    統合サムネイル生成ワーカークラス
    
    PILとlibvipsの両方を使用し、自動的に最適な方法でサムネイルを生成します。
    大きなサイズの画像も効率的に処理し、メモリ使用量を最小限に抑えます。
    """
    # サポートする画像形式
    SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif']
    
    # デフォルト設定
    DEFAULT_WEBP_QUALITY = 85
    DEFAULT_JPEG_QUALITY = 90
    DEFAULT_USE_VIPS = True
    DEFAULT_FALLBACK_TO_QT = True
    DEFAULT_SIZE_THRESHOLD = 5000  # このサイズ以上の画像はVIPSを使用
    
    # 生成エンジンタイプ
    ENGINE_QT = "qt"
    ENGINE_PIL = "pil"
    ENGINE_VIPS = "vips"
    
    def __init__(self, image_path: str, size: Union[Tuple[int, int], QSize], 
                 thumbnail_cache=None, use_vips: bool = None, worker_id: str = None):
        """
        初期化
        
        Args:
            image_path: 原画像のパス
            size: 生成するサムネイルのサイズ (width, height)
            thumbnail_cache: サムネイルキャッシュ（オプション）
            use_vips: libvipsを使用するかどうか (Noneの場合は設定から自動判定)
            worker_id: ワーカーの識別子（オプション）
        """
        worker_id = worker_id or f"thumb_{os.path.basename(image_path)}"
        super().__init__(worker_id)
        
        self.image_path = image_path
        
        # QSizeをタプルに変換
        if isinstance(size, QSize):
            self.size = (size.width(), size.height())
        else:
            self.size = size
            
        self.thumbnail_cache = thumbnail_cache
        
        # 設定から値を取得
        config = get_config()
        self.webp_quality = config.get("thumbnails.generation.webp_quality", self.DEFAULT_WEBP_QUALITY)
        self.jpeg_quality = config.get("thumbnails.generation.jpeg_quality", self.DEFAULT_JPEG_QUALITY)
        
        # VIPSを使用するかどうか
        if use_vips is None:
            self.use_vips = config.get("thumbnails.generation.use_vips", self.DEFAULT_USE_VIPS) and HAS_VIPS
        else:
            self.use_vips = use_vips and HAS_VIPS
            
        self.fallback_to_qt = config.get("thumbnails.generation.fallback_to_qt", self.DEFAULT_FALLBACK_TO_QT)
        self.size_threshold = config.get("thumbnails.generation.size_threshold", self.DEFAULT_SIZE_THRESHOLD)
        
        # 画像情報
        self.image_width = 0
        self.image_height = 0
        self.image_format = ""
        self.engine_used = ""
        
        # スレッドセーフなロック（特定の環境でのリソースアクセス競合を防止）
        self.image_lock = threading.RLock()
        
        logger.debug(f"UnifiedThumbnailWorker初期化: {image_path}, サイズ={self.size}")
    
    @Slot()
    def work(self) -> Tuple[str, QPixmap]:
        """
        サムネイルを生成
        
        自動的に最適な方法でサムネイルを生成します。PILとlibvipsを使い分け、
        大きなサイズの画像でもメモリ使用量を最小限に抑えます。
        
        Returns:
            (image_path, thumbnail): 画像パスとサムネイル画像のタプル
        """
        start_time = time.time()
        
        # キャンセルフラグをチェック
        self.check_cancelled()
        
        # キャッシュをチェック
        if self.thumbnail_cache:
            self.update_progress(5, "キャッシュをチェック中...")
            thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
            if thumbnail is not None:
                logger.debug(f"キャッシュヒット: {self.image_path}")
                return (self.image_path, thumbnail)
        
        # 画像が存在するか確認
        if not os.path.exists(self.image_path):
            logger.warning(f"画像ファイルが見つかりません: {self.image_path}")
            return (self.image_path, self._create_error_placeholder())
        
        # 拡張子をチェック
        ext = os.path.splitext(self.image_path.lower())[1]
        if not ext:
            logger.warning(f"拡張子がありません: {self.image_path}")
            # 拡張子がなくても処理を試みる
        
        self.update_progress(10, "画像を分析中...")
        
        try:
            # 最適な生成方法を判断
            use_engine = self._determine_best_engine()
            
            # 選択されたエンジンでサムネイルを生成
            if use_engine == self.ENGINE_VIPS and HAS_VIPS:
                self.update_progress(20, "libvipsで処理中...")
                pixmap = self._generate_with_vips()
                self.engine_used = self.ENGINE_VIPS
            elif use_engine == self.ENGINE_PIL and HAS_PIL:
                self.update_progress(20, "PILで処理中...")
                pixmap = self._generate_with_pil()
                self.engine_used = self.ENGINE_PIL
            else:
                self.update_progress(20, "Qtで処理中...")
                pixmap = self._generate_with_qt()
                self.engine_used = self.ENGINE_QT
            
            # 結果をチェック
            if pixmap is None or pixmap.isNull():
                logger.warning(f"サムネイル生成に失敗: {self.image_path}, エンジン={use_engine}")
                
                # 別のエンジンでリトライ
                if use_engine != self.ENGINE_QT and self.fallback_to_qt:
                    logger.debug(f"Qtエンジンにフォールバック: {self.image_path}")
                    pixmap = self._generate_with_qt()
                    self.engine_used = self.ENGINE_QT
            
            # それでも失敗した場合はプレースホルダーを返す
            if pixmap is None or pixmap.isNull():
                pixmap = self._create_error_placeholder()
                self.engine_used = "placeholder"
            
            # キャッシュに保存
            if self.thumbnail_cache and not pixmap.isNull():
                self.update_progress(90, "キャッシュに保存中...")
                self.thumbnail_cache.store_thumbnail(self.image_path, self.size, pixmap)
            
            # 処理時間を計測
            elapsed_time = time.time() - start_time
            logger.debug(
                f"サムネイル生成完了: {self.image_path}, "
                f"エンジン={self.engine_used}, "
                f"サイズ={pixmap.size()}, "
                f"所要時間={elapsed_time:.3f}秒"
            )
            
            return (self.image_path, pixmap)
            
        except CancellationError:
            # キャンセルの場合
            logger.info(f"サムネイル生成がキャンセルされました: {self.image_path}")
            raise
            
        except Exception as e:
            # その他のエラーの場合
            elapsed_time = time.time() - start_time
            logger.error(
                f"サムネイル生成エラー ({self.image_path}): {str(e)}, "
                f"所要時間={elapsed_time:.3f}秒"
            )
            
            # エラーが発生した場合はプレースホルダーを返す
            return (self.image_path, self._create_error_placeholder())
    
    def _determine_best_engine(self) -> str:
        """
        最適なサムネイル生成エンジンを決定
        
        Returns:
            str: 使用するエンジンのタイプ
        """
        # 画像サイズを取得
        img_size = self._get_image_size()
        max_dimension = max(img_size[0], img_size[1]) if img_size else 0
        
        # 画像サイズに基づいて判断
        if max_dimension > self.size_threshold:
            # 大きな画像
            if self.use_vips and HAS_VIPS:
                return self.ENGINE_VIPS
            elif HAS_PIL:
                return self.ENGINE_PIL
        else:
            # 小さな画像
            if HAS_PIL:
                return self.ENGINE_PIL
            elif self.use_vips and HAS_VIPS:
                return self.ENGINE_VIPS
        
        # デフォルトはQt
        return self.ENGINE_QT
    
    def _get_image_size(self) -> Optional[Tuple[int, int]]:
        """
        画像サイズを取得（可能な限り軽量に）
        
        Returns:
            (width, height): 画像のサイズ、またはNone
        """
        try:
            # まずはQImageで軽量に取得
            image_info = QImage(self.image_path)
            if not image_info.isNull():
                self.image_width = image_info.width()
                self.image_height = image_info.height()
                return (self.image_width, self.image_height)
            
            # Qtで失敗した場合はPILを試す
            if HAS_PIL:
                with Image.open(self.image_path) as img:
                    self.image_width, self.image_height = img.size
                    return (self.image_width, self.image_height)
            
            # どちらも失敗した場合はVIPSを試す
            if HAS_VIPS:
                image_info = pyvips.Image.new_from_file(self.image_path, access='sequential', fail=False)
                self.image_width = image_info.width
                self.image_height = image_info.height
                return (self.image_width, self.image_height)
            
        except Exception as e:
            logger.warning(f"画像サイズ取得エラー ({self.image_path}): {str(e)}")
        
        return None
    
    def _generate_with_pil(self) -> Optional[QPixmap]:
        """
        PILを使用してサムネイルを生成
        
        Returns:
            QPixmap: 生成されたサムネイル、または失敗時はNone
        """
        if not HAS_PIL:
            return None
        
        try:
            with self.image_lock:
                # PILで画像を開く
                with Image.open(self.image_path) as img:
                    # 画像情報を保存
                    self.image_format = img.format or ""
                    self.image_width, self.image_height = img.size
                    
                    # イメージモードを確認
                    if img.mode == 'RGBA' and img.format == 'JPEG':
                        # JPEGはアルファチャンネルをサポートしていないのでRGBに変換
                        img = img.convert('RGB')
                    
                    # キャンセルフラグをチェック
                    self.check_cancelled()
                    
                    self.update_progress(40, "サムネイル生成中...")
                    
                    # サムネイルを生成（PILのthumbnailはアスペクト比を保持し、効率的）
                    img.thumbnail(self.size, Image.Resampling.LANCZOS)
                    
                    # PythonオブジェクトからQPixmapへの変換
                    byte_arr = BytesIO()
                    img.save(byte_arr, format="PNG")
                    qimg = QImage.fromData(byte_arr.getvalue())
                    
                    if qimg.isNull():
                        logger.warning(f"PILでの変換に失敗: {self.image_path}")
                        return None
                    
                    pixmap = QPixmap.fromImage(qimg)
                    return pixmap
                    
        except UnidentifiedImageError:
            logger.warning(f"PILで画像を識別できません: {self.image_path}")
            return None
            
        except Exception as e:
            logger.warning(f"PILでのサムネイル生成エラー ({self.image_path}): {str(e)}")
            return None
    
    def _generate_with_vips(self) -> Optional[QPixmap]:
        """
        libvipsを使用してサムネイルを生成
        
        Returns:
            QPixmap: 生成されたサムネイル、または失敗時はNone
        """
        if not HAS_VIPS:
            return None
        
        try:
            # 画像が存在するか確認
            if not os.path.exists(self.image_path):
                return None
            
            self.update_progress(30, "画像メタデータを読み込み中...")
            
            # 画像情報を取得（軽量に）
            image_info = pyvips.Image.new_from_file(self.image_path, access='sequential', fail=False)
            self.image_width = image_info.width
            self.image_height = image_info.height
            
            # キャンセルフラグをチェック
            self.check_cancelled()
            
            self.update_progress(50, f"サイズ {self.image_width}x{self.image_height} の画像を処理中...")
            
            # 最終的なサムネイルサイズを計算
            target_width, target_height = self.size
            scale = min(target_width / self.image_width, target_height / self.image_height)
            new_width = int(self.image_width * scale)
            new_height = int(self.image_height * scale)
            
            # 大きな画像の場合はthumbnail_imageを使用
            if max(self.image_width, self.image_height) > self.size_threshold:
                # thumbnail_imageは内部的にキャッシュと最適なアルゴリズムを使用
                thumbnail_image = pyvips.Image.thumbnail(
                    self.image_path, 
                    new_width,
                    height=new_height,
                    size=pyvips.enums.Size.DOWN,
                    no_rotate=True,
                    access='sequential'
                )
            else:
                # 通常サイズの場合は標準的なリサイズ操作
                image = image_info
                thumbnail_image = image.resize(scale, kernel='lanczos3')
            
            # キャンセルフラグをチェック
            self.check_cancelled()
            
            self.update_progress(70, "画像フォーマット変換中...")
            
            # WebP形式で保存（高速処理・高圧縮率）
            buffer_format = ".webp[Q=%d,strip]" % self.webp_quality
            
            # 一時ファイルを作成せずメモリ上で処理
            self.update_progress(80, "メモリに保存中...")
            image_data = thumbnail_image.write_to_buffer(buffer_format)
            
            # QImageに変換
            self.update_progress(85, "QImageに変換中...")
            q_image = QImage.fromData(image_data)
            if q_image.isNull():
                logger.warning(f"VIPSでの変換に失敗: {self.image_path}")
                return None
            
            pixmap = QPixmap.fromImage(q_image)
            return pixmap
            
        except Exception as e:
            logger.warning(f"VIPSでのサムネイル生成エラー ({self.image_path}): {str(e)}")
            return None
    
    def _generate_with_qt(self) -> QPixmap:
        """
        Qtを使用してサムネイルを生成
        
        Returns:
            QPixmap: 生成されたサムネイル、または失敗時はプレースホルダー
        """
        try:
            self.update_progress(40, "画像を読み込み中...")
            
            # 最初に低解像度でメタデータだけを取得
            image_info = QImage(self.image_path)
            if image_info.isNull():
                logger.warning(f"Qtでの画像読み込みに失敗: {self.image_path}")
                return self._create_error_placeholder()
            
            self.image_width = image_info.width()
            self.image_height = image_info.height()
            
            # キャンセルフラグをチェック
            self.check_cancelled()
            
            self.update_progress(60, "サムネイル生成中...")
            
            # 非常に大きな画像の場合は、低解像度のフォーマットで読み込み直し
            if (max(self.image_width, self.image_height) > self.size_threshold):
                # 低解像度なフォーマットで読み込み直し、8ビットインデックスカラーモードに変換
                image = QImage(self.image_path)
                if not image.isNull():
                    image = image.convertToFormat(QImage.Format_Indexed8)
            else:
                image = image_info
            
            # サムネイル生成
            pixmap = QPixmap.fromImage(image)
            thumbnail = pixmap.scaled(
                self.size[0], self.size[1],
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            return thumbnail
            
        except Exception as e:
            logger.warning(f"Qtでのサムネイル生成エラー ({self.image_path}): {str(e)}")
            return self._create_error_placeholder()
    
    def _create_error_placeholder(self) -> QPixmap:
        """
        エラー時のプレースホルダーを生成
        
        Returns:
            QPixmap: エラープレースホルダー
        """
        pixmap = QPixmap(self.size[0], self.size[1])
        pixmap.fill(Qt.lightGray)
        return pixmap
    
    def get_image_info(self) -> Dict[str, Any]:
        """
        処理した画像の情報を取得
        
        Returns:
            dict: 画像情報を含む辞書
        """
        return {
            "path": self.image_path,
            "width": self.image_width,
            "height": self.image_height,
            "format": self.image_format,
            "thumbnail_size": self.size,
            "engine_used": self.engine_used
        }
