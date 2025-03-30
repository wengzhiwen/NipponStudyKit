'''
通过browser_use库，使用gpt-4o-mini模型，获取日本大学的募集要项文件
'''
import datetime
import threading
from typing import List
import os
import asyncio
import argparse
from concurrent.futures import ThreadPoolExecutor
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from browser_use.agent.service import Agent
from browser_use.controller.service import Controller
from browser_use.browser.browser import Browser

import dotenv
from loguru import logger


class Pdf(BaseModel):
    university_name: str
    title: str
    url: str


class Pdfs(BaseModel):
    pdfs: List[Pdf]
    save_path: str = f"./pdfs_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv"

    def __init__(self, **data):
        super().__init__(**data)
        self._save_lock = threading.Lock()

    def save(self):
        with self._save_lock:
            # 将Pdfs对象中的内容保存到./pdfs_datetime.csv文件中
            with open(self.save_path, "w", encoding="utf-8") as output_file:
                for pdf in self.pdfs:
                    output_file.write(f"{pdf.university_name},{pdf.title},{pdf.url}\n")

    def add_pdf(self, university_name, title, url):
        with self._save_lock:
            # 检查url是否已经存在
            for pdf in self.pdfs:
                if pdf.url == url:
                    return

            pdf = Pdf(university_name=university_name, title=title, url=url)
            self.pdfs.append(pdf)
            logger.info(f"Add pdf: title={title}, url={url}")


# 构建一个Pdfs对象，用于保存找到的募集要项文件的信息
pdfs = Pdfs(pdfs=[])

controller = Controller()


@controller.action("Save Pdfs", param_model=Pdfs)
def save_pdfs(params: Pdfs):
    '''
    保存找到的募集要项文件的信息
    '''
    try:
        for pdf in params.pdfs:
            pdfs.add_pdf(pdf.university_name, pdf.title, pdf.url)
        pdfs.save()
    except Exception as e:
        logger.error(e)


dotenv.load_dotenv()
model = ChatOpenAI(
    model="openai/gpt-4o-mini",  # 经过测试，gpt-4o-mini模型的性价比最好
    api_key=SecretStr(os.getenv('OPENROUTER_API_KEY')),
    base_url=os.getenv('OPENROUTER_END_POINT'),
    default_headers={
        "HTTP-Referer": "https://james.wengs.net",
        "X-Title": "Browser-use",
    },
)


async def main(university_name: str, headless: bool = False):
    task = (f"Googleで{university_name}の2026年度（令和8年度）の学部の私費外国人留学生選抜の募集要項と関連するトップ５のPDFドキュメントを探してくれ。", "探したPDFのURLは正しいかどうか（ダウンロードできる、４０３・４０４なし）を確認してくれ、OKの場合：",
            f"該当大学の名（{university_name}）及び関連するPDFドキュメントのタイトルと該当PDFのURL（掲載しているページのURLではなく）を保存してくれ（Save Pdfs）。",
            "PDFドキュメントは１つだけでもいい。該当大学の学部の私費外国人留学生選抜の募集要項があったら、タスクを終了してくれ。", "連続して同じPDFドキュメントが見つかったら、検索を中止してくれ。")

    logger.debug(f"Task: {task[:50]}")

    browser = Browser()
    browser.config.headless = headless
    agent = Agent(task, model, browser, controller=controller, use_vision=True)
    try:
        _ = await asyncio.wait_for(agent.run(max_steps=15), timeout=300)
    except Exception as e:
        logger.error(e)
    finally:
        try:
            await browser.close()
        except Exception as e:
            logger.error(f"Error on close agent: {e}")


def run_main(university_name, headless: bool = False):
    asyncio.run(main(university_name, headless))


def parse_args():
    parser = argparse.ArgumentParser(description='获取日本大学的募集要项文件')
    parser.add_argument('university_list_csv', help='输入的大学列表文件路径')
    parser.add_argument('--max-schools', type=int, default=5000, help='最大处理学校数量（默认：5000）')
    parser.add_argument('--max-threads', type=int, default=15, help='最大线程数（默认：15）')
    parser.add_argument('--output', help='输出PDF信息的文件路径（默认：自动生成）')
    parser.add_argument('--headless', action='store_true', help='启用浏览器headless模式')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.output:
        pdfs.save_path = args.output

    # 读取学校列表文件，将每一行的内容作为一个任务，调用main函数
    with ThreadPoolExecutor(max_workers=args.max_threads) as executor:
        with open(args.input_csv, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                try:
                    if i >= args.max_schools:
                        break

                    u_name, last_ad_date, last_ad_month = line.strip().split(",")

                    logger.info(f"process [{i+1}/{args.max_schools}] {u_name} @ {last_ad_month}")
                    t = executor.submit(run_main, u_name, args.headless)
                except Exception as e:
                    logger.error(e)
                    continue
