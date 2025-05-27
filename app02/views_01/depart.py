from django.shortcuts import render, redirect, HttpResponse
from app02.models import Department
import pandas as pd
from openpyxl import load_workbook


# Create your views here.


def depart_list(request):
    """ 部门列表 """
    # 获取数据库部门列表
    depart = Department.objects.all()
    return render(request, 'depart_list.html', {'depart': depart})


def depart_add(request):
    """ 添加部门 """
    if request.method == "GET":
        return render(request, 'depart_add.html')
    title = request.POST.get("title")
    Department.objects.create(title=title)
    return redirect('/depart/list/')


def depart_delete(request):
    """ 删除部门 """
    nid = request.GET.get("nid")
    Department.objects.filter(id=nid).delete()
    return redirect('/depart/list/')


def depart_edit(request, nid):
    """ 修改部门 """
    if request.method == "GET":
        row_object = Department.objects.filter(id=nid).first()
        return render(request, 'depart_edit.html', {'row_object': row_object})
    title = request.POST.get("title")
    Department.objects.filter(id=nid).update(title=title)
    return redirect('/depart/list/')


def depart_multi(request):
    """ 批量上传 """
    if request.method == 'POST' and 'exc' in request.FILES:
        file_object = request.FILES['exc']
        if file_object is None or file_object.size == 0:
            return HttpResponse('请选择一个有效的文件上传')
        try:
            df = pd.read_excel(file_object)
            departments = df['部门'].tolist()  # 确保这一列的名称与你的Excel中的列名一致
            for department in departments:
                # 检查是否存在这些部门ID
                exists = Department.objects.filter(title=department).exists()
                if not exists:
                    Department.objects.create(title=department)
                    # 假设你已经处理完上传，现在重定向到部门列表页面
            return redirect('/depart/list/')

        except Exception as e:
            # 处理读取Excel时可能发生的异常
            print(f"Error reading Excel file: {e}")
            # 返回一个错误页面给用户
            return HttpResponse(f"读取Excel文件时发生错误: {e}", status=500)
            # 如果不是POST请求或者没有上传文件，可以返回一个上传表单页面
    # 这里只是示例，你可能需要创建一个模板来显示这个表单
    return HttpResponse('请上传文件以进行批量处理')