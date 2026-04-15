"""
Excecoes customizadas para processadores de nos.
"""


class NodeProcessingError(Exception):
    """Falha funcional ao processar um no do workflow."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


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
