# Atalhos de deploy, logs e acessos do painel. `make` (ou `make ajuda`) lista tudo.
#
# De fora do servidor (seu computador):   make deploy SERVIDOR=deploy@painel.exemplo.com
# Para não repetir, crie o arquivo .env.make (não vai para o git) com uma linha:   SERVIDOR=deploy@painel.exemplo.com
# No próprio servidor, deixe SERVIDOR vazio: os comandos rodam ali mesmo.
#
# No Windows o `make` não vem instalado: use o WSL, ou `winget install ezwinports.make`, ou rode estes comandos no servidor.

.RECIPEPREFIX := >
.DEFAULT_GOAL := ajuda
SHELL := bash

-include .env.make

SERVIDOR ?=
DIR ?= /opt/eleicoes
DOMINIO ?=
SHA ?=

ifdef SERVIDOR
REMOTO = ssh -o BatchMode=yes $(SERVIDOR)
else
REMOTO = bash -c
endif

.PHONY: ajuda test deploy rollback status saude reiniciar simular normal \
        logs logs-erros nginx-erros acessos relatorio relatorio-local ativos acessos-ao-vivo por-hora dispositivos origens erros-http coletar

ajuda: ## mostra esta lista
> @grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  make %-16s %s\n", $$1, $$2}'

test: ## roda os testes aqui (sem servidor)
> python -m unittest discover -s tests

# ---- publicar ---------------------------------------------------------------------------------------------
deploy: ## publica a main no servidor (volta sozinho para a versão anterior se falhar)
> $(REMOTO) 'bash $(DIR)/deploy/deploy.sh'

rollback: ## volta para uma versão: make rollback SHA=abc1234
> @test -n "$(SHA)" || { echo "informe o commit: make rollback SHA=abc1234"; exit 1; }
> $(REMOTO) 'cd $(DIR) && git reset --hard $(SHA) && docker compose up -d --build'

reiniciar: ## reinicia o painel (o histórico do gráfico é mantido)
> $(REMOTO) 'cd $(DIR) && docker compose restart painel'

simular: ## ensaio: sobe a noite da eleição SIMULADA no servidor
> $(REMOTO) 'cd $(DIR) && docker compose -f docker-compose.yml -f deploy/compose.simulacao.yml up -d'

normal: ## volta ao painel normal (depois do ensaio)
> $(REMOTO) 'cd $(DIR) && docker compose up -d'

# ---- estado e logs ----------------------------------------------------------------------------------------
status: ## containers, versão publicada e saúde
> $(REMOTO) 'cd $(DIR) && docker compose ps && git log -1 --format="versão: %h %s (%cr)" && curl -s http://127.0.0.1:8765/healthz; echo'

saude: ## confere o site público (DOMINIO=painel.exemplo.com)
> @test -n "$(DOMINIO)" || { echo "informe o domínio: make saude DOMINIO=painel.exemplo.com"; exit 1; }
> curl -fsS https://$(DOMINIO)/healthz; echo

logs: ## segue o log do painel (Ctrl+C para sair)
> $(REMOTO) 'cd $(DIR) && docker compose logs -f --tail=100 painel'

logs-erros: ## só avisos e erros do painel (falhas do TSE, exceções)
> $(REMOTO) 'cd $(DIR) && docker compose logs --tail=2000 painel | grep -Ei "warning|error|falha|traceback|TSE respondeu"'

nginx-erros: ## últimas linhas do log de erros do nginx
> $(REMOTO) 'tail -n 60 /var/log/nginx/error.log'

# ---- acessos (log do nginx, formato "painel") ---------------------------------------------------------------
acessos: ## resumo: visitantes, aberturas, pico simultâneo, erros, % servido pelo cache
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh resumo'

relatorio: ## relatório completo da eleição (visitantes, pico, permanência, audiência, aparelhos, origens); salva em dados/
> @mkdir -p dados
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh relatorio' | tee dados/relatorio.md

relatorio-local: ## o mesmo relatório, a partir dos logs baixados com `make coletar` (funciona sem o servidor)
> @test -e dados/access.log || { echo "rode make coletar antes"; exit 1; }
> LOG=dados/access.log bash deploy/acessos.sh relatorio | tee dados/relatorio.md

ativos: ## quantas pessoas estão com o painel aberto agora
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh ativos'

acessos-ao-vivo: ## cada pedido, em tempo real (Ctrl+C para sair)
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh ao-vivo'

por-hora: ## pessoas, aberturas e pedidos por hora
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh por-hora'

dispositivos: ## celular x computador x robôs
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh dispositivos'

origens: ## de onde as pessoas vieram (link direto, WhatsApp, redes...)
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh origens'

erros-http: ## últimas respostas 4xx/5xx
> $(REMOTO) 'bash $(DIR)/deploy/acessos.sh erros'

coletar: ## baixa os logs de acesso e o histórico do gráfico para ./dados/ (só funciona de fora do servidor)
> @test -n "$(SERVIDOR)" || { echo "informe SERVIDOR=deploy@painel.exemplo.com"; exit 1; }
> mkdir -p dados
> scp -q '$(SERVIDOR):/var/log/painel/access.log*' dados/
> ssh -o BatchMode=yes $(SERVIDOR) 'cd $(DIR) && docker compose exec -T painel cat logs/historico_2t.json' > dados/historico_2t.json
> @echo "salvo em ./dados/ (logs com IPs: dado pessoal, não publique)"
