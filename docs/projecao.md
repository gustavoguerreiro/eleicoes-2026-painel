# Como funciona a projeção do resultado final

> **Em uma frase:** a projeção estima como a apuração deve terminar usando (1) o resultado do 1º turno de cada estado ou
> município, (2) o que a apuração do 2º turno já mostrou e (3) uma correção para o fato de que os boletins de urna **não chegam
> em ordem aleatória**. É uma **estimativa própria, não oficial**. O resultado oficial é o que o TSE divulga.

**Índice:** [O que a tela mostra](#o-que-a-tela-mostra) · [A matemática](#a-matemática-passo-a-passo) ·
[Exemplo com números reais](#exemplo-com-números-reais-2º-turno-de-2022) · [Como ler a faixa](#como-ler-a-faixa-e-a-confiança) ·
[Como foi testada](#como-foi-testada) · [Limites](#limites-o-que-ela-não-garante) · [Código e dados](#código-dados-e-como-reproduzir) ·
[English summary](#english-summary)

## O que a tela mostra

No cartão do **presidente** (Brasil) e do **governador** (RN), enquanto a apuração está em andamento:

- **Projeção** de cada candidato (ordem alfabética, como no resto do painel) e a **faixa** `a – b` ao lado.
- **Faltam ~X votos válidos**: o volume que ainda deve ser apurado.
- **Ponto de virada**: "para virar, *quem está atrás* precisa de Y% do que falta". Não depende de nenhum modelo, é só aritmética.
- **Confiança** baixa, média ou alta, que depende de quanto do eleitorado já foi apurado.

A faixa **não é uma probabilidade** (não diz "90% de chance"). Ela mostra cenários, e a seção
[Como ler a faixa](#como-ler-a-faixa-e-a-confiança) explica quais.

## A matemática, passo a passo

Cada **unidade** $u$ é um estado (no presidente: 27 estados mais o exterior) ou um município (no governador do RN: os 167).
Para cada uma temos, no instante atual:

- $a_u$, $b_u$: votos já apurados dos dois finalistas (A é o candidato do PT, B o outro);
- $E_u$: eleitores aptos da unidade; $e_u$: eleitores aptos das seções já apuradas; $p_u = e_u / E_u$ (fração apurada).

### 1. Quanto falta apurar

Cada eleitor apurado gerou, em média, $\rho_u = \dfrac{a_u + b_u}{e_u}$ votos válidos nos dois finalistas. Supondo que o
eleitorado que falta vote na mesma proporção:

$$F_u = \rho_u \, (E_u - e_u)$$

Esse volume acertou o que faltava com cerca de **±1%** em qualquer ponto da apuração de 2022.

### 2. O prior: o que o 1º turno diz, antes de olhar qualquer contagem

Seja $x_u = \dfrac{a^{1T}_u}{a^{1T}_u + b^{1T}_u}$ a fração do candidato A entre A e B no **1º turno** da unidade e $o_u$ a fração
dos votos válidos que foi para os demais candidatos. O prior é

$$\pi_u = \operatorname{expit}\!\Big(\alpha + \beta \,\operatorname{logit}(x_u) + \gamma\, o_u\Big)$$

com $\operatorname{logit}(t)=\ln\frac{t}{1-t}$ e $\operatorname{expit}$ a função inversa. Usamos a escala *logit* porque nela um
deslocamento geral de opinião é uma **soma**. Parâmetros do presidente: $\beta = 0{,}975$, $\gamma = -0{,}023$. O intercepto
$\alpha$ **não importa** (próximo passo).

### 3. A maré: o quanto o 2º turno está deslocado do 1º

A contagem de cada unidade tem um desvio em relação ao seu prior:

$$r_u = \operatorname{logit}\!\Big(\tfrac{a_u}{a_u+b_u}\Big) - \operatorname{logit}(\pi_u)$$

A **maré** $\theta$ é a média desses desvios ponderada pelos votos já contados ($w_u = a_u+b_u$):

$$\theta = \frac{\sum_u w_u\, r_u}{\sum_u w_u}$$

Ela diz "quanto, em média, o país se deslocou do 1º para o 2º turno". Se o prior errar o **nível** geral (por exemplo,
porque os candidatos mudaram), a maré corrige exatamente, e isso é verificado em teste automático
(`tests/test_projecao.py`). No governador, a maré do estado é a própria média dos municípios do estado.

### 4. Como o que falta vai votar

Para o que falta em cada unidade, a escala *logit* da fração de A é

$$\operatorname{logit} q_u \;=\; \operatorname{logit}\pi_u \;+\; \theta \;+\; \kappa_u\,(r_u-\theta) \;+\; \underbrace{\psi + \psi_1\operatorname{logit}\pi_u + \psi_2\, p_u}_{\text{correção de ordem}}$$

- $\pi_u + \theta$: o prior deslocado pela maré;
- $\kappa_u = p_u$: **quanto mais a unidade já apurou, mais confiamos no desvio dela própria** $(r_u - \theta)$ em vez da média;
- **correção de ordem** $(\psi, \psi_1, \psi_2)$: os boletins de urna **não chegam em ordem aleatória**. Em 2022 as últimas seções a
  serem totalizadas (periferias, interior, Norte e Nordeste) foram, em média, mais favoráveis ao PT que as primeiras, e mais ainda onde
  o PT é forte. O $\psi$ é o efeito base, $\psi_1$ amplifica onde o lado é forte e $\psi_2$ cresce com a fração já apurada.

| Perfil | $\psi$ | $\psi_1$ | $\psi_2$ | $\sigma$ (faixa) | Origem dos valores |
|---|---|---|---|---|---|
| Presidente | 0,03 | 0,05 | 0,08 | 0,05 | noite do 2º turno de 2022, ordem real dos boletins |
| Governador (RN) | −0,04 | 0 | 0 | 0,08 | 1º turno de 2026 no RN, ordem real, entre Cadu e Allyson |

### 5. Resultado projetado

$$A = \sum_u \big(a_u + F_u\, q_u\big), \qquad B = \sum_u \big(b_u + F_u\,(1-q_u)\big), \qquad \text{projeção de A} = \frac{A}{A+B}$$

### 6. A faixa

Refaz-se a conta do passo 4 com $\psi-\sigma$ e com $\psi+\sigma$. A faixa mostrada vai do menor ao maior desses resultados,
mais um pequeno piso. A sensibilidade é simples: se o logit do que falta mudar em $\Delta$, a porcentagem final muda em
aproximadamente

$$\Delta\text{ final} \approx 0{,}25 \times (\text{fração que falta}) \times \Delta \times 100\ \text{p.p.}$$

Com 80% ainda por apurar e $\Delta = 0{,}05$, isso dá cerca de **1,0 ponto percentual**.

### 7. Ponto de virada (sem modelo)

Com $L$ votos do líder, $T$ do que está atrás e $F$ votos válidos por apurar, o que está atrás precisa de

$$x = \frac{L - T + F}{2F}$$

da parcela que falta. Se $x > 100\%$, o resultado está matematicamente fora de alcance (o painel só afirma "praticamente definido"
com uma folga de 5%, porque $F$ também é uma estimativa).

## Exemplo com números reais (2º turno de 2022)

Reproduzindo a noite pela ordem real em que os boletins chegaram, com cerca de **20% do eleitorado apurado** (17:45), o resultado
final do Lula entre os dois foi **50,90%**:

| | % do Lula | Erro |
|---|---|---|
| Placar bruto (soma do que já foi apurado) | 48,4 | −2,5 p.p. |
| Prior + maré, **sem** correção de ordem | 50,0 | −0,9 p.p. |
| Modelo completo | 50,89 | −0,01 p.p. |
| Faixa mostrada | 49,9 a 51,9 | |

O placar erra porque as seções que chegam primeiro vêm de lugares menos favoráveis ao PT. Sem a correção de ordem, o modelo ainda erra
cerca de 1 ponto, e a faixa vai de "nenhum viés de ordem" (limite de baixo) a "o dobro do de 2022" (limite de cima).

## Como ler a faixa e a confiança

- A faixa é um **conjunto de cenários** sobre o viés de ordem: do "não existe" ao "muito maior que em 2022". Ela **não foi
  calibrada como intervalo de confiança** e não deve ser lida como "X% de chance".
- Se o viés de ordem de 2026 se comportar como o de 2022 (ou como o 1º turno de 2026 no RN), o erro típico do modelo foi pequeno
  (veja abaixo). Se for muito diferente, o erro pode se aproximar da largura da faixa.
- **Confiança** = quanto do eleitorado já foi apurado: **baixa** abaixo de 25% (presidente) ou 50% (governador), **alta** acima de 60% (presidente)
  ou 85% (governador).
- A projeção **some** quando o TSE marca o candidato como eleito, e não aparece antes de 5% do eleitorado apurado.

## Como foi testada

Com a **ordem real de chegada** dos boletins de urna (dados abertos do TSE, coluna `DT_BU_RECEBIDO`). Erro, em pontos percentuais,
da % final do candidato A (RMS por faixa de apuração):

| | 15–50% | 50–85% | 85–99% |
|---|---|---|---|
| Placar bruto (2º turno 2022, Brasil) | 1,86 | 0,85 | 0,22 |
| **Modelo (2º turno 2022, Brasil)** | **0,06** | **0,02** | **0,01** |

E **fora da amostra**: 1º turno de 2026 no RN, com ordem real de 2026 e prior só do 1º turno de **2022** (nada foi ajustado ali):
placar 1,14 / 0,72 / 0,08 contra modelo **0,27 / 0,09 / 0,11** (faixas 10–30%, 30–60%, 60–97%). O sinal do viés de ordem se repetiu, mas a
intensidade mudou mais de 2×, e por isso a faixa do presidente usa $\sigma=0{,}05$.

Os parâmetros de 2022 foram ajustados **na mesma noite** em que o teste foi feito, então o primeiro número é otimista. Todos os
experimentos estão em [`modelo/`](../modelo), e o detalhamento em [`modelo/README.md`](../modelo/README.md).

## Limites: o que ela não garante

- Só há **uma noite com ordem real de chegada** para o 2º turno (2022) e uma de 1º turno (2026, só o RN testado). O 2º turno de 2026
  pode ter outro viés de ordem.
- No **governador**, o 1º turno prevê o 2º município a município bem pior que no presidente (erro de 6–7 p.p. em 2018). Se o viés de
  ordem do 2º turno for do lado contrário e grande, a projeção do RN pode ser **pior que o placar** nas faixas iniciais (testado:
  [`modelo/README.md`](../modelo/README.md)).
- Em 2022 o TSE só divulgou ao público a partir das 19h (horário de Brasília), quando já havia 83% das seções totalizadas. Se
  isso se repetir, o painel pode não mostrar as faixas iniciais; a projeção serve então para o ajuste fino dos últimos 15%.
- O Brasil usa **estados** como unidade; usar os 5.570 municípios seria mais preciso, mas exigiria baixar muito mais arquivos
  do TSE durante a noite.

## Código, dados e como reproduzir

| O quê | Onde |
|---|---|
| O modelo (≈160 linhas, só biblioteca padrão) | [`backend/projecao.py`](../backend/projecao.py) |
| Montagem das unidades a partir dos arquivos do TSE | [`backend/painel_server.py`](../backend/painel_server.py) (`projecao_brasil`, `projecao_municipios`) |
| Backtest, experimentos e resultados | [`modelo/`](../modelo) e [`modelo/README.md`](../modelo/README.md) |
| Testes (inclui a noite de 2022) | [`tests/test_projecao.py`](../tests/test_projecao.py) |
| Reprodução da noite real de 2022 no painel | `python backend/painel_server.py --web --replay-2022` |

Os dados vêm de [dadosabertos.tse.jus.br](https://dadosabertos.tse.jus.br): Boletim de Urna de 2022 e de 2026 (com a hora de chegada de
cada seção), votação por seção de 2022 e de 2018. O que está nos testes é reproduzível com os scripts `modelo/dados_*.py`.

## English summary

The dashboard shows an **estimate (not official)** of how the count will end. For each unit (state for the presidential race,
municipality for the governor) it (1) predicts the runoff share from first-round results, (2) measures the **tide**, the average
logit shift between what the count already shows and that prior, (3) projects the votes still to come as
`prior + tide + own deviation weighted by the fraction counted + ballot-arrival-order correction`, and (4) adds everything up.
The **order correction** exists because ballots do not arrive in random order: in 2022 the last sections were more favourable to
the left. It was backtested minute by minute on the real arrival order of the 2022 runoff (error about 0.06 pp versus 1.9 pp for the raw
count at 15–50% counted) and out of sample on the 2026 first round in Rio Grande do Norte. The band is a set of *scenarios* about the
order effect, **not a probability**. Code: `backend/projecao.py`; experiments: `modelo/`.
