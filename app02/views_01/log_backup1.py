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
