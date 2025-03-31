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
        img = Image.open(image_path)
        contents = [
            "请参考以下图片的内容，将我提供的文本重新组织成 Markdown 格式。", img, f"文本内容：\n\n{text_content}", "\n\n请注意保持文本的含义，并根据图片内容调整格式和排版风格。", "如果页面有明显的页头、页脚，请忽略页头和页脚的文字。",
            "如果文本中包含标题、段落等结构信息，请尽量在 Markdown 中保留。", "请输出完整的 Markdown 格式文本，除非遇到源代码否则输出内容不要出现```系列的定界符。"
        ]
        response = model.generate_content(contents)
        return response.text.replace('```markdown\n', '').replace('```', '\n')
    except Exception as e:
        print(f"Error formatting to markdown: {e}")
        return None


def split_markdown_by_headers(text_content, chunk_size=1000):
    """将 Markdown 文本按照标题进行智能切割
    
    Args:
        text_content (str): Markdown 格式的文本内容
        chunk_size (int): 每个块的目标行数
        
    Returns:
        list: 切割后的文本块列表
    """
    lines = text_content.split('\n')
    if len(lines) <= chunk_size:
        return [text_content]

    chunks = []
    current_chunk = []
    current_size = 0

    # 用于判断是否为标题行的函数
    def is_header(line):
        stripped = line.strip()
        return stripped.startswith('#')

    def get_header_level(line):
        return len(line) - len(line.lstrip('#'))

    for i, line in enumerate(lines):
        current_chunk.append(line)
        current_size += 1

        # 当当前块接近目标大小时，寻找下一个合适的切割点
        if current_size >= chunk_size:
            # 向后查找最近的标题作为切割点
            look_ahead = min(100, len(lines) - i - 1)  # 向后最多看100行
            best_split_index = i + 1
            min_header_level = 6

            for j in range(i + 1, i + look_ahead + 1):
                if j >= len(lines):
                    break
                if is_header(lines[j]):
                    header_level = get_header_level(lines[j])
                    if header_level <= min_header_level:
                        min_header_level = header_level
                        best_split_index = j
                        if header_level <= 2:  # 如果找到 H1 或 H2，立即使用该切割点
                            break

            # 如果找到了合适的切割点
            if best_split_index > i:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
                continue

        # 如果这是最后一行
        if i == len(lines) - 1 and current_chunk:
            chunks.append('\n'.join(current_chunk))

    return chunks


def translate_markdown(text_content):
    """Translate markdown to Chinese using Gemini"""
    genai.configure()
    model = genai.GenerativeModel(os.getenv('GEMINI_MODEL_FOR_TRANSLATE', 'gemini-1.5-flash'))
    print(f"Translate by: {os.getenv('GEMINI_MODEL_FOR_TRANSLATE', 'gemini-1.5-flash')}")

    try:
        # 将文本分割成多个块
        text_chunks = split_markdown_by_headers(text_content)
        translated_chunks = []

        print(f"文本已被分割成 {len(text_chunks)} 个块进行翻译")

        for i, chunk in enumerate(text_chunks, 1):
            print(f"正在翻译第 {i}/{len(text_chunks)} 个块...")

            # 为每个块添加上下文信息
            context = []
            if i > 1:
                # 如果不是第一个块，添加前文衔接提示
                context.append("这是文档的续翻部分，请确保与前文翻译风格保持一致。")

            if i < len(text_chunks):
                # 如果不是最后一个块，添加后文衔接提示
                context.append("这是文档的中间部分，请确保留意与后文的衔接。")

            contents = [
                "你是优秀的日中翻译专家，擅长翻译日本留学相关的信息。", "请将我提供的 Markdown 格式文本翻译成中文。", f"文本内容：\n\n{chunk}", "\n\n以上是待翻译的Markdown内容。",
                "请注意保持文本的含义，并核对原稿尽可能保持和原稿一致的Markdown格式。", "请输出完整的翻译后的 Markdown 格式文本，除非遇到源代码否则输出内容不要出现```系列的定界符。"
            ]

            # 添加上下文信息
            if context:
                contents.extend(context)

            response = model.generate_content(contents)
            chunk_translation = response.text.replace('```markdown\n', '').replace('```', '\n')

            if chunk_translation:
                translated_chunks.append(chunk_translation)
            else:
                print(f"警告：第 {i} 个块翻译失败")
                return None

        # 合并所有翻译后的块
        return '\n\n'.join(translated_chunks)

    except Exception as e:
        print(f"Error on translating markdown: {e}")
        return None


