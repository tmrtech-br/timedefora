"""LocaPlay ConsoleAgent — programa que roda no PC ao lado do console e faz a ponte com a API LocaPlay.

Parte 1 (esta versão): heartbeat, autenticação, saúde e descoberta REAL do PS4/PS5 na rede (protocolo de
descoberta do Remote Play). Pareamento, conexão, vídeo e controle (via chiaki-ng) chegam na Parte 2 e, até lá,
respondem "não disponível" — o agente nunca finge que algo funcionou.
"""
VERSION = '0.1.0'
