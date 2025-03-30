import os
import random
import re
import csv
import time
import argparse
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional

import requests
import pandas as pd


class PDFDownloader:
    """PDF下载器，用于从CSV文件中提取URL并下载PDF文件"""

    def __init__(self, max_workers: int = 40):
        """
        初始化PDF下载器
        Args:
            max_workers: 最大线程数，默认为40
        """
        self.max_workers = max_workers
        self.download_dir = None
        self._browser_headers = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36'
        ]

    def _initialize_download_directory(self) -> str:
        """创建一个以当前时间命名的下载目录"""
        download_dir = os.path.join(os.getcwd(), f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(download_dir, exist_ok=True)
        self.download_dir = download_dir
        return download_dir

    def _validate_url(self, url: str) -> bool:
        """
        验证URL格式是否有效
        Args:
            url: 要验证的URL
        Returns:
            bool: URL格式是否有效
        """
        regex = re.compile(
            r'^(?:http|https)://'  # http:// 或 https://
            r'\w+(?:\.\w+)+',  # 域名
            re.IGNORECASE)
        return bool(re.match(regex, url))

    def _extract_url_from_row(self, row: List[str]) -> Optional[str]:
        """
        从CSV行数据中提取第一个有效的URL
        Args:
            row: CSV文件中的一行数据
        Returns:
            str or None: 找到的第一个有效URL，如果没有找到则返回None
        """
        for item in row:
            if isinstance(item, str) and self._validate_url(item):
                return item
        return None

    def _get_random_browser_header(self) -> str:
        """返回随机的浏览器User-Agent头信息"""
        return random.choice(self._browser_headers)

    def _download_single_pdf(self, identifier: str, url: str, save_dir: str) -> Tuple[bool, str, str]:
        """
        下载单个PDF文件并保存到指定目录
        Args:
            identifier: 文件标识符（通常是用户名或其他唯一标识）
            url: PDF文件的URL
            save_dir: 保存目录
        Returns:
            Tuple[bool, str, str]: (是否成功, 文件路径, 结果消息)
        """
        try:
            headers = {
                'User-Agent': self._get_random_browser_header(),
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

            session = requests.Session()
            time.sleep(random.uniform(1, 3))
            response = session.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            parsed_url = urlparse(url)
            pdf_filename = os.path.basename(parsed_url.path)
            if not pdf_filename.lower().endswith('.pdf'):
                pdf_filename += '.pdf'

            if len(pdf_filename) > 30:
                pdf_filename = identifier + pdf_filename[-30:]
            else:
                pdf_filename = identifier + pdf_filename

            pdf_file_path = os.path.join(save_dir, pdf_filename)
            while os.path.exists(pdf_file_path):
                random_num = str(random.randint(1000, 9999))
                pdf_filename = f"{random_num}_{pdf_filename}"
                pdf_file_path = os.path.join(save_dir, pdf_filename)

            with open(pdf_file_path, 'wb') as f:
                f.write(response.content)

            return True, pdf_filename, "200 OK"
        except requests.exceptions.RequestException as e:
            return False, "", str(e)

    def _process_csv_row(self, index: int, row: List[str], save_dir: str) -> Tuple[int, Tuple[str, str, str]]:
        """
        处理CSV中的单行数据：提取URL并下载PDF
        Args:
            index: 行索引
            row: CSV文件中的一行数据
            save_dir: 保存目录
        Returns:
            Tuple[int, Tuple[str, str, str]]: (行索引, (状态, 文件路径, 结果消息))
        """
        url = self._extract_url_from_row(row)
        if url:
            success, pdf_path, result = self._download_single_pdf(row[0], url, save_dir)
            if success:
                return index, ("Success", pdf_path, result)
            else:
                return index, ("Failed", "", result)
        else:
            return index, ("Failed", "", "No URL found")

    def batch_download_from_csv(self, csv_file_path: str) -> str:
        """
        从CSV文件中批量下载PDF文件
        Args:
            csv_file_path: CSV文件路径
        Returns:
            str: 下载报告文件路径
        """
        try:
            df = pd.read_csv(csv_file_path, dtype=str, header=None)
        except Exception as e:
            print(f"读取CSV文件时出错: {e}")
            return ""

        download_dir = self._initialize_download_directory()
        print(f"下载文件夹已创建: {download_dir}")

        rows = df.values.tolist()
        results = [("", "", "")] * len(rows)

        max_workers = min(self.max_workers, len(rows))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {executor.submit(self._process_csv_row, idx, row, download_dir): idx 
                             for idx, row in enumerate(rows)}

            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    _, download_result = future.result()
                    results[idx] = download_result
                    print(f"处理行 {idx + 1}/{len(rows)}: {download_result[0]}")
                except Exception as e:
                    results[idx] = ("Failed", "", str(e))
                    print(f"处理行 {idx + 1}/{len(rows)} 时出错: {e}")

        df['If_Success'] = [res[0] for res in results]
        df['File_Path'] = [res[1] for res in results]
        df['Result_Message'] = [res[2] for res in results]

        original_filename = os.path.basename(csv_file_path)
        report_filename = f"download_report_{original_filename}"
        report_file_path = os.path.join(download_dir, report_filename)

        try:
            df.to_csv(report_file_path, index=False, header=False, quoting=csv.QUOTE_ALL)
            print(f"下载报告: {report_file_path}")
            return report_file_path
        except Exception as e:
            print(f"创建下载报告时出错: {e}")
            return ""


def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(description='下载PDF文件并生成报告')
    parser.add_argument('csv_file', help='输入的CSV文件路径')
    parser.add_argument('--max-workers', type=int, default=40, help='最大线程数（默认：40）')
    args = parser.parse_args()

    downloader = PDFDownloader(max_workers=args.max_workers)
    downloader.batch_download_from_csv(args.csv_file)


if __name__ == "__main__":
    main()
