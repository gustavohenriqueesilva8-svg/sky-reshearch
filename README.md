# Sky Reshearch

## Planet X and SPHEREx — Blink Comparator & Transient Hunter

Projeto submetido ao NASA Space Apps Challenge: Planet X and SPHEREx.

Aplicação web para explorar imagens astronômicas públicas do IRSA, além de levantamentos DSS e infravermelhos de apoio.

> A visualização de canais e o espectro Quick-Look usam o All-Sky Cube do DR1. O Blink, a subtração e a combinação temporal SPHEREx consultam imagens espectrais MEF das coleções DR1 e QR3. O cubo all-sky combina os Surveys 1 e 2 e não é usado como se contivesse duas épocas.

## Recursos

- Blink e subtração DSS1/DSS2 como comparação óptica de apoio.
- Soma exploratória das épocas DSS1/DSS2 alinhadas como alternativa óptica ao stack SPHEREx quando o IRSA estiver indisponível.
- Blink temporal SPHEREx com cutouts das coleções `spherex_dr1` e `spherex_qr3`, selecionados por detector e comprimento de onda no alvo.
- Subtração SPHEREx com reprojeção bilinear WCS e soma temporal das épocas alinhadas.
- Consulta SIA2 via PyVO ao cubo SPHEREx DR1: canal individual ou média dos canais disponíveis de um dos seis detectores. O backend lê planos FITS remotos por HTTP Range para limitar os dados transferidos.
- Se a consulta SIA2 falhar, o cubo DR1 é lido pelo tile HEALPix correspondente no espelho público AWS `nasa-irsa-spherex`, usando acesso anônimo e HTTP Range; a origem utilizada é exibida nos metadados.
- Metadados do cubo incluem projeção, pixels cobertos, contagem de `FLAGS` e `NHITS`.
- Espectro Quick-Look real extraído do cubo DR1 pela mediana dos pixels cobertos em uma abertura 3×3, usando os comprimentos de onda da extensão `SPECTRAL_CHANNELS`. Os canais sem dados 51 e 52 são omitidos.
- Comparador WISE/2MASS/IRAS/IRIS/AKARI via SkyView, com avisos de falta de cobertura e falhas de serviço separados.
- Filtro espacial opcional de mediana 3×3.
- Gráfico espectral manual via `POST /api/spectrum`, com incerteza opcional.
- Tour guiado com cinco alvos: Estrela de Barnard, WISE 0855, Epsilon Indi B, RW Aurigae e R Draconis.
- Coordenadas decimais ou sexagesimais e links diretos com modo, coordenadas, canal/detector e FOV.
- Não há quadros astronômicos sintéticos nos fluxos de falha: a interface tenta dados observacionais DSS/SkyView ou WISE/2MASS/IRAS/AKARI e informa quando nenhum recurso tem cobertura.

## Arquitetura da Interface (UI/UX)

- **Boas-vindas centralizadas:** a página inicial abre por padrão com os alvos em destaque; a orientação de uso fica recolhida e aparece em cascata quando solicitada.
- **Navegação em quatro páginas:** Boas-vindas, Mapa Estelar, Laboratório de Imagens e Espectro Quick-Look são acessados pela navegação superior e sincronizados com `?page=home|starmap|workbench|spectrum`.
- **Modos com terminologia clara:** “Modo de Observação” mantém o fluxo visual essencial; “Modo de Pesquisa” revela parâmetros, metadados e diagnósticos.
- **Mapa Estelar & Catálogo:** carta equatorial com RA invertida no eixo horizontal, declinação no eixo vertical, zoom, pan, retícula de FOV e clique em coordenadas livres. Uma visualização 3D projeta RA/Dec e distâncias aproximadas em escala radial logarítmica a partir da Terra; objetos sem distância cadastrada ficam fora da projeção, sem posição inferida.
- **Blink animado entre épocas:** gera um crossfade ou GIF entre imagens alinhadas de SPHEREx ou DSS e oferece exportação WebM pelo navegador. A animação é uma comparação visual qualitativa; não calcula movimento próprio automaticamente.
- **Presets sem execução:** escolher um objeto apenas preenche RA, Dec, FOV, filtro, survey e parâmetros SPHEREx. A interface destaca a ação recomendada, mas só consulta os serviços depois do clique explícito em uma ação.
- **Ações categorizadas:** cubo espectral DR1, análises temporais SPHEREx e levantamentos multi-missão DSS/SkyView ficam em grupos distintos.
- **Laboratório Espectral dedicado:** permite extrair dados do cubo DR1 ou plotar CSV manual com incerteza, fora da bancada de imagens.
- **Ajuste seguro de FOV temporal:** os recortes temporais SPHEREx recebem no máximo 30 arcmin de raio; FOVs maiores são limitados na interface com aviso ao usuário.
- **Ações discretas:** botões em estilo fantasma, com cores aplicadas aos contornos e ao texto.

