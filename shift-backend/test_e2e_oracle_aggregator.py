import asyncio
import logging
from uuid import uuid4

import oracledb
oracledb.init_oracle_client()

from app.orchestration.flows.dynamic_runner import run_workflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_oracle_aggregator():
    """
    Testa um cenario real de ETL com agregacao:
    1. Extrai itens de nota fiscal (Origem: Oracle)
    2. Calcula o valor total de cada item (Math: QUANTIDADE * VALOR_UNITARIO)
    3. Agrupa por nota e soma os totais (Aggregator)
    4. Insere o resumo consolidado (Destino: Oracle)
    """
    workflow_id = str(uuid4())
    
    # Payload do React Flow simulado
    payload = {
        "nodes": [
            {
                "id": "trigger-1",
                "type": "triggerNode",
                "data": {"type": "triggerNode", "trigger_type": "manual"}
            },
            {
                "id": "extract-1",
                "type": "extractNode",
                "data": {
                    "type": "extractNode",
                    "connection_string": "oracle+oracledb://VIASOFTMCP:VIASOFTMCP@DW334:1521/VIASOFT3",
                    "table_name": "VIASOFTMCP.ITENS_NOTA_TESTE_DLT",
                    "chunk_size": 500
                }
            },
            {
                "id": "math-1",
                "type": "transformNode",
                "data": {
                    "type": "math",
                    "expressions": [
                        # Cria uma nova coluna com o total daquele item especifico
                        {
                            "target_column": "VALOR_TOTAL_ITEM",
                            "expression": "(QUANTIDADE * VALOR_UNITARIO) - DESCONTO"
                        }
                    ]
                }
            },
            {
                "id": "aggregator-1",
                "type": "aggregator",
                "data": {
                    "type": "aggregator",
                    "group_by": ["NUMERO_NOTA"],
                    "aggregations": [
                        # Soma os totais dos itens para dar o total da nota
                        {
                            "column": "VALOR_TOTAL_ITEM",
                            "operation": "sum",
                            "alias": "VALOR_TOTAL_NOTA"
                        },
                        # Conta quantos itens tem na nota
                        {
                            "column": "ID_ITEM",
                            "operation": "count",
                            "alias": "QTD_ITENS"
                        }
                    ]
                }
            },
            {
                "id": "load-1",
                "type": "loadNode",
                "data": {
                    "type": "loadNode",
                    "connection_string": "oracle+oracledb://VIASOFTMCP:VIASOFTMCP@localhost:1521/VIASOFT",
                    "target_table": "VIASOFTMCP.RESUMO_NOTAS_TESTE_DLT",
                    "write_disposition": "merge"
                }
            }
        ],
        "edges": [
            {"source": "trigger-1", "target": "extract-1"},
            {"source": "extract-1", "target": "math-1"},
            {"source": "math-1", "target": "aggregator-1"},
            {"source": "aggregator-1", "target": "load-1"}
        ]
    }

    logger.info("Iniciando execucao do workflow de Agregacao (Notas Fiscais)...")
    
    # Executar o fluxo (run_workflow agora e async — roda via asyncio.run).
    try:
        result = asyncio.run(run_workflow(
            workflow_payload=payload,
            workflow_id=workflow_id,
            triggered_by="manual",
        ))
        logger.info(f"Execucao finalizada com sucesso. Resultado: {result}")
    except Exception as e:
        logger.error(f"Erro durante a execucao: {e}")

if __name__ == "__main__":
    test_oracle_aggregator()
