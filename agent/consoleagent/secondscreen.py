"""Protocolo "Second Screen" do PS4 (TCP 997): abrir um jogo pelo código (CUSA…) sem navegar no menu.

Portado do ps4-waker (https://github.com/dhleong/ps4-waker, MIT License, Copyright (c) 2018 Daniel Leong).
Só funciona na rede local do console. O agente precisa ser registrado uma vez no PS4 com o PIN de
Configurações > Configurações de conexão do aplicativo móvel > Adicionar dispositivo.

Fluxo: UDP WAKEUP/LAUNCH (porta 987) → TCP 997 → ClientHello → ServerHello (semente) → Handshake (chave AES
cifrada com a chave pública RSA da Sony) → Login (cifrado) → BootRequest (código do jogo).
"""
from __future__ import annotations

import hashlib
import socket
import struct
import time

DDP_PORT, TCP_PORT, DDP_VERSION = 987, 997, '00020020'
PUBLIC_KEY = (b'-----BEGIN PUBLIC KEY-----\n'
              b'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxfAO/MDk5ovZpp7xlG9J\n'
              b'JKc4Sg4ztAz+BbOt6Gbhub02tF9bryklpTIyzM0v817pwQ3TCoigpxEcWdTykhDL\n'
              b'cGhAbcp6E7Xh8aHEsqgtQ/c+wY1zIl3fU//uddlB1XuipXthDv6emXsyyU/tJWqc\n'
              b'zy9HCJncLJeYo7MJvf2TE9nnlVm1x4flmD0k1zrvb3MONqoZbKb/TQVuVhBv7SM+\n'
              b'U5PSi3diXIx1Nnj4vQ8clRNUJ5X1tT9XfVmKQS1J513XNZ0uYHYRDzQYujpLWucu\n'
              b'ob7v50wCpUm3iKP1fYCixMP6xFm0jPYz1YQaMV35VkYwc40qgk3av0PDS+1G0dCm\n'
              b'swIDAQAB\n'
              b'-----END PUBLIC KEY-----\n')
HELLO, HANDSHAKE, LOGIN, LOGIN_RESULT, BOOT, BOOT_RESULT, STATUS, SERVER_STATUS, BYE = (
    0x6f636370, 32, 30, 7, 10, 11, 20, 18, 4)
LOGIN_ERRORS = {20: 'PIN necessário: registre o agente no PS4 (Configurações > Configurações de conexão do aplicativo móvel > '
                    'Adicionar dispositivo) e informe o PIN no painel.',
                22: 'O PS4 pede a senha de 4 dígitos do usuário.', 24: 'Senha de 4 dígitos incorreta.',
                30: 'O PS4 está ocupado com outro login; tente de novo em alguns segundos.'}
BOOT_ERRORS = {}


class SecondScreenError(Exception):
    pass


def credential_for(seed: str) -> str:
    """Credencial (64 hex) estável deste agente para um console. O PS4 a associa ao usuário no registro com PIN."""
    return hashlib.sha256(f'timedefora-agent:{seed}'.encode()).hexdigest()


def _ddp(kind: str, credential: str) -> bytes:
    return (f'{kind} * HTTP/1.1\nclient-type:a\nauth-type:C\nuser-credential:{credential}\n'
            f'device-discovery-protocol-version:{DDP_VERSION}\n').encode()


def _field(text: str, size: int) -> bytes:
    raw = (text or '').encode()[:size]
    return raw + b'\0' * (size - len(raw))


def _packet(kind: int, body: bytes = b'', size: int | None = None) -> bytes:
    total = size or 8 + len(body)
    data = struct.pack('<ii', total, kind) + body
    return data + b'\0' * (total - len(data))


