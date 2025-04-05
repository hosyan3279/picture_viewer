"""
libvipsを使用した高速サムネイル生成ワーカーモジュール

libvipsを使用して高速かつメモリ効率の良いサムネイル生成を行うワーカークラスを提供します。
特に大きなサイズの画像を効率的に処理します。
"""
import os
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap, QImage
from .workers import BaseWorker
import pyvips
import tempfile
from io import BytesIO

class VipsThumbnailWorker(BaseWorker):
    """
    libvipsを使用した高速サムネイル生成ワーカークラス
    
    libvipsを使用して大きなサイズの画像を効率的にサムネイル化し、
    処理速度とメモリ使用量を最適化します。
    """
    
    def __init__(self, image_path, size, thumbnail_cache=None):
        """
        初期化
        
        Args:
            image_path (str): 原画像のパス
            size (tuple): 生成するサムネイルのサイズ (width, height)
            thumbnail_cache (ThumbnailCache, optional): サムネイルキャッシュ
        """
        super().__init__()
        self.image_path = image_path
        self.size = size
        self.thumbnail_cache = thumbnail_cache
    
    @Slot()
    def work(self):
        """
        サムネイルを生成
        
        libvipsを使用して高速・メモリ効率の良いサムネイル生成を行います。
        特に大きなサイズの画像に対して効率的に動作します。
        
        Returns:
            tuple: (image_path, thumbnail) - 画像パスとサムネイル画像のタプル
        """
        print(f"サムネイル生成開始: {self.image_path}")
        # キャッシュをチェック
        if self.thumbnail_cache:
            thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
            if thumbnail is not None:
                print(f"キャッシュヒット: {self.image_path}")
                return (self.image_path, thumbnail)
        
        try:
            print(f"DEBUG: Starting to load {self.image_path} with libvips")
            
            # libvipsでサムネイル生成（高速・低メモリ）
            try:
                # 画像の読み込み
                # access='sequential'は大きなファイルをストリーミング処理するために最適
                image = pyvips.Image.new_from_file(self.image_path, access='sequential')
                
                # 画像のスケーリング係数を計算
                scale = min(self.size[0] / image.width, self.size[1] / image.height)
                
                # 新しいサイズを計算
                new_width = int(image.width * scale)
                new_height = int(image.height * scale)
                
                # サムネイル生成（指定サイズに合わせて縮小）
                # libvipsのthumbnailメソッドはキャッシュや最適なアルゴリズムを自動選択
                thumbnail_image = image.thumbnail_image(new_width, height=new_height, 
                                                       size=pyvips.enums.Size.DOWN,
                                                       no_rotate=True)
                
                # 一時ファイルを作成せずメモリ上で処理
                # PNG形式でメモリ上に保存（QPixmapで読み込みやすいように）
                png_data = thumbnail_image.write_to_buffer(".png")
                
                # QImageに変換
                q_image = QImage.fromData(png_data)
                pixmap = QPixmap.fromImage(q_image)
                
            except Exception as vips_error:
                print(f"libvips処理エラー: {str(vips_error)}、標準的な方法で再試行します")
                
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
            
            # キャッシュに保存
            if self.thumbnail_cache:
                self.thumbnail_cache.store_thumbnail(self.image_path, self.size, pixmap)
            
            print(f"サムネイル生成完了: {self.image_path}")
            return (self.image_path, pixmap)
            
        except Exception as e:
            print(f"エラー発生: {self.image_path}, 理由: {e}")
            # エラーが発生した場合はプレースホルダーを返す
            pixmap = QPixmap(self.size[0], self.size[1])
            pixmap.fill(Qt.lightGray)
            return (self.image_path, pixmap)
