"""Medições REAIS de imagem e áudio da janela do chiaki-ng (nada é estimado ou inventado).

- Imagem: captura a área da janela e mede brilho médio e variação; tela preta/uniforme = sem vídeo.
  Duas capturas seguidas medem se a imagem muda (movimento).
- Áudio: lê o medidor de pico do Windows para a sessão de áudio do processo do chiaki-ng (biblioteca pycaw).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import winutil

BLACK_MEAN, FLAT_STD = 8.0, 3.0


@dataclass
class Frame:
    ok: bool
    message: str
    mean: float | None = None
    std: float | None = None
    size: tuple[int, int] | None = None
    image: object = None

    def to_dict(self) -> dict:
        return {'ok': self.ok, 'mean': self.mean, 'std': self.std, 'size': self.size}


def frame(pid: int | None) -> Frame:
    w = winutil.main_window(pid)
    if not w:
        return Frame(False, 'Janela do chiaki-ng não encontrada (fechada ou minimizada).')
    img = winutil.grab(w.rect)
    if img is None:
        return Frame(False, 'Captura indisponível: instale o Pillow (pip install pillow).')
    from PIL import ImageStat
    g = img.convert('L')
    st = ImageStat.Stat(g)
    mean, std = round(st.mean[0], 1), round(st.stddev[0], 1)
    if mean < BLACK_MEAN and std < FLAT_STD:
        return Frame(False, f'Imagem preta ({w.size[0]}×{w.size[1]}): o console ainda não está transmitindo.', mean, std, w.size, g)
    if std < FLAT_STD:
        return Frame(False, f'Imagem uniforme ({w.size[0]}×{w.size[1]}, brilho {mean}): sem conteúdo do console.', mean, std, w.size, g)
    return Frame(True, f'Imagem recebida ({w.size[0]}×{w.size[1]}, brilho {mean}, variação {std}).', mean, std, w.size, g)


def motion(a: Frame, b: Frame) -> float | None:
    """Diferença média entre duas capturas (0 = imagem parada)."""
    if a.image is None or b.image is None or a.image.size != b.image.size:
        return None
    from PIL import ImageChops, ImageStat
    return round(ImageStat.Stat(ImageChops.difference(a.image, b.image)).mean[0], 2)


def audio_peak(pid: int | None, seconds: float = 1.5) -> tuple[float | None, str]:
    """Maior pico de áudio (0–1) do processo no período. None = não foi possível medir."""
    if not pid or not winutil.IS_WIN:
        return None, 'Medição de áudio indisponível (processo não encontrado ou sistema não Windows).'
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    except ImportError:
        return None, 'Medição de áudio indisponível: instale o pycaw (pip install pycaw).'
    comtypes.CoInitialize()
    try:
        meters = []
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.pid == pid:
                meters.append(s._ctl.QueryInterface(IAudioMeterInformation))
        if not meters:
            return 0.0, 'O chiaki-ng ainda não abriu uma saída de áudio.'
        peak, end = 0.0, time.monotonic() + seconds
        while time.monotonic() < end:
            peak = max(peak, *(m.GetPeakValue() for m in meters))
            time.sleep(0.05)
        peak = round(float(peak), 3)
        return peak, ('Áudio presente' if peak > 0.001 else 'Silêncio') + f' (pico {peak}).'
    except Exception as e:
        return None, f'Falha ao medir o áudio: {e}'
    finally:
        comtypes.CoUninitialize()
