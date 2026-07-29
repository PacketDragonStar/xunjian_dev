# NetBox 联动实施方案

> 版本：v1 | 生成日期：2026-07-28
> 基于 Grill Me 全决策链路，覆盖 DCIM + IPAM + Extras 完整矩阵
> 「方案蓝图」——代码落地时以此为单一真源

---

## 0. 目标定位

巡检系统（xunjian）采集 CL → 自动同步到 NetBox（开源 DCIM/IPAM），实现：

- **双写模式**：自建 CMDB（CmdbDevice 等）保留不动，NetBox 作为标准 CMDB 旁路写入
- **增量 diff + 人工确认删除**：只增/改，不静默删除；`--delete` 开关 + 终端报告
- **全链自动同步**：设备 → 接口 → IP → VLAN → VRF → Cable → FHRP → Prefix → Service
- **能力感知同步**：利用 `DeviceParseResult` 结构化数据，零重复解析

## 1. 架构

```
xunjian (Django + MySQL)
  │
  ├── NewDevice          →  身份元数据 (name/ip/role/site/device_type)
  ├── DeviceParseResult  →  结构化解析 (单一真源 app02/parsers/comware.py)
  │
  ▼
sync_netbox 命令
  │  默认产出: netbox_fixtures/<site>/<timestamp>.json  (导文件)
  │  --push : 通过 pynetbox 调 NetBox REST API 写入
  │  --delete : 执行待删除项（默认仅报告不删）
  │
  ▼
NetBox (Docker Compose 部署，内网 Linux，单实例·多 Site)

rebuild_topology 扩展 --netbox --netbox-delete 开关
post_inspection hooks: 不加，手动触发
```

## 2. 决策记录

| # | 决策 | 选项 |
|---|------|------|
| 1 | NetBox 部署方式 | Docker Compose，内网 Linux，单实例双 Site |
| 2 | 与自建 CMDB 关系 | 双写：自建表不动，NetBox 旁路 |
| 3 | 同步模式 | 默认导文件，`--push` 调 pynetbox API |
| 4 | 数据来源 | `NewDevice`（身份）+ `DeviceParseResult`（解析） |
| 5 | 堆叠设备 | 自动拆 Virtual Chassis（`parse_irf` 成员） |
| 6 | Device Type 管理 | 首次遇到自动创建，后续人工精修不覆盖 |
| 7 | LLDP 链路 | Cable 物理连线，两阶段（先接口→后 Cable） |
| 8 | 接口类型 | 从 `speed_mbps` 自动推断 |
| 9 | IP 地址 | 绑 Interface，关联 VRF |
| 10 | VRF | 自动建 |
| 11 | 同步策略 | 增量 diff，仅增/改，`--delete` 执行删除 |
| 12 | 删除确认 | `--delete` 开关 + 终端报告 |
| 13 | Cable 创建 | 两阶段（同次运行内：先全部建接口 → 再建 Cable） |
| 14 | 命令入口 | `sync_netbox` 独立命令 + `rebuild_topology --netbox` |
| 15 | 巡检后自动钩子 | 不加（手动触发，避免 NetBox 宕机拖慢巡检） |
| 16 | Console Ports | 每种 Device Type 加 1 个 |
| 17 | Power Ports | `display power` → 新写 `parse_power` → 按数量建 |
| 18 | Module Bays | `display device` → 新写 `parse_device` → 板卡槽位 |
| 19 | VLAN Groups | 按 Site 自动创建 |
| 20 | Route Targets | `parse_running_config` 扩展，5 行代码 |
| 21 | NAT | 新写 `parse_nat` |
| 22 | Services | NTP / Syslog / DNS / SNMP from running-config |
| 23 | Front/Rear Ports | Device Type 面板模板，需人工提供端口布局 |
| 24 | Racks / Locations | CLI 不可达，等 Excel 导入 |
| 25 | Assets | 序列号自动填，资产编号/采购/维保 → Excel 导入 |

## 3. DCIM 覆盖矩阵

