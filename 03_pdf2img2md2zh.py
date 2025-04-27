# pylint: disable=invalid-name
'''
将PDF文件转换为Markdown格式、翻译并提取招生信息

使用方法：
python 03_pdf2img2md_make_index_openai.py [pdf_folder] [--resume resume_dir]

'''
import json
import os
import sys
import shutil
import glob
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import base64

from pdf2image import convert_from_path
from tqdm import tqdm
from dotenv import load_dotenv
from natsort import natsorted
from agents import Agent, Runner, TResponseInputItem
from logging_config import setup_logger

# 设置日志记录器
logger = setup_logger(logger_name="pdf2md", log_level="INFO")


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
        # OpenAI API配置
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 环境变量未设置")

        # 模型配置
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.ocr_model = os.getenv("OPENAI_OCR_MODEL", "gpt-4o-mini")

        # PDF转图像DPI配置
        try:
            self.dpi = int(os.getenv("DPI", "150"))
        except ValueError:
            logger.warning("DPI配置无效，使用默认值150")
            self.dpi = 150

        logger.info(f'SETUP INFO = DPI: {self.dpi}, OCR_MODEL: {self.ocr_model}, MODEL: {self.model}')
        self._initialized = True


def convert_pdf_to_images(pdf_file, dpi):
    """Convert PDF file to list of images"""
    images = convert_from_path(pdf_file, dpi=dpi)
    return images


def save_images_with_progress(images, output_folder):
    """Save images with multi-threading and progress bars"""
    total_pages = len(images)
    logger.info(f'总页数: {total_pages}')

    max_workers = max(1, os.cpu_count() - 1)
    logger.info(f'使用 {max_workers} 个线程进行转换')

    chunk_size = (total_pages + max_workers - 1) // max_workers
    chunks = [images[i:i + chunk_size] for i in range(0, total_pages, chunk_size)]

    progress_bars = [tqdm(total=len(chunk), desc=f'线程 {i+1}', position=i, ncols=80) for i, chunk in enumerate(chunks)]

    def save_chunk(chunk_images, start_idx, progress_bar):
        for j, image in enumerate(chunk_images):
            image.save(os.path.join(output_folder, f'scan_{start_idx + j}.png'), 'PNG')
            progress_bar.update(1)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, chunk in enumerate(chunks):
                futures.append(executor.submit(save_chunk, chunk, i * chunk_size, progress_bars[i]))

            for future in as_completed(futures):
                future.result()
    finally:
        for progress_bar in progress_bars:
            progress_bar.close()


def perform_ocr(image_path):
    """使用OpenAI Vision模型进行OCR"""
    logger.info("使用OpenAI Vision进行OCR...")
    config = Config()
    try:
        # 创建OCR代理
        ocr_agent = Agent(
            name="OCR Agent",
            instructions="""你是一个专业的OCR文本识别专家。
请仔细观察图像中的文本内容，并尽可能准确地提取所有文本和表格。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。
针对表格的提取，可以采用markdown的语法来表示，特别注意表格的列数（有些表格首行有空单元格，也要算作一列）

请注意：
1. 仅提取图像中的实际文本，不要添加任何解释或说明
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取表格中的所有文字
4. 忽略所有的纯图形内容（比如：logo，地图等，包括页面上的水印）
5. 忽略所有的页眉和页脚，但保留原文中每页的页码（如果原文中有），严格按照原文中标注的页码来提取（不论原文是否有错）
6. 如果遇到空白页或整页都是没有意义的内容，请返回：EMPTY_PAGE
""",
            model=config.ocr_model  # 使用专门的OCR模型
        )

        # 读取图像文件
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # 编码图像为base64
        base64_image = base64.b64encode(image_data).decode('utf-8')

        # 按照llm_as_a_judge.py的示例优化输入格式
        input_items: list[TResponseInputItem] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "请识别这个图像中的所有文字内容，保持原始格式。"
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{base64_image}"
                    }
                ]
            }
        ]

        # 运行OCR代理
        result = Runner.run_sync(ocr_agent, input_items)

        if not result.final_output.strip():
            raise ValueError("OpenAI Vision未能提取任何文本")

        return result.final_output
    except Exception as e:
        logger.error(f"OpenAI Vision OCR错误: {e}")
        return None  # 返回None而不是空字符串，表示OCR失败


