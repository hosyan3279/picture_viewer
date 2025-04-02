"""
ワーカーマネージャーモジュール

マルチスレッド処理を管理するクラスを提供します。
"""
from PySide6.QtCore import QThreadPool

class WorkerManager:
    """
    マルチスレッド処理を管理するクラス
    
    QThreadPoolを使用してQRunnableベースのワーカーを管理します。
    """
    
    def __init__(self):
        """初期化"""
        self.threadpool = QThreadPool.globalInstance()
        self.active_workers = {}  # ワーカーID → ワーカーインスタンスのマッピング
    
    def start_worker(self, worker_id, worker):
        """
        ワーカーを開始
        
        Args:
            worker_id (str): ワーカーの識別子
            worker (QRunnable): 実行するワーカー
        """
        # 既存のワーカーをキャンセル（オプション）
        self.cancel_worker(worker_id)
        
        # 新しいワーカーを登録して開始
        self.active_workers[worker_id] = worker
        self.threadpool.start(worker)
    
    def cancel_worker(self, worker_id):
        """
        ワーカーをキャンセル
        
        Args:
            worker_id (str): キャンセルするワーカーの識別子
        """
        if worker_id in self.active_workers:
            worker = self.active_workers[worker_id]
            # キャンセル機能が実装されているワーカーのみ
            if hasattr(worker, 'cancel'):
                worker.cancel()
            del self.active_workers[worker_id]
    
    def cancel_all(self):
        """すべてのワーカーをキャンセル"""
        for worker_id in list(self.active_workers.keys()):
            self.cancel_worker(worker_id)
    
    def wait_for_all(self):
        """すべてのワーカーの完了を待機"""
        self.threadpool.waitForDone()
