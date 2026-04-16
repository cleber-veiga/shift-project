"""
Rotas REST para consultas publicas de CNPJ (BrasilAPI) e CEP (ViaCEP).
"""

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.models import User
from app.schemas.lookup import CEPResponse, CNPJResponse

router = APIRouter(tags=["lookups"])

_CNPJ_RE = re.compile(r"^\d{14}$")
_CEP_RE = re.compile(r"^\d{8}$")

_TIMEOUT = httpx.Timeout(10.0)


@router.get("/lookups/cnpj/{cnpj}", response_model=CNPJResponse)
async def lookup_cnpj(
    cnpj: str,
    _: User = Depends(get_current_user),
) -> CNPJResponse:
    digits = re.sub(r"\D", "", cnpj)
    if not _CNPJ_RE.match(digits):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CNPJ deve conter exatamente 14 digitos.",
        )

    url = f"https://brasilapi.com.br/api/cnpj/v1/{digits}"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)

    if resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CNPJ nao encontrado.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao consultar CNPJ na API externa.",
        )

    data = resp.json()

    return CNPJResponse(
        cnpj=data.get("cnpj", digits),
        razao_social=data.get("razao_social", ""),
        nome_fantasia=data.get("nome_fantasia") or None,
        cnae_fiscal=str(data["cnae_fiscal"]) if data.get("cnae_fiscal") else None,
        cnae_fiscal_descricao=data.get("cnae_fiscal_descricao") or None,
        logradouro=data.get("logradouro") or None,
        numero=data.get("numero") or None,
        complemento=data.get("complemento") or None,
        bairro=data.get("bairro") or None,
        cep=data.get("cep") or None,
        municipio=data.get("municipio") or None,
        uf=data.get("uf") or None,
        situacao_cadastral=str(data.get("descricao_situacao_cadastral", "")) or None,
        inscricao_estadual=data.get("inscricao_estadual") or None,
    )


@router.get("/lookups/cep/{cep}", response_model=CEPResponse)
async def lookup_cep(
    cep: str,
    _: User = Depends(get_current_user),
) -> CEPResponse:
    digits = re.sub(r"\D", "", cep)
    if not _CEP_RE.match(digits):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CEP deve conter exatamente 8 digitos.",
        )

    url = f"https://viacep.com.br/ws/{digits}/json/"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao consultar CEP na API externa.",
        )

    data = resp.json()

    if data.get("erro"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CEP nao encontrado.",
        )

    return CEPResponse(
        cep=data.get("cep", digits),
        logradouro=data.get("logradouro") or None,
        complemento=data.get("complemento") or None,
        bairro=data.get("bairro") or None,
        localidade=data.get("localidade") or None,
        uf=data.get("uf") or None,
        estado=data.get("estado") or None,
    )
