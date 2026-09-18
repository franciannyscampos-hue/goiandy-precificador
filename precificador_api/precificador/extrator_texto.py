"""
Extrai as ocorrencias de REF de uma pagina de catalogo com texto nativo (nao
escaneado), usando pdfplumber. Cobre os dois formatos que ja vimos na pratica:

  - REF em duas palavras: "REF." depois "194-MX" (ou "Referencia:" depois "10724")
  - REF grudada num token so: "REF.217-TR" (sem espaco depois do ponto)

Devolve uma lista de dicts: {codigo, x0, x1, top, bottom} -- tudo em pontos PDF,
origem no TOPO da pagina (padrao pdfplumber).
"""
import re


def extrair_refs_pagina(words: list[dict], config, refs_conhecidas: set = None) -> list[dict]:
    refs = []

    # modo "por correspondencia": nao tem rotulo nenhum (tipo "REF.") na frente do
    # codigo -- o codigo aparece sozinho, perto do produto. Casa direto contra os
    # codigos que ja existem na planilha (ver config.sem_rotulo). Esse e o modo
    # PADRAO agora -- funciona bem mesmo sem calibrar a industria (ver auto_config.py).
    if getattr(config, 'sem_rotulo', False) and refs_conhecidas:
        candidatos = []
        for w in words:
            t = w['text'].strip().upper()
            if t in refs_conhecidas:
                candidatos.append({'codigo': t, 'x0': w['x0'], 'x1': w['x1'],
                                    'top': w['top'], 'bottom': w['bottom']})

        # se o mesmo codigo aparece mais de uma vez na pagina (comum: uma ocorrencia
        # "de verdade" ao lado do codigo de barras, outra so decorativa perto da foto),
        # prefere a que tem um numero curto do lado (padrao de linha de codigo de barras)
        por_codigo: dict[str, list[dict]] = {}
        for r in candidatos:
            por_codigo.setdefault(r['codigo'], []).append(r)

        for codigo, ocorrencias in por_codigo.items():
            if len(ocorrencias) == 1:
                refs.append(ocorrencias[0])
            else:
                refs.append(_escolher_melhor_ocorrencia(ocorrencias, words))

        return refs

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


def _escolher_melhor_ocorrencia(ocorrencias: list[dict], words: list[dict]) -> dict:
    """Quando o mesmo codigo aparece 2+ vezes na pagina, prefere a ocorrencia que
    tem um numero curto por perto (padrao de linha de codigo de barras -- ver
    catalogo Goller: a REF aparece 1x na linha do codigo de barras -- essa e a
    certa -- e 1x decorativa/vertical do lado da foto -- essa nao)."""
    for oc in ocorrencias:
        centro = (oc['top'] + oc['bottom']) / 2
        for w in words:
            if w is oc:
                continue
            w_centro = (w['top'] + w['bottom']) / 2
            if abs(w_centro - centro) < 3 and 0 < w['x0'] - oc['x1'] < 120 and re.match(r'^\d{3,6}$', w['text']):
                return oc
    return ocorrencias[0]


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
