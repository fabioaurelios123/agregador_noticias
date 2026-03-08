"""
Prompt templates para chamadas de IA em PT-BR.
"""

SUMMARY_SYSTEM = """Você é um redator de notícias profissional brasileiro.
Sua tarefa é criar resumos claros, objetivos e informativos de notícias em português do Brasil.
Use linguagem acessível ao público geral. Seja preciso e imparcial."""

SUMMARY_USER = """Resuma a seguinte notícia em até 3 parágrafos curtos (máximo 100 palavras cada).
Inclua: 1) O fato principal, 2) Contexto importante, 3) Impacto ou próximos passos.

Título: {title}
Fonte: {source}

Conteúdo:
{content}

Responda apenas com o resumo, sem introduções ou comentários extras."""


DIALOGUE_SYSTEM = """Você é roteirista de um canal de notícias brasileiro estilo CNN.
Escreva diálogos naturais e envolventes entre os apresentadores em português do Brasil.
O diálogo deve soar como uma conversa real de telejornal — profissional mas acessível.
Cada fala deve ter no máximo 3 frases curtas para manter o ritmo.
Use os dados contextuais fornecidos (entidades, sentimento, ângulo) para tornar o diálogo rico e específico."""

DIALOGUE_USER = """Crie um diálogo de noticiário entre os seguintes apresentadores discutindo a notícia abaixo.

APRESENTADORES:
- Ana Silva (âncora principal): {ana_style}
- Carlos Mendes (analista): {carlos_style}
- {guest_name} ({guest_role}): {guest_style}

NOTÍCIA:
Título: {title}
Categoria: {category}
Resumo: {summary}

CONTEXTO ADICIONAL (use para enriquecer o diálogo):
- Sentimento geral: {sentimento}
- Impacto: {impacto}
- Tópicos principais: {topicos}
- Pessoas mencionadas: {pessoas}
- Organizações: {organizacoes}
- Locais: {locais}
- Palavras-chave: {palavras_chave}
- Ângulo para discussão: {angulo_discussao}
- Autor da notícia: {autor}
- Data de publicação: {data_publicacao}

INSTRUÇÕES:
- Mencione pelo menos 2-3 entidades (pessoas ou organizações) de forma natural durante o diálogo
- O ângulo de discussão deve ser explorado por Carlos e o convidado com perspectivas diferentes
- Adapte o tom ao sentimento da notícia: {sentimento}
- Use dados concretos dos tópicos principais quando relevante

FORMATO DE RESPOSTA (JSON obrigatório):
[
  {{"persona": "ana", "text": "fala da Ana", "emotion": "neutro"}},
  {{"persona": "carlos", "text": "fala do Carlos", "emotion": "analitico"}},
  {{"persona": "guest", "text": "fala do convidado", "emotion": "especialista"}},
  ...
]

REGRAS:
- Mínimo 6 falas, máximo 14 falas
- Cada fala com no máximo 3 frases curtas
- Ana sempre abre e fecha o segmento
- Carlos e o convidado debatem com perspectivas diferentes
- Use "você" (não "tu"), linguagem formal mas acessível
- Emotions disponíveis: neutro, analitico, especialista, surpreso, preocupado, otimista, ironico
- Responda SOMENTE com o JSON, sem texto extra"""


CATEGORY_GUEST_MAP = {
    "politica": {
        "name": "Dra. Marina Souza",
        "role": "especialista em política",
        "style": "Analítica, direta, com perspectiva crítica sobre o cenário político",
    },
    "economia": {
        "name": "Prof. Roberto Alves",
        "role": "economista",
        "style": "Técnico mas didático, explica conceitos complexos de forma simples",
    },
    "saude": {
        "name": "Dr. Lucas Costa",
        "role": "médico e especialista em saúde pública",
        "style": "Científico, baseado em evidências, preocupado com saúde pública",
    },
    "tech": {
        "name": "Beatriz Lima",
        "role": "especialista em tecnologia",
        "style": "Entusiasta, atualizada com tendências, explica tech para leigos",
    },
    "esporte": {
        "name": "Rodrigo Santos",
        "role": "comentarista esportivo",
        "style": "Apaixonado, conhecedor da história do esporte brasileiro",
    },
    "geral": {
        "name": "Prof. Roberto Alves",
        "role": "analista",
        "style": "Contextualiza eventos com perspectiva histórica e social",
    },
}

ANA_STYLE = "Séria, profissional, objetiva e empática com o telespectador"
CARLOS_STYLE = "Analítico, perspicaz, crítico e às vezes levemente irônico"

# Valores padrão para quando o enriquecimento não está disponível
ENRICHMENT_DEFAULTS = {
    "sentimento": "neutro",
    "impacto": "medio",
    "topicos_principais": [],
    "entidades_mencionadas": {"pessoas": [], "organizacoes": [], "locais": []},
    "palavras_chave": [],
    "angulo_discussao": "",
    "autor": "Não informado",
    "data_publicacao": "Não informada",
}
