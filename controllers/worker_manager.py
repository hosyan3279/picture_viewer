"""
ワーカーマネージャーモジュール

マルチスレッド処理を管理するクラスを提供します。
"""
from typing import Dict, List, Optional, Any, Union
import time
import threading
from PySide6.QtCore import QThreadPool, QRunnable, QObject, Signal
from utils import logger, get_config

class WorkerManagerSignals(QObject):
    """ワーカーマネージャーからのシグナルを定義するクラス"""
    worker_started = Signal(str)  # ワーカーID
    worker_finished = Signal(str)  # ワーカーID
    worker_cancelled = Signal(str)  # ワーカーID
    all_workers_done = Signal()  # すべてのワーカーが完了したときに発行
    error_occurred = Signal(str, str)  # (worker_id, error_message)

class WorkerManager(QObject):
    """
    マルチスレッド処理を管理するクラス
    
    QThreadPoolを使用してQRunnableベースのワーカーを管理します。
    ワーカーの起動、停止、監視、およびリソース管理を行います。
    """
    
    def __init__(self, max_threads: int = None):
        """
        初期化
        
        Args:
            max_threads: 最大スレッド数（Noneの場合は設定またはシステムデフォルト値を使用）
        """
        super().__init__()
        
        # 設定から最大スレッド数を取得
        config = get_config()
        if max_threads is None:
            max_threads = config.get("workers.max_concurrent")
        
        # スレッドプールの取得と設定
        self.threadpool = QThreadPool.globalInstance()
        if max_threads is not None:
            ideal_thread_count = self.threadpool.maxThreadCount()
            # 設定された値とシステムデフォルト値の小さい方を使用
            if max_threads > 0:
                self.threadpool.setMaxThreadCount(min(max_threads, ideal_thread_count))
            logger.debug(f"スレッド数設定: {self.threadpool.maxThreadCount()} (システム推奨値: {ideal_thread_count})")
        
        # ワーカー管理用のデータ構造
        self.active_workers: Dict[str, QRunnable] = {}  # ワーカーID → ワーカーインスタンスのマッピング
        self.worker_start_times: Dict[str, float] = {}  # ワーカーID → 開始時間のマッピング
        self.mutex = threading.RLock()  # スレッドセーフな操作のためのロック
        
        # シグナルオブジェクト
        self.signals = WorkerManagerSignals()
        
        logger.info(f"WorkerManagerを初期化: スレッド数={self.threadpool.maxThreadCount()}")
    
    def start_worker(self, worker_id: str, worker: QRunnable, priority: int = 0) -> bool:
        """
        ワーカーを開始
        
        Args:
            worker_id: ワーカーの識別子
            worker: 実行するワーカー
            priority: 優先度 (値が大きいほど優先度が高い)
            
        Returns:
            bool: ワーカーの起動に成功した場合はTrue
        """
        try:
            with self.mutex:
                # 既存のワーカーをキャンセル（IDが重複している場合）
                if worker_id in self.active_workers:
                    logger.warning(f"同じIDのワーカーが既に実行中のため、キャンセルします: {worker_id}")
                    self.cancel_worker(worker_id)
                
                # キャンセル機能の確認
                if not hasattr(worker, 'cancel'):
                    logger.warning(f"ワーカー {worker_id} はcancel()メソッドを実装していません")
                
                # 新しいワーカーを登録して開始
                self.active_workers[worker_id] = worker
                self.worker_start_times[worker_id] = time.time()
                
                # ワーカーの開始をログ記録
                logger.debug(f"ワーカーを開始: {worker_id}, 優先度={priority}")
                
                # スレッドプールでワーカーを開始
                self.threadpool.start(worker, priority)
                
                # シグナルを発行
                self.signals.worker_started.emit(worker_id)
                
                return True
        
        except Exception as e:
            logger.error(f"ワーカー起動エラー ({worker_id}): {e}")
            self.signals.error_occurred.emit(worker_id, str(e))
            return False
    
    def cancel_worker(self, worker_id: str) -> bool:
        """
        ワーカーをキャンセル
        
        Args:
            worker_id: キャンセルするワーカーの識別子
            
        Returns:
            bool: キャンセル操作が成功した場合はTrue
        """
        try:
            with self.mutex:
                if worker_id in self.active_workers:
                    worker = self.active_workers[worker_id]
                    
                    # ワーカーのキャンセルを試行
                    cancelled = False
                    try:
                        # キャンセル機能が実装されているワーカーのみ
                        if hasattr(worker, 'cancel'):
                            worker.cancel()
                            cancelled = True
                        else:
                            logger.warning(f"ワーカー {worker_id} にcancel()メソッドがありません")
                    except Exception as e:
                        logger.error(f"ワーカーキャンセルエラー ({worker_id}): {e}")
                    
                    # 管理リストから削除
                    del self.active_workers[worker_id]
                    if worker_id in self.worker_start_times:
                        del self.worker_start_times[worker_id]
                    
                    # キャンセルをログ記録
                    logger.debug(f"ワーカーをキャンセル: {worker_id}, 成功={cancelled}")
                    
                    # シグナルを発行
                    self.signals.worker_cancelled.emit(worker_id)
                    
                    return cancelled
                else:
                    logger.debug(f"キャンセル対象のワーカーが見つかりません: {worker_id}")
                    return False
        
        except Exception as e:
            logger.error(f"ワーカーキャンセル処理エラー ({worker_id}): {e}")
            return False
    
    def cancel_all(self) -> int:
        """
        すべてのワーカーをキャンセル
        
        Returns:
            int: キャンセルされたワーカーの数
        """
        try:
            with self.mutex:
                worker_ids = list(self.active_workers.keys())
                cancelled_count = 0
                
                for worker_id in worker_ids:
                    if self.cancel_worker(worker_id):
                        cancelled_count += 1
                
                logger.info(f"すべてのワーカーをキャンセル: {cancelled_count}/{len(worker_ids)}")
                
                if cancelled_count == len(worker_ids) and len(worker_ids) > 0:
                    self.signals.all_workers_done.emit()
                
                return cancelled_count
        
        except Exception as e:
            logger.error(f"すべてのワーカーのキャンセル処理エラー: {e}")
            return 0
    
    def wait_for_all(self, timeout_ms: int = 30000) -> bool:
        """
        すべてのワーカーの完了を待機
        
        Args:
            timeout_ms: タイムアウト時間（ミリ秒）
            
        Returns:
            bool: タイムアウトせずにすべてのワーカーが完了した場合はTrue
        """
        try:
            logger.info(f"すべてのワーカーの完了を待機: タイムアウト={timeout_ms}ms")
            
            result = self.threadpool.waitForDone(timeout_ms)
            
            if result:
                logger.info("すべてのワーカーが完了しました")
                self.signals.all_workers_done.emit()
            else:
                remaining = len(self.active_workers)
                logger.warning(f"タイムアウト: {remaining}個のワーカーが未完了")
            
            return result
        
        except Exception as e:
            logger.error(f"ワーカー待機エラー: {e}")
            return False
    
    def get_active_workers_count(self) -> int:
        """
        現在アクティブなワーカーの数を取得
        
        Returns:
            int: アクティブなワーカーの数
        """
        with self.mutex:
            return len(self.active_workers)
    
    def is_worker_active(self, worker_id: str) -> bool:
        """
        指定されたワーカーがアクティブかどうかを確認
        
        Args:
            worker_id: 確認するワーカーの識別子
            
        Returns:
            bool: ワーカーがアクティブな場合はTrue
        """
        with self.mutex:
            return worker_id in self.active_workers
    
    def get_worker_info(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        ワーカーの情報を取得
        
        Args:
            worker_id: 情報を取得するワーカーの識別子
            
        Returns:
            Dict or None: ワーカーの情報、存在しない場合はNone
        """
        with self.mutex:
            if worker_id in self.active_workers:
                worker = self.active_workers[worker_id]
                start_time = self.worker_start_times.get(worker_id, 0)
                current_time = time.time()
                
                return {
                    'id': worker_id,
                    'worker': worker,
                    'start_time': start_time,
                    'elapsed_seconds': current_time - start_time,
                    'has_cancel': hasattr(worker, 'cancel')
                }
            
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """
        ワーカーマネージャーの状態情報を取得
        
        Returns:
            Dict: ワーカーマネージャーの状態情報
        """
        with self.mutex:
            active_count = len(self.active_workers)
            max_threads = self.threadpool.maxThreadCount()
            active_threads = self.threadpool.activeThreadCount()
            
            # ワーカーの実行時間情報を収集
            current_time = time.time()
            longest_running = 0
            total_running_time = 0
            
            for worker_id, start_time in self.worker_start_times.items():
                running_time = current_time - start_time
                total_running_time += running_time
                longest_running = max(longest_running, running_time)
            
            avg_running_time = total_running_time / max(1, active_count) if active_count > 0 else 0
            
            return {
                'active_workers': active_count,
                'max_threads': max_threads,
                'active_threads': active_threads,
                'longest_running_seconds': longest_running,
                'avg_running_seconds': avg_running_time,
                'worker_ids': list(self.active_workers.keys())
            }
    
    def mark_worker_finished(self, worker_id: str) -> None:
        """
        ワーカーを完了状態としてマーク（内部使用）
        
        Args:
            worker_id: 完了したワーカーの識別子
        """
        with self.mutex:
            if worker_id in self.active_workers:
                # ワーカーを管理リストから削除
                del self.active_workers[worker_id]
                if worker_id in self.worker_start_times:
                    del self.worker_start_times[worker_id]
                
                # 完了をログ記録
                logger.debug(f"ワーカーが完了: {worker_id}")
                
                # シグナルを発行
                self.signals.worker_finished.emit(worker_id)
                
                # すべてのワーカーが完了した場合にシグナルを発行
                if len(self.active_workers) == 0:
                    self.signals.all_workers_done.emit()
