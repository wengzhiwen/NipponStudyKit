import csv
import os
import shutil

def ensure_error_data_dir():
    """确保error_data目录存在"""
    error_dir = 'pdf_with_md/error_data'
    if not os.path.exists(error_dir):
        os.makedirs(error_dir)
        print(f"创建目录: {error_dir}")
    return error_dir

def get_first_level_dir(file_path):
    """从文件路径中提取一级子目录"""
    # 移除开头的./和pdf_with_md/
    path = file_path.replace('./', '').replace('pdf_with_md/', '')
    # 获取第一个目录名
    first_dir = path.split('/')[0]
    return first_dir

def move_error_directories():
    """移动包含错误数据的目录"""
    error_file = 'pdf_with_md/org_error_20250106093355.csv'
    error_dir = ensure_error_data_dir()
    moved_dirs = set()  # 用于记录已处理的目录
    
    try:
        with open(error_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            print("开始处理错误数据目录...")
            print("-" * 50)
            
            for row in reader:
                if len(row) >= 1:
                    file_path = row[0]
                    first_level_dir = get_first_level_dir(file_path)
                    source_dir = os.path.join('pdf_with_md', first_level_dir)
                    target_dir = os.path.join(error_dir, first_level_dir)
                    
                    # 如果这个目录还没有被移动过
                    if first_level_dir not in moved_dirs and os.path.exists(source_dir):
                        try:
                            shutil.move(source_dir, target_dir)
                            moved_dirs.add(first_level_dir)
                            print(f"已移动: {first_level_dir}")
                        except Exception as e:
                            print(f"移动目录 {first_level_dir} 时发生错误: {str(e)}")
            
            print("-" * 50)
            print(f"处理完成。共移动 {len(moved_dirs)} 个目录到 {error_dir}")
            
    except FileNotFoundError:
        print(f"错误: 找不到文件 {error_file}")
    except Exception as e:
        print(f"处理文件时发生错误: {str(e)}")

if __name__ == "__main__":
    move_error_directories()
