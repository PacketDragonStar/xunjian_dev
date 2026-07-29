# NetBox 联动 · 任务看板

> 基于 `docs/netbox-integration-plan.md` v1 | 生成日期：2026-07-28
> 总估时：7–9 天 | 5 个 Phase

---

## 依赖关系图

```
Phase A ──────────────────────────────────────┐
  │  Ticket 1 (NetBox 部署)                    │
  │  Ticket 2 (解析器扩展)                     │
  │  Ticket 3 (netbox 模块骨架 + mapper)       │
  │  Ticket 4 (xunjian 侧 settings 配置)       │
  │                                            │
  └──────┬─────────────────────────────────────┤
         ▼                                     │
Phase B ────────────────────────────────────┐ │
  Ticket 5 (Device + Virtual Chassis)       │ │
  Ticket 6 (Interface + Console/Power)      │ │
  Ticket 7 (Module Bay + Inventory)         │ │
  Ticket 8 (Cable 两阶段)                   │ │
         │                                   │ │
         ▼                                   │ │
Phase C ──────────────────────────────────┐ │ │
  Ticket 9  (VLAN + VLAN Group + VRF)     │ │ │
  Ticket 10 (IP + Prefix + FHRP)          │ │ │
  Ticket 11 (Service + ASN + RouteTarget) │ │ │
         │                                 │ │ │
         ▼                                 │ │ │
Phase D ────────────────────────────────┐ │ │ │
  Ticket 12 (Tags + CustomFields + CC)  │ │ │ │
  Ticket 13 (Journal + NAT)             │ │ │ │
  Ticket 14 (rebuild_topology 扩展)     │ │ │ │
         │                               │ │ │ │
         ▼                               ▼ ▼ ▼ ▼
Phase E ──────────────────────────────────────
  Ticket 15 (端到端验证)
```

---

## Phase A: 基础设施（1–2 天）

### Ticket 1：NetBox 内网部署

- [ ] **Ticket 1**：在内网 Linux 服务器上用 Docker Compose 部署 NetBox 4.x LTS

**前置**：Docker ≥ 24.0 + Docker Compose ≥ v2.20，内网静态 IP

**步骤**：
1. `git clone -b release https://github.com/netbox-community/netbox-docker.git /opt/netbox-docker`
2. 创建 `docker-compose.override.yml`（按方案 §11.3 配置：端口 8080 / DB 密码 / 超级用户 / 时区中文）
3. `docker compose pull && docker compose up -d`
4. 等待 30-60s → `curl http://<IP>:8080/api/` 返回 JSON
5. NetBox UI 登录 → 创建 API Token（Write 权限，描述 `xunjian-sync`）
6. 配置备份 cron（PostgreSQL dump + media rsync）

**验收**：
- [ ] 浏览器访问 `http://<IP>:8080` → NetBox 登录页
- [ ] `curl http://<IP>:8080/api/` → 200 OK
- [ ] API Token 已生成并记录

---

### Ticket 2：新增 3 个解析器 + `parse_running_config` 4 项扩展

- [ ] **Ticket 2**：在 `app02/parsers/comware.py` 中扩展

**2.1 `parse_power(text)` — 新函数**

输入 `display power`，输出 `[{'id': '1', 'status': 'Normal', 'type': 'AC'}, ...]`

**2.2 `parse_device(text)` — 新函数**

输入 `display device`，输出 `[{'slot': '0', 'type': 'S6820-56HF', 'status': 'Normal'}, ...]`

**2.3 `parse_nat(text)` — 新函数**

输入 running-config 中 NAT 段，输出 `[{'type': 'static', 'inside_ip': '...', 'outside_ip': '...', 'port': 443}, ...]`

**2.4 `parse_running_config` 扩展**

| 扩展 | 改动 | 行数 |
|------|------|------|
| IP→VRF 关联 | 接口块内记录 `vpn-instance` 上下文，给同块 IP 注入 `vrf` | ~5 行 |
| Route Target | `route-target (import\|export) (\d+:\d+)` → `vrfs[].rt_*` | ~3 行 |
| ASN | `bgp \d+` → AS 号提取 | ~5 行 |
| Services | NTP server / info-center loghost / DNS server / SNMP 提取 | ~10 行 |

