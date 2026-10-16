#!/usr/bin/env bash
# Estatísticas de acesso, lidas do log do nginx (formato "painel", definido em deploy/nginx/painel.conf.template):
#   IP [hora ISO] "pedido" status bytes tempo cache "user-agent" "referer"
# Uso:  bash acessos.sh [resumo|relatorio|ativos|por-hora|dispositivos|origens|erros|ao-vivo]
# Lê o log atual e os rotacionados (access.log-AAAAMMDD[.gz]). LOG=/outro/arquivo muda o caminho.
#
# "Visitante" = IP + navegador (user-agent): separa aparelhos diferentes atrás do mesmo Wi-Fi, mas é uma estimativa
# (a mesma pessoa no celular e no computador conta duas vezes; dois iPhones iguais no mesmo Wi-Fi contam um).
set -uo pipefail
LOG="${LOG:-/var/log/painel/access.log}"

todos() {
  { for f in "$LOG"-*; do [ -e "$f" ] && zcat -f "$f"; done
    [ -e "$LOG" ] && cat "$LOG"; } 2>/dev/null
}

# Cada linha vira: ip, t (AAAA-MM-DDTHH:MM:SS), metodo, caminho (sem ?query), status, bytes, tempo, cache, ua, ref, vis
PARSE='BEGIN{FS="\""}
function jdn(y,m,d,   a,yy,mm) { a=int((14-m)/12); yy=y+4800-a; mm=m+12*a-3
  return d+int((153*mm+2)/5)+365*yy+int(yy/4)-int(yy/100)+int(yy/400)-32045 }
function epoca(s) { return jdn(substr(s,1,4)+0,substr(s,6,2)+0,substr(s,9,2)+0)*86400+substr(s,12,2)*3600+substr(s,15,2)*60+substr(s,18,2) }
function tipo(u) { if (u ~ /bot|crawler|spider|UptimeRobot|curl|monitor|Wget|python/) return "robô"
  if (u ~ /Mobi|Android|iPhone|iPad/) return "celular/tablet"; return "computador" }
{ split($1,a," "); ip=a[1]; t=substr(a[2],2,19)
  split($2,r," "); metodo=r[1]; caminho=r[2]; sub(/\?.*/,"",caminho)
  split($3,b," "); st=b[1]+0; by=b[2]+0; tempo=b[3]; cache=b[4]
  ua=$4; ref=$6; vis=ip "|" ua }'

