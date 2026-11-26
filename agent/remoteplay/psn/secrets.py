# SPDX-License-Identifier: AGPL-3.0-only
"""Windows per-user DPAPI encryption for PSN credentials. Never write unencrypted tokens.

The same Windows user that encrypted the file must run the agent in subsequent launches.
There is deliberately no plaintext fallback for Linux, CI, or Windows service accounts.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class DpapiError(RuntimeError):
    pass


class WindowsDpapi:
    def __init__(self):
        if os.name != 'nt':
            raise DpapiError('A proteção de contas PSN requer Windows e DPAPI; Linux não salva tokens.')
        self.crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    @staticmethod
    def _blob_type():
        class DataBlob(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
        return DataBlob

    def _process(self, data: bytes, encrypt: bool) -> bytes:
        if not data:
            raise DpapiError('Dados de credencial vazios.')
        blob = self._blob_type()
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source = blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        output = blob()
        func = self.crypt32.CryptProtectData if encrypt else self.crypt32.CryptUnprotectData
        func.argtypes = ([ctypes.POINTER(blob), ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(blob)] if encrypt else
                         [ctypes.POINTER(blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(blob)])
        func.restype = wintypes.BOOL
        if not func(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(output)):
            raise DpapiError('A criptografia DPAPI falhou. Use o mesmo usuário Windows do cadastro.')
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            self.kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))

    def encrypt(self, value: bytes) -> bytes:
        return self._process(value, True)

    def decrypt(self, value: bytes) -> bytes:
        return self._process(value, False)
