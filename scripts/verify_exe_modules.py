import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "dist/QoderGateway.exe"
data = open(path, "rb").read()
print(f"exe size: {len(data)/1024/1024:.1f} MB")

for name in [
    "DrissionPage", "DrissionPage.items", "DownloadKit", "tldextract",
    "websocket", "lxml", "cssselect", "win32gui", "win32process", "pywintypes",
    "qoder2api/static", "registrar",
]:
    hit = name.encode() in data
    print(f"  {'OK ' if hit else 'MISS'} {name}")
