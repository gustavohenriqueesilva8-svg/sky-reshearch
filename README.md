# Sky Researcher — encontre um astro e entenda onde ele está

Encontre um objeto pelo nome ou identificador e descubra em que direção ele aparece no céu e a que distância aproximada está da Terra. O **GPS da Via Láctea** é a visão de uma ferramenta aberta de orientação astronômica. O comparador desenvolvido para o NASA Space Apps Challenge permite investigar observações do campo escolhido. [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/)

## Experimente com a Estrela de Barnard

1. Abra **Mapa Estelar**, digite **Barnard** e selecione **Estrela de Barnard** no catálogo. Também é possível pesquisar identificadores já cadastrados no nome, como **M42**.
2. Na **Carta 2D**, veja a direção da estrela a partir da Terra. Passe para a **Vista 3D** para ver a mesma estrela selecionada e sua distância aproximada de 5,96 anos-luz. Os anéis da escala logarítmica representam 10, 100 e 1.000 anos-luz.
3. Clique em **Observar este astro** para abrir a ação recomendada do alvo. No Modo de Observação, Barnard abre o exemplo com dois recortes ópticos incluídos, de 1950 e 1991. Alterne as datas para comparar sua posição aparente com a das vizinhas. Use **Consultar SPHEREx** para tentar uma comparação infravermelha ao vivo. [Proveniência dos recortes de Barnard](assets/README.md)

## O que funciona hoje

A busca, o catálogo, a Carta 2D e a Vista 3D funcionam com os dados locais. Os filtros do catálogo ajudam a encontrar alvos da Via Láctea e listam as galáxias externas em um grupo separado. A carta mostra a direção dos objetos dos dois grupos. A vista 3D representa uma amostra dos objetos da Via Láctea cadastrados em relação à Terra. Para **R Draconis**, a carta indica a direção e a vista 3D explica que falta uma distância para posicioná-la.

Ações do catálogo como pesquisar, selecionar ou trocar de vista são locais. O botão de observação encaminha o alvo para o comparador ou o espectro, conforme a ação disponível. As consultas aos arquivos remotos dependem da cobertura e da disponibilidade da fonte. Já a página **Sistema Solar** calcula posições de Marte e da Terra por data e hora por meio do servidor local.

## Como executar

