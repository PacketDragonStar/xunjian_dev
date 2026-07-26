"""修复 gen_hualong_excel.py 第 82 行的括号问题，然后直接执行"""
with open('gen_hualong_excel.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    "custom', ''), '{\"func\":\"check_irf\"}'",
    "custom', '', '{\"func\":\"check_irf\"}'")

with open('gen_hualong_excel.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Syntax fixed, running gen_hualong_excel.py...')
exec(open('gen_hualong_excel.py', encoding='utf-8').read())