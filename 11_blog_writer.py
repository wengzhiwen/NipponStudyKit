import os
import re
import json
from datetime import datetime
from typing import Tuple, Optional
import sys
import argparse
from pathlib import Path

from agents import Agent, Runner, trace
from dotenv import load_dotenv
from logging_config import setup_logger

# 设置日志记录器
logger = setup_logger(logger_name="blog_writer", log_level="INFO")


class ServiceConfig:
    """配置类，用于管理所有配置信息"""

    def __init__(self):
        load_dotenv()

        # 加载模型配置
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.model_mini = os.getenv("OPENAI_MODEL_MINI", "gpt-4o-mini")

        # 检查配置信息
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY 环境变量未设置")
            raise ValueError("未设置OpenAI API密钥。请在.env文件中设置OPENAI_API_KEY环境变量。")

        logger.info(f'SETUP INFO = MODEL: {self.model}, MODEL_MINI: {self.model_mini}')


class UniversityUtils:

    def __init__(self):
        self.pdf_dirs = [d for d in os.listdir(".") if d.startswith("pdf_with_md")]
        self.university_list = None
        _ = self.get_university_list()

    def get_university_list(self) -> dict:
        """获取所有大学列表
        
        Returns:
            dict: 大学日文名到最新招生简章目录路径的映射
        """
        if hasattr(self, 'university_list') and self.university_list is not None and len(self.university_list) > 0:
            return self.university_list

        self.university_list = {}

        # 遍历所有pdf目录
        for pdf_dir in self.pdf_dirs:
            # 获取一级子目录
            for subdir in os.listdir(pdf_dir):
                subdir_path = Path(pdf_dir) / subdir
                if not subdir_path.is_dir():
                    continue

                # 检查必需文件是否存在
                required_files = [f"{subdir}.md", f"{subdir}_中文.md", f"{subdir}_report.md"]
                is_valid = all((subdir_path / f).exists() for f in required_files)
                if not is_valid:
                    continue

                # 解析目录名获取大学名和日期
                match = re.match(r"(.+)_(\d{4}[-]?\d{2}[-]?\d{2}|\d{8})", subdir)
                if not match:
                    continue

                univ_name = match.group(1)
                date_str = match.group(2)

                # 统一日期格式为yyyy-mm-dd
                if "-" not in date_str:
                    date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

                # 如果大学不在字典中，直接添加
                if univ_name not in self.university_list:
                    self.university_list[univ_name] = subdir_path
                    continue

                # 如果大学已在字典中，比较日期
                existing_path = self.university_list[univ_name]
                existing_match = re.match(r".+_(\d{4}[-]?\d{2}[-]?\d{2}|\d{8})", existing_path.name)
                if not existing_match:
                    # 如果已存在的目录名不合法，直接用新的替代
                    self.university_list[univ_name] = subdir_path
                    continue

                existing_date = existing_match.group(1)
                if "-" not in existing_date:
                    existing_date = f"{existing_date[:4]}-{existing_date[4:6]}-{existing_date[6:]}"

                # 比较日期，保留较新的
                if date_str > existing_date:
                    self.university_list[univ_name] = subdir_path

        return self.university_list

    def get_university_name_list_str(self) -> str:
        """获取所有大学日文名列表字符串（便于用于prompt）"""
        return "\n".join([k for k in self.university_list])

    def get_latest_admission_date(self, jp_name: str) -> Optional[str]:
        """获取指定大学最新的招生简章日期
        
        Args:
            jp_name (str): 大学日文名称
            
        Returns:
            Optional[str]: 最新的招生简章日期（yyyy-mm-dd格式），如果未找到则返回None
        """
        if jp_name not in self.university_list:
            return None

        path = self.university_list[jp_name]
        match = re.match(r".+_(\d{4}[-]?\d{2}[-]?\d{2}|\d{8})", path.name)
        if not match:
            return None

        date_str = match.group(1)
        # 统一日期格式为yyyy-mm-dd
        if "-" not in date_str:
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        return date_str

    def get_university_url(self, jp_name: str) -> Optional[str]:
        """获取大学对应的URL
        
        Args:
            jp_name (str): 大学日文名称
            
        Returns:
            Optional[str]: 大学URL，如果未找到则返回None
        """
        if jp_name not in self.university_list:
            return None

        latest_date = self.get_latest_admission_date(jp_name)
        if latest_date is None:
            return None

        return f"https://www.runjplib.com/university/{jp_name}/{latest_date}"


