from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import render, redirect, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django import forms
import pandas as pd
import json
from app02 import models
from app02.utils.pagination import Pagination
from app02.utils.bootstrap import BootstrapModelForm


class DeviceModelForm(BootstrapModelForm):
    class Meta:
        model = models.device_table
        fields = '__all__'
        exclude = ['conn_timeout', 'timeout']



class DeviceForm(forms.ModelForm):
    class Meta:
        model = models.device_table
        fields = ['password']  # 假设你的设备模型有一个password字段

@csrf_exempt
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('oldPassword')
        new_password = request.POST.get('newPassword')
        confirm_new_password = request.POST.get('confirmNewPassword')

        if new_password != confirm_new_password:
            return JsonResponse({'success': False, 'error': 'New password and confirm password do not match.'})

        # 假设你有一个函数来验证旧密码是否正确
        if not check_old_password(old_password):
            return JsonResponse({'success': False, 'error': 'Old password is incorrect.'})

        # 更新所有设备的密码

        models.device_table.objects.all().update(password=new_password)
        models.device_table.objects.filter(ip='100.127.30.24').update(password='!ColasoftL23')
        models.device_table.objects.filter(ip='100.127.30.25').update(password='!ColasoftL23')
        models.device_table.objects.filter(ip='100.127.30.27').update(password='!ColasoftL23')
        return JsonResponse({'success': True})

def check_old_password(old_password):
    # 这里应该是一个验证旧密码的函数，返回一个布尔值
    passwd=models.device_table.objects.filter(ip='100.127.0.11').first().password # 假设旧密码总是统一的
    if passwd==old_password:
        return True
    else:
        return False

def device_list(request):
    """ 设备列表 """
    search_fields = ['ip', 'device', 'group_name', 'user', 'password', 'expand','device_type']
    search_data = request.GET.get('query', '').strip()  # 去除可能的空白字符
    query = Q()  # 创建一个空的Q对象
    for field in search_fields:
        query |= Q(**{f'{field}__icontains': search_data})  # 使用f-string动态构建字段名

    # 根据搜索条件去数据库获取
    queryset = models.device_table.objects.filter(query)

    # queryset = models.Devices.objects.all()
    form = DeviceModelForm()
    page_object = Pagination(request, queryset)
    context = {
        'form': form,
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        'search_data': search_data
    }
    return render(request, 'device_list.html', context)


@csrf_exempt
def device_add(request):
    """ 新增、修改设备Ajax请求 """
    form = DeviceModelForm(request.POST)
    if form.is_valid():
        form.save()
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": False, "error": form.errors})


@csrf_exempt
def device_delete(request):
    """ 设备删除 """
    uid = request.GET.get('uid')
    exists = models.device_table.objects.filter(id=uid).exists
    if not exists:
        return JsonResponse({"status": False, "error": "数据不存在"})
    models.device_table.objects.filter(id=uid).delete()
    return JsonResponse({"status": True})


def device_multi(request):
    """ 批量上传 """

    if request.method == 'POST' and 'dev' in request.FILES:
        file_object = request.FILES['dev']
        if file_object is None or file_object.size == 0:
            return HttpResponse('请选择一个有效的文件上传')
        try:
            df = pd.read_excel(file_object)
            for index, row in df.iterrows():
                # unique
                name = row['device']
                # 提取其他字段的值到一个字典中
                device_data = {
                    'ip': row['ip'],
                    'group_name': row['group_name'],
                    'user': row['user'],
                    'password': row['password'],
                    'expand': json.dumps({
                        "port_up": row["port_up"],
                        "lldp_nei": row["lldp_nei"],
                        "ospf_nei": row["ospf_nei"],
                        "pim_nei": row["pim_nei"],
                        "zb": str(row["zb"]),
                        "hw_patch": str(row["hw_patch"])
                    }),
                    # 'expand': '{"port_up":'+str(row["port_up"])+',"lldp_nei":'+str(row["lldp_nei"])+',"ospf_nei":'+str(row["ospf_nei"])+',"pim_nei":'+str(row["pim_nei"])+',"zb":'+str(row["zb"])+',"hw_patch":'+str(row["hw_patch"])+'}',
                    'device_type': row['device_type'],
                }
                # 使用update_or_create方法
                # 如果设备存在，则更新字段；如果不存在，则创建新设备
                models.device_table.objects.update_or_create(device=name, defaults=device_data)
            return redirect('/device/list/')

        except Exception as e:
            # 处理读取Excel时可能发生的异常
            print(f"Error reading Excel file: {e}")
            # 返回一个错误页面给用户
            return HttpResponse(f"读取Excel文件时发生错误: {e}", status=500)
            # 如果不是POST请求或者没有上传文件，可以返回一个上传表单页面
    # 这里只是示例，你可能需要创建一个模板来显示这个表单
    return HttpResponse('请上传文件以进行批量处理')
@csrf_exempt
def device_detail(request):
    """ ajax编辑设备 """
    uid = request.GET.get("uid")
    row_object = models.device_table.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({'status': False, 'error': '数据不存在'})
    result = {
        "status": True,
        "data": {
            'ip': row_object.ip,
            'device':row_object.device,
            'group_name': row_object.group_name,
            'expand': row_object.expand,
            'device_type': row_object.device_type,
            'user': row_object.user,
            'password': row_object.password,
        }
    }
    return JsonResponse(result)


@csrf_exempt
def device_edit(request):
    """ 编辑设备 """
    uid = request.GET.get("uid")
    row_object = models.device_table.objects.filter(id=uid).first()
    if not row_object:
        return JsonResponse({'status': False, 'tips': '数据不存在,请刷新重试'})
    form = DeviceModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": False, "error": form.errors})
