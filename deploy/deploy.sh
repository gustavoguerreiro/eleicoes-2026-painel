#!/usr/bin/env bash
# Publica a versão mais recente da branch main neste servidor, SEM derrubar o que está no ar se a nova versão falhar:
# sobe, espera o /healthz responder e, se não responder, volta para o commit anterior.
# Quem chama: o GitHub Actions (ssh) ou você (`/opt/eleicoes/deploy/deploy.sh`). Roda como o usuário `deploy`.
set -euo pipefail

cd "$(dirname "$0")/.."
PORTA="${PORTA:-8765}"          # o mesmo PORTA do docker-compose.yml (só muda ao testar ao lado de outro painel)
export PORTA
exec 9>/tmp/eleicoes-deploy.lock
flock -n 9 || { echo "Já existe um deploy em andamento."; exit 1; }

ANTES=$(git rev-parse HEAD)
git fetch --quiet origin main
git reset --hard origin/main
DEPOIS=$(git rev-parse HEAD)
echo "Deploy: ${ANTES:0:7} -> ${DEPOIS:0:7}"

subir() { docker compose up -d --build --remove-orphans; }
saudavel() {                       # até ~2 min: o /healthz responde 200 quando o painel está de pé
  for _ in $(seq 1 40); do
    if curl -fsS -m 4 "http://127.0.0.1:$PORTA/healthz" >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  return 1
}

if subir && saudavel; then
  echo "No ar: ${DEPOIS:0:7}"
  docker image prune -f >/dev/null
  exit 0
fi

echo "FALHOU. Voltando para ${ANTES:0:7}..." >&2
docker compose logs --tail=40 painel >&2 || true
git reset --hard "$ANTES"
subir && saudavel && echo "Rollback ok: ${ANTES:0:7}" >&2 || echo "ATENÇÃO: o rollback também falhou." >&2
exit 1
