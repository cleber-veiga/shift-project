"""Pacote de utilitarios de banco de dados para servicos do shift-backend.

Conteudo principal:

- ``engine_cache``: cache global de engines SQLAlchemy por workspace,
  com pool dimensionado por tipo de banco e metricas Prometheus.
"""
