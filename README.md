# Sky Researcher — GPS espacial

Localize astros, acompanhe trajetórias e explore como as posições mudam com o tempo. A página inicial simula Sol, Terra e Marte em 3D e mostra coordenadas e distâncias. O **Mapa Estelar** localiza outros alvos do catálogo e encaminha cada alvo a ferramentas de observação ou análise.

## Experimente com a Estrela de Barnard

1. Abra **Mapa Estelar**, digite **Barnard** e selecione **Estrela de Barnard** no catálogo. Também é possível pesquisar identificadores já cadastrados no nome, como **M42**.
2. Na **Carta 2D**, veja a direção da estrela a partir da Terra. Passe para a **Vista 3D** para ver a mesma estrela selecionada e sua distância aproximada de 5,96 anos-luz. Os anéis da escala logarítmica representam 10, 100 e 1.000 anos-luz.
3. Clique em **Observar este astro** para abrir a ação recomendada do alvo. No Modo de Observação, Barnard abre o exemplo com dois recortes ópticos incluídos, de 1950 e 1991. Alterne as datas para comparar sua posição aparente com a das vizinhas. Use **Consultar SPHEREx** para tentar uma comparação infravermelha ao vivo. [Proveniência dos recortes de Barnard](assets/README.md)

## O que funciona hoje

A busca, o catálogo, a Carta 2D e a Vista 3D funcionam com os dados locais. Os filtros do catálogo ajudam a encontrar alvos da Via Láctea e listam as galáxias externas em um grupo separado. A carta mostra a direção dos objetos dos dois grupos. A vista 3D representa uma amostra dos objetos da Via Láctea cadastrados em relação à Terra. Para **R Draconis**, a carta indica a direção e a vista 3D explica que falta uma distância para posicioná-la.

Ações do catálogo como pesquisar, selecionar ou trocar de vista são locais. O botão de observação encaminha o alvo para o comparador ou o espectro, conforme a ação disponível. As consultas aos arquivos remotos dependem da cobertura e da disponibilidade da fonte. O catálogo fornece direções e distâncias aproximadas para consulta. As trajetórias dinâmicas do GPS espacial abrangem Terra e Marte.

## Como executar

