#!/usr/bin/env bash
# Prepara um servidor Ubuntu 22.04/24.04 NOVO (DigitalOcean, EC2...) para rodar o painel com nginx + HTTPS.
# Rode como root, UMA vez (é seguro rodar de novo: tudo aqui é idempotente):
#
#   DOMINIO=painel.exemplo.com EMAIL=voce@exemplo.com DEPLOY_PUBKEY="ssh-ed25519 AAAA... github-actions" \
#     bash setup.sh
#
# Antes: o registro DNS tipo A de DOMINIO já precisa apontar para o IP deste servidor (o certificado depende disso).
# Variáveis opcionais: REPO (padrão: o repositório do projeto, via https), DEPLOY_PUBKEY (chave que o GitHub Actions usa).
set -euo pipefail

: "${DOMINIO:?defina DOMINIO (ex.: painel.exemplo.com)}"
: "${EMAIL:?defina EMAIL (avisos de renovação do certificado)}"
REPO="${REPO:-https://github.com/gustavoguerreiro/eleicoes-2026-painel.git}"
DIR=/opt/eleicoes
USUARIO=deploy

[ "$(id -u)" = 0 ] || { echo "Rode como root (sudo bash setup.sh)."; exit 1; }
echo "$DOMINIO" | grep -Eq '^[A-Za-z0-9.-]+$' || { echo "DOMINIO inválido: $DOMINIO"; exit 1; }

echo "==> DNS"
if ! getent hosts "$DOMINIO" >/dev/null; then
  echo "O nome $DOMINIO ainda não resolve. Crie o registro A apontando para o IP deste servidor e espere propagar."
  exit 1
fi

echo "==> Pacotes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git nginx certbot python3-certbot-nginx ufw fail2ban unattended-upgrades

echo "==> Fuso horário de Brasília (os logs e o relatório ficam no horário que você conhece)"
timedatectl set-timezone America/Sao_Paulo || true

echo "==> Swap (1 GB), para o build da imagem não faltar memória em máquinas de 1 GB"
if ! swapon --show | grep -q .; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Docker"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

echo "==> Usuário de deploy ($USUARIO): sem senha, só chave SSH, no grupo docker"
id "$USUARIO" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$USUARIO"
usermod -aG docker,adm "$USUARIO"        # adm: ler os logs do nginx (make acessos)
if [ -n "${DEPLOY_PUBKEY:-}" ]; then
  install -d -m 700 -o "$USUARIO" -g "$USUARIO" "/home/$USUARIO/.ssh"
  grep -qxF "$DEPLOY_PUBKEY" "/home/$USUARIO/.ssh/authorized_keys" 2>/dev/null || echo "$DEPLOY_PUBKEY" >> "/home/$USUARIO/.ssh/authorized_keys"
  chown "$USUARIO:$USUARIO" "/home/$USUARIO/.ssh/authorized_keys"; chmod 600 "/home/$USUARIO/.ssh/authorized_keys"
fi

echo "==> Código em $DIR"
if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO" "$DIR"
fi
chown -R "$USUARIO:$USUARIO" "$DIR"

echo "==> Firewall: só SSH, HTTP e HTTPS"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

echo "==> Log de acessos (/var/log/painel, guardado 90 dias) para o relatório pós-eleição"
install -d -m 750 -o root -g adm /var/log/painel
cat > /etc/logrotate.d/painel <<'LOGROTATE'
/var/log/painel/access.log {
    daily
    rotate 90
    dateext
    compress
    missingok
    notifempty
    create 640 root adm
    sharedscripts
    postrotate
        [ ! -f /run/nginx.pid ] || kill -USR1 "$(cat /run/nginx.pid)"
    endscript
}
LOGROTATE

echo "==> nginx"
rm -f /etc/nginx/sites-enabled/default
sed "s/__DOMINIO__/$DOMINIO/g" "$DIR/deploy/nginx/painel.conf.template" > /etc/nginx/conf.d/painel.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> Primeiro deploy do painel (build da imagem; leva alguns minutos)"
sudo -u "$USUARIO" bash "$DIR/deploy/deploy.sh"

echo "==> Certificado HTTPS (Let's Encrypt) e renovação automática"
certbot --nginx -d "$DOMINIO" -m "$EMAIL" --agree-tos --no-eff-email --redirect --non-interactive
systemctl enable --now certbot.timer || true
certbot renew --dry-run

echo "==> Conferindo se este servidor alcança o TSE"
if curl -fsS -m 20 -o /dev/null "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json"; then
  echo "TSE: ok"
else
  echo "ATENÇÃO: este servidor NÃO conseguiu falar com o TSE. O painel ficaria sem dados."
  echo "         Isso pode ser bloqueio do IP do provedor. Teste outro provedor/região antes da eleição."
fi

echo
echo "Pronto: https://$DOMINIO"
echo "Saúde:  https://$DOMINIO/healthz"
