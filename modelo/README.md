# Modelo de projeção do resultado final

Este diretório tem os dados, os experimentos e o backtest que calibraram `backend/projecao.py` (o modelo que roda no painel).
A projeção é uma **estimativa própria, não oficial**. A faixa mostrada na tela é um conjunto de **cenários** sobre o viés de
ordem da apuração, e **não** uma probabilidade.

## Por que existe

O placar bruto engana no começo da apuração, porque as seções chegam em uma ordem enviesada. No 2º turno de 2022 o Lula
terminou com 50,90%, mas o placar bruto dizia 47,8% às 17:30 (8,6% apurado), 49,8% às 18:30 (55%) e 50,4% às 19:00 (85%).
O modelo corrige isso usando (1) o 1º turno de cada unidade e (2) o que o 2º turno já mostrou.

## O modelo (`backend/projecao.py`)

Para cada unidade *u* (estado no Brasil; município no governador), com `a`, `b` = votos já apurados dos dois finalistas:

1. **Quanto falta.** `faltam_u = (aptos_total − aptos_apurados) × (a+b)/aptos_apurados`. Em 2022 isso acertou o volume
   restante com **±1%** em qualquer ponto da apuração (medido na exploração inicial; ver o fim deste arquivo).
2. **Prior do 1º turno.** `π_u = invlogit(α + β·logit(a1/(a1+b1)) + γ·outros1)`, só com o 1º turno. O intercepto α não importa.
3. **Maré.** `θ` = desvio médio (em logit, ponderado pelos votos) entre o que cada unidade já mostrou e o seu prior, encolhido do
   estado para o país. Um erro de nível no prior é absorvido por completo pela maré (testado em `tests/test_projecao.py`).
4. **O que falta vota assim:** `logit q_u = logit π_u + θ + κ·(r_u − θ) + ψ + ψ₁·logit π_u + ψ₂·p_u`, com `κ = p_u` (fração
   apurada da unidade) e `r_u` o desvio da própria unidade. `ψ`, `ψ₁`, `ψ₂` corrigem o **viés de ordem**: as últimas seções a chegar
   são, em média, mais favoráveis a um lado (em 2022, ao PT) do que as primeiras, e mais ainda onde o lado é forte.
5. **Faixa:** a mesma projeção com `ψ ± σ` (cenários de transferência do viés de ordem), mais um piso pequeno.
6. **Ponto de virada** (sem nenhuma hipótese): do que falta, quanto o candidato que está atrás precisa levar.

## Dados (todos públicos, dos dados abertos do TSE)

| Dado | Uso | Tamanho |
|---|---|---|
| Boletim de Urna do 2º turno de 2022, por seção, com `DT_BU_RECEBIDO` (a hora em que o boletim chegou) | **ordem real da apuração**: o backtest minuto a minuto | 66 MB |
| Presidente por seção de 2022 (1º e 2º turno) | 1º turno por município de 2022 (prior) | 271 MB |
| Histórico oficial da totalização de 2022 (1º e 2º turno) | conferência da série nacional | 2 MB |
| Governador do RN em 2018 por seção (1º e 2º turno) | um par real 1º→2º turno de governador do RN | 21 MB |
| Boletim de Urna de 2026, 1º turno do RN, por seção | ordem real de apuração do RN em 2026 e viés de ordem entre Cadu e Allyson | 54 MB |

Scripts: `dados_2022.py`, `dados_2022_municipios.py`, `dados_rn.py` (baixam e resumem para `modelo/cache/`, ignorado pelo git).
As contas batem com os totais oficiais (Lula 60.345.999 × Bolsonaro 58.206.354 no 2º turno de 2022).

## Resultados do backtest

Erro da % final do candidato A (PT) entre os dois finalistas, em pontos percentuais (RMS dos instantes da faixa).

### Brasil: 2º turno de 2022 com a ordem real dos boletins (`backtest.py` e `tests/test_projecao.py`)

