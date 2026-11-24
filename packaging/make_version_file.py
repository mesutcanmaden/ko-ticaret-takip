"""PyInstaller için Windows sürüm bilgisi dosyası üretir (EXE > Özellikler > Ayrıntılar)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.paths import APP_NAME, APP_PUBLISHER, APP_VERSION  # noqa: E402

parts = [int(x) for x in APP_VERSION.split(".")] + [0]
v = tuple((parts + [0, 0, 0, 0])[:4])
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041f04b0', [
      StringStruct('CompanyName', {APP_PUBLISHER!r}),
      StringStruct('FileDescription', {APP_NAME + ' - Knight Online item alış-satış takip programı'!r}),
      StringStruct('FileVersion', {APP_VERSION!r}),
      StringStruct('InternalName', 'KOTicaretTakip'),
      StringStruct('LegalCopyright', {'© 2026 ' + APP_PUBLISHER!r}),
      StringStruct('OriginalFilename', 'KOTicaretTakip.exe'),
      StringStruct('ProductName', {APP_NAME!r}),
      StringStruct('ProductVersion', {APP_VERSION!r})])]),
    VarFileInfo([VarStruct('Translation', [0x041f, 1200])])
  ]
)
"""
out = ROOT / "packaging" / "version_info.txt"
out.write_text(text, encoding="utf-8")
print(APP_VERSION)
