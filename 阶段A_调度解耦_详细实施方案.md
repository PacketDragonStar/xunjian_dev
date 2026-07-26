# 阶段 A · 调度解耦（精简版）详细实施方案

> 适用前提：**每天由人工手动触发巡检**，无定时调度需求；内网运行、不引入 Redis/Celery 等新组件。
> 目标：点击巡检后 Web 立即返回、不阻塞；可看实时进度；失败设备可一键续跑。
> 前身文档：原《阶段A_调度解耦_详细实施方案.md》（含 Redis+Celery+定时，已废弃）

---

## 1. 方案定位与取舍

| 需求 | 是否保留 | 说明 |
|------|----------|------|
| 点击后不阻塞 UI | ✅ | 用 Django 后台线程执行，请求立即返回 `task_id` |
| 实时进度 | ✅ | `XunjianTask` 表记录 done/total，前端轮询 |
| 失败设备续跑 | ✅ | `failed_devices` 列表驱动续跑 |
| 定时调度（cron/beat） | ❌ 删除 | 你每天手动触发，不需要 |
| Redis / Celery / beat | ❌ 删除 | 不引入任何新服务、新进程 |
| 独立 worker 进程 | ❌ 删除 | 线程跑在现有 Django 进程内即可 |

> **唯一代价**：若巡检进行中 Django 服务被重启，后台线程会中断（任务停在"执行中"）。因是白天在场手动触发，遇此情况重跑一次即可，可接受。

---

## 2. 总体数据流

```
[浏览器] --POST /new/xunjian/--> [Django view]
                              |  1. 建 XunjianTask(status=排队)
                              |  2. threading.Thread(target=run_xunjian, task_id=...).start()
                              |  3. 立即返回 {task_id}
                              v
[后台线程] run_xunjian:
   - 置 status=执行中
   - 逐设备并发(线程池)执行
   - 每完成一台 → 回写 XunjianTask.done / failed / failed_devices
   - 结束 → status=完成/部分失败/失败
                              v
[MySQL] XunjianTask + XunjianRecord + CheckResult + AnomalyRecord

[浏览器] --每3秒 GET /new/task/detail/?task_id=xxx--> [Django] --> 读 XunjianTask --> JSON
[浏览器] --POST /new/task/<id>/resume/--> [Django] --> 新建 XunjianTask(仅失败设备) --> 启线程
```

---

## 3. 新增 / 修改文件清单

| 类别 | 文件 | 动作 |
|------|------|------|
| 新增模型 | `app02/models.py`（追加） | `XunjianTask` 模型 |
| 修改 | `app02/engine/executor.py` | `run_xunjian` 增加 `task_id` + 进度回写 + 异常捕获识别失败设备 |
| 修改 | `app02/views.py` | `new_run_xunjian` 异步化（启线程）；新增任务列表/详情/续跑视图 |
| 修改 | `xunjian_system1/urls.py` | 注册任务相关路由 |
| 新增 | `app02/templates/.../task_list.html` | 任务中心列表页 |
| 新增 | `app02/templates/.../task_detail.html` | 任务详情页（进度条 + 失败清单 + 续跑按钮） |
| 新增 | `app02/static/.../task_poll.js` | 前端轮询脚本 |
| **不改动** | `requirements.txt` / 部署配置 | 无需新增依赖与进程 |

---

## 4. 详细步骤

### 4.1 任务表模型（app02/models.py 追加）

```python
import uuid
from django.db import models

TASK_STATUS = (
    ('queued',  '排队中'),
    ('running', '执行中'),
    ('success', '完成'),
    ('partial', '部分失败'),
    ('failed',  '失败'),
)

class XunjianTask(models.Model):
    task_id        = models.CharField(max_length=36, unique=True,
                                      default=lambda: str(uuid.uuid4()), verbose_name='任务ID')
    operator       = models.CharField(max_length=50, verbose_name='操作人')
    scope_type     = models.CharField(max_length=10,
                                      choices=(('checkset','检查集'),('device','指定设备')),
                                      verbose_name='范围类型')
    scope_ids      = models.JSONField(default=list, verbose_name='范围ID列表')
    status         = models.CharField(max_length=10, choices=TASK_STATUS,
                                      default='queued', verbose_name='状态')
    total          = models.IntegerField(default=0, verbose_name='设备总数')
    done           = models.IntegerField(default=0, verbose_name='已完成')
    failed         = models.IntegerField(default=0, verbose_name='失败数')
    failed_devices = models.JSONField(default=list, verbose_name='失败设备名列表', blank=True)
    xj_time        = models.CharField(max_length=50, null=True, blank=True, verbose_name='关联巡检时间')
    summary        = models.TextField(blank=True, null=True, verbose_name='结果摘要')
    created_at     = models.DateTimeField(auto_now_add=True)
    started_at     = models.DateTimeField(null=True, blank=True)
    finished_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = '巡检任务'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]
```

