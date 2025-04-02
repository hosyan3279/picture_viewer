"""
効率的なディレクトリスキャンを行うワーカークラス

大量の画像ファイルを含むディレクトリを効率的に検索するための
最適化されたワーカークラスを提供します。
"""
import os
from PySide6.QtCore import QObject, Signal, Slot
from .workers import BaseWorker

class DirectoryScannerWorker(BaseWorker):
    """
    ディレクトリ内の画像ファイルを効率的にスキャンするワーカークラス
    
    大量のファイルを含むディレクトリでも効率的に動作し、
    進捗状況を定期的に報告します。
    """
    def __init__(self, directory, image_extensions=['.jpg', '.jpeg', '.png', '.gif', '.bmp'], batch_size=100):
        """
        初期化
        
        Args:
            directory (str): スキャンするディレクトリのパス
            image_extensions (list): 対象とする画像ファイルの拡張子リスト
            batch_size (int): 進捗報告を行うバッチサイズ
        """
        super().__init__()
        self.directory = directory
        self.image_extensions = image_extensions
        self.batch_size = batch_size
    
    def work(self):
        """
        ディレクトリ内の画像ファイルをスキャン
        
        Returns:
            list: 画像ファイルパスのリスト
        """
        image_files = []
        total_files = 0
        processed_files = 0
        
        # まず対象ファイル数を概算（大規模ディレクトリでは完全なカウントは遅いため）
        for _, _, files in os.walk(self.directory):
            total_files += len(files)
            # 非常に大きなディレクトリの場合は早めに抜ける
            if total_files > 10000:
                total_files = 10000  # 概算値として十分
                break
        
        # バッチ処理でファイルを収集
        for root, _, files in os.walk(self.directory):
            if self.is_cancelled:
                break
                
            batch = []
            for file in files:
                if self.is_cancelled:
                    break
                    
                processed_files += 1
                
                # batch_sizeファイルごとに進捗を報告
                if processed_files % self.batch_size == 0:
                    progress = int(min(100, 100 * processed_files / max(1, total_files)))
                    self.signals.progress.emit(progress)
                
                # 拡張子をチェック
                ext = os.path.splitext(file.lower())[1]
                if ext in self.image_extensions:
                    image_path = os.path.join(root, file)
                    batch.append(image_path)
            
            # バッチをリストに追加
            image_files.extend(batch)
        
        # 最終進捗を100%に設定
        self.signals.progress.emit(100)
        
        # 結果を返す
        return image_files
