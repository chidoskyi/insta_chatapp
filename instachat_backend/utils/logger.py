import logging
import sys
from functools import wraps
from time import time

# Get logger instance
def get_logger(name):
    """Get a logger instance with the given name"""
    return logging.getLogger(name)

# Custom logger with additional features
class CustomLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)
    
    def debug(self, message, extra=None):
        self.logger.debug(message, extra=extra)
    
    def info(self, message, extra=None):
        self.logger.info(message, extra=extra)
    
    def warning(self, message, extra=None):
        self.logger.warning(message, extra=extra)
    
    def error(self, message, exc_info=True, extra=None):
        self.logger.error(message, exc_info=exc_info, extra=extra)
    
    def critical(self, message, exc_info=True, extra=None):
        self.logger.critical(message, exc_info=exc_info, extra=extra)
    
    def log_performance(self, func_name, start_time):
        """Log performance timing"""
        duration = time() - start_time
        self.info(f"Performance: {func_name} took {duration:.4f} seconds")
    
    def log_api_call(self, method, url, status_code, response_time, user=None):
        """Log API calls"""
        extra = {
            'method': method,
            'url': url,
            'status_code': status_code,
            'response_time': response_time,
            'user': user
        }
        self.info(f"API Call: {method} {url} - {status_code} ({response_time:.2f}s)", extra=extra)

# Performance monitoring decorator
def log_execution_time(logger_name='performance'):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            start_time = time()
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}")
                raise
            finally:
                duration = time() - start_time
                logger.info(f"{func.__name__} executed in {duration:.4f}s")
        return wrapper
    return decorator

# Create module-level logger
app_logger = CustomLogger('instachat_backend')  