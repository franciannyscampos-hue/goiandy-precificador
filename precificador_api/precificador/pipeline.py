"""
Ponto de entrada principal. Uso tipico:

    from precificador.config import CatalogConfig
    from precificador.pipeline import processar_catalogo

    config = CatalogConfig.carregar('configs/maxximo.json')
    config.excel_path = 'tabela_de_preco_maxximo.xlsx'
    resultado = processar_catalogo('catalogo_maxximo.pdf', config, 'saida.pdf')
    print(resultado.relatorio())

Detecta sozinho se o PDF tem texto nativo ou e escaneado (checando se
pdfplumber extrai algum texto das primeiras paginas) e usa o caminho certo.
Para escaneado, processa em lotes pequenos (esse e o gargalo de tempo) --
quem estiver rodando isso num ambiente com timeout curto por chamada (tipo
dentro de uma function/job serverless) deve chamar `processar_lote` varias
vezes e juntar os PDFs no final com `juntar_pdfs`.
"""
import subprocess
import os
from dataclasses import dataclass, field
from pypdf import PdfReader, PdfWriter
import pdfplumber
from PIL import Image

from .matcher import PrecoLookup
from .placement import Estilo, escolher_posicao
from .extrator_texto import extrair_refs_pagina, limites_da_linha as limites_texto
from .extrator_ocr import ocr_pagina, extrair_refs as extrair_refs_ocr, limites_da_linha as limites_ocr, area_em_branco
from .render import desenhar_pagina_overlay, gerar_apendice_faltantes, fmt_preco

DPI_OCR = 150
REF_A4_ALTURA = 842.0  # referencia p/ escalar fonte quando o MediaBox da pagina foge do padrao


@dataclass
class Relatorio:
    encontrados: int = 0
    nao_encontrados: list = field(default_factory=list)  # (pagina, codigo)
    casamentos_especiais: list = field(default_factory=list)  # (pagina, codigo, motivo)
    avisos_apertado: list = field(default_factory=list)  # (pagina, texto)
    refs_detectadas_no_pdf: set = field(default_factory=set)

    def relatorio(self) -> str:
        linhas = [
            f'Precos inseridos: {self.encontrados}',
            f'Sem preco na planilha: {len(self.nao_encontrados)}',
            f'Casamentos especiais (sufixo invertido / so numero): {len(self.casamentos_especiais)}',
            f'Avisos (posicao apertada): {len(self.avisos_apertado)}',
        ]
        return '\n'.join(linhas)


def eh_catalogo_escaneado(pdf_path: str, n_paginas_teste=3) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:n_paginas_teste]:
            if (page.extract_text() or '').strip():
                return False
    return True


def processar_catalogo(pdf_path: str, config, out_path: str, pagina_inicial=1, pagina_final=None, lookup=None) -> Relatorio:
    config.excel_lookup = lookup if lookup is not None else PrecoLookup(config)
    relatorio = Relatorio()

    reader = PdfReader(pdf_path)
    n_paginas = len(reader.pages)
    fim = pagina_final or n_paginas
    writer = PdfWriter()

    escaneado = config.escaneado
    with pdfplumber.open(pdf_path) as doc:
        for i in range(pagina_inicial - 1, fim):
            page_plumber = doc.pages[i]
            if escaneado:
                _processar_pagina_ocr(pdf_path, i, page_plumber, reader, writer, config, relatorio)
            else:
                _processar_pagina_texto(page_plumber, reader, writer, config, relatorio)

    with open(out_path, 'wb') as f:
        writer.write(f)

    return relatorio


# --------------------------------------------------------------------------
# texto nativo
# --------------------------------------------------------------------------

def _processar_pagina_texto(page_plumber, reader, writer, config, relatorio):
    words = page_plumber.extract_words()
    pw, ph = page_plumber.width, page_plumber.height
    idx = page_plumber.page_number - 1

    refs = extrair_refs_pagina(words, config, refs_conhecidas=config.excel_lookup.todas_as_refs())
    estilo = Estilo(config.fonte_nome, config.fonte_tamanho, config.fonte_tamanho_min)

    posicoes = []
    for ref in refs:
        resultado = config.excel_lookup.buscar(ref['codigo'])
        relatorio.refs_detectadas_no_pdf.add(ref['codigo'].upper())
        if resultado.preco is None:
            relatorio.nao_encontrados.append((idx + 1, ref['codigo']))
            continue
        if resultado.motivo != 'exato':
            relatorio.casamentos_especiais.append((idx + 1, ref['codigo'], resultado.motivo))
        relatorio.encontrados += 1

        lim = limites_texto(words, ref, pw)
        pos = escolher_posicao(
            fmt_preco(resultado.preco),
            ref['x0'], ref['x1'], ref['top'], ref['bottom'],
            lim['esquerda'], lim['direita'], lim['teto'],
            estilo, verificar_branco=None,
        )
        if pos.modo == 'apertado':
            relatorio.avisos_apertado.append((idx + 1, fmt_preco(resultado.preco)))
        posicoes.append((pos, fmt_preco(resultado.preco)))

    base_page = reader.pages[idx]
    if posicoes:
        overlay_buf = desenhar_pagina_overlay(pw, ph, posicoes, config)
        base_page.merge_page(PdfReader(overlay_buf).pages[0])
    writer.add_page(base_page)


