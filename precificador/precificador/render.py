import io
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader


def fmt_preco(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def desenhar_pagina_overlay(pw, ph, posicoes_e_textos, config):
    """posicoes_e_textos: lista de (Posicao, texto). Retorna bytes de um PDF
    de 1 pagina (pw x ph) so com as etiquetas, pra mesclar com merge_page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    cor_texto = HexColor(config.cor_texto)
    cor_fundo = HexColor(config.cor_fundo)

    for pos, texto in posicoes_e_textos:
        y_rl = ph - (pos.y_top + pos.altura)
        c.setFillColor(cor_fundo)
        c.roundRect(pos.x, y_rl, pos.largura, pos.altura, 2, stroke=0, fill=1)
        c.setFillColor(cor_texto)
        c.setFont(config.fonte_nome, pos.fonte)
        c.drawString(pos.x + 3, y_rl + 2, texto)

    c.save()
    buf.seek(0)
    return buf


def gerar_apendice_faltantes(itens: list[tuple], titulo_catalogo: str) -> bytes:
    """itens: lista de (ref, descricao, preco). Gera paginas A4 com uma tabela
    REF / Descricao / Preco, pra anexar no final do PDF quando sobra item sem
    posicao encontrada no catalogo (comum em catalogo escaneado)."""
    W, H = A4
    MARGEM = 20 * mm
    LINHA_H = 7 * mm
    TITULO_COR = HexColor('#0B5FA5')
    FAIXA_COR = HexColor('#F2F2F2')

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    itens = sorted(itens, key=lambda r: str(r[0]))
    linhas_por_pagina = int((H - 45 * mm - MARGEM) / LINHA_H)
    total_paginas = max(1, -(-len(itens) // linhas_por_pagina))

    def cabecalho(pagina_num):
        c.setFillColor(TITULO_COR)
        c.setFont('Helvetica-Bold', 16)
        c.drawString(MARGEM, H - 18 * mm, f'Lista de referências sem preço no catálogo')
        c.setFont('Helvetica', 9)
        c.setFillColor(HexColor('#555555'))
        c.drawString(MARGEM, H - 24 * mm,
                      f'Itens de {titulo_catalogo} que existem na planilha mas não foram localizados nas imagens.')
        c.drawRightString(W - MARGEM, H - 18 * mm, f'Página {pagina_num} de {total_paginas}')
        y = H - 32 * mm
        c.setFillColor(TITULO_COR)
        c.rect(MARGEM, y - 2 * mm, W - 2 * MARGEM, LINHA_H, stroke=0, fill=1)
        c.setFillColor(HexColor('#FFFFFF'))
        c.setFont('Helvetica-Bold', 10)
        c.drawString(MARGEM + 2 * mm, y, 'REF')
        c.drawString(MARGEM + 30 * mm, y, 'DESCRIÇÃO')
        c.drawRightString(W - MARGEM - 2 * mm, y, 'PREÇO')
        return y - LINHA_H

    pagina = 1
    y = cabecalho(pagina)
    for i, (ref, desc, preco) in enumerate(itens):
        if y < MARGEM + LINHA_H:
            c.showPage()
            pagina += 1
            y = cabecalho(pagina)

        if i % 2 == 0:
            c.setFillColor(FAIXA_COR)
            c.rect(MARGEM, y - 1.5 * mm, W - 2 * MARGEM, LINHA_H, stroke=0, fill=1)

        c.setFillColor(HexColor('#0B5FA5'))
        c.setFont('Helvetica-Bold', 9)
        c.drawString(MARGEM + 2 * mm, y, str(ref))

        c.setFillColor(HexColor('#222222'))
        c.setFont('Helvetica', 8.5)
        desc_trunc = str(desc or '')
        max_w = 110 * mm
        while stringWidth(desc_trunc, 'Helvetica', 8.5) > max_w and len(desc_trunc) > 3:
            desc_trunc = desc_trunc[:-1]
        if desc_trunc != str(desc or ''):
            desc_trunc = desc_trunc[:-1] + '…'
        c.drawString(MARGEM + 30 * mm, y, desc_trunc)

        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(HexColor('#B5651D'))
        c.drawRightString(W - MARGEM - 2 * mm, y, fmt_preco(preco))

        y -= LINHA_H

    c.save()
    buf.seek(0)
    return buf.read()
