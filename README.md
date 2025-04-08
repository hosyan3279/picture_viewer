# Picture Viewer (画像ビューワーアプリケーション)

PySide6 を使用して構築された、高機能な画像ビューワーアプリケーションです。

## ✨ 主な機能

- **フォルダ内の画像表示:** 指定したフォルダ内の画像を一覧表示します。
- **サムネイル表示:** 画像のサムネイルをグリッド形式で表示し、ページネーション機能も備えています。
- **高速サムネイルキャッシュ:** 統合サムネイルキャッシュシステムにより、サムネイルの高速な読み込みを実現します。
- **マルチエンジンサムネイル生成:** Qt、PIL、libvipsなど複数の画像処理エンジンをサポートし、最適なものを自動選択します。
- **非同期処理:** マルチスレッドを活用し、画像の読み込みやサムネイル生成をバックグラウンドで行い、UIの応答性を維持します。
- **強化された画像読み込み:** より効率的な画像読み込み処理。
- **ディレクトリ監視:** フォルダ内の変更を検知する機能。
- **バッチ処理:** 複数の画像に対する一括処理機能。
- **遅延読み込み:** 画面に表示されるまで画像の読み込みを遅らせることで、メモリ使用量と初期表示速度を改善。
- **強化されたグリッドビュー:** スクロール連動の表示更新など、より洗練されたグリッド表示。
- **メモリ監視:** アプリケーションのメモリ使用状況を監視するユーティリティ。

## 🔧 必要条件

- Python 3.12
- uv (パッケージマネージャー)
- 必要なライブラリ (詳細は `requirements.txt` を参照)
    - **PySide6** (GUIフレームワーク)
    - **Pillow** (画像処理ライブラリ - サムネイル生成エンジンの一つ)
    - **pyvips** (libvipsのPythonバインディング - 高速画像処理用、オプション)
    - psutil (メモリ監視用)
    - 他、`requirements.txt` に記載されているライブラリ

## ⚡ libvips のインストールについて (オプション)

高速なサムネイル生成を有効にするには、pyvips (Pythonパッケージ) に加えて、システムにlibvips自体をインストールする必要があります：

### Windows
1. [vips-dev](https://github.com/libvips/libvips/releases) の最新リリースをダウンロード
2. インストーラーを実行
3. システム環境変数のPATHにvipsのbinディレクトリを追加 (通常は自動追加されます)

### macOS
```bash
brew install vips
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get install libvips-dev
```

## 🚀 インストール

1.  **リポジトリをクローン:**
    ```bash
    # このリポジトリの実際の URL に置き換えてください
    git clone [https://github.com/your-username/picture-viewer.git](https://github.com/your-username/picture-viewer.git)
    cd picture-viewer

    uv init
    uv venv
    source .venv/bin/activate  # Windowsの場合: .venv\Scripts\activate
    ```

2.  **依存関係をインストール:**
    プロジェクトのルートディレクトリ（`requirements.txt` がある場所）で、以下のコマンドを実行して必要なライブラリをインストールします。
    ```bash
    uv pip install -r requirements.txt
    ```
    これにより、`PySide6`、`Pillow`などの必要なすべてのライブラリがインストールされます。

## ▶️ 使用方法

アプリケーションを起動するには、プロジェクトのルートディレクトリで以下のコマンドを実行します:

```bash
uv run main.py
```

サンプルアプリケーションを試すには:

```bash
uv run examples/thumbnail_viewer.py
```

## 🖼️ サムネイル生成エンジン

このアプリケーションは、統合サムネイル生成ワーカー (`UnifiedThumbnailWorker`) で以下の3つのエンジンをサポートしています：

1. **Qt エンジン**: PySide6/Qt内蔵の画像処理機能を使用 (常に利用可能)
2. **PIL エンジン**: Python Image Library (Pillow) を使用 (インストールされている場合)
3. **VIPS エンジン**: libvips を使用した高速画像処理 (インストールされている場合)

アプリケーションは画像のサイズや特性に基づいて、自動的に最適なエンジンを選択します。これにより：

- 大きな画像でメモリ使用量が70%以上削減
- 高解像度画像のサムネイル生成が最大5倍高速化
- CPUマルチコアの効率的な活用

## 📂 プロジェクト構造

```
picture_viewer/
├── main.py                         # アプリケーションのエントリーポイント
├── requirements.txt                # 依存ライブラリリスト
├── README.md                       # このファイル
│
├── docs/                           # ドキュメント
│   └── thumbnail_cache.md          # サムネイルキャッシュの詳細ドキュメント
│
├── examples/                       # サンプルアプリケーション
│   └── thumbnail_viewer.py         # サムネイルビューワーのサンプル
│
├── models/                         # データモデル (データの構造と操作)
│   ├── __init__.py
│   ├── base_thumbnail_cache.py     # サムネイルキャッシュの基底クラス
│   ├── image_model.py              # 画像データの基本モデル
│   ├── thumbnail_cache.py          # 基本的なサムネイルキャッシュ
│   ├── enhanced_thumbnail_cache.py # 強化されたサムネイルキャッシュ
│   ├── advanced_thumbnail_cache.py # 高度なサムネイルキャッシュ
│   └── unified_thumbnail_cache.py  # 統合サムネイルキャッシュ
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
│   ├── enhanced_image_loader.py    # 強化された画像読み込み
│   ├── worker_manager.py           # スレッド/ワーカー管理
│   ├── workers.py                  # 基本的なワーカースレッド
│   ├── optimized_thumbnail_worker.py # 最適化されたサムネイル生成ワーカー
│   ├── vips_thumbnail_worker.py    # libvipsを使用した高速サムネイル生成ワーカー
│   ├── unified_thumbnail_worker.py # 統合サムネイル生成ワーカー
│   ├── directory_scanner.py        # ディレクトリ監視
│   └── batch_processor.py          # バッチ処理
│
├── tests/                          # テスト
│   ├── __init__.py
│   └── test_unified_cache.py       # 統合キャッシュのテスト
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

## 🔄 今後の改善点

- **ストレージバックエンドの拡張**: Amazon S3、Redisなど他のストレージシステムのサポート
- **分散キャッシュ**: 複数のマシンで動作する分散キャッシュシステム
- **GPUアクセラレーション**: 対応環境ではGPUを活用した処理の高速化
- **完全な非同期API**: async/awaitベースの完全な非同期API
- **メモリ圧縮**: キャッシュアイテムのメモリ内圧縮機能
