# NetBox 联动 · 内网部署与验收操作手册

> 前置：开发机代码已完成（`app02/parsers/comware.py` 扩展 + `app02/netbox/` 模块 + 命令），
> 本手册覆盖从「代码同步到内网」到「全站点跑通」的完整流程。

---

## 0. 前置确认

内网机器环境（先确认以下全部打勾再继续）：

- [x] **xunjian 项目路径**：确认内网 `xunjian_system1/` 根目录位置
- [x] **Python venv**：确认内网可用（`venv/Scripts/python.exe` 或同名）
- [ ] **MySQL 可达**：`settings.py` 中数据库配置正确，`python manage.py check` 通过
- [ ] **Docker**：`docker --version` ≥ 24.0
- [ ] **Docker Compose**：`docker compose version` ≥ v2.20
- [ ] **磁盘**：`df -h` 确保 `/opt`（或部署目录）≥ 20GB
- [ ] **内存**：`free -m` ≥ 4GB
- [ ] **内网 IP**：`ip addr` 或 `ipconfig` 记录本机 IP（后面 xunjian 要通过它访问 NetBox API）

---

## 1. 代码同步到内网

**方式 A：Git（推荐）**

```bash
# 在开发机上：
cd /path/to/xunjian_system1
git add -A
git commit -m "feat: NetBox 联动 — parsers + netbox module + sync_netbox command"
git push

# 在内网机器上：
cd /path/to/xunjian_system1
git pull
```

**方式 B：手动拷贝**

```bash
# 在开发机上打包
cd /path/to/xunjian_system1
# 新增文件
tar czf netbox_code.tar.gz \
  app02/netbox/ \
  app02/management/commands/sync_netbox.py \
  docs/netbox-integration-plan.md \
  docs/netbox-tickets.md

# 修改文件（全量打包安全）
tar czf app02_parsers.tar.gz app02/parsers/
tar czf app02_rebuild.tar.gz app02/management/commands/rebuild_topology.py

# 拷贝到内网机器，解压到对应位置
```

**同步后务必检查（在内网机器上）：**

```bash
cd /path/to/xunjian_system1

# 1. 确认新增模块存在
ls app02/netbox/
# 预期: __init__.py  client.py  mapper.py  diff.py  seed.py  sync.py

# 2. 确认命令存在
ls app02/management/commands/sync_netbox.py

# 3. 确认解析器扩展
grep "def parse_power" app02/parsers/comware.py
grep "def parse_device" app02/parsers/comware.py
grep "def parse_nat" app02/parsers/comware.py
grep "services, asn" app02/parsers/comware.py

# 4. Django check
python manage.py check
# 预期: System check identified no issues (0 silenced).

# 5. 安装 pynetbox
pip install pynetbox>=7.3
```

---

## 2. NetBox Docker 部署

### Step 1: 获取官方仓库

```bash
cd /opt
git clone -b release https://github.com/netbox-community/netbox-docker.git
cd netbox-docker
```

### Step 2: 创建环境配置

```bash
# 生成强随机 SECRET_KEY
python3 -c 'import secrets; print(secrets.token_hex(50))'
# 记下输出，下一步用 → ＜SECRET_KEY_OUTPUT＞
```

创建 `docker-compose.override.yml`（**不要改官方 docker-compose.yml**）：

```bash
cat > docker-compose.override.yml << 'DOCKEREOF'
version: '3.9'
services:
  netbox:
    ports:
      - "8080:8080"
    environment:
      DB_HOST: postgres
      DB_NAME: netbox
      DB_USER: netbox
      DB_PASSWORD: NetBox_DB_Pass_2026!      # ← 改掉
      REDIS_HOST: redis
      REDIS_CACHE_HOST: redis-cache
      SECRET_KEY: "<SECRET_KEY_OUTPUT>"       # ← 填入上面生成的值
      ALLOWED_HOSTS: "*"
      SUPERUSER_NAME: admin
      SUPERUSER_EMAIL: admin@example.com
      SUPERUSER_PASSWORD: NetBox_Admin_2026!  # ← 改掉
      TIME_ZONE: Asia/Shanghai
      LANGUAGE_CODE: zh-hans
      SITE_TITLE: "广期所网络资产"
      SITE_DESCRIPTION: "化龙 + 知识城"
    volumes:
      - netbox-media:/opt/netbox/netbox/media
      - ./reports:/opt/netbox/netbox/reports
      - ./scripts:/opt/netbox/scripts

volumes:
  netbox-media:
DOCKEREOF
```

