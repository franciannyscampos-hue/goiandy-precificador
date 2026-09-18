"""
Casamento entre a REF encontrada no catalogo e a linha certa da planilha de preco.

Ordem de tentativa (nunca pula etapa, nunca inventa preco):
1. Exato
2. Sufixo invertido (A-B <-> B-A), se configurado
3. So pelo numero, SOMENTE se esse numero aparecer em uma unica linha da planilha
   (senao seria ambiguo -- ver PrecoLookup._indexar_por_numero)
"""
import re
import openpyxl
from dataclasses import dataclass
from typing import Optional


@dataclass
class ResultadoBusca:
    preco: Optional[float]
    motivo: Optional[str]  # 'exato' | 'sufixo invertido' | 'so pelo numero (...)' | None


class PrecoLookup:
    def __init__(self, config):
        self.config = config
        self.precos: dict[str, float] = {}
        self._carregar_planilha()
        self._indexar_por_numero()

    def _carregar_planilha(self):
        wb = openpyxl.load_workbook(self.config.excel_path, data_only=True)
        ws = wb[self.config.excel_aba] if self.config.excel_aba else wb.active
        c_ref, c_preco = self.config.excel_col_ref, self.config.excel_col_preco
        for row in ws.iter_rows(min_row=self.config.excel_linha_inicial, values_only=True):
            if len(row) <= max(c_ref, c_preco):
                continue
            ref, preco = row[c_ref], row[c_preco]
            if ref and preco is not None:
                self.precos[str(ref).strip().upper()] = preco

    @classmethod
    def from_produtos(cls, produtos: list[dict], config):
        """Constroi o lookup a partir de uma lista ja pronta ([{reference, price}, ...]),
        sem ler nenhum arquivo Excel -- usado pelo servico HTTP, que recebe os
        produtos direto do banco de dados do sistema (ja vem parseado de la)."""
        obj = cls.__new__(cls)
        obj.config = config
        obj.precos = {}
        for p in produtos:
            ref, preco = p.get('reference'), p.get('price')
            if ref and preco is not None:
                obj.precos[str(ref).strip().upper()] = preco
        obj._indexar_por_numero()
        return obj

    def _indexar_por_numero(self):
        self.by_num = {}
        ambiguos = set()
        for ref in self.precos:
            m = re.search(r'(\d+)', ref)
            if not m:
                continue
            n = m.group(1)
            if n in self.by_num and self.by_num[n] != ref:
                ambiguos.add(n)
            self.by_num[n] = ref
        for n in ambiguos:
            self.by_num.pop(n, None)

    def buscar(self, codigo: str) -> ResultadoBusca:
        codigo_norm = codigo.strip().upper()

        if codigo_norm in self.precos:
            return ResultadoBusca(self.precos[codigo_norm], 'exato')

        if self.config.tentar_sufixo_invertido and '-' in codigo_norm:
            a, b = codigo_norm.split('-', 1)
            alt = f"{b}-{a}"
            if alt in self.precos:
                return ResultadoBusca(self.precos[alt], 'sufixo invertido')

        if self.config.tentar_so_numero:
            m = re.search(r'(\d+)$', codigo_norm) or re.search(r'(\d+)', codigo_norm)
            if m and m.group(1) in self.by_num:
                ref_correspondente = self.by_num[m.group(1)]
                return ResultadoBusca(
                    self.precos[ref_correspondente],
                    f'so pelo numero (planilha tem {ref_correspondente})'
                )

        return ResultadoBusca(None, None)

    def todas_as_refs(self) -> set:
        return set(self.precos.keys())
