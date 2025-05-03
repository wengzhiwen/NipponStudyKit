import argparse
from datetime import datetime
import time
import glob
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from buffalo import Buffalo, Work, Project
from pdf2image import convert_from_path
from ocr_tool import OCRTool
from translate_tool import TranslateTool
from analysis_tool import AnalysisTool

from logging_config import setup_logger

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

        try:
            # pylint: disable=invalid-envvar-default
            self.ocr_dpi = int(os.getenv("OCR_DPI", 150))
        except Exception:
            self.ocr_dpi = 150

        try:
            self.ocr_model_name = os.getenv("OCR_MODEL_NAME", "gpt-4o-mini")
        except Exception:
            self.ocr_model_name = "gpt-4o-mini"

        try:
            translate_terms_file = os.getenv("TRANSLATE_TERMS_FILE", "")
            if not translate_terms_file:
                raise ValueError("TRANSLATE_TERMS_FILE 环境变量未设置")
            if not Path(translate_terms_file).exists():
                raise FileNotFoundError(f"TRANSLATE_TERMS_FILE 文件不存在: {translate_terms_file}")
            with open(translate_terms_file, 'r', encoding='utf-8') as f:
                self.translate_terms = f.read()
        except Exception:
            self.translate_terms = ""

        try:
            self.translate_model_name = os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini")
        except Exception:
            self.translate_model_name = "gpt-4o-mini"

        try:
            self.analysis_model_name = os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini")
        except Exception:
            self.analysis_model_name = "gpt-4o-mini"

        analysis_questions_file = os.getenv("ANALYSIS_QUESTIONS_FILE", "")
        if not analysis_questions_file:
            raise ValueError("ANALYSIS_QUESTIONS_FILE 环境变量未设置")
        if not Path(analysis_questions_file).exists():
            raise FileNotFoundError(f"ANALYSIS_QUESTIONS_FILE 文件不存在: {analysis_questions_file}")
        with open(analysis_questions_file, 'r', encoding='utf-8') as f:
            self.analysis_questions = f.read()


        self._initialized = True


def create_buffalo_project(pdf_path) -> Project:
    config = Config()
    buffalo = Buffalo(base_dir=config.base_dir, template_path=config.buffalo_template_file)

    # 以pdf的basename的前5位加日期时间作为buffalo project的name
    project_folder_name = os.path.basename(pdf_path)[:5] + datetime.now().strftime('%Y%m%d_%H%M%S')
    project: Project = buffalo.create_project(project_folder_name)

    project.move_to_project(Path(pdf_path), "handbook.pdf")

    return project


def pdf2img(project: Project, work: Work, config: Config):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.IN_PROGRESS)
    project.save_project()

    # 将pdf转为图片这个操作，理论上不会失败，但仍然提供1次重试的机会
    retry_limit = 1

    while True:
        try:
            pdf_path = project.project_path / "handbook.pdf"
            if not pdf_path.exists():
                logger.error(f'{project.folder_name} - handbook.pdf 文件不存在')
                # retry is not necessary, not change status
                return

            images = convert_from_path(pdf_path, dpi=config.ocr_dpi)

            for i, image in enumerate(images):
                image.save(project.project_path / f'scan_{i}.png', 'PNG')

            work.set_status(Work.DONE)
            project.save_project()
            logger.info(f'{project.folder_name} - {work.name} 处理完成，共生成 {len(images)} 张图片')
            return

        except Exception as e:
            logger.error(f'{project.folder_name} - {work.name} 处理失败: {str(e)}')
            if retry_limit > 0:
                retry_limit -= 1
                continue
            else:
                logger.error(f'{project.folder_name} - {work.name} 处理失败，超过重试次数限制，放弃')
                # over retry limit, not change status
                return


def ocr(project: Project, work: Work, config: Config):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.IN_PROGRESS)
    project.save_project()

    try:
        image_files = sorted(project.project_path.glob('scan_*.png'))
        logger.debug(f'{project.folder_name} - 找到 {len(image_files)} 张图片')
        if not image_files:
            raise FileNotFoundError(f'{project.folder_name} - 未找到扫描图片')

        # 先提取当前文件夹中所有的md文件
        md_files = sorted(project.project_path.glob('*.md'))
        logger.debug(f'{project.folder_name} - 找到 {len(md_files)} 个md文件')

        ocr_tool = OCRTool(config.ocr_model_name)

        md_content = ""
        for img_path in image_files:
            # 如果当前图片的md文件已存在，则跳过
            if f'{img_path.stem}.md' in [md_file.name for md_file in md_files]:
                logger.info(f'{img_path.name} 对应的md文件 {img_path.stem}.md 已存在，跳过')
                try:
                    with open(project.project_path / f'{img_path.stem}.md', 'r', encoding='utf-8') as f:
                        current_page_content = f.read()
                        if current_page_content is None or len(current_page_content) == 0:
                            raise ValueError(f"{img_path.name} 对应的md文件 {img_path.stem}.md 虽然存在但内容为空")

                        md_content += current_page_content + '\n\n'
                    continue
                except Exception as e:
                    logger.info(f'{img_path.name} 对应的md文件 {img_path.stem}.md 虽然存在但读取失败: {str(e)}，从这里开始OCR')

            logger.info(f'开始使用 {config.ocr_model_name} 处理图片: {img_path.name}')

            # 将图片转换为markdown，比较容易因为波动等原因发生失败，提供1次重试的机会
            retry_limit = 1
            while True:
                try:
                    current_page_content = ocr_tool.img2md(img_path)

                    if current_page_content is None or len(current_page_content) == 0:
                        raise ValueError("OCR识别结束，但结果为空")

                    # 将当前结果保存到md文件中，如果文件已存在就直接覆盖
                    current_page_md_path = project.project_path / f'{img_path.stem}.md'
                    with open(current_page_md_path, 'w', encoding='utf-8') as f:
                        f.write(current_page_content)

                    md_content += current_page_content + '\n\n'

                    break
                except Exception as e:
                    logger.error(f'{project.folder_name} - {work.name} 处理失败: {str(e)}，重试中...')
                    if retry_limit > 0:
                        retry_limit -= 1
                        # 重试间隔10秒
                        time.sleep(10)
                        continue
                    else:
                        raise Exception(f'{project.folder_name} - {work.name} 处理失败，超过重试次数限制，放弃') from e

        # 保存OCR结果
        if md_content:
            md_path = project.project_path / 'handbook.md'
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
            work.set_status(Work.DONE)
            project.save_project()
        else:
            raise ValueError(f'{project.folder_name} - OCR未能提取任何有效内容，放弃')

    except Exception as e:
        logger.error(f'{project.folder_name} - OCR处理失败: {str(e)}')
        # do not change status
        # 需要人类介入，排除问题后修改该work的状态到not_started后，重新启动即可从失败的地方开始继续
        return