> ⚠️ **安全提醒**：以上密码仅为示例！生产环境务必替换为强密码并妥善保管。

### Step 3: 拉取镜像

```bash
docker compose pull
# 约 5-10 分钟（视网速），拉取 PostgreSQL + Redis + NetBox 四个镜像
```

### Step 4: 启动

```bash
docker compose up -d
# 首次启动会自动执行 migrate + 创建超级用户
```

### Step 5: 等待就绪

```bash
# 查看启动日志
docker compose logs -f netbox | grep -E "listening|ready|Worker"

# 看到类似以下输出表示就绪（约 30-60 秒）：
#   django  | Listening on tcp://0.0.0.0:8080
```

### Step 6: 验证

```bash
# 内网机器上
curl http://localhost:8080/api/
# 返回 JSON → 确认 API 可达

# 从 xunjian 所在机器测试（重要！）
curl http://<内网IP>:8080/api/
# 如果返回 JSON → NetBox API 对 xunjian 可达
```

> ⚠️ 如果 curl 不通：
> - 检查防火墙：`firewall-cmd --add-port=8080/tcp` 或 `iptables -A INPUT -p tcp --dport 8080 -j ACCEPT`
> - 检查 `docker compose ps` 确认 netbox 容器在运行

### Step 7: 创建 API Token

在浏览器打开 `http://<内网IP>:8080`：
1. 用 `admin` / `NetBox_Admin_2026!` 登录
2. 右上角头像 → **Profile & Settings**
3. **API Tokens** → **Add a token**
4. 勾选 **Write** ✓
5. 描述填 `xunjian-sync`
6. 点击 **Create**，**复制 Token**（只显示一次！）

---

## 3. xunjian 侧配置

在内网机器上编辑 `xunjian_system1/settings.py`：

```python
# ═══════════════════════════════════════════════════════
#  NetBox 联动（DCIM / IPAM）
# ═══════════════════════════════════════════════════════
NETBOX_URL = 'http://<内网IP>:8080'          # ← 改成实际 IP
NETBOX_TOKEN = '<复制的Token>'                # ← 粘贴 API Token
```

验证配置：

```bash
python manage.py shell -c "
from django.conf import settings
print('URL:', settings.NETBOX_URL)
print('Token:', settings.NETBOX_TOKEN[:10] + '...')
"
```

---

## 4. 首次试跑（单站点）

### 4.1 仅导文件（安全验证）

```bash
# 不推送到 NetBox，只导出 JSON 报告
python manage.py sync_netbox --site 化龙

# 预期输出:
#   [Phase 0] 仅导文件模式（不加 --push）
#   （变更报告，为空——因为没有 push）
#   变更报告已保存: netbox_fixtures/化龙_20260728_120000.json
```

### 4.2 推送写入

```bash
python manage.py sync_netbox --site 化龙 --push
```

**预期输出**：

```
============================================================
  NetBox 同步 — 化龙
  模式：推送
============================================================

[Phase 0] NetBox 连接成功

  ── 新增 ──
    [dcim.sites]              · 化龙
    [dcim.manufacturers]      · H3C
    [dcim.device_roles]       · FW / CSW / ASW / LSW / SRP / PSW / OASW
    [dcim.platforms]          · Comware 7
    [ipam.vlan_groups]        · 化龙-VLANs
    [extras.custom_fields]    · inspection_last_run / cpu_usage_5s / ...

[Phase 1] 同步设备…
  ── 新增 ──
    [dcim.devices]            · fw001.pri.2IDC4f.hualong.xc ...
    [dcim.virtual_chassis]    · asw001&002 / asw003&004 ...

[Phase 2] 同步接口…
  ── 更新 ──
    [dcim.interfaces]         · fw001... (57 接口) ...

[Phase 3] 同步 IPAM…
[Phase 4] 同步 Cable 连线…
[Phase 5] 同步 Extras...

  总计：新增/更新 xxx 项，待删除 0 项
  变更报告已保存: netbox_fixtures/化龙_20260728_120030.json
```

### 4.3 浏览器验证

打开 `http://<内网IP>:8080`：

