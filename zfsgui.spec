# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(['zfsgui.py'],
             pathex=['/Users/rejsmont/PycharmProjects/pyzfs'],
             binaries=[],
             datas=[( 'assets', 'assets' )],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='zfsgui',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False , icon='zfsgui.icns')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='zfsgui')
app = BUNDLE(coll,
             name='zfsgui.app',
             icon='zfsgui.icns',
             bundle_identifier=None,
             info_plist={
                'NSHighResolutionCapable': 'True',
                'LSUIElement': True
             })
