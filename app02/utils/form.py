from app01 import models
from django import forms
from app01.utils.bootstrap import BootstrapModelForm
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError


class UserModelForm(BootstrapModelForm):
    name = forms.CharField(
        min_length=2,
        lable="用户名",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    mobile = forms.CharField(
        label="手机号",
        validators=[RegexValidator(r'^1[3-9]\d{9}$', '手机号格式错误')]
    )

    class Meta:
        model = models.UserInfo
        fields = ('name', 'account', 'password', 'mobile', 'depart', 'gender', 'create_time')
