"""
ワーカーモジュール

バックグラウンド処理を行うワーカークラスを提供します。
"""
import os
import time
import traceback
from typing import List, Dict, Tuple, Optional, Any, Union, TypeVar, Generic

from PySide6.QtCore import QObject, Signal, Slot, QRunnable, Qt
from PySide6.QtGui import QPixmap

from utils import logger, get_config

# 汎用型変数（戻り値型用）
T = TypeVar('T')

class WorkerSignals(QObject, Generic[T]):
    """
    ワーカーが発行するシグナルを定義するクラス
    
    QRunnableはQObjectを継承していないため、このクラスを通じてシグナルを発行します。
    型パラメータTを使用して、ワーカーの結果型を指定できます。
    """
    started = Signal()  # ワーカーが開始された
    finished = Signal()  # ワーカーが終了した（成功でもエラーでも）
    cancelled = Signal()  # ワーカーがキャンセルされた
    error = Signal(str)  # エラーメッセージ
    result = Signal(object)  # 処理結果 (型Tのオブジェクト)
    progress = Signal(int)  # 進捗率 (0-100)
    progress_status = Signal(str)  # 進捗状況の説明
    
class BaseWorker(QRunnable):
    """
    基本ワーカークラス
    
    すべてのワーカークラスの基底クラスとして使用します。
    処理のキャンセル、進捗報告、エラー処理などの共通機能を提供します。
    """
    
    def __init__(self, worker_id: Optional[str] = None):
        """
        初期化
        
        Args:
            worker_id: ワーカーの識別子（省略時は自動生成）
        """
        super().__init__()
        self.signals = WorkerSignals()
        self.is_cancelled = False
        self.start_time = 0
        self.worker_id = worker_id or f"worker_{id(self)}"
        self.last_progress = 0
        self.last_progress_time = 0
        
        # 設定からタイムアウト値を取得
        config = get_config()
        self.progress_update_interval = config.get("workers.progress_update_interval_ms", 500) / 1000  # 秒単位に変換
    
    def cancel(self) -> bool:
        """
        処理をキャンセル
        
        Returns:
            bool: キャンセルフラグが設定された場合はTrue
        """
        logger.debug(f"ワーカーのキャンセルが要求されました: {self.worker_id}")
        
        if self.is_cancelled:
            # 既にキャンセル済み
            return False
            
        self.is_cancelled = True
        self.signals.cancelled.emit()
        return True
    
    def check_cancelled(self) -> bool:
        """
        キャンセル状態をチェックし、キャンセルされていた場合は例外を発生させる
        
        Returns:
            bool: キャンセルされていない場合はTrue
            
        Raises:
            CancellationError: キャンセルされた場合
        """
        if self.is_cancelled:
            logger.debug(f"ワーカー {self.worker_id} の処理がキャンセルされました")
            raise CancellationError("処理がキャンセルされました")
        return True
    
    def update_progress(self, progress: int, status: Optional[str] = None) -> None:
        """
        進捗状況を更新
        
        Args:
            progress: 進捗率（0-100）
            status: 状態の説明（オプション）
        """
        # 前回の更新から時間が経っていない場合は更新しない（UI更新の頻度制限）
        current_time = time.time()
        if (progress != 100 and  # 100%の場合は常に更新
            progress - self.last_progress < 5 and  # 5%以上変化した場合は更新
            current_time - self.last_progress_time < self.progress_update_interval):  # 一定時間経過していない
            return
            
        # 進捗値を有効範囲に正規化
        progress = max(0, min(100, progress))
        
        # 進捗シグナルを発行
        self.signals.progress.emit(progress)
        if status:
            self.signals.progress_status.emit(status)
            
        # 最後の更新時間と進捗を記録
        self.last_progress = progress
        self.last_progress_time = current_time
    
    @Slot()
    def run(self) -> None:
        """ワーカーの実行"""
        self.start_time = time.time()
        logger.debug(f"ワーカー {self.worker_id} を開始")
        
        try:
            # 開始シグナルを発行
            self.signals.started.emit()
            
            # キャンセルフラグをチェック
            if self.is_cancelled:
                logger.debug(f"ワーカー {self.worker_id} は開始前にキャンセルされました")
                return
                
            # 実際の処理を実行
            result = self.work()
            
            # キャンセルフラグをチェック（結果を返す前）
            if not self.is_cancelled:
                # 結果シグナルを発行
                self.signals.result.emit(result)
                logger.debug(f"ワーカー {self.worker_id} が結果を返しました")
            
        except CancellationError as ce:
            # キャンセルによる終了（エラーとしては扱わない）
            logger.debug(f"ワーカー {self.worker_id} はキャンセルにより終了: {ce}")
            
        except Exception as e:
            # その他の例外
            error_msg = str(e)
            logger.error(f"ワーカー {self.worker_id} でエラーが発生: {error_msg}")
            logger.debug(f"エラーの詳細: {traceback.format_exc()}")
            
            if not self.is_cancelled:
                self.signals.error.emit(error_msg)
                
        finally:
            # 処理時間を計算
            elapsed = time.time() - self.start_time
            logger.debug(f"ワーカー {self.worker_id} が終了: 処理時間={elapsed:.2f}秒")
            
            # 終了シグナルを発行
            self.signals.finished.emit()
    
    def work(self) -> Any:
        """
        実際の処理を行うメソッド
        
        このメソッドはサブクラスでオーバーライドする必要があります。
        処理中は定期的に check_cancelled() を呼び出して、キャンセル要求をチェックしてください。
        
        Returns:
            任意の型のオブジェクト（サブクラスでの実装による）
            
        Raises:
            NotImplementedError: オーバーライドされていない場合
        """
        raise NotImplementedError("work メソッドをサブクラスで実装する必要があります")


