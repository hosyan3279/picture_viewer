"""
メモリモニターモジュール

アプリケーションのメモリ使用状況を監視および最適化するためのユーティリティを提供します。
"""
import os
import gc
import psutil
from .logger import logger

class MemoryMonitor:
    """
    メモリ使用状況を監視し、最適化するためのクラス
    
    アプリケーションのメモリ使用状況を監視し、必要に応じて
    ガベージコレクションを実行するなどの最適化を行います。
    """
    
    def __init__(self, memory_threshold=80):
        """
        初期化
        
        Args:
            memory_threshold (int): メモリ使用率の閾値（%）
                この値を超えると最適化が実行される
        """
        self.memory_threshold = memory_threshold
        self.process = psutil.Process(os.getpid())
        logger.debug("MemoryMonitor initialized with threshold: %d%%", memory_threshold)
    
    def get_memory_usage(self):
        """
        現在のメモリ使用状況を取得
        
        Returns:
            dict: メモリ使用状況の情報
        """
        try:
            # プロセスのメモリ情報
            memory_info = self.process.memory_info()
            
            # システム全体のメモリ情報
            system_memory = psutil.virtual_memory()
            
            result = {
                'process_rss': memory_info.rss,  # プロセスの物理メモリ使用量（バイト）
                'process_vms': memory_info.vms,  # プロセスの仮想メモリ使用量（バイト）
                'process_percent': self.process.memory_percent(),  # プロセスのメモリ使用率（%）
                'system_total': system_memory.total,  # システム全体のメモリ量（バイト）
                'system_available': system_memory.available,  # システムの空きメモリ量（バイト）
                'system_percent': system_memory.percent,  # システムのメモリ使用率（%）
            }
            
            logger.debug(
                "Memory usage - Process: %.1f%%, System: %.1f%%", 
                result['process_percent'], 
                result['system_percent']
            )
            
            return result
        except Exception as e:
            logger.error("Error getting memory usage: %s", str(e))
            # 基本的な情報のみを含むフォールバック辞書を返す
            return {
                'process_rss': 0,
                'process_vms': 0,
                'process_percent': 0,
                'system_total': 0,
                'system_available': 0,
                'system_percent': 0,
            }
    
    def optimize_if_needed(self):
        """
        必要に応じてメモリ最適化を実行
        
        Returns:
            bool: 最適化が実行された場合True
        """
        memory_usage = self.get_memory_usage()
        
        # メモリ使用率が閾値を超えている場合
        if memory_usage['process_percent'] > self.memory_threshold:
            logger.info(
                "Memory usage exceeds threshold (%.1f%% > %d%%). Optimizing memory...",
                memory_usage['process_percent'],
                self.memory_threshold
            )
            self.optimize_memory()
            return True
        
        return False
    
    def optimize_memory(self):
        """
        メモリ最適化を実行
        """
        logger.debug("Starting memory optimization")
        
        # 最適化前のメモリ使用量を記録
        before = self.get_memory_usage()['process_rss']
        
        # 未使用オブジェクトのガベージコレクションを実行
        collected = gc.collect()
        logger.debug("Garbage collection completed: %d objects collected", collected)
        
        # 最適化後のメモリ使用量を記録
        after = self.get_memory_usage()['process_rss']
        saved = before - after if before > after else 0
        
        logger.info(
            "Memory optimization completed. Saved: %s", 
            self.format_memory_size(saved)
        )
        
        # キャッシュのクリアなど、他の最適化処理をここに実装可能
    
    def format_memory_size(self, size_bytes):
        """
        メモリサイズを読みやすい形式に変換
        
        Args:
            size_bytes (int): バイト単位のサイズ
            
        Returns:
            str: 読みやすい形式のサイズ文字列
        """
        try:
            # バイト → キロバイト → メガバイト → ギガバイト
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024.0 or unit == 'TB':
                    break
                size_bytes /= 1024.0
            
            return f"{size_bytes:.2f} {unit}"
        except Exception as e:
            logger.error("Error formatting memory size: %s", str(e))
            return f"{size_bytes} B"
    
    def get_formatted_memory_info(self):
        """
        読みやすい形式のメモリ情報を取得
        
        Returns:
            dict: 整形されたメモリ情報
        """
        try:
            memory_usage = self.get_memory_usage()
            
            result = {
                'process_memory': self.format_memory_size(memory_usage['process_rss']),
                'process_percent': f"{memory_usage['process_percent']:.1f}%",
                'system_memory': f"{self.format_memory_size(memory_usage['system_available'])} / {self.format_memory_size(memory_usage['system_total'])}",
                'system_percent': f"{memory_usage['system_percent']:.1f}%",
            }
            
            logger.debug("Formatted memory info: %s", result)
            return result
        except Exception as e:
            logger.error("Error getting formatted memory info: %s", str(e))
            return {
                'process_memory': 'N/A',
                'process_percent': 'N/A',
                'system_memory': 'N/A',
                'system_percent': 'N/A',
            }