| Apurado (seções) | Placar bruto | Reponderação por estado | Modelo entregue (estados) | Modelo com municípios |
|---|---|---|---|---|
| 15–50% | 1,86 | 0,85 | **0,06** | 0,08 |
| 50–85% | 0,85 | 0,59 | **0,02** | 0,05 |
| 85–99% | 0,22 | 0,13 | **0,01** | 0,00 |

Pontos a saber:
- `ψ`, `ψ₁`, `ψ₂` foram ajustados **na mesma noite** que o teste (3 números para ~70 instantes, e o resultado é estável numa grade
  em volta). Na eleição de 2026 eles podem ser diferentes: por isso a faixa é um cenário `ψ ± σ`, e o teste automático
  (`tests/test_projecao.py::NoiteDe2022`) exige só que o modelo seja ≥3× melhor que o placar e que a faixa contenha o resultado final.
- O prior usa coeficientes de outros estados (leave-one-state-out); a inclinação do prior pode errar 40% sem estragar o resultado (`backtest.py`).
- O viés de ordem **varia por estado**: de −0,01 (RJ, AC) a +0,12 (MA, PI, CE) em logit (exploração inicial); o modelo captura a parte
  explicada pela força do lado (`ψ₁`) e deixa o resto na faixa.

### Teste fora da amostra: 1º turno de 2026 no RN (`exp14.py`)

Alvo: % do Lula entre Lula+Flávio no RN no 1º turno de 2026, com a **ordem real de chegada de 2026** e como prior só o 1º turno de
**2022** (quatro anos antes), nos 167 municípios. Nada foi ajustado nesses dados. Erro RMS em p.p. por faixa de apuração:

| Modelo | 10–30% | 30–60% | 60–97% |
|---|---|---|---|
| Placar bruto | 1,14 | 0,72 | 0,08 |
| Reponderado por município, sem prior | 2,97 | 1,69 | 0,37 |
| Prior de 2022, sem correção de ordem | 1,56 | 1,05 | 0,30 |
| **Parâmetros de 2022 (presidente: ψ .03, ψ₁ .05, ψ₂ .08)** | **0,27** | **0,09** | 0,11 |
| ψ = 0,035 (o ótimo de 2022 por município) | 0,92 | 0,61 | 0,17 |

O que isso mostra: o sinal do viés de ordem de 2022 **se repete em 2026** (a melhor correção por município no RN foi +0,08, contra
+0,035 em 2022: mesmo sinal, outra intensidade), e os parâmetros de 2022 reduzem bastante o erro com 10–60% apurado. Com mais de 60%
apurado o placar do RN já erra pouco (0,08) e o modelo não melhora (0,11). A intensidade mudou mais de 2×, e por isso a faixa do
perfil `presidente` usa `σ = 0,05`. Falta testar o país inteiro com a ordem de 2026 (só RN foi testado; os demais estados são
~4,8 GB de Boletim de Urna de 2026, dos quais SP tem 1,3 GB).

### RN, governador: o que o painel mostra de verdade

O prior do 1º turno prevê **mal** o 2º turno de governador município a município (erro de 6–7 p.p. em 2018 contra 0,8 p.p. do
presidente nacional em 2022, exploração inicial). Então a projeção do RN depende mais da contagem, e o viés de ordem foi medido nos dados
de 2026:

| Medida do viés de ordem dentro do município (logit; + = o que falta é mais do candidato A) | Valor |
|---|---|
| 2022, 2º turno, Brasil (Lula x Bolsonaro) | +0,075 |
| 2022, 2º turno, só RN | +0,011 |
| **2026, 1º turno, RN, governador (Cadu PT x Allyson)** | **−0,056** |
| 2026, 1º turno, RN, presidente (Lula x Flávio) | +0,094 |

O sinal **muda com a corrida**, então não se herda o de 2022: o perfil `governador` usa `ψ = −0,04` e `σ = 0,08`. Teste com
um par real de governador do RN (2018) e a ordem real de chegada de 2026 (`exp13.py`):

