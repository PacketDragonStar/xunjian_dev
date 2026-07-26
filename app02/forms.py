# forms.py — 巡检系统表单（保留表单基础，MyModel 已随 v1 残余一起删除）

from django import forms


class UploadFileForm(forms.Form):
    file = forms.FileField(
        label='Upload Excel File',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xls,.xlsx'
        })
    )