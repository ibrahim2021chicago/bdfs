import logging
import logging.handlers
import os
from datetime import datetime

def setup_logger(log_dir='logs', level=logging.INFO):
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    # Local file handler
    os.makedirs(log_dir, exist_ok=True)
    log_filename = datetime.now().strftime('%Y-%m-%d_%H-%M-%S.log')
    log_path = os.path.join(log_dir, log_filename)
    file_handler = logging.FileHandler(log_path)
    formatter = logging.Formatter('%(asctime)s %(name)s: %(levelname)s %(message)s')
    file_handler.setFormatter(formatter)

    # Syslog handler
    syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
    syslog_handler.setFormatter(formatter)

    # Clear existing handlers before adding new ones
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(syslog_handler)

    return logger