**验收**（run 单测）：
- [ ] `python manage.py test app02.tests` — 56 个全过，新增解析器不破坏已有
- [ ] Django shell 手动喂真实 `display power` 回显 → 返回电源列表
- [ ] Django shell 手动喂真实 `display device` 回显 → 返回板卡列表

---

### Ticket 3：`app02/netbox/` 模块骨架 + 映射层

- [ ] **Ticket 3**：创建 `app02/netbox/` 目录及核心模块

**新建文件**：

| 文件 | 职责 |
|------|------|
| `app02/netbox/__init__.py` | 模块入口 |
| `app02/netbox/client.py` | NetBox API 客户端（`get_or_create` / `upsert` / `delete_if_exists`，pynetbox 封装） |
| `app02/netbox/mapper.py` | 数据映射器（xunjian 数据 → NetBox 字段），含：<br>- `map_role(xunjian_role) → netbox_role_slug`<br>- `map_if_type(speed_mbps) → if_type_slug`<br>- `map_status(oper_status) → NetBox status`<br>- `split_stacked_device(name, irf_members) → (vc_name, member_names)` |
| `app02/netbox/seed.py` | `seed_netbox()`：Site/Role/Manufacturer/Platform/VLAN Group/Custom Fields 一次性创建 |
| `app02/netbox/sync.py` | 7 阶段同步主逻辑（见 Ticket 5-13） |
| `app02/netbox/diff.py` | 变更报告生成 + 待删除清单 |

**依赖**：`pip install pynetbox`（加到 `requirements.txt`）

**验收**：
- [ ] `python manage.py check` — 0 issues
- [ ] `from app02.netbox.client import NetBoxClient` 不报 ImportError
- [ ] `python -c "from app02.netbox.mapper import *"` 0 error

---

### Ticket 4：xunjian `settings.py` NetBox 配置

- [ ] **Ticket 4**：追加 NetBox 配置块

```python
# ─────── NetBox 联动 ───────
NETBOX_URL = 'http://<内网IP>:8080'          # 空字符串 = 只导文件
NETBOX_TOKEN = ''                            # API Token
```

> 初始置空，内网部署后填入。

**验收**：
- [ ] `python manage.py check` — 0 issues
- [ ] `python manage.py shell -c "from django.conf import settings; print(settings.NETBOX_URL)"` — 输出 `http://<IP>:8080`

---

## Phase B: DCIM 核心同步（2–3 天）

### Ticket 5：Device + Virtual Chassis 同步

- [ ] **Ticket 5**：`sync.py` Phase 1 — 设备同步

**逻辑**：
1. 遍历 `NewDevice.objects.filter(enabled=True, site=site)`
2. 查 `DeviceParseResult` 拿 `parse_version` → model/serial/uptime
3. NetBox: upsert Device（site/device_type/role/serial/status=active）
4. 堆叠设备（name 含 `&` + `parse_irf` 有成员）：
   - 拆分为 Virtual Chassis + 成员 Device
   - 接口按 `GE{member_id}/0/*` 分配归属 Device
5. 输出 diff report: 新增 X 台，更新 Y 台

**验收**：
- [ ] 单台非堆叠设备 → NetBox 出现对应 Device
- [ ] 堆叠设备（如 asw003&004）→ Virtual Chassis + 2 个成员 Device
- [ ] 重复运行 → 无重复数据（幂等 upsert）

---

### Ticket 6：Interface + Console Port + Power Port 同步

- [ ] **Ticket 6**：`sync.py` Phase 2 — 接口同步

**逻辑**：
1. 遍历每台 Device 的 `parse_interface_brief` → 获取接口列表
2. 每个 Interface：`name` / `type`（speed_mbps → if_type） / `enabled`（oper_status） / `vlan`（pvid）
3. 同时建：
   - **Console Port**：每种 Device Type 建 1 个 `console-1`
   - **Power Port**：`parse_power` 返回几个就建几个（`power-1` / `power-2` / ...）
4. 输出 diff: 新增 X 接口，更新 Y 接口

**验收**：
- [ ] NetBox Device 详情页 → Interfaces 列表完整
- [ ] 接口类型正确（GE → 1000base-t, XGE → 10gbase-x-sfpp）
- [ ] Console Port 1 个，Power Port 数量 = `display power` 电源数

