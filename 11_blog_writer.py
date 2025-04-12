import os
import re
import json
from datetime import datetime
from typing import List, Tuple, Optional
import sys

from autogen import ConversableAgent
from autogen.io.run_response import RunResponseProtocol

from service_config import ServiceConfig


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
                subdir_path = os.path.join(pdf_dir, subdir)
                if not os.path.isdir(subdir_path):
                    continue

                # 检查必需文件是否存在
                required_files = [f"{subdir}.md", f"{subdir}_中文.md", f"{subdir}_report.md"]

                is_valid = all(os.path.exists(os.path.join(subdir_path, f)) for f in required_files)
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
                existing_match = re.match(r".+_(\d{4}[-]?\d{2}[-]?\d{2}|\d{8})", os.path.basename(existing_path))
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
        match = re.match(r".+_(\d{4}[-]?\d{2}[-]?\d{2}|\d{8})", os.path.basename(path))
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

    LOG_DIR = "log"
    OUTPUT_DIR = "blogs"

    def __init__(self):
        # 初始化配置
        self.config = ServiceConfig()

        self.university_utils = UniversityUtils()
        self._init_workspace()

        self.article_writer: Optional[ConversableAgent] = None
        self.blog_formatter: Optional[ConversableAgent] = None

    def _init_agents(self):
        """初始化agents"""
        self.article_writer = ConversableAgent(name="article_writer",
                                               llm_config=self.config.llm_config_low_cost,
                                               description="Agent for writing professional articles about studying in Japan",
                                               system_message="""你是一位专业的日本留学相关的文章的写作优化专家。
你的工作是：
1、根据用户输入的参考内容，重新进行组织和优化，使得文章内容更加轻松、易读
2、必要时根据你所掌握的日本留学相关的准确知识进行适当的补充
3、你所写的内容主要会被应用于留学相关网站的SEO，请务必确保文章内容对SEO友好
4、只有用户输入的参考内容中提到的大学，你才可以在输出中提及
5、记录下在你输出中提到的大学中文名称（全名）列表（大学中文全名、大学日文全名）
6、在文章的末尾添加一个"相关大学"的标题，列出上表中的中文全名

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

        self.blog_formatter = ConversableAgent(name="blog_formatter",
                                               llm_config=self.config.llm_config_mini,
                                               description="Agent for formatting articles",
                                               system_message="""你是一位专业的日本留学相关的文章的格式化专家。
你的工作是将输入的文章内容进行markdown格式化：
1、将文章内容进行markdown格式化，注意正确的使用H1～H4的标题以及加粗等markdown语法


请以JSON格式返回结果，格式如下：
{
    "formatted_content": "格式化后的文章内容"
}

注意：
- 你的工作只是进行格式化，除非有明显的中文语法错误，不要对文章内容进行任何的修改
- 返回的formatted_content不应该带有任何 ```json 或是 ``` 或是 ```markdown 这样的标记
""")

    def _init_workspace(self):
        """初始化工作目录"""
        if not os.path.exists(self.OUTPUT_DIR):
            os.makedirs(self.OUTPUT_DIR)
        if not os.path.exists(self.LOG_DIR):
            os.makedirs(self.LOG_DIR)

    def write_article(self, sample_md_content: str, sample_md_file_name: str = "") -> Tuple[Optional[str], Optional[str]]:
        """根据写作方向和参考内容生成文章"""

        task = f"""请根据以下参考内容，撰写一篇专业的日本留学咨询文章。

参考内容：
{sample_md_content}
        """

        # 使用标准输出文件记录对话过程
        std_output_file = f"ag2_std_output_{sample_md_file_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
        std_output_file = os.path.join(self.LOG_DIR, std_output_file)

        sys.stdout = open(std_output_file, "w", encoding="utf-8")
        try:
            self._init_agents()

            # 第一步：生成文章内容
            response: RunResponseProtocol = self.article_writer.run(message=task, user_input=False, summary_method="last_msg", max_turns=1)
            response.process()
            if not response or not response.summary:
                raise Exception("文章生成失败")

            try:
                article_data = json.loads(response.summary)
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
            format_task = f"""请格式化以下文章：
            
{article_data["content"]}
"""

            format_response: RunResponseProtocol = self.blog_formatter.run(message=format_task, user_input=False, summary_method="last_msg", max_turns=1)
            format_response.process()
            if not format_response or not format_response.summary:
                raise Exception("文章格式化失败")

            try:
                format_data = json.loads(format_response.summary)
            except json.JSONDecodeError as e:
                raise Exception(f"文章格式化结果格式错误: {e}") from e

            formatted_content = format_data["formatted_content"]

            # 添加大学URL
            for university in valid_universities:
                formatted_content = formatted_content.replace(university["chinese_name"], f"[{university['chinese_name']}]({university['url']})")

            return article_data["title"], formatted_content

        except Exception as e:
            print(f"生成文章时发生错误: {e}")
            return None, None
        finally:
            sys.stdout.close()
            sys.stdout = sys.__stdout__

    def process_one(self, sample_md_content: str, sample_md_file_name: str = "") -> Optional[str]:
        """处理单个文件"""
        try:
            title, formatted_content = self.write_article(sample_md_content, sample_md_file_name)
        except Exception as e:
            print(f"生成文章时发生错误: {e}")
            return None

        if title is None or len(title) == 0:
            print("未能生成文章的标题，pass")
            return None

        if formatted_content is None or len(formatted_content) == 0:
            print(f"未能生成文章的内容，pass: {title}")
            return None

        print(f"开始输出：{title}")

        # 创建一个以 title_当前时间.md 为名的文件
        output_file = os.path.join(self.OUTPUT_DIR, f"{title}_{datetime.now().strftime('%Y%m%d%H%M%S')}.md")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_content)

        return "Success"


def main():
    md_file_count = 0
    success_count = 0

    sample_dir = "output"
    # 从sample_dir中读取所有md文件
    for md_file in os.listdir(sample_dir):
        if md_file.endswith(".md"):
            print(f"开始处理: {md_file}")
            md_file_count += 1
            with open(os.path.join(sample_dir, md_file), "r", encoding="utf-8") as f:
                content = f.read()
            writer = ArticleWriter()
            result = writer.process_one(content, md_file)
            if result is None:
                print(f"处理失败: {md_file}")
            else:
                print(f"处理成功: {md_file}")
                success_count += 1

    print(f"总共处理了{md_file_count}个文件，成功了{success_count}个")


if __name__ == "__main__":
    main()
