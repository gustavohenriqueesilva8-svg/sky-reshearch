# Sky Researcher — o que mudou no céu?

O Sky Researcher é o primeiro passo para um **GPS espacial de código aberto**: um mapa que ajuda a encontrar objetos, localizar as observações disponíveis e investigar o que mudou entre elas. Para o desafio [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/) do NASA Space Apps, implementamos o primeiro caso de uso: comparar duas imagens da mesma região do céu e entender o que a comparação permite concluir.

É para **curiosos e estudantes** que querem explorar imagens astronômicas sem saber coordenadas ou formatos de arquivo; **educadores** que querem demonstrar movimento próprio com observações reais; e **astrônomos amadores e participantes de ciência cidadã** que querem localizar uma fonte e decidir o que investigar em seguida.

## Experimente com a Estrela de Barnard

1. Na página inicial, clique em **Comparar a Estrela de Barnard**.
2. Alterne entre **10/07/1950** e **17/06/1991**. O círculo mostra a posição aproximada de Barnard. Use as estrelas vizinhas para perceber o que permanece no lugar.
3. Em 1950, Barnard aparece na metade inferior do recorte. Em 1991, aparece mais ao norte, enquanto as vizinhas continuam em posições semelhantes. Isso é compatível com o [movimento próprio conhecido da estrela](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star).
4. Confira as placas e os links para os FITS originais no painel ao lado. Os recortes são **ópticos**, do Digitized Sky Survey (DSS), e estão incluídos no projeto. A atividade funciona sem acesso aos arquivos remotos. O brilho na tela não mede variação de brilho da estrela.

Depois do exemplo, use **Consultar SPHEREx** para procurar observações no infravermelho, experimente **RW Aurigae** ou **R Draconis** para comparar a aparência de uma fonte ou escolha outro campo no **Mapa Estelar**. Se a consulta ao vivo não devolver um par utilizável, a interface explica o que faltou e deixa voltar ao exemplo.

## Como executar

Para fazer só a atividade de Barnard, abra `index.html` no navegador mantendo a pasta `assets/` no mesmo diretório. Para habilitar as consultas aos arquivos e o laboratório, use Python 3.10+:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Abra [http://127.0.0.1:8002](http://127.0.0.1:8002). A [documentação da API](http://127.0.0.1:8002/docs) é servida pelo mesmo processo. Para abrir o [exemplo de Barnard diretamente](http://127.0.0.1:8002/?page=workbench&example=barnard), use `?page=workbench&example=barnard`. As consultas ao vivo exigem conexão com o IRSA ou o SkyView, conforme a fonte escolhida.

## Como funciona

- **Comparação guiada:** escolha uma data, alterne manualmente ou reproduza as imagens. A origem e as datas disponíveis aparecem em ambos os modos. A mistura dos quadros é uma ajuda visual; cada época tem só um quadro observado.
- **Modo de Pesquisa:** altera coordenadas RA/Dec, raio do campo, detectores, canais, filtro e cadência. Expõe metadados FITS e WCS, seleção de fonte, subtração e soma exploratória. O visor permite salvar uma imagem ou exportar a alternância em WebM quando o navegador oferece suporte.
- **Mapa Estelar:** permite escolher objetos no catálogo ou indicar um ponto da carta equatorial. A vista 3D mostra direções e distâncias aproximadas a partir da Terra; não posiciona objetos sem distância cadastrada.
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

## Roadmap para o GPS espacial

1. **Navegação por coordenadas e datas.** Unificar o mapa, o catálogo e as camadas de cobertura por levantamento. Procurar por nome, coordenada ou região; salvar a posição e os parâmetros da investigação em um link.
2. **Investigações reproduzíveis.** Guardar observações e candidatos com IDs, datas, bandas, recortes e parâmetros de alinhamento. Permitir anotações e compartilhamento sem depender de um único arquivo remoto.
3. **Comparação quantitativa.** Acrescentar séries com várias épocas, incertezas, fotometria e astrometria calibradas. Apoiar validação cruzada de candidatos e distinguir artefatos, estrelas variáveis e objetos móveis.
4. **Navegação no espaço.** Integrar catálogos de distância e efemérides com época, referencial e incerteza explícitos, incluindo previsões de posição. A visão é orientar a exploração de dados celestes; esta versão não fornece posicionamento de uma nave.

## Fontes, créditos e licença

- **SPHEREx / NASA-IPAC IRSA:** [imagens espectrais DR1](https://doi.org/10.26131/IRSA678), [All-Sky Cube DR1](https://doi.org/10.26131/IRSA679) e [imagens espectrais QR3](https://doi.org/10.26131/IRSA662). A missão é um projeto do JPL e do Caltech financiado pela NASA. Consulte a [documentação de acesso aos dados](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/) para consultar e citar os produtos.
- **Dados ópticos e de apoio:** [ESO Online Digitized Sky Survey](https://archive.eso.org/dss/dss), [créditos e licença dos recortes DSS](assets/README.md), [NASA SkyView](https://skyview.gsfc.nasa.gov/) e [SIMBAD / CDS](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star) para orientar o marcador de Barnard.
- **Assistência de IA:** OpenAI Codex e Google Gemini auxiliaram no desenvolvimento, na depuração e na documentação. Visual Studio Code foi usado como editor. As imagens e os espectros observacionais vêm dos arquivos identificados no aplicativo.
- O código é [MIT](LICENSE). Os recortes e produtos de dados de terceiros mantêm as respectivas licenças.

**English quick start:** Open `index.html` with the `assets` folder beside it and choose **Comparar a Estrela de Barnard**. Toggle the 1950 and 1991 optical plates to see Barnard's apparent position shift north relative to neighboring stars. Each frame links to its original FITS cutout. Run `python app.py` after installing the requirements to query SPHEREx and other archives.
