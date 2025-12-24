"""
Utilitários de timing humanizado.
"""
import time
import random


def gauss_wait(seconds, percent=10):
    """
    Sleep gaussiano com variação percentual.

    Args:
        seconds: Tempo base em segundos (média)
        percent: Variação em porcentagem (desvio padrão = seconds * percent / 100)

    Exemplo:
        gauss_wait(0.5, 10)  # Sleep de ~0.5s com ±10% de variação
        gauss_wait(1.0, 20)  # Sleep de ~1.0s com ±20% de variação

    Returns:
        float: Tempo efetivamente dormido
    """
    sigma = seconds * (percent / 100)
    actual = max(0.01, random.gauss(seconds, sigma))  # Mínimo 10ms
    time.sleep(actual)
    return actual
