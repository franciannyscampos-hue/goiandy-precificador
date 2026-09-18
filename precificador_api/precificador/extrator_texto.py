"""
Extrai as ocorrencias de REF de uma pagina de catalogo com texto nativo (nao
escaneado), usando pdfplumber. Cobre os dois formatos que ja vimos na pratica:

  - REF em duas palavras: "REF." depois "194-MX" (ou "Referencia:" depois "10724")
  - REF grudada num token so: "REF.217-TR" (sem espaco depois do ponto)

Devolve uma lista de dicts: {codigo, x0, x1, top, bottom} -- tudo em pontos PDF,
origem no TOPO da pagina (padrao pdfplumber).
"""
import re


def extrair_refs_pagina(words: list[dict], config) -> list[dict]:
    refs = []
    rotulo = _rotulo_da_regex(config.ref_regex)

    for idx, w in enumerate(words):
        texto = w['text']

        if config.ref_em_duas_palavras:
            if texto == rotulo and idx + 1 < len(words):
                nxt = words[idx + 1]
                # alguns catalogos tem um token do meio entre o rotulo e o codigo,
                # tipo "REF" / "120ml:" / "UT21-43" (tamanho no meio) -- se configurado,
                # pula esse token do meio e usa o proximo como codigo
                if config.token_meio_regex and re.match(config.token_meio_regex, nxt['text']):
                    if idx + 2 < len(words):
                        codigo_tok = words[idx + 2]
                        if abs(codigo_tok['top'] - w['top']) < 3:
                            refs.append({'codigo': codigo_tok['text'], 'x0': w['x0'], 'x1': codigo_tok['x1'],
                                         'top': w['top'], 'bottom': w['bottom']})
                    continue
                if abs(nxt['top'] - w['top']) < 3:
                    codigo = nxt['text'].rstrip(':')
                    refs.append({'codigo': codigo, 'x0': w['x0'], 'x1': nxt['x1'],
                                 'top': w['top'], 'bottom': w['bottom']})
                    continue

        if config.prefixo_grudado and texto.startswith(config.prefixo_grudado) and len(texto) > len(config.prefixo_grudado):
            codigo = texto[len(config.prefixo_grudado):]
            refs.append({'codigo': codigo, 'x0': w['x0'], 'x1': w['x1'],
                         'top': w['top'], 'bottom': w['bottom']})

    return refs


def _rotulo_da_regex(ref_regex: str) -> str:
    """Extrai o texto fixo do inicio da regex (ex: r'REF\\.\\s*' -> 'REF.').
    Para configs simples onde ref_regex e so o rotulo (ex: 'REF.', 'Referência:')."""
    # nas configs de exemplo, ref_regex guarda o rotulo exato usado no catalogo
    return ref_regex


def limites_da_linha(words: list[dict], ref: dict, pw: float) -> dict:
    """Acha o token mais proximo a esquerda, a direita e acima da REF, na mesma
    linha (comparando o centro vertical, pra nao pegar linha vizinha por engano)."""
    centro = (ref['top'] + ref['bottom']) / 2
    limite_esq = 0.0
    limite_dir = pw - 5
    teto_livre = 0.0

    for w in words:
        w_centro = (w['top'] + w['bottom']) / 2
        mesma_linha = abs(w_centro - centro) < 3
        if mesma_linha and w['x1'] < ref['x0']:
            limite_esq = max(limite_esq, w['x1'])
        if mesma_linha and w['x0'] > ref['x1']:
            limite_dir = min(limite_dir, w['x0'])
        if w['bottom'] <= ref['top'] and w['x0'] < ref['x1'] + 300 and w['x1'] > ref['x0'] - 300:
            teto_livre = max(teto_livre, w['bottom'])

    return {'esquerda': limite_esq, 'direita': limite_dir, 'teto': teto_livre}
