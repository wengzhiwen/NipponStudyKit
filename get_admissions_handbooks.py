import asyncio
import datetime
import threading
from typing import List
import os
import dotenv
from loguru import logger
from concurrent.futures import ThreadPoolExecutor
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from browser_use.agent.service import Agent
from browser_use.controller.service import Controller
from browser_use.browser.browser import Browser

class Pdf(BaseModel):
    u_name: str
    title: str
    url: str

class Pdfs(BaseModel):
    pdfs: List[Pdf]
    save_path: str = "./pdfs_{}.csv".format(datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    
    def __init__(self, **data):
        super().__init__(**data)
        self._save_lock = threading.Lock()

    def save(self):
        with self._save_lock:
            # 将Pdfs对象中的内容保存到./pdfs_datetime.csv文件中
            with open(self.save_path, "w") as f:
                for pdf in self.pdfs:
                    f.write("{},{},{}\n".format(pdf.u_name, pdf.title, pdf.url))
    
    def add_pdf(self, u_name, title, url):
        with self._save_lock:
            # 检查url是否已经存在
            for pdf in self.pdfs:
                if pdf.url == url:
                    return
            
            pdf = Pdf(u_name=u_name, title=title, url=url)
            self.pdfs.append(pdf)
            logger.info("Add pdf: title={}, url={}".format(title, url))

# 构建一个Pdfs对象，用于保存找到的募集要项文件的信息
pdfs = Pdfs(pdfs=[])

controller = Controller()
@controller.action("Save Pdfs", param_model=Pdfs)
def save_Pdfs(params: Pdfs):
    try:
        for pdf in params.pdfs:
            pdfs.add_pdf(pdf.u_name, pdf.title, pdf.url)
        pdfs.save()
    except Exception as e:
        logger.error(e)

dotenv.load_dotenv()
model = ChatOpenAI(
    model="openai/gpt-4o-mini", # 经过测试，gpt-4o-mini模型的性价比最好
    api_key=SecretStr(os.getenv('OPENROUTER_API_KEY')),
    base_url=os.getenv('OPENROUTER_END_POINT'),
    default_headers={
        "HTTP-Referer": "https://github.com", 
        "X-Title": "Browser-use", 
    },
)

async def main(u_name: str):
    task = (
        "Googleで{}の2026年度（令和8年度）の学部の私費外国人留学生選抜の募集要項と関連するトップ５のPDFドキュメントを探してくれ。".format(
            u_name
        ),
        "探したPDFのURLは正しいかどうか（ダウンロードできる、４０３・４０４なし）を確認してくれ、OKの場合：",
        "該当大学の名（{}）及び関連するPDFドキュメントのタイトルと該当PDFのURL（掲載しているページのURLではなく）を保存してくれ（Save Pdfs）。".format(
            u_name
        ),
        "PDFドキュメントは１つだけでもいい。該当大学の学部の私費外国人留学生選抜の募集要項があったら、タスクを終了してくれ。",
        "連続して同じPDFドキュメントが見つかったら、検索を中止してくれ。"
    )
    
    logger.debug(f"Task: {task[:50]}")
    
    browser = Browser()
    browser.config.headless = False # 虽然说理论上支持headless模式，但我测试下来根本不靠谱
    agent = Agent(task, model, browser, controller=controller, use_vision=True)
    try:
        result = await asyncio.wait_for(agent.run(max_steps=15), timeout=300)
    except Exception as e:
        logger.error(e)
    finally:
        try:
            await browser.close()
        except Exception as e:
            logger.error(f"Error on close agent: {e}")

# 为了并发套的壳子
def run_main(u_name):
    asyncio.run(main(u_name))
    
if __name__ == "__main__":
    max_u = 5000 # 调试时使用，限制单次处理的任务数
    processed_u = 0
    max_threads = 15 # 看你的内存
    
    # 读取学校列表文件，将每一行的内容作为一个任务，调用main函数
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        with open("./u_list.csv", "r") as f:
            for line in f:
                try:                    
                    if processed_u >= max_u:
                        break
                    
                    u_name, last_ad_date, last_ad_month = line.strip().split(",")
                    
                    if last_ad_month in(4,5,6) or last_ad_month in ("04","05","06"):
                        logger.info("process {} @ {}".format(u_name, last_ad_month))
                        t = executor.submit(run_main, u_name)
                        processed_u += 1
                except Exception as e:
                    logger.error(e)
                    continue
