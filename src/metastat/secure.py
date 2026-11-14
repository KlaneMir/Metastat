"""Token encryption with Windows DPAPI.

Only the same Windows account on the same computer can read an encrypted token; a data file copied
to another computer or another user does not reveal the token. Windows holds the keys;
the program has no key or password of its own in the code.
"""
from __future__ import annotations

import base64
import sys

PREFIX = "dpapi:"
_ENTROPY = b"metastat-token-v1"  # extra DPAPI "salt", not a secret
# one message for every damaged or foreign ciphertext, so the kind of damage cannot be told apart
_UNREADABLE = ("The token cannot be decrypted: it was saved on another computer or another "
               "Windows account. Paste the token again in Settings.")


class SecureError(Exception):
    pass


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _UI_FORBIDDEN = 0x01

    def _protect(data: bytes) -> bytes:
        src, _b1 = _blob(data)
        ent, _b2 = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptProtectData(ctypes.byref(src), ctypes.c_wchar_p("Metastat"), ctypes.byref(ent),
                                         None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise SecureError("Windows could not encrypt the token (CryptProtectData).")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _unprotect(data: bytes) -> bytes:
        src, _b1 = _blob(data)
        ent, _b2 = _blob(_ENTROPY)
        out = _Blob()
        if not _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent),
                                           None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise SecureError(_UNREADABLE)
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)
else:  # pragma: no cover - the program is for Windows
    def _protect(data: bytes) -> bytes:
        raise SecureError("Token encryption works only on Windows.")

    def _unprotect(data: bytes) -> bytes:
        raise SecureError("Token encryption works only on Windows.")


def encrypt(token: str) -> str:
    return PREFIX + base64.b64encode(_protect(token.encode("utf-8"))).decode("ascii")


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith(PREFIX):
        raise SecureError("Unknown format of the saved token.")
    try:
        data = base64.b64decode(value[len(PREFIX):], validate=True)
    except ValueError:  # binascii.Error: broken base64 gets the same error as any other damage
        raise SecureError(_UNREADABLE) from None
    return _unprotect(data).decode("utf-8")


def mask(token: str | None) -> str:
    """For display: only the start and the last 4 characters."""
    if not token:
        return "none"
    return f"{token[:4]}…{token[-4:]}" if len(token) > 12 else "…"
