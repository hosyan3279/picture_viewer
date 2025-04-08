"""
グリッドビューのリファクタリングをテストするためのシンプルなテストプログラム
"""
import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QTabWidget
from PySide6.QtCore import QTimer

# ローカルモジュールをインポート
from models.image_model import ImageModel
from controllers.worker_manager import WorkerManager
from views.image_grid_view import ImageGridView
from views.enhanced_grid_view import EnhancedGridView
from views.scroll_aware_image_grid import ScrollAwareImageGrid

class TestWindow(QMainWindow):
    """
    テスト用のメインウィンドウ
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("グリッドビューテスト")
        self.resize(800, 600)
        
        # モデルとワーカーマネージャーを初期化
        self.image_model = ImageModel()
        self.worker_manager = WorkerManager()
        
        # 中央ウィジェットを作成
        self.tab_widget = QTabWidget()
        
        # 各タイプのグリッドビューを作成
        self.basic_grid_view = ImageGridView(self.image_model, self.worker_manager)
        self.enhanced_grid_view = EnhancedGridView(self.image_model, self.worker_manager)
        self.scroll_aware_grid_view = ScrollAwareImageGrid(self.image_model, self.worker_manager)
        
        # タブウィジェットに追加
        self.tab_widget.addTab(self.basic_grid_view, "基本グリッドビュー")
        self.tab_widget.addTab(self.enhanced_grid_view, "拡張グリッドビュー")
        self.tab_widget.addTab(self.scroll_aware_grid_view, "スクロール最適化グリッドビュー")
        
        self.setCentralWidget(self.tab_widget)
        
        # グリッドビューのシグナルを接続
        self.basic_grid_view.image_selected.connect(self.on_image_selected)
        self.enhanced_grid_view.image_selected.connect(self.on_image_selected)
        self.scroll_aware_grid_view.image_selected.connect(self.on_image_selected)
        
        # テスト用にダミーデータを追加
        self.add_dummy_data()
    
    def add_dummy_data(self):
        """テスト用のダミーデータを追加"""
        for i in range(100):
            self.image_model.add_image(f"dummy/image_{i}.jpg")
        
        # モデルに変更を通知
        self.image_model.data_changed.emit()
        
        # ステータスバーに情報を表示
        self.statusBar().showMessage(f"{self.image_model.image_count()}個のダミー画像を追加しました")
    
    def on_image_selected(self, image_path):
        """画像選択時の処理"""
        self.statusBar().showMessage(f"選択された画像: {image_path}")

def main():
    """メイン関数"""
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
