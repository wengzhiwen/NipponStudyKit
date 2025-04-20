import os
import logging
import datetime

def setup_logger(logger_name="app", log_dir="log", log_level="INFO") -> logging.Logger:
    """设置日志记录器
    
    Args:
        logger_name (str): 日志记录器名称
        log_dir (str): 日志文件保存目录
        log_level (str): 日志级别，默认为INFO
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    # 创建logger实例
    app_logger = logging.getLogger(logger_name)

    # 设置日志级别
    level = os.getenv("LOG_LEVEL", log_level)
    app_logger.setLevel(getattr(logging, level))

    # 防止日志重复
    if app_logger.hasHandlers():
        app_logger.handlers.clear()

    # 创建格式化器
    formatter = logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 创建并配置文件处理器
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{logger_name}_{datetime.datetime.now().strftime('%Y%m%d')}.log")

    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, level))

    # 创建并配置控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, level))

    # 添加处理器到logger
    app_logger.addHandler(file_handler)
    app_logger.addHandler(console_handler)

    # 设置不传播到父logger
    app_logger.propagate = False

    return app_logger 