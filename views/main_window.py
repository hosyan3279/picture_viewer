"""
メインウィンドウモジュール

アプリケーションのメインウィンドウを提供します。
"""
import os
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QStatusBar,
    QToolBar, QStyle
)
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtCore import Qt, Slot

from ..models.image_model import ImageModel
from ..models.enhanced_thumbnail_cache import EnhancedThumbnailCache
from ..controllers.worker_manager import WorkerManager
from ..controllers.enhanced_image_loader import EnhancedImageLoader
from .enhanced_grid_view import EnhancedGridView
from ..controllers.directory_scanner import DirectoryScannerWorker # 確認用インポート

class MainWindow(QMainWindow):
    """
    アプリケーションのメインウィンドウ
    
    メニュー、ツールバー、ステータスバー、および中央ウィジェットを管理します。
    """
    
    def __init__(self):
        """初期化"""
        super().__init__()
        
        # ウィンドウの設定
        self.setWindowTitle("画像ビューワー")
        self.resize(800, 600)
        
        # モデルとコントローラーの初期化
        self.image_model = ImageModel()
        # 拡張されたサムネイルキャッシュを使用
        self.thumbnail_cache = EnhancedThumbnailCache(
            memory_limit=500,  # 最大500枚のサムネイルをメモリに保持
            disk_cache_limit_mb=2000,  # ディスクキャッシュは2GBまで
            cleanup_interval=120000  # 2分ごとにクリーンアップをチェック
        )
        self.worker_manager = WorkerManager()
        self.image_loader = EnhancedImageLoader(self.image_model, self.thumbnail_cache, self.worker_manager)
        
        # UIコンポーネントの初期化
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        """UIコンポーネントを設定"""
        # ステータスバーの設定
        self.statusBar().showMessage("準備完了")
        
        # メニューバーの設定
        self.create_menus()
        
        # ツールバーの設定
        self.create_toolbars()
        
        # 中央ウィジェットの設定（拡張グリッドビューを使用）
        self.image_grid_view = EnhancedGridView(
            self.image_model,
            self.worker_manager
        )
        self.setCentralWidget(self.image_grid_view)
    
    def create_menus(self):
        """メニューを作成"""
        # ファイルメニュー
        file_menu = self.menuBar().addMenu("ファイル")
        
        # フォルダを開くアクション
        open_action = QAction("フォルダを開く...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_action)
        
        # キャッシュメニュー
        cache_menu = file_menu.addMenu("キャッシュ")
        
        # キャッシュをクリアアクション
        clear_cache_action = QAction("キャッシュをクリア", self)
        clear_cache_action.triggered.connect(self.clear_cache)
        cache_menu.addAction(clear_cache_action)
        
        # キャッシュ情報を表示アクション
        show_cache_info_action = QAction("キャッシュ情報を表示", self)
        show_cache_info_action.triggered.connect(self.show_cache_info)
        cache_menu.addAction(show_cache_info_action)
        
        file_menu.addSeparator()
        
        # 終了アクション
        exit_action = QAction("終了", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 表示メニュー
        view_menu = self.menuBar().addMenu("表示")
        
        # 表示のリフレッシュアクション
        refresh_action = QAction("表示を更新", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh_view)
        view_menu.addAction(refresh_action)
    
    def create_toolbars(self):
        """ツールバーを作成"""
        # メインツールバー
        main_toolbar = QToolBar("メインツールバー", self)
        self.addToolBar(main_toolbar)
        
        # フォルダを開くアクション
        open_action = QAction("フォルダを開く", self)
        open_action.triggered.connect(self.open_folder)
        # 標準アイコンを使用
        open_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        main_toolbar.addAction(open_action)
    
    def setup_connections(self):
        """シグナル/スロット接続を設定"""
        # イメージローダーの接続
        self.image_loader.loading_finished.connect(self.loading_finished)
        self.image_loader.thumbnail_created.connect(self.update_thumbnail)
        self.image_loader.error_occurred.connect(self.show_error)
        self.image_loader.progress_updated.connect(self.update_progress) # 進捗シグナルを接続

        # イメージグリッドビューの接続
        self.image_grid_view.image_selected.connect(self.show_image_details)
        self.image_grid_view.thumbnail_needed.connect(self.image_loader.request_thumbnail)

    @Slot()
    def open_folder(self):
        """フォルダを開く"""
        folder_path = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder_path:
            self.statusBar().showMessage(f"フォルダスキャン開始: {os.path.basename(folder_path)}...")
            # 以前のワーカーが動いていたらキャンセルする方が良いかも
            self.worker_manager.cancel_worker("folder_scan")
            self.image_loader.load_images_from_folder(folder_path)

    @Slot(int)
    def update_progress(self, value):
        """
        進捗を更新 (フォルダスキャン中)

        Args:
            value (int): 進捗値 (0-100)
        """
        self.statusBar().showMessage(f"フォルダスキャン中... {value}%")

    @Slot()
    def loading_finished(self):
        """フォルダスキャンとモデル更新完了時の処理"""
        count = self.image_model.image_count()
        # この時点ではGridViewの表示更新は始まっているはず (data_changed経由)
        self.statusBar().showMessage(f"{count}枚の画像を検出しました。サムネイル表示中...")
        # 必要であれば、ここでGridViewに明示的な更新指示を出すことも可能だが、
        # 通常はImageModelのdata_changedシグナルで十分なはず。

    @Slot(str, object)
    def update_thumbnail(self, image_path, thumbnail):
        """
        サムネイルを更新

        Args:
            image_path (str): 画像のパス
            thumbnail: サムネイル画像 (QPixmap)
        """
        self.image_grid_view.update_thumbnail(image_path, thumbnail)

    @Slot(str)
    def show_error(self, message):
        """
        エラーメッセージを表示

        Args:
            message (str): エラーメッセージ
        """
        self.statusBar().showMessage("エラーが発生しました") # ステータスバーも更新
        QMessageBox.critical(self, "エラー", message)
    
    @Slot(str)
    def show_image_details(self, image_path):
        """
        画像の詳細を表示
        
        Args:
            image_path (str): 画像のパス
        """
        # 現在はパスをステータスバーに表示するだけ
        self.statusBar().showMessage(f"選択された画像: {image_path}")
        
        # 詳細表示機能は拡張タスクで実装予定
    
    @Slot()
    def clear_cache(self):
        """キャッシュをクリア"""
        self.thumbnail_cache.clear()
        QMessageBox.information(self, "情報", "サムネイルキャッシュをクリアしました")
    
    @Slot()
    def show_cache_info(self):
        """キャッシュ情報を表示"""
        stats = self.thumbnail_cache.get_stats()
        
        # 統計情報を整形
        info_text = "【サムネイルキャッシュ情報】\n\n"
        info_text += f"メモリキャッシュ: {stats['memory_cache_count']} / {stats['memory_cache_limit']} アイテム\n"
        info_text += f"ディスクキャッシュ: {stats['disk_cache_count']} アイテム\n"
        info_text += f"ディスクキャッシュサイズ: {stats['disk_cache_size_mb']:.2f} MB / {stats['disk_cache_limit_mb']:.2f} MB\n"
        
        # 拡張キャッシュの場合は追加情報を表示
        if 'enhanced' in stats and stats['enhanced']:
            info_text += f"\nキャッシュヒット: {stats['cache_hits']} 回\n"
            info_text += f"キャッシュミス: {stats['cache_misses']} 回\n"
            info_text += f"ヒット率: {stats['hit_ratio']:.2f}%\n"
            info_text += f"クリーンアップ間隔: {stats['cleanup_interval_ms'] / 1000} 秒\n"
        
        QMessageBox.information(self, "キャッシュ情報", info_text)
    
    @Slot()
    def refresh_view(self):
        """表示を更新"""
        self.image_grid_view.refresh()
