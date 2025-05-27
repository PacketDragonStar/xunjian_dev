from app02 import models

import os
from django.shortcuts import render
from django.conf import settings
from django.http import JsonResponse,HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


# 使用装饰器限制请求方法为GET或POST

def host_list(request):
    return render(request, 'host_list.html')


@require_http_methods(["GET", "POST"])
@csrf_exempt
def host_detail(request):
    file_dir = os.path.join(settings.MEDIA_ROOT, 'dist')

    if request.method == 'GET':
        # 列出目录下的所有.txt文件，并按修改日期排序
        files = sorted([f for f in os.listdir(file_dir)], reverse=True)
        # 返回文件列表作为JSON响应
        return JsonResponse({'files': files})

    elif request.method == 'POST':
        # 从POST请求中获取选中的文件名
        selected_file = request.POST.get('selected_file')
        if selected_file and os.path.isfile(os.path.join(file_dir, selected_file)):
            # 读取并返回文件内容
            with open(os.path.join(file_dir, selected_file), 'r',encoding='utf-8',errors='ignore') as file:
                content = file.read()
            return HttpResponse(content, content_type='text/plain')
        else:
            # 文件不存在或未提供文件名时返回错误响应
            return JsonResponse({'error': 'File not found or no file selected.'}, status=404)
