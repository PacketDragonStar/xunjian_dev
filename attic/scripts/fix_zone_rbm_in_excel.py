with open('gen_hualong_excel.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace("'display zone'", "'display security-zone'")
c = c.replace("'display rbm'", "'display remote-backup-group status'")
with open('gen_hualong_excel.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('zone/rbm commands updated in gen_hualong_excel.py')