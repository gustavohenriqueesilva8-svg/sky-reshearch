# Recortes didáticos da Estrela de Barnard

As imagens são derivadas de observações reais do telescópio Schmidt de 48 polegadas de Palomar, digitalizadas no **Digitized Sky Survey** pelo Space Telescope Science Institute (STScI) e consultadas pelo [ESO Online Digitized Sky Survey](https://archive.eso.org/dss/dss). As datas abaixo são as datas de observação (`DATE-OBS`) informadas nos FITS do ESO.

| Quadro | Data | Levantamento e placa |
| --- | --- | --- |
| [barnard-1950.png](barnard-1950.png) | 10/07/1950 | [DSS1 / POSS-I vermelho, 099V (E164), FITS original](https://archive.eso.org/dss/dss/image?ra=17+57+50.5&dec=%2B04+36+20&equinox=J2000&x=16&y=16&Sky-Survey=DSS1&mime-type=download-fits) |
| [barnard-1991.png](barnard-1991.png) | 17/06/1991 | [DSS2 / POSS-II vermelho, A0BG (SF04022), FITS original](https://archive.eso.org/dss/dss/image?ra=17+57+50.5&dec=%2B04+36+20&equinox=J2000&x=16&y=16&Sky-Survey=DSS2-red&mime-type=download-fits) |

O material POSS-I é creditado à **Association of Universities for Research in Astronomy (AURA)** e o POSS-II, ao **California Institute of Technology (Caltech)**. Os PNGs derivados são distribuídos sob [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) conforme a [política DSS do STScI/MAST](https://archive.stsci.edu/publishing/data-use#GSC-DSS). A licença MIT do repositório se aplica ao código, não às imagens.

O [script de reprodução](../scripts/build_barnard_demo.py) baixa duas regiões de 16′ × 16′ centradas em RA 17h57m50,5s e Dec +04°36′20″ (J2000). Reprojeta a placa de 1950 para o WCS da placa de 1991, recorta a área central e ajusta o contraste de cada quadro separadamente para visualização. O marcador é desenhado pelo visor usando a posição J2000 e o movimento próprio catalogados no [SIMBAD (CDS), com referência ao Gaia EDR3](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star), propagados aproximadamente às datas das placas. Ele indica onde procurar e não representa uma medição feita pelo aplicativo.

Para reproduzir, instale as dependências na raiz e execute `python scripts/build_barnard_demo.py`. Se já tiver os FITS do ESO, use `--fits DSS1.fits DSS2-red.fits`. Os FITS originais não são incluídos no repositório.

## Cena do GPS espacial

Os mapas equiretangulares de Sol, Terra e Marte em `solar/` são do **Solar System Scope (INOVE)**, redimensionados a 512 × 256 e recomprimidos em JPEG. A orientação e a aparência das texturas na cena são ilustrativas. [Texturas originais](https://ssi.solarsystemscope.com/textures/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

`vendor/three-gps.min.js` contém Three.js **0.181.2** e `OrbitControls`, empacotados em formato IIFE com esbuild 0.25.12 para uso local. [Código-fonte do Three.js](https://github.com/mrdoob/three.js/tree/r181) · [Licença MIT da biblioteca](vendor/three-LICENSE.txt)

`solar-demo.js` contém uma janela de 720 dias amostrada pelo mesmo código da API. Para regenerar o exemplo na raiz do repositório, com as dependências Python instaladas, execute:

```bash
python - <<'PY'
import json
from pathlib import Path
from ephemerides import solar_simulation

sample = json.dumps(solar_simulation("2025-01-16T12:00:00Z"), separators=(",", ":"))
Path("assets/solar-demo.js").write_text(
    "// Generated from ephemerides.solar_simulation. See assets/README.md.\n"
    + "window.solarDemo = " + sample + ";\n"
)
PY
```
