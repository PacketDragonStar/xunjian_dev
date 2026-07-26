"""旧数据迁移脚本

将原巡检系统的旧表数据迁移到新版表结构：
  device_table      -> NewDevice
  group_table       -> DeviceGroup
  function_table    -> CheckItem
  result_overall_table -> XunjianRecord
  result_specific_table -> CheckResult
  result_notes_table    -> AnomalyRecord

使用方法（在 Django shell 中执行）：
    python manage.py shell
    from app02.utils.migrate_old_data import migrate_all
    migrate_all()

或直接运行：
    python manage.py runscript migrate_old_data
"""
import json
import logging

logger = logging.getLogger(__name__)


def migrate_groups():
    """迁移分组：group_table -> DeviceGroup"""
    from app02.models import group_table, DeviceGroup
    created = 0
    skipped = 0
    for old in group_table.objects.all():
        obj, is_new = DeviceGroup.objects.get_or_create(
            name=old.group_name,
            defaults={'description': ''}
        )
        if is_new:
            created += 1
        else:
            skipped += 1
    logger.info(f'分组迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[分组] 新建 {created}, 跳过 {skipped}')


def migrate_check_items():
    """迁移巡检函数：function_table -> CheckItem"""
    from app02.models import function_table, CheckItem
    created = 0
    skipped = 0
    for old in function_table.objects.all():
        obj, is_new = CheckItem.objects.get_or_create(
            command=old.command,
            defaults={
                'name':    old.func,
                'parser':  'raw',
                'checker': 'baseline',
                'error_note': '与基线不一致，请检查',
                'timeout': 30,
                'enabled': True,
            }
        )
        if is_new:
            created += 1
        else:
            skipped += 1
    logger.info(f'巡检项迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[巡检项] 新建 {created}, 跳过 {skipped}')


def migrate_group_check_items():
    """迁移分组-函数绑定关系：function_group_relationship_table -> DeviceGroup.check_items"""
    from app02.models import (
        function_group_relationship_table, group_table,
        function_table, DeviceGroup, CheckItem
    )
    bound = 0
    for rel in function_group_relationship_table.objects.all():
        group_obj = group_table.objects.filter(id=rel.group_id).first()
        func_obj  = function_table.objects.filter(func=rel.func).first()
        if not group_obj or not func_obj:
            continue
        dg = DeviceGroup.objects.filter(name=group_obj.group_name).first()
        ci = CheckItem.objects.filter(command=func_obj.command).first()
        if dg and ci:
            dg.check_items.add(ci)
            bound += 1
    logger.info(f'分组-巡检项绑定迁移完成: {bound} 条')
    print(f'[绑定关系] 绑定 {bound} 条')


def migrate_devices():
    """迁移设备：device_table -> NewDevice"""
    from app02.models import device_table, group_table, DeviceGroup, NewDevice
    created = 0
    skipped = 0
    for old in device_table.objects.all():
        if NewDevice.objects.filter(name=old.device).exists():
            skipped += 1
            continue
        # 查找对应的新版分组
        dg = DeviceGroup.objects.filter(name=old.group_name).first()
        # 解析扩展字段
        try:
            extra = json.loads(old.expand) if old.expand else {}
        except (json.JSONDecodeError, TypeError):
            extra = {}
        NewDevice.objects.create(
            name=old.device,
            ip=old.ip,
            group=dg,
            device_type=old.device_type,
            username=old.user,
            password=old.password,
            extra=extra,
            enabled=True,
        )
        created += 1
    logger.info(f'设备迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[设备] 新建 {created}, 跳过 {skipped}')


def migrate_xunjian_records():
    """迁移巡检总记录：result_overall_table -> XunjianRecord"""
    from app02.models import result_overall_table, XunjianRecord
    created = 0
    skipped = 0
    for old in result_overall_table.objects.all():
        if XunjianRecord.objects.filter(time=old.time).exists():
            skipped += 1
            continue
        XunjianRecord.objects.create(
            time=old.time,
            operator=old.user_xnjian,
            result=old.result,
            is_baseline=old.jixian,
            device_count=0,
            check_count=0,
            ok_devices=0,
            anomaly_devices=0,
            failed_devices=0,
        )
        created += 1
    logger.info(f'巡检总记录迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[巡检总记录] 新建 {created}, 跳过 {skipped}')


def migrate_check_results():
    """迁移命令输出：result_specific_table -> CheckResult"""
    from app02.models import result_specific_table, CheckResult
    created = 0
    skipped = 0
    for old in result_specific_table.objects.all():
        if CheckResult.objects.filter(
            time=old.time, device=old.device, command=old.command
        ).exists():
            skipped += 1
            continue
        CheckResult.objects.create(
            time=old.time,
            device=old.device,
            command=old.command,
            result=old.result,
        )
        created += 1
    logger.info(f'命令输出迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[命令输出] 新建 {created}, 跳过 {skipped}')


def migrate_anomaly_records():
    """迁移异常记录：result_notes_table -> AnomalyRecord"""
    from app02.models import result_notes_table, AnomalyRecord
    created = 0
    skipped = 0
    for old in result_notes_table.objects.all():
        if AnomalyRecord.objects.filter(
            time=old.time, device=old.device, command=old.command
        ).exists():
            skipped += 1
            continue
        AnomalyRecord.objects.create(
            time=old.time,
            device=old.device,
            command=old.command,
            notes=old.notes,
            confirm=old.confirm,
            baseline_val='',
            current_val='',
        )
        created += 1
    logger.info(f'异常记录迁移完成: 新建 {created}, 跳过 {skipped}')
    print(f'[异常记录] 新建 {created}, 跳过 {skipped}')


def migrate_all():
    """执行全部迁移（按依赖顺序）"""
    print('=' * 50)
    print('开始迁移旧数据到新版表结构...')
    print('=' * 50)
    migrate_groups()
    migrate_check_items()
    migrate_group_check_items()
    migrate_devices()
    migrate_xunjian_records()
    migrate_check_results()
    migrate_anomaly_records()
    print('=' * 50)
    print('迁移完成！')
    print('=' * 50)


if __name__ == '__main__':
    import django
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xunjian_system1.settings')
    django.setup()
    migrate_all()
