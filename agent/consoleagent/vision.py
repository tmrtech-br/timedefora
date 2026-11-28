"""Leitura da tela do console para os roteiros de abertura (no estilo das bibliotecas de teste de interface).

- Texto: OCR nativo do Windows (Windows.Media.Ocr, pacotes "winrt-*"). Sem os pacotes, os passos de texto
  falham com uma mensagem clara (os passos por imagem continuam funcionando).
- Imagem: procura uma imagem de referência (recorte salvo da própria tela do console) por correlação
  normalizada (numpy). Funciona em tons de cinza e tolera pequenas mudanças de brilho.
"""
from __future__ import annotations

import base64
import io
import re
import unicodedata
from dataclasses import dataclass

MATCH_THRESHOLD = 0.82          # correlação mínima para considerar a imagem de referência "na tela"
WORK_WIDTH = 640                # a busca por imagem roda numa cópia reduzida da tela (rápido)


class VisionUnavailable(Exception):
    pass


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e só letras/números separados por um espaço (para comparar textos do OCR)."""
    t = unicodedata.normalize('NFKD', text or '')
    t = ''.join(c for c in t if not unicodedata.combining(c)).casefold()
    return ' '.join(re.sub(r'[^0-9a-z]+', ' ', t).split())


def contains_text(screen_text: str, wanted: str) -> bool:
    """O texto procurado aparece na tela? Tolera erros pequenos do OCR (letra trocada, espaço a mais)."""
    w, s = normalize(wanted), normalize(screen_text)
    if not w:
        return False
    if w in s or w.replace(' ', '') in s.replace(' ', ''):
        return True
    # Tolerância só nas letras: números (Far Cry 4 x Far Cry 5) precisam ser iguais.
    from difflib import SequenceMatcher
    wanted_words, words = w.split(), s.split()
    n = len(wanted_words)
    for i in range(len(words) - n + 1):
        window = words[i:i + n]
        if any(a != b for a, b in zip(window, wanted_words) if any(c.isdigit() for c in a + b)):
            continue
        if SequenceMatcher(None, ' '.join(window), w).ratio() >= 0.85:
            return True
    return False


# ---------------------------------------------------------------- OCR
_engine = None


def _ocr_engine():
    global _engine
    if _engine is not None:
        return _engine
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
    except ImportError as e:
        raise VisionUnavailable('Leitura de texto indisponível neste agente: instale os pacotes do OCR do Windows '
                                '(pip install -r requirements.txt no agente).') from e
    engine = None
    for tag in ('pt-BR', 'pt', 'en-US'):
        try:
            lang = Language(tag)
            if OcrEngine.is_language_supported(lang):
                engine = OcrEngine.try_create_from_language(lang)
                if engine:
                    break
        except Exception:
            continue
    engine = engine or OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise VisionUnavailable('O Windows deste agente não tem idioma de OCR instalado (Configurações > Idioma > '
                                'Português (Brasil) > Reconhecimento óptico de caracteres).')
    _engine = engine
    return engine


def read_text(image) -> list[str]:
    """Linhas de texto na imagem (PIL). Levanta VisionUnavailable se o OCR não estiver disponível."""
    import asyncio
    engine = _ocr_engine()
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    img = image.convert('RGBA')
    if img.width < 1000:                                  # OCR erra menos com letras maiores
        img = img.resize((img.width * 2, img.height * 2))
    writer = DataWriter()
    writer.write_bytes(img.tobytes())
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8, img.width, img.height,
                                                     BitmapAlphaMode.PREMULTIPLIED)

    async def run():
        return await engine.recognize_async(bitmap)

    result = asyncio.run(run())
    return [line.text for line in result.lines]


# ---------------------------------------------------------------- imagem de referência
@dataclass
class Reference:
    name: str
    pixels: object             # numpy float32 em tons de cinza
    source_width: int          # largura da tela de onde o recorte saiu (para ajustar a escala)


def decode_reference(name: str, data: dict) -> Reference:
    import numpy as np
    from PIL import Image
    raw = base64.b64decode(str(data.get('png') or ''))
    img = Image.open(io.BytesIO(raw)).convert('L')
    return Reference(name, np.asarray(img, dtype='float32'), int(data.get('width') or 1280))


def _shrink(arr, factor: float):
    import numpy as np
    from PIL import Image
    if abs(factor - 1.0) < 0.01:
        return arr
    h, w = arr.shape
    img = Image.fromarray(np.clip(arr, 0, 255).astype('uint8'), 'L')
    return np.asarray(img.resize((max(1, round(w * factor)), max(1, round(h * factor)))), dtype='float32')


def match_score(screen_image, ref: Reference) -> float:
    """Maior correlação (0–1) da referência em qualquer ponto da tela."""
    import numpy as np
    screen = np.asarray(screen_image.convert('L'), dtype='float32')
    # mesma escala da tela em que o recorte foi feito, depois reduz tudo para a largura de trabalho
    tpl = _shrink(ref.pixels, screen.shape[1] / max(1, ref.source_width))
    k = min(1.0, WORK_WIDTH / screen.shape[1])
    s, t = _shrink(screen, k), _shrink(tpl, k)
    H, W = s.shape
    h, w = t.shape
    if h < 4 or w < 4 or h > H or w > W:
        return 0.0
    t0 = t - t.mean()
    tnorm = float(np.sqrt((t0 * t0).sum()))
    if tnorm < 1e-3:
        return 0.0                                          # recorte uniforme não identifica nada
    from numpy.fft import irfft2, rfft2
    corr = irfft2(rfft2(s) * rfft2(t0[::-1, ::-1], s.shape), s.shape)[h - 1:H, w - 1:W]
    ii = np.pad(s, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    ii2 = np.pad(s * s, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def window(a):
        return a[h:, w:] - a[:-h, w:] - a[h:, :-w] + a[:-h, :-w]

    total, total2 = window(ii), window(ii2)
    var = np.clip(total2 - total * total / (h * w), 0, None)
    denom = np.sqrt(var) * tnorm
    ncc = np.where(denom > 1e-3, corr / np.maximum(denom, 1e-3), 0.0)
    return float(np.clip(ncc.max(), 0, 1))


def png_base64(image) -> str:
    buf = io.BytesIO()
    image.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')
