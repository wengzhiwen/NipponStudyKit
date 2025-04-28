import argparse
from datetime import datetime
import os
import sys

from dotenv import load_dotenv
from logging_config import setup_logger

logger = setup_logger(logger_name="md_analysis", log_level="INFO")

class Config:
    """配置类，用于管理所有配置信息（单例模式）"""
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        load_dotenv()
        
        self.base_dir = os.getenv("BASE_DIR", "bufallo_workspace")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir_basename = os.getenv("OUTPUT_DIR_BASENAME", "pdf_with_md")
        self.output_dir = f"{output_dir_basename}_{timestamp}"

        self._initialized = True


def workflow(pdf_folder):
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将PDF文件转换为Markdown格式并提取招生信息')
    parser.add_argument('dir', nargs='?', help='PDF文件目录路径')
    args = parser.parse_args()

    if not args.dir:
        logger.error('错误: 在正常模式下需要提供PDF目录')
        sys.exit(1)
    if not os.path.isdir(args.dir):
        logger.error(f'错误: {args.dir} 不是一个目录')
        sys.exit(1)
    
    workflow(args.dir)