# --------------------------------------------------------------------------
# escaneado / OCR
# --------------------------------------------------------------------------

def _pagina_para_imagem(pdf_path, pagina_1based, tmp_dir='/tmp/precificador_paginas'):
    os.makedirs(tmp_dir, exist_ok=True)
    img_path = f'{tmp_dir}/pg_{pagina_1based:04d}.png'
    if not os.path.exists(img_path):
        prefixo = f'{tmp_dir}/pg_{pagina_1based:04d}'
        subprocess.run(['pdftoppm', '-f', str(pagina_1based), '-l', str(pagina_1based),
                         '-png', '-r', str(DPI_OCR), pdf_path, prefixo],
                        check=True, capture_output=True)
        cands = [f for f in os.listdir(tmp_dir) if f.startswith(f'pg_{pagina_1based:04d}-')]
        if cands:
            os.rename(os.path.join(tmp_dir, cands[0]), img_path)
    return Image.open(img_path)


def _processar_pagina_ocr(pdf_path, idx, page_plumber, reader, writer, config, relatorio):
    pagina_1based = idx + 1
    pw, ph = page_plumber.width, page_plumber.height
    im = _pagina_para_imagem(pdf_path, pagina_1based)

    tokens = ocr_pagina(im, config)
    refs = extrair_refs_ocr(tokens, config)

    escala_px_pt = 72.0 / DPI_OCR
    escala_fonte = ph / REF_A4_ALTURA  # paginas com MediaBox fora do padrao precisam disso

    estilo = Estilo(
        config.fonte_nome,
        config.fonte_tamanho * escala_fonte,
        config.fonte_tamanho_min * escala_fonte,
        pad_x=3 * escala_fonte, pad_y=2 * escala_fonte, gap=5 * escala_fonte,
    )

    def verificar_branco_pt(x_pt, y_top_pt, largura_pt, altura_pt):
        return area_em_branco(
            im, x_pt / escala_px_pt, y_top_pt / escala_px_pt,
            largura_pt / escala_px_pt, altura_pt / escala_px_pt,
        )

    posicoes = []
    for ref in refs:
        resultado = config.excel_lookup.buscar(ref['codigo'])
        relatorio.refs_detectadas_no_pdf.add(ref['codigo'].upper())
        if resultado.preco is None:
            relatorio.nao_encontrados.append((pagina_1based, ref['codigo']))
            continue
        if resultado.motivo != 'exato':
            relatorio.casamentos_especiais.append((pagina_1based, ref['codigo'], resultado.motivo))
        relatorio.encontrados += 1

        lim = limites_ocr(tokens, ref, im.width)
        texto = fmt_preco(resultado.preco)

        pos = escolher_posicao(
            texto,
            ref['x0'] * escala_px_pt, ref['x1'] * escala_px_pt,
            ref['top'] * escala_px_pt, ref['bottom'] * escala_px_pt,
            lim['esquerda'] * escala_px_pt, lim['direita'] * escala_px_pt, lim['teto'] * escala_px_pt,
            estilo, verificar_branco=verificar_branco_pt,
        )
        if pos.modo == 'apertado':
            relatorio.avisos_apertado.append((pagina_1based, texto))
        posicoes.append((pos, texto))

    base_page = reader.pages[idx]
    if posicoes:
        overlay_buf = desenhar_pagina_overlay(pw, ph, posicoes, config)
        base_page.merge_page(PdfReader(overlay_buf).pages[0])
    writer.add_page(base_page)


def juntar_pdfs(caminhos: list[str], out_path: str):
    writer = PdfWriter()
    for caminho in caminhos:
        r = PdfReader(caminho)
        for p in r.pages:
            writer.add_page(p)
    with open(out_path, 'wb') as f:
        writer.write(f)
    return len(writer.pages)