Ao abrir `index.html` diretamente, o GPS espacial oferece uma demonstração com datas amostradas, além do catálogo estelar e da atividade local de Barnard. Mantenha a pasta `assets/` ao lado do arquivo. Para consultar qualquer data da cobertura do GPS, acessar os arquivos remotos e usar o laboratório, execute o servidor com Python 3.10+:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Abra [http://127.0.0.1:8002](http://127.0.0.1:8002). A [documentação da API](http://127.0.0.1:8002/docs) é servida pelo mesmo processo. Para abrir o [exemplo de Barnard diretamente](http://127.0.0.1:8002/?page=workbench&example=barnard), use `?page=workbench&example=barnard`. As consultas ao vivo exigem conexão com o IRSA ou o SkyView, conforme a fonte escolhida.

### Explore o GPS espacial

Abra a página inicial ou clique em **Localizar Marte** no **Mapa Estelar**. A simulação começa no instante UTC atual e avança a **1 dia/s**. Use **Pausar** ou escolha **1 min/s**, **1 h/s**, **1 dia/s** ou **7 dias/s**. **Tempo real** sincroniza o relógio com o UTC e segue a 1 s/s. Em **Recorte UTC**, informe o início e o fim, clique em **Aplicar recorte** e use a linha do tempo ou a reprodução. Selecione um astro pelo modelo 3D, pelo rótulo na cena ou pelo painel. A câmera se aproxima em escala logarítmica, acompanha a posição do astro quando a data muda e permite girar ao seu redor. A preferência por movimento reduzido leva diretamente ao enquadramento. [Página inicial](http://127.0.0.1:8002/)

**Navegação livre** solta o foco sem mover a câmera. Arraste ou use as setas para mudar a direção da visão. Use W/S para avançar e recuar, A/D para mover lateralmente e Q/E para baixar e subir. Desloque a vista também com o botão direito, com Shift e arraste ou com dois dedos. **Visão geral** restaura o enquadramento inicial. A roda, a pinça e os botões deslocam a câmera em função da distância à superfície do astro focalizado. Na navegação livre, a roda aproxima na direção do ponteiro e a pinça usa o centro do gesto. A escala do movimento acompanha a aproximação e é limitada pela distância até a superfície mais próxima. O movimento é maior de longe e mais fino de perto. O zoom respeita um limite externo às malhas.

O servidor usa a efeméride local `astropy:builtin`. A rota `/api/ephemerides/mars?instant=...` fornece um estado pontual. O GPS carrega da rota `/api/ephemerides/solar-system?instant=...` uma janela de 720 dias em passos de até cinco dias. Entre as amostras, usa interpolação cúbica de Hermite das posições com as velocidades da efeméride como tangentes. A derivada da interpolação fornece as velocidades intermediárias. Quando recebe `end=...`, amostra do instante inicial ao final, incluindo os dois limites e usando passos menores para recortes mais curtos. O painel do astro mostra a menor e a maior distância ao Sol nas amostras do intervalo. A rota de transferência Terra–Marte está indisponível.

**Referência do movimento** escolhe o astro na origem da vista, independentemente do alvo da câmera. O GPS calcula `r_rel = r_corpo − r_referência` e `v_rel = v_corpo − v_referência` com os mesmos eixos e o mesmo instante. As curvas unem as posições 3D relativas em cada amostra. Os rastros com opacidade crescente mostram até 12 dias anteriores no referencial selecionado. Com o Sol na origem elas são órbitas heliocêntricas. As setas sólidas com ponta preenchida mostram a projeção dos vetores de velocidade na câmera. Os vetores usam a escala gráfica fixa de 0,16 ua por 10 km/s. A projeção varia com a câmera. O gráfico de barras compara os módulos a partir de zero em um único eixo em km/s, com o limite superior arredondado para cima em passos de 10 km/s. O zoom e o ritmo de reprodução preservam esses valores em um instante fixo. As duas rotas incluem `velocities_km_s` quando recebem `velocities=true`. No recorte, o campo acompanha cada amostra.

A grade polar segue a eclíptica média J2000, centrada na referência de movimento. Os anéis marcam intervalos de 0,5 ua. Os guias vão desaparecendo abaixo de 0,05 ua de distância à superfície mais próxima. Para renderizar com Y para cima, a cena usa `(X, Z, −Y)` e uma unidade de cena por ua. **Proporção real**, o modo inicial, converte raios pela mesma relação de 149.597.870,7 km por ua. **Distância entre centros** mede o segmento 3D selecionado e mostra seu comprimento em ua e km. A régua indica a escala no plano paralelo à tela que passa pelo centro do astro de referência ou em foco. Seu valor muda conforme a câmera se aproxima. Os diâmetros esféricos adotados para Sol, Terra e Marte são 1.392.700 km, 12.742 km e 6.779 km. O painel **Diâmetros lado a lado** usa uma escala comum. **Comparar tamanhos 3D** mostra modelos texturizados em projeção ortográfica, com centros no mesmo plano, numa cena própria. A razão desses diâmetros é 109,30 × 1 × 0,532. O foco enquadra cada corpo pelo próprio tamanho. O painel distingue o diâmetro físico da estimativa em pixels baseada na projeção da esfera que envolve o modelo. Na visão geral, o losango auxilia a seleção quando o diâmetro projetado é inferior a dois pixels. A esfera física continua na cena. **Visualização aprimorada** amplia os modelos para leitura. Os polos são aproximações fixas e a fase das texturas é ilustrativa. A vista 3D usa WebGL 2 com buffer de profundidade logarítmico. [UA definida pela IAU](https://www.iau.org/static/resolutions/IAU2012_English.pdf) · [Raios nominais da IAU](https://arxiv.org/abs/1510.07674) · [Raios de Marte da NASA](https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html?level=1) · [Orientação cartográfica da IAU](https://www.usgs.gov/publications/report-iau-working-group-cartographic-coordinates-and-rotational-elements-2015)

**Fora da Terra → Sol** começa a 5.000 km de altitude e acompanha a Terra conforme a data avança. A luz pontual sai do centro do Sol e decai com o quadrado da distância. A configuração mostra o crescente iluminado e o Sol no mesmo enquadramento. O halo tem escala proporcional ao raio solar. A esfera distante de estrelas é procedural.

**Curvatura espacial** exibe uma superfície de Flamm para o exterior de um Sol esférico isolado. É um recorte equatorial de Schwarzschild em tempo fixo. A métrica espacial do recorte é `dℓ² = dr²/(1 − rₛ/r) + r²dφ²`. A altura é `z(r) = 2√(rₛ(r − rₛ)) + C`, com `rₛ = 2GM☉/c² ≈ 2,95325 km`, `GM☉ = 1,3271244 × 10¹¹ km³/s²` e `c = 299.792,458 km/s`. A constante vertical põe a borda de 2 ua no nível da grade. O desenho começa no raio solar adotado e amplia somente a altura em 1.000×. A inclinação física `√(rₛ/(r − rₛ))` diminui com a distância. A camada acompanha a posição do Sol na referência escolhida e deixa intactas as posições, trajetórias, velocidades e tamanhos dos astros. [Métrica e superfície de Flamm](https://www.mpe.mpg.de/~ste/lecture/notes-2024-11-11.pdf) · [Parâmetro gravitacional solar nominal da IAU](https://arxiv.org/abs/1510.07674)

**Campo gravitacional** fica logo abaixo de **Vetores de velocidade** no painel **Movimento relativo** e combina três fontes esféricas com as posições instantâneas das efemérides. O shader usa distâncias 3D em km e calcula `Φ = −Σ GMᵢ / rᵢ` fora das esferas físicas. Exibe cores e contornos de `|Φ|` em escala logarítmica de 300 a 200.000 km²/s² sobre um recorte paralelo à grade eclíptica. O plano passa pelo Sol na visão geral e pelo astro em foco durante a inspeção. As cores mais claras indicam maior `|Φ|`. Os valores de `GM`, em km³/s², são 132.712.440.000 para o Sol (IAU nominal), 398.600,435507 para a Terra (JPL DE440) e 42.828,37362 para Marte (JPL MAR097, planeta). [IAU](https://arxiv.org/abs/1510.07674) · [JPL DE440](https://ssd.jpl.nasa.gov/astro_par.html) · [JPL MAR097](https://ssd.jpl.nasa.gov/sats/phys_par/)

Em cada centro, a aceleração em m/s² é a soma vetorial das contribuições dos outros dois astros, dadas por `GMⱼ (rⱼ − rᵢ) / |rⱼ − rᵢ|³` com as conversões de unidade. As setas tracejadas com ponta vazada indicam direção. O painel mostra a magnitude resultante e a de cada contribuição, e no foco permite escolher qual delas a seta exibe. O campo usa gravitação newtoniana instantânea de três corpos esféricos. Posições e trajetórias continuam vindo das efemérides.

O servidor funciona sem acesso externo para as efemérides. Ao abrir o arquivo diretamente ou quando o endpoint está indisponível na abertura, a demonstração usa as amostras locais geradas em torno de 16 de janeiro de 2025. [Proveniência da demonstração e dos recursos gráficos](assets/README.md)

Para verificar no navegador a visão geral em **Proporção real** e a aproximação por cada marcador ou rótulo, execute `python scripts/check_real_scale_view.py` com o servidor em execução, Playwright instalado no ambiente de teste e Microsoft Edge com WebGL 2 disponível. O teste confere os marcadores subpixel, a proporção dos discos, a aproximação contínua, a régua de zoom e os pixels dos três modelos em desktop e celular.

Nas mesmas condições, `python scripts/check_gps_physics.py` confere diâmetros, distâncias, projeção dos vetores, escala comum das barras, o campo newtoniano e a geometria de Schwarzschild na cena renderizada. Também verifica a comparação ortográfica, a iluminação a 5.000 km acima da Terra, os quatro ritmos, os rastros, a navegação por teclado e a pinça com entrada tátil emulada. Os dois scripts aceitam `--captures DIRETÓRIO` para salvar as capturas de desktop e celular.

#### Geometria de Marte em Python

`mars_geometry(instant)` aceita `YYYY-MM-DDTHH:MM:SS` com uma fração opcional de até seis dígitos e fuso explícito (`Z` ou `±HH:MM`). A faixa UTC vai de `2000-01-01T00:00:00Z` (inclusive) a `2050-01-01T00:00:00Z` (exclusive). Entradas inválidas, fora da faixa ou com segundo `60` geram `ValueError`.

O dicionário retorna `instant_utc` normalizado para UTC, `length_unit` (`au`), `frame` (origem no centro do Sol) e `model` (`astropy:builtin`). `positions` contém os vetores geométricos `x, y, z` de `sun`, `earth` e `mars`. `distances` contém `mars_earth` e `mars_sun`, obtidas das diferenças entre os vetores 3D. As componentes e as distâncias são valores `float`.

O metadado `axes: "ICRS"` identifica os eixos nominais de `astropy:builtin`. O Astropy combina diretamente os vetores do Sol e da Terra derivados de `erfa.epv00`, com orientação BCRS, com o vetor heliocêntrico de Marte de `erfa.plan94`, expresso no equador e no equinócio médios de J2000.0. A combinação produz um alinhamento aproximado ao ICRS e usa a convenção nativa dos vetores sem aplicar rotação. [Efemérides do Astropy](https://docs.astropy.org/en/stable/coordinates/solarsystem.html)

Os valores são estimativas geométricas para o mesmo instante em TDB, sem correção de tempo de luz. `mars_state(instant)` acrescenta `velocities_km_s`, com os vetores nativos de velocidade da mesma efeméride. A conversão UTC → TDB usa os segundos intercalares disponíveis localmente, inclusive na primeira chamada. O aviso `dubious year` do ERFA é esperado para datas futuras além do período coberto pelos dados de segundos intercalares e é suprimido durante a conversão.

`epv00` usa uma versão simplificada da teoria VSOP2000, cuja dinâmica de origem inclui correções relativísticas. `plan94` usa uma solução planetária analítica aproximada baseada nos elementos médios de Simon et al. A conversão TT → TDB inclui as diferenças relativísticas entre as escalas de tempo. O GPS usa os vetores geométricos da efeméride tal como são fornecidos. A camada de Schwarzschild representa a geometria espacial e a propagação orbital continua a cargo da efeméride. [ERFA epv00](https://raw.githubusercontent.com/liberfa/erfa/v2.0.1/src/epv00.c) · [VSOP2000](https://doi.org/10.1023/A:1012279014297) · [ERFA plan94](https://raw.githubusercontent.com/liberfa/erfa/v2.0.1/src/plan94.c) · [ERFA dtdb](https://raw.githubusercontent.com/liberfa/erfa/v2.0.1/src/dtdb.c)

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

## Roadmap do GPS espacial

1. **Navegação por coordenadas e datas.** Adicionar busca por coordenadas e regiões, camadas de cobertura por levantamento e links para compartilhar parâmetros de investigação.
2. **Investigações reproduzíveis.** Guardar observações e candidatos com IDs, datas, bandas, recortes e parâmetros de alinhamento. Permitir anotações e compartilhamento sem depender de um único arquivo remoto.
3. **Comparação quantitativa.** Acrescentar séries com várias épocas, incertezas, fotometria e astrometria calibradas. Apoiar validação cruzada de candidatos e distinguir artefatos, estrelas variáveis e objetos móveis.
4. **Acompanhamento de objetos.** Ampliar a visualização de Marte para outros corpos e integrar catálogos de distância, com referencial e incerteza explícitos.

## Fontes, créditos e licença

- **Histórico do projeto.** O comparador foi desenvolvido no NASA Space Apps Challenge para investigar observações de um mesmo campo. [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/)
- **SPHEREx / NASA-IPAC IRSA:** [imagens espectrais DR1](https://doi.org/10.26131/IRSA678), [All-Sky Cube DR1](https://doi.org/10.26131/IRSA679) e [imagens espectrais QR3](https://doi.org/10.26131/IRSA662). A missão é um projeto do JPL e do Caltech financiado pela NASA. Consulte a [documentação de acesso aos dados](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/) para consultar e citar os produtos.
- **Dados ópticos e de apoio:** [ESO Online Digitized Sky Survey](https://archive.eso.org/dss/dss), [créditos e licença dos recortes DSS](assets/README.md), [NASA SkyView](https://skyview.gsfc.nasa.gov/) e [SIMBAD / CDS](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star) para orientar o marcador de Barnard.
- **Assistência de IA:** OpenAI Codex e Google Gemini auxiliaram no desenvolvimento, na depuração e na documentação. Visual Studio Code foi usado como editor. As imagens e os espectros observacionais vêm dos arquivos identificados no aplicativo.
- O código é [MIT](LICENSE). Os recortes e produtos de dados de terceiros mantêm as respectivas licenças.

**English quick start:** Open `index.html` with the `assets` folder beside it and open **Mapa Estelar**, search for **Barnard**, and switch between the sky chart and the 3D view. Select **Observar este astro** to open the archived comparison. Toggle the 1950 and 1991 optical plates to see Barnard's apparent position shift north relative to neighboring stars. Each frame links to its original FITS cutout. Run `python app.py` after installing the requirements to query SPHEREx and other archives.
