# -*- coding: utf-8 -*-
"""给 CheckItem 加 fix_suggestion，给 AnomalyRecord 加 severity"""
with open('app02/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. CheckItem 加 fix_suggestion（在 enabled 之后）
old = "    enabled        = models.BooleanField(verbose_name='启用', default=True)\n    created_at     = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)"
new = "    enabled        = models.BooleanField(verbose_name='启用', default=True)\n    fix_suggestion = models.CharField(verbose_name='整改建议', max_length=500, null=True, blank=True)\n    created_at     = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)"
content = content.replace(old, new)

# 2. AnomalyRecord 加 severity（在 confirm 之后）
old2 = "    confirm      = models.BooleanField(verbose_name='已确认', default=False)"
new2 = "    confirm      = models.BooleanField(verbose_name='已确认', default=False)\n    severity     = models.CharField(verbose_name='严重级别', max_length=10, default='P2',\n                                     choices=[('P0', 'P0-高危'), ('P1', 'P1-中危'), ('P2', 'P2-低危')])"
content = content.replace(old2, new2)

with open('app02/models.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('models.py updated: CheckItem.fix_suggestion + AnomalyRecord.severity')