def format_to_markdown(text_content, image_path):
    """使用OpenAI格式化OCR文本为markdown"""
    logger.info("格式化OCR文本为markdown...")

    # 创建格式化代理
    format_agent = Agent(name="Markdown Formatter",
                         instructions="""你是一个专业的文本格式化专家。
请将OCR出来的文本重新组织成Markdown格式。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。

请注意：
1. 保持除非OCR结果有明显的识别错误，否则不要修改OCR结果，更不要添加任何解释或说明，也不要进行归纳总结
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取不同的
4. OCR时已经要求忽略页眉、页脚，仅保留原文中的页码，请保持
   如有原文有页码的话，页码一律独立一行，前后空行，以 【数字 + ページ】 的形式表现
5. OCR时已经要求忽略所有的纯图形内容（比如：logo，地图等，包括页面上的水印），请保持；特别注意不要以Base64的编码来处理任何纯图形内容
6. 如果文本中包含大量无意义的信息，请删除他们
7. 对于像目录这样的内容，可能会包含大量的「..........」或事「-------------」这样的符号，如果只是为了表达页码的话请将其长度现在6个点也就是「......」
8. 如果有URL信息，请保持完整的URL信息，但不要用Markdown的链接格式来处理URL，保留纯文本状态即可
9. 如果遇到空白页或整页都是没有意义的内容，请返回：EMPTY_PAGE
10. 结果会被直接保存为md文件，所以请不要添加任何```markdown```之类的定界符

关于Markdown的语法格式，特别注意以下要求：
1. 表格前后的空行要保留
2. 列表前后的空行要保留
3. 标题前后的空行要保留
4. 表格的排版（特别是合并单元格）要与原文（图片）完全一致
5. 根据Markdown的语法，需要添加空格的地方，请务必添加空格；但不要在表格的单元格内填充大量的空格，需要的话填充一个空格即可
总之，要严格的践行Markdown的语法要求，不要只是看上去像，其实有不少语法错误
""",
                         model=Config().model)

    # 读取图像文件
    with open(image_path, 'rb') as f:
        image_data = f.read()

    # 编码图像为base64
    base64_image = base64.b64encode(image_data).decode('utf-8')

    # 按照llm_as_a_judge.py的示例优化输入格式
    input_items = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": f"请将以下OCR文本重新组织成Markdown格式：\n\n{text_content} \n\n-----------\n\n务必尊从系统提示词中的要求来进行格式化。"
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{base64_image}"
                }
            ]
        }
    ]

    # 运行格式化代理
    result = Runner.run_sync(format_agent, input_items)

    return result.final_output


def translate_markdown(md_content):
    """使用OpenAI翻译日语Markdown内容为中文"""
    logger.info("翻译Markdown内容为中文...")

    # 创建翻译代理
    translator_agent = Agent(name="Translator",
                             instructions="""你是一位专业的日语翻译专家，擅长将日语文本翻译成中文。
请将用户输入的日语Markdown文本翻译成中文，要求：
1. 保持原有的Markdown格式，标题、列表、表格、段落等格式要与原文完全一致
2. 翻译要准确、通顺，符合中文表达习惯
3. 专业术语要准确翻译
4. 不要添加任何额外的说明或注释
5. 直接返回翻译结果，不需要其他解释
6. 结果会被直接保存为md文件，所以请不要添加任何```markdown```之类的定界符
7. 针对学部和专业的名称，尽可能使用符合中文的表达方式来翻译，很难翻译准确的可以采用"将日文汉字变成中文汉字，假名变成英语"的方式来翻译。
   但是注意上下文中同一个学部和专业的名称，尽可能使用相同的翻译方式。
8. 所有第三方考试的名称，比如：EJU，TOEFL，TOEIC，等，使用统一的英语缩写来翻译。
9. 完整翻译全文，不要遗漏任何内容，不要添加任何解释或说明也不要进行归纳总结

部分专业术语（尽可能使用以下的中文来表达对应的日语含义，主要为了符合留学生的表达习惯）：
- 招生简章：募集要項
- 报名截止日：報名締め切り日
- 自费留学生：私費留学生
- 目录：目次
- 学部：学部
- 学科：学科
- 专攻：コース・専攻
- 出愿：出願
- 文件：資料・書類
- 校区：キャンパス
- 入学金：入学金
- 学费：授業料
""",
                             model=Config().model)

    # 按照llm_as_a_judge.py的示例优化输入格式
    input_items = [
        {
            "role": "user",
            "content": f"""请将以下日语Markdown文本翻译成中文：

{md_content}

-----------

请直接返回翻译结果。务必尊从系统提示词中的要求来进行翻译。"""
        }
    ]

    # 运行翻译代理
    result = Runner.run_sync(translator_agent, input_items)

    return result.final_output