```bash
python manage.py makemigrations app02
python manage.py migrate
```

### 4.2 巡检逻辑改造（app02/engine/executor.py）

把 `run_xunjian` 的 `executor.map(...)` 改为 `as_completed` + 异常捕获，并通过 `task_id` 回写进度。

```python
# app02/engine/executor.py （片段）
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.db import close_old_connections
from app02.models import XunjianTask

def run_xunjian(operator, device_ids=None, checkset_id=None, task_id=None):
    close_old_connections()                      # 线程内新建独立 DB 连接
    time_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    devices  = _resolve_devices(device_ids, checkset_id)
    check_items = _collect_check_items(devices)

    task = XunjianTask.objects.filter(task_id=task_id).first() if task_id else None
    if task:
        task.status = 'running'; task.total = len(devices)
        task.started_at = datetime.now()
        task.save(update_fields=['status','total','started_at'])

    record = XunjianRecord.objects.create(
        time=time_str, operator=operator, device_count=len(devices), ...)

    results = []
    failed_devices = []
    with ThreadPoolExecutor(max_workers=min(32, len(devices)+4)) as ex:
        futures = {ex.submit(xunjian_one_device, d, check_items, time_str): d
                   for d in devices}
        for fut in as_completed(futures):
            dev = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                failed_devices.append(dev.name)
                _new_logger.error(f'设备 {dev.name} 巡检失败: {e}')
            if task:
                task.done = task.done + 1
                task.failed = len(failed_devices)
                task.failed_devices = failed_devices
                task.save(update_fields=['done','failed','failed_devices'])
                close_old_connections()           # 防止长连接空闲超时

    # 原 _build_report / 写 CheckResult / AnomalyRecord 逻辑保持不变
    report = _build_report(results, time_str)

    if task:
        task.status = 'failed' if not results else ('partial' if failed_devices else 'success')
        task.xj_time = time_str
        task.finished_at = datetime.now()
        task.summary = f"设备 {len(devices)} 台，正常 {len(results)}，失败 {len(failed_devices)}"
        task.save(update_fields=['status','xj_time','finished_at','summary','failed_devices'])
        close_old_connections()
    return {'time': time_str, 'result': ..., 'report': report, 'cli_output': ...}
```

> 关键：`as_completed` 替代 `map`，单设备异常**不再中断整批**；失败设备名落入 `failed_devices`，供续跑使用。

### 4.3 视图改造（app02/views.py）

`new_run_xunjian` 改为"建任务 → 启线程 → 秒回 task_id"：

```python
import threading
from app02.engine.executor import run_xunjian
from app02.models import XunjianTask, NewDevice

@csrf_exempt
def new_run_xunjian(request):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'error': '仅支持POST'}, status=405)
    operator = request.session.get('info', {}).get('name', '未知')
    device_ids = [int(i) for i in request.POST.getlist('device_ids') if i] or None
    checkset_id = request.POST.get('checkset_id')
    checkset_id = int(checkset_id) if checkset_id else None

    scope_type = 'checkset' if checkset_id else 'device'
    scope_ids  = [checkset_id] if checkset_id else device_ids
    task = XunjianTask.objects.create(
        operator=operator, scope_type=scope_type,
        scope_ids=scope_ids or [], status='queued')
    t = threading.Thread(
        target=run_xunjian,
        kwargs={'operator': operator, 'device_ids': device_ids,
                'checkset_id': checkset_id, 'task_id': task.task_id},
        daemon=True)
    t.start()
    return JsonResponse({'status': True, 'task_id': task.task_id})
```

任务详情（供前端轮询）：

```python
def new_task_detail(request):
    task_id = request.GET.get('task_id')
    task = XunjianTask.objects.filter(task_id=task_id).first()
    if not task:
        return JsonResponse({'status': False, 'error': '任务不存在'}, status=404)
    return JsonResponse({
        'status': True,
        'task_id': task.task_id,
        'status_label': task.get_status_display(),
        'done': task.done, 'total': task.total, 'failed': task.failed,
        'failed_devices': task.failed_devices,
        'xj_time': task.xj_time,
        'summary': task.summary,
        'finished': task.status in ('success', 'partial', 'failed'),
    })
```

续跑（仅失败设备）：

```python
@csrf_exempt
def new_task_resume(request):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'error': '仅支持POST'}, status=405)
    task_id = request.POST.get('task_id')
    old = XunjianTask.objects.filter(task_id=task_id).first()
    if not old:
        return JsonResponse({'status': False, 'error': '任务不存在'}, status=404)
    failed_names = old.failed_devices or []
    if not failed_names:
        return JsonResponse({'status': False, 'error': '无失败设备可续跑'}, status=400)
    dev_ids = list(NewDevice.objects.filter(name__in=failed_names, enabled=True)
                   .values_list('id', flat=True))
    if not dev_ids:
        return JsonResponse({'status': False, 'error': '失败设备未匹配到资产'}, status=400)
    operator = request.session.get('info', {}).get('name', '未知')
    task = XunjianTask.objects.create(
        operator=operator, scope_type='device',
        scope_ids=dev_ids, status='queued', total=len(dev_ids))
    t = threading.Thread(
        target=run_xunjian,
        kwargs={'operator': operator, 'device_ids': dev_ids, 'task_id': task.task_id},
        daemon=True)
    t.start()
    return JsonResponse({'status': True, 'task_id': task.task_id})
```

