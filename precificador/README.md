# Precificador de Catálogos

Motor que insere preço (de uma planilha Excel) ao lado da referência certa, em
qualquer catálogo PDF de indústria — testado em 4 catálogos reais (Maxximo, KE
Home, Unitá Porcelanas, Göller) com layouts bem diferentes entre si.

## Como funciona

Cada indústria/fornecedor tem um **arquivo de configuração** (`configs/*.json`)
descrevendo como a REF aparece naquele catálogo específico e como a planilha
de preço dela é organizada. O motor (`precificador/`) é genérico — não muda
de catálogo pra catálogo, só a config muda.

Catálogo novo, de indústria que a gente nunca processou? Segue o roteiro em
`prompt_sistema_precificacao_catalogos.md` (diagnóstico manual/com IA) pra
montar a config nova. Depois disso, rodar é 100% automático.

## Uso rápido

```bash
pip install -r requirements.txt
# tambem precisa do tesseract instalado no sistema (apt install tesseract-ocr tesseract-ocr-por)
# so necessario se algum catalogo for escaneado (config "escaneado": true)

python run.py --config configs/maxximo.json \
    --pdf catalogo_maxximo.pdf \
    --excel tabela_maxximo.xlsx \
    --out catalogo_maxximo_precificado.pdf
```

Gera o PDF com os preços + (se sobrar item sem encontrar) um apêndice com a
lista dos que faltaram, anexado nas últimas páginas do mesmo arquivo.

## Estrutura

```
precificador/
  config.py          -- schema da configuracao por industria
  matcher.py          -- casamento REF x planilha (exato, sufixo invertido, so numero)
  placement.py         -- decide onde por o preco (esquerda/direita/acima), sem nunca ambiguar ou sobrepor
  extrator_texto.py    -- le REFs de catalogo com texto nativo (pdfplumber)
  extrator_ocr.py       -- le REFs de catalogo escaneado (OCR em tiras + checagem de fundo branco)
  pipeline.py           -- orquestra tudo, detecta sozinho se precisa de OCR
  render.py             -- desenha a etiqueta de preco e gera o apendice de faltantes
configs/
  maxximo.json, ke_home.json, unita.json, goller.json  -- prontas, uso imediato
run.py                  -- linha de comando
```

## Catálogo escaneado / muito grande

`processar_catalogo(..., pagina_inicial=X, pagina_final=Y)` processa só um
intervalo de páginas — use isso se estiver rodando num ambiente com tempo de
execução curto (função serverless, etc.): processe em lotes e junte os PDFs
no final com `precificador.juntar_pdfs([...])`.

OCR é bem mais lento que texto nativo (~2s/página fatiada em tiras vs
instantâneo com texto nativo). Catálogo escaneado grande (100+ páginas) pode
levar dezenas de minutos no total.

## Limitação conhecida

Este motor é Python e depende de bibliotecas nativas (`pdfplumber`, `tesseract`
via `pytesseract`, `reportlab`) — **não roda dentro de Cloudflare Pages
Functions / Workers** (runtime de borda, sem esses binários e com tempo de
execução curto demais pra OCR). Se for integrar num sistema hospedado no
Cloudflare Pages, esse motor precisa rodar num serviço à parte (ex.: Railway,
Render, uma VPS pequena, ou um Space com um contêiner Python) que o frontend
chama por API — ver seção de arquitetura na conversa/spec.
