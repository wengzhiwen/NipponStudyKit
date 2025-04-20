# pylint: disable=invalid-name
'''
将PDF文件转换为Markdown格式、翻译并提取招生信息

使用方法：
python 03_pdf2img2md_make_index.py [pdf_folder] [--resume resume_dir]

'''
import json
import os
import sys
import shutil
import glob
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import time  # 添加在文件开头的导入部分

from pdf2image import convert_from_path
from tqdm import tqdm
from dotenv import load_dotenv
import google.generativeai as genai
from google.cloud import vision
from PIL import Image
from natsort import natsorted
from autogen import ConversableAgent, LLMConfig, initiate_swarm_chat, AfterWorkOption


class ServiceConfig:
    """配置类，用于管理所有配置信息"""

    def __init__(self):
        load_dotenv()

        # 加载LLM配置文件路径
        self.llm_config_path = os.getenv("LLM_CONFIG_PATH", "config/llm_config.json")

        # 检查配置文件是否存在
        if not os.path.exists(self.llm_config_path):
            raise FileNotFoundError(f"LLM配置文件不存在: {self.llm_config_path}")

        # 加载LLM配置
        self.llm_config = self.load_config("MINI")
        self.llm_config_mini = self.load_config("LOW_COST")

    def load_config(self, model_tag: str = "STD") -> LLMConfig:
        """从配置文件加载LLM配置"""
        filter_dict = {"tags": [model_tag]}
        return LLMConfig.from_json(path=self.llm_config_path).where(**filter_dict)


def set_google_cloud_api_key_json():
    if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
        if os.path.exists(os.environ['GOOGLE_APPLICATION_CREDENTIALS']):
            return

    print('The specified GOOGLE_APPLICATION_CREDENTIALS file does not exist.')
    print('Load from local .env settings...')

    google_auth_json_path = os.getenv('GOOGLE_ACCOUNT_KEY_JSON')

    if google_auth_json_path is not None and os.path.exists(google_auth_json_path):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = google_auth_json_path
        print(f'Set GOOGLE_APPLICATION_CREDENTIALS to {google_auth_json_path}')
        return

    print(f'The GOOGLE_ACCOUNT_KEY_JSON file: {google_auth_json_path} does not exist.')
    print('Cannot load GOOGLE_APPLICATION_CREDENTIALS file.')
    sys.exit(1)


def convert_pdf_to_images(pdf_file, dpi):
    """Convert PDF file to list of images"""
    images = convert_from_path(pdf_file, dpi=dpi)
    return images


def save_images_with_progress(images, output_folder):
    """Save images with multi-threading and progress bars"""
    total_pages = len(images)
    print(f'Total pages: {total_pages}')

    max_workers = max(1, os.cpu_count() - 1)
    print(f'Using {max_workers} threads for conversion')

    chunk_size = (total_pages + max_workers - 1) // max_workers
    chunks = [images[i:i + chunk_size] for i in range(0, total_pages, chunk_size)]

    progress_bars = [tqdm(total=len(chunk), desc=f'Thread {i+1}', position=i, ncols=80) for i, chunk in enumerate(chunks)]

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


def ocr_by_google_cloud(image_path):
    """Perform OCR using Google Cloud Vision API"""
    client = vision.ImageAnnotatorClient()
    print("OCR by Google Vision")

    try:
        with open(image_path, 'rb') as image_file:
            content = image_file.read()
    except Exception as e:
        print(f"Error reading image file: {e}")
        return None

    try:
        image = vision.Image(content=content)
        # pylint: disable=no-member
        response = client.document_text_detection(image=image)
        time.sleep(10)  # OCR 后暂停10秒
        if response.error.message:
            raise Exception(f'Google Cloud API Error: {response.error.message}')
        return response.full_text_annotation.text
    except Exception as e:
        print(f"Error during OCR: {e}")
        raise e


