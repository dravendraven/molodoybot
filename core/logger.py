"""
Sistema de Logging Centralizado para MolodoyBot (v2)

Cria logs rotativos separados para crash e operational logging:

Arquivos gerados:
- crash.log: Crash logging (SEMPRE ATIVO) - max 2MB, 1 backup
- molodoy_bot.log: Operational logging (toggle na GUI) - max 5MB, 3 backups
- crash_dump.txt: Stack traces de segfaults (via faulthandler)
- crash_state.json: Estado do jogo no momento do crash

v2 Changes:
- Separação de crash logging (sempre ativo) e operational logging (controlável)
- Toggle em runtime via toggle_operational_logging()
- Correção de file handle leak do faulthandler
"""

import logging
import sys
import os
import json
import time
import threading
import traceback
import faulthandler
from logging.handlers import RotatingFileHandler
from functools import wraps

# Singleton do logger
_logger = None
_crash_dump_file = None


def get_log_directory():
    """Retorna o diretório onde os logs serão salvos."""
    # Usa o diretório do executável/script
    if getattr(sys, 'frozen', False):
        # Executando como .exe (PyInstaller)
        base_dir = os.path.dirname(sys.executable)
    else:
        # Executando como script Python
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    log_dir = os.path.join(base_dir, "logs")

    # Cria diretório de logs se não existir
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError:
            # Fallback para diretório atual se não conseguir criar
            log_dir = base_dir

    return log_dir


def setup_logger(name="MolodoyBot", operational_logging_enabled=False, console_level=logging.INFO):
    """
    Configura e retorna o logger centralizado com handlers separados.

    Args:
        name: Nome do logger
        operational_logging_enabled: Se True, ativa logging detalhado (DEBUG/INFO/WARNING)
                                     Se False, apenas crash logging (CRITICAL)
        console_level: Nível mínimo para output no console

    Returns:
        logging.Logger configurado
    """
    global _logger, _crash_dump_file

    if _logger is not None:
        return _logger

    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)  # Logger aceita tudo, filtro nos handlers

    # Evita handlers duplicados se chamado múltiplas vezes
    if _logger.handlers:
        return _logger

    log_dir = get_log_directory()

    # Formato detalhado para arquivos
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s - %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ===================================================================
    # 1. CRASH LOG (SEMPRE ATIVO) - Só loga CRITICAL (crashes)
    # ===================================================================
    crash_log_path = os.path.join(log_dir, "crash.log")
    try:
        crash_handler = RotatingFileHandler(
            crash_log_path,
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=1,
            encoding="utf-8"
        )
        crash_handler.setLevel(logging.CRITICAL)  # Apenas crashes
        crash_handler.setFormatter(file_formatter)
        _logger.addHandler(crash_handler)
        print(f"[LOGGER] Crash logging ativado: {crash_log_path}")
    except Exception as e:
        print(f"[LOGGER] ERRO ao criar crash log: {e}")

    # ===================================================================
    # 2. OPERATIONAL LOG (CONTROLADO POR TOGGLE) - DEBUG/INFO/WARNING
    # ===================================================================
    if operational_logging_enabled:
        operational_log_path = os.path.join(log_dir, "molodoy_bot.log")
        try:
            operational_handler = RotatingFileHandler(
                operational_log_path,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8"
            )
            operational_handler.setLevel(logging.DEBUG)  # Tudo exceto CRITICAL (já logado no crash.log)
            operational_handler.setFormatter(file_formatter)
            operational_handler.addFilter(lambda record: record.levelno < logging.CRITICAL)  # Evita duplicação
            _logger.addHandler(operational_handler)
            print(f"[LOGGER] Operational logging ativado: {operational_log_path}")
        except Exception as e:
            print(f"[LOGGER] Erro ao criar operational log: {e}")

    # Handler para console (menos verbose)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)

    # Formato simplificado para console
    console_formatter = logging.Formatter(
        "[%(levelname)s] %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    _logger.addHandler(console_handler)

    # Ativa faulthandler para capturar segfaults
    crash_dump_path = os.path.join(log_dir, "crash_dump.txt")
    try:
        _crash_dump_file = open(crash_dump_path, "w")
        faulthandler.enable(file=_crash_dump_file)
        print(f"[LOGGER] Faulthandler ativado: {crash_dump_path}")
    except Exception as e:
        print(f"[LOGGER] Não foi possível ativar faulthandler: {e}")

    status = "com operational logging" if operational_logging_enabled else "apenas crash logging"
    print(f"[LOGGER] Inicializado {status}. Logs em: {log_dir}")

    return _logger


def get_logger():
    """Retorna o logger existente ou cria um novo."""
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger


def toggle_operational_logging(enabled: bool):
    """
    Ativa ou desativa operational logging em runtime.
    Crash logging permanece sempre ativo.

    Args:
        enabled: True para ativar, False para desativar
    """
    logger = get_logger()
    log_dir = get_log_directory()

    # Remove handlers operacionais existentes
    for handler in logger.handlers[:]:
        if isinstance(handler, RotatingFileHandler):
            if "molodoy_bot.log" in handler.baseFilename:
                logger.removeHandler(handler)
                handler.close()
                print(f"[LOGGER] Operational handler removido")

    # Adiciona novo handler se enabled
    if enabled:
        operational_log_path = os.path.join(log_dir, "molodoy_bot.log")
        try:
            operational_handler = RotatingFileHandler(
                operational_log_path,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8"
            )
            operational_handler.setLevel(logging.DEBUG)

            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(threadName)s - %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            operational_handler.setFormatter(formatter)

            # Filtra CRITICAL para evitar duplicação no crash.log
            operational_handler.addFilter(lambda record: record.levelno < logging.CRITICAL)

            logger.addHandler(operational_handler)
            print(f"[LOGGER] Operational logging ativado em runtime: {operational_log_path}")
        except Exception as e:
            print(f"[LOGGER] Erro ao ativar operational logging: {e}")
    else:
        print(f"[LOGGER] Operational logging desativado - apenas crash logging ativo")


def shutdown_logger():
    """
    Fecha todos os handlers e libera recursos (incluindo faulthandler).
    Deve ser chamado no shutdown do bot.
    """
    global _logger, _crash_dump_file

    if _logger:
        # Fecha todos os handlers
        for handler in _logger.handlers[:]:
            try:
                handler.close()
                _logger.removeHandler(handler)
            except Exception:
                pass

        print("[LOGGER] Todos os handlers fechados")

    # Fecha file handle do faulthandler (CORRIGE LEAK)
    if _crash_dump_file:
        try:
            _crash_dump_file.close()
            _crash_dump_file = None
            print("[LOGGER] Faulthandler file handle fechado")
        except Exception:
            pass


def install_crash_handler(game_state_getter=None):
    """
    Instala handler global para exceções não tratadas.

    Args:
        game_state_getter: Função que retorna dict com estado do jogo
    """
    logger = get_logger()
    log_dir = get_log_directory()

    def global_exception_handler(exc_type, exc_value, exc_tb):
        """Captura todas as exceções não tratadas na main thread."""
        # Ignora KeyboardInterrupt (Ctrl+C)
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        logger.critical("=" * 60)
        logger.critical("CRASH NAO TRATADO!")
        logger.critical("=" * 60)

        # Log do traceback completo
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        for line in tb_lines:
            logger.critical(line.rstrip())

        # Salva estado do crash
        crash_state = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_unix": time.time(),
            "exception_type": str(exc_type.__name__),
            "exception_message": str(exc_value),
            "active_threads": [t.name for t in threading.enumerate()],
            "traceback": "".join(tb_lines)
        }

        # Adiciona estado do jogo se disponível
        if game_state_getter:
            try:
                game_state = game_state_getter()
                crash_state["game_state"] = game_state
            except Exception as e:
                crash_state["game_state_error"] = str(e)

        # Tenta obter info de memória
        try:
            import psutil
            process = psutil.Process()
            crash_state["memory_mb"] = round(process.memory_info().rss / (1024 * 1024), 2)
            crash_state["cpu_percent"] = process.cpu_percent()
        except Exception:
            pass

        # Salva em arquivo JSON
        crash_state_path = os.path.join(log_dir, "crash_state.json")
        try:
            with open(crash_state_path, "w", encoding="utf-8") as f:
                json.dump(crash_state, f, indent=2, ensure_ascii=False)
            logger.critical(f"Estado do crash salvo em: {crash_state_path}")
        except Exception as e:
            logger.error(f"Erro ao salvar estado do crash: {e}")

        # Chama handler original
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = global_exception_handler
    logger.info("Crash handler global instalado")


