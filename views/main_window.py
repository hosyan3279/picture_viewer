import os
from PySide6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QStatusBar,
    QToolBar, QStyle, QTabWidget, QVBoxLayout, QWidget,
    QStackedWidget, QApplication
)
from PySide6.QtGui import QAction, QKeySequence, QIcon, QKeyEvent, QShortcut
from PySide6.QtCore import Qt, Slot, QEvent, QTimer, QObject
from models.image_model import ImageModel
from models.unified_thumbnail_cache import UnifiedThumbnailCache
from controllers.worker_manager import WorkerManager
from controllers.enhanced_image_loader import EnhancedImageLoader
from views.enhanced_grid_view import EnhancedGridView
from views.flow_grid_view import FlowGridView
from views.single_image_view import SingleImageView # 正しいビュークラスをインポート
from utils import logger, get_config

class GlobalShortcutFilter(QObject):
    """
    アプリケーション全体のキーボードショートカットを処理するフィルタークラス
    
    特にフルスクリーンモードでのキーボードショートカットを確実に捕捉します。
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
    
    def eventFilter(self, watched, event):
        # キーイベントの場合のみ処理
        if event.type() == QEvent.KeyPress:
            if not isinstance(event, QKeyEvent):
                return False
                
            # デバッグログを追加
            key = event.key()
            modifiers = event.modifiers()
            logger.debug(f"GlobalShortcutFilter: KeyPress event - Key={key}, Modifiers={modifiers}")
            
            # フルスクリーン時のナビゲーションキー処理
            if self.main_window.isFullScreen() and self.main_window.stacked_widget.currentIndex() == 1:
                # 左矢印キー（前のページ）
                if key == Qt.Key_Left:
                    if hasattr(self.main_window, 'single_view_widget'):
                        self.main_window.single_view_widget.show_previous_image()
                        return True
                
                # 右矢印キー（次のページ）
                elif key == Qt.Key_Right:
                    if hasattr(self.main_window, 'single_view_widget'):
                        self.main_window.single_view_widget.show_next_image()
                        return True
                
                # Escキー（フルスクリーン解除）
                elif key == Qt.Key_Escape:
                    self.main_window.handle_fullscreen_toggle(False)
                    return True
                    
                # スペースキー（スライドショー切り替え）
                elif key == Qt.Key_Space:
                    if hasattr(self.main_window, 'single_view_widget'):
                        slideshow_action = self.main_window.single_view_widget.slideshow_action
                        if slideshow_action:
                            slideshow_action.toggle()
                            return True
                
                # F11キー（フルスクリーン切り替え）
                elif key == Qt.Key_F11:
                    self.main_window.handle_fullscreen_toggle(not self.main_window.isFullScreen())
                    return True
            
            # 通常のキー処理（必要に応じて）
            # その他のグローバルショートカットがあれば追加
                    
        # イベントを処理しなかった場合は、次のフィルターに渡す
        return super().eventFilter(watched, event)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = get_config()

        logger.info("Main window initialized.")
        self.image_model = ImageModel()
        self.thumbnail_cache = UnifiedThumbnailCache(
            memory_limit=self.config.get("cache.memory_limit"),
            disk_cache_dir=self.config.get("cache.disk_cache_dir"),
            disk_cache_limit_mb=self.config.get("cache.disk_cache_limit_mb"),
            cleanup_interval=self.config.get("cache.cleanup_interval_ms")
        )
        self.worker_manager = WorkerManager()
        self.image_loader = EnhancedImageLoader(self.image_model, self.thumbnail_cache, self.worker_manager)

        self.setup_ui()
        self.setup_connections()

        # グローバルショートカットフィルターを設定
        self.global_shortcut_filter = GlobalShortcutFilter(self)
        QApplication.instance().installEventFilter(self.global_shortcut_filter)
        
        # --- イベントフィルターのインストール ---
        if hasattr(self, 'single_view_widget'):
            self.single_view_widget.installEventFilter(self)
            logger.debug("Event filter installed on single_view_widget.")

    def setup_ui(self):
        logger.debug("Setting up UI components.")
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("準備完了")

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.tab_widget = QTabWidget()
        try:
             self.grid_view = EnhancedGridView(self.image_model, self.worker_manager)
             self.tab_widget.addTab(self.grid_view, "グリッドビュー")
             self.flow_view = FlowGridView(self.image_model, self.worker_manager)
             self.tab_widget.addTab(self.flow_view, "フロービュー")
        except Exception as e:
             logger.exception("Error creating view tabs.", exc_info=True)
             QMessageBox.critical(self, "UIエラー", f"ビューの作成中にエラーが発生しました:\n{e}")

        default_view_index = 0 if self.config.get("display.default_view", "grid") == "grid" else 1
        self.tab_widget.setCurrentIndex(default_view_index)

        # SingleImageView をインスタンス化
        self.single_view_widget = SingleImageView(self.image_model, self)

        self.stacked_widget.addWidget(self.tab_widget)       # Index 0
        self.stacked_widget.addWidget(self.single_view_widget) # Index 1
        self.stacked_widget.setCurrentIndex(0)

        self.create_menus()
        self.create_toolbars()

    def create_menus(self):
        # ... (変更なし) ...
        logger.debug("Creating menus.")
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("ファイル(&F)")
        open_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "フォルダを開く(&O)...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.setStatusTip("画像が含まれるフォルダを開きます")
        open_action.triggered.connect(self.open_folder)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        cache_menu = file_menu.addMenu("キャッシュ(&C)")
        clear_cache_action = QAction("キャッシュをクリア", self)
        clear_cache_action.setStatusTip("サムネイルキャッシュを削除します")
        clear_cache_action.triggered.connect(self.clear_cache)
        cache_menu.addAction(clear_cache_action)
        show_cache_info_action = QAction("キャッシュ情報を表示", self)
        show_cache_info_action.setStatusTip("キャッシュの使用状況を表示します")
        show_cache_info_action.triggered.connect(self.show_cache_info)
        cache_menu.addAction(show_cache_info_action)
        file_menu.addSeparator()
        exit_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton), "終了(&X)", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.setStatusTip("アプリケーションを終了します")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        view_menu = menu_bar.addMenu("表示(&V)")
        refresh_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "表示を更新(&R)", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.setStatusTip("現在の表示を更新します")
        refresh_action.triggered.connect(self.refresh_view)
        view_menu.addAction(refresh_action)
        view_menu.addSeparator()
        view_type_menu = view_menu.addMenu("ビュータイプ(&T)")
        self.grid_view_action = QAction("グリッドビュー", self)
        self.grid_view_action.setCheckable(True)
        self.grid_view_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(0))
        view_type_menu.addAction(self.grid_view_action)
        self.flow_view_action = QAction("フロービュー", self)
        self.flow_view_action.setCheckable(True)
        self.flow_view_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(1))
        view_type_menu.addAction(self.flow_view_action)
        self.sync_view_actions(self.tab_widget.currentIndex())
        self.tab_widget.currentChanged.connect(self.sync_view_actions)


    def create_toolbars(self):
        """ツールバーを作成"""
        logger.debug("Creating toolbars.")
        # メインツールバーのインスタンスを self に保持する
        self.main_toolbar = QToolBar("メインツールバー")
        self.main_toolbar.setMovable(False)
        self.addToolBar(self.main_toolbar)

        # --- ツールバーへのアクション追加 ---
        # (変更なし)
        open_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "フォルダを開く", self)
        open_action.setStatusTip("画像が含まれるフォルダを開きます")
        open_action.triggered.connect(self.open_folder)
        self.main_toolbar.addAction(open_action)

        self.main_toolbar.addSeparator()

        grid_view_tool_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView), "グリッドビュー", self)
        grid_view_tool_action.setStatusTip("グリッド形式で表示します")
        grid_view_tool_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(0))
        self.main_toolbar.addAction(grid_view_tool_action)

        flow_view_tool_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), "フロービュー", self)
        flow_view_tool_action.setStatusTip("フローレイアウトで表示します")
        flow_view_tool_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(1))
        self.main_toolbar.addAction(flow_view_tool_action)

        self.main_toolbar.addSeparator()
        refresh_tool_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "更新", self)
        refresh_tool_action.setStatusTip("現在の表示を更新します (F5)")
        refresh_tool_action.triggered.connect(self.refresh_view)
        self.main_toolbar.addAction(refresh_tool_action)


    def setup_connections(self):
        logger.debug("Setting up signal/slot connections.")
        try:
            self.image_loader.loading_finished.connect(self.on_loading_finished)
            self.image_loader.thumbnail_created.connect(self.update_thumbnail)
            self.image_loader.error_occurred.connect(self.show_error)
            self.image_loader.progress_updated.connect(self.update_progress)

            if hasattr(self, 'grid_view'):
                 self.grid_view.image_selected.connect(self.show_single_image_view)
                 self.grid_view.thumbnail_needed.connect(self.image_loader.request_thumbnail)
            if hasattr(self, 'flow_view'):
                 self.flow_view.image_selected.connect(self.show_single_image_view)
                 self.flow_view.thumbnail_needed.connect(self.image_loader.request_thumbnail)

            # single_view_widget のシグナルを接続
            self.single_view_widget.back_requested.connect(self.show_thumbnail_view)
            self.single_view_widget.fullscreen_toggled.connect(self.handle_fullscreen_toggle) # フルスクリーン接続

        except Exception as e:
             logger.exception("Error setting up connections.", exc_info=True)
             QMessageBox.critical(self, "接続エラー", f"シグナル/スロット接続中にエラーが発生しました:\n{e}")

    @Slot(int)
    def sync_view_actions(self, index):
        # ... (変更なし) ...
        is_grid_active = (index == 0)
        self.grid_view_action.setChecked(is_grid_active)
        self.flow_view_action.setChecked(not is_grid_active)
        logger.debug(f"Synced view actions. Current index: {index} (Grid: {is_grid_active})")

    @Slot()
    def open_folder(self):
        # ... (変更なし) ...
        folder_path = QFileDialog.getExistingDirectory(self, "フォルダを選択", os.path.expanduser("~"))
        if folder_path:
            logger.info(f"Folder selected: {folder_path}")
            self.status_bar.showMessage(f"フォルダスキャン開始: {os.path.basename(folder_path)}...")
            if self.worker_manager.is_worker_active("folder_scan"):
                 logger.info("Cancelling previous folder scan worker.")
                 self.worker_manager.cancel_worker("folder_scan")
            self.image_loader.load_images_from_folder(folder_path)
        else:
            logger.info("Folder selection cancelled.")

    @Slot(int)
    def update_progress(self, value):
        # ... (変更なし) ...
        self.status_bar.showMessage(f"フォルダスキャン中... {value}%")

    @Slot()
    def on_loading_finished(self):
        # ... (変更なし) ...
        count = self.image_model.image_count()
        logger.info(f"Loading finished. {count} images found.")
        self.status_bar.showMessage(f"{count}枚の画像を検出しました。サムネイル準備中...", 5000)

    @Slot(str, object)
    def update_thumbnail(self, image_path, thumbnail):
        # ... (変更なし) ...
        try:
             if hasattr(self, 'grid_view'):
                  self.grid_view.receive_thumbnail(image_path, thumbnail)
             if hasattr(self, 'flow_view'):
                  self.flow_view.receive_thumbnail(image_path, thumbnail)
        except Exception as e:
             logger.error(f"Error updating thumbnail in view for {image_path}: {e}")

    @Slot(str)
    def show_error(self, message):
        # ... (変更なし) ...
        logger.error(f"Error occurred: {message}")
        self.status_bar.showMessage(f"エラー: {message}", 10000)

    @Slot(str)
    def show_single_image_view(self, image_path: str):
        logger.info(f"Switching to single image view for: {image_path}")
        try:
            current_index = self.image_model.images.index(image_path)
        except ValueError:
            logger.error(f"選択された画像がモデル内に見つかりません: {image_path}")
            QMessageBox.warning(self, "エラー", "選択された画像がリスト内に見つかりません。")
            return
        if self.image_model.image_count() == 0: return

        self.single_view_widget.load_image(current_index)
        self.stacked_widget.setCurrentIndex(1)
        # TODO: ツールバー/メニューの状態を更新

    @Slot()
    def show_thumbnail_view(self):
        logger.info("Switching back to thumbnail view.")
        self.stacked_widget.setCurrentIndex(0)
        # TODO: ツールバー/メニューの状態を更新

    @Slot(bool)
    def handle_fullscreen_toggle(self, checked: bool):
        """フルスクリーンモードを切り替える"""
        ui_visible = not checked

        # --- UI要素の表示/非表示 ---
        if hasattr(self, 'main_toolbar'): self.main_toolbar.setVisible(ui_visible)
        if self.menuBar(): self.menuBar().setVisible(ui_visible)
        if self.statusBar(): self.statusBar().setVisible(ui_visible)
        if hasattr(self, 'single_view_widget'): self.single_view_widget.set_ui_elements_visible(ui_visible)

        # --- ウィンドウ状態の切り替えとフォーカス設定 ---
        if checked:
            logger.info("Entering fullscreen mode.")
            # フルスクリーン前にフォーカスをリセット（任意）
            self.setFocus()
            
            # フルスクリーン表示
            self.showFullScreen()
            
            # フルスクリーン直後に明示的にフォーカスを設定
            QTimer.singleShot(100, self._set_focus_after_fullscreen)
        else:
            logger.info("Exiting fullscreen mode.")
            self.showNormal()
            # 通常モードに戻った際にフォーカスを設定
            QTimer.singleShot(100, self._set_focus_after_normal)

        # --- アクション状態同期 ---
        if hasattr(self, 'single_view_widget') and hasattr(self.single_view_widget, 'fullscreen_action'):
             fullscreen_action = self.single_view_widget.fullscreen_action
             if fullscreen_action and fullscreen_action.isCheckable():
                  if fullscreen_action.isChecked() != checked:
                       fullscreen_action.blockSignals(True)
                       fullscreen_action.setChecked(checked)
                       fullscreen_action.blockSignals(False)
                       
    def _set_focus_after_fullscreen(self):
        """フルスクリーン後にフォーカスを正しく設定する"""
        if hasattr(self, 'single_view_widget'):
            if hasattr(self.single_view_widget, 'view') and self.single_view_widget.view:
                self.single_view_widget.view.setFocus(Qt.FocusReason.OtherFocusReason)
                logger.debug("Focus set to single_view_widget.view after fullscreen")
                
                # QGraphicsViewのフォーカスポリシーの調整（オプション）
                self.single_view_widget.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            else:
                # フォールバック：ウィジェット自体にフォーカス
                self.single_view_widget.setFocus(Qt.FocusReason.OtherFocusReason)
                logger.debug("Focus set to single_view_widget (fallback)")
    
    def _set_focus_after_normal(self):
        """通常モードに戻った後にフォーカスを設定する"""
        if self.stacked_widget.currentIndex() == 0 and hasattr(self, 'tab_widget'):
            current_tab = self.tab_widget.currentWidget()
            if current_tab:
                current_tab.setFocus(Qt.FocusReason.OtherFocusReason)
                logger.debug("Focus set to current tab widget after normal mode")
        elif self.stacked_widget.currentIndex() == 1 and hasattr(self, 'single_view_widget'):
            self.single_view_widget.setFocus(Qt.FocusReason.OtherFocusReason)
            logger.debug("Focus set to single_view_widget after normal mode")

    # --- イベントフィルター (変更なし) ---
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # --- キープレスイベントの詳細ログ ---
        if event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                key = event.key()
                modifiers = event.modifiers()
                text = event.text()
                is_autorepeat = event.isAutoRepeat()
                logger.debug(
                    f"EventFilter KeyPress on '{watched.objectName() if watched else 'None'}': "
                    f"Key={key}, Mod={modifiers}, Text='{text}', Repeat={is_autorepeat}, Accepted={event.isAccepted()}"
                )

        # --- 既存のEscキー処理 ---
        if watched == self.single_view_widget:
            if event.type() == QEvent.Type.KeyPress:
                if isinstance(event, QKeyEvent):
                    if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
                        logger.debug("Event filter caught Esc in fullscreen single view.")
                        self.handle_fullscreen_toggle(False)
                        fullscreen_action = next((a for a in self.single_view_widget.toolbar.actions() if "フルスクリーン" in a.text()), None)
                        if fullscreen_action and fullscreen_action.isCheckable():
                            fullscreen_action.setChecked(False)
                        logger.debug("Event filter consumed Esc key.")
                        return True # イベント消費

        # --- 上記以外はデフォルト処理 ---
        try:
            accepted = super().eventFilter(watched, event)
            # if event.type() == QEvent.Type.KeyPress: # super().eventFilter後の状態もログ
            #    logger.debug(f"EventFilter returning {accepted} for KeyPress on '{watched.objectName() if watched else 'None'}' after super call.")
            return accepted
        except Exception as e:
             logger.error(f"Error in super().eventFilter: {e}")
             return False # エラー時はイベントをブロックしない
        

    @Slot()
    def clear_cache(self):
        # ... (変更なし) ...
        logger.info("Clearing thumbnail cache.")
        reply = QMessageBox.question(self, "キャッシュクリアの確認",
                                     "サムネイルキャッシュをクリアしますか？\n(次回表示時に再生成されます)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                 success = self.thumbnail_cache.clear()
                 if success:
                      QMessageBox.information(self, "キャッシュクリア完了", "サムネイルキャッシュをクリアしました。")
                      logger.info("Thumbnail cache cleared successfully.")
                      self.refresh_view()
                 else:
                      QMessageBox.warning(self, "キャッシュクリア失敗", "サムネイルキャッシュのクリア中にエラーが発生しました。")
                      logger.error("Failed to clear thumbnail cache.")
            except Exception as e:
                 logger.exception("Exception during cache clear.", exc_info=True)
                 QMessageBox.critical(self, "キャッシュクリアエラー", f"キャッシュクリア中に予期せぬエラーが発生しました:\n{e}")
        else:
             logger.info("Cache clear cancelled by user.")


    @Slot()
    def show_cache_info(self):
        # ... (変更なし) ...
        logger.debug("Showing cache info.")
        try:
            stats = self.thumbnail_cache.get_stats()
            info_text = "【サムネイルキャッシュ情報】\n\n"
            mem_limit = stats.get('memory_cache_limit', 'N/A')
            info_text += f"メモリキャッシュ: {stats.get('memory_cache_count', 'N/A')} / {mem_limit} アイテム\n"
            disk_limit = stats.get('disk_cache_limit_mb', 0)
            info_text += f"ディスクキャッシュ: {stats.get('disk_cache_count', 'N/A')} アイテム\n"
            info_text += f"ディスクキャッシュサイズ: {stats.get('disk_cache_size_mb', 0):.2f} MB / {disk_limit:.2f} MB\n"
            info_text += f"\nヒット率: {stats.get('hit_ratio', 0):.2f}%\n"
            info_text += f"総ヒット数: {stats.get('hits', 'N/A')}\n"
            info_text += f"総ミス数: {stats.get('misses', 'N/A')}\n"
            info_text += f"総書き込み数: {stats.get('writes', 'N/A')}\n"
            info_text += f"総エラー数: {stats.get('errors', 'N/A')}\n"
            if stats.get('enhanced', False) or stats.get('using_sqlite', False):
                 info_text += f"\nクリーンアップ回数: {stats.get('cleanup_count', 'N/A')}\n"
                 cleanup_interval_s = stats.get('cleanup_interval_ms', 0) / 1000
                 info_text += f"クリーンアップ間隔: {cleanup_interval_s} 秒\n"
                 popular = stats.get('popular_entries', [])
                 if popular:
                      info_text += "\nアクセス数の多いエントリ Top 5:\n"
                      for entry in popular:
                           info_text += f" - {entry.get('path', '?')} ({entry.get('size', '?')}): {entry.get('count', '?')}回\n"
            QMessageBox.information(self, "キャッシュ情報", info_text)
        except Exception as e:
             logger.exception("Error getting cache stats.", exc_info=True)
             QMessageBox.critical(self, "情報取得エラー", f"キャッシュ情報の取得中にエラーが発生しました:\n{e}")

    @Slot()
    def refresh_view(self):
        # ... (変更なし) ...
        current_tab_index = self.tab_widget.currentIndex()
        logger.info(f"Refreshing current view (Tab index: {current_tab_index}).")
        current_widget = self.tab_widget.currentWidget()
        if isinstance(current_widget, (EnhancedGridView, FlowGridView)):
            current_widget.refresh()
        else:
            logger.warning("Current tab widget is not a known view type, cannot refresh.")

    def closeEvent(self, event):
        # ... (変更なし) ...
        logger.info("Close event received. Shutting down workers and saving state...")
        cancelled_count = self.worker_manager.cancel_all()
        logger.info(f"Attempted to cancel {cancelled_count} workers.")
        if hasattr(self.thumbnail_cache, '_update_db_stats'):
             self.thumbnail_cache._update_db_stats()
        logger.info("Cleanup complete. Accepting close event.")
        event.accept()

    # --- keyPressEvent を削除 ---
    # def keyPressEvent(self, event: QKeyEvent):
    #     # ... (このメソッド全体を削除またはコメントアウト) ...