class ArticleWriter:

    LOG_DIR = Path("log")
    OUTPUT_DIR = Path("blogs")

    def __init__(self):
        # 初始化配置
        self.config = ServiceConfig()

        self.university_utils = UniversityUtils()
        self._init_workspace()

        self.article_writer: Optional[Agent] = None
        self.blog_formatter: Optional[Agent] = None

    def _init_agents(self):
        """初始化agents"""
        # 创建文章写作代理
        self.article_writer = Agent(name="article_writer",
                                   model=self.config.model,
                                   instructions="""你是一位专业的日本留学相关的文章的写作优化专家。
你的工作是：
1、根据用户输入的参考内容，重新进行组织和优化，使得文章内容更加轻松、易读
2、必要时根据你所掌握的日本留学相关的准确知识进行适当的补充
3、你所写的内容主要会被应用于留学相关网站的SEO，请务必确保文章内容对SEO友好
4、只有用户输入的参考内容中提到的大学，你才可以在输出中提及
5、记录下在你输出中提到的大学中文名称（全名）列表（大学中文全名、大学日文全名）
6、在文章的末尾添加一个"相关大学"的标题，列出上表中的中文全名
7、表格是很好的信息组织方式，如果需要，可以使用markdown的语法来表示表格

请以JSON格式返回结果，格式如下：
{
    "title": "文章标题",
    "content": "文章内容",
    "universities": [
        {
            "chinese_name": "大学中文名",
            "japanese_name": "大学日文名(日文全名，不是英文名)"
        }
    ]
}

注意：
 - 请不要对日本留学相关的内容进行任何推测，不要添加任何主观臆断
 - 输入的原文中可能存在一些留学咨询机构的广告（比如请咨询XXX，或是XXX位你提供服务），请不要在你输出的内容中保留任何的广告内容，特别是联系方式
 - 你撰写的文章中必须使用大学完整的中文名称
 - 不要在返回中带有```json 或是 ``` 这样的定界符
""")

        # 创建文章格式化代理
        self.blog_formatter = Agent(name="blog_formatter",
                                   model=self.config.model,
                                   instructions="""你是一位专业的日本留学相关的文章的格式化专家。
你的工作是将输入的文章内容进行markdown格式化：
1、将文章内容进行markdown格式化，注意正确的使用H1～H4的标题以及加粗等markdown语法
2、表格的排版要特别注意，保证表格的完整性


请以JSON格式返回结果，格式如下：
{
    "formatted_content": "格式化后的文章内容"
}

注意：
- 你的工作只是进行格式化，除非有明显的中文语法错误，不要对文章内容进行任何的修改
- 返回的formatted_content不应该带有任何 ```json 或是 ``` 或是 ```markdown 这样的标记

关于Markdown的语法格式，特别注意以下要求：
1. 表格前后的空行要保留
2. 列表前后的空行要保留
3. 标题前后的空行要保留
4. 表格的排版（特别是合并单元格）要与原文（图片）完全一致
5. 根据Markdown的语法，需要添加空格的地方，请务必添加空格；但不要在表格的单元格内填充大量的空格，需要的话填充一个空格即可
总之，要严格的践行Markdown的语法要求，不要只是看上去像，其实有不少语法错误
""")

    def _init_workspace(self):
        """初始化工作目录"""
        self.OUTPUT_DIR.mkdir(exist_ok=True)
        self.LOG_DIR.mkdir(exist_ok=True)

    def write_article(self, sample_md_content: str, sample_md_file_name: str = "") -> Tuple[Optional[str], Optional[str]]:
        """根据写作方向和参考内容生成文章"""

        task = f"""请根据以下参考内容，撰写一篇专业的日本留学咨询文章。

参考内容：
{sample_md_content}
        """

        # 使用标准输出文件记录对话过程
        std_output_file = self.LOG_DIR / f"ag2_std_output_{sample_md_file_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"

        sys.stdout = open(std_output_file, "w", encoding="utf-8")
        try:
            self._init_agents()

            # 第一步：生成文章内容
            with trace("文章生成"):
                input_items = [
                    {
                        "role": "user",
                        "content": task
                    }
                ]
                result = Runner.run_sync(self.article_writer, input_items)
                if not result or not result.final_output:
                    raise Exception("文章生成失败")

                try:
                    article_data = json.loads(result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章生成结果格式错误: {e}") from e

            # 为大学添加URL
            valid_universities = []
            if article_data.get("universities") and isinstance(article_data["universities"], list):
                for university in article_data["universities"]:
                    url = self.university_utils.get_university_url(university["japanese_name"])
                    if url:
                        university["url"] = url
                        valid_universities.append(university)

            # 第二步：格式化文章
            with trace("文章格式化"):
                format_input_items = [
                    {
                        "role": "user",
                        "content": f"""请格式化以下文章：
                        
{article_data["content"]}
"""
                    }
                ]
                format_result = Runner.run_sync(self.blog_formatter, format_input_items)
                if not format_result or not format_result.final_output:
                    raise Exception("文章格式化失败")

                try:
                    format_data = json.loads(format_result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章格式化结果格式错误: {e}") from e

                formatted_content = format_data["formatted_content"]

            # 添加大学URL
            for university in valid_universities:
                formatted_content = formatted_content.replace(university["chinese_name"], f"[{university['chinese_name']}]({university['url']})")

            return article_data["title"], formatted_content

        except Exception as e:
            logger.error(f"生成文章时发生错误: {e}")
            return None, None
        finally:
            sys.stdout.close()
            sys.stdout = sys.__stdout__

    def process_one(self, sample_md_content: str, sample_md_file_name: str = "") -> Optional[str]:
        """处理单个文件"""
        try:
            title, formatted_content = self.write_article(sample_md_content, sample_md_file_name)
        except Exception as e:
            logger.error(f"生成文章时发生错误: {e}")
            return None

        if title is None or len(title) == 0:
            logger.warning("未能生成文章的标题，pass")
            return None

        if formatted_content is None or len(formatted_content) == 0:
            logger.warning(f"未能生成文章的内容，pass: {title}")
            return None

        logger.info(f"开始输出：{title}")

        # 创建一个以 title_当前时间.md 为名的文件
        output_file = self.OUTPUT_DIR / f"{title}_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_content)

        return "Success"


def main(input_folder_path: Path) -> None:
    """主函数，协调整个文章生成过程
    
    Args:
        input_folder_path (Path): 要处理的文件夹路径
    """
    try:
        # 创建服务实例
        writer = ArticleWriter()

        # 处理所有文件
        md_file_count = 0
        success_count = 0

        # 从input_folder_path中读取所有md文件
        for md_file in input_folder_path.glob("*.md"):
            logger.info(f"开始处理: {md_file.name}")
            md_file_count += 1
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            result = writer.process_one(content, md_file.name)
            if result is None:
                logger.error(f"处理失败: {md_file.name}")
            else:
                logger.info(f"处理成功: {md_file.name}")
                success_count += 1

        # 汇总处理结果
        if success_count < md_file_count:
            logger.warning(f"处理完成：共 {md_file_count} 个文件，成功 {success_count} 个，失败 {md_file_count - success_count} 个")
        else:
            logger.info(f"处理完成：全部 {md_file_count} 个文件处理成功")

    except ValueError as e:
        # 处理已知的配置和初始化错误
        logger.error(f"程序初始化失败: {e}")
        sys.exit(1)
    except Exception as e:
        # 处理未预期的运行时错误
        logger.error(f"程序运行过程中发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='日本留学文章生成')
    parser.add_argument('input_folder', nargs='?', default="output", help='保存文章源文件的文件夹。如果不指定，将使用默认值：output')
    args = parser.parse_args()

    try:
        input_folder = Path(args.input_folder)
    except Exception as e:
        logger.error(f'输入路径不合法：{args.input_folder} - {str(e)}')
        print('Usage: python blog_writer.py <input_folder>')
        sys.exit(1)

    if not input_folder.exists():
        logger.error(f'指定的文件夹不存在：{input_folder}')
        print('Usage: python blog_writer.py <input_folder>')
        sys.exit(1)

    if not input_folder.is_dir():
        logger.error(f'指定的路径不是一个文件夹：{input_folder}')
        print('Usage: python blog_writer.py <input_folder>')
        sys.exit(1)

    try:
        # 检查文件夹是否可读
        if not os.access(input_folder, os.R_OK):
            logger.error(f'没有权限读取指定的文件夹：{input_folder}')
            print('Usage: python blog_writer.py <input_folder>')
            sys.exit(1)

        # 检查文件夹是否为空
        if not any(input_folder.glob("*.md")):
            logger.error(f'指定的文件夹中没有找到任何.md文件：{input_folder}')
            print('Usage: python blog_writer.py <input_folder>')
            sys.exit(1)

        logger.info(f"开始处理：{input_folder}")
        main(input_folder)
    except Exception as e:
        logger.error(f'处理过程中发生错误：{str(e)}')
        sys.exit(1)
