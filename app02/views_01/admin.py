from app02 import models
from django import forms
from django.db.models import Q
from django.shortcuts import render, redirect, HttpResponse
from django.core.exceptions import ValidationError
from app02.utils.encrypt import md5
from app02.utils.pagination import Pagination
from app02.utils.bootstrap import BootstrapModelForm
class AdminModelForm(BootstrapModelForm):
    confirm_pass = forms.CharField(
        label='确认密码',
        widget=forms.PasswordInput
    )

    class Meta:
        model = models.Admin
        fields = '__all__'
        widgets = {
            "password": forms.PasswordInput(render_value=True)
        }

    def clean_password(self):
        password = self.cleaned_data.get('password')
        return md5(password)

    def clean_confirm_pass(self):
        password = self.cleaned_data.get('password')
        print('pass:'+password)
        confirm_pass = self.cleaned_data.get('confirm_pass')
        print('con_pass:' + md5(confirm_pass))
        if password != md5(confirm_pass):
            raise ValidationError("密码不一致")
        # 返回什么，此字段以后保存到数据库就是什么。
        return password


class AdminEditModelForm(BootstrapModelForm):
    """ 编辑管理员校验 """
    username = forms.CharField(
        label="用户名",
        widget=forms.TextInput(attrs={'readonly': 'readonly'})
    )

    class Meta:
        model = models.Admin
        fields = ['username', 'depart', 'name', 'phone']


# class AdminPasswordModelForm(BootstrapModelForm):
#     """ 修改密码 """
#
# password = forms.CharField(
#     label="原密码",
#     widget=forms.PasswordInput(render_value=False)
# )
#
# new_password = forms.CharField(
#     label="新密码",
#     widget=forms.PasswordInput(render_value=False)
# )
#
# confirm_password = forms.CharField(
#     label="确认新密码",
#     widget=forms.PasswordInput(render_value=True)
# )
#
# class Meta:
#     model = models.Admin
#     fields = ['password', 'new_password', 'confirm_password']  # 添加'original_password'字段
#
# def clean_password(self):
#     pwd = self.cleaned_data.get("password")
#     md5_pwd = md5(pwd)
#
#     # 去数据库校验密码是否一致
#     exists = models.Admin.objects.filter(id=self.instance.pk, password=md5_pwd).exists()
#     if not exists:
#         raise ValidationError("密码错误")
#     return md5_pwd
#
# def clean_confirm_password(self):
#     pwd = self.cleaned_data.get("new_password")
#     confirm = self.cleaned_data.get("confirm_password")
#     if pwd and confirm and pwd != confirm:
#         raise ValidationError("密码不一致")
#     # 返回什么，此字段以后保存到数据库就是什么。
#     return pwd


class AdminResetModelForm(BootstrapModelForm):
    """ 重置密码校验 """
    confirm_password = forms.CharField(
        label="确认密码",
        widget=forms.PasswordInput(render_value=True)
    )

    class Meta:
        model = models.Admin
        fields = ['password', 'confirm_password']
        widgets = {
            "password": forms.PasswordInput(render_value=True)
        }

    def clean_password(self):
        pwd = self.cleaned_data.get("password")
        md5_pwd = md5(pwd)

        # 去数据库校验当前密码和新输入的密码是否一致
        exists = models.Admin.objects.filter(id=self.instance.pk, password=md5_pwd).exists()
        if exists:
            raise ValidationError("不能与以前的密码相同")

        return md5_pwd

    def clean_confirm_password(self):
        pwd = self.cleaned_data.get("password")
        confirm = md5(self.cleaned_data.get("confirm_password"))
        if confirm != pwd:
            raise ValidationError("密码不一致")
        # 返回什么，此字段以后保存到数据库就是什么。
        return confirm


def admin_list(request):
    """ 管理员列表 """
    search_fields = ['username', 'name']
    search_data = request.GET.get('query', '').strip()  # 去除可能的空白字符
    query = Q() # 创建一个空的Q对象
    for field in search_fields:
        query |= Q(**{f'{field}__icontains': search_data})  # 使用f-string动态构建字段名

    # 根据搜索条件去数据库获取
    queryset = models.Admin.objects.filter(query)

    # 分页
    page_object = Pagination(request, queryset)
    context = {
        'queryset': page_object.page_queryset,
        'page_string': page_object.html(),
        'search_data': search_data
    }
    return render(request, 'admin_list.html', context)





def admin_edit(request, nid):
    """ 编辑用户 """
    # 对象 / None
    row_object = models.Admin.objects.filter(id=nid).first()
    if not row_object:
        # return render(request, 'error.html', {"msg": "数据不存在"})
        return redirect('/admin/list/')

    title = "编辑管理员"
    if request.method == "GET":
        form = AdminEditModelForm(instance=row_object)
        return render(request, 'change.html', {"form": form, "title": title})

    form = AdminEditModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return redirect('/admin/list/')
    return render(request, 'change.html', {"form": form, "title": title})


def admin_password(request, nid):
    """ 修改密码 """
    # 对象 / None
    row_object = models.Admin.objects.filter(id=nid).first()
    if not row_object:
        return redirect('/admin/list/')

    title = "修改密码 - {}".format(row_object.name)

    if request.method == "GET":
        form = AdminPasswordModelForm()
        return render(request, 'change.html', {"form": form, "title": title})

    form = AdminPasswordModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return redirect('/admin/list/')
    return render(request, 'change.html', {"form": form, "title": title})


def admin_reset(request, nid):
    """ 重置密码 """
    # 对象 / None
    row_object = models.Admin.objects.filter(id=nid).first()
    if not row_object:
        return redirect('/search/history/')

    title = "重置密码 - {}".format(row_object.name)

    if request.method == "GET":
        form = AdminResetModelForm()
        return render(request, 'change.html', {"form": form, "title": title})

    form = AdminResetModelForm(data=request.POST, instance=row_object)
    if form.is_valid():
        form.save()
        return redirect('/search/history/')
    return render(request, 'change.html', {"form": form, "title": title})

def admin_add(request):
    """ 新增、修改设备Ajax请求 """
    form = AdminModelForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect('/admin/list/')
    return render(request, 'change.html', {"form": form })