class CancellationError(Exception):
    """ワーカーのキャンセルを示す例外"""
    pass


class FolderScanWorker(BaseWorker):
    """
    フォルダ内の画像ファイルをスキャンするワーカー
    
    指定されたフォルダとそのサブフォルダ内の画像ファイルを検索し、
    そのパスのリストを返します。
    """
    
    def __init__(self, folder_path: str, worker_id: Optional[str] = None):
        """
        初期化
        
        Args:
            folder_path: スキャンするフォルダのパス
            worker_id: ワーカーの識別子（オプション）
        """
        super().__init__(worker_id or f"folder_scan_{os.path.basename(folder_path)}")
        self.folder_path = folder_path
        
        # 設定から対象とする画像拡張子を取得
        config = get_config()
        self.image_extensions = config.get("app.image_extensions", 
                                          ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'])
        
        logger.debug(f"FolderScanWorkerを初期化: path={folder_path}, extensions={self.image_extensions}")
    
    def work(self) -> List[str]:
        """
        フォルダ内の画像ファイルをスキャン
        
        進捗状況を定期的に更新し、キャンセル要求をチェックします。
        
        Returns:
            List[str]: 画像ファイルのパスのリスト
        """
        if not os.path.exists(self.folder_path):
            logger.error(f"指定されたフォルダが存在しません: {self.folder_path}")
            raise FileNotFoundError(f"フォルダが見つかりません: {self.folder_path}")
        
        if not os.path.isdir(self.folder_path):
            logger.error(f"指定されたパスはフォルダではありません: {self.folder_path}")
            raise NotADirectoryError(f"フォルダではありません: {self.folder_path}")
        
        logger.info(f"フォルダ {self.folder_path} のスキャンを開始")
        self.update_progress(0, f"フォルダをスキャン中: {self.folder_path}")
        
        # 画像ファイルの検索
        image_files = []
        total_files_checked = 0
        last_progress_update = time.time()
        
        try:
            # まず、ファイル数を概算（大規模ディレクトリでは完全なカウントは時間がかかる）
            total_files_estimated = 0
            for _, _, files in os.walk(self.folder_path):
                self.check_cancelled()
                total_files_estimated += len(files)
                # 非常に大きなディレクトリの場合は早めに打ち切る
                if total_files_estimated > 10000:
                    break
            
            logger.debug(f"推定ファイル数: {total_files_estimated}")
            
            # 実際のスキャン
            for root, _, files in os.walk(self.folder_path):
                self.check_cancelled()
                
                for file in files:
                    self.check_cancelled()
                    total_files_checked += 1
                    
                    # 拡張子をチェック
                    ext = os.path.splitext(file.lower())[1]
                    if ext in self.image_extensions:
                        image_path = os.path.join(root, file)
                        image_files.append(image_path)
                    
                    # 進捗を定期的に更新
                    current_time = time.time()
                    if current_time - last_progress_update >= 0.5 or total_files_checked % 100 == 0:
                        progress = min(95, int(100 * total_files_checked / max(1, total_files_estimated)))
                        self.update_progress(
                            progress, 
                            f"{len(image_files)}個の画像を発見 ({total_files_checked}ファイルを確認)"
                        )
                        last_progress_update = current_time
            
            # 完了
            self.update_progress(100, f"{len(image_files)}個の画像を発見")
            logger.info(f"フォルダスキャン完了: {len(image_files)}個の画像ファイル / {total_files_checked}個のファイルを確認")
            
            return image_files
            
        except CancellationError:
            logger.info(f"フォルダスキャンがキャンセルされました: {len(image_files)}個の画像が見つかっています")
            raise
            
        except Exception as e:
            logger.error(f"フォルダスキャン中にエラーが発生: {e}")
            raise


class ThumbnailWorker(BaseWorker):
    """
    サムネイル画像を生成するワーカー
    
    指定された画像からサムネイルを生成し、オプションでキャッシュに保存します。
    """
    
    def __init__(self, image_path: str, size: Tuple[int, int], 
                 thumbnail_cache: Optional[Any] = None, 
                 worker_id: Optional[str] = None):
        """
        初期化
        
        Args:
            image_path: 原画像のパス
            size: 生成するサムネイルのサイズ (width, height)
            thumbnail_cache: サムネイルキャッシュ（オプション）
            worker_id: ワーカーの識別子（オプション）
        """
        super().__init__(worker_id or f"thumbnail_{os.path.basename(image_path)}")
        self.image_path = image_path
        self.size = size
        self.thumbnail_cache = thumbnail_cache
        logger.debug(f"ThumbnailWorkerを初期化: path={image_path}, size={size}")
    
    def work(self) -> Tuple[str, QPixmap]:
        """
        サムネイルを生成
        
        キャンセル要求をチェックしながら、画像からサムネイルを生成します。
        キャッシュが指定されている場合は、まずキャッシュをチェックし、
        生成後にキャッシュに保存します。
        
        Returns:
            Tuple[str, QPixmap]: 画像パスとサムネイル画像のタプル
        """
        try:
            # キャンセル要求をチェック
            self.check_cancelled()
            
            # キャッシュをチェック
            cached_thumbnail = None
            if self.thumbnail_cache:
                self.update_progress(10, "キャッシュをチェック中")
                cached_thumbnail = self.thumbnail_cache.get_thumbnail(self.image_path, self.size)
                
                if cached_thumbnail:
                    logger.debug(f"キャッシュヒット: {self.image_path}")
                    self.update_progress(100, "キャッシュから読み込み完了")
                    return (self.image_path, cached_thumbnail)
            
            # ファイルの存在を確認
            if not os.path.exists(self.image_path):
                logger.error(f"画像ファイルが存在しません: {self.image_path}")
                raise FileNotFoundError(f"画像ファイルが見つかりません: {self.image_path}")
            
            # サムネイルの生成
            self.update_progress(20, "画像を読み込み中")
            pixmap = QPixmap(self.image_path)
            if pixmap.isNull():
                logger.error(f"画像を読み込めません: {self.image_path}")
                raise ValueError(f"画像を読み込めません: {self.image_path}")
            
            self.check_cancelled()
            
            # リサイズ
            self.update_progress(50, "サムネイルを生成中")
            thumbnail = pixmap.scaled(
                self.size[0], self.size[1],
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            self.check_cancelled()
            
            # キャッシュに保存
            if self.thumbnail_cache:
                self.update_progress(80, "キャッシュに保存中")
                self.thumbnail_cache.store_thumbnail(self.image_path, self.size, thumbnail)
            
            self.update_progress(100, "サムネイル生成完了")
            
            logger.debug(f"サムネイル生成完了: {self.image_path}, サイズ={thumbnail.size()}")
            return (self.image_path, thumbnail)
            
        except CancellationError:
            logger.info(f"サムネイル生成がキャンセルされました: {self.image_path}")
            raise
            
        except Exception as e:
            logger.error(f"サムネイル生成中にエラーが発生: {self.image_path} - {e}")
            raise
