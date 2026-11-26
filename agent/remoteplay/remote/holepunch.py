# SPDX-License-Identifier: AGPL-3.0-only
"""Seleção verificável de pares UDP (peça de NAT traversal da PSN).

Referência: chiaki-ng/lib/src/remote/holepunch.c (select candidate / sockets ctrl/data).
O desafio/resposta específico Sony e as ofertas via PSN dependem do porte
completo do Session Manager; esta classe só declara êxito após VERIFICAR
uma resposta recebida do peer, nunca após um sendto() bem-sucedido.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class Candidate:
    address: str
    port: int
    kind: str = 'STATIC'

    def __post_init__(self):
        ipaddress.ip_address(self.address)
        if not 1 <= self.port <= 65535 or self.kind not in ('STATIC', 'LOCAL'):
            raise ValueError('Candidato PSN inválido.')


class _ProbeReceiver(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=32)

    def datagram_received(self, data, addr):
        try:
            self.queue.put_nowait((data, addr))
        except asyncio.QueueFull:
            pass


class PunchFailed(ConnectionError):
    pass


class CandidatePunch:
    """Socket de controle ou de dados por console, mantido aberto após o furo.

    NÃO cria ofertas Sony e NÃO converte testes locais em prova PSN.
    O callback verifier deve validar a autenticação/assinatura do protocolo.
    """
    def __init__(self, *, local_port=0):
        self.local_port = local_port
        self.transport = None
        self.receiver = None
        self.peer = None

    async def open(self):
        if self.transport:
            raise RuntimeError('Socket já aberto.')
        loop = asyncio.get_running_loop()
        self.transport, self.receiver = await loop.create_datagram_endpoint(
            _ProbeReceiver, local_addr=('0.0.0.0', self.local_port))
        self.local_port = self.transport.get_extra_info('sockname')[1]
        return self

    async def punch(self, candidates: list[Candidate], challenge: bytes,
                    verifier: Callable[[bytes, tuple[str, int]], bool], *,
                    timeout=3.0, interval=0.2) -> Candidate:
        if not self.transport:
            raise RuntimeError('Socket não aberto.')
        if not candidates or not 1 <= len(challenge) <= 1400:
            raise ValueError('Candidatos/challenge inválidos.')
        if verifier is None:
            raise ValueError('Verificador de resposta obrigatório: não é permitido simular sucesso.')
        allowed = {(c.address, c.port) for c in candidates}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            for c in candidates:
                self.transport.sendto(challenge, (c.address, c.port))
            try:
                data, addr = await asyncio.wait_for(self.receiver.queue.get(), min(interval, max(0.001, deadline - loop.time())))
            except asyncio.TimeoutError:
                continue
            if addr in allowed and verifier(data, addr):
                self.peer = addr
                return next(c for c in candidates if (c.address, c.port) == addr)
        raise PunchFailed('Nenhum candidato UDP respondeu com prova válida. O console remoto não foi conectado.')

    async def close(self):
        if self.transport:
            self.transport.close()
            self.transport = None
        self.peer = None
