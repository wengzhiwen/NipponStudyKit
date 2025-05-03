# 日本大学招生信息处理工具集

这是一个用于处理日本大学招生信息的综合工具集，主要包含三个核心模块：

## 1. 招生简章下载工具

- `get_admissions_handbooks.py`: 自动获取日本各大学招生简章的工具
- `pdf_downloader_tool.py`: PDF文件下载和管理的辅助工具

这两个工具目前是独立运行的，尚未完全整合。

## 2. 招生简章处理工具

核心功能：
- PDF转PNG图片
- 使用Google Cloud Vision API进行OCR识别
- 使用Gemini AI生成格式化的Markdown文件
- 使用Gemini AI进行中文翻译
- 分析招生信息并识别有效的招生简章
- 按大学名称和申请截止日期组织文件
- 生成详细的处理报告

主要文件：
- `process_handbooks_pdf.py`: 主处理脚本
- `ocr_tool.py`: OCR处理工具
- `translate_tool.py`: 翻译工具
- `analysis_tool.py`: 内容分析工具
- `rename_analysis_tool.py`: 文件重命名工具

## 3. 博客写作工具

- `11_blog_writer.py`: 用于生成日本大学招生相关博客文章的工具（开发中）


## 安装设置

1. 安装系统依赖：
```bash
# Ubuntu/Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Windows
# 从[poppler releases](http://blog.alivate.com.au/poppler-windows/)下载并安装
```

2. 安装Python依赖：
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

3. 配置环境变量：
```bash
# 从示例文件复制并重命名
cp .env.sample .env
```

然后编辑`.env`文件，填入您的配置信息。

