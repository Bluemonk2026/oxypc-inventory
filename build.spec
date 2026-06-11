# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for OxyPC Inventory
# Build: pyinstaller build.spec

import os
block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('config.py', '.'),
        ('database.py', '.'),
        ('models', 'models'),
        ('routers', 'routers'),
        ('auth', 'auth'),
    ],
    hiddenimports=[
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.logging',
        'asyncpg',
        'asyncpg.pgproto',
        'asyncpg.pgproto.pgproto',
        'asyncpg.protocol',
        'asyncpg.protocol.protocol',
        'passlib.handlers.bcrypt',
        'jose',
        'jose.jwt',
        'multipart',
        'aiofiles',
        'jinja2',
        'sqlalchemy.dialects.postgresql',
        'sqlalchemy.ext.asyncio',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
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
    name='OxyPC_Inventory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