| 检查点 | 路径 | 预期 |
|--------|------|------|
| 设备列表 | Devices → Devices | 可见化龙所有设备（含 IRF 拆分的 Virtual Chassis） |
| 设备详情 | 点击某 Device | 接口列表完整、IP 已绑定、VRF 关联 |
| Virtual Chassis | Devices → Virtual Chassis | asw001&002 等堆叠对可见，含成员列表 |
| 前面板 | Device 详情 → Interfaces 标签 | 接口类型正确（1000base-t / 10gbase-x-sfpp） |
| Cable | Connections → Cables | LLDP 邻居物理连线可见 |
| VLAN | IPAM → VLANs | 化龙 VLAN 列表完整，归属 化龙-VLANs 组 |
| VRF | IPAM → VRFs | 多 VRF 环境可见 |
| IP 地址 | IPAM → IP Addresses | IP 绑 Interface + VRF |
| Prefix | IPAM → Prefixes | 路由网络号可见 |
| FHRP | IPAM → FHRP Groups | VRRP 实例可见 |

### 4.4 增量验证（重复运行）

```bash
# 再跑一次——验证幂等
python manage.py sync_netbox --site 化龙 --push
```

预期：**零报错、零重复创建**。终端报告显示「更新」而非「新增」。

---

## 5. 全量站点跑通

```bash
# 知识城单独跑
python manage.py sync_netbox --site 知识城 --push

# 浏览器验证（同上 4.3 检查点，切换到知识城 Site）
```

---

## 6. 删除验证

```bash
# 先预览待删除清单（不加 --delete）
python manage.py sync_netbox --site 化龙 --push
# 查看报告「⚠️ 待删除」部分

# 确认无误后执行删除
python manage.py sync_netbox --site 化龙 --push --delete
```

---

## 7. 一键联动验证（`rebuild_topology --netbox`）

```bash
python manage.py rebuild_topology --site 化龙 --push --netbox
```

预期流程：

```
[1/2] 刷新 CMDB 台账 (sync_cmdb)...
[2/2] 导出 network-seek fixture...
[push] 刷新拓扑图：化龙 -> bolt://localhost:7687
拓扑图刷新完成。

[3/3] 同步 NetBox CMDB (sync_netbox)...
  ... (同 4.2 的输出)
```

---

## 8. 备份配置

### NetBox 每日备份 cron

```bash
# 在内网 NetBox 服务器上
crontab -e

# 追加：
0 2 * * * docker exec netbox-docker-postgres-1 pg_dump -U netbox netbox > /backup/netbox_$(date +\%Y\%m\%d).sql
```

### xunjian 配置备份

```bash
# settings.py 中 NETBOX_URL / NETBOX_TOKEN 要进备份
git add xunjian_system1/settings.py
git commit -m "config: NetBox 联动配置"
```

---

## 9. 常见排错

| 症状 | 可能原因 | 排查 |
|------|---------|------|
| `sync_netbox --push` 降级为仅导文件 | NETBOX_URL 或 TOKEN 错误 | `curl -H "Authorization: Token $TOKEN" $URL/api/` |
| Device 没有接口 | `DeviceParseResult` 缺接口采集数据 | `DeviceParseResult.objects.filter(device__name='xxx', command='display interface brief')` |
| Cable 缺失 | LLDP 对端设备未同步 | 先同步两端设备，Cable 会自动补建 |
| Virtual Chassis 为空 | 设备名无 `&` 或 `parse_irf` 无结果 | `DeviceParseResult.objects.filter(command='display irf')` |
| 型号显示 Unknown | `display version` 无采集数据 | `DeviceParseResult.objects.filter(command='display version')` |
| NetBox Docker 启动失败 | 端口冲突（8080 被占用） | `docker compose logs netbox \| tail -50`，改端口 |

---

## 10. 验收打勾清单

- [ ] 代码已同步：`ls app02/netbox/sync.py` 存在
- [ ] `python manage.py check` → 0 issues
- [ ] NetBox Docker 4 个容器 `Up`：`docker compose ps`
- [ ] NetBox API 可达：`curl http://<内网IP>:8080/api/` → JSON
- [ ] API Token 已生成并填到 `settings.py`
- [ ] `sync_netbox --site 化龙 --push` → 无报错
- [ ] 浏览器验证：化龙 26 台设备可见（含 Virtual Chassis）
- [ ] 接口/IP/VLAN/VRF/Cable 完整
- [ ] `sync_netbox --site 知识城 --push` → 无报错
- [ ] 增量重跑：零报错、零重复
- [ ] `rebuild_topology --site 化龙 --push --netbox` → 全链路一通
- [ ] 备份 cron 已配置 ✓
