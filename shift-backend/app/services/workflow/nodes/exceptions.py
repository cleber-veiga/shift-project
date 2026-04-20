"""
Excecoes customizadas para processadores de nos.
"""


class NodeProcessingError(Exception):
    """Falha funcional ao processar um no do workflow."""

    def __init__(self, message: str, *, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class SubWorkflowError(NodeProcessingError):
    """Falha originada em um sub-workflow.

    Carrega ``failed_by`` (node_id do filho que falhou) e
    ``node_executions`` (lista com as execucoes ate a falha) para que o
    chamador — tipicamente ``call_workflow`` ou ``loop`` — possa exibir
    trace detalhado sem precisar de infra extra de observabilidade.
    """

    def __init__(
        self,
        message: str,
        *,
        failed_by: str | None = None,
        inner_error: str | None = None,
        node_executions: list | None = None,
    ):
        super().__init__(
            message,
            details={
                "failed_by": failed_by,
                "inner_error": inner_error,
                "node_executions": node_executions or [],
            },
        )
        self.failed_by = failed_by
        self.inner_error = inner_error
        self.node_executions = node_executions or []


class NodeProcessingSkipped(Exception):
    """
    Levantada quando um no decide abortar o fluxo graciosamente.

    Exemplo: um no de polling executa uma query que nao retorna dados.
    O motor do Shift interpreta esta excecao como
    "Encerrar o workflow sem erro - nada a processar."
    """

    def __init__(self, message: str = "No ignorado - sem dados para processar."):
        self.message = message
        super().__init__(self.message)
