import os
import re
import difflib
from bs4 import BeautifulSoup
from datetime import datetime
from nornir.core.task import Result
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import render, HttpResponse, redirect
from django.views.decorators.csrf import csrf_exempt
from app02.models import device_table, ConfigBackup
from app02.utils.nornir_init import nornir_init
from app02.utils.bootstrap import BootstrapModelForm
from app02.utils.pagination import Pagination


def filter_time_from_output(platform, output):
    if platform == 'cisco_nxos':
        return re.sub(r"!Time:\s(.+)", "", output)
    elif platform == 'huawei':
        return re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", output)
    # 可以添加更多平台的处理逻辑
    return output


PLATFORM_BACKUP_INFO = {
    'cisco_nxos': {'commands': ['show running-config'],
                   'time_filter': filter_time_from_output},
    'huawei': {'commands': ['display current-configuration'],
               'time_filter': filter_time_from_output
               },
    # 可以添加更多平台的配置
}


class ConfigBackupModelForm(BootstrapModelForm):
    class Meta:
        model = ConfigBackup
        fields = '__all__'


class DeviceModelForm(BootstrapModelForm):
    class Meta:
        model = device_table
        fields = '__all__'
        exclude = ['conn_timeout', 'timeout']


def conf_backup_list(request):
    """ 备份列表 """
    search_fields = ['cmd', 'dev__device', 'dev__ip']  # 允许搜索的字段列表
    search_data = request.GET.get('query', '').strip()  # 获取搜索词并去除空白字符
    order_by = request.GET.get('order_by', '-created_time').strip()  # 获取排序方式，默认为创建时间倒序

    query = Q()  # 创建一个空的Q对象
    # 为每个搜索字段构建Q查询条件
    for field in search_fields:
        # 如果字段包含 '__'，则跨关系的查询
        if '__' in field:
            # 使用icontains进行不区分大小写的包含搜索
            # 这里需要确保字段路径正确，例如 'dev__name'
            query |= Q(**{f'{field}__icontains': search_data})
        else:
            # 对于非跨关系的字段，直接使用icontains
            query |= Q(**{f'{field}__icontains': search_data})
            # 应用查询条件
    queryset = ConfigBackup.objects.filter(query).order_by(order_by)

    form = ConfigBackupModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        "queryset": page_object.page_queryset,  # 分完页的数据
        "page_string": page_object.html(),  # 生成页码
        'search_data': search_data,
        'order_by': order_by,
    }
    return render(request, 'conf_backup_list.html', context)


def select_device(request):
    """ 选择设备 """
    search_fields = ['ip', 'platform', 'vendor', 'name', 'model']
    search_data = request.GET.get('query', '').strip()  # 去除可能的空白字符
    query = Q()  # 创建一个空的Q对象
    for field in search_fields:
        query |= Q(**{f'{field}__icontains': search_data})  # 使用f-string动态构建字段名

    # 根据搜索条件去数据库获取
    queryset = device_table.objects.filter(query)

    # queryset = models.Devices.objects.all()
    form = DeviceModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        'search_data': search_data
    }
    return render(request, 'select_device.html', context)

@csrf_exempt
def save_notes(request):
    if request.method == 'POST':
        config_backup_ids = request.POST.get('ids', '').split(',')
        notes = request.POST.get('notes', '')
        success_count = 0
        for backup_id in config_backup_ids:
            try:
                backup = ConfigBackup.objects.get(id=backup_id)
                backup.notes = notes  # 假设你的模型中有一个名为 'notes' 的字段
                backup.save()  # 保存更改到数据库
                success_count += 1
            except ConfigBackup.DoesNotExist:
                continue
                # 根据需要返回适当的响应
        if success_count == 0:
            return JsonResponse({'status': 'error', 'message': '没有找到任何设备来保存备注。'}, status=404)
        elif success_count < len(config_backup_ids):
            # 如果有一些ID不存在，但仍然有成功的更新
            return JsonResponse(
                {'status': 'success', 'message': f'备注已成功保存到{success_count}个设备，但一些ID不存在。'}, status=200)
        else:
            return JsonResponse({'status': 'success', 'message': '备注已成功保存到所有设备。'}, status=200)
    return JsonResponse({'status': 'error', 'message': '无效的请求方法。'}, status=400)


