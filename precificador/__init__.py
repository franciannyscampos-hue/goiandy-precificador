from .config import CatalogConfig
from .pipeline import processar_catalogo, testar_amostra, eh_catalogo_escaneado, juntar_pdfs, Relatorio
from .render import gerar_apendice_faltantes, fmt_preco
from .auto_config import detectar_config, config_padrao

__all__ = [
    'CatalogConfig', 'processar_catalogo', 'testar_amostra', 'eh_catalogo_escaneado', 'juntar_pdfs',
    'Relatorio', 'gerar_apendice_faltantes', 'fmt_preco', 'detectar_config', 'config_padrao',
]
