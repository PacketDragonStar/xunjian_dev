# -*- coding: utf-8 -*-
import os

base = r'c:/Users/ZSS/Desktop/xunjian/xunjian111/xunjian_system/xunjian_system1/app02/templates'

for fname in ['new_xunjian_page.html', 'new_info_history.html']:
    path = os.path.join(base, fname)
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ['utf-8', 'utf-8-sig', 'gbk', 'cp936']:
        try:
            text = raw.decode(enc)
            # 检测是否含乱码特征字符
            if '\ufffd' in text or '鍙' in text or '璁' in text:
                print(f'{fname}: {enc} contains mojibake, skip')
                continue
            print(f'{fname}: OK with {enc}, len={len(text)}')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            break
        except Exception as e:
            print(f'{fname}: {enc} failed: {e}')
            continue
    else:
        # 所有编码都有问题，尝试用gbk解码后重新encode为utf-8
        try:
            text = raw.decode('gbk', errors='replace')
            print(f'{fname}: forced gbk->utf8 rewrite')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        except Exception as e:
            print(f'{fname}: all failed: {e}')
