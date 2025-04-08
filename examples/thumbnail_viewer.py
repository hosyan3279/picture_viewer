#!/usr/bin/env python3
"""
サムネイルビューワーの例

統合サムネイルキャッシュと統合サムネイル生成ワーカーを使用した
シンプルなサムネイルビューワーのサンプルアプリケーション。
"""
import os
import sys
import time
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QPushButton, QLabel, QGridLayout, QScrollArea,
    QProgressBar, QStatusBar, QMessageBox
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap

# プロジェクトのルートディレクトリをPythonパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 統合サムネイルキャッシュとワーカーをインポート
from models.unified_thumbnail_cache import UnifiedThumbnailCache
from controllers.unified_thumbnail_worker import UnifiedThumbnailWorker
from controllers.worker_manager import WorkerManager

class ImageLabel(QLabel):
    """クリック可能なサムネイル画像ラベル"""
    clicked = Signal(str)  # 画像パスを送信するシグナル
    
    def __init__(self, image_path=None, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setFixedSize(150, 150)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                border: 1px solid #cccccc;
                background-color: #f9f9f9;
                border-radius: 3px;
            }
            QLabel:hover {
                border: 1px solid #aaaaaa;
                background-color: #f0f0f0;
            }
        """)
        
        # プレースホルダーテキスト
        self.setText("読み込み中...")
    
    def mousePressEvent(self, event):
        """マウスクリックイベント"""
        if event.button() == Qt.LeftButton and self.image_path:
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)

class ThumbnailViewer(QMainWindow):
    """サムネイルビューワーのメインウィンドウ"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("サムネイルビューワー")
        self.resize(800, 600)
        
        # サムネイルキャッシュを作成
        self.cache = UnifiedThumbnailCache(
            memory_limit=200,
            disk_cache_limit_mb=1000,
            cleanup_interval=60000
        )
        
        # ワーカーマネージャーを作成
        self.worker_manager = WorkerManager()
        
        # UIの構築
        self.setup_ui()
        
        # 画像ラベルのマッピング
        self.image_labels = {}  # 画像パス -> ラベル
        
        # 画像リスト
        self.image_paths = []
        
        # ステータスバーを更新
        self.statusBar().showMessage("フォルダを選択してください")
    
    def setup_ui(self):
        """UIを構築"""
        # 中央ウィジェット
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # ツールバー
        toolbar = QHBoxLayout()
        
        # フォルダを開くボタン
        self.open_button = QPushButton("フォルダを開く")
        self.open_button.clicked.connect(self.open_folder)
        toolbar.addWidget(self.open_button)
        
        # キャッシュ情報ボタン
        self.cache_info_button = QPushButton("キャッシュ情報")
        self.cache_info_button.clicked.connect(self.show_cache_info)
        toolbar.addWidget(self.cache_info_button)
        
        # キャッシュクリアボタン
        self.clear_cache_button = QPushButton("キャッシュクリア")
        self.clear_cache_button.clicked.connect(self.clear_cache)
        toolbar.addWidget(self.clear_cache_button)
        
        toolbar.addStretch()
        
        # プログレスバー
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        toolbar.addWidget(self.progress_bar)
        
        # レイアウトに追加
        main_layout.addLayout(toolbar)
        
        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        main_layout.addWidget(self.scroll_area)
        
        # グリッドウィジェット
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        self.scroll_area.setWidget(self.grid_widget)
        
        # 大きな画像表示用ラベル
        self.large_image_label = QLabel("画像を選択してください")
        self.large_image_label.setAlignment(Qt.AlignCenter)
        self.large_image_label.setMinimumHeight(200)
        main_layout.addWidget(self.large_image_label)
        
        # ステータスバー
        self.statusBar()
    
    def open_folder(self):
        """フォルダを開く"""
        folder_path = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder_path:
            # フォルダ内の画像を検索
            self.load_images_from_folder(folder_path)
    
    def load_images_from_folder(self, folder_path):
        """フォルダから画像を読み込む"""
        # 対応する画像形式
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        
        # グリッドをクリア
        self.clear_grid()
        
        # 画像リストをクリア
        self.image_paths = []
        
        # フォルダ内の画像を検索
        start_time = time.time()
        for root, _, files in os.walk(folder_path):
            for file in files:
                ext = os.path.splitext(file.lower())[1]
                if ext in image_extensions:
                    self.image_paths.append(os.path.join(root, file))
        
        # 検索時間
        elapsed = time.time() - start_time
        
        # 画像がない場合
        if not self.image_paths:
            self.statusBar().showMessage(f"フォルダに画像が見つかりませんでした ({elapsed:.2f}秒)")
            return
        
        # ステータスバーを更新
        self.statusBar().showMessage(f"{len(self.image_paths)}枚の画像を読み込みました ({elapsed:.2f}秒)")
        
        # サムネイルを表示
        self.display_thumbnails()
    
    def display_thumbnails(self):
        """サムネイルを表示"""
        # グリッドをクリア
        self.clear_grid()
        
        # 列数 (ウィンドウサイズに応じて調整)
        columns = 4
        
        # サムネイルサイズ
        thumb_size = (150, 150)
        
        # 画像を配置
        for i, image_path in enumerate(self.image_paths):
            row, col = divmod(i, columns)
            
            # ラベルを作成
            label = ImageLabel(image_path)
            label.clicked.connect(self.show_large_image)
            
            # グリッドに配置
            self.grid_layout.addWidget(label, row, col)
            
            # マッピングを保存
            self.image_labels[image_path] = label
            
            # サムネイルを読み込み
            self.load_thumbnail(image_path, thumb_size, label)
    
    def load_thumbnail(self, image_path, size, label):
        """サムネイルを読み込む"""
        # キャッシュをチェック
        thumbnail = self.cache.get_thumbnail(image_path, size)
        
        if thumbnail is not None:
            # キャッシュヒット
            label.setPixmap(thumbnail)
            label.setText("")
            return
        
        # ワーカーを作成
        worker = UnifiedThumbnailWorker(image_path, size, self.cache)
        
        # 途中経過を表示
        worker.signals.progress.connect(lambda p, m, path=image_path: 
                                       self.update_progress(p, m, path))
        
        # 結果を処理
        worker.signals.result.connect(lambda result, label=label: 
                                     self.on_thumbnail_created(result, label))
        
        # エラーを処理
        worker.signals.error.connect(lambda error, label=label: 
                                    self.on_thumbnail_error(error, label))
        
        # ワーカーを開始
        self.worker_manager.start_worker(f"thumbnail_{image_path}", worker)
    
    def on_thumbnail_created(self, result, label):
        """サムネイル作成完了時の処理"""
        image_path, thumbnail = result
        
        # エラーチェック
        if thumbnail is None or thumbnail.isNull():
            label.setText("エラー")
            return
        
        # サムネイルを表示
        label.setPixmap(thumbnail)
        label.setText("")
        
        # ツールチップを設定
        label.setToolTip(image_path)
    
    def on_thumbnail_error(self, error, label):
        """サムネイル作成エラー時の処理"""
        label.setText("エラー")
        print(f"サムネイル作成エラー: {error}")
    
    def update_progress(self, progress, message, path):
        """進捗を更新"""
        if not self.progress_bar.isVisible():
            self.progress_bar.setVisible(True)
        
        self.progress_bar.setValue(progress)
        
        # ステータスバーにメッセージを表示
        filename = os.path.basename(path)
        self.statusBar().showMessage(f"{filename}: {message} ({progress}%)")
        
        # 完了時
        if progress >= 100:
            self.progress_bar.setVisible(False)
            self.statusBar().showMessage(f"{len(self.image_paths)}枚の画像を読み込みました")
    
    def show_large_image(self, image_path):
        """大きな画像を表示"""
        pixmap = QPixmap(image_path)
        
        if pixmap.isNull():
            self.large_image_label.setText("画像を読み込めませんでした")
            return
        
        # 表示サイズに合わせてリサイズ
        max_width = self.large_image_label.width() - 20
        max_height = self.large_image_label.height() - 20
        
        scaled_pixmap = pixmap.scaled(
            max_width, max_height,
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        
        # 画像を表示
        self.large_image_label.setPixmap(scaled_pixmap)
        
        # ファイル名をステータスバーに表示
        filename = os.path.basename(image_path)
        size = pixmap.size()
        self.statusBar().showMessage(f"{filename} ({size.width()}x{size.height()})")
    
    def clear_grid(self):
        """グリッドをクリア"""
        # すべてのウィジェットを削除
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # マッピングをクリア
        self.image_labels.clear()
    
    def show_cache_info(self):
        """キャッシュ情報を表示"""
        stats = self.cache.get_stats()
        
        message = "【サムネイルキャッシュ情報】\n\n"
        message += f"メモリキャッシュ: {stats['memory_cache_count']} / {stats['memory_cache_limit']} アイテム\n"
        message += f"ディスクキャッシュ: {stats['disk_cache_count']} アイテム\n"
        message += f"ディスクキャッシュサイズ: {stats['disk_cache_size_mb']:.2f} MB / {stats['disk_cache_limit_mb']:.2f} MB\n"
        message += f"ヒット: {stats['hits']} 回\n"
        message += f"ミス: {stats['misses']} 回\n"
        message += f"ヒット率: {stats['hit_ratio']:.2f}%\n"
        
        # 人気のエントリがあれば表示
        if 'popular_entries' in stats and stats['popular_entries']:
            message += "\n【よくアクセスされる画像】\n"
            for entry in stats['popular_entries']:
                filename = os.path.basename(entry['path'])
                message += f"- {filename} ({entry['size']}): {entry['count']}回\n"
        
        QMessageBox.information(self, "キャッシュ情報", message)
    
    def clear_cache(self):
        """キャッシュをクリア"""
        reply = QMessageBox.question(
            self, 
            "キャッシュクリア", 
            "サムネイルキャッシュをクリアしますか？",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # キャッシュをクリア
            self.cache.clear(clear_disk=True)
            
            # UIを更新（必要に応じて）
            if self.image_paths:
                # 現在のサムネイルを再読み込み
                for label in self.image_labels.values():
                    label.setText("読み込み中...")
                    label.setPixmap(QPixmap())
                
                # サムネイルを再読み込み
                for image_path, label in self.image_labels.items():
                    self.load_thumbnail(image_path, (150, 150), label)
            
            QMessageBox.information(self, "情報", "キャッシュをクリアしました")
    
    def closeEvent(self, event):
        """ウィンドウを閉じるときの処理"""
        # ワーカーをキャンセル
        self.worker_manager.cancel_all()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("サムネイルビューワー")
    
    # スタイルシートの設定（オプション）
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f5f5f5;
        }
        QStatusBar {
            background-color: #ececec;
            color: #333333;
        }
        QPushButton {
            background-color: #f0f0f0;
            border: 1px solid #c0c0c0;
            border-radius: 3px;
            padding: 3px 10px;
            min-width: 60px;
        }
        QPushButton:hover {
            background-color: #e5e5e5;
        }
        QPushButton:pressed {
            background-color: #d0d0d0;
        }
        ImageLabel[imageLabel="true"] {
            border: 1px solid #cccccc; 
            background-color: #f9f9f9;
        }
        ImageLabel[imageLabel="true"]:hover {
            border: 1px solid #3399ff;
        }
        QScrollArea {
            border: none;
            background-color: #ffffff;
        }
    """)
    
    window = ThumbnailViewer()
    window.show()
    
    sys.exit(app.exec())