---

### Ticket 7：Module Bay + Inventory Item 同步

- [ ] **Ticket 7**：`sync.py` Phase 2 补充

**逻辑**：
1. `parse_device` → 槽位列表 → 主槽位 Device 元数据，子卡 → Module Bay
2. `parse_manuinfo` → 序列号 → Inventory Item（板卡/子卡 SN）
3. `display transceiver diagnosis interface` → 光模块 SN/型号 → Inventory Item（绑接口）

**验收**：
- [ ] 模块化设备（如防火墙 M9000）→ Module Bay 可见
- [ ] Inventory Items 列表可查到板卡 SN 和光模块 SN

---

### Ticket 8：Cable 同步（两阶段 LLDP）

- [ ] **Ticket 8**：`sync.py` Phase 4 — Cable 同步

**逻辑**：
1. 确保 Phase 2 全部 Device 的 Interface 已创建（Cable 前置条件）
2. 遍历 `parse_lldp` → `(src_dev, src_intf, dst_dev, dst_intf)` 
3. 两端 Interface 都存在 → 建 Cable（`termination_a_type='dcim.interface', ...`）
4. 对端不存在 → 跳过，记录到 diff report "跳过的 Cable"

**验收**：
- [ ] 两条真实 LLDP 邻居 → NetBox Cable 列表可见
- [ ] NetBox 前面板视图 → 连线展示
- [ ] LLDP 对端尚未同步的设备 → 跳过不报错，下次自动补

---

## Phase C: IPAM 同步（1–2 天）

### Ticket 9：VLAN + VLAN Group + VRF 同步

- [ ] **Ticket 9**：`sync.py` Phase 3 — VLAN/VRF

**逻辑**：
1. `seed_netbox` 建 VLAN Group（按 Site：`化龙-VLANs` / `知识城-VLANs`）
2. `parse_vlan_brief` + `parse_running_config` → VLAN 列表
3. NetBox: upsert VLAN（vid/name/group/site）
4. `parse_running_config` → VRF 列表 + Route Target
5. NetBox: upsert VRF（name/rd/route_targets）
6. IRF 接口 `ip binding vpn-instance X` → VRF 自动关联

**验收**：
- [ ] NetBox VLAN 列表 → 化龙 + 知识城 VLAN 齐全
- [ ] VLAN 归属于正确的 VLAN Group
- [ ] VRF 列表包含所有多 VRF 实例 + Route Target

---

### Ticket 10：IP Address + Prefix + FHRP Group 同步

- [ ] **Ticket 10**：`sync.py` Phase 3 — IP/Prefix/FHRP

**逻辑**：
1. `parse_running_config` → IPs（interface_name/cidr/vrf）
2. NetBox: upsert IP Address → 绑定到对应 Interface + VRF
3. `parse_route_table` → 网络号 → NetBox Prefix（status=active，site 范围）
4. `parse_vrrp` → FHRP Group（group_id / virtual_ip / protocol=VRRP / auth_type=plaintext）
5. FHRP Group 关联到对应 Interface

**验收**：
- [ ] Device 详情页 → IP Address 列表完整（含 VRF 归属）
- [ ] Prefix 列表可见 IP 子网
- [ ] VRRP 设备 → FHRP Group 可见，含 Virtual IP

---

### Ticket 11：Service + ASN + Route Target 同步

- [ ] **Ticket 11**：`sync.py` Phase 3 — 补充 IPAM

**逻辑**：
1. `parse_running_config` 扩展 → Services（NTP/Syslog/DNS/SNMP）
2. NetBox: upsert Service（name/protocol/ports）绑定到 Device
3. running-config → ASN → NetBox IPAM ASN
4. Route Target 已在 Ticket 9 VRF 中处理

**验收**：
- [ ] Device Services 列表含 NTP / Syslog / DNS 配置
- [ ] ASN（如有 BGP 设备）→ IPAM ASN 列表可见

---

## Phase D: Extras（1 天）

### Ticket 12：Tags + Custom Fields + Config Contexts 同步

- [ ] **Ticket 12**：`sync.py` Phase 5 — 元数据

