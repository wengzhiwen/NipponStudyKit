import glob
import os
import sys
import argparse
import time
from dotenv import load_dotenv
from google.cloud import vision
from google.auth.transport.requests import Request
import google.generativeai as genai
from google.oauth2 import service_account
from PIL import Image
from natsort import natsorted
import threading
from concurrent.futures import ThreadPoolExecutor

def translate_markdown(text_content, to_language, image_path):
    genai.configure()
    GEMINI_MODEL = 'gemini-1.5-pro-002'
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        print(f"Error occurred while loading the Gemini model: {e}")
        return None
    
    try:
        img = Image.open(image_path)
        contents = [
            "请将我提供的 Markdown 格式文本翻译成{}。".format(to_language),
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
        print(f"Error occurred while translating Markdown: {e}")
        return None

def format_to_markdown_ref_image(text_content, image_path):
    genai.configure()
    GEMINI_MODEL = os.getenv('GEMINI_MODEL_FOR_FORMAT_MD', 'gemini-1.5-flash')
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        print(f"Error occurred while loading the Gemini model: {e}")
        return None
    
    try:
        img = Image.open(image_path)
        contents = [
            "请参考以下图片的内容，将我提供的文本重新组织成 Markdown 格式。",
            img,
            f"文本内容：\n\n{text_content}",
            "请注意保持文本的含义，并根据图片内容调整格式和排版风格，例如：图片中有列表，你可以考虑将文本中的相关部分也组织成列表。",
            "如果文本中包含标题、段落等结构信息，请尽量在 Markdown 中保留。",
            "请输出完整的 Markdown 格式文本。"
        ]

        response = model.generate_content(contents)
        return response.text
    except Exception as e:
        print(f"Error occurred while formatting to markdown: {e}")
        return None

def ocr_by_google_cloud(image_path):
    #client_options = {'api_key': GOOGLE_CLOUD_API_KEY}
    client = vision.ImageAnnotatorClient()

    try:
        with open(image_path, 'rb') as image_path:
            content = image_path.read()
    except Exception as e:
        print(f"Error occurred while OCR image file: {e}")
        return None

    try:
        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)
    except Exception as e:
        print(f"Error occurred while calling Google Cloud API: {e}")
        raise e

    if response.error.message:
        raise Exception(
            'Google Cloud API Error: {}'.format(
                response.error.message
            )
        )
    else:
        return response.full_text_annotation.text

# 检查和设置 Google Cloud API Key json 文件
def set_google_cloud_api_key_json():
    # 检查os.environ['GOOGLE_APPLICATION_CREDENTIALS']是否已经设置
    if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
        # 检查设置的文件是否存在
        if os.path.exists(os.environ['GOOGLE_APPLICATION_CREDENTIALS']):
            return
    
    print('The specified GOOGLE_APPLICATION_CREDENTIALS file does not exist.')
    print('Load from local .env settings...')
    
    load_dotenv()
    GOOGLE_ACCOUNT_KEY_JSON = os.getenv('GOOGLE_ACCOUNT_KEY_JSON')
    
    # 检查GOOGLE_ACCOUNT_KEY_JSON设置的文件是否存在
    if GOOGLE_ACCOUNT_KEY_JSON is not None and os.path.exists(GOOGLE_ACCOUNT_KEY_JSON):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_ACCOUNT_KEY_JSON
        print('Set GOOGLE_APPLICATION_CREDENTIALS to {}'.format(GOOGLE_ACCOUNT_KEY_JSON))
        return
    
    print('The GOOGLE_ACCOUNT_KEY_JSON file: {} does not exist.'.format(GOOGLE_ACCOUNT_KEY_JSON))
    print('Cannot load GOOGLE_APPLICATION_CREDENTIALS file.')
    sys.exit(1)

def process_img_folder(img_folder, trans_to):
    images = natsorted(glob.glob(f'{img_folder}/*.png') + 
        glob.glob(f'{img_folder}/*.jpg') + 
        glob.glob(f'{img_folder}/*.jpeg'))
    
    if len(images) == 0:
        print(f"当前目录：{img_folder}，没有包含任何图片文件，跳过")
        return
    
    print(f'{len(images)} images to process...')
    
    set_google_cloud_api_key_json()
    
    output_file = os.path.join(img_folder ,f'{os.path.basename(img_folder)}_{int(time.time())}.md')

    # 如果指定了翻译语言，再创建一个临时文件保存翻译后的内容
    if trans_to:
        print(f'Translate to {trans_to}')
        output_file_trans = os.path.join(img_folder ,f'{os.path.basename(img_folder)}_{int(time.time())}_{trans_to}.md')
    
    try:
        with open(output_file, 'w') as f:
            if trans_to:
                with open(output_file_trans, 'w') as ft:
                    for img in images:
                        print(f'Processing {img_folder}: {images.index(img) + 1} / {len(images)}')
                        text_content = ocr_by_google_cloud(img)
                        markdown_output = format_to_markdown_ref_image(text_content, img)
                        if markdown_output:
                            f.write(markdown_output)
                            f.write('\n\n')
                        trans_output = translate_markdown(markdown_output, trans_to, img)
                        if trans_output:
                            ft.write(trans_output)
                            ft.write('\n\n')
            else:
                for img in images:
                    print(f'Processing {img_folder}: {images.index(img) + 1} / {len(images)}')
                    text_content = ocr_by_google_cloud(img)
                    markdown_output = format_to_markdown_ref_image(text_content, img)
                    if markdown_output:
                        f.write(markdown_output)
                        f.write('\n\n')
    except Exception as e:
        print(f"Error occurred while saving the Markdown file: {e}")
        sys.exit(1)

    print(f'Processing complete, saved to {output_file}')
    
    if trans_to:
        print(f'Translated doc saved to {output_file_trans}')

if __name__ == '__main__':
    img_folder_base = "./pdf2img_20250105050605"
    trans_to = "中文"
    
    # Get all first-level subdirectories
    subdirs = [d for d in glob.glob(f"{img_folder_base}/*") if os.path.isdir(d)]
    
    # Create a thread pool to process subdirectories
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit each directory to the thread pool
        futures = []
        for subdir in subdirs:
            print(f"Submitting directory: {subdir}")
            future = executor.submit(process_img_folder, subdir, trans_to)
            futures.append(future)
        
        # Wait for all tasks to complete
        for future in futures:
            future.result()