def format_to_markdown_ref_image(text_content, image_path):
    """Format OCR text to markdown using Gemini"""
    genai.configure()
    model = genai.GenerativeModel(os.getenv('GEMINI_MODEL_FOR_FORMAT_MD', 'gemini-1.5-flash'))
    print(f"Format OCR text to markdown by: {os.getenv('GEMINI_MODEL_FOR_FORMAT_MD', 'gemini-1.5-flash')}")

    try:
        prompt = f"""请将我提供的文本重新组织成 Markdown 格式。
请参考我提供的图片进行格式化，文本内容是这个图片OCR的结果，我希望通过Markdown格式尽可能还原图片中的格式。

文本内容：

{text_content}

------
以上是所有的文本内容，你可以开始格式化了。

请注意：
1. 保持文本的含义和结构
2. 如果文本中包含标题、段落等结构信息，请在 Markdown 中保留
3. 如果有页头、页脚，请忽略它们
4. 输出完整的 Markdown 格式文本，不要使用```系列的定界符，因为输出内容将会被直接保存为.md文件
5. 如果文本中包含大量的无意义的信息（往往是图片的OCR结果），请忽略它们
6. 如果遇到空白页（或整页都是没有意义的内容），请返回：EMPTY_PAGE
"""

        img = Image.open(image_path)
        contents = [prompt, img]

        response = model.generate_content(contents)
        return response.text.replace('```markdown\n', '').replace('```', '\n')
    except Exception as e:
        print(f"Error formatting to markdown: {e}")
        return None


def translate_markdown(md_content: str) -> str:
    """使用 autogen agent 翻译 markdown 内容"""

    config = ServiceConfig()

    # 配置翻译 agent
    translator_agent = ConversableAgent(
        name="Translator_Agent",
        llm_config=config.llm_config,
        human_input_mode="NEVER",
        description="日语翻译专家",
        system_message="""你是一位专业的日语翻译专家，擅长将日语文本翻译成中文。
请将用户输入的日语Markdown文本翻译成中文，要求：
1. 保持原有的Markdown格式
2. 翻译要准确、通顺，符合中文表达习惯
3. 专业术语要准确翻译
4. 直接返回翻译结果，不需要其他解释
5. 忠实翻译全文！不要有任何遗漏！

请注意：
- 不要在输出内容前后添加```markdown之类的标记，因为你的输出结果会直接被保存为.md文件
- 不要进行寒暄，直接开始翻译
- 不要添加任何额外的说明性文字
- 翻译结果的行数应该和原文差不多""",
    )

    # 准备翻译提示
    translate_prompt = f"""请将以下日语Markdown文本翻译成中文：

{md_content}

请直接返回翻译结果。"""

    # 用当前的日期时间来命名重定向
    output_file = f"translate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.stdout.log"
    # 保存原始的stdout
    old_stdout = sys.stdout

    # 执行翻译
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            sys.stdout = f
            chat_result, _, _ = initiate_swarm_chat(initial_agent=translator_agent,
                                                    agents=[translator_agent],
                                                    messages=translate_prompt,
                                                    after_work=AfterWorkOption.TERMINATE,
                                                    max_rounds=2)

            # 获取翻译结果
            return chat_result.chat_history[-1]["content"]
    finally:
        # 恢复原始的stdout
        sys.stdout = old_stdout


def analyze_admission_info(md_content):
    """Analyze admission information using Gemini"""

    config = ServiceConfig()

    analyze_agent = ConversableAgent(
        name="Analyze_Agent",
        llm_config=config.llm_config,
        human_input_mode="NEVER",
        description="大学招生信息分析专家",
        system_message="""你是一位专业的大学招生信息分析专家，擅长分析大学招生信息。
请根据用户输入的Markdown文本进行分析并提取以下信息，以JSON格式返回。

请严格按照以下JSON格式返回（注意：必须是合法的JSON格式，不要添加任何其他说明文字）：
{
    "大学名称": "大学的日语名称",
    "报名截止日期": "YYYY/MM/DD格式，如果有多个日期选择最晚的，无法确认则返回2099/01/01",
    "学校简介": "1-3句话描述，包含QS排名（如果有）",
    "学校地址": "〒000-0000格式的邮编+详细地址"
}""",
    )

    prompt = md_content + "\n\n请确保返回的是合法的JSON格式，不要包含任何其他说明文字。"

    # 用当前的日期时间来命名重定向
    output_file = f"analyze_{datetime.now().strftime('%Y%m%d_%H%M%S')}.stdout.log"
    # 保存原始的stdout
    old_stdout = sys.stdout
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            sys.stdout = f
            chat_result, _, _ = initiate_swarm_chat(initial_agent=analyze_agent,
                                                agents=[analyze_agent],
                                                messages=prompt,
                                                after_work=AfterWorkOption.TERMINATE,
                                                max_rounds=2)

            # 获取分析结果
            text = chat_result.chat_history[-1]["content"]
    except Exception as e:
        print(f"Error analyzing admission info: {e}")
        return None
    finally:
        # 恢复原始的stdout
        sys.stdout = old_stdout

    # Try to parse as JSON to validate format
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        # If not valid JSON, try to extract JSON part
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            # Validate extracted JSON
            json.loads(json_str)
            return json_str
        else:
            print(f"Could not extract valid JSON from response: {text}")
            return None