| Viés de ordem de verdade | Placar 10–30% / 30–60% / 60–97% | Modelo | Faixa contém o resultado |
|---|---|---|---|
| −0,056 (o medido em 2026) | 2,9 / 2,0 / 0,7 | **0,7 / 0,4 / 0,1** | 100% |
| 0,000 | 2,2 / 1,5 / 0,5 | 1,5 / 0,9 / 0,3 | 94% |
| +0,050 (contra a evidência) | 1,5 / 1,1 / 0,3 | 2,2 / 1,4 / 0,6 (**pior que o placar**) | 4% |
| −0,120 | 3,8 / 2,6 / 1,0 | 0,2 / 0,3 / 0,2 | 100% |

Leitura honesta: a projeção do RN é boa **se** o viés de ordem do 2º turno se parecer com o do 1º turno de 2026; se for do lado
contrário e grande, ela pode ser pior que o placar nas primeiras faixas. Por isso o painel só marca "confiança alta" no RN com
85% do eleitorado apurado, e a faixa é larga (cerca de 3 p.p. com 10–30% apurado).

## Limites

- Só uma noite com ordem real de chegada para o 2º turno (2022) e a de 1º turno de 2026 (só RN testado). O 2º turno de 2026 pode
  ter um viés de ordem diferente; o Boletim de Urna de 2026 será publicado depois, e aí dá para refazer o backtest com a noite real.
- As séries históricas de 2014 e 2018 não têm a hora de chegada dos boletins (só 2022 e 2026 têm `DT_BU_RECEBIDO`).
- O 2º turno de 2022 só publicou ao público a partir das 19h (horário de Brasília), quando já havia 83% das seções totalizadas
  (`Historico_Totalizacao_Presidente_BR_2T_2022`). Se o TSE repetir isso, a janela em que a projeção faz mais diferença (15–85%) pode
  nem aparecer na tela; o que sobra é o ajuste fino dos últimos 15% (erro do placar 0,5 p.p. às 19h, do modelo ≈0,02).
- Estado como unidade (Brasil) mede pior o viés de ordem **dentro** do estado que o município como unidade. Usar os 5.570
  municípios melhora, mas exige baixar muito mais arquivos do TSE durante a noite; não está ligado.

## Reproduzir

```bash
python modelo/dados_2022.py              # 66 MB
python modelo/dados_2022_municipios.py   # 271 MB
python modelo/dados_rn.py                # 75 MB
python modelo/backtest.py                # tabela principal
python modelo/exp13.py                   # RN governador (par real de 2018 + ordem real de 2026)
python modelo/exp14.py                   # teste fora da amostra: RN, 1º turno de 2026
python -m unittest tests.test_projecao   # regressão (a noite de 2022 só roda se os dados estiverem baixados)
```

## Scripts que estão aqui e o que ficou de fora

| Script | O que faz |
|---|---|
| `dados_2022.py`, `dados_2022_municipios.py`, `dados_rn.py` | baixam e resumem os dados abertos do TSE para `modelo/cache/` |
| `replay.py`, `nucleo.py` | reproduzem a apuração de 2022 minuto a minuto; priors do 1º turno e avaliação de parâmetros |
| `backtest.py` | tabela principal do Brasil (2º turno de 2022, ordem real) e testes de robustez |
| `exp13.py`, `rn_2018.py` | RN governador: par real de 2018 com a ordem real de chegada de 2026 |
| `exp14.py` | teste fora da amostra: RN, 1º turno de 2026, prior só do 1º turno de 2022 |

Alguns números deste arquivo vieram de **scripts de exploração que não estão no repositório** (comparação do placar com a
reponderação por estado, o erro do volume que falta, o viés de ordem por estado, a escolha dos parâmetros ψ₁ e ψ₂ numa grade, o erro do
prior de governador em 2018 e a medida do viés de ordem dentro do município). Eles usaram as mesmas funções de `nucleo.py` e `replay.py` sobre
os mesmos dados; o teste `tests/test_projecao.py::NoiteDe2022` e os scripts acima reproduzem o essencial: a projeção entregue contra
a ordem real de 2022 e os testes do RN.
