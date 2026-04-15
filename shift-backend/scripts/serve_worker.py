"""Inicia o worker Prefect registrando o flow como deployment."""
from app.orchestration.flows.dynamic_runner import run_workflow

run_workflow.serve(name="shift-workflow-runner")
