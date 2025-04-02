# 画像ビューワーアプリケーション

PySide6を使用した画像ビューワーアプリケーションです。

## 機能

- フォルダから画像ファイルを読み込み表示
- サムネイル表示とページネーション
- サムネイルキャッシュによる高速表示
- マルチスレッドによる非同期処理

## 必要条件

- Python 3.6以上
- PySide6

## インストール

```bash
# リポジトリをクローン
git clone https://github.com/your-username/picture-viewer.git
cd picture-viewer

# 依存関係をインストール
pip install -r requirements.txt
```

または、単にPySide6をインストールします：

```bash
pip install PySide6
```

## 使用方法

アプリケーションを起動するには：

```bash
python main.py
```

## プロジェクト構造

```
picture_viewer/
├── main.py                # エントリーポイント
├── models/                # データモデル
│   ├── __init__.py
│   ├── image_model.py     # 画像データモデル
│   └── thumbnail_cache.py # サムネイルキャッシュ
├── views/                 # ビューコンポーネント
│   ├── __init__.py
│   ├── main_window.py     # メインウィンドウ
│   └── image_grid_view.py # 画像グリッド表示
├── controllers/           # コントローラーロジック
│   ├── __init__.py
│   ├── image_loader.py    # 画像読み込み
│   ├── worker_manager.py  # スレッド管理
│   └── workers.py         # ワーカークラス
├── utils/                 # ユーティリティ関数
│   └── __init__.py
└── tests/                 # テストコード
    ├── __init__.py
    ├── test_image_model.py
    ├── test_thumbnail_cache.py
    ├── test_worker_manager.py
    └── run_all_tests.py
```

## テスト

テストを実行するには：

```bash
python -m tests.run_all_tests
```

または個別のテストを実行：

```bash
python -m tests.test_image_model
```

## MVCアーキテクチャ

このアプリケーションはModel-View-Controller (MVC)パターンを使用しています：

- **Model**: 画像データとメタデータ、サムネイルキャッシュを管理
- **View**: ユーザーインターフェースを提供
- **Controller**: モデルとビューの調整、処理ロジックを実装

## ライセンス

MITライセンスの下で公開されています。
