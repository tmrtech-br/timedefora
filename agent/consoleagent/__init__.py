"""LocaPlay ConsoleAgent — programa que roda no PC ao lado do console e faz a ponte com a API LocaPlay.

Parte 1: heartbeat, autenticação, saúde e descoberta REAL do PS4/PS5 (protocolo de descoberta do Remote Play).
Parte 2: acordar o console, conectar pelo chiaki-ng (direto ou PSN), controle virtual DS4, preparação com roteiro
para abrir o jogo e testes reais de imagem/áudio/controle. O agente nunca finge que algo funcionou.
"""
VERSION = '0.2.0'
