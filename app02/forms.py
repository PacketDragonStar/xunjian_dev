from django import forms
from .models import MyModel

class MyForm(forms.ModelForm):
    class Meta:
        model = MyModel
        fields = ['my_checkbox_field']
        labels = {
            'my_checkbox_field': '选中我',  # 在这里设置标签文本
        }
        widgets = {
            'my_checkbox_field': forms.CheckboxInput(attrs={
                'class': 'my-checkbox-class',  # 设置CSS类
                'style': 'margin: 10px;',     # 设置内联样式
            })
        }