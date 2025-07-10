"""
日本留学信息BLOG生成工具

这个工具提供了三种模式来生成日本留学相关的文章：

1. 批量处理模式 (Batch Mode)
   功能：处理指定文件夹中的所有markdown文件，优化（特别是SEO）和梳理每一篇文章，并生成Markdown格式的BLOG
   特点：
   - 自动处理文件夹中的所有.md文件
   - 每篇文章独立生成，互不影响
   - 适合处理大量独立的大学介绍文章
   使用方式：
   ```bash
   python blog_writer.py -b <directory> [-o <output_directory>]
   ```

2. 对比分析模式 (Compare Mode)
   功能：分析多个大学的markdown文件，生成一篇综合性的推荐BLOG
   特点：
   - 最多支持5个文件同时分析
   - 自动分析大学的共同点和特色
   - 生成一篇综合性的文章，突出各大学的特色
   - 适合生成"某地区大学推荐"、"某类型大学对比"等主题文章
   使用方式：
   ```bash
   python blog_writer.py -c <file1> [file2 ...] [-o <output_directory>]
   ```

3. 材料扩展模式 (Expand Mode)
   功能：基于指定的markdown文件材料和扩展写作方向，生成一篇扩展性的BLOG文章
   特点：
   - 接受一个markdown文件作为基础材料
   - 根据用户提供的写作方向和提示词进行扩展
   - 适合在现有材料基础上进行主题扩展和深入分析
   - 支持多样化的写作角度和内容扩展
   使用方式：
   ```bash
   python blog_writer.py -e <markdown_file> --prompt "<扩展写作方向>" [-o <output_directory>]
   ```

输出：
- 生成的文章默认保存在 `blogs` 目录下，可通过 -o 参数指定其他输出目录
- 处理日志保存在 `log` 目录下
- 文章中的大学名称会自动添加对应的URL链接
"""

import os
import json
from datetime import datetime
from typing import Optional
import sys
import argparse
from pathlib import Path

from agents import Agent, Runner, trace
from dotenv import load_dotenv
from logging_config import setup_logger
from university_utils import UniversityUtils

logger = setup_logger(logger_name="blog_writer", log_level="INFO")


