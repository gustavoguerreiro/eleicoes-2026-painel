# Colocar no ar (nginx + HTTPS + deploy automático)

```
 Pessoas ──https──▶ nginx (443, certificado Let's Encrypt, microcache, limite de pedidos)
                      └──▶ painel em Docker (127.0.0.1:8765) ──▶ TSE
 GitHub (push na main) ──testes──▶ ssh ──▶ deploy.sh (build, espera /healthz, volta atrás se falhar)
```

Tudo roda em **uma** máquina e **uma** instância do painel (o histórico do gráfico fica na memória e em `logs/`; duas
instâncias teriam históricos diferentes). Para umas 40 pessoas, 1 vCPU e 1 GB bastam.

## 1. O que você precisa

| Item | Detalhe |
|---|---|
| **Domínio** | Precisa de um nome (o certificado não sai para IP puro). Pode ser um subdomínio de um domínio seu ou um grátis (DuckDNS). Crie um registro **A** apontando para o IP do servidor. |
| **Servidor** | Ubuntu 22.04 ou 24.04. DigitalOcean: droplet básico 1 vCPU / 1 GB (cerca de US$ 6/mês, confira o preço). EC2: `t3.small` (ou `t3.micro` com a swap que o setup cria). A DigitalOcean não tem região em São Paulo; para este painel a latência não importa. |
| **Portas** | Libere 22, 80 e 443 (firewall do provedor/Security Group). O `setup.sh` também configura o `ufw`. |
| **Chave SSH** | Uma chave só para o deploy automático (passo 2). |

## 2. Chave para o GitHub Actions entrar no servidor

No seu computador (não coloque senha na chave):

```bash
ssh-keygen -t ed25519 -f deploy_key -C github-actions -N ""
```

`deploy_key` (privada) vai para o GitHub; `deploy_key.pub` (pública) vai para o servidor. Não commite nenhuma das duas.

## 3. Preparar o servidor (uma vez)

**Antes**, faça push desta pasta `deploy/` para o GitHub (o setup baixa o repositório). Se o repositório for privado, use
`REPO=git@github.com:...` com uma deploy key, ou copie o código com `scp`.

```bash
ssh root@IP_DO_SERVIDOR
curl -fsSL https://raw.githubusercontent.com/gustavoguerreiro/eleicoes-2026-painel/main/deploy/setup.sh -o setup.sh
DOMINIO=painel.exemplo.com EMAIL=voce@exemplo.com DEPLOY_PUBKEY="$(cat colar-aqui-a-chave-publica)" bash setup.sh
```

O script instala nginx, certbot e Docker, cria o usuário `deploy`, liga o firewall e o `fail2ban`, publica o painel
(build da imagem), emite o certificado, ativa a renovação automática e **confere se o servidor alcança o TSE**. Pode rodar
de novo quando mudar o nginx: ele é idempotente.

## 4. Deploy automático (GitHub)

Em *Settings → Secrets and variables → Actions*:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `DEPLOY_SSH_KEY` | conteúdo de `deploy_key` (a privada) |
| Secret | `DEPLOY_KNOWN_HOSTS` | saída de `ssh-keyscan -t ed25519 IP_DO_SERVIDOR` |
| Secret | `DEPLOY_USER` | `deploy` |
| Secret | `DEPLOY_HOST` | o IP (ou o domínio) do servidor |
| Variable | `DOMINIO` | `painel.exemplo.com` |
| Variable | `DEPLOY_ATIVO` | `true` (qualquer outro valor desliga o deploy) |

A partir daí, todo push na `main` roda os testes e, se passarem, publica. O `deploy.sh` sobe a nova versão, espera o
`/healthz` e, se ela não responder, **volta sozinho para a versão anterior** e o job fica vermelho.

## 5. Conferir

```bash
curl -s https://painel.exemplo.com/healthz          # {"ok":true,...}
curl -sI https://painel.exemplo.com/api?turno=2     # 200, Cache-Control: public ...
```

Abra o endereço no navegador: só o RN, sem seletor de estado e sem chat. Cadeado verde. Teste também no celular.

## 6. Ensaio geral antes do dia 25

```bash
ssh deploy@IP
cd /opt/eleicoes && docker compose -f docker-compose.yml -f deploy/compose.simulacao.yml up -d   # noite simulada
```

Chame alguns amigos para abrir ao mesmo tempo. Para voltar ao normal: `docker compose up -d` (um novo deploy também volta).

## 7. Noite da eleição

- **Congele o deploy:** variável `DEPLOY_ATIVO=false` no GitHub. Nada de mexer no código ao vivo.
- **Monitor externo:** cadastre `https://painel.exemplo.com/healthz` no UptimeRobot (grátis, a cada 5 min, aviso por e-mail).
  O `/healthz` responde 503 se o dado ficar velho (mais de 2 min).
- **Acompanhar:** `docker compose logs -f painel` (erros do TSE aparecem como `TSE respondeu 429...`).
- **Reiniciar sem perder o gráfico:** `docker compose restart painel`. O histórico vem de `logs/historico_2t.json` (volume).

