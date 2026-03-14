# Brasil24 — Agregador de Noticias + Canal YouTube 24/7

Sistema completo de agregação de notícias brasileiras com geração automática de vídeos, personagens de podcast com IA e transmissão ao vivo no YouTube.

---

## Visão Geral

```
RSS Feeds (G1, CNN Brasil, Folha, R7, UOL...)
        ↓
  Coleta automática a cada 15min (FeedParser + Newspaper3K)
        ↓
  Deduplicação (MinHash) + Ranqueamento de importância
        ↓
  Enriquecimento via URL → entidades, sentimento, tópicos,
  impacto, imagem og:image, ângulo de discussão
        ↓
  IA → Resumo + Diálogo contextual entre personagens
  (usa dados do enriquecimento para diálogos mais ricos)
        ↓
  edge-tts → Áudio em PT-BR (Ana + Carlos + Convidado)
        ↓
  FFmpeg + MoviePy → Vídeo animado MP4 1080p
  (Ken Burns na imagem real OU fundo genérico animado do canal)
        ↓
  YouTube Live 24/7 (ao vivo de dia, replay à noite)
        ↓
  Dashboard Web estilo CNN (tempo real via WebSocket)
```

### Personagens

| Personagem | Papel | Voz |
|---|---|---|
| **Ana Silva** | Âncora principal | pt-BR-FranciscaNeural |
| **Carlos Mendes** | Analista político/econômico | pt-BR-AntonioNeural |
| **Dra. Marina Souza** | Convidada — Política | pt-BR-FranciscaNeural |
| **Prof. Roberto Alves** | Convidado — Economia | pt-BR-AntonioNeural |
| **Dr. Lucas Costa** | Convidado — Saúde | pt-BR-AntonioNeural |
| **Beatriz Lima** | Convidada — Tecnologia | pt-BR-FranciscaNeural |
| **Rodrigo Santos** | Convidado — Esporte | pt-BR-AntonioNeural |

---

## Pré-requisitos

Escolha entre **Docker** (recomendado, sem precisar instalar nada) ou **Python + FFmpeg** (instalação manual).

