"""Windows user-bound DPAPI protection without prompts or machine-wide keys."""

import ctypes
from ctypes import wintypes


class Blob(ctypes.Structure):
    """Represent the documented Win32 DATA_BLOB ABI on x86-64 and ARM64."""

    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(value: bytes, *, decrypt: bool = False) -> bytes:
    """Protect or unprotect bytes for this Windows user, failing if DPAPI is unavailable."""
    loader = getattr(ctypes, "WinDLL")  # Windows-only API; POSIX callers never use this backend.
    crypt = loader("crypt32", use_last_error=True)
    kernel = loader("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    # UI_FORBIDDEN=1. Never set LOCAL_MACHINE, which would allow other users to decrypt.
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Windows credential protection failed.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)
