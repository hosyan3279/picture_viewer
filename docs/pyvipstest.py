import pyvips

# バージョン情報を表示
print(f"libvips バージョン: {pyvips.version(0)}")
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