**逻辑**：
1. Tags：按 site / role / capabilities 自动打标（如 `hualong` / `fw` / `ospf` / `vrrp` / `irf`）
2. Custom Fields：
   - `inspection_last_run` ← 本次巡检时间
   - `cpu_usage_5s` ← 最新 `parse_cpu_usage`
   - `memory_free_pct` ← 最新 `parse_memory_free`
   - `uptime_days` ← `parse_version`
   - `capabilities` ← `NewDevice.extra['capabilities']` JSON
3. Config Contexts：`{'capabilities': [...], 'disabled_commands': [...]}` 存 Device

**验收**：
- [ ] NetBox Device 详情 → Tags 可见
- [ ] Custom Fields 有值（cpu/memory/uptime/capabilities）
- [ ] Config Contexts 含能力清单

---

### Ticket 13：Journal Entries + NAT 同步

- [ ] **Ticket 13**：`sync.py` Phase 5 补充

**逻辑**：
1. 每次同步跑完后，在每台有变更的 Device 写 Journal Entry：
   「2026-07-28 sync_netbox: 新增接口 2, 更新 IP 3, 跳过 Cable 1。巡检状态: pass」
2. `parse_nat` → NAT rules → NetBox IPAM NAT（inside/outside 关联）

**验收**：
- [ ] NetBox Device Journal 有同步记录
- [ ] NAT 规则在 IPAM → NAT 列表可见

---

### Ticket 14：`rebuild_topology --netbox` 扩展

- [ ] **Ticket 14**：在 `app02/management/commands/rebuild_topology.py` 中加开关

```bash
python manage.py rebuild_topology --site 化龙 --push --netbox --netbox-delete
```

内部在 `--push` 流程末尾追加 `call_command('sync_netbox', site=site, push=True, delete=netbox_delete)`。

**验收**：
- [ ] `rebuild_topology --site 化龙 --netbox` → 执行 CMDB sync + export + network-seek + NetBox 全链
- [ ] 不加 `--netbox` 时行为不变

---

## Phase E: 端到端验证（1 天）

### Ticket 15：内网端到端验证

- [ ] **Ticket 15**：在内网真机环境跑通全链路

**步骤**：
1. **部署**：确认 NetBox 容器运行正常，API 可达
2. **配置**：`settings.py` 填入 `NETBOX_URL` + `NETBOX_TOKEN`
3. **seed**：`python manage.py sync_netbox --site 化龙`（第一次自动 seed 基础数据）
4. **首跑**：`python manage.py sync_netbox --site 化龙 --push`
5. **验证**：
   - 所有设备在 NetBox 中可见
   - 堆叠正确拆分 VC
   - 接口/VLAN/IP/VRF/Cable 量与 `sync_cmdb` 自建 CMDB 交叉核对
6. **增量**：重复跑 `sync_netbox --push`，确认零报错、零重复
7. **删除**：`sync_netbox --push --delete` 终���报告，确认待删清单合理
8. **知识城**：重复 3-7 步骤
9. **一键联动**：`rebuild_topology --site 化龙 --push --netbox` 全链路跑通

**验收标准**（全部打勾才算过）：
- [ ] NetBox 中化龙 26 台 + 知识城 76 台设备可见
- [ ] 堆叠设备拆分为 Virtual Chassis（化龙 ASW×6 / PSW×2 / SRP×1 / OASW×N，知识城 OASW×4）
- [ ] LLDP Cable 连线可查
- [ ] IP 绑 Interface 且关联 VRF
- [ ] VRRP FHRP Group 可查
- [ ] VLAN/VLAN Group/Prefix 与生产一致
- [ ] 增量模式：重复运行不产生重复
- [ ] `--delete` 实时报告待删除项
- [ ] `rebuild_topology --netbox` 一键完成全链路

---

## 完成检查清单

- [ ] `python manage.py test app02.tests` → 56+ 全过
- [ ] `python manage.py check` → 0 issues
- [ ] NetBox Docker 容器 → 4 个 up
- [ ] `curl <NETBOX_URL>/api/` → 200
- [ ] `sync_netbox --site 化龙 --push` → 0 报错
- [ ] `sync_netbox --site 知识城 --push` → 0 报错
- [ ] `rebuild_topology --site 化龙 --push --netbox` → 全链路打通