def analyze_admission_info(md_content):
    """使用OpenAI分析招生信息"""
    logger.info("分析招生信息...")

    # 创建分析代理
    analyze_agent = Agent(name="Admission Analyzer",
                          instructions="""你是一位专业的大学招生信息分析专家，擅长分析大学招生信息。
请根据输入的Markdown文本进行分析并提取以下信息，以JSON格式返回。

请严格按照以下JSON格式返回（必须是合法的JSON格式，不要添加任何其他说明文字）：
{
    "大学名称": "大学的日语全名",
    "报名截止日期": "YYYY/MM/DD格式，如果有多个日期选择最晚的，无法确认则返回2099/01/01"
}
""",
                          model=Config().model)

    # 按照llm_as_a_judge.py的示例优化输入格式
    input_items = [
        {
            "role": "user",
            "content": md_content + "\n\n请确保返回的是合法的JSON格式，不要包含任何其他说明文字。"
        }
    ]

    # 运行分析代理
    result = Runner.run_sync(analyze_agent, input_items)

    # 尝试解析JSON
    try:
        json.loads(result.final_output)
        return result.final_output
    except json.JSONDecodeError:
        # 如果不是有效的JSON，尝试提取JSON部分
        import re
        json_match = re.search(r'\{.*\}', result.final_output, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            try:
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                logger.error(f"无法提取有效的JSON: {result.final_output}")
                return None
        else:
            logger.error(f"响应中没有有效的JSON: {result.final_output}")
            return None


def sanitize_filename(filename):
    """净化文件名，替换无效字符"""
    # 将日期中的斜杠替换为破折号
    filename = filename.replace('/', '-')
    # 替换空格和其他特殊字符
    filename = filename.replace(' ', '_')
    filename = ''.join(c for c in filename if c.isalnum() or c in '_-')
    return filename


def process_single_pdf(pdf_path, output_base_folder, resume_dir=None):
    """处理单个PDF文件
    
    Args:
        pdf_path (str): PDF文件路径
        output_base_folder (str): 输出基础目录
        resume_dir (str, optional): 恢复中断工作的目录路径
    """
    config = Config()
    try:
        # 创建带有净化的PDF基本名称的输出文件夹
        base_name = sanitize_filename(os.path.splitext(os.path.basename(pdf_path))[0])
        output_folder = os.path.join(output_base_folder, base_name)
        os.makedirs(output_folder, exist_ok=True)

        # 如果尚未完成，复制原始PDF
        if not os.path.exists(os.path.join(output_folder, os.path.basename(pdf_path))) and not resume_dir:
            shutil.copy2(pdf_path, output_folder)

        # 在恢复模式下，检查是否需要重新进行PDF转图片
        log_file = os.path.join(output_folder, 'pdf2md.log')
        need_convert = True
        if resume_dir and os.path.exists(log_file):
            logger.info(f'发现日志文件：{log_file}')
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
                if "Conversion completed" in log_content:
                    need_convert = False

        # 如果需要，将PDF转换为图像
        if need_convert:
            logger.info(f'正在将 {pdf_path} 转换为图像...')
            images = convert_pdf_to_images(pdf_path, config.dpi)  # 使用配置的DPI
            save_images_with_progress(images, output_folder)

            # 记录转换日志
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"PDF: {pdf_path}\n")
                f.write(f"Total pages: {len(images)}\n")
                f.write("Conversion completed\n")

        # 将图片处理为markdown
        logger.info('正在处理图像生成markdown...')
        image_files = natsorted(glob.glob(f'{output_folder}/*.png'))
        md_content = ""
        need_translate = False
        ocr_error_count = 0  # 添加OCR错误计数

        for img in image_files:
            img_name = os.path.basename(img)
            md_file = os.path.join(output_folder, f"{os.path.splitext(img_name)[0]}.md")

            # 检查是否需要重新处理该页面
            need_process = True
            if os.path.exists(md_file):
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content and len(content) > 0:  # 如果文件不为空
                        need_process = False
                        md_content += content + '\n\n'
                        logger.info(f'使用现有markdown: {img_name}')
                    else:
                        os.remove(md_file)  # 删除空的markdown文件
                        logger.info(f'删除空的markdown文件: {img_name}')

            if need_process:
                logger.info(f'处理 {img_name}...')
                try:
                    text_content = perform_ocr(img)
                    if text_content is None:  # OCR失败
                        logger.error(f"OCR失败: {img_name}")
                        ocr_error_count += 1
                        continue  # 跳过此图像的后续处理
                    
                    markdown_output = format_to_markdown(text_content, img)

                    if markdown_output:
                        # 保存单个页面的markdown
                        with open(md_file, 'w', encoding='utf-8') as f:
                            f.write(markdown_output)
                        md_content += markdown_output + '\n\n'
                        need_translate = True  # 只要有过处理痕迹，就需要翻译
                except Exception as e:
                    logger.error(f"处理 {img} 时出错: {e}")
                    ocr_error_count += 1
                    if os.path.exists(md_file):
                        os.remove(md_file)
                    continue  # 捕获异常后继续处理下一个图像，而不是直接引发异常

        # 检查是否所有页面都OCR失败
        if ocr_error_count == len(image_files):
            logger.error(f"所有页面OCR都失败，跳过后续处理: {pdf_path}")
            # 将output_folder重命名为：{output_folder}_ocr_failed
            new_folder_name = f'{output_folder}_ocr_failed'
            new_folder_path = os.path.join(output_base_folder, new_folder_name)
            os.rename(output_folder, new_folder_path)
            return False
            
        # 如果md_content为空，跳过后续处理
        if not md_content.strip():
            logger.warning(f"没有有效的Markdown内容，跳过后续处理: {pdf_path}")
            # 将output_folder重命名为：{output_folder}_no_content
            new_folder_name = f'{output_folder}_no_content'
            new_folder_path = os.path.join(output_base_folder, new_folder_name)
            os.rename(output_folder, new_folder_path)
            return False

        # 分析招生信息
        logger.info('分析招生信息...')
        info = analyze_admission_info(md_content)
        if info is None:
            # 将output_folder重命名为：{output_folder}_can_not_analyze
            new_folder_name = f'{output_folder}_can_not_analyze'
            new_folder_path = os.path.join(output_base_folder, new_folder_name)
            os.rename(output_folder, new_folder_path)
            logger.warning(f'无法分析: {output_folder}, 跳过...')
            return False
        else:
            try:
                info_dict = json.loads(info)
                new_folder_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
                new_folder_path = os.path.join(output_base_folder, new_folder_name)
                base_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")

                # 不论是否是恢复模式，都会重新拼装和保存日语版markdown文件
                md_path = os.path.join(output_folder, f'{base_name}.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)

                # 检查是否需要重新翻译
                zh_md_path = os.path.join(output_folder, f'{base_name}_中文.md')
                if os.path.exists(zh_md_path):
                    logger.info(f'找到中文版本: {zh_md_path}, 比较行数...')
                    # 比较中文版和日文版的行数
                    with open(zh_md_path, 'r', encoding='utf-8') as f:
                        zh_lines = len([line for line in f if line.strip()])
                    jp_lines = len([line for line in md_content.split('\n') if line.strip()])

                    # 计算行数差异百分比
                    line_diff_percent = abs(zh_lines - jp_lines) / max(zh_lines + 1, jp_lines + 1) * 100
                    if line_diff_percent > 15:
                        logger.info(f'中文版与日文版行数差异超过15%（{line_diff_percent:.1f}%），需要重新翻译')
                        need_translate = True
                    else:
                        logger.info(f'中文版与日文版行数差异在允许范围内（{line_diff_percent:.1f}%），无需重新翻译')
                else:
                    need_translate = True

                # 如果需要，翻译为中文
                if need_translate:
                    logger.info('翻译为中文...')
                    zh_content = translate_markdown(md_content)
                    if zh_content:
                        with open(zh_md_path, 'w', encoding='utf-8') as f:
                            f.write(zh_content)

                # 重命名文件夹和PDF
                os.rename(output_folder, new_folder_path)
                old_pdf = os.path.join(new_folder_path, os.path.basename(pdf_path))
                new_pdf = os.path.join(new_folder_path, f"{base_name}.pdf")
                os.rename(old_pdf, new_pdf)

                return True
            except Exception as e:
                logger.error(f"处理招生信息时出错: {e}")
                return False

    except Exception as e:
        logger.error(f"处理PDF时出错: {e}")
        return False


def workflow(pdf_folder=None, resume_dir=None):
    load_dotenv(override=True)
    config = Config()

    if resume_dir:
        logger.info(f'恢复模式：{resume_dir}')
        # 在恢复模式下，直接使用resume_dir作为输出目录
        output_folder = resume_dir
        # 获取所有一级子目录
        subdirs = [d for d in os.listdir(resume_dir) if os.path.isdir(os.path.join(resume_dir, d))]

        logger.info(f'找到 {len(subdirs)} 个目录需要处理')
        processed_dirs = 0
        valid_handbooks = 0
        total_pages = 0

        for subdir in subdirs:
            subdir_path = os.path.join(resume_dir, subdir)
            logger.info(f'\n处理目录: {subdir}...')

            # 查找该目录下的PDF文件
            pdf_files = [f for f in os.listdir(subdir_path) if f.endswith('.pdf')]
            if not pdf_files:
                logger.warning(f'在 {subdir} 中未找到PDF文件，跳过...')
                continue

            # 统计页面数（通过PNG文件数量）
            total_pages += len([f for f in os.listdir(subdir_path) if f.endswith('.png')])

            pdf_path = os.path.join(subdir_path, pdf_files[0])  # 只处理这个文件夹下第一个（理论上是唯一的）的PDF文件
            # 处理这个PDF文件，包括具体的resume逻辑也都在这里
            if process_single_pdf(pdf_path, output_folder, resume_dir=resume_dir):
                valid_handbooks += 1
            processed_dirs += 1

            logger.info(f'进度: {processed_dirs}/{len(subdirs)} 个目录已处理')

        logger.info('\n处理完成:')
        logger.info(f'总共处理的目录数: {processed_dirs}')
        logger.info(f'有效手册数: {valid_handbooks}')
        logger.info(f'总共处理的页面数: {total_pages}')
        logger.info(f'输出文件夹: {output_folder}')

    else:
        # 正常模式的原有逻辑
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_folder = f"pdf_with_md_{timestamp}"
        os.makedirs(output_folder, exist_ok=True)

        # 获取所有PDF文件
        pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
        total_pdfs = len(pdf_files)
        processed_pdfs = 0
        valid_handbooks = 0
        total_pages = 0

        logger.info(f'找到 {total_pdfs} 个PDF文件')

        for pdf_path in pdf_files:
            logger.info(f'\n处理 {os.path.basename(pdf_path)}...')
            images = convert_pdf_to_images(pdf_path, config.dpi)  # 使用配置的DPI
            total_pages += len(images)

            if process_single_pdf(pdf_path, output_folder):
                valid_handbooks += 1
            processed_pdfs += 1

            logger.info(f'进度: {processed_pdfs}/{total_pdfs} 个PDF已处理，找到 {valid_handbooks} 个有效手册')

        logger.info('\n处理完成:')
        logger.info(f'总共处理的PDF数: {processed_pdfs}')
        logger.info(f'有效手册数: {valid_handbooks}')
        logger.info(f'总共处理的页面数: {total_pages}')
        logger.info(f'输出文件夹: {output_folder}')


def review_workflow(output_folder):
    """检查并修复已处理的结果目录
    
    Args:
        output_folder (str): 包含处理结果的目录路径
    """
    load_dotenv(override=True)
    config = Config()  # 创建Config实例

    # 获取所有子目录（大学文件夹）
    subdirs = [d for d in os.listdir(output_folder) if os.path.isdir(os.path.join(output_folder, d))]

    # 处理统计
    total_dirs = len(subdirs)
    processed_dirs = 0
    regenerated_md = 0
    regenerated_translations = 0
    translation_line_diff_issues = 0  # 新增：统计行数差异问题

    logger.info(f'\n开始检查 {total_dirs} 个处理结果目录...')

    for subdir in subdirs:
        processed_dirs += 1
        subdir_path = os.path.join(output_folder, subdir)
        logger.info(f'\n检查目录 ({processed_dirs}/{total_dirs}): {subdir}')

        # 查找相关文件
        pdf_files = [f for f in os.listdir(subdir_path) if f.endswith('.pdf')]
        md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
        zh_md_files = [f for f in os.listdir(subdir_path) if f.endswith('中文.md')]

        if not pdf_files:
            logger.warning(f'警告：目录 {subdir} 中未找到PDF文件，跳过处理')
            continue

        pdf_path = os.path.join(subdir_path, pdf_files[0])

        # 检查日文md文件
        needs_md_regeneration = True
        jp_line_count = 0
        if md_files:
            md_path = os.path.join(subdir_path, md_files[0])
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
                jp_lines = md_content.split('\n')
                jp_line_count = len(jp_lines)
                if jp_line_count >= 10:  # 仍然保留最小行数检查
                    needs_md_regeneration = False

        # 如果需要重新生成日文md
        if needs_md_regeneration:
            logger.info('重新生成日文Markdown文件...')
            # 转换PDF到图片
            images = convert_pdf_to_images(pdf_path, config.dpi)

            # 保存图片
            for i, image in enumerate(images):
                image.save(os.path.join(subdir_path, f'scan_{i}.png'), 'PNG')

            # 处理图片生成markdown
            md_content = ""
            image_files = natsorted(glob.glob(f'{subdir_path}/*.png'))

            for img in image_files:
                logger.info(f'处理图片 {os.path.basename(img)}...')
                text_content = perform_ocr(img)
                markdown_output = format_to_markdown(text_content, img)
                if markdown_output:
                    md_content += markdown_output + '\n\n'

            # 保存新的markdown文件
            if md_content:
                new_md_path = os.path.join(subdir_path, f'{os.path.splitext(pdf_files[0])[0]}.md')
                with open(new_md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                regenerated_md += 1
                # 更新日文行数
                jp_line_count = len(md_content.split('\n'))
            else:
                logger.warning('警告：无法生成Markdown内容')
                continue

        # 检查中文md文件
        needs_translation = True
        if zh_md_files and jp_line_count > 0:  # 确保有日文文件作为参考
            zh_md_path = os.path.join(subdir_path, zh_md_files[0])
            with open(zh_md_path, 'r', encoding='utf-8') as f:
                zh_content = f.read()
                zh_line_count = len(zh_content.split('\n'))

                # 计算行数差异百分比
                line_diff_percentage = abs(zh_line_count - jp_line_count) / jp_line_count * 100

                if line_diff_percentage <= 20:  # 允许20%的行数差异
                    needs_translation = False
                else:
                    logger.warning(f'中文译文行数差异过大：日文 {jp_line_count} 行，中文 {zh_line_count} 行，差异 {line_diff_percentage:.1f}%')
                    translation_line_diff_issues += 1

        # 如果需要重新翻译
        if needs_translation:
            logger.info('重新生成中文翻译...')
            # 读取最新的日文md内容
            current_md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
            if not current_md_files:
                logger.warning('警告：未找到日文Markdown文件，跳过翻译')
                continue

            md_path = os.path.join(subdir_path, current_md_files[0])
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

            # 执行翻译
            zh_content = translate_markdown(md_content)
            if zh_content:
                # 保存翻译结果
                zh_md_path = os.path.join(subdir_path, f'{os.path.splitext(current_md_files[0])[0]}_中文.md')
                with open(zh_md_path, 'w', encoding='utf-8') as f:
                    f.write(zh_content)
                regenerated_translations += 1
            else:
                logger.warning('警告：翻译失败')

        # 清理临时图片文件
        for img in glob.glob(f'{subdir_path}/scan_*.png'):
            os.remove(img)

    # 生成报告
    logger.info('\n=== Review 处理报告 ===')
    logger.info(f'检查的目录总数: {total_dirs}')
    logger.info(f'重新生成的日文Markdown文件数: {regenerated_md}')
    logger.info(f'重新生成的中文翻译文件数: {regenerated_translations}')
    logger.info(f'因行数差异过大重新翻译的文件数: {translation_line_diff_issues}')
    logger.info(f'处理完成的目录: {processed_dirs}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将PDF文件转换为Markdown格式并提取招生信息')
    parser.add_argument('dir', nargs='?', help='PDF文件目录路径（在非恢复模式下必需）')
    parser.add_argument('--resume', help='恢复之前中断的工作，指定输出目录路径')
    args = parser.parse_args()

    if args.resume:
        if not os.path.isdir(args.resume):
            logger.error(f'错误: 恢复目录 {args.resume} 不是一个目录')
            sys.exit(1)
        workflow(resume_dir=args.resume)
    else:
        if not args.dir:
            logger.error('错误: 在正常模式下需要提供PDF目录')
            sys.exit(1)
        if not os.path.isdir(args.dir):
            logger.error(f'错误: {args.dir} 不是一个目录')
            sys.exit(1)
        workflow(args.dir)
