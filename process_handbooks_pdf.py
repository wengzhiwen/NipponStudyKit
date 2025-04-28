import argparse
from datetime import datetime
import time
import glob
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from logging_config import setup_logger
from buffalo import Buffalo, Work, Project

logger = setup_logger(logger_name="ProcessHandbooksPDF", log_level="INFO")


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

        try:
            self.base_dir = Path(os.getenv("BASE_DIR", "bufallo_workspace"))
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ValueError(f"Base directory cannot be created: {self.base_dir}") from e

        try:
            self.buffalo_template_file = Path(os.getenv("BUFFALO_TEMPLATE_FILE_NAME", "wf_template.yml"))
            if not self.buffalo_template_file.exists():
                raise FileNotFoundError(f"Buffalo template file not found: {self.buffalo_template_file}")
        except Exception as e:
            raise FileNotFoundError(f"Buffalo template file not found: {self.buffalo_template_file}") from e

        self._initialized = True


def workflow(pdf_folder):
    config = Config()

    # 获取所有PDF文件
    pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
    total_pdfs = len(pdf_files)
    created_buffalo_projects = 0

    logger.info(f'找到 {total_pdfs} 个PDF文件')

    for pdf_path in pdf_files:
        logger.info(f'\n处理 {os.path.basename(pdf_path)}...')

        try:
            buffalo = Buffalo(base_dir=config.base_dir, template_path=config.buffalo_template_file)

            # 以pdf的basename的前5位加日期时间作为buffalo project的name
            project_folder_name = os.path.basename(pdf_path)[:5] + datetime.now().strftime('%Y%m%d_%H%M%S')
            project: Project = buffalo.create_project(project_folder_name)

            project.move_to_project(Path(pdf_path), "handbook.pdf")

            created_buffalo_projects += 1

            logger.info(f'进度: {created_buffalo_projects}/{total_pdfs} 已创建buffalo项目')
        except Exception as e:
            logger.error(f'错误: 创建buffalo项目失败，错误信息: {e}')
            continue
        finally:
            # 等待1秒
            time.sleep(1)

    logger.info('\n处理完成:')
    logger.info(f'总共创建的buffalo项目数: {created_buffalo_projects}')


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
