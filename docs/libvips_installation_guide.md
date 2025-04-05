# libvips インストールガイド

このガイドでは、picture_viewerアプリケーションで使用している高速画像処理ライブラリ「libvips」のインストール方法について説明します。

## libvipsとは

libvipsは、メモリ使用を最小限に抑えながら非常に高速に動作する画像処理ライブラリです。大きなサイズの画像を処理する際に特に効果を発揮し、一般的なライブラリと比較して：

- **処理速度**: 同等の処理が約3〜4倍高速
- **メモリ使用量**: 最大で1/10程度に削減可能
- **マルチコア活用**: 自動的にCPUの全コアを効率的に活用

## インストール手順

### Windows

1. **libvipsのダウンロード**:
   - [libvips公式リリースページ](https://github.com/libvips/libvips/releases)から最新の`vips-dev-w64-all-x.y.z.zip`（64ビット版）をダウンロードします。
   - または、[prebuilt Windows binaries](https://www.libvips.org/install.html)からインストーラー版をダウンロードします。

2. **インストール**:
   - インストーラー版の場合: ダウンロードしたインストーラーを実行し、指示に従ってインストールします。
   - ZIP版の場合: ダウンロードしたZIPファイルを展開し、任意の場所（例: `C:\Program Files\vips`）に配置します。

3. **環境変数の設定**:
   - インストーラー版は自動的に環境変数を設定します。
   - ZIP版の場合は、以下の手順で環境変数を設定する必要があります：
     1. 「システムのプロパティ」→「環境変数」を開く
     2. システム変数の「Path」を選択して「編集」
     3. 「新規」をクリックし、libvipsのbinディレクトリへのパス（例: `C:\Program Files\vips\bin`）を追加
     4. 「OK」をクリックして全ての画面を閉じる

4. **確認**:
   - コマンドプロンプトを開き、`vips --version`を実行してインストールを確認します。
   - 正しくインストールされていれば、libvipsのバージョン情報が表示されます。

### macOS

1. **Homebrewを使用したインストール**:
   ```bash
   brew install vips
   ```

2. **確認**:
   ```bash
   vips --version
   ```

### Linux (Ubuntu/Debian)

1. **パッケージマネージャーを使用したインストール**:
   ```bash
   sudo apt-get update
   sudo apt-get install libvips-dev
   ```

2. **確認**:
   ```bash
   vips --version
   ```

### Linux (Fedora/RHEL/CentOS)

1. **パッケージマネージャーを使用したインストール**:
   ```bash
   sudo dnf install vips-devel
   ```
   または古いバージョンの場合:
   ```bash
   sudo yum install vips-devel
   ```

2. **確認**:
   ```bash
   vips --version
   ```

## Python パッケージ (pyvips) のインストール

libvipsをインストールした後、Pythonバインディングである`pyvips`をインストールする必要があります。

```bash
pip install pyvips
```

または、アプリケーションの依存関係をインストールする場合:

```bash
pip install -r requirements.txt
```

## 動作確認

libvipsが正しくインストールされているか確認するには、以下のPythonコードを実行してください：

```python
import pyvips

# バージョン情報を表示
print(f"libvips バージョン: {pyvips.version()}")
print(f"pyvips バージョン: {pyvips.__version__}")

# 簡単な画像処理テスト
try:
    # テスト画像を生成
    black = pyvips.Image.black(100, 100)
    
    # 赤色に着色
    red = black.add([255, 0, 0]).cast("uchar")
    
    # PNG形式で保存
    red.write_to_file("test_red.png")
    print("テスト画像が正常に生成されました：test_red.png")
except Exception as e:
    print(f"エラーが発生しました: {e}")
```

このコードが正常に実行され、赤い正方形の画像が生成されれば、libvipsは正しく動作しています。

## トラブルシューティング

### インポートエラー

```
ImportError: No module named 'pyvips'
```

**解決策**: `pip install pyvips` を実行して、Pythonバインディングをインストールしてください。

### ライブラリロードエラー

```
ImportError: DLL load failed: 指定されたモジュールが見つかりません。
```

**解決策**: 
1. libvipsが正しくインストールされていることを確認
2. システム環境変数のPathにlibvipsのbinディレクトリが含まれていることを確認
3. コンピューターを再起動（環境変数の変更を反映するため）

### バージョンの互換性問題

```
pyvips.error.Error: unable to load library
```

**解決策**: libvipsとpyvipsのバージョンが互換性のあることを確認してください。最新バージョンのpyvipsをインストールすることで解決することが多いです：

```bash
pip install --upgrade pyvips
```

### その他の問題

libvipsに関するその他の問題については、[公式ドキュメント](https://libvips.github.io/libvips/)や[GitHub Issues](https://github.com/libvips/libvips/issues)を参照してください。