class ArticleWriter:

    LOG_DIR = Path("log")
    DEFAULT_OUTPUT_DIR = Path("blogs")

    def __init__(self, output_dir: Optional[str] = None):
        load_dotenv()

        self.model = os.getenv("OPENAI_BLOG_WRITER_MODEL", "gpt-4o")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY 环境变量未设置")
            raise ValueError("未设置OpenAI API密钥。请在.env文件中设置OPENAI_API_KEY环境变量。")

        logger.info(f'SETUP INFO = MODEL: {self.model}')

        self.university_utils = UniversityUtils()

        # 设置输出目录：如果指定了输出目录，使用指定的目录，否则使用默认目录
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = self.DEFAULT_OUTPUT_DIR

        self.output_dir.mkdir(exist_ok=True)
        self.LOG_DIR.mkdir(exist_ok=True)

        self.article_writer: Optional[Agent] = None
        self.blog_formatter: Optional[Agent] = None
        self.comparative_writer: Optional[Agent] = None
        self.article_reducer: Optional[Agent] = None
        self.expand_writer: Optional[Agent] = None

    def _init_agents(self):
        self.article_writer = Agent(name="article_writer",
                                    model=self.model,
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

        self.blog_formatter = Agent(name="blog_formatter",
                                    model=self.model,
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
6. 文章开始的summary部分（若有）可以使用块引用的语法来突出表示
总之，要严格的践行Markdown的语法要求，不要只是看上去像，其实有不少语法错误
""")

        self.comparative_writer = Agent(name="comparative_writer",
                                        model=self.model,
                                        instructions=f"""你是一位专业的日本留学相关的文章的写作专家。
除非输出内容中明确要求使用日语的部分，其他部分一律使用中文输出。

你的工作是：
1、根据用户输入的多个大学的参考内容，分析这些大学的共同点和特色
2、撰写一篇综合性的文章，重点突出这些大学的共同特点和各自的特色对大学进行推荐
3、不要机械的去写共同特点是xxx，共同特色是xxx，共同特色更多的体现在标题和开头即可，内容还是以各个大学分别的介绍为主
4、对于可以渡日前申请、只需要进行线上面试等入学方式比较便捷的大学进行特别说明，但篇幅不要多
5、文章内容要轻松易读，适合SEO优化
6、表格是很好的信息组织方式，如果需要，可以使用markdown的语法来表示表格

请以JSON格式返回结果，格式如下：
{{
    "title": "文章标题",
    "content": "文章内容",
    "universities": [
        {{
            "chinese_name": "大学中文名",
            "japanese_name": "大学日文名(日文全名，不是英文名)"
        }}
    ]
}}

注意：
 - 标题不要太长，但要带上今年的年份：{datetime.now().year}，以提升SEO的水准
 - 请不要对日本留学相关的内容进行任何推测，不要添加任何主观臆断
 - 你撰写的文章中必须使用大学完整的中文名称
 - 不要添加任何主观臆断，不要添加任何原文中不存在的信息（哪怕是一些常识性的信息），不要推测 不要推测 不要推测！
 - 对于重要的数据，请保持原样，不要进行任何修改
 - 文章内容要正面积极
 - 不要在返回中带有```json 或是 ``` 这样的定界符
""")

        self.article_reducer = Agent(name="article_reducer",
                                     model=self.model,
                                     instructions="""你是一位专业的日本大学招生简章的缩减专家。
如果输入的内容原文是日语，那你的输出也必须是日语，否则请输出中文。

你的工作是：
1. 仔细阅读文章全文，对文章中提到的信息完全把握的前提下进行后续步骤
2. 对文章内容按以下要求进行处理：
 - 保留：大学的全名、基本信息，概况介绍；如果特别长进行适当缩减
 - 保留：大学或学部的特色说明，但删除与外国人留学生招募不相关的学部；如果特别长进行适当缩减
 - 删除：学校创始人 校长 教学理念等相关的介绍，但如果有和这个学校相关的名人的介绍可以进行适当缩减
 - 简化：各个学部的招生要求中，只保留与外国人留学生有关的学部（本科）的招生信息，并进行简化，将要求类似的学部进行合并
 - 保留：如果有提到和大学排名相关的信息，请保留
 - 保留：在几月进行出愿（报名）、考试、合格发表、入学等关键时间点，精确到月份，不需要保留年份和具体日期
3. 输出结果第一行为大学的日文全名

注意事项：
1. 请确保提取的信息准确、客观，不要添加任何主观臆断
2. 所有提取的信息请控制在5000字以内
3. 不需要保留原文的格式（比如Markdown），特别是繁复的表格只需要准确提取表格所表达的信息的概要内容即可
4. 不要添加任何主观臆断，不要添加任何原文中不存在的信息（哪怕是一些常识性的信息），不要推测 不要推测 不要推测！
5. 对于重要的数据，请保持原样，不要进行任何修改
6. 不需要保留任何和年份有关的信息
""")

        self.expand_writer = Agent(name="expand_writer",
                                   model=self.model,
                                   instructions=f"""你是一位专业的日本留学相关的文章的简体中文BLOG写作专家。

你的工作是：
1、根据用户提供的基础材料（markdown文件内容，一般是大学的留学生招生简章）和扩展写作方向
2、在保持原材料核心信息准确性的基础上，按照指定的写作方向进行BLOG的书写
3、你要写作的BLOG文章是根据扩展写作方向的要求来撰写的，并不是以对基础材料的归纳和总结为主，具体原始材料需要引用到什么程度，请根据扩展写作方向来决定
4、确保文章内容轻松易读，适合SEO优化
5、如果有你有互联网搜索能力，请使用互联网搜索能力来获取更多信息，但请确保只搜索日文的信息，不要搜索中文的信息
6、记录下在你输出中提到的大学中文名称（全名）列表（大学中文全名、大学日文全名）
7、表格是很好的信息组织方式，如果需要，可以使用markdown的语法来表示表格

请以JSON格式返回结果，格式如下：
{{
    "title": "文章标题",
    "content": "文章内容",
    "universities": [
        {{
            "chinese_name": "大学中文名",
            "japanese_name": "大学日文名(日文全名，不是英文名)"
        }}
    ]
}}

注意：
 - 标题要体现扩展的写作方向，并带上今年的年份：{datetime.now().year + 1}，以提升SEO的水准
 - 请严格基于提供的基础材料进行扩展，如果要添加补充的信息，请务必使用互联网上的权威日语信息（千万不要参考中文的信息）
 - 你撰写的文章中必须使用大学完整的中文名称
 - 不要添加任何主观臆断，不要推测基础材料中没有的信息
 - 对于重要的数据，请保持原样，不要进行任何修改
 - 文章内容要正面积极
 - 不要在返回中带有```json 或是 ``` 这样的定界符
 - 请使用简体中文输出
""")

    def write_article(self, sample_md_content: str) -> Optional[str]:
        task = f"""请根据以下参考内容，撰写一篇专业的日本留学咨询文章。

参考内容：
{sample_md_content}
        """

        try:
            logger.info("初始化AI代理...")
            self._init_agents()

            with trace("文章生成"):
                input_items = [{"role": "user", "content": task}]
                result = Runner.run_sync(self.article_writer, input_items)
                if not result or not result.final_output:
                    raise Exception("文章生成失败")

                try:
                    article_data = json.loads(result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章生成结果格式错误: {e}") from e

            logger.info("为大学添加URL链接...")
            valid_universities = []
            if article_data.get("universities") and isinstance(article_data["universities"], list):
                for university in article_data["universities"]:
                    url = self.university_utils.get_university_url(university["japanese_name"])
                    if url:
                        university["url"] = url
                        valid_universities.append(university)

            logger.info("开始格式化文章...")
            with trace("文章格式化"):
                format_input_items = [{"role": "user", "content": f"""请格式化以下文章：
                        
{article_data["content"]}
"""}]
                format_result = Runner.run_sync(self.blog_formatter, format_input_items)
                if not format_result or not format_result.final_output:
                    raise Exception("文章格式化失败")

                try:
                    format_data = json.loads(format_result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章格式化结果格式错误: {e}") from e

                formatted_content = format_data["formatted_content"]

            logger.info("在文章中添加大学URL链接...")
            for university in valid_universities:
                formatted_content = formatted_content.replace(university["chinese_name"], f"[{university['chinese_name']}]({university['url']})")

            logger.info("保存文章...")
            return self._save_article(article_data["title"], formatted_content)

        except Exception as e:
            logger.error(f"生成文章时发生错误: {e}")
            return None

    def write_comparative_article(self, md_contents: list[str]) -> Optional[str]:
        try:
            logger.info("初始化AI代理...")
            self._init_agents()

            logger.info(f"开始缩减{len(md_contents)}篇文章的内容...")
            article_summaries = []
            for i, content in enumerate(md_contents):
                logger.info(f"正在缩减第{i+1}/{len(md_contents)}篇文章...")
                with trace(f"缩减文章 {i+1}/{len(md_contents)}"):
                    input_items = [{
                        "role": "user",
                        "content": f"""请缩减以下文章内容：

{content}

----
以上是所有提供给你的材料。

请严格按照系统提示词中的要求和说明进行工作并输出结果。特别注意输出结果所使用的语言要根据系统提示词中的要求来决定。
"""
                    }]
                    result = Runner.run_sync(self.article_reducer, input_items)
                    if not result or not result.final_output:
                        raise Exception("缩减文章失败")

                    article_summaries.append(result.final_output)
                    logger.debug(f"缩减后的文章：{result.final_output}")

            logger.info("开始生成综合性文章...")
            with trace("综合性文章生成"):
                input_items = [{
                    "role":
                    "user",
                    "content":
                    """请根据以下多所大学的信息，撰写一篇综合性的日本留学的BLOG。

""" + '\n\n'.join(article_summaries) + """

----
以上是所有提供给你的材料。

请严格按照系统提示词中的要求和说明进行工作并输出结果。
"""
                }]
                result = Runner.run_sync(self.comparative_writer, input_items)
                if not result or not result.final_output:
                    raise Exception("综合性文章生成失败")

                try:
                    article_data = json.loads(result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"综合性文章生成结果格式错误: {e}") from e

            logger.info("为大学添加URL链接...")
            valid_universities = []
            if article_data.get("universities") and isinstance(article_data["universities"], list):
                for university in article_data["universities"]:
                    url = self.university_utils.get_university_url(university["japanese_name"])
                    if url:
                        university["url"] = url
                        valid_universities.append(university)

            logger.info("开始格式化文章...")
            with trace("文章格式化"):
                format_input_items = [{"role": "user", "content": f"""请格式化以下文章：
                        
{article_data["content"]}
"""}]
                format_result = Runner.run_sync(self.blog_formatter, format_input_items)
                if not format_result or not format_result.final_output:
                    raise Exception("文章格式化失败")

                try:
                    format_data = json.loads(format_result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章格式化结果格式错误: {e}") from e

                formatted_content = format_data["formatted_content"]

            logger.info("在文章中添加大学URL链接...")
            for university in valid_universities:
                formatted_content = formatted_content.replace(university["chinese_name"], f"[{university['chinese_name']}]({university['url']})")

            logger.info("保存文章...")
            return self._save_article(article_data["title"], formatted_content)

        except Exception as e:
            logger.error(f"生成综合性文章时发生错误: {e}")
            return None

    def write_expand_article(self, md_content: str, expand_prompt: str) -> Optional[str]:
        try:
            logger.info("初始化AI代理...")
            self._init_agents()

            logger.info("开始根据材料和扩展方向生成文章...")
            with trace("材料扩展文章生成"):
                input_items = [{
                    "role":
                    "user",
                    "content":
                    f"""请根据以下基础材料和扩展写作方向，撰写一篇扩展性的日本留学BLOG文章。

基础材料：
{md_content}

扩展写作方向：
{expand_prompt}

----
以上是所有提供给你的材料。

请严格按照系统提示词中的要求和说明进行工作并输出结果。基于基础材料，按照扩展写作方向进行创作。
"""
                }]
                result = Runner.run_sync(self.expand_writer, input_items)
                if not result or not result.final_output:
                    raise Exception("扩展文章生成失败")

                try:
                    article_data = json.loads(result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"扩展文章生成结果格式错误: {e}") from e

            logger.info("为大学添加URL链接...")
            valid_universities = []
            if article_data.get("universities") and isinstance(article_data["universities"], list):
                for university in article_data["universities"]:
                    url = self.university_utils.get_university_url(university["japanese_name"])
                    if url:
                        university["url"] = url
                        valid_universities.append(university)

            logger.info("开始格式化文章...")
            with trace("文章格式化"):
                format_input_items = [{"role": "user", "content": f"""请格式化以下文章：
                        
{article_data["content"]}
"""}]
                format_result = Runner.run_sync(self.blog_formatter, format_input_items)
                if not format_result or not format_result.final_output:
                    raise Exception("文章格式化失败")

                try:
                    format_data = json.loads(format_result.final_output)
                except json.JSONDecodeError as e:
                    raise Exception(f"文章格式化结果格式错误: {e}") from e

                formatted_content = format_data["formatted_content"]

            logger.info("在文章中添加大学URL链接...")
            for university in valid_universities:
                formatted_content = formatted_content.replace(university["chinese_name"], f"[{university['chinese_name']}]({university['url']})")

            logger.info("保存文章...")
            return self._save_article(article_data["title"], formatted_content)

        except Exception as e:
            logger.error(f"生成扩展文章时发生错误: {e}")
            return None

    def _save_article(self, title: str, formatted_content: str) -> str:
        if title is None or len(title) == 0:
            logger.warning("未能生成文章的标题，pass")
            return None

        if formatted_content is None or len(formatted_content) == 0:
            logger.warning(f"未能生成文章的内容，pass: {title}")
            return None

        logger.info(f"开始输出：{title}")

        output_file = self.output_dir / f"{title}_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_content)

        return "Success"


def process_batch_mode(input_folder_path: Path, output_dir: Optional[str] = None) -> None:
    try:
        writer = ArticleWriter(output_dir)

        md_file_count = 0
        success_count = 0

        for md_file in input_folder_path.glob("*.md"):
            logger.info(f"开始处理: {md_file.name}")
            md_file_count += 1
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            result = writer.write_article(content)
            if result is None:
                logger.error(f"处理失败: {md_file.name}")
            else:
                logger.info(f"处理成功: {md_file.name}")
                success_count += 1

        if success_count < md_file_count:
            logger.warning(f"处理完成：共 {md_file_count} 个文件，成功 {success_count} 个，失败 {md_file_count - success_count} 个")
        else:
            logger.info(f"处理完成：全部 {md_file_count} 个文件处理成功")

    except Exception as e:
        logger.error(f"批量处理模式执行失败: {e}")
        raise


def process_compare_mode(input_files: list[Path], output_dir: Optional[str] = None) -> None:
    try:
        writer = ArticleWriter(output_dir)

        if len(input_files) < 1:
            raise ValueError("未指定任何文件")
        if len(input_files) > 5:
            logger.warning("指定的文件数量超过5个，将只处理前5个文件")
            input_files = input_files[:5]

        md_contents = []
        for input_file_path in input_files:
            try:
                logger.info(f"正在读取文件：{input_file_path}")
                content = input_file_path.read_text(encoding='utf-8')
                md_contents.append(content)
            except Exception as e:
                logger.error(f"读取文件失败，将跳过：{input_file_path}，错误信息：{str(e)}")
                continue

        if not md_contents:
            raise ValueError("没有成功读取任何文件内容")

        result = writer.write_comparative_article(md_contents)
        if result is None:
            raise ValueError("生成综合性文章失败")
        logger.info("生成综合性文章成功")

    except Exception as e:
        logger.error(f"对比分析模式执行失败: {e}")
        raise


def process_expand_mode(input_file: Path, expand_prompt: str, output_dir: Optional[str] = None) -> None:
    try:
        writer = ArticleWriter(output_dir)

        logger.info(f"正在读取文件：{input_file}")
        try:
            content = input_file.read_text(encoding='utf-8')
        except Exception as e:
            raise ValueError(f"读取文件失败：{input_file}，错误信息：{str(e)}") from e

        if not content.strip():
            raise ValueError(f"文件内容为空：{input_file}")

        logger.info(f"扩展写作方向：{expand_prompt}")
        result = writer.write_expand_article(content, expand_prompt)
        if result is None:
            raise ValueError("生成扩展文章失败")
        logger.info("生成扩展文章成功")

    except Exception as e:
        logger.error(f"材料扩展模式执行失败: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='日本留学文章生成')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-b', '--batch', help='批量处理模式：处理指定文件夹中的所有markdown文件')
    group.add_argument('-c', '--compare', nargs='+', help='对比分析模式：处理指定的多个markdown文件并生成综合性文章（最多5个文件）')
    group.add_argument('-e', '--expand', help='材料扩展模式：基于指定的markdown文件和扩展方向生成文章')
    parser.add_argument('-p', '--prompt', help='扩展写作方向（仅在材料扩展模式下使用）')
    parser.add_argument('-o', '--output', help='指定输出目录（默认为"blogs"目录）')
    args = parser.parse_args()

    try:
        if args.expand:
            if not args.prompt:
                raise ValueError("材料扩展模式需要提供扩展写作方向（--prompt参数）")

            input_file = Path(args.expand)
            if not input_file.exists():
                raise ValueError(f'指定的文件不存在：{input_file}')
            if not input_file.is_file():
                raise ValueError(f'指定的路径不是一个文件：{input_file}')
            if not os.access(input_file, os.R_OK):
                raise ValueError(f'没有权限读取指定的文件：{input_file}')

            process_expand_mode(input_file, args.prompt, args.output)
        elif args.compare:
            input_files = [Path(f) for f in args.compare]
            for file_path in input_files:
                if not file_path.exists():
                    raise ValueError(f'指定的文件不存在：{file_path}')
                if not file_path.is_file():
                    raise ValueError(f'指定的路径不是一个文件：{file_path}')
                if not os.access(file_path, os.R_OK):
                    raise ValueError(f'没有权限读取指定的文件：{file_path}')
            process_compare_mode(input_files, args.output)
        else:
            input_folder = Path(args.batch)
            if not input_folder.exists():
                raise ValueError(f'指定的文件夹不存在：{input_folder}')
            if not input_folder.is_dir():
                raise ValueError(f'指定的路径不是一个文件夹：{input_folder}')
            if not os.access(input_folder, os.R_OK):
                raise ValueError(f'没有权限读取指定的文件夹：{input_folder}')
            if not any(input_folder.glob("*.md")):
                raise ValueError(f'指定的文件夹中没有找到任何.md文件：{input_folder}')
            process_batch_mode(input_folder, args.output)
    except ValueError as e:
        logger.error(str(e))
        print('Usage:')
        print('  批量处理模式: python blog_writer.py -b <directory> [-o <output_directory>]')
        print('  对比分析模式: python blog_writer.py -c <file1> [file2 ...] [-o <output_directory>]')
        print('  材料扩展模式: python blog_writer.py -e <markdown_file> --prompt "<扩展写作方向>" [-o <output_directory>]')
        sys.exit(1)
    except Exception as e:
        logger.error(f'处理过程中发生未预期的错误：{str(e)}')
        sys.exit(1)
