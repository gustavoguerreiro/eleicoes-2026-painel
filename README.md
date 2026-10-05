# Eleições 2026 — painel

Painel ao vivo da apuração das eleições de 2026, com dados da divulgação oficial do TSE
(`resultados.tse.jus.br`): presidente, governador, senador, deputado federal e estadual, por estado e Brasil,
com indicação de 2º turno e visão de bancadas do Congresso.

## Como rodar

Requer Python 3.10+ (só biblioteca padrão).

```bash
cd backend
python painel_server.py --web          # abre http://localhost:8765
python painel_server.py --uf pe        # estado inicial diferente
python painel_server.py --uma-vez      # versão terminal (só 1º turno), imprime uma vez
python painel_server.py --web --simular-2t --sim-duracao 120   # TESTE do 2º turno com dados fabricados
```

No Windows: duplo clique em `iniciar.bat`.

## 1º e 2º turno

O painel abre no **2º turno** (25/10/2026) e tem um seletor para o resultado final do **1º turno**.

- **Antes de 25/10** os arquivos do 2º turno ainda não existem no TSE (dão 404). O painel detecta isso sozinho e
  mostra o duelo com o desempenho dos finalistas no 1º turno e "o que está em disputa" (votos dos eliminados,
  brancos, nulos e abstenção).
- **Quando o TSE publicar** os arquivos, o painel passa sozinho ao modo ao vivo: placar, barra dos 50% e mapas
  com o resultado do 2º turno. Os códigos de eleição do 2º turno são lidos do `ele-c.json` (campo `cdt2`).
- **`--simular-2t`** fabrica arquivos de 2º turno a partir dos do 1º (divisão pseudo-aleatória dos votos dos demais
  candidatos, apuração avançando até 100%) para testar a tela sem dado real. O painel mostra um aviso de simulação.

## Chat: planos de governo (RAG) + números do painel

A aba **Pergunte** responde sobre (1) o que os candidatos propõem, com base nos **planos de governo registrados no
TSE**, e (2) os **números da apuração** do próprio painel ("qual a diferença de votos entre Flávio e Lula?").

```
planos (PDF) ──► extração e limpeza ──► trechos por seção/página ──► índice BM25
                                                                         │
pergunta ──► Claude decide as ferramentas ──┬─ buscar_propostas ─────────┘  (cita a página)
                                            ├─ resultados / resultados_por_regiao / resumo_geral  (números do TSE)
                                            └─ listar_documentos
```

**Por que ferramentas em vez de fine-tuning.** Fine-tuning ensina estilo, não fatos: o modelo "esqueceria" o placar a
cada minuto, erraria contas e não saberia citar a página. Aqui o modelo só decide *o que consultar*; os números e as
diferenças são calculados em Python a partir dos mesmos dados do painel, e as propostas vêm de trechos citáveis.

- **Citação obrigatória.** Cada proposta termina com `[n]`; clicar abre o trecho original, a página e o link do plano no TSE.
- **Imparcial por construção.** Terceira pessoa, mesmo rigor para todos, sem indicar voto nem se passar por candidato
  (regras no prompt em `backend/chat.py`; há teste que garante que elas continuam lá).
- **Fora do escopo desta versão:** biografia e processos, pesquisas de intenção de voto e previsões. O chat diz isso e
  aponta fontes oficiais.
- **Conversa no servidor.** O navegador só manda a nova pergunta; o histórico é só de acréscimo e turnos incompletos
  (falha, recusa, aba fechada) são descartados, então o histórico nunca fica inválido.
- **Proteções de custo e abuso.** Limite por IP (20 perguntas/10 min, 120/dia) e global; `POST /api/chat` só aceita
  `application/json` e confere a origem, para outro site não conseguir gastar a sua chave.

### Como configurar

```bash
pip install -r backend/requirements.txt
copy .env.example .env                       # e preencha ANTHROPIC_API_KEY (o .env nunca vai para o git)
cd backend
python -m rag.ingestao                       # PDFs em data/planos/ -> data/rag/trechos.jsonl (já versionado)
python painel_server.py --web
```

Modelo padrão: `claude-opus-5-5`. Para gastar menos: `CLAUDE_MODEL=claude-sonnet-5-5` no `.env`. As perguntas dos
usuários são enviadas à API da Anthropic.

### Qualidade

```bash
python -m rag.avaliacao                      # mede a BUSCA (sem custo): hit@k e MRR em data/rag/avaliacao.json
python -m unittest discover -s tests -v      # 32 testes: limpeza, busca, ferramentas, laço do chat, limitador
```

A avaliação das 22 perguntas dá hit@5 = 100% e MRR 0,95. As perguntas foram escritas depois de conhecer o corpus,
então o número é otimista: serve como alarme de regressão, não como nota final.

## Estrutura

- `backend/painel_server.py` — coleta os arquivos do TSE, projeta cadeiras e serve a API
  (`/api?uf=RN&turno=1|2`, `/api/mapa?uf=RN&cargo=3&turno=2`, `/geo/...`, `/api/chat`).
- `backend/chat.py`, `backend/chat_ferramentas.py` — o chat: prompt, laço com ferramentas, limitador e as ferramentas.
- `backend/rag/` — `texto.py` (limpeza), `ingestao.py` (PDF → trechos), `busca.py` (BM25), `avaliacao.py`.
- `backend/geo.py` — malhas e nomes do IBGE, com cache em `data/geo/`.
- `frontend/painel.html` — página única que consome a API e se atualiza sozinha.
- `data/planos/` — planos de governo dos candidatos (TSE) e `manifesto.json` com a origem de cada um.
- `data/rag/` — trechos indexados e o conjunto de avaliação.
- `tests/` — testes automatizados.

## Aviso

Projeções de deputados são estimativas (quociente eleitoral, cláusulas de 80%/20% e sobras); o resultado oficial
é o que o TSE marca como eleito. O assistente é uma ferramenta informativa e não oficial.

## Roadmap

- [x] Mapas do Brasil e do RN (malhas do IBGE)
- [x] RAG com os planos de governo registrados no TSE
- [x] Chat com citações das fontes
- [x] Testes automatizados
- [ ] Busca híbrida (embeddings) se o corpus crescer — ponto de troca em `Indice.pontuar`
- [ ] CI e deploy
