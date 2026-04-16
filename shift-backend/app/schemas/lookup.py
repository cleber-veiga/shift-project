"""
Schemas Pydantic para consultas publicas de CNPJ e CEP.
"""

from pydantic import BaseModel


class CNPJResponse(BaseModel):
    cnpj: str
    razao_social: str
    nome_fantasia: str | None = None
    cnae_fiscal: str | None = None
    cnae_fiscal_descricao: str | None = None
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    cep: str | None = None
    municipio: str | None = None
    uf: str | None = None
    situacao_cadastral: str | None = None
    inscricao_estadual: str | None = None


class CEPResponse(BaseModel):
    cep: str
    logradouro: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    localidade: str | None = None
    uf: str | None = None
    estado: str | None = None