As faixas dos detectores no painel são guias aproximados de comprimento de onda. D1–D3 cobrem 0,75–2,41 µm; D4 cobre 2,42–3,82 µm; D5 cobre 3,83–4,41 µm; e D6 cobre 4,42–5,00 µm. Características de H₂O, CO₂ ou CO dependem da fonte, da posição no detector e da qualidade dos dados; os marcadores não afirmam uma detecção. Consulte os [produtos de dados oficiais SPHEREx/IRSA](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/) e a [página do desafio Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/).

## Casos de Estudo Inclusos (Guided Tour)

- **Estrela de Barnard:** subtração temporal SPHEREx para demonstrar o alinhamento WCS.
- **WISE 0855:** banda integrada do detector D6 do cubo DR1 (4,42–5,00 µm), com comparação WISE W1/W2 via SkyView.
- **Epsilon Indi B:** espectro Quick-Look extraído do cubo DR1; os pontos reais também preenchem o editor tabular para edição e novo gráfico manual.
- **RW Aurigae:** Blink temporal SPHEREx com filtro de mediana.
- **R Draconis:** soma temporal SPHEREx no detector D6 para uma estrela variável Mira.

O tour também exibe imagens DSS1/DSS2 e a subtração óptica como referência para Barnard, além da comparação multi-missão SPHEREx/WISE para WISE 0855.

As macros consultam dados públicos no IRSA e dependem de rede, cobertura e disponibilidade dos produtos. O espectro Quick-Look é uma extração exploratória de brilho superficial, não fotometria PSF calibrada.

## Dados SPHEREx

O All-Sky Cube DR1 fornece 102 canais combinados dos Surveys 1 e 2. Para comparação temporal, a aplicação consulta MEFs das coleções `spherex_dr1` e `spherex_qr3`, que representam dados de surveys distintos. Os pares são selecionados no mesmo detector, ordenados por data e comparados pela compatibilidade do comprimento de onda calculado na posição do alvo. O IRSA Cutout Service reduz cada MEF antes do download.

O backend preserva parâmetros existentes ao acrescentar ou substituir `center` e `size` no URL do cutout e aplica um `Cutout2D` local como proteção adicional. O recorte mantém o WCS atualizado e aplica a mesma janela espacial à imagem, ao fundo zodiacal e às flags.