任务列表（页面用，按时间倒序）：`new_task_list` 直接 `XunjianTask.objects.all()` 渲染到 `task_list.html`。

### 4.4 路由（xunjian_system1/urls.py）

```python
path('new/task/list/',        views.new_task_list,    name='new_task_list'),
path('new/task/detail/',      views.new_task_detail,  name='new_task_detail'),
path('new/task/<str:task_id>/resume/', views.new_task_resume, name='new_task_resume'),
# new_run_xunjian 已有
```

### 4.5 前端任务中心

`task_list.html`：表格展示任务（状态彩色标签 + 进度条 `<progress>`），列表项点击进入详情。

`task_detail.html` + `task_poll.js`：

```javascript
// task_poll.js —— 进入详情页后启动轮询
const taskId = document.getElementById('task-id').value;
const timer = setInterval(async () => {
  const r = await fetch(`/new/task/detail/?task_id=${taskId}`);
  const d = await r.json();
  if (!d.status) return;
  document.getElementById('progress').value = d.total ? d.done / d.total : 0;
  document.getElementById('status').textContent = d.status_label;
  document.getElementById('summary').textContent = d.summary || '';
  if (d.finished) {
    clearInterval(timer);
    renderResult(d);                       // 渲染最终结果与失败设备清单
    if (d.failed_devices && d.failed_devices.length)
      document.getElementById('resume-btn').style.display = 'inline';
  }
}, 3000);
```

`续跑` 按钮：`POST /new/task/<task_id>/resume/` → 拿到新 `task_id` → 跳转到新任务详情页。

> 原"立即执行"按钮改为：提交后跳转/打开任务详情页（而非原地等 JSON 返回结果）。

---

## 5. 执行顺序与验证点

| 步骤 | 内容 | 验证点 |
|------|------|--------|
| 1 | 模型 `XunjianTask` + migrate | 表生成，admin 可见 |
| 2 | executor 改造（task_id + 进度 + 异常捕获） | 单测：注入 mock 设备，验证失败设备被记录且整批不中断 |
| 3 | `new_run_xunjian` 启线程 + 返回 task_id | 点击后页面秒回，DB 出现 queued→running 任务 |
| 4 | 任务详情 + 列表视图 + 路由 | 轮询能看到 done 递增 |
| 5 | 前端任务中心 + 轮询 | 进度条实时推进，完成展示结果 |
| 6 | 续跑视图 | 失败设备可一键重跑，新任务仅含失败设备 |

---

## 6. 验收标准（对照精简版目标）

- [ ] 点击巡检后页面**秒回**，不再随设备数增长而阻塞
- [ ] 任务详情页进度条实时推进（done/total）
- [ ] 单设备失败**不中断整批**，失败设备进入 `failed_devices`
- [ ] "续跑失败设备"仅重跑失败部分
- [ ] 全程**未新增任何依赖、进程或服务**（无 Redis/Celery/worker）

---

## 7. 风险与注意

| 风险 | 缓解 |
|------|------|
| Django 服务重启致线程中断 | 任务停"执行中"；手动重跑即可（你每天在场触发，可接受） |
| 后台线程 DB 连接空闲超时（MySQL gone away） | 进度回写处调用 `close_old_connections()`；长巡检中连接随写操作保持活跃 |
| 多线程并发写 `XunjianTask` | 每次仅 `update_fields` 少量字段，单任务单线程写，无竞争 |
| gunicorn 多 worker | 线程落在接收请求的 worker 内；轮询读 MySQL，不受 worker 归属影响 |
| 历史结果归属 | 续跑产生独立 `xj_time` 的新记录，与原任务分开，符合"续跑=再跑一次"语义 |

---

## 8. 工作量估算（单人）

| 子项 | 规模 |
|------|------|
| 任务表模型 + 迁移 | S（0.5d） |
| executor 改造 | M（1d，含单测） |
| 视图（异步化 + 列表/详情/续跑） | M（1d） |
| 前端任务中心 + 轮询 | M（1d） |
| 联调 | S（0.5d） |
| **合计** | **约 3.5~4 人天** |

---

## 下一步

完成 A 后建议进入 **阶段 B（收敛双引擎）**：旧→新数据迁移时直接关联 `XunjianTask` 体系，避免二次改造。需要可继续出 B 的详细方案。
