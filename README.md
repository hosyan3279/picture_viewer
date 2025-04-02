
# Picture Viewer (画像ビューワーアプリケーション)

PySide6 を使用して構築された、高機能な画像ビューワーアプリケーションです。

## ✨ 主な機能

- **フォルダ内の画像表示:** 指定したフォルダ内の画像を一覧表示します。
- **サムネイル表示:** 画像のサムネイルをグリッド形式で表示し、ページネーション機能も備えています。
- **高速サムネイルキャッシュ:** サムネイルをキャッシュ (`enhanced_thumbnail_cache.py`, `advanced_thumbnail_cache.py`) することで、次回以降の表示を高速化します。
- **非同期処理:** マルチスレッド (`worker_manager.py`, `workers.py`, `optimized_thumbnail_worker.py`) を活用し、画像の読み込みやサムネイル生成をバックグラウンドで行い、UIの応答性を維持します。
- **強化された画像読み込み:** より効率的な画像読み込み処理 (`enhanced_image_loader.py`)。
- **ディレクトリ監視:** フォルダ内の変更を検知する機能 (`directory_scanner.py`)。
- **バッチ処理:** 複数の画像に対する一括処理機能 (`batch_processor.py`)。
- **遅延読み込み:** 画面に表示されるまで画像の読み込みを遅らせることで、メモリ使用量と初期表示速度を改善 (`lazy_image_label.py`)。
- **強化されたグリッドビュー:** スクロール連動の表示更新など、より洗練されたグリッド表示 (`scroll_aware_image_grid.py`, `enhanced_grid_view.py`)。
- **メモリ監視:** アプリケーションのメモリ使用状況を監視するユーティリティ (`memory_monitor.py`)。

## 🔧 必要条件

- Python 3.12
- uv
- 必要なライブラリ (詳細は `requirements.txt` を参照)
    - **PySide6** (GUIフレームワーク)
    - Pillow (画像処理ライブラリ - requirements.txt に含まれている想定)
    - psutil (メモリ監視用 - requirements.txt に含まれている想定)
    - 他、`requirements.txt` に記載されているライブラリ

## 🚀 インストール

1.  **リポジトリをクローン:**
    ```bash
    # このリポジトリの実際の URL に置き換えてください
    git clone [https://github.com/your-username/picture-viewer.git](https://github.com/your-username/picture-viewer.git)
    cd picture-viewer

    uv init
    uv venv
    source .venv/bin/activate
    ```

2.  **依存関係をインストール:**
    プロジェクトのルートディレクトリ（`requirements.txt` がある場所）で、以下のコマンドを実行して必要なライブラリをインストールします。
    ```bash
    uv pip install -r requirements.txt
    ```
    これにより、`PySide6` を含む必要なすべてのライブラリがインストールされます。

## ▶️ 使用方法

アプリケーションを起動するには、プロジェクトのルートディレクトリで以下のコマンドを実行します:

```bash
uv run -m picture_viewer.main
```

## 📂 プロジェクト構造

```
picture_viewer/
├── main.py                         # アプリケーションのエントリーポイント
├── requirements.txt                # 依存ライブラリリスト
├── README.md                       # このファイル
├── プロジェクト詳細.md             # (任意) より詳細なプロジェクト情報
├── .gitignore                      # Gitが無視するファイル/フォルダ指定
│
├── models/                         # データモデル (データの構造と操作)
│   ├── __init__.py
│   ├── image_model.py              # 画像データの基本モデル
│   ├── thumbnail_cache.py          # 基本的なサムネイルキャッシュ
│   ├── enhanced_thumbnail_cache.py # 強化されたサムネイルキャッシュ
│   └── advanced_thumbnail_cache.py   # 高度なサムネイルキャッシュ
│
├── views/                          # UIコンポーネント (画面表示)
│   ├── __init__.py
│   ├── main_window.py              # メインウィンドウ
│   ├── image_grid_view.py          # 基本的な画像グリッドビュー
│   ├── enhanced_grid_view.py       # 強化されたグリッドビュー
│   ├── scroll_aware_image_grid.py  # スクロール対応グリッドビュー
│   └── lazy_image_label.py         # 遅延読み込み画像ラベル
│
├── controllers/                    # アプリケーションロジック (モデルとビューの連携)
│   ├── __init__.py
│   ├── image_loader.py             # (基本の可能性あり) 画像読み込み
│   ├── enhanced_image_loader.py    # 強化された画像読み込み
│   ├── worker_manager.py           # スレッド/ワーカー管理
│   ├── workers.py                  # 基本的なワーカースレッド
│   ├── optimized_thumbnail_worker.py # 最適化されたサムネイル生成ワーカー
│   ├── directory_scanner.py        # ディレクトリ監視
│   └── batch_processor.py          # バッチ処理
│
├── utils/                          # 補助的な関数やクラス
│   ├── __init__.py
│   └── memory_monitor.py           # メモリ監視ユーティリティ
```

## 🏛️ アーキテクチャ

このアプリケーションは **Model-View-Controller (MVC)** パターンに基づいて設計されています:

- **Model (`models/`)**: アプリケーションのデータ（画像情報、サムネイルキャッシュなど）と、それらを操作するためのロジックを担当します。データの永続化や状態管理を行います。
- **View (`views/`)**: ユーザーインターフェース（ウィンドウ、ボタン、画像表示エリアなど）の表示を担当します。ユーザーからの入力を受け付け、Controller に伝えます。
- **Controller (`controllers/`)**: Model と View の間の調整役です。ユーザーのアクション（ボタンクリック、フォルダ選択など）に応じて Model のデータを更新したり、Model の変更を View に反映させたりします。また、画像読み込みやサムネイル生成などのバックグラウンド処理の管理も行います。

さらに、`utils/` ディレクトリには、特定のMVCコンポーネントに依存しない、プロジェクト全体で再利用可能な汎用的な補助機能（メモリ監視など）が含まれています。

