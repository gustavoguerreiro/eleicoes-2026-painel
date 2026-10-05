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
python painel_server.py --uma-vez      # versão terminal, imprime uma vez
```

No Windows: duplo clique em `iniciar.bat`.

## Estrutura

- `backend/painel_server.py` — coleta os arquivos do TSE, projeta cadeiras e serve a API (`/api?uf=RN`).
- `frontend/painel.html` — página única que consome a API e se atualiza sozinha.

## Aviso

Projeções de deputados são estimativas (quociente eleitoral, cláusulas de 80%/20% e sobras); o resultado oficial
é o que o TSE marca como eleito.

## Roadmap

- [ ] Mapas do Brasil e do RN (malhas do IBGE)
- [ ] RAG com os planos de governo registrados no TSE
- [ ] Chat com citações das fontes
- [ ] Testes, CI e deploy
