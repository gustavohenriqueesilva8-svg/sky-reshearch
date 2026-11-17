"""Typed response contracts for the Sky Researcher v1 API."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat


class _ApiResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class StateVector3D(_ApiResponse):
    """Cartesian components in the units of the enclosing field."""

    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat


class EphemerisResponse(_ApiResponse):
    target_id: str
    instant_utc: AwareDatetime
    position_au: StateVector3D | None = Field(None, description="Posição cartesiana em unidades astronômicas.")
    velocity_km_s: StateVector3D | None = Field(None, description="Velocidade cartesiana em km/s.")
    frame: str = "heliocentric ICRS"
    source: str = "astropy:builtin"
    status: Literal["available", "unavailable"] = "available"
    message: str | None = None


class SpectralPoint(_ApiResponse):
    wavelength_um: Annotated[FiniteFloat, Field(gt=0)]
    flux_mjy_sr: FiniteFloat = Field(description="Brilho superficial em MJy/sr.")
    uncertainty_mjy_sr: Annotated[FiniteFloat, Field(ge=0, description="Incerteza em MJy/sr.")] | None = None


class SpherexIrsaResponse(_ApiResponse):
    target_id: str
    status: Literal["available", "unavailable"] = "available"
    source: str = "SPHEREx/IRSA"
    profile_kind: Literal["sky_background"] | None = Field(
        None,
        description="Identifica o fundo do céu na direção consultada.",
    )
    points: list[SpectralPoint] = Field(default_factory=list)
    ra_deg: Annotated[FiniteFloat, Field(ge=0, lt=360)] | None = None
    dec_deg: Annotated[FiniteFloat, Field(ge=-90, le=90)] | None = None
    message: str | None = None


class ScientificArticleItem(_ApiResponse):
    title: str
    authors: list[str] = Field(default_factory=list)
    summary: str | None = None
    url: Annotated[str, Field(pattern=r"^https?://")]
    published: AwareDatetime | None = None
    source: str = "arXiv"


class ResearchFeedResponse(_ApiResponse):
    target_id: str
    query_name: str
    spherex: SpherexIrsaResponse
    articles: list[ScientificArticleItem]