| NetBox 模型 | 自动化 | 数据来源 | 需要的新开发 |
|------------|:-----:|---------|------------|
| Sites | ✅ 全自动 | `NewDevice.site` | — |
| Locations | ❌ | Excel 导入 | — |
| Racks | ❌ | Excel 导入 | — |
| Manufacturers | ✅ seed | H3C 写死 | — |
| Platforms | ✅ seed | Comware 7 写死 | — |
| Device Types | ✅ 自动创建 | `parse_version` → model | — |
| Device Roles | ✅ | `NewDevice.role` → 映射 | — |
| Devices | ✅ | `NewDevice` + `DeviceParseResult` | — |
| Virtual Chassis | ✅ | `parse_irf` → 拆成员 | — |
| Interfaces | ✅ | `parse_interface_brief` | — |
| Console Ports | ✅ | Device Type 创建时 +1 | — |
| Power Ports | ✅ | `parse_power`（新写） | `parse_power()` |
| Front/Rear Ports | ⚠️ 需人工 | 设备面板规格书 | Device Type 面板模板 |
| Module Bays | ✅ | `parse_device`（新写） | `parse_device()` |
| Inventory Items | ✅ | `parse_manuinfo` + transceiver | — |
| Cables | ✅ | `parse_lldp` → 两阶段 | — |

## 4. IPAM 覆盖矩阵

| NetBox 模型 | 自动化 | 数据来源 | 需要的新开发 |
|------------|:-----:|---------|------------|
| VRFs | ✅ | `parse_running_config` | IP→VRF 关联修复 |
| Prefixes | ✅ | `parse_route_table` → 网络号 | — |
| IP Addresses | ✅ | `parse_running_config` → 绑 Interface + VRF | IP→VRF 关联修复 |
| VLANs | ✅ | `parse_vlan_brief` + running-config | — |
| VLAN Groups | ✅ | 按 Site 自动创建 | — |
| ASNs | ✅ | running-config 扩展 | 加两行正则 |
| Aggregates | ⚠️ | 路由表推导 / Excel | 非自动创建 |
| Services | ✅ | NTP/Syslog/DNS/SNMP from rc | `parse_running_config` 扩展 |
| FHRP Groups | ✅ | `parse_vrrp` | — |
| Route Targets | ✅ | `parse_running_config` 扩展 | 加两行正则 |
| NAT | ✅ | 新写 `parse_nat` | `parse_nat()` |
| L2VPN | ❌ | 不适用 | — |

## 5. Extras 覆盖矩阵

| NetBox 特性 | 自动化 | 说明 |
|------------|:-----:|------|
| Tags | ✅ | 站点 / 角色 / 协议自动打标 |
| Custom Fields | ✅ | `inspection_last_run` / `cpu_usage` / `memory_free` / `capabilities` |
| Config Contexts | ✅ | `capabilities` / `disabled_commands` 存入设备 |
| Journal Entries | ✅ | 每次同步记录变更摘要（增/改/删统计） |
| Webhooks | ✅ | NetBox 原生，配置 URL 即用 |
| Change Logging | ✅ | NetBox 原生，自动跟踪 ObjectChange |
| Assets | ⚠️ | SN 自动填，Asset Tag/采购/维保 → Excel 导入 |

## 6. 需要新增的解析器（`app02/parsers/comware.py`）

### 6.1 `parse_power(text)` — 电源

**输入**：`display power`

**输出**：`[{'id': '1', 'status': 'Normal', 'type': 'AC'}, ...]`

**NetBox 映射**：按数量在 Device 下建 Power Port；Inventory Item 记电源型号/状态

### 6.2 `parse_device(text)` — 设备槽位/板卡

**输入**：`display device`

**输出**：`[{'slot': '0', 'subslot': '0', 'type': 'M9000-X10', 'status': 'Normal'}, ...]`

**NetBox 映射**：主槽位 → Device 元数据；子卡槽位 → Module Bay；板卡 → Inventory Item

### 6.3 `parse_nat(text)` — NAT（防火墙）

**输入**：`display current-configuration` 中 NAT 相关段

**输出**：`[{'type': 'static', 'inside_ip': '...', 'outside_ip': '...', 'port': 443}, ...]`

