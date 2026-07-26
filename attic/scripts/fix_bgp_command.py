"""修正 BGP 命令为 display bgp peer ipv4"""
files = ['gen_hualong_excel.py', 'app02/views.py']
for fp in files:
    with open(fp, 'r', encoding='utf-8') as f:
        c = f.read()
    c = c.replace("display bgp peer'", "display bgp peer ipv4'")
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(c)
    print(f'{fp} bgp updated')