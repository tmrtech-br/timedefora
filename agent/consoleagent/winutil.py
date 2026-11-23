"""Utilitários do Windows (ctypes, sem dependências): janelas de um processo, foco, teclas e captura de imagem.

Fora do Windows as funções retornam vazio/None — o agente informa "não disponível" em vez de fingir.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

IS_WIN = sys.platform == 'win32'

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    try:  # coordenadas reais de tela em monitores com escala (125%, 150%...)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass

VK = {'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09, 'space': 0x20,
      'backspace': 0x08, 'f11': 0x7A, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22}
KEYEVENTF_KEYUP = 0x0002


@dataclass
class Window:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]    # área cliente em coordenadas de tela (esq, topo, dir, base)

    @property
    def size(self) -> tuple[int, int]:
        return self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]


def windows_of_pid(pid: int | None) -> list[Window]:
    """Janelas visíveis do processo, maior primeiro."""
    if not IS_WIN or not pid:
        return []
    found: list[Window] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return True
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        rc = wintypes.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(rc))
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        if rc.right > 50 and rc.bottom > 50:
            found.append(Window(int(hwnd), buf.value, (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)))
        return True

    _user32.EnumWindows(cb, 0)
    return sorted(found, key=lambda w: w.size[0] * w.size[1], reverse=True)


def main_window(pid: int | None) -> Window | None:
    ws = windows_of_pid(pid)
    return ws[0] if ws else None


def focus(w: Window) -> bool:
    if not IS_WIN:
        return False
    _user32.ShowWindow(w.hwnd, 9)                 # SW_RESTORE
    _user32.keybd_event(0x12, 0, 0, 0)            # ALT: libera a troca de foco imposta pelo Windows
    _user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
    ok = bool(_user32.SetForegroundWindow(w.hwnd))
    time.sleep(0.2)
    return ok


def press_key(name: str, hold: float = 0.08) -> None:
    if not IS_WIN:
        raise OSError('Envio de teclas só existe no Windows.')
    vk = VK.get(name.lower())
    if vk is None:
        raise ValueError(f'Tecla desconhecida: {name}')
    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def grab(rect: tuple[int, int, int, int]):
    """Captura a região da tela (PIL.Image) ou None se o Pillow não estiver instalado."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return None
    return ImageGrab.grab(bbox=rect, all_screens=True)
