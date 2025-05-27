from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import render, redirect, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django import forms
import pandas as pd

from app02 import models
from app02.utils.pagination import Pagination
from app02.utils.bootstrap import BootstrapModelForm


class funcModelForm(BootstrapModelForm):
    class Meta:
        model = models.function_table
        fields = '__all__'
        exclude = ['conn_timeout', 'timeout']


def func_list(request):
    """ 设备列表 """
    search_fields = ['func', 'command']
    search_data = request.GET.get('query', '').strip()  # 去除可能的空白字符
    query = Q()  # 创建一个空的Q对象
    for field in search_fields:
        query |= Q(**{f'{field}__icontains': search_data})  # 使用f-string动态构建字段名

    # 根据搜索条件去数据库获取
    queryset = models.function_table.objects.filter(query)

    # queryset = models.Devices.objects.all()
    form = funcModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        'search_data': search_data
    }
    return render(request, 'func_list.html', context)


@csrf_exempt
def func_add(request):
    """ 新增、修改设备Ajax请求 """
    form =funcModelForm(request.POST)
    if form.is_valid():
        form.save()
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": False, "error": form.errors})


@csrf_exempt
def func_delete(request):
    """ 设备删除 """
    uid = request.GET.get('uid')
    exists = models.function_table.objects.filter(id=uid).exists
    if not exists:
        return JsonResponse({"status": False, "error": "数据不存在"})
    models.function_table.objects.filter(id=uid).delete()
    return JsonResponse({"status": True})


def func_multi(request):
    """ 批量上传 """

    if request.method == 'POST' and 'dev' in request.FILES:
        file_object = request.FILES['dev']
        if file_object is None or file_object.size == 0:
            return HttpResponse('请选择一个有效的文件上传')
        try:
            df = pd.read_excel(file_object)
            for index, row in df.iterrows():
                # unique
                func = row['func']
                command =row['command']
                # 提取其他字段的值到一个字典中
                # device_data = {
                #     'ip': row['ip'],
                #     'group_name': row['group_name'],
                #     'user': row['user'],
                #     'password': row['password'],
                #     'expand': {'port_up':row['port_up'],'lldp_nei':row['lldp_nei'],'ospf_nei':row['ospf_nei'],'pim_nei':row['pim_nei'],'zb':row['zb'],'hw_patch':row['hw_patch']},
                #     'device_type': row['device_type'],
                # }
                # 使用update_or_create方法
                # 如果设备存在，则更新字段；如果不存在，则创建新设备
                models.function_table.objects.update_or_create(func=func, command=command)
            return redirect('/func/list/')

        except Exception as e:
            # 处理读取Excel时可能发生的异常
            print(f"Error reading Excel file: {e}")
            # 返回一个错误页面给用户
            return HttpResponse(f"读取Excel文件时发生错误: {e}", status=500)
            # 如果不是POST请求或者没有上传文件，可以返回一个上传表单页面
    # 这里只是示例，你可能需要创建一个模板来显示这个表单
    return HttpResponse('请上传文件以进行批量处理')
