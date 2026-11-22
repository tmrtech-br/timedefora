"""GameBridge — camada de streaming/controle de consoles substituível.

Regra de arquitetura: serviços de catálogo, reservas, pagamentos, filas e
autenticação NUNCA importam módulos de adaptadores concretos; usam apenas
`get_adapter(method)` e o contrato `ConsoleStreamingAdapter`.
"""
from .contract import (CONTRACT_VERSION, AdapterError, AdapterResult, ConsoleRef, ConsoleStreamingAdapter,
                       StreamMetrics, StreamState)
from .registry import METHODS, get_adapter, method_info

__all__ = ['CONTRACT_VERSION', 'AdapterError', 'AdapterResult', 'ConsoleRef', 'ConsoleStreamingAdapter',
           'StreamMetrics', 'StreamState', 'METHODS', 'get_adapter', 'method_info']
