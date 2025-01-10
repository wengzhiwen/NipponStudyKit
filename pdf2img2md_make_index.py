import json
import os
import sys
import time
import shutil
import glob
import csv
from datetime import datetime
from pathlib import Path
from pdf2image import convert_from_path
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    load_dotenv()
    GOOGLE_ACCOUNT_KEY_JSON = os.getenv('GOOGLE_ACCOUNT_KEY_JSON')
    
    if GOOGLE_ACCOUNT_KEY_JSON is not None and os.path.exists(GOOGLE_ACCOUNT_KEY_JSON):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_ACCOUNT_KEY_JSON
        print('Set GOOGLE_APPLICATION_CREDENTIALS to {}'.format(GOOGLE_ACCOUNT_KEY_JSON))
        return
    
    print('The GOOGLE_ACCOUNT_KEY_JSON file: {} does not exist.'.format(GOOGLE_ACCOUNT_KEY_JSON))
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

    progress_bars = [tqdm(total=len(chunk), desc=f'Thread {i+1}', position=i, ncols=80) 
                    for i, chunk in enumerate(chunks)]
    
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

    try:
        with open(image_path, 'rb') as image_file:
            content = image_file.read()
    except Exception as e:
        print(f"Error reading image file: {e}")
        return None

    try:
        image = vision.Image(content=content)
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
    
    try:
        img = Image.open(image_path)
        contents = [
            "请参考以下图片的内容，将我提供的文本重新组织成 Markdown 格式。",
            img,
            f"文本内容：\n\n{text_content}",
            "请注意保持文本的含义，并根据图片内容调整格式和排版风格。",
            "如果文本中包含标题、段落等结构信息，请尽量在 Markdown 中保留。",
            "请输出完整的 Markdown 格式文本。"
        ]
        response = model.generate_content(contents)
        return response.text
    except Exception as e:
        print(f"Error formatting to markdown: {e}")
        return None

def translate_markdown(text_content, image_path):
    """Translate markdown to Chinese using Gemini"""
    genai.configure()
    model = genai.GenerativeModel('gemini-1.5-pro-002')
    
    try:
        img = Image.open(image_path)
        contents = [
            "请将我提供的 Markdown 格式文本翻译成中文。",
            f"文本内容：\n\n{text_content}",
            "同时提供上述文本内容的OCR前的原稿图片，以便更好地理解文本内容和格式。",
            img,
            "原稿图片仅供参考，翻译对象仍然是提供的文本内容。",
            "请注意保持文本的含义，并核对原稿尽可能保持和原稿一致的格式。",
            "请输出完整的翻译后的 Markdown 格式文本。"
        ]
        response = model.generate_content(contents)
        return response.text
    except Exception as e:
        print(f"Error translating markdown: {e}")
        return None

def analyze_admission_info(md_content):
    """Analyze admission information using Gemini"""
    genai.configure()
    model = genai.GenerativeModel(os.getenv('GEMINI_MODEL_FOR_ORG_INFO', 'gemini-1.5-pro'))
    
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
            "学校地址": "〒000-0000格式的邮编+详细地址",
            "学部和专业信息": [
                {
                    "学部名": "学部名称",
                    "专业名": "专业名称",
                    "招生人数": "招生人数",
                    "英语要求": "英语考试要求",
                    "EJU要求": "日本留学试验要求",
                    "面试要求": "面试相关要求"
                }
            ]
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

def process_single_pdf(pdf_path, output_base_folder, dpi=100):
    """Process a single PDF file"""
    try:
        # Create output folder with sanitized PDF basename
        base_name = sanitize_filename(os.path.splitext(os.path.basename(pdf_path))[0])
        output_folder = os.path.join(output_base_folder, base_name)
        os.makedirs(output_folder, exist_ok=True)
        
        # Copy original PDF
        shutil.copy2(pdf_path, output_folder)
        
        # Convert PDF to images
        print(f'Converting {pdf_path} to images...')
        images = convert_pdf_to_images(pdf_path, dpi)
        save_images_with_progress(images, output_folder)
        
        # Process images to markdown
        print(f'Processing images to markdown...')
        image_files = natsorted(glob.glob(f'{output_folder}/*.png'))
        
        md_content = ""
        for img in image_files:
            print(f'Processing {os.path.basename(img)}...')
            text_content = ocr_by_google_cloud(img)
            markdown_output = format_to_markdown_ref_image(text_content, img)
            if markdown_output:
                md_content += markdown_output + '\n\n'
        
        # Analyze admission info first to get the correct base name
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
                
                # Save markdown content with correct name
                md_path = os.path.join(output_folder, f'{base_name}.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                
                # Translate to Chinese
                print('Translating to Chinese...')
                zh_content = ""
                for img in image_files:
                    print(f'Processing {os.path.basename(img)}...')
                    trans_output = translate_markdown(md_content, img)
                    if trans_output:
                        zh_content += trans_output + '\n\n'
                
                # Save Chinese translation with correct name
                zh_md_path = os.path.join(output_folder, f'{base_name}_中文.md')
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
                f"{folder_name}/{base_name}_中文.md", # zh_md_path
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
            writer.writerow([
                'pdf_path',
                'md_path',
                'zh_md_path',
                'university_name',
                'deadline',
                'address',
                'description'
            ])
            writer.writerows(sorted(index_rows, key=lambda x: x[3]))  # Sort by university name
        print(f"Generated index.csv with {len(index_rows)} entries")
    else:
        print("No valid entries found for index.csv")

def main():
    # Setup Google Cloud credentials
    set_google_cloud_api_key_json()
    
    # Get input folder
    pdf_folder = "./pdf"
    if not os.path.exists(pdf_folder):
        print(f"PDF folder not found: {pdf_folder}")
        return
    
    # Create output folder
    current_time = datetime.now().strftime("%Y%m%d%H%M%S")
    output_folder = f"pdf_with_md_{current_time}"
    os.makedirs(output_folder, exist_ok=True)
    
    # Get all PDF files
    pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"No PDF files found in {pdf_folder}")
        return
    
    # Process statistics
    total_pdfs = len(pdf_files)
    processed_pdfs = 0
    total_pages = 0
    valid_handbooks = 0
    
    # Process each PDF
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_folder, pdf_file)
        print(f'\nProcessing: {pdf_file}')
        
        # Convert and process
        images = convert_pdf_to_images(pdf_path, 100)
        total_pages += len(images)
        
        if process_single_pdf(pdf_path, output_folder):
            valid_handbooks += 1
        processed_pdfs += 1
        
        print(f'Progress: {processed_pdfs}/{total_pdfs}')
    
    # Generate report
    print('\n=== Processing Report ===')
    print(f'Total PDF files processed: {total_pdfs}')
    print(f'Total pages converted: {total_pages}')
    print(f'Valid admission handbooks: {valid_handbooks}')
    print(f'Output folder: {output_folder}')
    
    # Generate index.csv
    print('\nGenerating index.csv...')
    generate_index_csv(output_folder)

if __name__ == '__main__':
    main()
