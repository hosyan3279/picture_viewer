# サムネイルキャッシュシステム

このドキュメントでは、画像ビューワーアプリケーションのサムネイルキャッシュシステムについて説明します。

## 概要

サムネイルキャッシュシステムは、画像のサムネイルを効率的に管理し、アプリケーションのパフォーマンスを向上させるための重要なコンポーネントです。このシステムは以下の機能を提供します：

- メモリとディスクの2層キャッシュによる高速アクセス
- SQLiteデータベースを使用したメタデータの管理
- スレッドセーフな操作によるマルチスレッド環境での安全性
- 自動メモリ最適化とLRU（Least Recently Used）アルゴリズム
- キャッシュヒット率などの詳細な統計情報

## キャッシュの種類

アプリケーションには以下の3つのキャッシュ実装があります：

1. **基本キャッシュ（ThumbnailCache）**: 基本的なメモリとディスクのキャッシュ機能を提供。JSONファイルでメタデータを管理。
2. **拡張キャッシュ（EnhancedThumbnailCache）**: 基本キャッシュに自動メモリ最適化機能を追加。
3. **高度キャッシュ（AdvancedThumbnailCache）**: SQLiteを使用した高性能なメタデータ管理を実装。

そして、これらのすべての良い点を統合した新しい実装があります：

4. **統合キャッシュ（UnifiedThumbnailCache）**: すべての実装の長所を組み合わせた最新のキャッシュシステム。SQLiteデータベース、スレッドセーフな操作、自動メモリ最適化、そして詳細な統計機能を備えています。

## 特長の比較

| 機能 | ThumbnailCache | EnhancedThumbnailCache | AdvancedThumbnailCache | UnifiedThumbnailCache |
|------|----------------|------------------------|------------------------|------------------------|
| メモリキャッシュ | ✓ | ✓ | ✓ | ✓ |
| ディスクキャッシュ | ✓ | ✓ | ✓ | ✓ |
| メタデータ保存 | JSON | JSON | SQLite | SQLite |
| 自動メモリ最適化 | - | ✓ | - | ✓ |
| スレッドセーフ | - | 部分的 | ✓ | ✓ |
| 詳細な統計情報 | 基本 | 基本 | 基本 | 詳細 |
| 無効エントリの自動削除 | ✓ | ✓ | - | ✓ |
| エラー処理 | 基本 | 基本 | 基本 | 高度 |
| 予測読み込み | - | - | - | ✓ |

## 使用方法

### 基本使用法

```python
from models.unified_thumbnail_cache import UnifiedThumbnailCache

# キャッシュのインスタンスを作成
cache = UnifiedThumbnailCache(
    memory_limit=200,  # メモリに保持するサムネイル数
    disk_cache_limit_mb=1000,  # ディスクキャッシュの上限（MB）
    cleanup_interval=60000  # クリーンアップ間隔（ミリ秒）
)

# サムネイルの取得
thumbnail = cache.get_thumbnail(image_path, (150, 150))
if thumbnail is not None:
    # キャッシュヒット - サムネイルを表示
    image_label.setPixmap(thumbnail)
else:
    # キャッシュミス - サムネイルを生成する必要がある
    # (後述のサムネイル生成ワーカーを使用)
    pass

# サムネイルの保存
cache.store_thumbnail(image_path, (150, 150), thumbnail)

# 統計情報の取得
stats = cache.get_stats()
print(f"メモリキャッシュ: {stats['memory_cache_count']}/{stats['memory_limit']} アイテム")
print(f"ディスクキャッシュ: {stats['disk_cache_size_mb']:.2f}MB/{stats['disk_cache_limit_mb']}MB")
print(f"ヒット率: {stats['hit_ratio']:.2f}%")

# キャッシュのクリア
cache.clear(clear_disk=True)  # ディスクキャッシュもクリア
```

### サムネイル生成ワーカーとの連携

```python
from controllers.unified_thumbnail_worker import UnifiedThumbnailWorker
from controllers.worker_manager import WorkerManager

# ワーカーマネージャーのインスタンスを作成
worker_manager = WorkerManager()

# サムネイル生成ワーカーを作成
worker = UnifiedThumbnailWorker(
    image_path,  # 元画像のパス
    (150, 150),  # サムネイルサイズ
    cache  # サムネイルキャッシュ
)

# 結果を受け取るコールバック
def on_thumbnail_created(result):
    path, thumbnail = result
    if thumbnail and not thumbnail.isNull():
        # サムネイルを表示
        image_label.setPixmap(thumbnail)

# シグナルを接続
worker.signals.result.connect(on_thumbnail_created)

# ワーカーを実行
worker_manager.start_worker(f"thumbnail_{image_path}", worker)
```

## サムネイル生成エンジン

`UnifiedThumbnailWorker`は、以下の3つのサムネイル生成エンジンを内蔵しています：

1. **PILエンジン**: Pythonの画像処理ライブラリであるPILを使用。バランスの取れた速度とメモリ効率を提供。
2. **VIPSエンジン**: 高速な画像処理ライブラリであるlibvipsを使用。特に大きなサイズの画像に効果的。
3. **Qtエンジン**: QImageとQPixmapを使用。依存関係が最も少なく、常に利用可能。

ワーカーは自動的に画像のサイズや特性に基づいて最適なエンジンを選択します。

## 設定パラメータ

キャッシュシステムは以下の設定パラメータをサポートしています：

### UnifiedThumbnailCache

- `memory_limit`: メモリキャッシュに保持するサムネイル数の上限（デフォルト: 200）
- `disk_cache_dir`: ディスクキャッシュのディレクトリパス（デフォルト: `~/.picture_viewer_cache`）
- `disk_cache_limit_mb`: ディスクキャッシュの上限（MB）（デフォルト: 1000）
- `cleanup_interval`: 自動クリーンアップの間隔（ミリ秒）（デフォルト: 60000）
- `db_path`: SQLiteデータベースのパス（デフォルト: ディスクキャッシュディレクトリ内）

### UnifiedThumbnailWorker

- `use_vips`: libvipsを使用するかどうか（デフォルト: 設定ファイルから）
- `size_threshold`: VIPSを使用する画像サイズの閾値（デフォルト: 5000ピクセル）
- `webp_quality`: WebP形式で保存する際の品質（デフォルト: 85）
- `jpeg_quality`: JPEG形式で保存する際の品質（デフォルト: 90）
- `fallback_to_qt`: 他のエンジンが失敗した場合にQtにフォールバックするかどうか（デフォルト: true）

## パフォーマンスの最適化

キャッシュシステムのパフォーマンスを最適化するためのヒント：

1. 適切なメモリ制限を設定する：アプリケーションで使用可能なメモリに応じて`memory_limit`を調整してください。
2. ディスクキャッシュの場所：高速なSSDを使用している場合は、そこにディスクキャッシュを配置することでパフォーマンスが向上します。
3. クリーンアップ間隔：頻繁なクリーンアップは不要なオーバーヘッドになる可能性があるため、60秒以上の間隔を推奨します。
4. PILとlibvipsのインストール：可能であれば、両方のライブラリをインストールすることで、より効率的なサムネイル生成が可能になります。

## エラー処理

キャッシュシステムは、以下のようなエラー状況に対応しています：

- ファイルの読み取り/書き込みエラー
- データベース操作エラー
- 無効な画像ファイル
- メモリ不足
- ディスク容量不足

エラーが発生した場合、キャッシュシステムはログに警告またはエラーメッセージを記録し、適切なフォールバック動作を実行します。
