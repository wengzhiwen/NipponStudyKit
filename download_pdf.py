import os
import random
import re
import csv
import time
import requests
import pandas as pd
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

def create_download_folder():
    """创建一个以当前时间命名的临时文件夹"""
    temp_dir = os.path.join(os.getcwd(), f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def is_valid_url(url):
    """简单验证URL是否有效"""
    regex = re.compile(
        r'^(?:http|https)://'  # http:// 或 https://
        r'\w+(?:\.\w+)+',      # 域名
        re.IGNORECASE
    )
    return re.match(regex, url) is not None

def find_first_url(row):
    """在一行中找到第一个有效的URL"""
    for item in row:
        if isinstance(item, str) and is_valid_url(item):
            return item
    return None

def get_random_user_agent():
    """返回随机的User-Agent"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36'
    ]
    return random.choice(user_agents)

def download_pdf(u_name, url, save_dir):
    """下载PDF文件并保存到指定目录"""
    try:
        # 添加浏览器模拟的headers
        headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'DNT': '1'
        }
        
        # 创建session以处理cookies
        session = requests.Session()
        
        # 添加随机延迟(1-3秒)避免被检测为机器人
        time.sleep(random.uniform(1, 3))
        
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查请求是否成功

        # 验证Content-Type是否为PDF
        #content_type = response.headers.get('Content-Type', '')
        #if 'application/pdf' not in content_type:
        #    return False, "URL does not point to a PDF."

        # 从URL中提取文件名
        parsed_url = urlparse(url)
        pdf_filename = os.path.basename(parsed_url.path)
        if not pdf_filename.lower().endswith('.pdf'):
            pdf_filename += '.pdf'
        
        # 如果文件名过长，取最后30个字符
        if len(pdf_filename) > 30:
            pdf_filename = u_name + pdf_filename[-30:]
        else:
            pdf_filename = u_name + pdf_filename

        pdf_file_path = os.path.join(save_dir, pdf_filename)
        # 确认文件是否已经存在
        while os.path.exists(pdf_file_path):
            # 生成4位随机数
            random_num = str(random.randint(1000, 9999))
            # 在文件名前加上随机数
            pdf_filename = f"{random_num}_{pdf_filename}"
            pdf_file_path = os.path.join(save_dir, pdf_filename)

        with open(pdf_file_path, 'wb') as f:
            f.write(response.content)

        return True, pdf_filename, "200 OK"
    except requests.exceptions.RequestException as e:
        return False, "", str(e)

def process_row(index, row, save_dir):
    """处理单行数据：下载PDF并返回结果"""
    url = find_first_url(row)
    if url:
        success, pdf_path, result = download_pdf(row[0], url, save_dir)
        if success:
            return index, ("Success", pdf_path, result)
        else:
            return index, ("Failed", "", result)
    else:
        return index, ("Failed", "", "No URL found")

def main():
    pdf_url_csv_path = "./admissions_handbooks_url.csv"

    try:
        # 读取CSV时明确指定没有header
        df = pd.read_csv(pdf_url_csv_path, dtype=str, header=None)  # 以字符串形式读取所有数据
    except Exception as e:
        print(f"读取CSV文件时出错: {e}")
        return

    temp_dir = create_download_folder()
    print(f"下载文件夹已创建: {temp_dir}")

    rows = df.values.tolist()
    results = [("", "", "")] * len(rows) 

    # 使用多线程进行下载
    max_workers = min(40, len(rows))  # 最大线程不超过行数
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(process_row, idx, row, temp_dir): idx
            for idx, row in enumerate(rows)
        }

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                _, download_result = future.result()
                results[idx] = download_result
                print(f"处理行 {idx + 1}/{len(rows)}: {download_result[0]}")
            except Exception as e:
                results[idx] = ("Failed", "", e)
                print(f"处理行 {idx + 1}/{len(rows)} 时出错: {e}")
                try:
                    print(future.result())
                except:
                    print("无法输出完整的返回结果")

    df['If_Success'] = [res[0] for res in results]
    df['File_Path'] = [res[1] for res in results]
    df['Result_Message'] = [res[2] for res in results]

    original_filename = os.path.basename(pdf_url_csv_path)
    report_filename = f"download_report_{original_filename}"
    report_file_path = os.path.join(temp_dir, report_filename)

    try:
        # 写入CSV时不包含header
        df.to_csv(report_file_path, index=False, header=False, quoting=csv.QUOTE_ALL)
        print(f"下载报告: {report_file_path}")
    except Exception as e:
        print(f"Error on create download report: {e}")

if __name__ == "__main__":
    main()
