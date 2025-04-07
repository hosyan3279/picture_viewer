"""
アプリケーションのエントリーポイント

画像ビューワーアプリケーションを起動します。
"""
import sys
from PySide6.QtWidgets import QApplication
from views.main_window import MainWindow

def main():
    """アプリケーションのメイン関数"""
    # アプリケーションの作成
    app = QApplication(sys.argv)
    app.setApplicationName("画像ビューワー")
    
    # スタイルシートの設定（オプション）
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f5f5f5;
        }
        QStatusBar {
            background-color: #ececec;
            color: #333333;
        }
        QToolBar {
            background-color: #f8f8f8;
            border-bottom: 1px solid #d0d0d0;
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
        QPushButton:disabled {
            color: #a0a0a0;
            background-color: #f5f5f5;
        }
        QLabel[imageLabel="true"] {
            border: 1px solid #cccccc; 
            background-color: #f9f9f9;
        }
        QLabel[imageLabel="true"]:hover {
            border: 1px solid #3399ff;
        }
        QScrollArea {
            border: none;
            background-color: #ffffff;
        }
    """)
    
    # メインウィンドウの作成と表示
    window = MainWindow()
    window.show()
    
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
