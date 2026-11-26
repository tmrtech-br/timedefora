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


def move_offscreen(w: Window) -> tuple[int, int] | None:
    """Tira a janela da área visível (à direita de todos os monitores) sem minimizar: o Windows continua
    compondo o conteúdo, então PrintWindow segue capturando. Devolve a posição original (para reveal)."""
    if not IS_WIN or not w:
        return None
    rc = wintypes.RECT()
    if not _user32.GetWindowRect(w.hwnd, ctypes.byref(rc)):
        return None
    x = _user32.GetSystemMetrics(76) + _user32.GetSystemMetrics(78) + 200     # SM_XVIRTUALSCREEN + SM_CXVIRTUALSCREEN
    if rc.left >= x - 200:
        return None                                                             # já está fora da tela
    # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
    _user32.SetWindowPos(w.hwnd, 0, x, rc.top, 0, 0, 0x0001 | 0x0004 | 0x0010)
    return rc.left, rc.top


def move_to(w: Window, pos: tuple[int, int]) -> None:
    if IS_WIN and w and pos:
        _user32.SetWindowPos(w.hwnd, 0, pos[0], pos[1], 0, 0, 0x0001 | 0x0004 | 0x0010)


def press_key(name: str, hold: float = 0.08) -> None:
    if not IS_WIN:
        raise OSError('Envio de teclas só existe no Windows.')
    vk = VK.get(name.lower())
    if vk is None:
        raise ValueError(f'Tecla desconhecida: {name}')
    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def grab_window_rgb(w: Window):
    """Conteúdo da PRÓPRIA janela (PrintWindow com renderização completa), mesmo coberta por outra janela.
    Matriz numpy RGB do tamanho da área cliente, ou None (fora do Windows, janela minimizada ou falha)."""
    if not IS_WIN or not w:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    gdi = ctypes.windll.gdi32
    width, height = w.size
    if width <= 0 or height <= 0:
        return None
    hdc_win = _user32.GetDC(w.hwnd)
    hdc = gdi.CreateCompatibleDC(hdc_win)
    bmp = gdi.CreateCompatibleBitmap(hdc_win, width, height)
    old = gdi.SelectObject(hdc, bmp)
    try:
        # 1 = PW_CLIENTONLY, 2 = PW_RENDERFULLCONTENT (necessário para janelas com aceleração de vídeo)
        if not _user32.PrintWindow(w.hwnd, hdc, 1 | 2):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                        ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long), ('biYPelsPerMeter', ctypes.c_long),
                        ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]
        bi = BITMAPINFOHEADER()
        bi.biSize, bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = ctypes.sizeof(bi), width, -height, 1, 32
        buf = ctypes.create_string_buffer(width * height * 4)
        if not gdi.GetDIBits(hdc, bmp, 0, height, buf, ctypes.byref(bi), 0):
            return None
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 4)
        return np.ascontiguousarray(arr[:, :, 2::-1])           # BGRA → RGB
    finally:
        gdi.SelectObject(hdc, old)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(hdc)
        _user32.ReleaseDC(w.hwnd, hdc_win)


def capture_window(w: Window):
    """Imagem RGB da janela: primeiro o conteúdo da própria janela (resiste a janelas por cima); se vier preta
    (alguns renderizadores de vídeo não respondem ao PrintWindow), usa a captura da região da tela."""
    arr = grab_window_rgb(w)
    if arr is not None and arr.size and float(arr.mean()) >= 2.0:
        return arr
    arr2 = grab_rgb(w.rect)
    if arr2 is not None:
        return arr2
    img = grab(w.rect)
    if img is None:
        return arr
    import numpy as np
    return np.asarray(img.convert('RGB'))


_tls = __import__('threading').local()


def grab_rgb(rect: tuple[int, int, int, int]):
    """Captura rápida (biblioteca mss, ~16 ms) como matriz numpy RGB; None se mss/numpy não estiverem instalados."""
    try:
        import mss
        import numpy as np
    except ImportError:
        return None
    sct = getattr(_tls, 'sct', None)
    if sct is None:                                   # mss não pode ser compartilhado entre threads
        sct = _tls.sct = (getattr(mss, 'MSS', None) or mss.mss)()
    shot = sct.grab({'left': rect[0], 'top': rect[1], 'width': rect[2] - rect[0], 'height': rect[3] - rect[1]})
    return np.asarray(shot)[:, :, 2::-1]              # BGRA → RGB


def grab(rect: tuple[int, int, int, int]):
    """Captura a região da tela (PIL.Image) ou None se o Pillow não estiver instalado."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return None
    return ImageGrab.grab(bbox=rect, all_screens=True)
