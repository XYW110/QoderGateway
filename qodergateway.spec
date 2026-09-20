# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：QoderGateway 单文件 exe
# 构建命令（项目根目录）：
#   .venv\Scripts\pyinstaller.exe --clean -y qodergateway.spec
#
# 注意：registrar.py 里 DrissionPage 是函数内延迟导入，PyInstaller 静态分析容易漏抓；
# 其生态（DownloadKit / tldextract / websocket-client / lxml / cssselect）同样多为
# 深层或动态导入，统一用 collect_all 整包收集，漏一个 exe 里注册机就 BrowserConnectError。
# 本地构建机若没装这些包（如临时 venv），对应 collect_all 自动跳过，不影响其他部分打包。

from PyInstaller.utils.hooks import collect_all

block_cipher = None

_datas: list = []
_binaries: list = []
_hidden: list = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

# 注册机浏览器栈：整包收集（含 DrissionPage 自带 ini 配置等数据文件）
for _pkg in ("DrissionPage", "DownloadKit", "tldextract", "websocket", "cssselect"):
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        continue
    _datas += _d
    _binaries += _b
    _hidden += _h

# Windows 窗口控制（registrar 的置顶/隐藏依赖 pywin32）
_hidden += [
    "win32api", "win32gui", "win32process", "win32con", "win32com", "pythoncom", "pywintypes",
]

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=_binaries,
    datas=[
        # 打包前端静态资源：打包后位于 _MEIPASS/qoder2api/static
        ("src/qoder2api/static", "qoder2api/static"),
    ] + _datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="QoderGateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=None,
)
