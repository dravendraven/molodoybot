# core/config_utils.py
"""
Utilitários para trabalhar com configurações dinâmicas (providers).

Fornece helpers para simplificar acesso a config providers em módulos
que recebem configurações via lambda ou callable.
"""


def make_config_getter(config_provider):
    """
    Cria uma função helper para acessar configurações de forma concisa.

    Args:
        config_provider: Callable que retorna dict de configurações
                        ou dict estático

    Returns:
        Função get_cfg(key, default) que acessa as configs

    Exemplo de uso:
        # No módulo que recebe o config_provider:
        def my_module_loop(pm, base_addr, config):
            get_cfg = make_config_getter(config)

            # Uso:
            enabled = get_cfg('enabled', False)
            targets = get_cfg('targets', [])
            min_delay = get_cfg('min_delay', 1.0)
    """
    def get_cfg(key, default=None):
        """Acessa uma chave da configuração com fallback."""
        if callable(config_provider):
            return config_provider().get(key, default)
        elif isinstance(config_provider, dict):
            return config_provider.get(key, default)
        else:
            return default

    return get_cfg
