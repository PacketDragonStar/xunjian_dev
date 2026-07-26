"""修复 gen_hualong_excel.py 第 82 行"""
with open('gen_hualong_excel.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'IRF堆叠状态' in line and line.count("''),") == 1:
        lines[i] = line.replace("custom', ''),", "custom', '', ")
        print(f'FIXED: line {i+1}')
        break

with open('gen_hualong_excel.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Trying to run gen_hualong_excel.py...')
exec(open('gen_hualong_excel.py', encoding='utf-8').read())