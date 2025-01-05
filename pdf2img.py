import os
import sys
import time
import shutil
from pdf2image import convert_from_path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def convert_pdf_to_images(pdf_file, dpi):
    """将PDF文件转换为图片列表
    参数:
        pdf_file: PDF文件路径
        dpi: 输出图片的DPI值
    返回:
        转换后的图片列表
    """
    images = convert_from_path(pdf_file, dpi=dpi)
    return images

def check_conversion_success(output_folder):
    """检查转换是否成功（是否生成了png文件）"""
    return any(f.lower().endswith('.png') for f in os.listdir(output_folder))

def save_chunk(chunk_images, output_folder, start_idx, progress_bar):
    """保存一组图片到指定文件夹"""
    for j, image in enumerate(chunk_images):
        image.save(os.path.join(output_folder, f'scan_{start_idx + j}.png'), 'PNG')
        progress_bar.update(1)

def save_images_with_progress(images, output_folder):
    """多线程保存图片，显示进度条
    返回: None
    """
    total_pages = len(images)
    print(f'总页数: {total_pages}')
    
    max_workers = max(1, os.cpu_count() - 1)
    print(f'使用 {max_workers} 个线程进行转换')

    chunk_size = (total_pages + max_workers - 1) // max_workers
    chunks = [images[i:i + chunk_size] for i in range(0, total_pages, chunk_size)]

    futures = []
    progress_bars = [tqdm(total=len(chunk), desc=f'线程 {i+1}', position=i, ncols=80) 
                    for i, chunk in enumerate(chunks)]
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i, chunk in enumerate(chunks):
                futures.append(executor.submit(save_chunk, chunk, output_folder, 
                                            i * chunk_size, progress_bars[i]))
            
            for future in as_completed(futures):
                future.result()
    finally:
        for progress_bar in progress_bars:
            progress_bar.close()

    print(f'已保存到文件夹: {output_folder}')

def process_single_pdf(pdf_path, output_base_folder, dpi):
    """处理单个PDF文件
    返回: (bool, str) - (是否成功, 错误信息)
    """
    try:
        # 创建输出文件夹
        output_folder = os.path.join(output_base_folder, 
            os.path.splitext(os.path.basename(pdf_path))[0] + time.strftime('%Y%m%d%H%M%S'))
        os.mkdir(output_folder)
        
        # 复制原PDF文件
        shutil.copy2(pdf_path, output_folder)
        
        # 转换PDF到图片
        images = convert_pdf_to_images(pdf_path, dpi)
        
        # 保存图片
        save_images_with_progress(images, output_folder)
        
        # 检查转换结果
        return check_conversion_success(output_folder), None
            
    except Exception as e:
        return False, str(e)

def print_report(total_pdfs, successful_conversions, failed_conversions):
    """打印转换报告"""
    print("\n=== PDF转换报告 ===")
    print(f"总PDF文件数: {total_pdfs}")
    print(f"成功转换数: {successful_conversions}")
    print(f"失败转换数: {len(failed_conversions)}")
    
    if failed_conversions:
        print("\n失败的PDF文件:")
        for failed_pdf in failed_conversions:
            print(f"- {failed_pdf}")

def process_pdf_folder(pdf_folder, dpi):
    """处理指定文件夹中的所有PDF文件"""
    # 获取所有PDF文件
    pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"在 {pdf_folder} 中未找到PDF文件")
        return
        
    total_pdfs = len(pdf_files)
    print(f"找到 {total_pdfs} 个PDF文件")

    output_base_folder = os.path.join(".", "pdf2img_" + time.strftime('%Y%m%d%H%M%S'))
    os.mkdir(output_base_folder)
    
    # 统计变量
    successful_conversions = 0
    failed_conversions = []
    
    # 处理每个PDF文件
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_folder, pdf_file)
        print(f'正在转换 {pdf_path} (DPI: {dpi})...')
        
        success, error = process_single_pdf(pdf_path, output_base_folder, dpi)
        if success:
            successful_conversions += 1
        else:
            if error:
                print(f"转换错误: {error}")
            failed_conversions.append(pdf_file)
    
    print_report(total_pdfs, successful_conversions, failed_conversions)

if __name__ == '__main__':
    pdf_folder = "./download_20250105_011016"
    dpi = 100

    process_pdf_folder(pdf_folder, dpi)