def conf_backup_add(request):
    if request.method == 'POST':
        selected_devs = request.POST.get('selected_devs', '').split(',')
        selected_devs = [int(dev_id) for dev_id in selected_devs if dev_id.isdigit()]  # 清理和转换ID
        selected_devices = device_table.objects.filter(id__in=selected_devs)
        result = batch_backup_config(selected_devices)
        return JsonResponse({
            'success': True,
            'success_num': result['success_num'],
            'fail_num': result['fail_num'],
            'fail_dev': result['fail_dev'],
        })

    elif request.method == "GET":
        # 调用批量配置备份的函数
        queryset = device_table.objects.all()
        result = batch_backup_config(queryset)
        # 组织返回给用户的信息
        # 这里可以返回JSON格式的数据给前端
        return JsonResponse({
            'success': True,
            'success_num': result['success_num'],
            'fail_num': result['fail_num'],
            'fail_dev': result['fail_dev'],
        })
        # 如果不是GET请求，你可能需要返回一个错误或重定向
    else:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


def conf_backup_download(request, uid):
    try:
        backup = ConfigBackup.objects.get(id=uid)
        if backup.config_file and os.path.exists(backup.config_file.path):
            # 打开文件
            with open(backup.config_file.path, 'rb') as f:
                response = HttpResponse(f, content_type='application/octet-stream')
                response['Content-Disposition'] = 'attachment; filename="{}"'.format(backup.config_file.name)
                return response
        else:
            # 如果文件不存在，返回错误响应
            return HttpResponse("文件不存在", status=404)
    except ConfigBackup.DoesNotExist:
        # 如果城市不存在，返回错误响应
        return HttpResponse("配置不存在", status=404)


def conf_backup_view(request, uid):
    try:
        backup = ConfigBackup.objects.get(id=uid)
        if backup.config_file and os.path.exists(backup.config_file.path):
            with open(backup.config_file.path, 'r', encoding='utf-8') as f:
                file_content = f.read()
            context = {
                'file_content': file_content,
                'backup': backup,
            }
            return render(request, 'conf_backup_view.html', context)
        else:
            return HttpResponse("文件不存在", status=404)
    except ConfigBackup.DoesNotExist:
        return HttpResponse("配置不存在", status=404)


def diff_view(request, uid):
    config_now = ConfigBackup.objects.get(id=uid)
    if config_now.config_file and os.path.exists(config_now.config_file.path):
        with open(config_now.config_file.path, 'r', encoding='utf-8') as f:
            now_config = f.readlines()
    last_success_backup = ConfigBackup.objects.filter(
        dev=config_now.dev,
        backup_status='success'
    ).exclude(id=uid).order_by('-created_time').first()

    if last_success_backup:
        with open(last_success_backup.config_file.path, 'r', encoding='utf-8') as f:
            last_config = f.readlines()
    else:
        last_config = []
    d = difflib.HtmlDiff()
    html_diff = d.make_file(now_config, last_config, '现网配置', '基线配置')

    # 使用BeautifulSoup解析html_diff字符串
    soup = BeautifulSoup(html_diff, 'html.parser')
    # 查找所有带有nowrap属性的td元素，并移除这些属性
    for td in soup.find_all('td', attrs={'nowrap': True}):
        del td['nowrap']
        # 将修改后的BeautifulSoup对象转换回HTML字符串
    cleaned_html_diff = str(soup)
    # 返回渲染后的模板，使用清理后的html_diff
    return render(request, 'diff_view.html', {'html_diff': cleaned_html_diff})


class Result:
    def __init__(self, host, result, failed=False, error=None):
        self.host = host
        self.result = result
        self.failed = failed
        self.error = error


