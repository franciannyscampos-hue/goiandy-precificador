"""
Onde colocar a etiqueta de preco, dado:
  - a caixa (x0,x1,top,bottom) do codigo da REF, em pontos PDF (origem no TOPO da pagina)
  - a lista de "tokens" da pagina (palavras com x0,x1,top,bottom) pra saber o que
    tem por perto e nao encostar em nada
  - opcionalmente, uma imagem da pagina renderizada, pra confirmar que a area
    escolhida e realmente fundo branco (texto ausente != area livre -- pode ser foto)

Regra de ouro (ver o prompt geral): o preco tem que ficar visualmente ligado, sem
ambiguidade, ao codigo da REF certa. Por isso a ordem de tentativa e sempre:
ESQUERDA do codigo -> DIREITA do codigo -> ACIMA da linha -> ultimo recurso
(fonte minima, aceita ficar apertado, mas isso e sinalizado pra revisao).
"""
from dataclasses import dataclass
from reportlab.pdfbase.pdfmetrics import stringWidth
from typing import Optional, Callable


@dataclass
class Estilo:
    fonte_nome: str = 'Helvetica-Bold'
    fonte_tamanho: float = 10
    fonte_tamanho_min: float = 8
    pad_x: float = 3
    pad_y: float = 2
    gap: float = 5


@dataclass
class Posicao:
    modo: str  # 'esquerda' | 'direita' | 'acima' | 'apertado'
    x: float
    y_top: float  # topo da caixa, em pontos, a partir do TOPO da pagina
    largura: float
    altura: float
    fonte: float


def _cabe(texto, fonte_nome, fonte, pad_x, espaco_disponivel):
    largura = stringWidth(texto, fonte_nome, fonte)
    return largura + 2 * pad_x <= espaco_disponivel, largura


def _reduzir_ate_caber(texto, estilo: Estilo, espaco_disponivel):
    fonte = estilo.fonte_tamanho
    cabe, largura = _cabe(texto, estilo.fonte_nome, fonte, estilo.pad_x, espaco_disponivel)
    while not cabe and fonte > estilo.fonte_tamanho_min:
        fonte -= 0.5
        cabe, largura = _cabe(texto, estilo.fonte_nome, fonte, estilo.pad_x, espaco_disponivel)
    return cabe, fonte, largura


def escolher_posicao(
    texto: str,
    ref_x0: float, ref_x1: float, ref_top: float, ref_bottom: float,
    limite_esquerda: float,  # x1 do token mais proximo a esquerda, na mesma linha (ou 0)
    limite_direita: float,   # x0 do token mais proximo a direita, na mesma linha (ou largura da pagina)
    teto_livre: float,       # bottom do token mais proximo acima (ou 0)
    estilo: Estilo,
    verificar_branco: Optional[Callable[[float, float, float, float], bool]] = None,
) -> Posicao:
    """verificar_branco(x0_pt, y0_top_pt, largura_pt, altura_pt) -> bool.
    Se None, todo candidato que couber por texto e aceito (uso tipico: catalogo com
    texto nativo, sem necessidade de checar imagem). Passe a funcao quando estiver
    processando pagina escaneada, onde "sem texto" nao quer dizer "sem foto"."""
    linha_h = ref_bottom - ref_top
    candidatos = []

    # 1) esquerda
    espaco_esq = ref_x0 - estilo.gap - estilo.pad_x - limite_esquerda
    cabe, fonte, largura = _reduzir_ate_caber(texto, estilo, espaco_esq)
    if cabe:
        box_w = largura + 2 * estilo.pad_x
        box_h = max(linha_h, fonte + 2 * estilo.pad_y)
        candidatos.append(Posicao('esquerda', ref_x0 - estilo.gap - box_w, ref_top, box_w, box_h, fonte))

    # 2) direita
    espaco_dir = limite_direita - (ref_x1 + estilo.gap) - estilo.pad_x
    cabe, fonte, largura = _reduzir_ate_caber(texto, estilo, espaco_dir)
    if cabe:
        box_w = largura + 2 * estilo.pad_x
        box_h = max(linha_h, fonte + 2 * estilo.pad_y)
        candidatos.append(Posicao('direita', ref_x1 + estilo.gap, ref_top, box_w, box_h, fonte))

    # 3) acima da linha
    fonte = estilo.fonte_tamanho
    box_h = fonte + 2 * estilo.pad_y
    box_w = stringWidth(texto, estilo.fonte_nome, fonte) + 2 * estilo.pad_x
    espaco_vert = ref_top - teto_livre
    if espaco_vert >= box_h + 4:
        y_top = ref_top - 3 - box_h
        candidatos.append(Posicao('acima', ref_x0, y_top, box_w, box_h, fonte))

    for cand in candidatos:
        if verificar_branco is None or verificar_branco(cand.x, cand.y_top, cand.largura, cand.altura):
            return cand

    # 4) ultimo recurso -- direita, fonte minima, aceita apertar (fica marcado pra revisao)
    fonte = estilo.fonte_tamanho_min
    largura = stringWidth(texto, estilo.fonte_nome, fonte)
    box_w = largura + 2 * estilo.pad_x
    box_h = max(linha_h, fonte + 2 * estilo.pad_y)
    return Posicao('apertado', ref_x1 + estilo.gap, ref_top, box_w, box_h, fonte)
