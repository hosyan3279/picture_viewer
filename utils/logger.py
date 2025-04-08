"""
ロギングユーティリティモジュール

アプリケーション全体で使用される一貫したロギング機能を提供します。
"""
import os
import logging
import sys
from logging.handlers import RotatingFileHandler

# ロガーの設定
logger = logging.getLogger('picture_viewer')

# ログレベルの初期化（デフォルトはINFO）
logger.setLevel(logging.INFO)

# ログフォーマット
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

# コンソールハンドラー
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ログファイルパスの設定
def initialize_file_logging(log_dir=None):
    """ファイルベースのロギングを初期化する

    Args:
        log_dir (str, optional): ログディレクトリのパス。指定がない場合は、ユーザーのホームディレクトリに作成されます。
    """
    global logger
    
    # デフォルトのログディレクトリはユーザーのホームディレクトリ
    if log_dir is None:
        log_dir = os.path.join(os.path.expanduser("~"), ".picture_viewer", "logs")
    
    # ログディレクトリが存在しない場合は作成
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "picture_viewer.log")
    
    # ローテーティングファイルハンドラー（1MBごとにローテーション、最大5ファイル）
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1024*1024, backupCount=5)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # 既存のファイルハンドラーを削除（再初期化のため）
    for handler in logger.handlers[:]:
        if isinstance(handler, RotatingFileHandler):
            logger.removeHandler(handler)
    
    logger.addHandler(file_handler)
    logger.info("File logging initialized: %s", log_file)

def set_log_level(level):
    """ロガーのログレベルを設定する

    Args:
        level: ログレベル（logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL）
    """
    global logger
    logger.setLevel(level)
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
            handler.setLevel(level)
    
    logger.info("Log level set to %s", logging.getLevelName(level))

# デバッグ環境の場合は、デバッグログを有効化する
def enable_debug_logging():
    """デバッグログを有効化する"""
    set_log_level(logging.DEBUG)

# エクスポートする関数とオブジェクト
__all__ = ['logger', 'initialize_file_logging', 'set_log_level', 'enable_debug_logging']
