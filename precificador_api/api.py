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
    config_key: str
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
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, 'catalogo.pdf')
            async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
                resp = await client.get(req.pdf_url)
                resp.raise_for_status()
                with open(pdf_path, 'wb') as f:
                    f.write(resp.content)

            config_path = CONFIGS_DIR / f'{req.config_key}.json'
            if not config_path.exists():
                raise ValueError(f'Config "{req.config_key}" não encontrada.')
            config = CatalogConfig.carregar(str(config_path))
            config.excel_path = None  # nao usa, vamos passar o lookup pronto

            produtos_dicts = [p.model_dump() for p in req.produtos]
            lookup = PrecoLookup.from_produtos(produtos_dicts, config)

            out_path = os.path.join(tmp, 'resultado.pdf')

            # roda em thread separada pra nao bloquear o event loop (OCR/pdfplumber sao sincronos e pesados)
            relatorio = await asyncio.to_thread(
                processar_catalogo, pdf_path, config, out_path, 1, None, lookup
            )

            # apendice com os itens da planilha que nao apareceram no catalogo
            todas_refs = {p.reference.strip().upper() for p in req.produtos}
            faltantes_refs = todas_refs - relatorio.refs_detectadas_no_pdf
            resultado_final_path = out_path
            apendice_gerado = False
            if faltantes_refs:
                por_ref = {p.reference.strip().upper(): p for p in req.produtos}
                itens = [(ref, por_ref[ref].name, por_ref[ref].price) for ref in faltantes_refs if ref in por_ref]
                apendice_bytes = gerar_apendice_faltantes(itens, req.config_key)

                writer = PdfWriter()
                for p in PdfReader(out_path).pages:
                    writer.add_page(p)
                for p in PdfReader(io.BytesIO(apendice_bytes)).pages:
                    writer.add_page(p)
                resultado_final_path = os.path.join(tmp, 'resultado_com_apendice.pdf')
                with open(resultado_final_path, 'wb') as f:
                    writer.write(f)
                apendice_gerado = True

            await _enviar_callback_sucesso(req.callback_precification_id, resultado_final_path,
                                            relatorio.encontrados, len(faltantes_refs), apendice_gerado)
            jobs[job_id] = 'done'

    except Exception as e:
        traceback.print_exc()
        await _enviar_callback_erro(req.callback_precification_id, str(e))
        jobs[job_id] = 'error'


async def _enviar_callback_sucesso(precification_id, pdf_path, total_matched, total_missing, apendice_gerado):
    url = f'{CALLBACK_BASE_URL}/api/precifications/{precification_id}/callback'
    async with httpx.AsyncClient(timeout=120) as client:
        with open(pdf_path, 'rb') as f:
            await client.put(
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


async def _enviar_callback_erro(precification_id, mensagem):
    url = f'{CALLBACK_BASE_URL}/api/precifications/{precification_id}/callback'
    async with httpx.AsyncClient(timeout=30) as client:
        await client.put(
            url,
            headers={'X-Callback-Token': CALLBACK_TOKEN},
            data={'status': 'error', 'error_message': mensagem},
        )