cmd="${1:-resumo}"
case "$cmd" in
  resumo)
    todos | awk "$PARSE"'
      { n++; ips[ip]=1; viss[vis]=1; bytes+=by
        if (n==1) ini=t; fim=t
        if (st>=400 && st<500) e4++; if (st>=500) e5++
        if (caminho=="/" || caminho=="/index.html") loads++
        if (caminho=="/api") { api++; if (cache=="HIT") hit++
          m=substr(t,1,16); k=m SUBSEP vis; if (!(k in vistos)) { vistos[k]=1; porMin[m]++ } }
      }
      END { if (!n) { print "Sem acessos no log."; exit }
        for (m in porMin) { if (porMin[m]>pico) { pico=porMin[m]; quando=m } }
        for (i in ips) u++; for (i in viss) v++
        printf "Período:                      %s  até  %s\n", ini, fim
        printf "Pedidos no total:             %d  (%.1f MB enviados)\n", n, bytes/1048576
        printf "Visitantes (IP + navegador):  %d   (IPs distintos: %d)\n", v, u
        printf "Aberturas da página:          %d\n", loads
        printf "Pico de gente ao mesmo tempo: %d  (minuto %s)\n", pico, quando
        printf "Respostas 4xx / 5xx:          %d / %d\n", e4, e5
        if (api) printf "/api servida pelo cache:      %.0f%%  (%d de %d)\n", 100*hit/api, hit, api }'
    ;;

  relatorio)    # o retrato completo da eleição: para rodar depois que tudo acabou
    tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
    todos > "$tmp"
    [ -s "$tmp" ] || { echo "Sem acessos no log ($LOG)."; exit 1; }
    echo "# Relatório de acessos: painel Apuração 2026"
    echo
    echo "## Visão geral"
    awk "$PARSE"'
      { n++; ips[ip]=1; viss[vis]=1; bytes+=by
        if (n==1) ini=t; fim=t
        if (st>=400 && st<500) e4++; if (st>=500) e5++
        if (caminho=="/" || caminho=="/index.html") { loads++; lv[vis]++ }
        if (caminho=="/api") { api++; if (cache=="HIT") hit++
          m=substr(t,1,16); k=m SUBSEP vis; if (!(k in vistos)) { vistos[k]=1; porMin[m]++ } }
      }
      END { for (m in porMin) { if (porMin[m]>pico) { pico=porMin[m]; quando=m } }
        for (i in ips) u++; for (i in viss) v++; for (i in lv) vl++
        printf "- Período dos dados: %s até %s\n", ini, fim
        printf "- **Visitantes distintos (IP + navegador): %d** (IPs distintos: %d)\n", v, u
        printf "- Aberturas da página: %d (%d visitantes abriram; média de %.1f aberturas por visitante)\n", loads, vl, (vl ? loads/vl : 0)
        printf "- **Pico de gente ao mesmo tempo: %d** (no minuto %s)\n", pico, quando
        printf "- Pedidos: %d (%.1f MB enviados); %.0f%% da /api veio do cache do nginx\n", n, bytes/1048576, (api ? 100*hit/api : 0)
        printf "- Respostas de erro: %d (4xx) e %d (5xx)\n", e4, e5 }' "$tmp"

    echo
    echo "## Quanto tempo ficaram com o painel aberto (sessões)"
    echo "Uma sessão acaba quando o visitante passa mais de 5 minutos sem atualizar. Aba em segundo plano conta como aberta."
    awk "$PARSE"'
      caminho=="/api" { s=epoca(t)
        if ((vis in ult) && s-ult[vis] > 300) { print ult[vis]-ini[vis]+10; ini[vis]=s }
        if (!(vis in ini)) ini[vis]=s
        ult[vis]=s }
      END { for (v in ult) print ult[v]-ini[v]+10 }' "$tmp" | sort -n | awk '
      { d[NR]=$1/60; soma+=$1/60
        if ($1<120) b1++; else if ($1<600) b2++; else if ($1<1800) b3++; else if ($1<3600) b4++; else b5++ }
      END { if (!NR) { print "(sem dados de /api)"; exit }
        printf "- Sessões: %d\n", NR
        printf "- Tempo médio: %.1f min; mediana: %.1f min; 90%% ficaram até %.1f min; a maior: %.0f min\n", soma/NR, d[int((NR+1)/2)], d[int(0.9*NR)+(0.9*NR>int(0.9*NR)?1:0)], d[NR]
        printf "- Até 2 min: %d | 2 a 10 min: %d | 10 a 30 min: %d | 30 a 60 min: %d | mais de 1 h: %d\n", b1, b2, b3, b4, b5 }'

    echo
    echo "## Audiência ao longo do tempo (visitantes distintos a cada 10 minutos)"
    echo '```'
    awk "$PARSE"'
      caminho=="/api" { q=substr(t,1,15) "0"; k=q SUBSEP vis; if (!(k in v)) { v[k]=1; c[q]++ } }
      END { for (q in c) print q, c[q] }' "$tmp" | sort | awk '
      { l[NR]=$1; n[NR]=$2; if ($2>max) max=$2 }
      END { for (i=1;i<=NR;i++) { w=int(40*n[i]/max+0.5); bar=""; for (j=0;j<w;j++) bar=bar "#"
        printf "%s %4d %s\n", substr(l[i],6,5) " " substr(l[i],12,5), n[i], bar } }'
    echo '```'

    echo
    echo "## Por dia"
    awk "$PARSE"'
      { d=substr(t,1,10); k=d SUBSEP vis; if (!(k in v)) { v[k]=1; vd[d]++; dias[vis]++ } reqs[d]++ }
      END { for (d in vd) printf "%s %d %d\n", d, vd[d], reqs[d]
        for (x in dias) { tot++; if (dias[x]>1) volt++ }
        printf "VOLTARAM %d %d\n", volt, tot }' "$tmp" | sort | awk '
      /^VOLTARAM/ { volt=$2; tot=$3; next }
      { printf "- %s: %d visitantes, %d pedidos\n", $1, $2, $3 }
      END { printf "- Voltaram em mais de um dia: %d de %d visitantes\n", volt, tot }'

    echo
    echo "## Aparelhos (por visitante)"
    awk "$PARSE"' { if (!(vis in cl)) cl[vis]=tipo(ua) } END { for (x in cl) c[cl[x]]++; for (k in c) printf "%s %d\n", k, c[k] }' "$tmp" | sort | awk '{ n=$NF; sub(/ *[0-9]+$/, ""); printf "- %s: %d\n", $0, n }'

    echo
    echo "## De onde vieram (referer na abertura da página)"
    awk "$PARSE"'
      caminho=="/" { o=ref; if (o=="" || o=="-") o="direto (link colado, WhatsApp, app)"; else { sub(/^https?:\/\//,"",o); sub(/\/.*/,"",o) } k=o SUBSEP vis; if (!(k in v)) { v[k]=1; c[o]++ } }
      END { for (k in c) printf "%d\t%s\n", c[k], k }' "$tmp" | sort -rn | head -12 | awk -F"\t" '{ printf "- %s: %d visitantes\n", $2, $1 }'

    echo
    echo "## Problemas"
    awk "$PARSE"' st>=500 { c5++ } st==429 { c429++ } st==404 { c404++ }
      END { printf "- 5xx (falhas do servidor): %d\n- 429 (limite de pedidos do nginx): %d\n- 404 (endereço que não existe): %d\n", c5, c429, c404 }' "$tmp"
    ;;

  ativos)       # quem pediu /api nos últimos 2 minutos = quem está com o painel aberto agora
    desde="$(date -d '2 minutes ago' +%Y-%m-%dT%H:%M)"
    tail -n 5000 "$LOG" 2>/dev/null | awk -v desde="$desde" "$PARSE"'
      caminho=="/api" && substr(t,1,16) >= desde { vs[vis]=1 }
      END { for (i in vs) n++; printf "Pessoas com o painel aberto agora (últimos 2 min): %d\n", n }'
    ;;
  por-hora)
    printf "%-14s %10s %10s %10s\n" "hora" "visitantes" "aberturas" "pedidos"
    todos | awk "$PARSE"'
      { h=substr(t,1,13); k=h SUBSEP vis; if (!(k in v)) { v[k]=1; vs[h]++ }
        reqs[h]++; if (caminho=="/") loads[h]++ }
      END { for (h in reqs) printf "%-14s %10d %10d %10d\n", h, vs[h], loads[h], reqs[h] }' | sort
    ;;
  dispositivos)
    todos | awk "$PARSE"'
      { if (!(vis in cl)) cl[vis]=tipo(ua) }
      END { for (x in cl) c[cl[x]]++; for (k in c) printf "%-16s %d visitantes\n", k, c[k] }' | sort
    ;;
  origens)      # de onde vieram (referer da abertura da página)
    todos | awk "$PARSE"'
      caminho=="/" { o=ref; if (o=="" || o=="-") o="(direto: link colado, WhatsApp, app...)"; else { sub(/^https?:\/\//,"",o); sub(/\/.*/,"",o) } c[o]++ }
      END { for (k in c) printf "%6d  %s\n", c[k], k }' | sort -rn | head -15
    ;;
  erros)
    todos | awk "$PARSE"' st>=400 { printf "%s %s %s %s %s\n", t, ip, metodo, caminho, st }' | tail -40
    ;;
  ao-vivo)
    tail -n 0 -F "$LOG" | awk "$PARSE"'
      { printf "%s %-15s %-4s %-14s %d %s %ss\n", substr(t,12,8), ip, metodo, caminho, st, cache, tempo; fflush() }'
    ;;
  *)
    echo "uso: acessos.sh [resumo|relatorio|ativos|por-hora|dispositivos|origens|erros|ao-vivo]"; exit 2 ;;
esac