### Docker (recomendado)
- [Docker Desktop](https://docs.docker.com/get-docker/) (Windows/macOS) ou Docker Engine + Docker Compose Plugin (Linux)

### Python manual
- Python 3.10 ou superior
- FFmpeg instalado no sistema

```bash
# Ubuntu/Debian
sudo apt-get install -y ffmpeg

# macOS (Homebrew)
brew install ffmpeg

# Windows: baixar em https://ffmpeg.org/download.html e adicionar ao PATH
```

---

## Docker (recomendado)

Docker é a forma mais simples — sem instalar Python, FFmpeg ou dependências.

### Cenário 1 — Modo sem IA (testar o sistema rapidamente)

```bash
cp .env.example .env
# AI_PROVIDER=none já é o padrão — não precisa editar nada

docker compose up -d
# Acesse: http://localhost:8000
```

---

### Cenário 2 — Com Anthropic Claude

```bash
cp .env.example .env
```

Edite o `.env`:
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
docker compose up -d
```

---

### Cenário 3 — Com Ollama (IA local gratuita)

#### Opção A — Ollama em container Docker (tudo junto)

Edite o `.env`:
```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2
```

```bash
# Sobe a aplicação + Ollama
docker compose --profile ollama up -d

# Baixar o modelo (primeira vez — pode demorar, ~2GB)
docker compose exec ollama ollama pull llama3.2

# Verificar modelos disponíveis
docker compose exec ollama ollama list
```

> Para usar GPU NVIDIA com o Ollama, descomente o bloco `deploy:` no `docker-compose.yml`.

#### Opção B — Ollama já instalado no host

```bash
ollama serve   # se ainda não estiver rodando
```

Edite o `.env`:
```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2
```

```bash
docker compose up -d
```

> **Linux:** o `extra_hosts: host.docker.internal:host-gateway` já está configurado no `docker-compose.yml`, então `host.docker.internal` funciona sem configuração extra.

---

### Cenário 4 — Com transmissão ao YouTube

Edite o `.env` (em qualquer um dos cenários acima):
```env
YOUTUBE_STREAM_KEY=xxxx-xxxx-xxxx-xxxx
```

```bash
docker compose up -d

# Iniciar transmissão via API
curl -X POST http://localhost:8000/api/admin/start-stream

# Parar transmissão
curl -X POST http://localhost:8000/api/admin/stop-stream
```

---

### Volumes Docker (persistência de dados)

Os dados são preservados em volumes nomeados — não se perdem ao reiniciar ou recriar containers:

| Volume | Conteúdo |
|---|---|
| `brasil24_db` | Banco de dados SQLite (`database/news.db`) |
| `brasil24_videos` | Vídeos gerados (`video/output/`) |
| `brasil24_assets` | Trilha de fundo (`video/assets/bg_music.mp3`) |
| `ollama_data` | Modelos Ollama baixados (perfil `ollama`) |

Para apagar tudo e começar do zero:
```bash
docker compose down -v
```

---

### Comandos Docker úteis

```bash
# Ver logs em tempo real
docker compose logs -f brasil24

# Reiniciar o app sem recriar
docker compose restart brasil24

# Rebuild após alterar requirements.txt
docker compose build --no-cache && docker compose up -d

# Executar diagnóstico dentro do container
docker compose exec brasil24 python diagnose.py

# Verificar artigos e episódios no banco
docker compose exec brasil24 python -c "
from database.db import get_session_factory
from database.models import Article, Episode
db = get_session_factory()()
print(f'Artigos: {db.query(Article).count()}')
print(f'Episódios: {db.query(Episode).count()}')
"

# Forçar fetch de notícias agora
curl -X POST http://localhost:8000/api/admin/fetch
```

---

## Instalação manual (sem Docker)

### 1. Criar ambiente virtual
```bash
python3 -m venv venv
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

> **Nota:** A instalação de `newspaper3k` e `moviepy` pode demorar alguns minutos.

---

## Configuração

### 1. Criar arquivo `.env`
```bash
cp .env.example .env
```

### 2. Escolher o provedor de IA

O sistema suporta três modos — defina `AI_PROVIDER` no `.env`:

| `AI_PROVIDER` | Descrição | Custo |
|---|---|---|
| `none` | Diálogos padrão (sem IA) | Gratuito |
| `ollama` | IA local via Ollama | Gratuito |
| `anthropic` | Claude (Anthropic) | Pago |

---

#### Opção A — Sem IA (padrão)
```env
AI_PROVIDER=none
```
Funciona imediatamente, usa diálogos pré-definidos. Ideal para testar o sistema.

---

#### Opção B — Ollama (gratuito, roda localmente)

**1. Instalar o Ollama:**
```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Windows: baixar em https://ollama.com/download
```

**2. Baixar um modelo em PT-BR:**
```bash
ollama pull llama3.2      # Recomendado — rápido e bom em PT-BR (~2GB)
ollama pull mistral       # Boa alternativa (~4GB)
ollama pull gemma3        # Excelente em PT-BR (~5GB)
```

**3. Iniciar o servidor Ollama:**
```bash
ollama serve
# Roda em http://localhost:11434
```

**4. Configurar o `.env`:**
```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

> **Dica Ollama:** Use `ollama list` para ver os modelos instalados.
> Para usar o Ollama em outro servidor da rede: `OLLAMA_BASE_URL=http://192.168.1.100:11434`

---

#### Opção C — Anthropic Claude (melhor qualidade)

**1. Obter a API key:** https://console.anthropic.com/

**2. Configurar o `.env`:**
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

O sistema usa o modelo `claude-haiku-4-5` (mais rápido e barato).

---

### 3. Configuração completa do `.env`
```env
# AI_PROVIDER: "anthropic", "ollama" ou "none"
AI_PROVIDER=none

ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

# Obrigatório apenas para transmissão ao YouTube
YOUTUBE_STREAM_KEY=xxxx-xxxx-xxxx-xxxx

# Configurações gerais (padrões já funcionam)
DB_PATH=database/news.db
FETCH_INTERVAL_MINUTES=15
MAX_NEWS_PER_CYCLE=50
VIDEO_OUTPUT_DIR=video/output
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
```

> **Dica:** Sem `YOUTUBE_STREAM_KEY`, tudo funciona exceto a transmissão ao vivo.

---

## Rodando o Servidor (instalação manual)

### Iniciar o servidor
```bash
# Com virtualenv ativo
uvicorn main:app --host 0.0.0.0 --port 8000

# Ou diretamente pelo Python
python main.py

# Ou com o caminho completo do venv (sem precisar ativar)
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

### Acessar o dashboard
Abra o navegador em: **http://localhost:8000**

O servidor irá automaticamente:
1. Inicializar o banco de dados SQLite
2. Buscar notícias de todos os feeds RSS
3. Agendar fetch automático a cada 15 minutos
4. Disponibilizar a API REST e WebSocket

---

## Estrutura do Projeto

```
agregardor_noticias/
├── main.py                    # Entrypoint FastAPI
├── requirements.txt
├── .env                       # Suas configurações (não commitar)
├── .env.example               # Modelo de configurações
│
├── config/
│   ├── settings.py            # Configurações via pydantic
│   ├── sources.yaml           # Feeds RSS e palavras-chave
│   ├── personas.yaml          # Definição dos personagens
│   └── schedule.yaml          # Horários dia/noite
│
├── database/
│   ├── models.py              # Modelos SQLAlchemy
│   ├── db.py                  # Sessão/engine SQLite
│   └── news.db                # Banco (criado automaticamente)
│
├── aggregator/                # Coleta de notícias
│   ├── feed_fetcher.py        # RSS via FeedParser
│   ├── scraper.py             # Conteúdo completo via Newspaper3K
│   ├── deduplicator.py        # Remove duplicatas (MinHash)
│   ├── ranker.py              # Pontuação de importância
│   ├── enricher.py            # Enriquecimento via URL (IA extrai entidades, sentimento, tópicos)
│   └── scheduler.py           # APScheduler (fetch a cada 15min)
│
├── ai/
│   ├── client.py              # Cliente unificado (Anthropic ou Ollama)
│   ├── summarizer.py          # Resume notícias em PT-BR
│   ├── dialogue_generator.py  # Gera diálogo Ana/Carlos/Convidado (usa enrichment)
│   └── prompts.py             # Templates de prompts em PT-BR
│
├── tts/
│   ├── voice_engine.py        # edge-tts: síntese de voz
│   └── audio_mixer.py         # FFmpeg: concatena falas + trilha de fundo
│
├── video/
│   ├── compositor.py          # MoviePy: monta vídeo animado final
│   ├── news_effects.py        # Efeitos visuais animados (Ken Burns, ticker, overlays)
│   ├── pipeline.py            # Pipeline completo artigo→vídeo
│   ├── assets/                # Trilha de fundo (bg_music.mp3, opcional)
│   └── output/                # Vídeos gerados (criado automaticamente)
│
├── stream/
│   ├── streamer.py            # FFmpeg RTMP → YouTube Live
│   ├── playlist_manager.py    # Fila de vídeos dia/noite
│   └── scheduler.py           # Modo diurno (ao vivo) / noturno (replay)
│
├── api/
│   ├── routes/
│   │   ├── news.py            # GET /api/news
│   │   ├── stream.py          # GET /api/stream/status
│   │   └── health.py          # GET /api/health
│   └── websocket.py           # WS /ws/news
│
└── frontend/
    ├── index.html             # Dashboard estilo CNN
    └── static/
        ├── style.css          # Tema escuro, animações
        └── app.js             # WebSocket + atualização ao vivo
```

---

## API REST

### Notícias
```bash
# Top 10 notícias do dia
GET /api/news/top?n=10

# Listar notícias com paginação e filtros
GET /api/news?page=1&per_page=20&category=economia

# Notícia específica (com conteúdo completo)
GET /api/news/42

# Categorias disponíveis: politica, economia, saude, tech, esporte, geral
```

### Stream
```bash
# Status da transmissão
GET /api/stream/status

# Saúde do sistema
GET /api/health
```

### Admin (geração de vídeos)
```bash
# Forçar fetch de notícias agora
POST /api/admin/fetch

# Gerar vídeo para um artigo específico
POST /api/admin/generate/42

# Processar e gerar os top N artigos
POST /api/admin/process-top?n=3
```

---

## Enriquecimento de Notícias

O sistema possui um módulo de enriquecimento (`aggregator/enricher.py`) que extrai informações estruturadas de cada notícia antes de gerar o áudio e o vídeo. Isso torna os diálogos muito mais ricos e contextualizados.

### O que o enriquecedor extrai

Para cada URL de notícia, a IA analisa o conteúdo completo e retorna:

| Campo | Descrição |
|---|---|
| `titulo` | Título extraído da página |
| `autor` | Autor do artigo |
| `resumo` | Resumo objetivo em PT-BR |
| `sentimento` | `positivo` / `negativo` / `neutro` |
| `impacto` | `alto` / `medio` / `baixo` |
| `topicos_principais` | Lista de tópicos abordados |
| `entidades_mencionadas` | Pessoas, organizações e locais citados |
| `palavras_chave` | Termos relevantes da notícia |
| `angulo_discussao` | Sugestão de ângulo para debate entre os personagens |
| `image_url` | Imagem `og:image` da notícia (usada como fundo do vídeo) |

### Usando o enriquecedor manualmente

```bash
# Via Python diretamente
python -c "
from aggregator.enricher import enrich_url
import json
data = enrich_url('https://g1.globo.com/politica/noticia/2024/01/01/exemplo.html')
print(json.dumps(data, indent=2, ensure_ascii=False))
"

# Via arquivo de teste incluído no projeto
python python_summary_news_test.py
```

### Como o enriquecimento melhora o pipeline

1. **Diálogos mais contextuais**: Ana e Carlos mencionam pessoas, organizações e locais reais da notícia
2. **Ângulo de debate**: A IA recebe uma sugestão de qual aspecto focar na discussão
3. **Imagem automática**: Se o RSS não trouxer imagem, o enriquecedor extrai o `og:image` da URL
4. **Resumo de qualidade**: O resumo do enriquecedor substitui o gerado pelo summarizer (mais preciso pois usa o conteúdo completo da página)

---

## Efeitos Visuais nos Vídeos

Os vídeos gerados pelo sistema têm efeitos animados profissionais, mesmo sem imagem da notícia.

### Com imagem real (og:image ou RSS)

- **Ken Burns effect**: zoom lento de 1.0× para 1.08× ao longo do vídeo, com leve pan
- Imagem com blur suave + escurecimento para melhorar legibilidade do texto

### Sem imagem (fundo genérico do canal)

O sistema gera automaticamente um fundo animado com a identidade visual do canal BRASIL24:

- **Gradiente animado** com cores por categoria:
  - Política → roxo/violeta
  - Economia → verde
  - Saúde → lilás
  - Tech → azul/teal
  - Esporte → laranja
  - Geral → azul marinho
- **Linhas diagonais em movimento** (accent color baseado no sentimento da notícia)
- **Vinheta** nas bordas para dar profundidade
- **Círculo de luz pulsante** no centro (animado com `sin(t)`)

### Overlays animados (sempre presentes)

| Elemento | Descrição |
|---|---|
| **Logo BRASIL24** | Canto superior direito com badge "AO VIVO" piscando (0.5Hz) |
| **Título da notícia** | Parte inferior, com quebra automática de linha |
| **Label do personagem** | Slide-in da esquerda a cada troca de fala (Ana / Carlos / Convidado) |
| **Badge de sentimento** | Canto inferior direito: POSITIVO (verde), NEGATIVO (vermelho), NEUTRO (azul) |
| **Overlay de entidades** | Rotativo a cada 4s: pessoas (👤), organizações (🏛), locais (📍) |
| **Ticker animado** | Barra inferior com scrolling do título + "BRASIL24 — NOTICIAS AO VIVO" |

### Adicionar trilha de fundo (opcional)

Coloque um arquivo `bg_music.mp3` em `video/assets/` para adicionar música ambiente suave ao vídeo. O mixer reduz o volume da trilha automaticamente para não competir com as vozes.

---

## Gerando Vídeos Manualmente

### Via API
```bash
# Ver top artigos para saber os IDs
curl http://localhost:8000/api/news/top?n=5

# Gerar vídeo para o artigo de ID 42
curl -X POST http://localhost:8000/api/admin/generate/42

# Gerar vídeos para os 3 melhores artigos
curl -X POST "http://localhost:8000/api/admin/process-top?n=3"
```

### Via Python (direto)
```bash
python -c "
import asyncio
from video.pipeline import generate_episode_for_article
ep_id = asyncio.run(generate_episode_for_article(42))
print(f'Episódio gerado: ID {ep_id}')
"
```

Os vídeos são salvos em `video/output/episode_<ID>/video_final.mp4`.

---

## Transmissão ao Vivo no YouTube

### Pré-requisitos
1. Ter um canal no YouTube com transmissões ao vivo habilitadas
2. Obter a **Chave de Stream** em: YouTube Studio → Transmissões ao Vivo → Chave de stream
3. Adicionar a chave no `.env`: `YOUTUBE_STREAM_KEY=xxxx-xxxx-xxxx`

### Transmitir um vídeo de teste (10 segundos)
```bash
python -m stream.streamer video/output/episode_2/video_final.mp4 --test
```

### Iniciar transmissão contínua 24/7
```bash
# Em um terminal separado (mantém rodando)
python -c "
from stream.streamer import stream_continuous
from stream.scheduler import get_stream_mode
stream_continuous(mode_fn=get_stream_mode)
"
```

**Horários automáticos:**
- **06:00 – 23:00** → Modo **AO VIVO**: transmite vídeos novos conforme são gerados
- **23:00 – 06:00** → Modo **REPLAY**: repete os vídeos do dia em loop (estilo CNN madrugada)

---

## Testando Componentes Individualmente

### Testar coleta de notícias
```bash
python -m aggregator.feed_fetcher
# Resultado: "Fetched X new articles"
```

### Testar enriquecimento de URL
```bash
python -c "
from aggregator.enricher import enrich_url
import json
data = enrich_url('https://g1.globo.com/politica/noticia/exemplo.html')
print(json.dumps(data, indent=2, ensure_ascii=False))
"
# Retorna: sentimento, impacto, entidades, tópicos, imagem e ângulo de discussão
```

### Testar geração de voz (TTS)
```bash
python -m tts.voice_engine "Boa tarde, eu sou Ana Silva do Brasil Vinte e Quatro."
# Gera: test_speech.mp3
```

### Testar diálogo com IA (com enriquecimento)
```bash
python -c "
from ai.dialogue_generator import generate_dialogue
from aggregator.enricher import enrich_url

# Sem enrichment (básico)
script = generate_dialogue('Governo anuncia novo pacote econômico', 'O governo federal...', 'economia')
for linha in script:
    print(f\"[{linha['persona']}] {linha['text']}\")
"
```

### Verificar provedor de IA ativo
```bash
# Via API (mostra provider, modelo e disponibilidade)
curl http://localhost:8000/api/health

# Via Python direto
python -c "from ai.client import provider_info; print(provider_info())"
```

### Verificar banco de dados
```bash
python -c "
from database.db import get_session_factory
from database.models import Article, Episode
db = get_session_factory()()
print(f'Artigos: {db.query(Article).count()}')
print(f'Episódios: {db.query(Episode).count()}')
"
```

---

## Fontes de Notícias Configuradas

| Fonte | Categoria | Peso |
|---|---|---|
| G1 (Globo) | Geral | 1.0 |
| CNN Brasil | Geral | 1.0 |
| Agência Brasil | Geral | 0.9 |
| Folha de S.Paulo | Geral | 0.9 |
| G1 Economia | Economia | 0.9 |
| G1 Política | Política | 0.9 |
| R7 | Geral | 0.8 |
| UOL Notícias | Geral | 0.8 |
| G1 Saúde | Saúde | 0.8 |
| G1 Tecnologia | Tech | 0.8 |

Para adicionar novas fontes, edite `config/sources.yaml`.

---

## Solução de Problemas

### Ollama: modelo não encontrado
```bash
# Ver modelos instalados
ollama list

# Baixar o modelo configurado no .env
ollama pull llama3.2

# Testar se o Ollama está respondendo
curl http://localhost:11434/api/tags
```

### Ollama: conexão recusada
```bash
# Certifique-se de que o servidor está rodando
ollama serve

# Se quiser rodar em background (Linux)
nohup ollama serve &
```

### Diálogos sem qualidade (mesmo com IA)
Alguns modelos Ollama menores têm dificuldade com JSON estruturado.
Tente modelos maiores ou mude para Anthropic:
```bash
ollama pull mistral        # melhor estrutura JSON
ollama pull llama3.1:8b   # mais capaz
```

### Ollama retorna resposta vazia (`""`)
Modelos cloud no Ollama (com sufixo `:cloud`, ex: `kimi-k2.5:cloud`) ignoram a opção `num_predict`.
O sistema detecta automaticamente modelos `:cloud` e omite essa opção.
Se usar outro modelo cloud com comportamento similar, verifique se o modelo tem `:cloud` no nome.

### Enriquecimento falha / sem dados
O enriquecimento é **não-crítico** — se falhar, o pipeline continua normalmente com dados básicos.
Causas comuns:
- Paywall no site (sem conteúdo acessível)
- Timeout na requisição HTTP (configurável em `enricher.py`)
- Resposta da IA sem JSON válido (o sistema usa fallback)

### Erro: `ffmpeg not found`
```bash
sudo apt-get install -y ffmpeg   # Ubuntu/Debian
brew install ffmpeg               # macOS
```

### Erro: `ModuleNotFoundError`
```bash
# Certifique-se de estar com o virtualenv ativo
source venv/bin/activate
pip install -r requirements.txt
```

### Dashboard não carrega notícias
```bash
# Forçar um fetch manual
curl -X POST http://localhost:8000/api/admin/fetch

# Verificar logs do servidor
```

### Vídeos não são gerados
```bash
# Verificar se existem artigos não processados
curl http://localhost:8000/api/news/top?n=5

# Verificar saúde geral
curl http://localhost:8000/api/health
```

### Diálogos muito simples (sem naturalidade)
Configure a `ANTHROPIC_API_KEY` no `.env` para usar o Claude API e obter diálogos muito mais naturais e contextualizados.

---

## Dependências Principais

| Pacote | Uso |
|---|---|
| `fastapi` + `uvicorn` | Servidor web e API REST |
| `sqlalchemy` | Banco de dados SQLite |
| `feedparser` | Leitura de feeds RSS |
| `newspaper3k` | Extração de conteúdo de artigos |
| `anthropic` | Claude API (resumos e diálogos) |
| `httpx` | Requisições HTTP (Ollama + download de imagens) |
| `beautifulsoup4` | Limpeza de HTML para o enriquecedor |
| `edge-tts` | Síntese de voz gratuita em PT-BR |
| `moviepy` | Composição de vídeo animado |
| `Pillow` | Efeitos visuais e overlays nos frames |
| `numpy` | Processamento de arrays de pixels |
| `apscheduler` | Agendamento de tarefas |
| `datasketch` | Deduplicação por similaridade (MinHash) |
| `pylivestream` | Streaming RTMP → YouTube Live |
