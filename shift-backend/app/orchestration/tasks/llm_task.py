"""
Task Prefect para nós do tipo aiNode / llmNode.
Integração com LangChain usando LCEL (LangChain Expression Language).
"""

from prefect import get_run_logger, task

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.llms.fake import FakeListLLM


@task(name="llm_node", retries=1, retry_delay_seconds=5)
def execute_llm_node(
    node_id: str,
    config: dict,
    input_data: dict | None = None,
) -> dict:
    """
    Executa um nó de IA/LLM usando uma chain LangChain (LCEL).

    Args:
        node_id: Identificador único do nó no workflow.
        config: Configuração do nó
            {prompt_template, model_name, temperature}.
        input_data: Dados de entrada recebidos de nós anteriores (opcional).

    Returns:
        Dicionário com o resultado do processamento do LLM.
    """
    logger = get_run_logger()
    prompt_template = config.get("prompt_template", "Processe: {input}")
    model_name = config.get("model_name", "gpt-4")

    logger.info(f"Nó LLM '{node_id}' — modelo: {model_name}")

    # Montar a chain LCEL
    prompt = ChatPromptTemplate.from_template(prompt_template)
    parser = StrOutputParser()

    # TODO: Substituir pelo LLM real (OpenAI, Anthropic, etc.)
    # Exemplo com LLM real:
    #   from langchain_openai import ChatOpenAI
    #   llm = ChatOpenAI(model=model_name, temperature=config.get("temperature", 0.7))
    llm = FakeListLLM(responses=[
        f"[Mock LLM] Resultado simulado para o nó '{node_id}'. "
        "Substitua pelo LLM real em produção."
    ])

    chain = prompt | llm | parser

    # Executar a chain com os dados de entrada
    result = chain.invoke(input_data or {"input": "dados de exemplo"})

    logger.info(f"Nó LLM '{node_id}' concluído.")
    return {
        "node_id": node_id,
        "model": model_name,
        "llm_output": result,
    }
