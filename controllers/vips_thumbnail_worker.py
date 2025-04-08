"""
libvipsを使用した高速サムネイル生成ワーカーモジュール

libvipsを使用して高速かつメモリ効率の良いサムネイル生成を行うワーカークラスを提供します。
特に大きなサイズの画像を効率的に処理します。
"""
import os
import time
from typing import Tuple, Optional, Any, Dict, Union
import pyvips
from io import BytesIO

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage

from .workers import BaseWorker, CancellationError
from utils import logger, get_config

# libvipsの並列処理を最適化するための環境変数設定
# 0を設定するとシステムのCPUコア数に基づいて最適化されます
os.environ["VIPS_CONCURRENCY"] = "0"

# キャッシュサイズを設定（MBで指定、デフォルトは100MB）
# 大きな画像を処理する場合は増やすと良いかもしれません
os.environ["VIPS_CACHE_MAX"] = "1024"

# オペレーションキャッシュを有効化
os.environ["VIPS_CACHE_MAX_FILES"] = "100"

# デバッグ情報の抑制（必要に応じて "1" に変更）
os.environ["VIPS_WARNING"] = "0"

class VipsThumbnailWorker(BaseWorker):
    """
    libvipsを使用した高速サムネイル生成ワーカークラス
    
    libvipsを使用して大きなサイズの画像を効率的にサムネイル化し、
    処理速度とメモリ使用量を最適化します。
    """
    # サポートする画像形式
    SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif']
    
    # WebP圧縮品質のレベル（0-100）
    WEBP_QUALITY = 85
    
    # JPEGフォールバック時の品質レベル（0-100）
    JPEG_QUALITY = 90
    
    def __init__(self, image_path: str, size: Tuple[int, int], thumbnail_cache=None, worker_id: str = None):
        """
        初期化
        
        Args:
            image_path: 原画像のパス
            size: 生成するサムネイルのサイズ (width, height)
            thumbnail_cache: サムネイルキャッシュ（オプション）
            worker_id: ワーカーの識別子（オプション）
        """
        worker_id = worker_id or f"vips_thumb_{os.path.basename(image_path)}"
        super().__init__(worker_id)
        
        self.image_path = image_path
        self.size = size
        self.thumbnail_cache = thumbnail_cache
        
        # 設定から値を取得
        config = get_config()
        self.webp_quality = config.get("thumbnails.generation.webp_quality", self.WEBP_QUALITY)
        self.jpeg_quality = config.get("thumbnails.generation.jpeg_quality", self.JPEG_QUALITY)
        self.use_webp = config.get("thumbnails.generation.use_webp", True)
        self.fallback_to_qt = config.get("thumbnails.generation.fallback_to_qt", True)
        
        # 画像情報
        self.image_width = 0
        self.image_height = 0
        self.image_format = ""
        
        logger.debug(f"VipsThumbnailWorker初期化: {image_path}, サイズ={size}")
    
    def work(self) -> Tuple[str, QPixmap]:
        """
        サムネイルを生成
        
        libvipsを使用して高速・メモリ効率の良いサムネイル生成を行います。
        特に大きなサイズの画像に対して効率的に動作します。
        
        Returns:
            Tuple[str, QPixmap]: 画像パスとサムネイル画像のタプル
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
        
        self.update_progress(10, "画像を読み込み中...")
        
        try:
            # libvipsでサムネイル生成（高速・低メモリ）
            try:
                # 画像拡張子をチェック
                ext = os.path.splitext(self.image_path.lower())[1]
                if ext not in self.SUPPORTED_FORMATS:
                    raise ValueError(f"サポートされていない画像形式です: {ext}")
                
                # 画像が存在するか確認
                if not os.path.exists(self.image_path):
                    raise FileNotFoundError(f"画像ファイルが見つかりません: {self.image_path}")
                
                self.update_progress(15, "画像メタデータを読み込み中...")
                
                # 画像情報を取得（軽量に）
                image_info = pyvips.Image.new_from_file(self.image_path, access='sequential', fail=False)
                self.image_width = image_info.width
                self.image_height = image_info.height
                
                # キャンセルフラグをチェック
                self.check_cancelled()
                
                self.update_progress(30, f"サイズ {self.image_width}x{self.image_height} の画像を処理中...")
                
                # 画像が非常に大きい場合、リサイズ処理を最適化
                max_dimension = max(self.image_width, self.image_height)
                
                # 最終的なサムネイルサイズを計算
                target_width, target_height = self.size
                scale = min(target_width / self.image_width, target_height / self.image_height)
                new_width = int(self.image_width * scale)
                new_height = int(self.image_height * scale)
                
                self.update_progress(40, f"サムネイル生成中 ({new_width}x{new_height})...")
                
                # サムネイル生成のアプローチを選択
                if max_dimension > 5000:
                    # 非常に大きな画像の場合はthumbnail_imageを使用
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
                
                self.update_progress(60, "画像フォーマット変換中...")
                
                # 出力形式を選択（WebPが有効ならWebP、それ以外はJPEG）
                if self.use_webp:
                    # WebP形式で保存（高速処理・高圧縮率）
                    # Q85程度でも高品質
                    buffer_format = ".webp[Q=%d,strip]" % self.webp_quality
                else:
                    # JPEG形式で保存（幅広い互換性）
                    # Q90程度の高品質設定
                    buffer_format = ".jpg[Q=%d,strip]" % self.jpeg_quality
                
                # 一時ファイルを作成せずメモリ上で処理
                self.update_progress(70, "メモリに保存中...")
                image_data = thumbnail_image.write_to_buffer(buffer_format)
                
                # QImageに変換
                self.update_progress(80, "QImageに変換中...")
                q_image = QImage.fromData(image_data)
                if q_image.isNull():
                    raise ValueError("QImageへの変換に失敗しました")
                
                pixmap = QPixmap.fromImage(q_image)
                
                # キャンセルフラグをチェック
                self.check_cancelled()
                
            except Exception as vips_error:
                # libvipsの処理に失敗した場合
                logger.warning(f"libvips処理エラー ({self.image_path}): {str(vips_error)}, 標準的な方法で再試行します")
                self.update_progress(50, "代替手段で処理中...")
                
                # Qtにフォールバックするかどうかを確認
                if not self.fallback_to_qt:
                    raise vips_error
                
                # 標準的なQt方式にフォールバック
                image_info = QImage(self.image_path)
                if image_info.isNull():
                    raise ValueError(f"画像を読み込めません: {self.image_path}")
                
                # サムネイル生成
                pixmap = QPixmap.fromImage(image_info)
                pixmap = pixmap.scaled(
                    self.size[0], self.size[1],
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            
            # キャンセルフラグをチェック
            self.check_cancelled()
            
            # キャッシュに保存
            self.update_progress(90, "キャッシュに保存中...")
            if self.thumbnail_cache and not pixmap.isNull():
                self.thumbnail_cache.store_thumbnail(self.image_path, self.size, pixmap)
            
            self.update_progress(100, "サムネイル生成完了")
            
            # 処理時間を計測
            elapsed_time = time.time() - start_time
            logger.debug(
                f"サムネイル生成完了: {self.image_path}, "
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
            pixmap = QPixmap(self.size[0], self.size[1])
            pixmap.fill(Qt.lightGray)
            return (self.image_path, pixmap)
    
    def get_image_info(self) -> Dict[str, Any]:
        """
        処理した画像の情報を取得
        
        Returns:
            Dict[str, Any]: 画像情報を含む辞書
        """
        return {
            "path": self.image_path,
            "width": self.image_width,
            "height": self.image_height,
            "format": self.image_format,
            "thumbnail_size": self.size
        }
