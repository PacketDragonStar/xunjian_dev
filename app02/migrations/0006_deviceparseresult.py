# 阶段二：采集时一次解析落库 —— DeviceParseResult
# 结构化解析结果（app02.parsers 单一真源输出），与 CheckResult.raw 解耦。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app02', '0005_checkerscript_checkerscriptversion'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeviceParseResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device', models.CharField(db_index=True, max_length=50, verbose_name='设备名')),
                ('command', models.CharField(max_length=200, verbose_name='命令')),
                ('collected_at', models.CharField(help_text='对齐 CheckResult.time', max_length=50, verbose_name='采集时间')),
                ('schema_version', models.CharField(default='1', max_length=10, verbose_name='schema版本')),
                ('data', models.JSONField(blank=True, null=True, verbose_name='结构化结果')),
                ('created_at', models.DateTimeField(auto_now_add=True, blank=True, null=True, verbose_name='入库时间')),
            ],
            options={
                'verbose_name': '设备解析结果',
                'indexes': [
                    models.Index(fields=['device', 'command', 'collected_at'], name='dpr_dev_cmd_time_idx'),
                ],
                'unique_together': {('device', 'command', 'collected_at')},
            },
        ),
    ]