Consulte a [visão geral DR1](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html), o [guia oficial de acesso SIA2 e dos tiles All-Sky Cube](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/), o [acesso em nuvem oficial do IRSA](https://irsa.ipac.caltech.edu/cloud_access/) e o [tutorial de HiPS e cubes SPHEREx](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/).

## Requisitos e execução

Python 3.10+ e acesso à internet para consultar IRSA e SkyView.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

A API fica em `http://127.0.0.1:8002`; a documentação interativa fica em `http://127.0.0.1:8002/docs`. Abra `index.html` no navegador. Para publicar o servidor, restrinja CORS em `app.py` às origens confiáveis.

## Rotas

| Rota | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /api/blink_with_metadata` | `ra`, `dec`, `epoch` (`1`/`2`), `fov` em arcmin, `filter` opcional | JSON com metadados e PNG em data URL (DSS) |
| `GET /api/subtract` | `ra`, `dec`, `fov` em arcmin, `filter` opcional | Fluxo PNG da diferença normalizada DSS2 − DSS1 |
| `GET /api/add` | `ra`, `dec`, `fov` em arcmin, `filter` opcional | Fluxo PNG da soma exploratória normalizada DSS1 + DSS2 |
| `GET /api/catalog` | — | JSON com os cinco alvos do desafio, objetos clássicos, coordenadas, distância aproximada, FOV e parâmetros recomendados |
| `GET /api/motion_video` | `ra`, `dec`, `source=auto|spherex|optical`, `detector`, `fov`, `filter` | JSON com imagens PNG alinhadas, GIF em data URL e metadados; modo `auto` usa DSS se o serviço SPHEREx falhar ou não tiver par temporal |
| `GET /api/infrared` | `ra`, `dec`, `fov` em graus, `survey` ou `band`, `filter` opcional | Fluxo PNG infravermelho |
| `GET /api/spherex/band` | `ra`, `dec`, `band`, `mode=channel|detector`, `fov` em arcmin, `filter` opcional | JSON com PNG base64, metadados WCS, qualidade (`FLAGS`, `NHITS`) e origem SIA2 ou espelho AWS |
| `GET /api/spherex/spectrum` | `ra`, `dec` | JSON com espectro real do cubo DR1, qualidade e PNG base64; consulta o tile público AWS se SIA2 falhar |
| `GET /api/spherex/blink` | `ra`, `dec`, `detector` (1–6), `fov` em arcmin, `filter` opcional | JSON com duas imagens SPHEREx alinhadas, metadados e PNGs base64 |
| `GET /api/spherex/subtract` | `ra`, `dec`, `detector` (1–6), `fov` em arcmin, `filter` opcional | JSON com imagem PNG base64 e metadados das duas épocas |
| `GET /api/spherex/add` | `ra`, `dec`, `detector` (1–6), `fov` em arcmin, `filter` opcional | JSON com soma PNG base64 e metadados das duas épocas |
| `POST /api/spectrum` | JSON com linhas CSV `comprimento_de_onda,fluxo[,incerteza]` ou arrays `wavelength`/`flux` | Fluxo PNG do gráfico espectral manual |

Em `/api/spherex/band`, `mode=channel` espera `band` de 1 a 102. `mode=detector` espera `band` de 1 a 6 e calcula a média dos canais desse detector, ignorando planos sem dados. A rota `/api/spherex/spectrum` retorna fluxo em MJy/sr como mediana da abertura 3×3; não executa ajuste PSF. `/api/spherex/add` soma as duas épocas alinhadas, sem ponderação por variância. O parâmetro `fov` das rotas temporais e do cubo é o raio em minutos de arco.

O deep link para o cubo aceita, por exemplo, `?ra=180&dec=2.5&fov=5&mode=spherex&band=88`. O modo temporal usa `mode=spherex-blink&detector=5`.

As consultas SkyView enviam o FOV como `radius` e solicitam uma grade de 500 pixels. A [API SkyView do Astroquery](https://astroquery.readthedocs.io/en/stable/api/astroquery.skyview.SkyViewClass.html) documenta que `radius` determina a área angular e prevalece sobre `width`/`height`; portanto, esses dois parâmetros não são enviados junto com `radius`. As respostas da API incluem cabeçalhos `Cache-Control: no-store` para evitar a reutilização de imagens antigas pelo navegador.

As páginas também podem ser compartilhadas com `?page=home`, `?page=starmap`, `?page=workbench` ou `?page=spectrum`. Um deep link de processamento pode combinar a página, coordenadas e ação, por exemplo: `?page=workbench&ra=00h42m44.3s&dec=%2B41d16m09s&fov=60&mode=spherex&view=detector&band=1`. A abertura de uma URL com `mode` explícito executa a ação solicitada; apenas carregar um preset na interface não dispara consultas.

## Limitações

O cubo All-Sky usa projeção HEALPix (HPX) e agrega imagens, portanto não preserva épocas. A média de detector aplica `nanmean` aos canais do cubo; não empilha exposições brutas. A extração espectral é uma mediana exploratória em MJy/sr, sem incerteza formal nem fotometria PSF. O Blink temporal só retorna par quando encontra cobertura e datas adequadas; diferenças de calibração, PSF, fundo e qualidade ainda exigem avaliação científica. A soma das épocas não é ponderada por variância. O filtro de mediana pode atenuar fontes compactas e deve ser tratado como opção visual. O acesso HTTP remoto do fsspec depende de `aiohttp` e `requests`; o timeout de leitura Astropy é definido como 120 segundos. As consultas DSS e infravermelhas continuam sujeitas à cobertura dos respectivos surveys no SkyView.

## Resiliência e fontes alternativas

Em consultas ao All-Sky Cube DR1, o backend tenta primeiro o índice SIA2 do IRSA e depois busca o tile FITS do espelho público AWS `nasa-irsa-spherex`, calculando o índice HEALPix order 5 pela coordenada. O acesso AWS é anônimo e usa leitura remota por intervalos; não baixa o cubo inteiro para a máquina. O caminho dos tiles e os detalhes do produto seguem o [guia de acesso SPHEREx/IRSA](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/) e o [tutorial oficial HiPS Cube](https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube/).

Se as observações temporais SPHEREx não estiverem acessíveis, o comparador consulta imagens reais DSS1/DSS2 via SkyView. Se o cubo ou espectro SPHEREx não puder ser lido, a interface pode mostrar uma imagem real de WISE, 2MASS, IRAS ou AKARI quando houver cobertura; ela identifica explicitamente a origem e não a chama de imagem ou espectro SPHEREx. Se nenhum levantamento retornar dados, a interface mostra uma mensagem de indisponibilidade. Não são gerados campos estelares, metadados ou espectros sintéticos como fallback.

Para reduzir a espera na troca de fonte, as consultas ao cubo/banda SPHEREx e aos surveys infravermelhos alternativos são iniciadas em paralelo. Os surveys alternativos têm limite de 12 segundos por consulta e, quando um deles retorna primeiro, a interface exibe a imagem real e identifica a sua origem; blink e combinações temporais também disputam a resposta SPHEREx com DSS1/DSS2 em paralelo. A contingência não espera o timeout longo de uma única fonte antes de iniciar as demais.

Esses caminhos seguem as recomendações publicadas na [discussão #2257](https://github.com/nasa/spaceapps/discussions/2257) (espelho S3 público, HiPS/Aladin Lite ou dados observacionais previamente armazenados) e na [discussão #2249](https://github.com/nasa/spaceapps/discussions/2249), que permite usar recursos listados para o desafio e orienta incluir pelo menos um recurso NASA para elegibilidade ao Global Judging. Consulte também a [página oficial de recursos Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=resources).

A soma DSS normaliza cada época antes de combiná-las e não representa fotometria calibrada.

## Citação dos dados SPHEREx

Ao publicar resultados produzidos com dados do IRSA, cite os identificadores correspondentes: **10.26131/IRSA678** (imagens espectrais DR1), **10.26131/IRSA679** (All-Sky Cube DR1) e **10.26131/IRSA662** (imagens QR3). O texto institucional solicitado pelo IRSA é:

> This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration.

Referências: [SPHEREx DR1](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html) e [SPHEREx Quick Releases](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html).

## Licença

O código deste repositório está sob a licença MIT (consulte [LICENSE](LICENSE)). Essa licença cobre o código do projeto; dados SPHEREx e serviços externos seguem seus próprios termos e requisitos de citação.
