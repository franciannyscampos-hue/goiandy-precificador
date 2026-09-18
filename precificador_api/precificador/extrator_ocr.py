"""
Extrai ocorrencias de REF de uma pagina ESCANEADA (sem texto nativo), via OCR.

Licoes aprendidas na pratica (catalogo Goller, 174 paginas):
  - Nunca manda a pagina inteira pro Tesseract de uma vez: ele se confunde em
    paginas com varios produtos/fotos e le so uma fracao, silenciosamente.
    Corta em N tiras horizontais com sobreposicao e junta o resultado.
  - --psm 6 (bloco uniforme de texto) funciona muito melhor que o modo padrao
    pra esse tipo de pagina densa.
  - Quando a REF aparece mais de uma vez na pagina (ex: uma vez na horizontal,
    do lado do codigo de barras; outra vez vertical, rotacionada, do lado da
    foto), so a ocorrencia com um "par" numerico por perto (o codigo de barras
    secundario) e a certa pra por preco -- a outra e so decorativa/rotulo.
"""
import re
import pytesseract
from PIL import Image


def ocr_pagina(im: Image.Image, config) -> list[dict]:
    """Roda OCR em tiras e devolve tokens deduplicados: {text, x0, x1, top, bottom}
    em PIXELS da imagem renderizada (converter pra pontos PDF depois, ver pipeline)."""
    w_img, h_img = im.size
    n = config.ocr_n_tiras
    overlap = config.ocr_overlap
    tokens = []

    for i in range(n):
        y0 = max(0, int(h_img * (i / n - overlap)))
        y1 = min(h_img, int(h_img * ((i + 1) / n + overlap)))
        crop = im.crop((0, y0, w_img, y1))
        data = pytesseract.image_to_data(crop, lang=config.ocr_lang,
                                          config=f'--psm {config.ocr_psm}',
                                          output_type=pytesseract.Output.DICT)
        for j in range(len(data['text'])):
            t = data['text'][j].strip()
            if t:
                tokens.append({
                    'text': t,
                    'x0': data['left'][j], 'top': data['top'][j] + y0,
                    'x1': data['left'][j] + data['width'][j],
                    'bottom': data['top'][j] + data['height'][j] + y0,
                })

    return _dedup(tokens)


def _dedup(tokens, tol=8):
    out = []
    for tok in tokens:
        dup = any(
            tok['text'] == t2['text'] and abs(tok['top'] - t2['top']) < tol and abs(tok['x0'] - t2['x0']) < tol
            for t2 in out
        )
        if not dup:
            out.append(tok)
    return out


def extrair_refs(tokens: list[dict], config) -> list[dict]:
    refs = []
    for tok in tokens:
        m = re.match(config.ref_regex, tok['text'].upper())
        if not m:
            continue
        codigo = tok['text'].upper()

        if config.exige_par_numerico:
            centro = (tok['top'] + tok['bottom']) / 2
            tem_par = any(
                re.match(config.par_numerico_regex, t2['text']) and
                abs((t2['top'] + t2['bottom']) / 2 - centro) < 15 and
                0 < t2['x0'] - tok['x1'] < config.par_distancia_max_pt
                for t2 in tokens if t2 is not tok
            )
            if not tem_par:
                continue

        refs.append({'codigo': codigo, 'x0': tok['x0'], 'x1': tok['x1'],
                     'top': tok['top'], 'bottom': tok['bottom']})
    return refs


def limites_da_linha(tokens, ref, largura_img):
    centro = (ref['top'] + ref['bottom']) / 2
    limite_esq = 0.0
    limite_dir = largura_img - 5
    teto_livre = 0.0
    for tok in tokens:
        t_centro = (tok['top'] + tok['bottom']) / 2
        mesma_linha = abs(t_centro - centro) < 15
        if mesma_linha and tok['x1'] < ref['x0']:
            limite_esq = max(limite_esq, tok['x1'])
        if mesma_linha and tok['x0'] > ref['x1']:
            limite_dir = min(limite_dir, tok['x0'])
        if tok['bottom'] <= ref['top'] and tok['x0'] < ref['x1'] + 300 and tok['x1'] > ref['x0'] - 300:
            teto_livre = max(teto_livre, tok['bottom'])
    return {'esquerda': limite_esq, 'direita': limite_dir, 'teto': teto_livre}


def area_em_branco(im: Image.Image, x0, y0_top, largura, altura) -> bool:
    """Confere se a regiao (em pixels) e mesmo fundo branco, e nao uma foto/embalagem
    -- essencial antes de aceitar uma posicao 'acima' ou 'esquerda' em pagina escaneada,
    ja que ausencia de TEXTO ali nao quer dizer ausencia de IMAGEM."""
    left, top = max(0, int(x0)), max(0, int(y0_top))
    right, bottom = min(im.width, int(x0 + largura)), min(im.height, int(y0_top + altura))
    if right <= left or bottom <= top:
        return True
    regiao = im.crop((left, top, right, bottom)).convert('L')
    hist = regiao.histogram()
    total = sum(hist)
    if total == 0:
        return True
    claros = sum(hist[235:])
    return (claros / total) > 0.9
