from django.db import models


from pathlib import Path
from datetime import date, datetime
from django.db import models
from app02.utils.encrypt import md5


# Create your models here.


class Department(models.Model):
    """ 部门表 """
    title = models.CharField(verbose_name='标题', max_length=32)

    def __str__(self):
        return self.title


class UserInfo(models.Model):
    """ 员工表 """
    name = models.CharField(verbose_name="姓名", max_length=16)
    account = models.CharField(verbose_name="账号", max_length=16)
    password = models.CharField(verbose_name="密码", max_length=16)
    phone = models.CharField(verbose_name="手机号", max_length=11, null=True, blank=True)
    create_time = models.DateField(verbose_name="入职时间", null=True, blank=True)
    # 级联删除
    depart = models.ForeignKey(to="Department", to_field="id", on_delete=models.CASCADE)
    # 置空
    # depart = models.ForeignKey(to="Department", to_field="id", null=True, blank=True, on_delete=models.SET_NULL)

    # 在django中做的约束
    gender_choices = (
        (1, "男"),
        (2, "女")
    )
    gender = models.SmallIntegerField(verbose_name="性别", choices=gender_choices)


class Admin(models.Model):
    """ 管理员表 """
    username = models.CharField(verbose_name="账号", max_length=64)
    password = models.CharField(verbose_name="密码", max_length=64)
    name = models.CharField(verbose_name="姓名", max_length=16, null=True, blank=True)
    phone = models.CharField(verbose_name="手机号", max_length=11, null=True, blank=True)
    depart = models.ForeignKey(to="Department", to_field="id", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.name
def config_backup_upload_to(instance, filename):
    dev = instance.dev
    date_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
    return str(Path('ConfigBackup', date_str, filename))


class ConfigBackup(models.Model):
    dev = models.ForeignKey(verbose_name='关联设备', to='device_table', on_delete=models.CASCADE)
    cmd = models.CharField(verbose_name='执行的命令', max_length=128)
    config_file = models.FileField(verbose_name='配置文件', upload_to=config_backup_upload_to)
    created_time = models.DateTimeField(verbose_name='创建时间', auto_now_add=True)
    status_choices = (
        ('success', "成功"),
        ('fail', "失败"),
    )
    backup_status = models.CharField(verbose_name='备份状态', max_length=10, choices=status_choices, default='success')
    failure_reason = models.TextField(verbose_name='失败原因', blank=True, null=True)
    config_changed = models.CharField(verbose_name='配置是否改变', max_length=10, blank=True, null=True)
    notes = models.TextField(verbose_name='备注',blank=True, null=True)
    def __str__(self):
        # 我们可以访问外键对象的属性，比如取所属设备名self.dev.name
        return '{}于{}的"{}"备份'.format(self.dev.device, self.created_time, self.cmd)
# Create your models here.
class device_group_relationship_table(models.Model):
    device = models.CharField(max_length=50)
    group_id =models.IntegerField()

class device_table(models.Model):
    device= models.CharField(max_length=50)
    ip = models.CharField(max_length=50)
    group_name =models.CharField(max_length=50)
    user = models.CharField(max_length=64)
    password = models.CharField(max_length=64)
    expand= models.TextField()
    device_type = models.CharField(max_length=100)

class group_table(models.Model):
    group_name= models.CharField(max_length=50)

class function_table(models.Model):
    func = models.CharField(max_length=50)
    command = models.CharField(max_length=100)

class function_group_relationship_table(models.Model):
    func = models.CharField(max_length=50)
    group_id = models.IntegerField()

class result_overall_table(models.Model):
    time =models.CharField(max_length=50)
    user_xnjian = models.CharField(max_length=50)
    jixian = models.BooleanField()
    result = models.CharField(max_length=50)

class result_specific_table(models.Model):
    time =models.CharField(max_length=50)
    device = models.CharField(max_length=50)
    command= models.CharField(max_length=100)
    result = models.TextField(null=True, blank=True)
    config_changed = models.CharField(verbose_name='运行配置是否改变', max_length=10, blank=True, default='')
    notes = models.TextField(verbose_name='备注', blank=True, null=True)


class result_notes_table(models.Model):
    time =models.CharField(max_length=50)
    device = models.CharField(max_length=50)
    command= models.CharField(max_length=100)
    notes = models.CharField(max_length=100,null=True, blank=True)
    confirm = models.BooleanField()

class Item(models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=False)



class MyModel(models.Model):
    # 定义一个 BooleanField 作为复选框
    my_checkbox_field = models.BooleanField(default=False)