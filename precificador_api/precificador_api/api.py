"""
Serviço pequeno que roda em algum lugar que aceite Python (Railway, Render, uma
VPS) e expõe o motor de precificação (pasta ../precificador) como API HTTP,
pra o sistema em Cloudflare Pages chamar.

Fluxo:
  1. Cloudflare chama POST /precificar com {pdf_url, config_key, produtos,
     callback_precification_id} e recebe {job_id} na hora.
  2. Esse servico baixa o PDF, roda o motor (pode levar minutos, principalmente
     se a config for de catalogo escaneado), e ao terminar chama de volta
     PUT {CALLBACK_BASE_URL}/api/precifications/{callback_precification_id}/callback
     no proprio sistema Cloudflare, com o PDF pronto.

Rodar localmente:  uvicorn api:app --host 0.0.0.0 --port 8000
Variaveis de ambiente esperadas:
  CALLBACK_BASE_URL        -- ex: https://goiandy-catalogo.pages.dev
  PRECIFICADOR_CALLBACK_TOKEN  -- mesmo valor configurado no wrangler.jsonc
"""
import os
import sys
import uuid
import asyncio
import tempfile
import traceback
from pathlib import Path

import httpx
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from precificador.config import CatalogConfig
from precificador.matcher import PrecoLookup
from precificador.pipeline import processar_catalogo, eh_catalogo_escaneado
from precificador.render import gerar_apendice_faltantes
from precificador.auto_config import config_padrao
from pypdf import PdfReader, PdfWriter
import io

CALLBACK_BASE_URL = os.environ['CALLBACK_BASE_URL']
CALLBACK_TOKEN = os.environ.get('PRECIFICADOR_CALLBACK_TOKEN', '')
CONFIGS_DIR = Path(__file__).resolve().parent / 'precificador' / 'configs'

app = FastAPI()
jobs: dict[str, str] = {}  # job_id -> status (so pra consulta manual/debug, o estado real fica no callback)


class Produto(BaseModel):
    reference: str
    name: str | None = None
    price: float | None = None


class PrecificarRequest(BaseModel):
    pdf_url: str
    config_key: str | None = None   # None/"" = deteccao automatica, sem calibracao manual
    produtos: list[Produto]
    callback_precification_id: int


