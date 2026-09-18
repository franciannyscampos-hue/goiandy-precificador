# Precificador API

Servico HTTP que expoe o motor de precificacao Python (pasta ../precificador)
pra o sistema em Cloudflare Pages chamar. Ver o topo de api.py pra o fluxo
completo.

## Rodar local
```
pip install -r requirements.txt
export CALLBACK_BASE_URL=https://goiandy-catalogo.pages.dev
export PRECIFICADOR_CALLBACK_TOKEN=mesmo-token-do-wrangler
uvicorn api:app --reload
```

## Deploy (Railway, exemplo)
1. Criar novo projeto no Railway, apontar pra essa pasta (ou repositorio).
2. Adicionar `tesseract-ocr` e `tesseract-ocr-por` como pacote de sistema
   (Railway usa Nixpacks -- adicionar um `nixpacks.toml` ou `apt.txt` com
   esses dois pacotes, senao catalogo escaneado tipo Goller nao funciona).
3. Configurar as variaveis de ambiente CALLBACK_BASE_URL e
   PRECIFICADOR_CALLBACK_TOKEN.
4. Copiar a URL publica gerada (ex: https://algo.up.railway.app) pro
   PRECIFICADOR_API_URL do wrangler.jsonc do sistema principal.