def backup_config(task_context):
    host = task_context.host
    platform = host.platform
    dev_obj = device_table.objects.filter(name=host.name).first()
    result_msg = f'{host.name}配置备份开始'
    try:
        if platform in PLATFORM_BACKUP_INFO:
            config_info = PLATFORM_BACKUP_INFO[platform]
            # 获取Netmiko连接
            net_conn = task_context.host.get_connection('netmiko', task_context.nornir.config)
            # secret参数可以直接从Netmiko连接中获取
            if net_conn.secret:
                net_conn.enable()
            # 获取对应平台要执行的配置备份命令

            for cmd in config_info['commands']:
                output = net_conn.send_command(cmd)
                filtered_output = config_info['time_filter'](platform, output)  # 过滤了show run的当前时间
                # 配置备份文本文件名称
                date_time = datetime.now().strftime('%H-%M-%S')
                file_name = '{}_{}_{}.txt'.format(host.name, host.hostname, date_time)
                # 构建一个ContentFile对象用于赋值给配置备份ConfigBackup对象的config_file字段
                config_content = ContentFile(content=filtered_output, name=file_name)

                # 查找上一个成功的备份
                last_success_backup = ConfigBackup.objects.filter(
                    dev=dev_obj,
                    backup_status='success'
                ).order_by('-created_time').first()

                config_changed = '未知'  # 初始化为未知
                if last_success_backup:
                    with open(last_success_backup.config_file.path, 'r', encoding='utf-8') as f:
                        last_config = f.read()

                    if filtered_output != last_config:
                        config_changed = '配置变化'

                    else:
                        config_changed = ''

                        # 创建配置备份对象
                config_backup_obj = ConfigBackup(dev=dev_obj, cmd=cmd, config_file=config_content,
                                                 backup_status='success',
                                                 failure_reason='',
                                                 config_changed=config_changed,
                                                 notes='')
                config_backup_obj.save()
            result_msg = f'{host.name}配置备份成功'
        else:
            config_backup_obj = ConfigBackup(dev=dev_obj, cmd='', config_file='None',
                                             backup_status='fail',
                                             failure_reason='暂时不支持此平台设备的配置备份',
                                             config_changed='',
                                             notes='')
            config_backup_obj.save()
            result_msg = f'不支持平台 {platform} 的配置备份'
    except Exception as e:
        result_msg = f'{str(e)}'
        config_backup_obj = ConfigBackup(dev=dev_obj, cmd='', config_file='None',
                                         backup_status='fail',
                                         failure_reason=result_msg,
                                         config_changed='',
                                         notes='')
        config_backup_obj.save()
        return Result(host=host, result=result_msg, failed=True, error=str(e))
    return Result(host=host, result=result_msg, failed=False)


# result = '{}配置备份成功'.format(task_context.host.name)
# platform = task_context.host.platform
# # 查找网络设备Device
# dev_obj = Devices.objects.filter(name=task_context.host.name).first()
# # 判断当前平台是否在支持的平台解析字典当中
# if platform in PLATFORM_BACKUP_INFO:
#     # 获取Netmiko连接
#     net_conn = task_context.host.get_connection('netmiko', task_context.nornir.config)
#     # secret参数可以直接从Netmiko连接中获取
#     secret = net_conn.secret
#     if secret:
#         net_conn.enable()
#     # 获取对应平台要执行的配置备份命令
#     cmds = PLATFORM_BACKUP_INFO[platform]
#     for cmd in cmds:
#         output = net_conn.send_command(cmd)
#         # 配置备份文本文件名称
#         file_name = '{}.txt'.format(cmd)
#         # 构建一个ContentFile对象用于赋值给配置备份ConfigBackup对象的config_file字段
#         config_content = ContentFile(content=output, name=file_name)
#         # 创建配置备份对象
#         config_backup_obj = ConfigBackup(dev=dev_obj, cmd=cmd, config_file=config_content)
#         config_backup_obj.save()
#
# else:
#     raise Exception('暂时不支持此平台设备的配置备份')
#
# return Result(host=task_context.host, result=result)


def batch_backup_config(queryset, num_workers=100):
    # 通过Device的queryset加载nornir对象
    nr = nornir_init(queryset, num_workers)
    # 批量配置备份的task函数
    results = nr.run(task=backup_config)
    # 初始化失败设备的列表
    fail_dev = []
    success_num = 0
    # 失败的设备会被Nornir捕获异常，将网络设备追加到Nornir Result的failed_hosts字段
    # 这是一个类似于字典的数据结构，可以进行for循环，key为Nornir网络对象的name属性，即设备名
    # for fail_host_name in result.failed_hosts:
    #     fail_dev.append(fail_host_name)
    # # 通过内置函数len计算失败网络设备的数量
    # fail_num = len(fail_dev)
    # # 通过本次执行任务设备总量减去失败的设备总量获取成功设备的总量
    # success_num = len(queryset) - fail_num
    # result_detail = {'success_num': success_num, 'fail_num': fail_num, 'fail_dev': fail_dev}
    # return result_detail
    for host, result in results.items():
        if isinstance(result, Exception):
            fail_dev.append(host.name)
        elif isinstance(result, Result) and result.failed:
            fail_dev.append(host.name)
        else:
            success_num += 1
    fail_num = len(fail_dev)
    result_detail = {'success_num': success_num, 'fail_num': fail_num, 'fail_dev': fail_dev}
    return result_detail
