"""
フローレイアウトモジュール

アイテムを左から右、そして上から下へと自然に「流れる」ように配置する
カスタムレイアウトクラスを提供します。
"""
from PySide6.QtCore import Qt, QSize, QRect, QPoint
from PySide6.QtWidgets import QLayout, QLayoutItem, QStyle
from PySide6.QtWidgets import QSizePolicy


class FlowLayout(QLayout):
    """
    フローレイアウトクラス
    
    アイテムを左から右、そして上から下へと自然に「流れる」ように配置します。
    画像ギャラリーなど、サイズが均一で数が変動するアイテムの配置に適しています。
    """
    
    def __init__(self, parent=None, margin=0, spacing=-1):
        """
        初期化
        
        Args:
            parent: 親ウィジェット
            margin: マージン
            spacing: アイテム間のスペース
        """
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing if spacing >= 0 else 4)
        
        self._item_list = []
    
    def __del__(self):
        """デストラクタ"""
        # 残りのアイテムをクリア
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)
    
    def addItem(self, item):
        """
        アイテムをレイアウトに追加
        
        Args:
            item (QLayoutItem): 追加するレイアウトアイテム
        """
        self._item_list.append(item)
    
    def count(self):
        """
        レイアウト内のアイテム数を取得
        
        Returns:
            int: アイテム数
        """
        return len(self._item_list)
    
    def itemAt(self, index):
        """
        指定インデックスのアイテムを取得
        
        Args:
            index (int): アイテムのインデックス
            
        Returns:
            QLayoutItem or None: 指定インデックスのアイテム
        """
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None
    
    def takeAt(self, index):
        """
        指定インデックスのアイテムを削除して取得
        
        Args:
            index (int): アイテムのインデックス
            
        Returns:
            QLayoutItem or None: 削除されたアイテム
        """
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None
    
    def expandingDirections(self):
        """
        レイアウトの拡張方向を取得
        
        Returns:
            Qt.Orientations: 拡張方向
        """
        return Qt.Orientations(0)  # 拡張なし
    
    def hasHeightForWidth(self):
        """
        幅に基づく高さを持つかどうかを判定
        
        Returns:
            bool: 常にTrue
        """
        return True
    
    def heightForWidth(self, width):
        """
        指定幅に対する高さを計算
        
        Args:
            width (int): 幅
            
        Returns:
            int: 必要な高さ
        """
        return self._do_layout(QRect(0, 0, width, 0), True)
    
    def setGeometry(self, rect):
        """
        レイアウトのジオメトリを設定
        
        Args:
            rect (QRect): 設定するジオメトリ
        """
        super().setGeometry(rect)
        self._do_layout(rect, False)
    
    def sizeHint(self):
        """
        レイアウトのサイズヒントを取得
        
        Returns:
            QSize: サイズヒント
        """
        return self.minimumSize()
    
    def minimumSize(self):
        """
        レイアウトの最小サイズを計算
        
        Returns:
            QSize: 最小サイズ
        """
        size = QSize()
        
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
            
        margin = self.contentsMargins()
        size += QSize(margin.left() + margin.right(), margin.top() + margin.bottom())
        
        return size
    
    def _do_layout(self, rect, test_only=False):
        """
        実際のレイアウト処理を行う
        
        Args:
            rect (QRect): レイアウト領域
            test_only (bool): サイズ計算のみかどうか
            
        Returns:
            int: 使用した高さ
        """
        margin = self.contentsMargins()
        x = rect.x() + margin.left()
        y = rect.y() + margin.top()
        line_height = 0
        spacing = self.spacing()
        
        for item in self._item_list:
            style = item.widget().style() if item.widget() else None
            
            # レイアウトのスペースを計算


# そして _do_layout メソッド内の部分を以下のように修正：
            layout_spacing_x = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton,  # QStyle.ControlType ではなく QSizePolicy.ControlType
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Horizontal
            ) if style else spacing

            layout_spacing_y = style.layoutSpacing(
                QSizePolicy.ControlType.PushButton,
                QSizePolicy.ControlType.PushButton,
                Qt.Orientation.Vertical
            ) if style else spacing
            
            space_x = layout_spacing_x if spacing == -1 else spacing
            space_y = layout_spacing_y if spacing == -1 else spacing
            
            next_x = x + item.sizeHint().width() + space_x
            
            # 次のアイテムが行に収まるかチェック
            if next_x - space_x > rect.right() - margin.right() and line_height > 0:
                # 新しい行に移動
                x = rect.x() + margin.left()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            
            # アイテムのジオメトリを設定
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            
            # 行の高さを更新
            line_height = max(line_height, item.sizeHint().height())
            
            # X座標を更新
            x = next_x
        
        # 使用した高さを返す
        return y + line_height - rect.y() + margin.bottom()
