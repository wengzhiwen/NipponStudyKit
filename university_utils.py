"""
大学工具类，用于处理大学相关的工具函数
"""

import os
import re
from pathlib import Path
from typing import Optional


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

    def get_university_url(self, jp_name: str) -> Optional[str]:
        """获取大学对应的URL
        
        Args:
            jp_name (str): 大学日文名称
            
        Returns:
            Optional[str]: 大学URL，如果未找到则返回None
        """
        if jp_name not in self.university_list:
            return None

        return f"https://www.runjplib.com/university/{jp_name}"
