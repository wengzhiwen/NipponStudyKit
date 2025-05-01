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

def create_buffalo_project(pdf_path) -> Project:
    config = Config()
    buffalo = Buffalo(base_dir=config.base_dir, template_path=config.buffalo_template_file)

    # 以pdf的basename的前5位加日期时间作为buffalo project的name
    project_folder_name = os.path.basename(pdf_path)[:5] + datetime.now().strftime('%Y%m%d_%H%M%S')
    project: Project = buffalo.create_project(project_folder_name)

    project.move_to_project(Path(pdf_path), "handbook.pdf")

    return project

def pdf2img(project: Project, work: Work):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.DONE)
    project.save_project()

def ocr(project: Project, work: Work):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.DONE)
    project.save_project()

def translate(project: Project, work: Work):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.DONE)
    project.save_project()

def analysis(project: Project, work: Work):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.DONE)
    project.save_project()

def output(project: Project, work: Work):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.DONE)
    project.save_project()

workers = {
    "01_pdf2img": pdf2img,
    "02_ocr": ocr,
    "03_translate": translate,
    "04_analysis": analysis,
    "05_output": output,
}

def factory_start():
    config = Config()

    for work_name, worker in workers.items():
        while True:
            buffalo = Buffalo(base_dir=config.base_dir, template_path=config.buffalo_template_file)
            project: Project
            work: Work
            project, work = buffalo.get_a_job(work_name)
            if project is None or work is None:
                break
            try:
                worker(project, work)
            except Exception as e:
                logger.error(f'{project.folder_name} - {work.name} 处理失败，错误信息: {e}')
                continue
            finally:
                time.sleep(1)

def workflow(pdf_folder):
    # 获取所有PDF文件
    pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
    total_pdfs = len(pdf_files)
    created_buffalo_projects = 0

    logger.info(f'找到 {total_pdfs} 个PDF文件')

    for pdf_path in pdf_files:
        logger.info(f'\n处理 {os.path.basename(pdf_path)}...')

        try:
            _ = create_buffalo_project(pdf_path)

            logger.info(f'进度: {created_buffalo_projects}/{total_pdfs} 已创建buffalo项目')
        except Exception as e:
            logger.error(f'错误: 创建buffalo项目失败，错误信息: {e}')
            continue
        finally:
            time.sleep(1)

    logger.info(f'总共创建的buffalo项目数: {created_buffalo_projects}')

    factory_start()


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
