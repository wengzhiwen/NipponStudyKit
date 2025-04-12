"""
配置管理模块
"""
import os
from dotenv import load_dotenv
from autogen import LLMConfig


class ServiceConfig:
    """配置类，用于管理所有配置信息"""

    def __init__(self):
        load_dotenv()

        # 加载LLM配置文件路径
        self.llm_config_path = os.getenv("LLM_CONFIG_PATH", "config/llm_config.json")

        # 检查配置文件是否存在
        if not os.path.exists(self.llm_config_path):
            raise FileNotFoundError(f"LLM配置文件不存在: {self.llm_config_path}")

        # 加载LLM配置
        self.llm_config = self.load_config("STD")
        self.llm_config_mini = self.load_config("MINI")
        self.llm_config_low_cost = self.load_config("LOW_COST")

    def load_config(self, model_tag: str = "STD") -> LLMConfig:
        """从配置文件加载LLM配置
        
        Args:
            model_tag (str): 模型标签，用于选择特定的配置。默认为"STD"。
        
        Returns:
            LLMConfig: 加载的LLM配置对象
        """
        filter_dict = {"tags": [model_tag]}
        return LLMConfig.from_json(path=self.llm_config_path).where(**filter_dict)