class Session:
    """Uma conexão logada com o PS4. Use como contexto: with Session(host, cred) as s: s.boot('CUSA05904')."""

    def __init__(self, host: str, credential: str, pin: str = '', passcode: str = '', timeout: float = 10.0,
                 model: str = 'timedefora'):
        self.host, self.credential, self.pin, self.passcode = host, credential, pin, passcode
        self.timeout, self.model = timeout, model
        self.sock: socket.socket | None = None
        self._enc = self._dec = None

    # ------------------------------------------------------------ transporte
    def _recv_exact(self, n: int) -> bytes:
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise SecondScreenError('O PS4 encerrou a conexão.')
            buf += chunk
        return buf

    def _send(self, data: bytes, encrypted: bool = True) -> None:
        if encrypted:
            data += b'\0' * (-len(data) % 16)                    # mesmo preenchimento do app (zeros até 16)
            data = self._enc.update(data)
        self.sock.sendall(data)

    def _recv(self) -> tuple[int, bytes]:
        """Lê um pacote cifrado: decifra o 1º bloco para saber o tamanho e lê o restante (alinhado a 16)."""
        first = self._dec.update(self._recv_exact(16))
        length, kind = struct.unpack_from('<ii', first)
        if length < 8 or length > 65536:
            raise SecondScreenError(f'Resposta inesperada do PS4 (tamanho {length}).')
        rest = (length + 15) // 16 * 16 - 16
        data = first + (self._dec.update(self._recv_exact(rest)) if rest > 0 else b'')
        return kind, data[:length]

    def _expect(self, wanted: int, limit: float | None = None) -> bytes:
        deadline = time.monotonic() + (limit or self.timeout)
        while time.monotonic() < deadline:
            kind, data = self._recv()
            if kind == wanted:
                return data
            if kind == SERVER_STATUS:                               # batimento: responde para manter a conexão
                self._send(_packet(STATUS, struct.pack('<i', 0)))
        raise SecondScreenError('O PS4 não respondeu a tempo.')

    # ------------------------------------------------------------ sessão
    def open(self) -> 'Session':
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:  # pede ao PS4 para abrir a porta 997
            for kind in ('WAKEUP', 'LAUNCH'):
                udp.sendto(_ddp(kind, self.credential), (self.host, DDP_PORT))
        time.sleep(0.6)
        try:
            self.sock = socket.create_connection((self.host, TCP_PORT), timeout=self.timeout)
        except OSError as e:
            raise SecondScreenError(f'O PS4 não aceitou a conexão na porta {TCP_PORT} ({e}). Ele está ligado e na mesma rede?')
        self.sock.settimeout(self.timeout)
        self._send(_packet(HELLO, struct.pack('<ii', 0x20000, 0), 28), encrypted=False)
        head = self._recv_exact(8)
        length, kind = struct.unpack('<ii', head)
        if kind != HELLO or not 36 <= length <= 4096:
            raise SecondScreenError('O PS4 recusou o início da conexão.')
        hello = head + self._recv_exact(length - 8)
        if struct.unpack_from('<i', hello, 12)[0] != 0:
            raise SecondScreenError('O PS4 recusou o início da conexão.')
        seed = hello[20:36]
        key = bytes(16)                                             # a chave AES vai cifrada com a RSA da Sony
        rsa = serialization.load_pem_public_key(PUBLIC_KEY)
        blob = rsa.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
        cipher = Cipher(algorithms.AES(key), modes.CBC(seed))
        self._enc, self._dec = cipher.encryptor(), cipher.decryptor()
        self._send(_packet(HANDSHAKE, blob + seed, 280), encrypted=False)
        body = (_field(self.passcode, 4) + struct.pack('<i', 513) + _field(self.credential, 64) + _field('PlayStation', 256)
                + _field('4.4', 16) + _field(self.model, 16) + _field(self.pin, 16))
        self._send(_packet(LOGIN, body, 384))
        result = struct.unpack_from('<i', self._expect(LOGIN_RESULT), 8)[0]
        if result != 0:
            raise SecondScreenError(LOGIN_ERRORS.get(result, f'O PS4 recusou o login (código {result}).'))
        self._send(_packet(STATUS, struct.pack('<i', 0)))
        return self

    def boot(self, title_id: str) -> None:
        """Abre o jogo pelo código (ex.: CUSA05904). Se outro jogo estiver aberto, o PS4 pede para fechá-lo."""
        self._send(_packet(BOOT, _field(title_id.strip().upper(), 16)))
        result = struct.unpack_from('<i', self._expect(BOOT_RESULT, 30), 8)[0]
        if result != 0:
            raise SecondScreenError(f'O PS4 não abriu o jogo {title_id} (código {result}). O jogo está instalado neste console?')

    def close(self) -> None:
        if self.sock is not None:
            try:
                self._send(_packet(BYE))
            except Exception:
                pass
            self.sock.close()
            self.sock = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
