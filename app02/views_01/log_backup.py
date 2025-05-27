from django.db.models import Q
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from app02.models import *
from app02.utils.pagination import Pagination
from app02.utils.bootstrap import BootstrapForm, BootstrapModelForm


class result_specific_tableModelForm(BootstrapModelForm):
    class Meta:
        model = result_specific_table
        fields = '__all__'


def log_backup_list(request):
    """ 备份列表 """
    search_fields = ['device', 'command']  # 允许搜索的字段列表
    search_data = request.GET.get('query', '').strip()  # 获取搜索词并去除空白字符
    order_by = request.GET.get('order_by', '-time').strip()  # 获取排序方式，默认为创建时间倒序

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
    # 添加额外的过滤条件来限制command字段
    command_filter = Q(command__icontains='show running-config') | Q(command__icontains='display current-configuration')
    # 将搜索条件和command过滤条件组合起来
    queryset = result_specific_table.objects.filter(query & command_filter).order_by(order_by)
    form = result_specific_tableModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        "queryset": page_object.page_queryset,  # 分完页的数据
        "page_string": page_object.html(),  # 生成页码
        'search_data': search_data,
        'order_by': order_by,
    }
    return render(request, 'log_backup_list.html', context)


@csrf_exempt
def save_notes(request):
    if request.method == 'POST':
        config_backup_ids = request.POST.get('ids', '').split(',')
        notes = request.POST.get('notes', '')
        success_count = 0
        for backup_id in config_backup_ids:
            try:
                backup = result_specific_table.objects.get(id=backup_id)
                backup.notes = notes  # 假设你的模型中有一个名为 'notes' 的字段
                backup.save()  # 保存更改到数据库
                success_count += 1
            except result_specific_table.DoesNotExist:
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
import os
import zipfile
import time
import random
from io import BytesIO


def download_backups(request):
    # 获取前端传递的时间参数
    start_date_str = request.GET.get('startDate')
    end_date_str = request.GET.get('endDate')

    # 打印接收到的日期参数
    print(f"Received start date: {start_date_str}, end date: {end_date_str}")

    # 将字符串转换为日期对象
    start_date = time.strptime(start_date_str, "%Y-%m-%d") if start_date_str else None
    end_date = time.strptime(end_date_str, "%Y-%m-%d") if end_date_str else None

    # 根据时间范围查询数据库
    query_params = {}
    if start_date:
        query_params['time__gte'] = start_date_str
    if end_date:
        query_params['time__lte'] = end_date_str

    backups = result_specific_table.objects.filter(**query_params)

    # 创建一个BytesIO对象来存储压缩文件
    s = BytesIO()

    # 创建一个zip文件对象
    zf = zipfile.ZipFile(s, "w", zipfile.ZIP_DEFLATED)

    # 用于存储每个时间戳的数据
    time_data = {}

    # 遍历查询结果，按时间戳分组
    for backup in backups:
        time_str = backup.time
        device = backup.device
        if time_str not in time_data:
            time_data[time_str] = {}
        if device not in time_data[time_str]:
            time_data[time_str][device] = []
        time_data[time_str][device].append({
            'command': backup.command,
            'result': backup.result,
        })

    # 为每个时间戳创建一个目录，并将设备数据写入目录下的文件
    for time_str, devices in time_data.items():
        # 生成一个随机数，确保目录名唯一
        random_suffix = str(random.randint(1000, 9999))  # 生成一个四位随机数
        unique_dir_path = f"{time_str}_{random_suffix}/"

        # 创建一个目录
        zf.writestr(zipfile.ZipInfo(unique_dir_path), '')

        # 为每个设备生成一个文本文件并添加到压缩文件中
        for device, data in devices.items():
            # 创建一个BytesIO对象来存储单个设备的文本内容
            txt_buffer = BytesIO()

            # 写入设备信息
            txt_buffer.write(f"Device: {device}\n".encode())
            txt_buffer.write(b"\n")

            # 写入所有命令及其结果
            for entry in data:
                txt_buffer.write(f"Command: {entry['command']}\n".encode())
                txt_buffer.write(b"Result:\n")
                txt_buffer.write(entry['result'].encode())
                txt_buffer.write(b"\n\n")

            # 重置文件指针到开始位置
            txt_buffer.seek(0)

            # 将文本内容写入zip文件
            info = zipfile.ZipInfo(f"{unique_dir_path}{device}.txt")
            info.date_time = time.localtime(time.time())[:6]
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, txt_buffer.getvalue())

    # 关闭zip文件对象
    zf.close()

    # 创建HttpResponse对象，设置Content-Type和Content-Disposition头
    response = HttpResponse(s.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename=bulk_backups.zip'
    response['Content-Length'] = s.tell()

    # 打印响应体的前100个字符，用于调试
    print(f"Response body (first 100 chars): {s.getvalue()[:100]}")

    return response

def log_backup_download(request, uid):
    try:
        backup_result = result_specific_table.objects.get(id=uid)
        download_filename = backup_result.device + '_' + backup_result.time + '.txt'
        response = HttpResponse(backup_result.result, content_type='text/plain')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(download_filename)
        return response
    except result_specific_table.DoesNotExist:
        # 如果记录不存在，返回错误响应
        return HttpResponse("配置不存在", status=404)