**NetBox 映射**：`ipam.IPAddress` 的 NAT（inside/outside）关联

### 6.4 `parse_running_config` 扩展现有

| 扩展点 | 正则 | 输出字段 |
|-------|------|---------|
| IP→VRF 关联 | 接口块内记录 `vpn-instance` 上下文 | `ips[].vrf = vpn_instance_name` |
| Route Target | `route-target (import\|export) (\d+:\d+)` | `vrfs[].rt_import` / `vrfs[].rt_export` |
| ASN | `bgp \d+` 上下文 | AS 号 |
| Services | `ntp-service server (\S+)` / `info-center loghost (\S+)` / `dns server (\S+)` / `snmp-agent` | `services[]` |

## 7. 新增管理命令

### 7.1 `sync_netbox`

```bash
# 预览（只导文件）
python manage.py sync_netbox --site 化龙
python manage.py sync_netbox --site 知识城 --out netbox_fixtures/

# 推送写入
python manage.py sync_netbox --site 化龙 --push

# 推送 + 执行删除
python manage.py sync_netbox --site 化龙 --push --delete
```

内部流程：

```
Phase 0: seed_netbox  →  Site/Role/Manufacturer/Platform/VRF Group 基础数据
Phase 1: sync_devices →  upsert 每台 Device (含 Virtual Chassis 拆堆叠)
Phase 2: sync_interfaces →  按 Device 创建/更新 Interface
Phase 3: sync_ipam     →  VLAN/VLAN Group/IP Address/Prefix/VRF/FHRP/Service
Phase 4: sync_cables   →  两端 Interface 都存在 → 建 Cable
Phase 5: sync_extras   →  Tags/Custom Fields/Config Contexts/Journal Entry
Phase 6: diff_report   →  输出变更摘要 + 待删除清单
Phase 7: delete_stale  →  仅在 --delete 时执行，移除 NetBox 中已消失的数据
```

### 7.2 `rebuild_topology` 扩展

```bash
python manage.py rebuild_topology --site 化龙 --netbox --push
```

在 `--push` 已存在的 `subprocess` 调 network-seek 之后，追加 `sync_netbox --push`。

## 8. NetBox 基础数据 seed

`seed_netbox`（或集成在 `sync_netbox --push` 首次运行时自动执行）：

| 实体 | 内容 |
|------|------|
| Sites | 知识城、化龙 |
| Manufacturers | H3C（name=H3C, slug=h3c） |
| Platforms | Comware 7（name=Comware 7, slug=comware-7, manufacturer=h3c） |
| Device Roles | FW / CSW / ASW / LSW / SRP / OASW / PSW / USW / IDC |
| VLAN Groups | 知识城-VLANs / 化龙-VLANs |
| Custom Fields | `inspection_last_run`(date), `inspection_status`(text), `cpu_usage_5s`(int) |
| | `memory_free_pct`(int), `uptime_days`(int), `capabilities`(json) |

## 9. 接口类型自动推断

从 `parse_interface_brief` 的 `speed_mbps` 字段直接映射：

```python
SPEED_TO_IF_TYPE = {
    10:     '10base-t',
    100:    '100base-tx',
    1000:   '1000base-t',
    10000:  '10gbase-x-sfpp',
    25000:  '25gbase-x-sfpp',
    40000:  '40gbase-x-qsfpp',
    100000: '100gbase-x-qsfp28',
}
```

## 10. 堆叠设备 → Virtual Chassis

1. `NewDevice.name` 含 `&` 且 `parse_irf` 返回 `members[]` → 触发拆分
2. 从设备名提取成员名：`asw003&004.pri...xc` → members = `['asw003', 'asw004']`
3. NetBox 侧：
   - 先创建各成员 Device（name=`asw003`, `asw004`）
   - 创建 VirtualChassis（name=`asw003&004`, master=`asw003`）
   - 各成员 `.virtual_chassis` = VC 实例，`.vc_position` = 成员序号
4. 接口分配：接口名 `GE{member_id}/0/*` → `member_id` 对应的 Device
5. 管理 IP 挂在 Virtual Chassis 的 master 成员上