@app.post('/precificar')
async def precificar(req: PrecificarRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = 'processing'
    background_tasks.add_task(_processar_em_background, job_id, req)
    return {'job_id': job_id}


@app.get('/status/{job_id}')
async def status(job_id: str):
    return {'status': jobs.get(job_id, 'desconhecido')}


async def _processar_em_background(job_id: str, req: PrecificarRequest):
    print(f'[{job_id}] INICIO precification_id={req.callback_precification_id} config={req.config_key} pdf_url={req.pdf_url}', flush=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, 'catalogo.pdf')
            print(f'[{job_id}] baixando PDF...', flush=True)
            async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
                resp = await client.get(req.pdf_url)
                print(f'[{job_id}] download respondeu status={resp.status_code} tamanho={len(resp.content)} bytes content-type={resp.headers.get("content-type")}', flush=True)
                resp.raise_for_status()
                with open(pdf_path, 'wb') as f:
                    f.write(resp.content)
            print(f'[{job_id}] PDF salvo em {pdf_path}', flush=True)

            config_path = CONFIGS_DIR / f'{req.config_key}.json' if req.config_key else None
            if config_path and config_path.exists():
                config = CatalogConfig.carregar(str(config_path))
                print(f'[{job_id}] usando config calibrada "{req.config_key}"', flush=True)
            else:
                # sem calibracao manual (ou config nao encontrada) -- usa deteccao
                # automatica: casa REF direto contra os codigos da planilha, sem
                # precisar saber o formato/rotulo usado nesse catalogo especifico
                escaneado_auto = await asyncio.to_thread(eh_catalogo_escaneado, pdf_path)
                config = config_padrao(req.config_key or 'auto', escaneado=escaneado_auto)
                print(f'[{job_id}] sem config calibrada -> deteccao automatica (escaneado={escaneado_auto})', flush=True)
            config.excel_path = None  # nao usa, vamos passar o lookup pronto
            print(f'[{job_id}] config carregada: escaneado={config.escaneado}', flush=True)

            produtos_dicts = [p.model_dump() for p in req.produtos]
            lookup = PrecoLookup.from_produtos(produtos_dicts, config)
            print(f'[{job_id}] lookup montado com {len(lookup.precos)} produtos', flush=True)

            out_path = os.path.join(tmp, 'resultado.pdf')

            print(f'[{job_id}] iniciando processar_catalogo...', flush=True)
            # roda em thread separada pra nao bloquear o event loop (OCR/pdfplumber sao sincronos e pesados)
            relatorio = await asyncio.to_thread(
                processar_catalogo, pdf_path, config, out_path, 1, None, lookup
            )
            print(f'[{job_id}] processar_catalogo terminou: {relatorio.relatorio()}', flush=True)

            # apendice com os itens da planilha que nao apareceram no catalogo
            todas_refs = {p.reference.strip().upper() for p in req.produtos}
            faltantes_refs = todas_refs - relatorio.refs_detectadas_no_pdf
            resultado_final_path = out_path
            apendice_gerado = False
            if faltantes_refs:
                print(f'[{job_id}] gerando apendice com {len(faltantes_refs)} itens faltantes...', flush=True)
                por_ref = {p.reference.strip().upper(): p for p in req.produtos}
                itens = [(ref, por_ref[ref].name, por_ref[ref].price) for ref in faltantes_refs if ref in por_ref]
                apendice_bytes = gerar_apendice_faltantes(itens, req.config_key or 'catálogo')

                writer = PdfWriter()
                for p in PdfReader(out_path).pages:
                    writer.add_page(p)
                for p in PdfReader(io.BytesIO(apendice_bytes)).pages:
                    writer.add_page(p)
                resultado_final_path = os.path.join(tmp, 'resultado_com_apendice.pdf')
                with open(resultado_final_path, 'wb') as f:
                    writer.write(f)
                apendice_gerado = True

            print(f'[{job_id}] enviando callback de sucesso...', flush=True)
            await _enviar_callback_sucesso(req.callback_precification_id, resultado_final_path,
                                            relatorio.encontrados, len(faltantes_refs), apendice_gerado)
            print(f'[{job_id}] FIM - sucesso', flush=True)
            jobs[job_id] = 'done'

    except Exception as e:
        print(f'[{job_id}] ERRO: {e}', flush=True)
        traceback.print_exc()
        try:
            await _enviar_callback_erro(req.callback_precification_id, str(e))
            print(f'[{job_id}] callback de erro enviado', flush=True)
        except Exception as e2:
            print(f'[{job_id}] FALHOU AO ENVIAR CALLBACK DE ERRO: {e2}', flush=True)
            traceback.print_exc()
        jobs[job_id] = 'error'


async def _enviar_callback_sucesso(precification_id, pdf_path, total_matched, total_missing, apendice_gerado):
    url = f'{CALLBACK_BASE_URL}/api/precifications/{precification_id}/callback'
    async with httpx.AsyncClient(timeout=120) as client:
        with open(pdf_path, 'rb') as f:
            resp = await client.put(
                url,
                headers={'X-Callback-Token': CALLBACK_TOKEN},
                data={
                    'status': 'done',
                    'total_matched': str(total_matched),
                    'total_missing': str(total_missing),
                    'appendix_generated': 'true' if apendice_gerado else 'false',
                },
                files={'file': ('resultado.pdf', f, 'application/pdf')},
            )
            print(f'callback sucesso -> {resp.status_code} {resp.text[:300]}', flush=True)
            resp.raise_for_status()


async def _enviar_callback_erro(precification_id, mensagem):
    url = f'{CALLBACK_BASE_URL}/api/precifications/{precification_id}/callback'
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(
            url,
            headers={'X-Callback-Token': CALLBACK_TOKEN},
            data={'status': 'error', 'error_message': mensagem},
        )
        print(f'callback erro -> {resp.status_code} {resp.text[:300]}', flush=True)
