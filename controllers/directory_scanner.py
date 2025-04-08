"""
効率的なディレクトリスキャンを行うワーカークラス

大量の画像ファイルを含むディレクトリを効率的に検索するための
最適化されたワーカークラスを提供します。
"""
import os
import time
from typing import List, Set, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot
from .workers import BaseWorker, CancellationError
from utils import logger, get_config

class DirectoryScannerWorker(BaseWorker):
    """
    ディレクトリ内の画像ファイルを効率的にスキャンするワーカークラス
    
    大量のファイルを含むディレクトリでも効率的に動作し、
    進捗状況を定期的に報告します。
    """
    def __init__(self, directory: str, image_extensions: Optional[List[str]] = None, 
                 batch_size: int = None, recursive: bool = True):
        """
        初期化
        
        Args:
            directory: スキャンするディレクトリのパス
            image_extensions: 対象とする画像ファイルの拡張子リスト（Noneの場合は設定から取得）
            batch_size: 進捗報告を行うバッチサイズ（Noneの場合は設定から取得）
            recursive: サブディレクトリを再帰的にスキャンするかどうか
        """
        worker_id = f"dir_scan_{os.path.basename(directory)}"
        super().__init__(worker_id)
        
        self.directory = directory
        self.recursive = recursive
        
        # 設定から値を取得
        config = get_config()
        if image_extensions is None:
            image_extensions = config.get_supported_extensions()
        if batch_size is None:
            batch_size = config.get("workers.batch_size", 100)
            
        self.image_extensions = image_extensions
        self.batch_size = batch_size
        
        # ファイル数などの統計情報
        self.total_files_scanned = 0
        self.total_images_found = 0
        self.total_directories_scanned = 0
        
        logger.debug(
            f"DirectoryScannerWorker初期化: directory={directory}, "
            f"extensions={image_extensions}, batch_size={batch_size}, recursive={recursive}"
        )
    
    def work(self) -> List[str]:
        """
        ディレクトリ内の画像ファイルをスキャン
        
        Returns:
            List[str]: 画像ファイルパスのリスト
            
        Raises:
            FileNotFoundError: ディレクトリが存在しない場合
            NotADirectoryError: 指定されたパスがディレクトリでない場合
            PermissionError: ディレクトリにアクセス権がない場合
            CancellationError: 処理がキャンセルされた場合
            OSError: その他のファイルシステムエラーが発生した場合
        """
        # ディレクトリの存在を確認
        if not os.path.exists(self.directory):
            logger.error(f"指定されたディレクトリが存在しません: {self.directory}")
            raise FileNotFoundError(f"ディレクトリが見つかりません: {self.directory}")
            
        if not os.path.isdir(self.directory):
            logger.error(f"指定されたパスはディレクトリではありません: {self.directory}")
            raise NotADirectoryError(f"ディレクトリではありません: {self.directory}")
            
        try:
            # アクセス権の確認
            os.listdir(self.directory)
        except PermissionError:
            logger.error(f"ディレクトリへのアクセス権がありません: {self.directory}")
            raise PermissionError(f"アクセス権限がありません: {self.directory}")
        
        logger.info(f"ディレクトリスキャンを開始: {self.directory}, 再帰={self.recursive}")
        self.update_progress(0, f"ディレクトリスキャンを開始: {self.directory}")
        
        start_time = time.time()
        image_files = []
        total_files_estimate = 0
        processed_files = 0
        
        try:
            # 対象ファイル数を概算（大規模ディレクトリでは完全なカウントは遅いため）
            self.update_progress(1, "ファイル数を概算中...")
            
            if self.recursive:
                for _, _, files in os.walk(self.directory):
                    self.check_cancelled()
                    total_files_estimate += len(files)
                    
                    # 非常に大きなディレクトリの場合は早めに抜ける
                    if total_files_estimate > 10000:
                        total_files_estimate = 10000  # 概算値として十分
                        break
            else:
                # 再帰的でない場合は、トップディレクトリのみのファイル数を取得
                total_files_estimate = len(os.listdir(self.directory))
            
            logger.debug(f"推定ファイル数: {total_files_estimate}")
            
            # スキャンの実行
            self.update_progress(2, f"ファイルスキャン中... 約 {total_files_estimate} ファイル")
            
            # バッチ処理でファイルを収集
            if self.recursive:
                # 再帰的なスキャン
                for root, dirs, files in os.walk(self.directory):
                    self.check_cancelled()
                    
                    self.total_directories_scanned += 1
                    batch = []
                    
                    for file in files:
                        self.check_cancelled()
                        
                        processed_files += 1
                        self.total_files_scanned += 1
                        
                        # 定期的に進捗を報告
                        if processed_files % self.batch_size == 0:
                            progress = min(95, int(100 * processed_files / max(1, total_files_estimate)))
                            self.update_progress(
                                progress, 
                                f"スキャン中: {processed_files}/{total_files_estimate} ファイル, {len(image_files)} 画像が見つかりました"
                            )
                        
                        # 拡張子をチェック
                        ext = os.path.splitext(file.lower())[1]
                        if ext in self.image_extensions:
                            image_path = os.path.join(root, file)
                            batch.append(image_path)
                            self.total_images_found += 1
                    
                    # バッチをリストに追加
                    image_files.extend(batch)
            else:
                # 非再帰的なスキャン（トップディレクトリのみ）
                files = [f for f in os.listdir(self.directory) 
                         if os.path.isfile(os.path.join(self.directory, f))]
                
                self.total_directories_scanned = 1
                batch = []
                
                for file in files:
                    self.check_cancelled()
                    
                    processed_files += 1
                    self.total_files_scanned += 1
                    
                    # 定期的に進捗を報告
                    if processed_files % self.batch_size == 0:
                        progress = min(95, int(100 * processed_files / max(1, len(files))))
                        self.update_progress(
                            progress, 
                            f"スキャン中: {processed_files}/{len(files)} ファイル, {len(image_files)} 画像が見つかりました"
                        )
                    
                    # 拡張子をチェック
                    ext = os.path.splitext(file.lower())[1]
                    if ext in self.image_extensions:
                        image_path = os.path.join(self.directory, file)
                        batch.append(image_path)
                        self.total_images_found += 1
                
                # バッチをリストに追加
                image_files.extend(batch)
            
            # 最終進捗を報告
            elapsed_time = time.time() - start_time
            logger.info(
                f"ディレクトリスキャン完了: {self.directory}, "
                f"画像ファイル数={len(image_files)}, "
                f"総ファイル数={self.total_files_scanned}, "
                f"ディレクトリ数={self.total_directories_scanned}, "
                f"所要時間={elapsed_time:.2f}秒"
            )
            
            self.update_progress(
                100, 
                f"スキャン完了: {len(image_files)} 画像ファイルが見つかりました"
            )
            
            # 結果を返す
            return image_files
            
        except CancellationError:
            # キャンセルの場合
            elapsed_time = time.time() - start_time
            logger.info(
                f"ディレクトリスキャンがキャンセルされました: {self.directory}, "
                f"画像ファイル数={len(image_files)}, "
                f"処理済みファイル数={processed_files}, "
                f"所要時間={elapsed_time:.2f}秒"
            )
            raise
            
        except Exception as e:
            # その他のエラーの場合
            elapsed_time = time.time() - start_time
            logger.error(
                f"ディレクトリスキャンエラー: {self.directory}, "
                f"エラー={str(e)}, "
                f"処理済みファイル数={processed_files}, "
                f"所要時間={elapsed_time:.2f}秒"
            )
            raise
    
    def get_stats(self) -> dict:
        """
        スキャンの統計情報を取得
        
        Returns:
            dict: 統計情報を含む辞書
        """
        return {
            "directory": self.directory,
            "recursive": self.recursive,
            "total_files_scanned": self.total_files_scanned,
            "total_images_found": self.total_images_found,
            "total_directories_scanned": self.total_directories_scanned,
            "image_extensions": self.image_extensions,
        }
