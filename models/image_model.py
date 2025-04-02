# --- START OF FILE image_model.py ---

"""
画像モデルモジュール

画像データとメタデータを管理するモデルクラスを提供します。
"""
from PySide6.QtCore import QObject, Signal

class ImageModel(QObject):
    """
    画像データとメタデータを管理するモデルクラス

    画像ファイルパスとそれに関連するメタデータを保持し、
    データが変更されたときに通知するシグナルを発行します。
    """
    data_changed = Signal()

    def __init__(self):
        """初期化"""
        super().__init__()
        self.images = []  # 画像パスのリスト
        self.metadata = {}  # 画像パスをキーとしたメタデータ辞書

    def add_image(self, image_path, metadata=None):
        """
        画像をモデルに追加 (シグナル発行なし)

        Args:
            image_path (str): 画像ファイルへのパス
            metadata (dict, optional): 画像に関連するメタデータ
        """
        if image_path not in self.images:
            self.images.append(image_path)
            self.metadata[image_path] = metadata or {}
            # self.data_changed.emit() # ここでは発行しない

    def add_images_batch(self, image_paths, metadatas=None):
        """
        複数の画像をモデルに一括で追加し、最後にシグナルを発行

        Args:
            image_paths (list): 画像ファイルパスのリスト
            metadatas (list, optional): 各画像に対応するメタデータのリスト (辞書)。省略した場合は空辞書。
        """
        added_new = False
        num_paths = len(image_paths)

        if metadatas is None:
            metadatas = [{} for _ in range(num_paths)]
        elif len(metadatas) != num_paths:
            raise ValueError("image_pathsとmetadatasの数が一致しません")

        current_image_set = set(self.images) # 高速な存在チェックのためセットを使用

        new_images = []
        new_metadata = {}

        for i, image_path in enumerate(image_paths):
            if image_path not in current_image_set:
                new_images.append(image_path)
                new_metadata[image_path] = metadatas[i] or {}
                added_new = True

        if added_new:
            self.images.extend(new_images)
            self.metadata.update(new_metadata)
            print(f"DEBUG: Emitting data_changed after adding {len(new_images)} images.")
            self.data_changed.emit() # バッチ処理後に一度だけ発行

    def clear(self):
        """すべての画像データをクリア"""
        if self.images or self.metadata: # 変更があった場合のみシグナルを発行
            self.images.clear()
            self.metadata.clear()
            print("DEBUG: Emitting data_changed after clear.")
            self.data_changed.emit()

    def image_count(self):
        """画像の総数を取得"""
        return len(self.images)

    def get_image_at(self, index):
        """
        指定されたインデックスの画像パスを取得

        Args:
            index (int): 画像のインデックス

        Returns:
            str or None: 画像のパス。インデックスが範囲外の場合はNone
        """
        if 0 <= index < len(self.images):
            return self.images[index]
        return None

    def get_metadata(self, image_path):
        """
        画像のメタデータを取得

        Args:
            image_path (str): 画像のパス

        Returns:
            dict: 画像のメタデータ。画像が存在しない場合は空辞書
        """
        return self.metadata.get(image_path, {})

    def get_images_batch(self, start, count):
        """
        画像のバッチを取得

        Args:
            start (int): 開始インデックス
            count (int): 取得する画像の数

        Returns:
            list: 指定範囲の画像パスのリスト
        """
        end = min(start + count, len(self.images))
        if start < 0: start = 0
        return self.images[start:end]
# --- END OF FILE image_model.py ---