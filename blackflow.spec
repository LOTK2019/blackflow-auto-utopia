# pyinstaller blackflow.spec --noconfirm
from PyInstaller.utils.hooks import collect_all
from pathlib import Path
from tools.stage_engine import NATIVE_DLLS

ocr_data, ocr_bins, ocr_hidden = collect_all('rapidocr_onnxruntime')
engine = Path(SPECPATH) / 'vendor/maa'
if not (engine / 'MaaCore.dll').is_file():
    raise RuntimeError('先运行 tools/stage_engine.py 准备内置 MAA 引擎')
engine_bins = [(str(engine / name), 'maa') for name in NATIVE_DLLS]
engine_data = [(str(engine / 'resource'), 'maa/resource'), (str(engine / 'engine.json'), 'maa')]
ui = Analysis(['tools/exe_app.py'], pathex=['.'],
    binaries=ocr_bins + engine_bins, datas=ocr_data + engine_data + [('assets/no-ideal-icon-slot.png', 'assets')],
    hiddenimports=ocr_hidden + ['app'], excludes=['pytest', 'unittest'])
ui_pyz = PYZ(ui.pure)
ui_exe = EXE(ui_pyz, ui.scripts, [], exclude_binaries=True,
    name='自动实托邦', console=False, debug=False)

worker = Analysis(['tools/exe_worker.py'], pathex=['.'], binaries=[], datas=[], hiddenimports=[],
    excludes=['tkinter', 'cv2', 'numpy', 'rapidocr_onnxruntime', 'onnxruntime'])
worker_pyz = PYZ(worker.pure)
worker_exe = EXE(worker_pyz, worker.scripts, [], exclude_binaries=True,
    name='blackflow-worker', console=True, debug=False)

bundle = COLLECT(ui_exe, worker_exe, ui.binaries, ui.datas, worker.binaries, worker.datas,
    strip=False, upx=False, name='自动实托邦')
