"""
Config por industria/catalogo. Cada catalogo novo ganha um JSON como os que estao
em /configs. Isso e o que muda de fornecedor pra fornecedor -- o motor (matcher.py,
placement.py, ocr.py, pipeline.py) e igual pra todos.

Ver /configs/*.json para exemplos reais (maxximo, ke_home, unita, goller).
"""
from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class CatalogConfig:
    nome: str

    # --- como a REF aparece no texto do PDF ---
    # regex com um grupo de captura pro codigo. Ex: r'REF\.\s*([\w-]+)'
    ref_regex: str
    # se True, o "achado" da regex vem em 2 tokens de palavra separados
    # (tipico de catalogo com texto nativo, extraido via pdfplumber word-by-word);
    # se False, a regex roda sobre o texto corrido de uma linha (tipico de OCR)
    ref_em_duas_palavras: bool = True

    # alguns catalogos escrevem a REF as vezes grudada, ex "REF.217-TR" num token so.
    # prefixo que, se um token comecar com ele e for mais longo, o resto e o codigo
    prefixo_grudado: Optional[str] = None  # ex: "REF."

    # catalogo sem NENHUM rotulo antes do codigo (o codigo aparece sozinho, perto
    # do produto) -- nesse caso casamos direto contra os codigos da planilha
    sem_rotulo: bool = False

    # alguns catalogos tem um token NO MEIO entre o rotulo e o codigo, ex:
    # "REF" / "120ml:" / "UT21-43" -- regex que, se bater no token seguinte ao
    # rotulo, pula ele e usa o token DEPOIS como codigo (ver config da Unita)
    token_meio_regex: Optional[str] = None

    # exige um codigo secundario (numerico) por perto pra confirmar a ocorrencia
    # (usado no Goller: a REF aparece 2x, so uma delas -- a que tem o codigo de
    # barras do lado -- e a certa pra por preco)
    exige_par_numerico: bool = False
    par_numerico_regex: str = r'^\d{3,5}$'
    par_distancia_max_pt: float = 700  # em pontos, na mesma linha

    # --- planilha de preco ---
    excel_aba: Optional[str] = None  # nome da aba, ou None pra pegar a ativa/primeira
    excel_col_ref: int = 0  # indice da coluna (0-based)
    excel_col_preco: int = 1
    excel_linha_inicial: int = 2  # 1-based, pulando cabecalho

    # --- casamento REF <-> planilha ---
    tentar_sufixo_invertido: bool = True  # "A-B" tambem tenta "B-A"
    tentar_so_numero: bool = True  # ultimo recurso, so quando nao e ambiguo

    # --- catalogo escaneado (sem texto nativo)? ---
    escaneado: bool = False
    ocr_n_tiras: int = 5
    ocr_overlap: float = 0.08
    ocr_psm: int = 6
    ocr_lang: str = 'por'

    # --- visual ---
    fonte_nome: str = 'Helvetica-Bold'
    fonte_tamanho: float = 10
    fonte_tamanho_min: float = 8
    cor_texto: str = '#0B5FA5'
    cor_fundo: str = '#FFE38A'
    prioridade_posicao: tuple = ('esquerda', 'direita', 'acima')

    @staticmethod
    def carregar(caminho_json: str) -> "CatalogConfig":
        with open(caminho_json, encoding='utf-8') as f:
            d = json.load(f)
        return CatalogConfig(**d)

    def salvar(self, caminho_json: str):
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2)
