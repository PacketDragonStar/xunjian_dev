
from django import forms
from app02 import models
from app02.utils.encrypt import md5
from app02.utils.bootstrap import BootstrapForm
from django.shortcuts import render, redirect, HttpResponse

class LoginForm(BootstrapForm):
    bootstrap_exclude_fields = ["username", "password"]
    username = forms.CharField(
        label="账号",
        widget=forms.TextInput(attrs={
            'class': "input-item",
            'placeholder': "账号"
        }),
        required=True  # 必填项
    )

    password = forms.CharField(
        label="密码",
        widget=forms.PasswordInput(
            attrs={'class': "input-item", 'placeholder': "密码"},
            render_value=True),
        required=True
    )

    # code = forms.CharField(
    #     label="验证码",
    #     widget=forms.TextInput,
    #     required=True
    # )

    def clean_password(self):
        password = self.cleaned_data.get('password')
        return md5(password)


def login(request):
    """ 登录 """
    if request.method == "GET":
        form = LoginForm()
        return render(request, 'login.html', {'form': form})

    form = LoginForm(data=request.POST)
    if form.is_valid():
        # 验证码的校验
        # user_input_code = form.cleaned_data.pop('code')
        # code = request.session.get('image_code', "")
        # if code.upper() != user_input_code:
        #     form.add_error("code", "验证码错误")
        #     return render(request, 'login.html', {'form': form})

        # 去数据库校验用户名和密码是否正确，获取用户对象、None
        admin_object = models.Admin.objects.filter(**form.cleaned_data).first()
        if not admin_object:
            form.add_error("password", "用户名或密码错误")
            # form.add_error("username", "用户名或密码错误")
            return render(request, 'login.html', {'form': form})

        # 用户名和密码正确
        # 网站生成随机字符串; 写到用户浏览器的cookie中；在写入到session中；
        # {{ request.session.info.name }}登录后右上角显示用户姓名
        request.session["info"] = {'id': admin_object.id, 'username': admin_object.username, 'name': admin_object.name}

        return redirect("/search/history/")

    return render(request, 'login.html', {'form': form})


# def image_code(request):
#     """ 生成图片验证码 """
#
#     # 调用pillow函数，生成图片
#     img, code_string = check_code()
#
#     # 写入到自己的session中（以便于后续获取验证码再进行校验）
#     request.session['image_code'] = code_string
#     # 给Session设置60s超时
#     request.session.set_expiry(60 * 60 * 24 * 7)
#
#     stream = BytesIO()
#     img.save(stream, 'png')
#     return HttpResponse(stream.getvalue())


def logout(request):
    """ 注销 """
    request.session.clear()
    return redirect("/login/")