def install_thread_exception_handler():
    """
    Instala handler para exceções em threads (Python 3.8+).
    """
    logger = get_logger()

    def thread_exception_handler(args):
        """Handler para exceções não tratadas em threads."""
        logger.critical(f"CRASH EM THREAD: {args.thread.name}")
        logger.critical(f"Tipo: {args.exc_type.__name__}")
        logger.critical(f"Valor: {args.exc_value}")

        if args.exc_traceback:
            tb_lines = traceback.format_tb(args.exc_traceback)
            for line in tb_lines:
                logger.critical(line.rstrip())

    # Só disponível no Python 3.8+
    if hasattr(threading, 'excepthook'):
        threading.excepthook = thread_exception_handler
        logger.info("Thread exception handler instalado")
    else:
        logger.warning("Thread exception handler não disponível (requer Python 3.8+)")


def thread_safe_wrapper(func):
    """
    Decorator que adiciona logging e tratamento de erros a funções de thread.

    Uso:
        @thread_safe_wrapper
        def minha_thread_loop():
            ...
    """
    logger = get_logger()

    @wraps(func)
    def wrapper(*args, **kwargs):
        thread_name = threading.current_thread().name
        logger.info(f"Thread iniciada: {thread_name} ({func.__name__})")

        try:
            return func(*args, **kwargs)
        except MemoryError as e:
            logger.critical(f"MEMORY ERROR em {thread_name}!")
            logger.critical(f"Função: {func.__name__}")
            logger.exception("Stack trace:")

            # Tenta liberar memória
            try:
                import gc
                collected = gc.collect()
                logger.warning(f"Garbage collection forçado: {collected} objetos liberados")
            except Exception:
                pass

            raise
        except Exception as e:
            logger.critical(f"CRASH em {thread_name}!")
            logger.critical(f"Função: {func.__name__}")
            logger.exception(f"Exceção: {e}")
            raise
        finally:
            logger.info(f"Thread finalizada: {thread_name} ({func.__name__})")

    return wrapper


def log_resource_usage(logger_instance=None):
    """
    Loga uso atual de recursos do processo.

    Returns:
        dict com cpu_percent e memory_mb
    """
    log = logger_instance or get_logger()

    try:
        import psutil
        process = psutil.Process()
        cpu = process.cpu_percent()
        ram_mb = process.memory_info().rss / (1024 * 1024)

        log.debug(f"Recursos: CPU={cpu:.1f}% RAM={ram_mb:.1f}MB")

        return {"cpu_percent": cpu, "memory_mb": ram_mb}
    except Exception as e:
        log.warning(f"Erro ao obter uso de recursos: {e}")
        return None


# Níveis de log exportados para conveniência
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
