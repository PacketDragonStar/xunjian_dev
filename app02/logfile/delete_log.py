import os
import time
import datetime

def delete_old_files():
    # 获取当前时间戳
    now = time.time()
    # 计算一个月前的时间戳，一个月按 30 天算
    one_month_ago = now - 30 * 24 * 60 * 60
    # 获取当前文件夹路径
    current_dir = os.getcwd()

    # 遍历当前文件夹中的所有文件和子文件夹
    for root, dirs, files in os.walk(current_dir):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                # 获取文件的最后修改时间戳
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < one_month_ago:
                    # 如果文件的最后修改时间早于一个月前，删除该文件
                    os.remove(file_path)
                    print(f"已删除文件: {file_path}")
            except Exception as e:
                print(f"删除文件 {file_path} 时出错: {e}")

if __name__ == "__main__":
    delete_old_files()
