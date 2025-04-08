# --- START REFACTORED controllers/unified_thumbnail_worker.py ---
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
    # libvipsの設定 (moved config to config.py -> configure_vips())
except ImportError:
    HAS_VIPS = False
    logger.warning("libvipsがインストールされていません。高速処理は無効化されます。")

class UnifiedThumbnailWorker(BaseWorker):
    """
    統合サムネイル生成ワーカークラス

    PILとlibvipsの両方を使用し、自動的に最適な方法でサムネイルを生成します。
    大きなサイズの画像も効率的に処理し、メモリ使用量を最小限に抑えます。
    """
    # サポートする画像形式 (Consider moving to config)
    # SUPPORTED_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif']

    # デフォルト設定 (Read from config)
    DEFAULT_WEBP_QUALITY = 85
    DEFAULT_JPEG_QUALITY = 90
    DEFAULT_USE_VIPS = True
    DEFAULT_FALLBACK_TO_QT = True
    DEFAULT_SIZE_THRESHOLD = 4096 # Default threshold from config.py

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
        # Generate worker_id based on path and size for better identification
        size_tuple = size if isinstance(size, tuple) else (size.width(), size.height())
        # Ensure worker_id doesn't contain invalid characters for filenames if used as such
        safe_basename = os.path.basename(image_path).replace(" ", "_").replace(":", "_")
        worker_id = worker_id or f"thumb_{safe_basename}_{size_tuple[0]}x{size_tuple[1]}"
        super().__init__(worker_id)

        self.image_path = image_path

        # QSizeをタプルに変換
        if isinstance(size, QSize):
            self.size = (size.width(), size.height())
        else:
            self.size = size # Already a tuple

        self.thumbnail_cache = thumbnail_cache

        # 設定から値を取得
        config = get_config()
        gen_config = config.get("thumbnails.generation", {})
        self.webp_quality = gen_config.get("webp_quality", self.DEFAULT_WEBP_QUALITY)
        self.jpeg_quality = gen_config.get("jpeg_quality", self.DEFAULT_JPEG_QUALITY)

        # VIPSを使用するかどうか
        if use_vips is None:
            self.use_vips = gen_config.get("use_vips", self.DEFAULT_USE_VIPS) and HAS_VIPS
        else:
            # Allow override, but still check if HAS_VIPS
            self.use_vips = use_vips and HAS_VIPS

        self.fallback_to_qt = gen_config.get("fallback_to_qt", self.DEFAULT_FALLBACK_TO_QT)
        # Use max_size_for_direct as size threshold for VIPS vs PIL/Qt
        self.size_threshold = gen_config.get("max_size_for_direct", self.DEFAULT_SIZE_THRESHOLD)
        self.use_lanczos = gen_config.get("use_lanczos", True)
        self.strip_metadata = gen_config.get("strip_metadata", True)
        self.thumbnail_algorithm = gen_config.get("thumbnail_algorithm", "thumbnail") # 'thumbnail' or 'resize'

        # 画像情報
        self.image_width = 0
        self.image_height = 0
        self.image_format = ""
        self.engine_used = ""

        # スレッドセーフなロック（PIL/VIPSライブラリ自体がスレッドセーフか要確認だが念のため）
        # Using RLock for potential reentrant calls within generation methods if needed
        self.image_lock = threading.RLock()

        logger.debug(f"Worker {self.worker_id} initialized for {os.path.basename(image_path)}, Size={self.size}, UseVIPS={self.use_vips}")

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

        # キャッシュをチェック (Early exit if cache hit)
        if self.thumbnail_cache:
            self.update_progress(5, "キャッシュをチェック中...")
            try:
                 thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
                 if thumbnail is not None and not thumbnail.isNull():
                     logger.debug(f"Cache hit: {self.worker_id}")
                     self.update_progress(100, "キャッシュヒット")
                     return (self.image_path, thumbnail)
            except Exception as cache_e:
                 logger.warning(f"Cache check error for {self.worker_id}: {cache_e}")
                 # Proceed with generation if cache check fails

        # 画像が存在するか確認
        if not os.path.exists(self.image_path):
            logger.warning(f"Image file not found: {self.image_path} ({self.worker_id})")
            # Return path and an empty/error pixmap
            return (self.image_path, self._create_error_placeholder("File Not Found"))

        # 拡張子をチェック (Informational)
        ext = os.path.splitext(self.image_path.lower())[1]
        if not ext:
            logger.debug(f"Image has no extension: {self.image_path} ({self.worker_id})")
            # Continue trying to load it

        self.update_progress(10, "画像を分析中...")
        pixmap = None # Initialize pixmap result
        final_engine = "None"

        try:
            # 最適な生成方法を判断
            use_engine = self._determine_best_engine()
            final_engine = use_engine # Store the initially chosen engine

            # 選択されたエンジンでサムネイルを生成
            logger.debug(f"Attempting generation with engine: {use_engine} for {self.worker_id}")
            if use_engine == self.ENGINE_VIPS:
                self.update_progress(20, "libvipsで処理中...")
                pixmap = self._generate_with_vips()
            elif use_engine == self.ENGINE_PIL:
                self.update_progress(20, "PILで処理中...")
                pixmap = self._generate_with_pil()
            else: # Fallback to Qt
                self.update_progress(20, "Qtで処理中...")
                pixmap = self._generate_with_qt()

            # Check if generation failed with the chosen engine
            if pixmap is None or pixmap.isNull():
                logger.warning(f"Thumbnail generation failed with engine {use_engine} for {self.worker_id}")

                # Try fallback engines if configured and initial engine wasn't Qt
                if use_engine != self.ENGINE_QT and self.fallback_to_qt:
                    logger.info(f"Falling back to Qt engine for {self.worker_id}")
                    final_engine = self.ENGINE_QT
                    pixmap = self._generate_with_qt()
                elif use_engine != self.ENGINE_PIL and HAS_PIL: # Try PIL if VIPS/Qt failed
                     logger.info(f"Falling back to PIL engine for {self.worker_id}")
                     final_engine = self.ENGINE_PIL
                     pixmap = self._generate_with_pil()

            # If still failed after fallbacks, use placeholder
            if pixmap is None or pixmap.isNull():
                 logger.error(f"All generation attempts failed for {self.worker_id}")
                 pixmap = self._create_error_placeholder("Generation Failed")
                 final_engine = "placeholder"

            self.engine_used = final_engine # Record the engine that produced the final result

            # Store in cache if successful and cache is available
            if self.thumbnail_cache and final_engine != "placeholder":
                self.update_progress(90, "キャッシュに保存中...")
                try:
                     # Ensure the stored thumbnail is not the error placeholder
                     if not pixmap.property("isErrorPlaceholder"): # Check for custom property if set
                          self.thumbnail_cache.store_thumbnail(self.image_path, self.size, pixmap)
                     else:
                          logger.debug(f"Skipping cache store for error placeholder: {self.worker_id}")
                except Exception as cache_e:
                     logger.warning(f"Cache store error for {self.worker_id}: {cache_e}")
                     # Continue even if cache store fails

            elapsed_time = time.time() - start_time
            logger.info(
                f"Worker {self.worker_id} completed. Engine: {self.engine_used}, "
                f"Result Size: {pixmap.size() if pixmap else 'None'}, Time: {elapsed_time:.3f}s"
            )
            self.update_progress(100, f"完了 ({self.engine_used})")
            return (self.image_path, pixmap)

        except CancellationError:
            # Propagate cancellation
            logger.info(f"Worker {self.worker_id} cancelled during generation.")
            raise

        except Exception as e:
            # Catch any other unexpected errors during generation logic
            elapsed_time = time.time() - start_time
            logger.exception(f"Unexpected error in worker {self.worker_id}: {e}", exc_info=True)
            # Return path and an error placeholder
            return (self.image_path, self._create_error_placeholder(f"Error: {type(e).__name__}"))

    def _determine_best_engine(self) -> str:
        """
        最適なサムネイル生成エンジンを決定

        Returns:
            str: 使用するエンジンのタイプ ('vips', 'pil', 'qt')
        """
        # Get image size (might be cached from previous call if any)
        if self.image_width == 0 or self.image_height == 0:
             img_size = self._get_image_size()
             if img_size:
                  self.image_width, self.image_height = img_size
             else:
                  logger.warning(f"Could not determine image size for {self.worker_id}, defaulting to Qt.")
                  return self.ENGINE_QT # Fallback if size cannot be determined

        max_dimension = max(self.image_width, self.image_height)
        use_vips_preferred = self.use_vips and HAS_VIPS

        # Decision Logic:
        # 1. Prefer VIPS for very large images if enabled
        if use_vips_preferred and max_dimension > self.size_threshold:
            logger.debug(f"Using VIPS for large image ({max_dimension}px): {self.worker_id}")
            return self.ENGINE_VIPS
        # 2. Prefer PIL if available (generally faster than Qt for many formats)
        elif HAS_PIL:
            logger.debug(f"Using PIL for image ({max_dimension}px): {self.worker_id}")
            return self.ENGINE_PIL
        # 3. Use VIPS if PIL not available but VIPS is
        elif use_vips_preferred:
            logger.debug(f"Using VIPS (PIL unavailable) for image ({max_dimension}px): {self.worker_id}")
            return self.ENGINE_VIPS
        # 4. Fallback to Qt
        else:
            logger.debug(f"Using Qt (VIPS/PIL unavailable) for image ({max_dimension}px): {self.worker_id}")
            return self.ENGINE_QT

    def _get_image_size(self) -> Optional[Tuple[int, int]]:
        """
        画像サイズを取得（可能な限り軽量に）

        Returns:
            (width, height): 画像のサイズ、またはNone
        """
        # Try VIPS first if available (often fastest for just size)
        if HAS_VIPS:
             try:
                  # Use fail=True to catch unsupported formats quickly
                  # Use access='sequential' for potentially faster header reading
                  # pyvips.Image.new_from_file can raise an Error exception
                  img_vips = pyvips.Image.new_from_file(self.image_path, access='sequential', fail=True)
                  # logger.debug(f"Got size via VIPS for {self.worker_id}")
                  return (img_vips.width, img_vips.height)
             except pyvips.Error as vips_e:
                  logger.debug(f"VIPS failed to get size for {self.worker_id}: {vips_e} (trying other methods)")
             except Exception as e:
                  logger.warning(f"Unexpected error getting size via VIPS for {self.worker_id}: {e}")


        # Try PIL if VIPS failed or unavailable
        if HAS_PIL:
            try:
                with self.image_lock: # Lock around PIL operations if needed
                    # Open without loading pixel data using verify() might be faster?
                    # For now, just open normally.
                    with Image.open(self.image_path) as img:
                        # logger.debug(f"Got size via PIL for {self.worker_id}")
                        return img.size # (width, height)
            except UnidentifiedImageError:
                 logger.debug(f"PIL could not identify image format for {self.worker_id}")
            except Exception as e:
                logger.warning(f"Error getting size via PIL for {self.worker_id}: {e}")

        # Try Qt as a last resort (might load more data than needed)
        try:
            qimg_info = QImage(self.image_path)
            if not qimg_info.isNull():
                # logger.debug(f"Got size via Qt for {self.worker_id}")
                return (qimg_info.width(), qimg_info.height())
            else:
                 logger.debug(f"Qt could not load image for size info: {self.worker_id}")
        except Exception as e:
            logger.warning(f"Error getting size via Qt for {self.worker_id}: {e}")

        logger.error(f"Failed to determine image size for: {self.worker_id}")
        return None

    def _generate_with_pil(self) -> Optional[QPixmap]:
        """PILを使用してサムネイルを生成"""
        if not HAS_PIL: return None
        logger.debug(f"Generating thumbnail with PIL for {self.worker_id}")
        try:
            with self.image_lock: # Ensure thread safety for PIL operations if necessary
                with Image.open(self.image_path) as img:
                    self.image_format = img.format or ""
                    self.image_width, self.image_height = img.size # Update size info

                    # Handle potential mode issues (e.g., CMYK, P) before thumbnailing
                    if img.mode == 'P':
                         # Convert indexed color to RGBA or RGB
                         img = img.convert('RGBA')
                    elif img.mode == 'CMYK':
                         img = img.convert('RGB')
                    elif img.mode == 'RGBA' and self.image_format == 'JPEG':
                         img = img.convert('RGB') # Remove alpha for JPEG

                    self.check_cancelled() # Check cancellation before intensive operation
                    self.update_progress(40, "サムネイル生成中 (PIL)...")

                    # Use LANCZOS resampling if configured
                    resample_filter = Image.Resampling.LANCZOS if self.use_lanczos else Image.Resampling.BILINEAR
                    img.thumbnail(self.size, resample=resample_filter)

                    self.check_cancelled() # Check after thumbnailing
                    self.update_progress(70, "QPixmapに変換中 (PIL)...")

                    # Convert PIL Image to QPixmap via QImage
                    # Try to detect format for saving to buffer, default to PNG
                    buffer_format = "PNG" # Default, supports alpha
                    img_format_upper = self.image_format.upper() if self.image_format else ""

                    byte_arr = BytesIO()
                    save_options = {}
                    if buffer_format == "PNG":
                         save_options['compress_level'] = 1 # Faster PNG saving

                    img.save(byte_arr, format=buffer_format, **save_options)
                    byte_arr.seek(0) # Reset buffer position

                    qimg = QImage()
                    load_ok = qimg.loadFromData(byte_arr.read()) # Read bytes

                    if not load_ok or qimg.isNull():
                        logger.warning(f"Failed to load QImage from PIL buffer for {self.worker_id}")
                        return None

                    pixmap = QPixmap.fromImage(qimg)
                    logger.debug(f"PIL generation successful for {self.worker_id}")
                    return pixmap

        except UnidentifiedImageError:
            logger.warning(f"PIL could not identify image format: {self.image_path} ({self.worker_id})")
            return None
        except CancellationError:
             raise # Propagate cancellation
        except Exception as e:
            logger.error(f"PIL generation error for {self.worker_id}: {e}", exc_info=True)
            return None


    def _generate_with_vips(self) -> Optional[QPixmap]:
        """libvipsを使用してサムネイルを生成"""
        if not HAS_VIPS: return None
        logger.debug(f"Generating thumbnail with VIPS for {self.worker_id}")
        try:
            self.update_progress(30, "画像読み込み中 (VIPS)...")

            # --- Modified VIPS thumbnail call ---
            # Use thumbnail function, only specify width. Height is calculated.
            # Remove unsupported keyword arguments like 'size' and potentially 'height' if width is enough.
            # Keep auto_rotate=True as it's generally useful and supported.
            vips_thumb = pyvips.Image.thumbnail(
                self.image_path,
                self.size[0], # Target width
                height=self.size[1], # Specify target height as well, VIPS should handle aspect ratio
                auto_rotate=True
                # Removed: size=pyvips.enums.Size.BOTH
            )
            # --- End Modification ---


            # Update image info if possible (thumbnail might not have original size)
            self.image_width = vips_thumb.width
            self.image_height = vips_thumb.height
            # Cannot easily get original format from thumbnail result

            self.check_cancelled() # Check after loading/thumbnailing
            self.update_progress(70, "フォーマット変換中 (VIPS)...")

            # Write to buffer in a suitable format (e.g., WebP or PNG)
            # WebP generally offers good compression/speed balance
            buffer_format = ".webp"
            save_options = {"Q": self.webp_quality, "strip": self.strip_metadata, "lossless": False}
            # Alternative: PNG for guaranteed lossless alpha
            # buffer_format = ".png"
            # save_options = {"compression": 1, "strip": self.strip_metadata}

            image_data = vips_thumb.write_to_buffer(buffer_format, **save_options)

            self.check_cancelled() # Check after writing to buffer
            self.update_progress(85, "QPixmapに変換中 (VIPS)...")

            q_image = QImage()
            load_ok = q_image.loadFromData(image_data) # Load from buffer

            if not load_ok or q_image.isNull():
                 logger.warning(f"Failed to load QImage from VIPS {buffer_format} buffer for {self.worker_id}")
                 # Try PNG fallback if WebP failed?
                 if buffer_format == ".webp":
                      logger.debug(f"Retrying VIPS generation with PNG format for {self.worker_id}")
                      png_options = {"compression": 1, "strip": self.strip_metadata}
                      image_data = vips_thumb.write_to_buffer(".png", **png_options)
                      q_image = QImage() # Create new QImage instance
                      load_ok = q_image.loadFromData(image_data)
                      if not load_ok or q_image.isNull():
                           logger.error(f"Failed to load QImage from VIPS PNG buffer for {self.worker_id}")
                           return None
                 else:
                      return None # Already tried PNG or other format

            pixmap = QPixmap.fromImage(q_image)
            logger.debug(f"VIPS generation successful for {self.worker_id}")
            return pixmap

        except pyvips.Error as vips_e:
            # Catch specific VIPS errors
            logger.error(f"VIPS generation error for {self.worker_id}: {vips_e}")
            # Log the specific arguments maybe?
            # logger.debug(f"VIPS thumbnail args: width={self.size[0]}, height={self.size[1]}, auto_rotate=True")
            return None
        except CancellationError:
             raise # Propagate cancellation
        except Exception as e:
            logger.error(f"Unexpected VIPS generation error for {self.worker_id}: {e}", exc_info=True)
            return None

    def _generate_with_qt(self) -> Optional[QPixmap]:
        """Qtを使用してサムネイルを生成"""
        logger.debug(f"Generating thumbnail with Qt for {self.worker_id}")
        try:
            self.update_progress(40, "画像を読み込み中 (Qt)...")

            # QPixmap is generally preferred for display, try loading directly
            pixmap = QPixmap(self.image_path)

            if pixmap.isNull():
                # Try QImage as fallback if QPixmap fails
                logger.debug(f"QPixmap failed for {self.worker_id}, trying QImage.")
                qimg = QImage(self.image_path)
                if qimg.isNull():
                    logger.warning(f"Qt failed to load image: {self.image_path} ({self.worker_id})")
                    return None # Return None instead of placeholder here
                else:
                     self.image_width = qimg.width()
                     self.image_height = qimg.height()
                     pixmap = QPixmap.fromImage(qimg) # Convert loaded QImage to QPixmap
            else:
                 self.image_width = pixmap.width()
                 self.image_height = pixmap.height()


            self.check_cancelled() # Check after loading
            self.update_progress(60, "サムネイル生成中 (Qt)...")

            # Scale the loaded pixmap
            thumbnail = pixmap.scaled(
                self.size[0], self.size[1],
                Qt.AspectRatioMode.KeepAspectRatio, # Use AspectRatioMode enum
                Qt.TransformationMode.SmoothTransformation # Use TransformationMode enum
            )

            if thumbnail.isNull():
                 logger.warning(f"Qt scaling resulted in null pixmap for {self.worker_id}")
                 return None

            logger.debug(f"Qt generation successful for {self.worker_id}")
            return thumbnail

        except CancellationError:
             raise # Propagate cancellation
        except Exception as e:
            logger.error(f"Qt generation error for {self.worker_id}: {e}", exc_info=True)
            return None # Return None on error


    def _create_error_placeholder(self, text="Error") -> QPixmap:
        """エラー時のプレースホルダーを生成"""
        try:
             pixmap = QPixmap(self.size[0], self.size[1])
             pixmap.fill(Qt.GlobalColor.lightGray) # Use GlobalColor enum
             pixmap.setProperty("isErrorPlaceholder", True) # Set custom property

             # Optionally draw text indicating error
             # from PySide6.QtGui import QPainter, QColor, QPen
             # painter = QPainter(pixmap)
             # pen = QPen(QColor(Qt.GlobalColor.red))
             # painter.setPen(pen)
             # painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
             # painter.end()

             return pixmap
        except Exception as e:
             logger.error(f"Failed to create error placeholder: {e}")
             # Return an absolutely minimal pixmap if creation fails
             err_pixmap = QPixmap(1, 1)
             err_pixmap.setProperty("isErrorPlaceholder", True)
             return err_pixmap


    # This might be redundant if worker manager tracks info
    def get_image_info(self) -> Dict[str, Any]:
        """処理した画像の情報を取得"""
        return {
            "path": self.image_path,
            "width": self.image_width,
            "height": self.image_height,
            "format": self.image_format,
            "thumbnail_size": self.size,
            "engine_used": self.engine_used
        }

# --- END REFACTORED controllers/unified_thumbnail_worker.py ---
