# PyInstaller hook for turbovec
# turbovec is a native C extension with no Python package data,
# but we need to ensure its .pyd/.so binary is collected.
from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("turbovec")
hiddenimports = ["turbovec"]
