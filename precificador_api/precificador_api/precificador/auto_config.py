"""
Gera uma CatalogConfig automaticamente, sem precisar de calibracao manual por
industria. Funciona bem na maioria dos casos porque descobrimos que dá pra casar
a REF direto contra os codigos da planilha de preco, sem precisar saber onde/como
o catalogo escreve um rotulo tipo "REF." na frente do codigo (ver testes com
Maxximo, KE Home, Unita e Clio -- taxa de acerto ficou perto da versao calibrada
a mao em todos).

Uso tipico (a partir de um Excel bruto, ex. linha de comando/chat):

    from precificador.auto_config import detectar_config
    config = detectar_config('planilha.xlsx', 'catalogo.pdf')
    if config is None:
        print("Nao consegui detectar as colunas da planilha automaticamente --
               precisa calibrar manualmente essa industria.")
    else:
        resultado = processar_catalogo('catalogo.pdf', config, 'saida.pdf')

Quando o sistema já tem os produtos vindos prontos do banco (reference + price
separados, como no goiandy-catalogo-sistema via D1), NÃO precisa nem dessa
deteccao de coluna -- so usar config_padrao() direto com PrecoLookup.from_produtos.
"""
import re
import openpyxl
from .config import CatalogConfig
from .pipeline import eh_catalogo_escaneado

PALAVRAS_COL_REF = ['referen', 'refer', 'cod', r'\bref\b']
PALAVRAS_COL_PRECO = ['preç', 'prec', 'valor', 'price']


def config_padrao(nome: str, escaneado: bool = False) -> CatalogConfig:
    """Config generica que funciona pra qualquer catalogo com texto nativo (ou
    escaneado, se OCR), sem nenhuma calibracao manual: casa direto contra os
    codigos da planilha (sem_rotulo=True)."""
    return CatalogConfig(
        nome=nome,
        ref_regex='',
        sem_rotulo=True,
        tentar_sufixo_invertido=True,
        tentar_so_numero=True,
        escaneado=escaneado,
    )


def _detectar_colunas(ws) -> tuple[int, int] | None:
    """Acha a coluna de referencia e a de preco pelo cabecalho (primeira linha
    nao vazia). Devolve None se nao conseguir com confianca."""
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        cabecalho = row
        break
    else:
        return None

    col_ref = col_preco = None
    for i, val in enumerate(cabecalho):
        if val is None:
            continue
        v = str(val).strip().lower()
        if col_ref is None and any(re.search(p, v) for p in PALAVRAS_COL_REF):
            col_ref = i
        if col_preco is None and any(re.search(p, v) for p in PALAVRAS_COL_PRECO):
            col_preco = i

    if col_ref is None or col_preco is None:
        return None
    return col_ref, col_preco


def detectar_config(excel_path: str, pdf_path: str, nome: str = 'auto') -> CatalogConfig | None:
    wb = openpyxl.load_workbook(excel_path, data_only=True)

    for ws in wb.worksheets:
        cols = _detectar_colunas(ws)
        if cols is None:
            continue
        col_ref, col_preco = cols
        # confirma que a aba realmente tem dados nessas colunas (nao só cabecalho)
        tem_dado = False
        for row in ws.iter_rows(min_row=2, max_row=5, values_only=True):
            if len(row) > max(col_ref, col_preco) and row[col_ref] and row[col_preco] is not None:
                tem_dado = True
                break
        if not tem_dado:
            continue

        escaneado = eh_catalogo_escaneado(pdf_path)
        config = config_padrao(nome, escaneado=escaneado)
        config.excel_aba = ws.title
        config.excel_col_ref = col_ref
        config.excel_col_preco = col_preco
        return config

    return None