def analyze_admission_info(md_content):
    """Analyze admission information using Gemini"""
    genai.configure()
    model = genai.GenerativeModel(os.getenv('GEMINI_MODEL_FOR_ORG_INFO', 'gemini-1.5-pro'))
    print(f"Analyze admission information by: {os.getenv('GEMINI_MODEL_FOR_ORG_INFO', 'gemini-1.5-pro')}")

    prompt = '''请用中文回答我的问题：
        提示词最后添付的文本是根据从大学官网下载的原始PDF文件OCR成的markdown版本。
        首先确认，这是不是包含该大学的本科（学部）私费留学生的招生信息（募集要项）。
        如果不是的话，请返回"NO"。
        如果是的话，请分析并提取以下信息，以JSON格式返回。
        
        请严格按照以下JSON格式返回（注意：必须是合法的JSON格式，不要添加任何其他说明文字）：
        {
            "大学名称": "大学的日语名称",
            "报名截止日期": "YYYY/MM/DD格式，如果有多个日期选择最晚的，无法确认则返回2099/01/01",
            "学校简介": "1-3句话描述，包含QS排名（如果有）",
            "学校地址": "〒000-0000格式的邮编+详细地址"
        }
        
        以下是添付的markdown内容：\n\n'''

    prompt = prompt + md_content + "\n\n请确保返回的是合法的JSON格式，不要包含任何其他说明文字。"

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()

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
                return "NO"
    except Exception as e:
        print(f"Error analyzing admission info: {e}")
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

        # 检查是否需要恢复工作
        if resume_dir:
            resume_folder = os.path.join(resume_dir, base_name)
            if os.path.exists(resume_folder):
                # 复制已存在的文件
                for item in os.listdir(resume_folder):
                    src = os.path.join(resume_folder, item)
                    dst = os.path.join(output_folder, item)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)

        # 检查是否需要重新进行PDF转图片
        log_file = os.path.join(output_folder, 'pdf2md.log')
        need_convert = True
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
                if f"PDF: {pdf_path}" in log_content and "Conversion completed" in log_content:
                    need_convert = False

        # Copy original PDF if not already done
        if not os.path.exists(os.path.join(output_folder, os.path.basename(pdf_path))):
            shutil.copy2(pdf_path, output_folder)

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
                    if content:  # 如果文件不为空
                        need_process = False
                        md_content += content + '\n\n'
                    else:
                        os.remove(md_file)  # 删除空的markdown文件

            if need_process:
                print(f'Processing {img_name}...')
                try:
                    text_content = ocr_by_google_cloud(img)
                    time.sleep(10)  # 每次OCR后暂停10秒
                    markdown_output = format_to_markdown_ref_image(text_content, img)

                    if markdown_output:
                        # 保存单个页面的markdown
                        with open(md_file, 'w', encoding='utf-8') as f:
                            f.write(markdown_output)
                        md_content += markdown_output + '\n\n'
                        need_translate = True
                except Exception as e:
                    print(f"Error processing {img}: {e}")
                    # 如果处理失败，删除可能存在的空markdown文件
                    if os.path.exists(md_file):
                        os.remove(md_file)
                    raise e

        # Analyze admission info
        print('Analyzing admission information...')
        info = analyze_admission_info(md_content)
        if info == "NO":
            print(f'Not an admission handbook, removing folder: {output_folder}')
            shutil.rmtree(output_folder)
            return False
        else:
            try:
                info_dict = json.loads(info)
                new_folder_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
                new_folder_path = os.path.join(output_base_folder, new_folder_name)
                base_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")

                # Save markdown content
                md_path = os.path.join(output_folder, f'{base_name}.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)

                # 检查是否需要重新翻译
                zh_md_path = os.path.join(output_folder, f'{base_name}_中文.md')
                if os.path.exists(zh_md_path):
                    # 比较中文版和日文版的行数
                    with open(zh_md_path, 'r', encoding='utf-8') as f:
                        zh_lines = len([line for line in f if line.strip()])
                    jp_lines = len([line for line in md_content.split('\n') if line.strip()])

                    # 计算行数差异百分比
                    line_diff_percent = abs(zh_lines - jp_lines) / max(zh_lines, jp_lines) * 100
                    if line_diff_percent > 15:
                        print(f'中文版与日文版行数差异超过15%（{line_diff_percent:.1f}%），需要重新翻译')
                        need_translate = True
                    else:
                        print(f'中文版与日文版行数差异在允许范围内（{line_diff_percent:.1f}%），无需重新翻译')

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


def rename_folders(output_folder):
    """Rename folders and files based on university name and deadline"""
    # Get all subdirectories (university folders)
    subdirs = [d for d in os.listdir(output_folder) if os.path.isdir(os.path.join(output_folder, d))]

    for subdir in subdirs:
        subdir_path = os.path.join(output_folder, subdir)
        md_files = [f for f in os.listdir(subdir_path) if f.endswith('.md') and not f.endswith('中文.md')]
        if not md_files:
            continue

        md_path = os.path.join(subdir_path, md_files[0])
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()

            info = analyze_admission_info(md_content)
            if info == "NO":
                continue

            info_dict = json.loads(info)
            new_folder_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
            new_folder_path = os.path.join(output_folder, new_folder_name)

            if subdir_path != new_folder_path:
                # Rename folder
                os.rename(subdir_path, new_folder_path)
                print(f"Renamed folder: {subdir} -> {new_folder_name}")

                # Rename files inside the folder
                base_name = sanitize_filename(f"{info_dict['大学名称']}_{info_dict['报名截止日期']}")
                for file in os.listdir(new_folder_path):
                    if file.endswith('.pdf'):
                        old_path = os.path.join(new_folder_path, file)
                        new_path = os.path.join(new_folder_path, f"{base_name}.pdf")
                        os.rename(old_path, new_path)
                    elif file.endswith('.md') and not file.endswith('中文.md'):
                        old_path = os.path.join(new_folder_path, file)
                        new_path = os.path.join(new_folder_path, f"{base_name}.md")
                        os.rename(old_path, new_path)
                    elif file.endswith('中文.md'):
                        old_path = os.path.join(new_folder_path, file)
                        new_path = os.path.join(new_folder_path, f"{base_name}_中文.md")
                        os.rename(old_path, new_path)

        except Exception as e:
            print(f"Error renaming {subdir}: {e}")
            continue


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


def workflow(pdf_folder, resume_dir=None):
    load_dotenv(override=True)

    # Setup Google Cloud credentials
    set_google_cloud_api_key_json()

    # Create output folder with timestamp
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
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

        if process_single_pdf(pdf_path, output_folder, resume_dir):
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
    parser.add_argument('dir', help='目录路径')
    parser.add_argument('--review', action='store_true', help='启用review模式，检查并修复已处理的结果')
    parser.add_argument('--resume', help='恢复之前中断的工作，指定输出目录路径')
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f'Error: {args.dir} is not a directory')
        sys.exit(1)

    if args.review:
        review_workflow(args.dir)
    else:
        workflow(args.dir, args.resume)