def translate(project: Project, work: Work, config: Config):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.IN_PROGRESS)
    project.save_project()

    try:
        # 读取handbook.md文件
        md_path = project.project_path / 'handbook.md'
        if not md_path.exists():
            raise FileNotFoundError(f'{project.folder_name} - handbook.md 文件不存在')

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if not md_content.strip():
            raise ValueError(f'{project.folder_name} - markdown文件内容为空')

        translate_tool = TranslateTool(config.translate_model_name, config.translate_terms)
        logger.info(f'开始使用 {config.translate_model_name} 执行翻译')

        # 翻译md内容，比较容易因为波动等原因发生失败，提供1次重试的机会
        retry_limit = 1
        while True:
            try:
                zh_content = translate_tool.md2zh(md_content)
                break
            except Exception as e:
                logger.error(f'{project.folder_name} - 翻译失败: {str(e)}')
                if retry_limit > 0:
                    retry_limit -= 1
                    time.sleep(10)
                    continue
                else:
                    raise Exception(f'{project.folder_name} - 翻译失败，超过重试次数限制，放弃') from e

        if not zh_content:
            raise ValueError(f'{project.folder_name} - 翻译失败')

        # 保存翻译结果
        zh_md_path = project.project_path / 'handbook_zh.md'
        with open(zh_md_path, 'w', encoding='utf-8') as f:
            f.write(zh_content)

        work.set_status(Work.DONE)
        project.save_project()

    except Exception as e:
        logger.error(f'{project.folder_name} - {work.name} 处理失败: {str(e)}')
        # do not change status
        # 需要人类介入，排除问题后修改该work的状态到not_started后，重新启动即可从失败的地方开始继续
        return


def analysis(project: Project, work: Work, config: Config):
    logger.info(f'{project.folder_name} - {work.name} 开始处理')
    work.set_status(Work.IN_PROGRESS)
    project.save_project()

    try:
        md_path = project.project_path / 'handbook.md'
        if not md_path.exists():
            raise FileNotFoundError(f'{project.folder_name} - handbook.md 文件不存在')

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if not md_content.strip():
            raise ValueError(f'{project.folder_name} - markdown文件内容为空')

        analysis_tool = AnalysisTool(config.analysis_model_name, config.analysis_questions, config.translate_terms)
        logger.info(f'开始使用 {config.analysis_model_name} 执行分析')

        # 分析md内容，比较容易因为波动等原因发生失败，提供1次重试的机会
        retry_limit = 1
        while True:
            try:
                report_content = analysis_tool.md2report(md_content)
                break
            except Exception as e:
                logger.error(f'{project.folder_name} - 分析失败: {str(e)}')
                if retry_limit > 0:
                    retry_limit -= 1
                    time.sleep(10)
                    continue
                else:
                    raise Exception(f'{project.folder_name} - 分析失败，超过重试次数限制，放弃') from e

        if not report_content:
            raise ValueError(f'{project.folder_name} - 分析失败')

        report_path = project.project_path / 'handbook_report.md'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)

        work.set_status(Work.DONE)
        project.save_project()

    except Exception as e:
        logger.error(f'{project.folder_name} - {work.name} 处理失败: {str(e)}')
        # do not change status
        # 需要人类介入，排除问题后修改该work的状态到not_started后，重新启动即可从失败的地方开始继续
        return


def output(project: Project, work: Work, config: Config):
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

    job_count = 0
    success_count = 0
    failed_count = 0

    while True:
        buffalo = Buffalo(base_dir=config.base_dir, template_path=config.buffalo_template_file)
        project: Project
        work: Work
        project, work = buffalo.get_a_job()
        if project is None or work is None:
            # 没有任务了，退出
            break

        job_count += 1
        worker = workers[work.name]
        try:
            worker(project, work, config)
            if work.status == Work.NOT_STARTED:
                logger.info(f'{project.folder_name} - {work.name} 未能正确处理，将会自动重试...')
            if work.status == Work.IN_PROGRESS:
                logger.info(f'{project.folder_name} - {work.name} 未能正确处理，需要人工介入')
                failed_count += 1
            if work.status == Work.DONE:
                logger.info(f'{project.folder_name} - {work.name} 处理完成')
                success_count += 1
        except Exception as e:
            logger.error(f'{project.folder_name} - {work.name} 处理失败，错误信息: {e}')
            continue
        finally:
            time.sleep(1)

    logger.info('当前base dir中的buffalo项目所属的所有任务都已执行完毕')
    logger.info(f'总共执行了 {job_count} 个任务，成功了 {success_count} 个，失败了 {failed_count} 个')

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

            created_buffalo_projects += 1
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