## 11. NetBox 部署

### 11.1 部署架构

```
内网 Linux Server (Docker)
  ├── PostgreSQL 16   (ports: 5432)
  ├── Redis 7          (ports: 6379)
  ├── NetBox 4.x       (ports: 8000 → 宿主 8080)
  └── netbox-docker 官方仓库
```

### 11.2 前置条件

| 项 | 最低要求 | 检查命令 |
|---|---------|---------|
| Docker | ≥ 24.0 | `docker --version` |
| Docker Compose | ≥ v2.20 | `docker compose version` |
| 磁盘空间 | ≥ 20 GB（镜像 + 数据库） | `df -h` |
| 内存 | ≥ 4 GB | `free -m` |
| 内网 IP | 静态 IP，后面 xunjian 要通过 REST API 访问 | `ip addr` |

### 11.3 安装步骤

#### Step 1: 获取 NetBox Docker 官方仓库

```bash
cd /opt
git clone -b release https://github.com/netbox-community/netbox-docker.git
cd netbox-docker
```

> 锁定稳定 release 分支（建议 NetBox 4.1 LTS），避免 `master` 踩坑。

#### Step 2: 覆盖环境变量

创建 `docker-compose.override.yml`（不修改官方模板）：

```yaml
version: '3.9'
services:
  netbox:
    ports:
      - "8080:8080"        # 内网访问端口（避开 8000，可能已被 xunjian 占用）
    environment:
      # 数据库
      DB_HOST: postgres
      DB_NAME: netbox
      DB_USER: netbox
      DB_PASSWORD: ChangeMe_DB_Pass_2026     # ← 改成你的
      # Redis
      REDIS_HOST: redis
      REDIS_CACHE_HOST: redis-cache
      # NetBox
      SECRET_KEY: "$(python3 -c 'import secrets; print(secrets.token_hex(50))')"
      ALLOWED_HOSTS: "*"
      SUPERUSER_NAME: admin
      SUPERUSER_EMAIL: admin@example.com
      SUPERUSER_PASSWORD: ChangeMe_Admin_2026   # ← 改成你的
      # 时区 & 语言
      TIME_ZONE: Asia/Shanghai
      LANGUAGE_CODE: zh-hans
      # 站点名
      SITE_TITLE: "广期所网络资产"
      SITE_DESCRIPTION: "化龙 + 知识城"
    volumes:
      - netbox-media:/opt/netbox/netbox/media
      - ./reports:/opt/netbox/netbox/reports
      - ./scripts:/opt/netbox/scripts

volumes:
  netbox-media:
```

#### Step 3: 拉取镜像并启动

```bash
docker compose pull
docker compose up -d
```

首次启动会自动执行 `migrate` + 创建超级用户。

#### Step 4: 等待启动完成

```bash
docker compose logs -f netbox | grep -E "Worker|listening|ready"
# 看到 "Listening on ..." 表示就绪，约 30-60 秒
```

#### Step 5: 访问验证

```bash
curl http://<内网IP>:8080/api/
# 返回 API 根节点 JSON → 成功
```

浏览器打开 `http://<内网IP>:8080`，用 `admin` / `ChangeMe_Admin_2026` 登录。

#### Step 6: 创建 API Token

在 NetBox UI 右上角头像 → **Profile & Settings** → **API Tokens** → **Add a token**

- Key: 勾选 **Write**
- 描述: `xunjian-sync`
- 复制生成的 Token（只显示一次）

### 11.4 xunjian 侧配置

在 `xunjian_system1/settings.py` 追加：

```python
# ─────── NetBox 联动 ───────
NETBOX_URL = 'http://<内网IP>:8080'          # 改成实际内网 IP
NETBOX_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxx'    # 上面生成的 Token
```

> `NETBOX_URL` 为空时，`sync_netbox` 只导文件、不调 API（安全默认）。

### 11.5 健康检查

```bash
# 检查容器状态
docker compose ps
# 预期: netbox / postgres / redis / redis-cache 四个 up

# 检查 API 连通（从 xunjian 所在机器）
curl -H "Authorization: Token $NETBOX_TOKEN" http://<内网IP>:8080/api/dcim/devices/
# 返回空列表 []  → 初次部署正常
```

