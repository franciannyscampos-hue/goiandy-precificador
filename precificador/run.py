#!/usr/bin/env python3
"""
Uso:
    python run.py --config configs/maxximo.json --pdf catalogo.pdf --excel precos.xlsx --out saida.pdf

    # catalogo escaneado grande: processa em lotes pra nao estourar tempo/memoria
    python run.py --config configs/goller.json --pdf catalogo.pdf --excel precos.xlsx \\
        --out saida.pdf --lote-inicio 1 --lote-fim 15

Gera automaticamente um apendice (paginas extras no final) com os itens da
planilha que nao foram encontrados no catalogo, se sobrar algum.
"""
import argparse
import sys
from precificador import CatalogConfig, processar_catalogo, gerar_apendice_faltantes, juntar_pdfs
from precificador.render import fmt_preco
from pypdf import PdfReader, PdfWriter
import io
import openpyxl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True, help='JSON de configuracao da industria (ver /configs)')
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--excel', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--lote-inicio', type=int, default=1)
    ap.add_argument('--lote-fim', type=int, default=None)
    ap.add_argument('--sem-apendice', action='store_true', help='nao gerar lista de faltantes no final')
    args = ap.parse_args()

    config = CatalogConfig.carregar(args.config)
    config.excel_path = args.excel

    print(f'Processando {args.pdf} com a config "{config.nome}"...')
    relatorio = processar_catalogo(args.pdf, config, args.out,
                                    pagina_inicial=args.lote_inicio, pagina_final=args.lote_fim)

    print()
    print(relatorio.relatorio())

    if not args.sem_apendice:
        wb = openpyxl.load_workbook(args.excel, data_only=True)
        ws = wb[config.excel_aba] if config.excel_aba else wb.active
        todos = {}
        for row in ws.iter_rows(min_row=config.excel_linha_inicial, values_only=True):
            if len(row) <= max(config.excel_col_ref, config.excel_col_preco):
                continue
            ref, preco = row[config.excel_col_ref], row[config.excel_col_preco]
            desc = row[2] if len(row) > 2 else ''
            if ref and preco is not None:
                todos[str(ref).strip().upper()] = (desc, preco)

        faltantes = sorted(set(todos.keys()) - relatorio.refs_detectadas_no_pdf)
        if faltantes:
            print(f'\n{len(faltantes)} refs da planilha nao encontradas no catalogo -> gerando apendice...')
            itens = [(ref, todos[ref][0], todos[ref][1]) for ref in faltantes]
            apendice_bytes = gerar_apendice_faltantes(itens, config.nome)

            reader_principal = PdfReader(args.out)
            reader_apendice = PdfReader(io.BytesIO(apendice_bytes))
            writer = PdfWriter()
            for p in reader_principal.pages:
                writer.add_page(p)
            for p in reader_apendice.pages:
                writer.add_page(p)
            with open(args.out, 'wb') as f:
                writer.write(f)
            print(f'Apendice com {len(faltantes)} itens anexado ({len(reader_apendice.pages)} paginas extras).')

    print(f'\nPronto: {args.out}')


if __name__ == '__main__':
    main()
