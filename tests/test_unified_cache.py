"""
UnifiedThumbnailCacheとUnifiedThumbnailWorkerのテストスクリプト

統合されたサムネイルキャッシュとサムネイル生成ワーカーの機能をテストします。
"""
import os
import time
import unittest
import tempfile
import shutil
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QSize

import sys
# プロジェクトルートディレクトリをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.unified_thumbnail_cache import UnifiedThumbnailCache
from controllers.unified_thumbnail_worker import UnifiedThumbnailWorker
from controllers.worker_manager import WorkerManager

# アプリケーションインスタンスを作成（Qtの要件）
app = QApplication.instance() or QApplication([])

class TestUnifiedThumbnailCache(unittest.TestCase):
    """UnifiedThumbnailCacheのテストクラス"""
    
    def setUp(self):
        """テスト前の準備"""
        # テスト用の一時ディレクトリを作成
        self.temp_dir = tempfile.mkdtemp(prefix="test_thumbnail_cache_")
        
        # テスト用キャッシュディレクトリ
        self.cache_dir = os.path.join(self.temp_dir, 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # テスト用画像ディレクトリ
        self.images_dir = os.path.join(self.temp_dir, 'images')
        os.makedirs(self.images_dir, exist_ok=True)
        
        # テスト用画像を作成（単純な色のついた四角形）
        self.test_image_path = os.path.join(self.images_dir, 'test.png')
        self._create_test_image(self.test_image_path, 200, 200)
        
        # 大きめの画像も作成
        self.large_image_path = os.path.join(self.images_dir, 'large.png')
        self._create_test_image(self.large_image_path, 1000, 1000)
        
        # UnifiedThumbnailCacheを作成
        self.cache = UnifiedThumbnailCache(
            memory_limit=10,
            disk_cache_dir=self.cache_dir,
            disk_cache_limit_mb=10,
            cleanup_interval=1000
        )
        
        # WorkerManagerを作成
        self.worker_manager = WorkerManager()
    
    def tearDown(self):
        """テスト後のクリーンアップ"""
        # ワーカーマネージャを停止
        self.worker_manager.wait_for_all()
        
        # キャッシュをクリア
        self.cache.clear(clear_disk=True)
        
        # 一時ディレクトリを削除
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass
    
    def _create_test_image(self, path, width, height):
        """テスト用の画像を作成"""
        pixmap = QPixmap(width, height)
        pixmap.fill(0xFFBBBBBB)  # 薄いグレー
        pixmap.save(path, "PNG")
    
    def test_cache_store_and_retrieve(self):
        """キャッシュの保存と取得のテスト"""
        # テスト用のサムネイルを作成
        test_size = (100, 100)
        pixmap = QPixmap(100, 100)
        pixmap.fill(0xFFCCCCCC)  # 別の薄いグレー
        
        # キャッシュに保存
        result = self.cache.store_thumbnail(self.test_image_path, test_size, pixmap)
        self.assertTrue(result, "サムネイルを保存できませんでした")
        
        # キャッシュから取得
        retrieved = self.cache.get_thumbnail(self.test_image_path, test_size)
        self.assertIsNotNone(retrieved, "サムネイルを取得できませんでした")
        self.assertEqual(retrieved.width(), 100, "サムネイルの幅が正しくありません")
        self.assertEqual(retrieved.height(), 100, "サムネイルの高さが正しくありません")
        
        # 存在しない画像はNoneを返すことを確認
        none_result = self.cache.get_thumbnail("non_existent.png", test_size)
        self.assertIsNone(none_result, "存在しない画像でNoneを返すべきです")
    
    def test_memory_cache_limit(self):
        """メモリキャッシュの上限テスト"""
        # メモリキャッシュの上限を超えるサムネイルを保存
        for i in range(15):  # memory_limitは10
            test_size = (50, 50)
            pixmap = QPixmap(50, 50)
            pixmap.fill(0xFF000000 + i * 0x10000)  # 異なる色
            self.cache.store_thumbnail(f"{self.test_image_path}_{i}", test_size, pixmap)
        
        # 統計情報を取得
        stats = self.cache.get_stats()
        
        # キャッシュのアイテム数が上限以下であることを確認
        self.assertLessEqual(stats['memory_cache_count'], 10, 
                           "メモリキャッシュのアイテム数が上限を超えています")
    
    def test_worker_thumbnail_generation(self):
        """サムネイル生成ワーカーのテスト"""
        # ワーカーを作成
        worker = UnifiedThumbnailWorker(self.test_image_path, (75, 75), self.cache)
        
        # 結果を取得するコールバック
        result_data = [None]
        
        def on_result(data):
            result_data[0] = data
        
        # シグナルを接続
        worker.signals.result.connect(on_result)
        
        # ワーカーを実行
        self.worker_manager.start_worker("test_worker", worker)
        
        # ワーカーの完了を待機
        self.worker_manager.wait_for_all()
        
        # 結果を確認
        self.assertIsNotNone(result_data[0], "ワーカーの結果がありません")
        image_path, thumbnail = result_data[0]
        
        self.assertEqual(image_path, self.test_image_path, "画像パスが一致しません")
        self.assertFalse(thumbnail.isNull(), "サムネイルがNullです")
        self.assertEqual(thumbnail.width(), 75, "サムネイルの幅が正しくありません")
        
        # キャッシュにも保存されていることを確認
        cached = self.cache.get_thumbnail(self.test_image_path, (75, 75))
        self.assertIsNotNone(cached, "サムネイルがキャッシュに保存されていません")
    
    def test_worker_large_image(self):
        """大きな画像のサムネイル生成テスト"""
        # ワーカーを作成
        worker = UnifiedThumbnailWorker(self.large_image_path, (150, 150), self.cache)
        
        # 結果を取得するコールバック
        result_data = [None]
        
        def on_result(data):
            result_data[0] = data
        
        # シグナルを接続
        worker.signals.result.connect(on_result)
        
        # ワーカーを実行
        self.worker_manager.start_worker("large_image_worker", worker)
        
        # ワーカーの完了を待機
        self.worker_manager.wait_for_all()
        
        # 結果を確認
        self.assertIsNotNone(result_data[0], "ワーカーの結果がありません")
        image_path, thumbnail = result_data[0]
        
        self.assertEqual(image_path, self.large_image_path, "画像パスが一致しません")
        self.assertFalse(thumbnail.isNull(), "サムネイルがNullです")
        self.assertLessEqual(thumbnail.width(), 150, "サムネイルの幅が上限を超えています")
        self.assertLessEqual(thumbnail.height(), 150, "サムネイルの高さが上限を超えています")
    
    def test_stats(self):
        """統計情報のテスト"""
        # いくつかのサムネイルを保存
        for i in range(5):
            test_size = (60, 60)
            pixmap = QPixmap(60, 60)
            pixmap.fill(0xFF000000 + i * 0x10000)  # 異なる色
            self.cache.store_thumbnail(f"{self.test_image_path}_{i}", test_size, pixmap)
        
        # 何回かアクセスする
        for i in range(3):
            _ = self.cache.get_thumbnail(f"{self.test_image_path}_{i}", (60, 60))
        
        # 存在しないものにもアクセス（ミス）
        _ = self.cache.get_thumbnail("non_existent.png", (60, 60))
        
        # 統計情報を取得
        stats = self.cache.get_stats()
        
        # 各種統計情報が取得できることを確認
        self.assertIn('memory_cache_count', stats, "memory_cache_countがありません")
        self.assertIn('disk_cache_count', stats, "disk_cache_countがありません")
        self.assertIn('hits', stats, "hitsがありません")
        self.assertIn('misses', stats, "missesがありません")
        self.assertIn('hit_ratio', stats, "hit_ratioがありません")
        
        # ヒット数とミス数が正しいか確認（近似値）
        self.assertGreaterEqual(stats['hits'], 3, "ヒット数が少なすぎます")
        self.assertGreaterEqual(stats['misses'], 1, "ミス数が少なすぎます")
    
    def test_purge_invalid_entries(self):
        """無効なエントリのパージテスト"""
        # 有効なエントリを作成
        valid_size = (80, 80)
        pixmap = QPixmap(80, 80)
        pixmap.fill(0xFFDDDDDD)
        self.cache.store_thumbnail(self.test_image_path, valid_size, pixmap)
        
        # 後で削除する一時ファイルを作成
        temp_image_path = os.path.join(self.images_dir, 'temp.png')
        self._create_test_image(temp_image_path, 200, 200)
        
        # 一時ファイル用のサムネイルを作成
        temp_size = (90, 90)
        temp_pixmap = QPixmap(90, 90)
        temp_pixmap.fill(0xFFEEEEEE)
        self.cache.store_thumbnail(temp_image_path, temp_size, temp_pixmap)
        
        # ファイルを削除して無効なエントリにする
        os.remove(temp_image_path)
        
        # 無効なエントリをパージ
        purged = self.cache.purge_invalid_entries()
        
        # 少なくとも1つのエントリがパージされたことを確認
        self.assertGreaterEqual(purged, 1, "無効なエントリがパージされていません")
        
        # パージ後に無効なエントリにアクセスするとNoneが返ることを確認
        none_result = self.cache.get_thumbnail(temp_image_path, temp_size)
        self.assertIsNone(none_result, "無効なエントリがまだキャッシュに残っています")
        
        # 有効なエントリはまだアクセスできることを確認
        valid_result = self.cache.get_thumbnail(self.test_image_path, valid_size)
        self.assertIsNotNone(valid_result, "有効なエントリがアクセスできません")

if __name__ == '__main__':
    unittest.main()
