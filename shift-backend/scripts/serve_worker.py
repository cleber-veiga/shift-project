"""
Inicia o worker Prefect (process pool).

Ordem correta:
    1. make prefect          — servidor Prefect (terminal separado)
    2. make init-prefect     — só na primeira vez
    3. make worker           — este script

O worker cria o pool automaticamente se não existir, e executa
TODOS os deployments registrados nele:
  - shift-workflow-runner   (execuções manuais)
  - shift-cron-{uuid}       (execuções agendadas por cron)
"""
import asyncio

from app.core.config import settings

POOL = settings.PREFECT_WORK_POOL_NAME or "shift-pool"


async def main() -> None:
    from prefect.workers.process import ProcessWorker

    print(f"Iniciando worker no pool '{POOL}'...")
    print("Pressione Ctrl+C para encerrar.\n")

    async with ProcessWorker(work_pool_name=POOL) as worker:
        await worker.start()


asyncio.run(main())
