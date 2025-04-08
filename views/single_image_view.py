# --- START OF FILE views/single_image_view.py ---

"""
シングル画像表示ビューモジュール

選択された画像を MainWindow 内に表示し、基本的な操作（ズーム、パン、回転、ナビゲーション、スライドショー）を行うための
ウィジェットを提供します。
"""
import os
import random
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QToolBar, QSizePolicy, QLabel, QStatusBar, QPushButton, QStyle,
    QSpinBox, QWidgetAction
)
from PySide6.QtGui import QPixmap, QAction, QIcon, QKeyEvent, QWheelEvent, QPainter, QTransform, QKeySequence
from PySide6.QtCore import Qt, Signal, Slot, QRectF, QTimer

from models.image_model import ImageModel
from utils import logger, get_config

class SingleImageView(QWidget):
    """画像を MainWindow 内に表示するためのウィジェット"""
    back_requested = Signal()
    fullscreen_toggled = Signal(bool)

    # スライドショーモード定数
    MODE_ORDER = "order"
    MODE_RANDOM = "random"

    def __init__(self, image_model: ImageModel, parent=None):
        """
        初期化

        Args:
            image_model (ImageModel): 画像リストを持つモデル
            parent (QWidget, optional): 親ウィジェット
        """
        super().__init__(parent)
        self.image_model = image_model
        self.current_index = -1 # 初期インデックスは未設定状態
        self.config = get_config()
        self.pixmap_item: QGraphicsPixmapItem = None
        self.scene: QGraphicsScene = None
        self.view: QGraphicsView = None
        self.current_rotation = 0.0

        # --- スライドショー関連の初期化 ---
        self.is_slideshow_running = False
        # 設定からデフォルト値を取得 (なければデフォルト5秒)
        default_interval_sec = self.config.get("slideshow.default_interval_sec", 5)
        self.slideshow_interval_ms = default_interval_sec * 1000
        # 設定からデフォルトモードを取得 (なければ順序)
        self.slideshow_mode = self.config.get("slideshow.default_mode", self.MODE_ORDER)

        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.timeout.connect(self._show_next_slide)
        self.slideshow_timer.setInterval(self.slideshow_interval_ms)

        # --- UI設定 ---
        self._setup_ui()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _setup_ui(self):
        """UIコンポーネントを設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- ツールバー ---
        self.toolbar = QToolBar("画像操作")
        self._setup_toolbar()
        layout.addWidget(self.toolbar)

        # --- グラフィックビュー ---
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # パンを有効化
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setStyleSheet("border: none; background-color: #333;") # 背景色を暗く
        layout.addWidget(self.view)

        # --- ステータスバー (ファイル名表示用) ---
        self.status_bar = QStatusBar()
        self.status_label = QLabel("")
        self.status_bar.addPermanentWidget(self.status_label)
        layout.addWidget(self.status_bar)

    def _setup_toolbar(self):
        """ツールバーのアクションを設定"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # アイコンファイルのあるディレクトリへのパス (プロジェクト構造に合わせて調整)
        icon_dir = os.path.join(script_dir, "..", "resources", "icons")
        logger.debug(f"Icon directory path: {icon_dir}") # パス確認用ログ

        # --- ギャラリーへ戻る ---
        back_icon_path = os.path.join(icon_dir, "gallery.svg") # アイコンファイル名
        back_action = QAction(QIcon(back_icon_path), "ギャラリーへ戻る", self)
        back_action.triggered.connect(self.back_requested.emit)

        self.toolbar.addAction(back_action)
        self.toolbar.addSeparator()

        # --- ナビゲーション ---
        prev_icon_path = os.path.join(icon_dir, "arrow-left.svg")
        self.prev_action = QAction(QIcon(prev_icon_path), "前へ", self)
        self.prev_action.triggered.connect(self.show_previous_image)
        self.prev_action.setShortcut(Qt.Key.Key_Left)
        self.prev_action.setShortcut(Qt.Key.Key_A)
        self.prev_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        self.prev_action.setToolTip("前の画像を表示します (← or A)")
        self.toolbar.addAction(self.prev_action)

        next_icon_path = os.path.join(icon_dir, "arrow-right.svg")
        self.next_action = QAction(QIcon(next_icon_path), "次へ", self)
        self.next_action.triggered.connect(self.show_next_image)
        self.next_action.setShortcut(Qt.Key.Key_Right)
        self.next_action.setShortcut(Qt.Key.Key_D)
        self.next_action.setToolTip("次の画像を表示します (→ or D)")
        self.next_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        self.toolbar.addAction(self.next_action)

        self.toolbar.addSeparator()

        # --- スライドショー ---
        slideshow_play_icon_path = os.path.join(icon_dir, "play.svg") # 再生アイコン
        # アクションをメンバ変数として保持
        self.slideshow_action = QAction(QIcon(slideshow_play_icon_path), "スライドショー開始", self)
        self.slideshow_action.setCheckable(True)
        self.slideshow_action.toggled.connect(self.toggle_slideshow)
        self.slideshow_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        self.toolbar.addAction(self.slideshow_action)

        # モード切り替えアクション
        mode_order_icon_path = os.path.join(icon_dir, "loop-square.svg") # 順序アイコン例
        self.slideshow_mode_action = QAction(QIcon(mode_order_icon_path), "順序再生", self)
        self.slideshow_mode_action.setToolTip("クリックして再生モード切替 (順序/ランダム)")
        self.slideshow_mode_action.triggered.connect(self.toggle_slideshow_mode)
        self.toolbar.addAction(self.slideshow_mode_action)
        self._update_slideshow_mode_action() # 初期アイコンとテキスト設定

        # 間隔設定スピンボックス
        interval_label = QLabel(" 間隔(秒): ")
        self.toolbar.addWidget(interval_label) # ラベル追加
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(1, 60) # 1秒から60秒
        self.interval_spinbox.setValue(self.slideshow_interval_ms // 1000)
        self.interval_spinbox.setSuffix(" 秒")
        self.interval_spinbox.valueChanged.connect(self.change_slideshow_interval)
        self.toolbar.addWidget(self.interval_spinbox) # スピンボックス追加

        self.toolbar.addSeparator()

        # --- ズーム ---
        zoom_in_icon_path = os.path.join(icon_dir, "plus-small.svg") # アイコンファイル名
        zoom_in_action = QAction(QIcon(zoom_in_icon_path), "拡大", self)
        zoom_in_action.triggered.connect(self.zoom_in)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        zoom_in_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        zoom_in_action.setToolTip("画像を拡大します (Ctrl + +)")
        self.toolbar.addAction(zoom_in_action)

        zoom_out_icon_path = os.path.join(icon_dir, "minus-small.svg") # アイコンファイル名
        zoom_out_action = QAction(QIcon(zoom_out_icon_path), "縮小", self)
        zoom_out_action.triggered.connect(self.zoom_out)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        zoom_out_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        zoom_out_action.setToolTip("画像を縮小します (Ctrl + -)")
        self.toolbar.addAction(zoom_out_action)

        zoom_fit_icon_path = os.path.join(icon_dir, "broken-image.svg") # アイコンファイル名 (変更推奨)
        zoom_fit_action = QAction(QIcon(zoom_fit_icon_path), "全体表示", self)
        zoom_fit_action.triggered.connect(self.fit_to_view)
        zoom_fit_action.setShortcut(Qt.Key.Key_F)
        zoom_fit_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_fit_action.setToolTip("画像を全体表示します (F)")
        self.toolbar.addAction(zoom_fit_action)

        zoom_original_icon_path = os.path.join(icon_dir, "desktop-wallpaper.svg") # アイコンファイル名 (変更推奨)
        zoom_original_action = QAction(QIcon(zoom_original_icon_path), "等倍表示", self)
        zoom_original_action.triggered.connect(self.zoom_original)
        zoom_original_action.setShortcut(Qt.Key.Key_0)
        zoom_original_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_original_action.setToolTip("画像を等倍表示します (0)")
        self.toolbar.addAction(zoom_original_action)

        self.toolbar.addSeparator()

        # --- 回転 ---
        rotate_left_icon_path = os.path.join(icon_dir, "rotate-left.svg") # アイコンファイル名
        rotate_left_action = QAction(QIcon(rotate_left_icon_path), "左回転", self)
        rotate_left_action.triggered.connect(self.rotate_left)
        rotate_left_action.setShortcut(Qt.Key.Key_L)
        rotate_left_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        rotate_left_action.setToolTip("画像を左に90度回転します (L)")
        self.toolbar.addAction(rotate_left_action)

        rotate_right_icon_path = os.path.join(icon_dir, "rotate-right.svg") # アイコンファイル名
        rotate_right_action = QAction(QIcon(rotate_right_icon_path), "右回転", self)
        rotate_right_action.triggered.connect(self.rotate_right)
        rotate_right_action.setShortcut(Qt.Key.Key_R)
        rotate_right_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut) # <<<--- コンテキスト設定
        rotate_right_action.setToolTip("画像を右に90度回転します (R)")
        self.toolbar.addAction(rotate_right_action)

        self.toolbar.addSeparator()

        # --- フルスクリーン ---
        fullscreen_icon_path = os.path.join(icon_dir, "expand.svg") # アイコンファイル名
        self.fullscreen_action = QAction(QIcon(fullscreen_icon_path), "フルスクリーン", self)
        self.fullscreen_action.setCheckable(True)
        # MainWindow 側で状態を管理するため、ここではシグナルを発行するだけ
        self.fullscreen_action.toggled.connect(self.fullscreen_toggled.emit)
        self.fullscreen_action.setShortcut(Qt.Key.Key_F11)
        self.toolbar.addAction(self.fullscreen_action)

    # --- 追加: UI要素の表示/非表示を切り替えるメソッド ---
    @Slot(bool)
    def set_ui_elements_visible(self, visible: bool):
        """ツールバーとステータスバーの表示状態を設定する"""
        if hasattr(self, 'toolbar'):
            self.toolbar.setVisible(visible)
        if hasattr(self, 'status_bar'):
            self.status_bar.setVisible(visible)

    # --- スライドショー関連メソッド ---

    @Slot(bool)
    def toggle_slideshow(self, checked: bool):
        """スライドショーの開始/停止を切り替え"""
        if checked:
            self.start_slideshow()
        else:
            self.stop_slideshow()

    def start_slideshow(self):
        """スライドショーを開始"""
        if not self.is_slideshow_running and self.image_model.image_count() > 1:
            logger.info(f"Starting slideshow: mode={self.slideshow_mode}, interval={self.slideshow_interval_ms}ms")
            self.is_slideshow_running = True
            self.slideshow_timer.start()
            self._update_slideshow_action_state()
        else:
            logger.debug("Slideshow already running or not enough images.")
            if self.slideshow_action.isChecked() != self.is_slideshow_running:
                self.slideshow_action.setChecked(self.is_slideshow_running)

    def stop_slideshow(self):
        """スライドショーを停止"""
        if self.is_slideshow_running:
            logger.info("Stopping slideshow.")
            self.is_slideshow_running = False
            self.slideshow_timer.stop()
            self._update_slideshow_action_state()
        else:
            if self.slideshow_action.isChecked() != self.is_slideshow_running:
                self.slideshow_action.setChecked(self.is_slideshow_running)

    def _update_slideshow_action_state(self):
        """スライドショー開始/停止アクションのアイコンとテキストを更新"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(script_dir, "..", "resources", "icons")
        if self.is_slideshow_running:
            pause_icon_path = os.path.join(icon_dir, "pause.svg")
            self.slideshow_action.setIcon(QIcon(pause_icon_path))
            self.slideshow_action.setText("スライドショー停止")
            self.slideshow_action.setToolTip("スライドショーを停止します (Space)")
        else:
            play_icon_path = os.path.join(icon_dir, "play.svg")
            self.slideshow_action.setIcon(QIcon(play_icon_path))
            self.slideshow_action.setText("スライドショー開始")
            self.slideshow_action.setToolTip("スライドショーを開始します (Space)")
        # アクションの状態が内部状態と異なれば同期
        if self.slideshow_action.isChecked() != self.is_slideshow_running:
             self.slideshow_action.setChecked(self.is_slideshow_running)

    @Slot()
    def toggle_slideshow_mode(self):
        """スライドショーの再生モードを切り替え"""
        if self.slideshow_mode == self.MODE_ORDER:
            self.slideshow_mode = self.MODE_RANDOM
        else:
            self.slideshow_mode = self.MODE_ORDER
        logger.info(f"Slideshow mode changed to: {self.slideshow_mode}")
        self._update_slideshow_mode_action()

    def _update_slideshow_mode_action(self):
        """スライドショーモードアクションのアイコンとテキストを更新"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_dir = os.path.join(script_dir, "..", "resources", "icons")
        if self.slideshow_mode == self.MODE_RANDOM:
            random_icon_path = os.path.join(icon_dir, "shuffle.svg") # shuffle.svg に変更
            self.slideshow_mode_action.setIcon(QIcon(random_icon_path))
            self.slideshow_mode_action.setText("ランダム再生")
        else:
            order_icon_path = os.path.join(icon_dir, "loop-square.svg") # loop-square.svg に変更
            self.slideshow_mode_action.setIcon(QIcon(order_icon_path))
            self.slideshow_mode_action.setText("順序再生")

    @Slot(int)
    def change_slideshow_interval(self, value_sec: int):
        """スライドショーの間隔を変更"""
        self.slideshow_interval_ms = value_sec * 1000
        self.slideshow_timer.setInterval(self.slideshow_interval_ms)
        logger.debug(f"Slideshow interval changed to: {self.slideshow_interval_ms}ms")
        if self.is_slideshow_running:
            self.slideshow_timer.start()

    @Slot()
    def _show_next_slide(self):
        """タイマーによって次のスライドを表示"""
        if not self.is_slideshow_running or self.image_model.image_count() < 1: # 1枚でも停止しないように変更
            self.stop_slideshow()
            return

        count = self.image_model.image_count()
        if count == 0: # 画像がない場合は停止
             self.stop_slideshow()
             return

        next_index = -1

        if count == 1: # 画像が1枚しかない場合
             next_index = 0 # 常に同じ画像
        elif self.slideshow_mode == self.MODE_ORDER:
            next_index = (self.current_index + 1) % count
        elif self.slideshow_mode == self.MODE_RANDOM:
            possible_indices = list(range(count))
            if self.current_index in possible_indices and count > 1: # 現在のインデックスを除外 (1枚の場合は除く必要なし)
                possible_indices.remove(self.current_index)
            if not possible_indices:
                 next_index = self.current_index # 候補がない場合は現状維持
            else:
                 next_index = random.choice(possible_indices)

        if next_index != -1: # next_index が有効ならロード
            # インデックスが変わらない場合(画像1枚 or ランダムで同じものが選ばれた)でもロード処理を呼ぶことでタイマーが再開される
            logger.debug(f"Slideshow showing next: index {next_index}")
            self.load_image(next_index)
        # else: # load_image が呼ばれなかった場合でもタイマーは start されるべき
        #     if self.is_slideshow_running:
        #         self.slideshow_timer.start() # タイマーが止まらないように

    # --- 画像表示関連メソッド ---

    @Slot(int)
    def load_image(self, index: int):
        """指定されたインデックスの画像を読み込む"""
        image_path = self.image_model.get_image_at(index)
        if not image_path:
             logger.warning(f"Invalid image index requested: {index}")
             self.stop_slideshow() # 不正なインデックスならスライドショー停止
             return

        self.current_index = index
        logger.debug(f"Loading image index {index}: {image_path}")
        pixmap = QPixmap(image_path)

        if pixmap.isNull():
            logger.error(f"Failed to load image: {image_path}")
            self.scene.clear()
            self.pixmap_item = None
            self.status_label.setText(f"エラー: {os.path.basename(image_path)}")
            self.stop_slideshow() # 読み込み失敗ならスライドショー停止
            return

        self.scene.clear()
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.fit_to_view()
        self.current_rotation = 0.0
        self.pixmap_item.setTransformOriginPoint(self.pixmap_item.boundingRect().center())

        file_name = os.path.basename(image_path)
        img_size = pixmap.size()
        status_text = f"{file_name} ({img_size.width()}x{img_size.height()}) - {index + 1}/{self.image_model.image_count()}"
        self.status_label.setText(status_text)
        logger.debug(f"Status updated: {status_text}")

        self._update_navigation_state()

        # タイマーが停止していたら（手動操作後など）、スライドショー実行中なら再開
        if self.is_slideshow_running and not self.slideshow_timer.isActive():
            logger.debug("Restarting slideshow timer after manual navigation or load.")
            self.slideshow_timer.start()

    @Slot()
    def show_previous_image(self):
        """前の画像を表示 (スライドショータイマーリセット付き)"""
        if self.current_index > 0:
            # タイマーリセットのために stop/start するのではなく、start()だけで良い
            if self.is_slideshow_running:
                self.slideshow_timer.start() # 現在の間隔でタイマーを再スタート
            self.load_image(self.current_index - 1)
        else:
            logger.debug("Already at the first image.")

    @Slot()
    def show_next_image(self):
        """次の画像を表示 (スライドショータイマーリセット付き)"""
        count = self.image_model.image_count()
        if self.current_index < count - 1:
            if self.is_slideshow_running:
                self.slideshow_timer.start() # 現在の間隔でタイマーを再スタート
            self.load_image(self.current_index + 1)
        elif self.is_slideshow_running and self.slideshow_mode == self.MODE_ORDER and count > 0:
            # 最後の画像で順序モードなら最初に戻る
            logger.debug("Looping slideshow back to first image.")
            self.slideshow_timer.start()
            self.load_image(0)
        else:
            logger.debug("Already at the last image or cannot loop.")

    def _update_navigation_state(self):
        """ナビゲーションアクションの有効/無効状態を更新"""
        if hasattr(self, 'prev_action') and hasattr(self, 'next_action'):
             is_first = (self.current_index <= 0)
             is_last = (self.current_index >= self.image_model.image_count() - 1)
             can_loop = (self.is_slideshow_running and self.slideshow_mode == self.MODE_ORDER and self.image_model.image_count() > 0)

             self.prev_action.setEnabled(not is_first)
             self.next_action.setEnabled(not is_last or can_loop) # ループ可能なら最後でも有効
        else:
             logger.warning("_update_navigation_state: prev_action or next_action not found.")

    # --- イベントハンドラ ---

    def hideEvent(self, event):
        """ウィジェットが非表示になるときにスライドショーを停止"""
        logger.debug("SingleImageView hideEvent called, stopping slideshow.")
        self.stop_slideshow()
        super().hideEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        """マウスホイールイベントでズーム"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            # 通常のホイールイベントはQGraphicsViewに委譲
            super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """キープレスイベント処理 - ショートカットを最優先"""
        key = event.key()
        logger.debug(f"SingleImageView.keyPressEvent received KeyPress: {key}") # ★デバッグログ追加

        if key == Qt.Key.Key_Escape:
            main_window = self.window()
            is_fullscreen = False
            if main_window and hasattr(main_window, 'isFullScreen'):
                try: is_fullscreen = main_window.isFullScreen()
                except Exception: pass

            if not is_fullscreen:
                logger.debug("SingleImageView received Esc (not fullscreen), emitting back_requested.")
                self.stop_slideshow()
                self.back_requested.emit()
                event.accept() # Esc (非フルスクリーン) はここで消費
                return
            else:
                # フルスクリーン時の Esc は MainWindow の eventFilter に任せる
                logger.debug("SingleImageView received Esc (fullscreen), ignoring.")
                event.ignore() # 親にイベントを渡すことを明示
                return

        # --- Esc 以外のキーは、まず super() に処理させる ---
        logger.debug(f"SingleImageView calling super().keyPressEvent for key {key}")
        super().keyPressEvent(event)
        logger.debug(f"SingleImageView super().keyPressEvent finished. Event accepted: {event.isAccepted()}")

        # --- super() で処理されなかった場合 (通常はショートカットがここで処理されるはず) ---
        # if not event.isAccepted():
        #     logger.warning(f"SingleImageView KeyPress {key} was not accepted by superclass/shortcuts.")
        #     # ここで独自のキー処理が必要なら追加するが、今回は何もしない

    def resizeEvent(self, event):
        """リサイズ時にビューに合わせて再フィット (オプション)"""
        # self.fit_to_view() # 常にフィットさせたい場合
        super().resizeEvent(event)

    # --- ズーム関連メソッド ---
    @Slot()
    def zoom_in(self):
        self.view.scale(1.2, 1.2)

    @Slot()
    def zoom_out(self):
        self.view.scale(1 / 1.2, 1 / 1.2)

    @Slot()
    def fit_to_view(self):
        """画像をビュー全体に表示"""
        if self.pixmap_item:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @Slot()
    def zoom_original(self):
        """画像を等倍で表示"""
        if self.pixmap_item:
            self.view.setTransform(QTransform())
            self.view.centerOn(self.pixmap_item)

    # --- 回転関連メソッド ---
    @Slot()
    def rotate_left(self):
        """画像を左に90度回転"""
        if self.pixmap_item:
            self.current_rotation -= 90.0
            if self.current_rotation < 0: self.current_rotation += 360.0
            self.pixmap_item.setRotation(self.current_rotation)

    @Slot()
    def rotate_right(self):
        """画像を右に90度回転"""
        if self.pixmap_item:
            self.current_rotation += 90.0
            if self.current_rotation >= 360.0: self.current_rotation -= 360.0
            self.pixmap_item.setRotation(self.current_rotation)

# --- END OF FILE views/single_image_view.py ---
