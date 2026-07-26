# -*- coding: utf-8 -*-
"""对比防火墙1（你改的） vs 防火墙（原始），列出差异"""
import pandas as pd

xl = '巡检项阈值配置表_化龙.xlsx'
df1 = pd.read_excel(xl, '防火墙1')
df2 = pd.read_excel(xl, '防火墙')

print('=== 防火墙1（你改的）===')
pd.set_option('display.max_colwidth', 80)
pd.set_option('display.max_columns', 15)
print(df1[['检查项', 'parser', 'checker', '现网阈值/期望值（待填）']].to_string())

print('\n\n=== 差异行 ===')
col = '现网阈值/期望值（待填）'
for i in range(min(len(df1), len(df2))):
    v1 = str(df1.iloc[i][col])
    v2 = str(df2.iloc[i][col])
    if v1 != v2:
        name = df1.iloc[i]['检查项']
        print(f'Row {i}: {name}')
        print(f'  防火墙（原始）: {v2}')
        print(f'  防火墙1（你改）: {v1}')