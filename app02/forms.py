# forms.py — 巡检系统表单（保留表单基础，MyModel 已随 v1 残余一起删除）

from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        label='用户名',
        widget=forms.TextInput(attrs={'class': 'input-item', 'placeholder': '用户名'}),
    )
    password = forms.CharField(
        label='密码',
        widget=forms.PasswordInput(attrs={'class': 'input-item', 'placeholder': '密码'}),
    )


class UploadFileForm(forms.Form):
    file = forms.FileField(
        label='Upload Excel File',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xls,.xlsx'
        })
    )