### 11.6 备份策略

| 备份内容 | 方式 | 频率 |
|---------|------|------|
| PostgreSQL 数据 | `docker exec postgres pg_dump -U netbox netbox > backup.sql` | 每日 |
| Media 文件 | 挂载 `netbox-media` volume，宿主机 `docker cp` | 每周 |
| 配置文件 | `docker-compose.override.yml` 进 git | 每次修改后 |

> 生产级建议：`cron` + `rsync` 推送到备份服务器。

---

## 12. 开发阶段

### Phase A: 基础设施 + NetBox 安装（1-2 天）

- [ ] `app02/parsers/comware.py`: 新增 `parse_power()` / `parse_device()` / `parse_nat()`
- [ ] `app02/parsers/comware.py`: `parse_running_config` 扩展（IP→VRF / Route Target / ASN / Services）
- [ ] `app02/netbox/` 模块：`sync.py` / `seed.py` / `diff.py` / `mapper.py`
- [ ] `app02/management/commands/sync_netbox.py`

### Phase B: DCIM 核心同步（2-3 天）

- [ ] Device sync（含 Virtual Chassis 拆堆叠）
- [ ] Interface sync（含接口类型推断 + speed_mbps 映射）
- [ ] Console Port / Power Port / Module Bay
- [ ] Inventory Item（序列号、光模块）
- [ ] Cable（两阶段 LLDP）

### Phase C: IPAM 同步（1-2 天）

- [ ] VLAN + VLAN Group
- [ ] VRF + Route Target
- [ ] IP Address（绑 Interface + VRF）
- [ ] Prefix（路由表）
- [ ] FHRP Group（VRRP）
- [ ] Service（NTP/Syslog/DNS/SNMP）
- [ ] ASN

### Phase D: Extras（1 天）

- [ ] Tags / Custom Fields / Config Contexts
- [ ] Journal Entries
- [ ] NAT sync
- [ ] `rebuild_topology --netbox` 扩展

### Phase E: 端到端验证（1 天）

- [ ] `seed_netbox` 验证
- [ ] 单站点试跑 `sync_netbox --site 化龙 --push`
- [ ] diff report 验证
- [ ] `--delete` 验证
- [ ] 全量两站点跑通

## 13. 验收标准

- [ ] `python manage.py sync_netbox --site 化龙 --push` 成功写入所有设备
- [ ] NetBox UI 中可见 26 台化龙设备 + 76 台知识城设备（含正确角色/型号/接口）
- [ ] 堆叠设备正确拆分为 Virtual Chassis（如 asw003&004 → VC + 2 成员）
- [ ] LLDP Cable 连线在 NetBox 前面板可查看
- [ ] IP 地址正确绑定到 Interface 并关联 VRF
- [ ] VRRP FHRP Group 可查
- [ ] VLAN / VLAN Group / Prefix 与生产一致
- [ ] `sync_netbox` 增量模式：重复运行不产生重复数据
- [ ] `--delete` 模式：按报告确认后正确移除过期数据
- [ ] `rebuild_topology --netbox` 可一键完成 CMDB + 拓扑 + NetBox 全链路

## 14. 风险与约束

| 风险 | 缓解 |
|------|------|
| NetBox 内网不可达 | `sync_netbox` 默认只导文件，`--push` 失败不阻塞 |
| 设备命名不一致导致 Cable dangling | 依赖 LLDP System Name == 台账名（已知脆弱点，和 network-seek 同源） |
| Device Type 自动创建不完整 | 占位创建后人工在 NetBox UI 补充属性（u_height / is_full_depth / 面板布局） |
| 防火墙端口 8022 | `NewDevice.port` 已存储，连接层 `_build_conn_kwargs` 已支持，不影响同步 |
| NetBox 版本兼容 | 锁定 NetBox 4.x LTS |

---

> **后续待输入**：Front/Rear Ports 面板布局（每种型号的端口图）、Racks/Locations（Excel）、Asset Tag/采购/维保日期（Excel）
