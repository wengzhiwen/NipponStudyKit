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
import time
import base64

from pdf2image import convert_from_path
from tqdm import tqdm
from dotenv import load_dotenv
from PIL import Image
from natsort import natsorted
from agents import Agent, Runner, function_tool


class Config:
    """配置类，用于管理所有配置信息"""

    def __init__(self):
        load_dotenv()
        # OpenAI API配置
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 环境变量未设置")
            
        # 模型配置
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.ocr_model = os.getenv("OPENAI_OCR_MODEL", "gpt-4o-mini")  # 默认使用更便宜的4o-mini进行OCR
        
        # PDF转图像DPI配置
        try:
            self.dpi = int(os.getenv("DPI", "150"))
        except ValueError:
            print("警告: DPI配置无效，使用默认值150")
            self.dpi = 150


def convert_pdf_to_images(pdf_file, dpi):
    """Convert PDF file to list of images"""
    images = convert_from_path(pdf_file, dpi=dpi)
    return images


def save_images_with_progress(images, output_folder):
    """Save images with multi-threading and progress bars"""
    total_pages = len(images)
    print(f'总页数: {total_pages}')

    max_workers = max(1, os.cpu_count() - 1)
    print(f'使用 {max_workers} 个线程进行转换')

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
    print("使用OpenAI Vision进行OCR...")
    config = Config()
    try:
        # 创建OCR代理
        ocr_agent = Agent(
            name="OCR Agent",
            instructions="""你是一个专业的OCR文本识别专家。
请仔细观察图像中的文本内容，并尽可能准确地提取所有文本和表格。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。

请注意：
1. 仅提取图像中的实际文本，不要添加任何解释或说明
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取表格中的所有文字
4. 忽略所有的纯图形内容（比如：logo，地图等）
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
        
        # 运行OCR代理
        result = Runner.run_sync(ocr_agent, {"role": "user", "content": [
            {"type": "text", "text": "请识别这个图像中的所有文字内容，保持原始格式。"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
        ]})
        
        if not result.final_output.strip():
            raise ValueError("OpenAI Vision未能提取任何文本")
            
        return result.final_output
    except Exception as e:
        print(f"OpenAI Vision OCR错误: {e}")
        return ""


def format_to_markdown(text_content, image_path):
    """使用OpenAI格式化OCR文本为markdown"""
    print("格式化OCR文本为markdown...")
    
    # 创建格式化代理
    format_agent = Agent(
        name="Markdown Formatter",
        instructions="""你是一个专业的文本格式化专家。
请将OCR出来的文本重新组织成Markdown格式。
输出应该保持原始文本的格式和结构，包括格式（加粗、斜体、下划线、表格）、段落和标题。

请注意：
1. 保持除非OCR结果有明显的识别错误，否则不要修改OCR结果，更不要添加任何解释或说明
2. 保持原始日语文本，不要翻译
3. 尽可能保持原始格式结构，特别是表格，要准确的提取不同的
4. OCR时已经要求忽略页眉、页脚，仅保留原文中的页码，请保持
5. OCR时已经要求忽略所有的纯图形内容（比如：logo，地图等），请保持；特别注意不要以Base64的编码来处理任何纯图形内容
6. 如果文本中包含大量无意义的信息，请删除他们
7. 如果有URL信息，请保持完整的URL信息，但不要用Markdown的链接格式来处理URL，保留纯文本状态即可
8. 如果遇到空白页或整页都是没有意义的内容，请返回：EMPTY_PAGE
""",
        model=Config().model
    )
    
    # 读取图像文件
    with open(image_path, 'rb') as f:
        image_data = f.read()
    
    # 编码图像为base64
    base64_image = base64.b64encode(image_data).decode('utf-8')
    
    # 运行格式化代理
    result = Runner.run_sync(format_agent, {"role": "user", "content": [
        {"type": "text", "text": f"请将以下OCR文本重新组织成Markdown格式：\n\n{text_content}"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
    ]})
    
    return result.final_output


def translate_markdown(md_content):
    """使用OpenAI翻译日语Markdown内容为中文"""
    print("翻译Markdown内容为中文...")
    
    # 创建翻译代理
    translator_agent = Agent(
        name="Translator",
        instructions="""你是一位专业的日语翻译专家，擅长将日语文本翻译成中文。
        请将用户输入的日语Markdown文本翻译成中文，要求：
        1. 保持原有的Markdown格式
        2. 翻译要准确、通顺，符合中文表达习惯
        3. 专业术语要准确翻译
        4. 不要添加任何额外的说明或注释
        5. 直接返回翻译结果，不需要其他解释
        """,
        model=Config().model
    )
    
    # 运行翻译代理
    result = Runner.run_sync(translator_agent, f"""请将以下日语Markdown文本翻译成中文：

{md_content}

请直接返回翻译结果。""")
    
    return result.final_output


def analyze_admission_info(md_content):
    """使用OpenAI分析招生信息"""
    print("分析招生信息...")
    
    # 创建分析代理
    analyze_agent = Agent(
        name="Admission Analyzer",
        instructions="""你是一位专业的大学招生信息分析专家，擅长分析大学招生信息。
        请根据输入的Markdown文本进行分析并提取以下信息，以JSON格式返回。
        
        请严格按照以下JSON格式返回（必须是合法的JSON格式，不要添加任何其他说明文字）：
        {
            "大学名称": "大学的日语名称",
            "报名截止日期": "YYYY/MM/DD格式，如果有多个日期选择最晚的，无法确认则返回2099/01/01",
            "学校简介": "1-3句话描述，包含QS排名（如果有）",
            "学校地址": "〒000-0000格式的邮编+详细地址"
        }
        """,
        model=Config().model
    )
    
    # 运行分析代理
    result = Runner.run_sync(analyze_agent, md_content + "\n\n请确保返回的是合法的JSON格式，不要包含任何其他说明文字。")
    
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
                print(f"无法提取有效的JSON: {result.final_output}")
                return None
        else:
            print(f"响应中没有有效的JSON: {result.final_output}")
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
            print(f'发现日志文件：{log_file}')
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
                if "Conversion completed" in log_content:
                    need_convert = False

        # 如果需要，将PDF转换为图像
        if need_convert:
            print(f'正在将 {pdf_path} 转换为图像...')
            images = convert_pdf_to_images(pdf_path, config.dpi)  # 使用配置的DPI
            save_images_with_progress(images, output_folder)

            # 记录转换日志
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"PDF: {pdf_path}\n")
                f.write(f"Total pages: {len(images)}\n")
                f.write("Conversion completed\n")

        # 将图片处理为markdown
        print('正在处理图像生成markdown...')
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
                        print(f'使用现有markdown: {img_name}')
                    else:
                        os.remove(md_file)  # 删除空的markdown文件
                        print(f'删除空的markdown文件: {img_name}')

            if need_process:
                print(f'处理 {img_name}...')
                try:
                    text_content = perform_ocr(img)
                    markdown_output = format_to_markdown(text_content, img)

                    if markdown_output:
                        # 保存单个页面的markdown
                        with open(md_file, 'w', encoding='utf-8') as f:
                            f.write(markdown_output)
                        md_content += markdown_output + '\n\n'
                        need_translate = True  # 只要有过处理痕迹，就需要翻译
                except Exception as e:
                    print(f"处理 {img} 时出错: {e}")
                    if os.path.exists(md_file):
                        os.remove(md_file)
                    raise e

        # 分析招生信息
        print('分析招生信息...')
        info = analyze_admission_info(md_content)
        if info is None:
            # 将output_folder重命名为：{output_folder}_can_not_analyze
            new_folder_name = f'{output_folder}_can_not_analyze'
            new_folder_path = os.path.join(output_base_folder, new_folder_name)
            os.rename(output_folder, new_folder_path)
            print(f'无法分析: {output_folder}, 跳过...')
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
                    print(f'找到中文版本: {zh_md_path}, 比较行数...')
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

                # 如果需要，翻译为中文
                if need_translate:
                    print('翻译为中文...')
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
                print(f"处理招生信息时出错: {e}")
                return False

    except Exception as e:
        print(f"处理PDF时出错: {e}")
        return False


def workflow(pdf_folder=None, resume_dir=None):
    load_dotenv(override=True)
    config = Config()

    if resume_dir:
        print(f'恢复模式：{resume_dir}')
        # 在恢复模式下，直接使用resume_dir作为输出目录
        output_folder = resume_dir
        # 获取所有一级子目录
        subdirs = [d for d in os.listdir(resume_dir) if os.path.isdir(os.path.join(resume_dir, d))]

        print(f'找到 {len(subdirs)} 个目录需要处理')
        processed_dirs = 0
        valid_handbooks = 0
        total_pages = 0

        for subdir in subdirs:
            subdir_path = os.path.join(resume_dir, subdir)
            print(f'\n处理目录: {subdir}...')

            # 查找该目录下的PDF文件
            pdf_files = [f for f in os.listdir(subdir_path) if f.endswith('.pdf')]
            if not pdf_files:
                print(f'在 {subdir} 中未找到PDF文件，跳过...')
                continue
            
            # 统计页面数（通过PNG文件数量）
            total_pages += len([f for f in os.listdir(subdir_path) if f.endswith('.png')])

            pdf_path = os.path.join(subdir_path, pdf_files[0])  # 只处理这个文件夹下第一个（理论上是唯一的）的PDF文件
            # 处理这个PDF文件，包括具体的resume逻辑也都在这里
            if process_single_pdf(pdf_path, output_folder, resume_dir=resume_dir):
                valid_handbooks += 1
            processed_dirs += 1

            print(f'进度: {processed_dirs}/{len(subdirs)} 个目录已处理')

        print('\n处理完成:')
        print(f'总共处理的目录数: {processed_dirs}')
        print(f'有效手册数: {valid_handbooks}')
        print(f'总共处理的页面数: {total_pages}')
        print(f'输出文件夹: {output_folder}')

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

        print(f'找到 {total_pdfs} 个PDF文件')

        for pdf_path in pdf_files:
            print(f'\n处理 {os.path.basename(pdf_path)}...')
            images = convert_pdf_to_images(pdf_path, config.dpi)  # 使用配置的DPI
            total_pages += len(images)

            if process_single_pdf(pdf_path, output_folder):
                valid_handbooks += 1
            processed_pdfs += 1

            print(f'进度: {processed_pdfs}/{total_pdfs} 个PDF已处理，找到 {valid_handbooks} 个有效手册')

        print('\n处理完成:')
        print(f'总共处理的PDF数: {processed_pdfs}')
        print(f'有效手册数: {valid_handbooks}')
        print(f'总共处理的页面数: {total_pages}')
        print(f'输出文件夹: {output_folder}')


def review_workflow(output_folder):
    """检查并修复已处理的结果目录
    
    Args:
        output_folder (str): 包含处理结果的目录路径
    """
    load_dotenv(override=True)

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
            images = convert_pdf_to_images(pdf_path, config.dpi)

            # 保存图片
            for i, image in enumerate(images):
                image.save(os.path.join(subdir_path, f'scan_{i}.png'), 'PNG')

            # 处理图片生成markdown
            md_content = ""
            image_files = natsorted(glob.glob(f'{subdir_path}/*.png'))

            for img in image_files:
                print(f'处理图片 {os.path.basename(img)}...')
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
            print(f'错误: 恢复目录 {args.resume} 不是一个目录')
            sys.exit(1)
        workflow(resume_dir=args.resume)
    else:
        if not args.dir:
            print('错误: 在正常模式下需要提供PDF目录')
            sys.exit(1)
        if not os.path.isdir(args.dir):
            print(f'错误: {args.dir} 不是一个目录')
            sys.exit(1)
        workflow(args.dir)
