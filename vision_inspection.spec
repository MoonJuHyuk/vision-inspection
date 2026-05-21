# vision_inspection.spec  (GitHub Actions CI 빌드용)
from PyInstaller.utils.hooks import collect_all

datas_cv2, bins_cv2, hi_cv2 = collect_all('cv2')
datas_pil, bins_pil, hi_pil = collect_all('PIL')
datas_np,  bins_np,  hi_np  = collect_all('numpy')

a = Analysis(
    ['src/main.py'],
    pathex=['.'],
    binaries=bins_cv2 + bins_pil + bins_np,
    datas=datas_cv2 + datas_pil + datas_np,
    hiddenimports=hi_cv2 + hi_pil + hi_np + [
        'cv2', 'numpy', 'PIL', 'PIL.ImageFont', 'PIL.ImageDraw', 'PIL.Image',
        'updater',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='vision_inspection',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='vision_inspection',
)
