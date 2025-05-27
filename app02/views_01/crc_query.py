import os
from textfsm import TextFSM

from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Max

from app02.models import *
from app02.utils.pagination import Pagination
from app02.utils.bootstrap import BootstrapForm, BootstrapModelForm


def get_latest_running_config_results():
    # 获取最新的批次时间
    latest_time = result_specific_table.objects.aggregate(Max('time')).get('time__max')

    # 查询最新批次时间中 command 为 'show running-config' 的记录
    results = result_specific_table.objects.filter(
        time=latest_time,
        command='show int_show interface transceiver details'
    )
    return results


def parse_running_configs(results):
    # 定义 TextFSM 模板文件的路径
    textfsm_path = os.path.join(settings.BASE_DIR, 'app02', 'cisco_nxos_show_interface.textfsm')
    structured_data = []

    for result in results:
        data = result.result  # 获取 result 字段的数据
        hostname = result.device  # 获取设备名称
        print(hostname)
        print(data)
        with open(textfsm_path, 'r', encoding='utf-8') as textfsm_file:
            template = TextFSM(textfsm_file)
            fsm_data = template.ParseTextToDicts(data)
            for fsm in fsm_data:
                if 'CRC' in fsm and fsm['CRC'] != '0' and fsm['CRC'] != '':
                    row = {
                        'Hostname': hostname,
                        'Interface': fsm['INTERFACE'],
                        'CRC': fsm['CRC'],
                        'Link_Status': fsm['LINK_STATUS']
                    }
                    structured_data.append(row)
    return structured_data


def crc_query(request):
    # 获取最新批次时间中 command 为 'show running-config' 的记录
    results = get_latest_running_config_results()
    # 解析这些记录的 result 字段
    structured_data = parse_running_configs(results)
    context = {
        'structured_data': structured_data,
    }
    return render(request, 'crc_list.html', context)
