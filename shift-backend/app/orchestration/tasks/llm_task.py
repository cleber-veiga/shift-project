"""
Execucao de nos do tipo aiNode / llmNode.
Integracao com LangChain usando LCEL (LangChain Expression Language).
"""

import asyncio

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.llms.fake import FakeListLLM

from app.core.logging import bind_context, get_logger
from app.core.retry import retry_with


# Politica de retry vem do tenacity (ver app/core/retry.py). Tenacity
# aplica automaticamente a variante async quando o alvo e uma coroutine.
@retry_with(attempts=2, delay_seconds=5)
async def execute_llm_node(
    node_id: str,
    config: dict,
    input_data: dict | None = None,
) -> dict:
    """
    Executa um no de IA/LLM usando uma chain LangChain (LCEL).

    Args:
        node_id: Identificador unico do no no workflow.
        config: Configuracao do no
            {prompt_template, model_name, temperature}.
        input_data: Dados de entrada recebidos de nos anteriores (opcional).

    Returns:
        Dicionario com o resultado do processamento do LLM.
    """
    logger = get_logger(__name__)
    prompt_template = config.get("prompt_template", "Processe: {input}")
    model_name = config.get("model_name", "gpt-4")

    with bind_context(node_id=node_id):
        logger.info("llm.start", model=model_name)

        prompt = ChatPromptTemplate.from_template(prompt_template)
        parser = StrOutputParser()

        # TODO: Substituir pelo LLM real (OpenAI, Anthropic, etc.)
        llm = FakeListLLM(responses=[
            f"[Mock LLM] Resultado simulado para o no '{node_id}'. "
            "Substitua pelo LLM real em producao."
        ])

        chain = prompt | llm | parser
        # chain.invoke e sincrono — roda em thread para nao bloquear o loop.
        result = await asyncio.to_thread(
            chain.invoke, input_data or {"input": "dados de exemplo"}
        )

        logger.info("llm.completed", model=model_name)
        return {
            "node_id": node_id,
            "model": model_name,
            "llm_output": result,
        }
