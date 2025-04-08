"""
アプリケーションのエントリーポイント

画像ビューワーアプリケーションを起動します。
"""
import sys
import os
import logging
from PySide6.QtWidgets import QApplication
from views.main_window import MainWindow
from utils import (
    logger, initialize_file_logging, enable_debug_logging,
    get_config, configure_vips
)

def main():
    """アプリケーションのメイン関数"""
    # 設定の初期化
    config = get_config()
    app_data_dir = config.get("app.data_dir")
    
    # ロギングの初期化
    log_dir = os.path.join(app_data_dir, "logs")
    initialize_file_logging(log_dir)
    
    # デバッグモードの場合はデバッグログを有効化
    if "--debug" in sys.argv or config.get("app.debug_mode"):
        enable_debug_logging()
        logger.debug("デバッグモードで起動しました")
        # 設定をデバッグ出力
        logger.debug(f"アプリケーション設定: データディレクトリ={app_data_dir}")
    
    # libvipsの設定を適用
    configure_vips()
    logger.info(f"libvips設定を適用しました")
    
    logger.info("アプリケーションを起動しています")
    
    # アプリケーションの作成
    app = QApplication(sys.argv)
    app.setApplicationName(config.get("app.name"))
    
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
    
    # ウィンドウサイズの取得
    window_size = config.get("app.window_size")
    
    logger.info("メインウィンドウを作成しています")
    # メインウィンドウの作成と表示
    window = MainWindow()
    window.resize(*window_size)
    window.show()
    
    logger.info("イベントループを開始します")
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