## 8. Operação

| O que | Comando (no servidor, como `deploy`, em `/opt/eleicoes`) |
|---|---|
| Ver estado | `docker compose ps` e `docker compose logs --tail=100 painel` |
| Publicar na mão | `bash deploy/deploy.sh` |
| Voltar para uma versão | `git reset --hard SHA && docker compose up -d --build` |
| Mudou o nginx | como root: `DOMINIO=... EMAIL=... bash deploy/setup.sh` |
| Renovação do certificado | automática (`systemctl list-timers \| grep certbot`) |

## 9. Makefile: deploy, logs e acessos

Há um `Makefile` na raiz. De fora do servidor, crie o arquivo `.env.make` (ignorado pelo git) com
`SERVIDOR=deploy@painel.exemplo.com`; no próprio servidor não precisa. `make` sozinho lista tudo:

| Comando | O que faz |
|---|---|
| `make deploy` / `make rollback SHA=...` | publica a main / volta para uma versão |
| `make status` / `make saude DOMINIO=...` | containers, versão e saúde / confere o site público |
| `make logs` / `make logs-erros` / `make nginx-erros` | log do painel (ao vivo) / só avisos e erros / erros do nginx |
| `make acessos` | resumo: pessoas distintas, aberturas, **pico de gente ao mesmo tempo**, erros, % servido pelo cache |
| `make ativos` | quantas pessoas estão com o painel aberto agora |
| `make acessos-ao-vivo` | cada pedido em tempo real |
| `make por-hora` / `make dispositivos` / `make origens` / `make erros-http` | acessos por hora / celular x computador / de onde vieram / respostas 4xx e 5xx |
| `make coletar` | baixa os logs de acesso e o histórico do gráfico para `./dados/` (para você analisar depois) |
| `make simular` / `make normal` | liga / desliga o ensaio com a noite simulada |

Os acessos vêm do log do nginx (`/var/log/painel/access.log`, no horário de Brasília), que o `setup.sh` guarda por **90 dias**
(rotação diária, comprimido). "Visitante" = IP + navegador: separa aparelhos diferentes no mesmo Wi-Fi, mas é uma estimativa
(a mesma pessoa no celular e no computador conta duas vezes). O log tem IPs de visitantes (dado pessoal): `./dados/` não
vai para o git e o relatório não lista IPs, só números agregados.

No Windows o `make` não vem instalado (use o WSL ou `winget install ezwinports.make`), ou rode os mesmos comandos no
servidor, onde o `make` existe (`sudo apt install make`).

## 10. Depois da eleição: o retrato dos acessos

**Antes de apagar o servidor:**

```bash
make coletar      # baixa os logs de acesso e o histórico do gráfico para ./dados/
make relatorio    # gera dados/relatorio.md (também dá para rodar de novo offline com `make relatorio-local`)
```

O relatório (`dados/relatorio.md`) traz: visitantes distintos, aberturas da página, **pico de gente ao mesmo tempo**,
tempo de permanência (média, mediana, faixas), a curva de audiência a cada 10 minutos (em barras), visitantes por dia e
quantos voltaram, celular x computador, de onde vieram (WhatsApp, redes, link direto) e os erros. Se quiser outro
recorte, os logs brutos ficam em `dados/`.

## 11. O que foi testado aqui (e o que não foi)

Testado no meu PC com Docker: o build da imagem e o painel rodando em container (usuário comum, volume gravável, alcança o
TSE, só o RN); o `nginx -t` da configuração e o nginx na frente do painel (proxy, microcache `MISS`→`HIT`, gzip, limite de
pedidos devolvendo 429, 404 para `/geo/uf/SP` e `/api/chat`, cabeçalhos de segurança, log no formato novo); o `deploy.sh`
em dois cenários, **versão boa** (sobe e confirma `/healthz`) e **versão quebrada** (detecta, volta para a anterior e sai
com erro); o `acessos.sh` contra um log real do nginx e contra logs sintéticos de 2 dias; o `Makefile` com GNU make.

**Não foi testado**: o `setup.sh` (precisa de um Ubuntu de verdade: apt, certbot, ufw, firewall do provedor), a emissão do
certificado Let's Encrypt, o GitHub Actions e o acesso ao TSE a partir do IP do provedor. O `setup.sh` confere o TSE no final.
Faça o setup na sexta, como combinado, e confira a lista da seção 5 antes de divulgar o link.

## 12. Limites e riscos (leia)

- **O TSE pode bloquear IP de datacenter.** O `setup.sh` testa isso no fim. Se falhar, tente outra região/provedor, ou rode o
  painel no seu PC com Cloudflare Tunnel (é o plano B).
- **Não foi testado num servidor real** (escrevi e validei a sintaxe aqui, mas só você consegue rodar o `setup.sh` de verdade).
  Faça o passo 3 pelo menos uns dias antes da eleição.
- **Não escale para duas máquinas:** o histórico e os limites ficam na memória de cada processo.
- **Chat:** fica desligado no modo público. Só ligaria com `CHAT_ATIVO=1` no `.env` e a chave da Anthropic (não recomendado).