Para usar o catálogo estelar e a atividade de Barnard com os dados locais, abra `index.html` no navegador mantendo a pasta `assets/` no mesmo diretório. Para habilitar o Sistema Solar, as consultas aos arquivos e o laboratório, use Python 3.10+:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Abra [http://127.0.0.1:8002](http://127.0.0.1:8002). A [documentação da API](http://127.0.0.1:8002/docs) é servida pelo mesmo processo. Para abrir o [exemplo de Barnard diretamente](http://127.0.0.1:8002/?page=workbench&example=barnard), use `?page=workbench&example=barnard`. As consultas ao vivo exigem conexão com o IRSA ou o SkyView, conforme a fonte escolhida.

### Localize Marte no Sistema Solar

Com o servidor local em execução, abra [Sistema Solar](http://127.0.0.1:8002/?page=solar-system) ou clique em **Localizar Marte** na página inicial ou no **Mapa Estelar**. A vista abre no instante atual. Edite **Data e hora (UTC)** e clique em **Atualizar posição** para ver como os marcadores e as distâncias Marte–Terra e Marte–Sol mudam. Alterne entre **Vista inclinada**, **Plano XY** e **Plano XZ** ou abra a tabela de coordenadas. Os círculos são guias de escala, com intervalos de 0,5 unidade astronômica.

A página consulta `GET /api/ephemerides/mars?instant=2025-01-16T12:00:00Z`. O cálculo usa a efeméride embutida no servidor e funciona sem conexão externa. As posições são geométricas em relação ao Sol.

#### Geometria de Marte em Python

`mars_geometry(instant)` aceita `YYYY-MM-DDTHH:MM:SS` com uma fração opcional de até seis dígitos e fuso explícito (`Z` ou `±HH:MM`). A faixa UTC vai de `2000-01-01T00:00:00Z` (inclusive) a `2050-01-01T00:00:00Z` (exclusive). Entradas inválidas, fora da faixa ou com segundo `60` geram `ValueError`.

O dicionário retorna `instant_utc` normalizado para UTC, `length_unit` (`au`), `frame` (origem no centro do Sol) e `model` (`astropy:builtin`). `positions` contém os vetores geométricos `x, y, z` de `sun`, `earth` e `mars`. `distances` contém `mars_earth` e `mars_sun`, obtidas das diferenças entre os vetores 3D. As componentes e as distâncias são valores `float`.

O metadado `axes: "ICRS"` identifica os eixos nominais de `astropy:builtin`. O Astropy combina diretamente os vetores do Sol e da Terra derivados de `erfa.epv00`, com orientação BCRS, com o vetor heliocêntrico de Marte de `erfa.plan94`, expresso no equador e no equinócio médios de J2000.0. A combinação produz um alinhamento aproximado ao ICRS e usa a convenção nativa dos vetores sem aplicar rotação. [Efemérides do Astropy](https://docs.astropy.org/en/stable/coordinates/solarsystem.html)

Os valores são estimativas geométricas para o mesmo instante em TDB, sem correção de tempo de luz. A conversão UTC → TDB usa os segundos intercalares disponíveis localmente, inclusive na primeira chamada. O aviso `dubious year` do ERFA é esperado para datas futuras além do período coberto pelos dados de segundos intercalares e é suprimido durante a conversão.

```bash
python -c 'from ephemerides import mars_geometry; print(mars_geometry("2025-01-16T12:00:00Z"))'
python -m unittest tests_test_ephemerides.py
```

## Comparador e processamento de dados

- **Comparação guiada:** escolha uma data, alterne manualmente ou reproduza as imagens. A origem e as datas disponíveis aparecem em ambos os modos. A mistura dos quadros é uma ajuda visual; cada época tem só um quadro observado.
- **Modo de Pesquisa:** altera coordenadas RA/Dec, raio do campo, detectores, canais, filtro e cadência. Expõe metadados FITS e WCS, seleção de fonte, subtração e soma exploratória. O visor permite salvar uma imagem ou exportar a alternância em WebM quando o navegador oferece suporte.
- **Laboratório espectral:** inspeciona canais individuais ou a média por detector do SPHEREx DR1. O Quick-Look extrai um espectro de uma abertura de 3 × 3 pixels e permite exportar ou editar os dados em CSV. WISE, 2MASS, IRAS, IRIS e AKARI via SkyView oferecem contexto de outras faixas, não épocas SPHEREx.

### Pipeline de dados

O frontend usa HTML, CSS e JavaScript. O backend usa FastAPI, Astropy, PyVO, Astroquery, NumPy e SciPy para consultar, ler e processar os dados; as dependências estão em [requirements.txt](requirements.txt).

1. **Localizar o campo.** A posição do catálogo ou digitada pela pessoa é convertida para coordenadas celestes. O raio define a região a consultar.
2. **Encontrar duas observações.** Para o SPHEREx, o IRSA é consultado por SIA2 nas coleções de imagens espectrais DR1 e QR3. O seletor procura imagens do mesmo detector, separadas por pelo menos 30 dias, com cobertura e comprimentos de onda comparáveis no alvo. Quando o par selecionado ultrapassa a tolerância espectral nominal, o visor avisa. A fonte de cada observação vem do registro; a data do arquivo FITS nunca é usada como data do céu observado.
3. **Recortar e alinhar.** Os FITS são recortados no campo; o processamento SPHEREx remove o fundo zodiacal e mascara flags de pixels inválidos quando essas extensões estão disponíveis. A primeira imagem é reprojetada para a grade celeste (WCS) da segunda por interpolação bilinear. A comparação temporal mostra a área válida comum.
4. **Exibir com contexto.** A comparação SPHEREx usa uma escala visual comum. A comparação óptica ao vivo ajusta o contraste de cada época separadamente. O modo automático aceita o primeiro par válido do IRSA ou do DSS/SkyView e identifica o levantamento utilizado. A consulta explícita SPHEREx não troca de missão silenciosamente. O exemplo de Barnard usa dois FITS ópticos, alinhados e preparados antecipadamente; a [proveniência e a reprodução dos recortes](assets/README.md) estão documentadas.
5. **Separar tempo de espectro.** O All-Sky Cube DR1 agrega os Surveys 1 e 2 e fornece 102 canais, excluindo os canais vazios 51 e 52 das extrações. O backend consulta o índice IRSA e o espelho público AWS, lendo os planos FITS necessários por intervalos HTTP. O cubo serve à visualização de bandas e ao espectro, não como fonte de duas épocas.

As principais rotas são `/api/spherex/blink` (par SPHEREx), `/api/motion_video` (par temporal e GIF opcional), `/api/spherex/subtract` e `/api/spherex/add` (diferença e soma), `/api/spherex/band` (cubo), `/api/spherex/spectrum` (extração), `/api/infrared` (SkyView) e `/api/catalog` (alvos). As rotas de comparação usam raio em minutos de arco; `/api/infrared` usa graus. Execute os testes com `python -m unittest tests_test_api.py`.

## Limitações

- Uma diferença visual ajuda a escolher onde investigar. Resolução, escala de contraste, comprimentos de onda, fundo, cobertura e alinhamento podem criar diferenças sem mudança no objeto. O aplicativo não mede movimento próprio automaticamente, não mede períodos com duas imagens e não confirma candidatos a Planet X.
- A cobertura, a disponibilidade e as datas variam por campo. O SPHEREx temporal limita o raio a 30′; um par utilizável pode não existir no detector escolhido. Uma data ausente é apresentada como não informada. Consultas malsucedidas não geram imagens nem espectros substitutos sintéticos.
- O Quick-Look é uma estimativa exploratória de brilho superficial em MJy/sr, sem fotometria PSF nem incerteza formal. A soma temporal não é ponderada pela variância; a subtração trabalha com quadros normalizados. O filtro de mediana pode atenuar fontes compactas.

## Roadmap do GPS da Via Láctea

1. **Navegação por coordenadas e datas.** Adicionar busca por coordenadas e regiões, camadas de cobertura por levantamento e links para compartilhar parâmetros de investigação.
2. **Investigações reproduzíveis.** Guardar observações e candidatos com IDs, datas, bandas, recortes e parâmetros de alinhamento. Permitir anotações e compartilhamento sem depender de um único arquivo remoto.
3. **Comparação quantitativa.** Acrescentar séries com várias épocas, incertezas, fotometria e astrometria calibradas. Apoiar validação cruzada de candidatos e distinguir artefatos, estrelas variáveis e objetos móveis.
4. **Acompanhamento de objetos.** Ampliar a visualização de Marte para outros corpos e integrar catálogos de distância, com referencial e incerteza explícitos.

## Fontes, créditos e licença

- **SPHEREx / NASA-IPAC IRSA:** [imagens espectrais DR1](https://doi.org/10.26131/IRSA678), [All-Sky Cube DR1](https://doi.org/10.26131/IRSA679) e [imagens espectrais QR3](https://doi.org/10.26131/IRSA662). A missão é um projeto do JPL e do Caltech financiado pela NASA. Consulte a [documentação de acesso aos dados](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/) para consultar e citar os produtos.
- **Dados ópticos e de apoio:** [ESO Online Digitized Sky Survey](https://archive.eso.org/dss/dss), [créditos e licença dos recortes DSS](assets/README.md), [NASA SkyView](https://skyview.gsfc.nasa.gov/) e [SIMBAD / CDS](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star) para orientar o marcador de Barnard.
- **Assistência de IA:** OpenAI Codex e Google Gemini auxiliaram no desenvolvimento, na depuração e na documentação. Visual Studio Code foi usado como editor. As imagens e os espectros observacionais vêm dos arquivos identificados no aplicativo.
- O código é [MIT](LICENSE). Os recortes e produtos de dados de terceiros mantêm as respectivas licenças.

**English quick start:** Open `index.html` with the `assets` folder beside it and open **Mapa Estelar**, search for **Barnard**, and switch between the sky chart and the 3D view. Select **Observar este astro** to open the archived comparison. Toggle the 1950 and 1991 optical plates to see Barnard's apparent position shift north relative to neighboring stars. Each frame links to its original FITS cutout. Run `python app.py` after installing the requirements to query SPHEREx and other archives.
