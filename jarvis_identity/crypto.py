import os


MAGIC = b"JID1"


def protect(payload):
    value = bytes(payload)
    if os.name != "nt":
        return value
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte)))

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = (ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob),
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(ctypes.byref(source), "JARVIS identity", None, None, None, 1, ctypes.byref(target)):
        raise OSError("DPAPI non ha cifrato i dati biometrici")
    try:
        return MAGIC + ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def unprotect(payload):
    value = bytes(payload)
    if os.name != "nt" or not value.startswith(MAGIC):
        return value
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte)))

    encrypted = value[len(MAGIC):]
    buffer = ctypes.create_string_buffer(encrypted)
    source = Blob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = (ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("DPAPI non ha decifrato i dati biometrici")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))