def sanitize_filename(filename):
    """Sanitize filename by replacing invalid characters"""
    # Replace slashes in date with dashes
    filename = filename.replace('/', '-')
    # Replace spaces and other special characters
    filename = filename.replace(' ', '_')
    filename = ''.join(c for c in filename if c.isalnum() or c in '_-')
    return filename


def process_single_pdf(pdf_path, output_base_folder, resume_dir=None):
    """Process a single PDF file
    
    Args:
        pdf_path (str): PDF文件路径
        output_base_folder (str): 输出基础目录
        resume_dir (str, optional): 恢复中断工作的目录路径
    """
    try:
        # Create output folder with sanitized PDF basename
        base_name = sanitize_filename(os.path.splitext(os.path.basename(pdf_path))[0])
        output_folder = os.path.join(output_base_folder, base_name)
        os.makedirs(output_folder, exist_ok=True)

        # Copy original PDF if not already done
        if not os.path.exists(os.path.join(output_folder, os.path.basename(pdf_path))) and not resume_dir:
            shutil.copy2(pdf_path, output_folder)

        # 在恢复模式下，检查是否需要重新进行PDF转图片
        log_file = os.path.join(output_folder, 'pdf2md.log')
        need_convert = True
        if resume_dir and os.path.exists(log_file):
            print(f'发现日志文件：{log_file}')
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
                if "Conversion completed" in log_content:
                    need_convert = False

        # Convert PDF to images if needed
        if need_convert:
            print(f'Converting {pdf_path} to images...')
            images = convert_pdf_to_images(pdf_path, 100)
            save_images_with_progress(images, output_folder)

            # 记录转换日志
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"PDF: {pdf_path}\n")
                f.write(f"Total pages: {len(images)}\n")
                f.write("Conversion completed\n")

        # Process images to markdown
        print('Processing images to markdown...')
        image_files = natsorted(glob.glob(f'{output_folder}/*.png'))
        md_content = ""
        need_translate = False

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
                        print(f'Using existing markdown for {img_name}')
                    else:
                        os.remove(md_file)  # 删除空的markdown文件
                        print(f'Removing empty markdown file for {img_name}')

            if need_process:
                print(f'Processing {img_name}...')
                try:
                    text_content = ocr_by_google_cloud(img)
                    markdown_output = format_to_markdown_ref_image(text_content, img)

                    if markdown_output:
                        # 保存单个页面的markdown
                        with open(md_file, 'w', encoding='utf-8') as f:
                            f.write(markdown_output)
                        md_content += markdown_output + '\n\n'
                        need_translate = True  # 只要有过处理痕迹，就需要翻译
                except Exception as e:
                    print(f"Error processing {img}: {e}")
                    if os.path.exists(md_file):
                        os.remove(md_file)
                    raise e

        # Analyze admission info
        print('Analyzing admission information...')
        info = analyze_admission_info(md_content)
        if info is None:
            # 将output_folder重命名为：{output_folder}_can_not_analyze
            new_folder_name = f'{output_folder}_can_not_analyze'
            new_folder_path = os.path.join(output_base_folder, new_folder_name)
            os.rename(output_folder, new_folder_path)
            print(f'Can not analyze: {output_folder}, skip...')
            return False
        else:
            try:
                info_dict = json.loads(info)
                new_folder_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
                new_folder_path = os.path.join(output_base_folder, new_folder_name)
                base_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")

                # 不论是否是否是恢复模式，都会重新拼装和保存日语版markdown文件
                md_path = os.path.join(output_folder, f'{base_name}.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)

                # 检查是否需要重新翻译
                zh_md_path = os.path.join(output_folder, f'{base_name}_中文.md')
                if os.path.exists(zh_md_path):
                    print(f'Found Chinese version: {zh_md_path}, compare lines...')
                    # 比较中文版和日文版的行数
                    with open(zh_md_path, 'r', encoding='utf-8') as f:
                        zh_lines = len([line for line in f if line.strip()])
                    jp_lines = len([line for line in md_content.split('\n') if line.strip()])

                    # 计算行数差异百分比
                    line_diff_percent = abs(zh_lines - jp_lines) / max(zh_lines + 1, jp_lines + 1) * 100
                    if line_diff_percent > 15:
                        print(f'中文版与日文版行数差异超过15%（{line_diff_percent:.1f}%），需要重新翻译')
                        need_translate = True
                    else:
                        print(f'中文版与日文版行数差异在允许范围内（{line_diff_percent:.1f}%），无需重新翻译')
                else:
                    need_translate = True

                # Translate to Chinese if needed
                if need_translate:
                    print('Translating to Chinese...')
                    zh_content = translate_markdown(md_content)
                    if zh_content:
                        with open(zh_md_path, 'w', encoding='utf-8') as f:
                            f.write(zh_content)

                # Rename folder and PDF
                os.rename(output_folder, new_folder_path)
                old_pdf = os.path.join(new_folder_path, os.path.basename(pdf_path))
                new_pdf = os.path.join(new_folder_path, f"{base_name}.pdf")
                os.rename(old_pdf, new_pdf)

                return True
            except Exception as e:
                print(f"Error processing admission info: {e}")
                return False

    except Exception as e:
        print(f"Error processing PDF: {e}")
        return False


def generate_index_csv(output_folder):
    """Generate index.csv file from processed markdown files"""
    index_rows = []

    # Get all subdirectories (university folders)
    subdirs = [d for d in os.listdir(output_folder) if os.path.isdir(os.path.join(output_folder, d))]

    for subdir in subdirs:
        subdir_path = os.path.join(output_folder, subdir)

        # Find the markdown file (not Chinese version)
        md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
        if not md_files:
            continue

        md_path = os.path.join(subdir_path, md_files[0])

        # Read and analyze markdown content
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

            info = analyze_admission_info(md_content)
            if info == "NO":
                continue

            info_dict = json.loads(info)

            # Create one entry per university
            folder_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
            base_name = folder_name  # Same as folder name for files

            row = [
                f"{folder_name}/{base_name}.pdf",  # pdf_path
                f"{folder_name}/{base_name}.md",  # md_path
                f"{folder_name}/{base_name}_中文.md",  # zh_md_path
                info_dict['大学名称'],  # university_name
                info_dict['报名截止日期'],  # deadline
                info_dict['学校地址'],  # address
                info_dict['学校简介']  # description
            ]
            index_rows.append(row)

        except Exception as e:
            print(f"Error processing {md_path}: {e}")
            continue

    # Write index.csv
    if index_rows:
        index_path = os.path.join(output_folder, 'index.csv')
        with open(index_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(['pdf_path', 'md_path', 'zh_md_path', 'university_name', 'deadline', 'address', 'description'])
            writer.writerows(sorted(index_rows, key=lambda x: x[3]))  # Sort by university name
        print(f"Generated index.csv with {len(index_rows)} entries")
    else:
        print("No valid entries found for index.csv")


def workflow(pdf_folder=None, resume_dir=None):
    load_dotenv(override=True)

    # Setup Google Cloud credentials
    set_google_cloud_api_key_json()

    if resume_dir:
        print(f'恢复模式：{resume_dir}')
        # 在恢复模式下，直接使用resume_dir作为输出目录
        output_folder = resume_dir
        # 获取所有一级子目录
        subdirs = [d for d in os.listdir(resume_dir) if os.path.isdir(os.path.join(resume_dir, d))]

        print(f'Found {len(subdirs)} directories to process')
        processed_dirs = 0
        valid_handbooks = 0
        total_pages = 0

        for subdir in subdirs:
            subdir_path = os.path.join(resume_dir, subdir)
            print(f'\nProcessing directory: {subdir}...')

            # 查找该目录下的PDF文件
            pdf_files = [f for f in os.listdir(subdir_path) if f.endswith('.pdf')]
            if not pdf_files:
                print(f'No PDF file found in {subdir}, skipping...')
                continue
            
            # 统计页面数（通过PNG文件数量）
            total_pages += len([f for f in os.listdir(subdir_path) if f.endswith('.png')])

            pdf_path = os.path.join(subdir_path, pdf_files[0])  # 只处理这个文件夹下第一个（理论上是唯一的）的PDF文件
            # 处理这个PDF文件，包括具体的resume逻辑也都在这里
            if process_single_pdf(pdf_path, output_folder, resume_dir=resume_dir):
                valid_handbooks += 1
            processed_dirs += 1

            print(f'Progress: {processed_dirs}/{len(subdirs)} directories processed')

        print('\nProcessing completed:')
        print(f'Total directories processed: {processed_dirs}')
        print(f'Valid handbooks found: {valid_handbooks}')
        print(f'Total pages processed: {total_pages}')
        print(f'Output folder: {output_folder}')

    else:
        # 正常模式的原有逻辑
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_folder = f"pdf_with_md_{timestamp}"
        os.makedirs(output_folder, exist_ok=True)

        # Get all PDF files
        pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
        total_pdfs = len(pdf_files)
        processed_pdfs = 0
        valid_handbooks = 0
        total_pages = 0

        print(f'Found {total_pdfs} PDF files')

        for pdf_path in pdf_files:
            print(f'\nProcessing {os.path.basename(pdf_path)}...')
            images = convert_pdf_to_images(pdf_path, 100)
            total_pages += len(images)

            if process_single_pdf(pdf_path, output_folder):
                valid_handbooks += 1
            processed_pdfs += 1

            print(f'Progress: {processed_pdfs}/{total_pdfs} PDFs processed, {valid_handbooks} valid handbooks found')

        print('\nProcessing completed:')
        print(f'Total PDFs processed: {processed_pdfs}')
        print(f'Valid handbooks found: {valid_handbooks}')
        print(f'Total pages processed: {total_pages}')
        print(f'Output folder: {output_folder}')

    # Generate index.csv
    generate_index_csv(output_folder)


def review_workflow(output_folder):
    """检查并修复已处理的结果目录
    
    Args:
        output_folder (str): 包含处理结果的目录路径
    """
    load_dotenv(override=True)
    set_google_cloud_api_key_json()

    # 获取所有子目录（大学文件夹）
    subdirs = [d for d in os.listdir(output_folder) if os.path.isdir(os.path.join(output_folder, d))]

    # 处理统计
    total_dirs = len(subdirs)
    processed_dirs = 0
    regenerated_md = 0
    regenerated_translations = 0
    translation_line_diff_issues = 0  # 新增：统计行数差异问题

    print(f'\n开始检查 {total_dirs} 个处理结果目录...')

    for subdir in subdirs:
        processed_dirs += 1
        subdir_path = os.path.join(output_folder, subdir)
        print(f'\n检查目录 ({processed_dirs}/{total_dirs}): {subdir}')

        # 查找相关文件
        pdf_files = [f for f in os.listdir(subdir_path) if f.endswith('.pdf')]
        md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
        zh_md_files = [f for f in os.listdir(subdir_path) if f.endswith('中文.md')]

        if not pdf_files:
            print(f'警告：目录 {subdir} 中未找到PDF文件，跳过处理')
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
            print('重新生成日文Markdown文件...')
            # 转换PDF到图片
            images = convert_pdf_to_images(pdf_path, 100)

            # 保存图片
            for i, image in enumerate(images):
                image.save(os.path.join(subdir_path, f'scan_{i}.png'), 'PNG')

            # 处理图片生成markdown
            md_content = ""
            image_files = natsorted(glob.glob(f'{subdir_path}/*.png'))

            for img in image_files:
                print(f'处理图片 {os.path.basename(img)}...')
                text_content = ocr_by_google_cloud(img)
                markdown_output = format_to_markdown_ref_image(text_content, img)
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
                print('警告：无法生成Markdown内容')
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
                    print(f'中文译文行数差异过大：日文 {jp_line_count} 行，中文 {zh_line_count} 行，差异 {line_diff_percentage:.1f}%')
                    translation_line_diff_issues += 1

        # 如果需要重新翻译
        if needs_translation:
            print('重新生成中文翻译...')
            # 读取最新的日文md内容
            current_md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
            if not current_md_files:
                print('警告：未找到日文Markdown文件，跳过翻译')
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
                print('警告：翻译失败')

        # 清理临时图片文件
        for img in glob.glob(f'{subdir_path}/scan_*.png'):
            os.remove(img)

    # 重新生成 index.csv
    print('\n重新生成 index.csv...')
    generate_index_csv(output_folder)

    # 生成报告
    print('\n=== Review 处理报告 ===')
    print(f'检查的目录总数: {total_dirs}')
    print(f'重新生成的日文Markdown文件数: {regenerated_md}')
    print(f'重新生成的中文翻译文件数: {regenerated_translations}')
    print(f'因行数差异过大重新翻译的文件数: {translation_line_diff_issues}')
    print(f'处理完成的目录: {processed_dirs}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将PDF文件转换为Markdown格式并提取招生信息')
    parser.add_argument('dir', nargs='?', help='PDF文件目录路径（在非恢复模式下必需）')
    parser.add_argument('--resume', help='恢复之前中断的工作，指定输出目录路径')
    args = parser.parse_args()

    if args.resume:
        if not os.path.isdir(args.resume):
            print(f'Error: Resume directory {args.resume} is not a directory')
            sys.exit(1)
        workflow(resume_dir=args.resume)
    else:
        if not args.dir:
            print('Error: PDF directory is required in normal mode')
            sys.exit(1)
        if not os.path.isdir(args.dir):
            print(f'Error: {args.dir} is not a directory')
            sys.exit(1)
        workflow(args.dir)
