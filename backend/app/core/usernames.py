"""Formato e moderação dos nomes que aparecem publicamente."""
import re

USERNAME_RE = re.compile(r'[A-Za-z0-9_.]{3,24}')
LEETSPEAK = str.maketrans('013457', 'oieast')
TOKEN_TERMS = frozenset({
    'arrombado', 'arrombada', 'bicha', 'bichona', 'bosta', 'buceta', 'cacete', 'caralho',
    'cuzao', 'cuzona', 'desgracado', 'desgracada', 'foda', 'foder', 'fodase', 'fudido',
    'fudida', 'merda', 'piranha', 'porra', 'puta', 'puto', 'traveco', 'viado', 'viada', 'veado',
    'vagabundo', 'vagabunda', 'nazista', 'fuck', 'fucking', 'shit', 'bitch',
})
EMBEDDED_TERMS = (
    'filhodaputa', 'filhadaputa', 'fdp', 'tomarnocu', 'vaipraporra', 'putaquepariu',
    'arrombado', 'arrombada', 'buceta', 'caralho', 'cuzao', 'cuzona', 'fodase', 'fudido', 'fudida',
    'traveco', 'sapatona', 'macacopreto', 'negroimundo', 'pretolixo', 'nigger', 'faggot',
    'heilhitler', 'supremaciabranca', 'whitesupremacy', 'matargay', 'odeiogay', 'killgays',
    'matarnordestino', 'nordestinodelixo', 'odeionordestino', 'foraimigrantes', 'imigranteslixo',
)


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.fullmatch(username):
        return 'Use 3 a 24 letras, números, "_" ou ".".'

    # Os separadores delimitam palavras comuns, mas não escondem termos fragmentados.
    tokens = re.split(r'[_.]+', username.lower())
    for part in [*tokens, ''.join(tokens)]:
        without_number = re.sub(r'^\d+|\d+$', '', part)
        variants = {part, without_number, part.translate(LEETSPEAK), without_number.translate(LEETSPEAK)}
        if any(
            candidate.removesuffix('s') in TOKEN_TERMS or any(term in candidate for term in EMBEDDED_TERMS)
            for candidate in variants
        ):
            return 'Escolha um nome público sem palavrões, insultos ou conteúdo discriminatório.'
    return None
