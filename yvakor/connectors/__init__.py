"""YVAKOR — Conectores plugáveis.

O usuário faz login/cadastro uma vez por serviço (painel da interface) e o
agente passa a ter as ferramentas daquele serviço disponíveis automaticamente.
Credenciais ficam em data/connectors.json (fora do git).
"""
from yvakor.connectors.manager import ConnectorManager

__all__ = ["ConnectorManager"]
