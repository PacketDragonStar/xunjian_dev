import datetime
import os
import re
import math
import difflib
import pandas as pd
from app02.models import result_notes_table
from textfsm import TextFSM
from django.conf import settings
from paramiko import SSHClient, AutoAddPolicy
from time import sleep


base_dir = settings.BASE_DIR
now = datetime.datetime.now()
today = now.strftime("%Y-%m-%d_%H_%M_%S")
file_path = os.path.join(base_dir, 'app02', 'static', 'devicebrief_test.xlsx')
shbfd_txm_path = os.path.join(base_dir, 'app02', 'cisco_nxos_show_bfd_session.textfsm')
shint_txm_path = os.path.join(base_dir, 'app02', 'cisco_nxos_show_interface.textfsm')
shinttran_txm_path = os.path.join(base_dir, 'app02', 'cisco_nxos_show_interface_transceiver_details.textfsm')
shlldp_txm_path = os.path.join(base_dir, 'app02', 'cisco_nxos_show_lldp_neighbors.textfsm')
disint_txm_path = os.path.join(base_dir, 'app02', 'hw_display_int_brief.textfsm')
devs_df = pd.read_excel(file_path)
devs = devs_df.to_dict(orient='records')


def compare_text(text1, text2):
    text1 = re.sub(r'\s+', ' ', text1).strip()  # 合并空白字符并去除两端的空白
    text2 = re.sub(r'\s+', ' ', text2).strip()  # 合并空白字符并去除两端的空白
    matcher = difflib.SequenceMatcher(None, text1, text2)
    return matcher.ratio()


def shrun(self, time, name, con, jixian, expend_dic):  # 配置对比
    result = self.send_command("show run")  # 发送show run命令
    # 使用正则表达式替换功能，移除结果中的时间戳信息
    result1 = re.sub(r"!Time:\s(.+)", "", result)
    # 查询数据库中标记为'是'的基线记录
    notes = ''
    if jixian:
        # 将基线记录中的'show run'结果从JSON格式转换为Python字典，并提取'result'键对应的值
        text = jixian
        # 同样移除基线记录结果中的时间戳信息
        text1 = re.sub(r"!Time:\s(.+)", "", text)
        # 比较当前设备的配置与基线配置是否一致
        if compare_text(text1, result1) == 1:
            # 如果配置一致，则创建一个链接表示状态正常，并设置链接参数
            pass
        else:

            notes = '配置不一致，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shversion(self, time, name, con, jixian, expend_dic):  # show version 设备运行时间------只对比设备运行时间
        result = self.send_command("show version")
        match = re.search(r"(Kernel uptime(.*))", result)
        s = match.group()
        match1 = re.search(r'(\d+) day\(s\), (\d+) hour\(s\), (\d+) minute\(s\), (\d+) second\(s\)', s)
        notes = ''
        if match1:
            days = match1.group(1)
            hour = match1.group(2)
            if int(days) < 10:
                notes = '设备运行时间不足10天'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
            notes = '设备采集异常'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result




def shntp(self, time, name, con, jixian, expend_dic):  # show ntp peer-status
    result = self.send_command("show ntp peer-status")  # 将show ntp  peer-status命令运行，并返回结果到result
    con = 'show ntp peer-status'
    if "Total peers : 2" in result and "*100.127.19.11" in result and "=100.127.19.12" in result:
        pass
    else:
        notes = 'ntp状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shclock(self, time, name, con, jixian, expend_dic):  # show clock
    result = self.send_command("show clock")
    if 'Time source is NTP' in result:
        pass
    else:
        notes = '时间异常，请查看'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shenv(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show environment")
    notes = ''
    if result.count("ok") == 2 and result.count("Ok") == 10:
        pass
    else:
        notes = '硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shcpu(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show processes cpu")
    match = re.search(r"five minutes: (\d+)%", result)
    notes = ''
    cpuuse = int(match.group(1))
    if cpuuse <= 75:
        pass
    else:
        notes = 'cpu使用率超过75%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shmem(self, time, name, con, jixian, expend_dic):  # show process memory shared detail
    result = self.send_command("show system resources")
    lines = result.split("\n")
    memory_line = None
    notes = ''
    for line in lines:
        if "Memory usage" in line:
            memory_line = line
            break
    matches = re.findall(r'\d+', memory_line)
    used = int(matches[1])
    if used < 12297399:  # 内存为16G，低于75%为正常。
        pass
    else:
        notes = '内存使用率超过75%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def shflash(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    match = re.search(r"bootflash://\s*(\d+)", result)
    flashuse = int(match.group(1))
    notes = ''
    if flashuse < 11250000000:  # flash使用率低于75%为正常
        pass
    else:
        notes = 'flash使用率超过75%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shint(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show interface")
    result2 = self.send_command("show interface transceiver details")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    notes = ''
    with open(shinttran_txm_path, encoding='utf8') as textfsm_file:
        template = TextFSM(textfsm_file)
        s2 = template.ParseTextToDicts(result2)
    a = []

    for i in s2:
        if i['RX_VALUE'] and i['RX_VALUE'] != 'N/A':
            i['RX_VALUE'] = math.floor(float(i['RX_VALUE']))
        a.append(i)
    with open(shint_txm_path, encoding='utf8') as textfsm_file:
        template = TextFSM(textfsm_file)
    s1 = template.ParseTextToDicts(result)
    pass
    for int in s1:
        s5 = {'RX_VALUE': '', 'RX_ALARM_HIGH': '', 'RX_ALARM_LOW': ''}
        int.update(s5)
        if 'down' in int['LINK_STATUS']:
            int['LINK_STATUS'] = 'down'
        for int2 in a:
            if int['INTERFACE'] == int2['INTERFACE']:
                if int['LINK_STATUS'] == 'up' and int2['RX_VALUE'] != 'N/A':
                    if int2['RX_VALUE'] > -13.97 and int2['RX_VALUE'] < 1.99:
                        int2['RX_VALUE'] = str(int2['RX_VALUE'])
                        int['RX_VALUE'] = '正常'
                    else:
                        int2['RX_VALUE'] = str(int2['RX_VALUE'])
                        int['RX_VALUE'] = '收发光异常'
                if int['LINK_STATUS'] == 'up' and int2['RX_VALUE'] == 'N/A':
                    int['RX_VALUE'] = '异常'
                    notes = '收发光异常'
                    result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
                    result = '端口未收光，请检查\n' + result
                if 'down' in int['LINK_STATUS'] and int2['RX_VALUE'] == 'N/A':
                    int['RX_VALUE'] = '正常'
                if 'down' in int['LINK_STATUS'] and int2['RX_VALUE'] != 'N/A':
                    int['RX_VALUE'] = '异常收光'
    # intf_df2 = pd.DataFrame(s1)
    # df_selected = intf_df2[
    #     ['INTERFACE', 'LINK_STATUS', 'ADMIN_STATE', 'IP_ADDRESS', 'CRC', 'INPUT_ERRORS',
    #      'OUTPUT_ERRORS', 'RX_VALUE']]
    result12 = "show interface\n" + result + "show interface transceiver details\n" + result2
    # dict = {'result': result12, 'status': status, 'con': "show interface&show interface transceiver details"}
    return result12
    # return 'show interface' + result + '\n' + 'show interface transceiver details' + result2 + '\n', df_selected.to_string()


def shpoch(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show port-channel database")
    notes = ''
    if result.count("[active ] [up]") == int(expend_dic['port_up']):  # UP端口总数指定值就正常。
        pass
    else:
        notes = '端口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def shiproute(self, time, name, con, jixian, expend_dic):  # 去掉了路由条目存活时间--------------------------------对比
    result = self.send_command("show ip route")
    pattern = r"denotes VRF <string>.*"
    match = re.search(pattern, result, re.DOTALL)
    text = match.group().replace("denotes VRF <string>", " ")
    text1 = text.lstrip()
    text2 = re.sub(r'\d+[wdh]', '', text1)
    pattern1 = r'(\d{2}):(\d{2}):(\d{2})'
    text3 = re.sub(pattern1, '', text2)
    if jixian:
        result1 = jixian
        pattern = r"denotes VRF <string>.*"
        match1 = re.search(pattern, result1, re.DOTALL)
        notes = ''
        if match1:
            text_ = match1.group().replace("denotes VRF <string>", " ")
            text_1 = text_.lstrip()
            text_2 = re.sub(r'\d+[wdh]', '', text_1)
            pattern1 = r'(\d{2}):(\d{2}):(\d{2})'
            text_3 = re.sub(pattern1, '', text_2)
            match_ratio = compare_text(text3, text_3)
            if match_ratio == 1:
                pass
            else:
                notes = '路由与基线对比有差别，请检查'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result
    else:
        notes = '路由基线错误，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result


def shiproutesum(self, time, name, con, jixian,
                 expend_dic):  # -------------------------------------------------------------对比
    result = self.send_command("show ip route summary")
    notes = ''
    if jixian:
        result1 = jixian
        if compare_text(result, result1) == 1:
            pass
        else:

            notes = '与sheb1ip route对比有差别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result
    else:

        notes = '设备路由基线错误，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result


def shospfnei(self, time, name, con, jixian, expend_dic):  # 9个FULL状态及邻居总数为9则为正常。
    result = self.send_command("show ip ospf neighbor")
    if result.count("FULL/") == int(expend_dic['ospf_nei']):
        pass
    else:
        notes = '设备ospf_nei邻居数量异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def showospfsum(self, time, name, con, jixian, expend_dic):  # ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    result = self.send_command("show ip ospf route summary")
    notes = ''
    if jixian:
        result1 = jixian
        matcher = difflib.SequenceMatcher(None, result, result1)

        match_ratio = matcher.ratio()  # 返回文本相似度比率，1 表示完全相同

        if match_ratio == 1:
            pass
        else:
            notes = '设备ospf路由与基线对比有差别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result
    else:

        notes = '设备ospf路由基线异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result


def shpimnei(self, time, name, con, jixian, expend_dic):  # Bidir-Capable(双向能力) yes=8,BFD State UP= 8 则为正常状态。
    result = self.send_command("show ip pim neighbor")
    notes = ''
    if result.count("yes") == int(expend_dic['pim_nei']) and result.count("Up ") == int(expend_dic['pim_nei']):
        pass
    else:
        notes = '设备pim邻居与基线对比有差别，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def shmroute(self, time, name, con, jixian, expend_dic):  # 有A、B 2路组播路由表项则判断为正常
    result = self.send_command("show ip mroute")
    notes = ''
    zb=expend_dic['zb']
    if zb == 'yes':
        pattern = r"\(11\.8\.18\.11\/32\,\s232\.8\.18\.11\/32\).*"
        match = re.search(pattern, result, re.DOTALL)
        if match:
            pass
        else:
            notes = '组播路由与基线对比有差别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    if zb == 'no':
        pattern = r"\s232\.0\.0\.0\/8\).*"
        match = re.search(pattern, result, re.DOTALL)
        if match:
            pass
        else:
            notes = '组播路由与基线对比有差别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shlldp(self, time, name, con, jixian, expend_dic):  # 邻居条目对比
    result = self.send_command("show lldp neighbors")
    text1 = re.search(r'Total entries displayed: (.*)', result)
    notes = ''
    if text1.group(1) == str(int(expend_dic['lldp_nei'])):
        pass
    else:
        notes = '设备lldp邻居数量不为'+str(int(expend_dic['lldp_nei']))+'，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


# def shinttrans(self,time,name,con):  # 过滤只显示Rx Power这一行,并将收光数值取整，负数向上取整，正数向下取整++++++++++++++++#show   logging
#     result2 = self.send_command("show interface transceiver details")
#     with open('cisco_nxos_show_interface_transceiver_details.textfsm', encoding='utf8') as textfsm_file:
#         template = TextFSM(textfsm_file)
#         s2 = template.ParseTextToDicts(result2)
#     a = []
#     for i in s2:
#         if i['RX_VALUE'] and i['RX_VALUE']!= 'N/A':
#             i['RX_VALUE'] = math.floor(float(i['RX_VALUE']))
#         a.append(i)
#     intf_df2 = pd.DataFrame(a)
#     df_selected = intf_df2[
#         ['INTERFACE', 'RX_VALUE', 'RX_ALARM_HIGH', 'RX_ALARM_LOW', 'RX_WARN_HIGH', 'RX_WARN_LOW']]
#     return result2, '设备收发光信息如下：\n'+df_selected.to_string()+'\n'




def shcrc(self, time, name, con, jixian, expend_dic):  # 接口CRC情况
    result = self.send_command("show interface  | i CRC")
    if compare_text(result,jixian)==1:
        pass
    else:
        notes = '接口CRC异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def sharp(self, time, name, con, jixian, expend_dic):  # 过滤arp老化时间
    result = self.send_command("show ip arp")
    return result


def shmac(self, time, name, con, jixian, expend_dic):  # 直接输出命令执行结果
    result = self.send_command("show mac address-table")
    #if compare_text(result, jixian) == 1:
    #    pass
    #else:
    #    notes = 'mac对比不一致，请检查'
    #    result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shhsrp(self, time, name, con, jixian, expend_dic):  # 严格匹配命令输出的2组hsrp状态信息，能匹配就显示hsrp运行正常。
    result = self.send_command("show hsrp brief")
    notes = ''
    if (result.count("P Active   local            11.8.18.3        11.8.18.1") == 1 and result.count(
            "P Active   local            11.8.19.3        11.8.19.1")) or (
            result.count("Standby  11.8.18.2        local            11.8.18.1") == 1 and result.count(
        "Standby  11.8.19.2        local            11.8.19.1") == 1):
        pass
    else:
        notes = '设备hsrp状态异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def shlogging(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show logging last 20")
    notes = ''
    if jixian:
        result1 = jixian
        matcher = difflib.SequenceMatcher(None, result, result1)

        match_ratio = matcher.ratio()  # 返回文本相似度比率，1 表示完全相同

        if match_ratio == 1:
            pass
        else:

            notes = '与基线日志有区别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result
    else:

        notes = '设备logging基线问题，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

        return result


def shbfdsess(self, time, name, con, jixian, expend_dic):
    result = self.send_command("show bfd neighbors")
    notes = ''
    if jixian:
        result1 = jixian
        cleaned_text_1 = re.sub(r"\S+\(5\)", "", result)
        cleaned_text_2 = re.sub(r"\S+\(5\)", "", result1)
        if compare_text(cleaned_text_1, cleaned_text_2) == 1:
            pass
        else:
            notes = '设备bfd与基线对比有区别，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result
    else:
        notes = '设备bfd基线问题，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result


def discur(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display current-configuration")
    text1 = re.sub(r"!Last configuration was saved at \d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}(?: by monitor)?",
                   "!Last configuration was saved at",
                   result)
    text2 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text1)
    if jixian:
        text1_ = re.sub(r"!Last configuration was saved at \d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}(?: by monitor)?",
                        "!Last configuration was saved at",
                        jixian)
        text2_ = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text1_)
        if compare_text(text2, text2_) == 1:
            pass
        else:
            notes = '设备配置对比不一致，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '设备配置基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disver_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display version")
    pattern = r"^HUAWEI NetEngine 8000 M8 uptime.*$"
    match = re.search(pattern, result, re.MULTILINE)
    s = match.group()
    match1 = re.search(r'(\d+) days?, (\d+) hours?, (\d+) minutes?', s)
    if match1:
        days = match1.group(1)
        hours = match1.group(2)
        minutes = match1.group(3)
        if int(days) < 10:
            notes = '设备运行近期有重启，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '基线异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disver_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display version")
    pattern = r"^HUAWEI USG6655F uptime.*$"
    match = re.search(pattern, result, re.MULTILINE)
    notes = ''
    if match:
        s = match.group()
        match1 = re.search(r'(\d+) days?, (\d+) hours?, (\d+) minutes?', s)
        if match1:
            days = match1.group(1)
            hours = match1.group(2)
            minutes = match1.group(3)
            if int(days) >= 10:
                pass
            else:
                notes = '设备运行近期有重启，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:

            notes = '采集错误，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:

        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def disver_ce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display version")
    pattern = r"^HUAWEI CE6863-48S6CQ uptime.*$"
    match = re.search(pattern, result, re.MULTILINE)
    if match:
        s = match.group()
        match1 = re.search(r'(\d+) days?, (\d+) hours?, (\d+) minutes?', s)
        notes = ''
        if match1:
            days = match1.group(1)
            hours = match1.group(2)
            minutes = match1.group(3)
            if int(days) >= 10:
                pass
            else:
                notes = '设备运行近期有重启，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
            notes = '采集错误，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def disver_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display version")
    pattern = r"^Huarong FM6857E-48S6CQ uptime.*$"
    match = re.search(pattern, result, re.MULTILINE)
    if match:
        s = match.group()
        match1 = re.search(r'(\d+) days?, (\d+) hours?, (\d+) minutes?', s)
        notes = ''
        if match1:
            days = match1.group(1)
            hours = match1.group(2)
            minutes = match1.group(3)
            if int(days) >= 10:
                pass
            else:
                notes = '设备运行近期有重启，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
            notes = '采集错误，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disver_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display version")
    pattern = r"^HUAWEI S5731-H48T4XC Routing Switch uptime.*$"
    match = re.search(pattern, result, re.MULTILINE)
    notes = ''
    if match:
        s = match.group()
        match1 = re.search(r'(\d+) week\S?, (\d+) days?, (\d+) hours?, (\d+) minutes?', s)
        if match1:
            weeks = match1.group(1)
            if int(weeks) >= 1:
                pass
            else:
                notes = '设备运行近期有重启，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
            notes = '采集错误，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disclock(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display clock")
    if 'UTC+08:00' in result:
        pass
    else:
        notes = '时区异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disntp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ntp status")
    if result.count("synchronized") == 2:
        pass
    else:
        notes = 'ntp状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result

def disarp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display arp")
    return result

def dismac(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display mac-address")
    return result



# def dispatch(self,patch):
#     result = self.send_command("display patch-information")
#     if patch in result and "Patch Package State   :Running" in result:
#         return result,"Patch运行状态正常。\n"
#     else:
#         return result,"Patch运行状态异常,请检查\n" + today + " 出现异常啦，快看!!!!!!!!!!!!!!! " + str(
#             random.randint(0, 99999)) + str(random.randint(0, 99999)) + str(
#             random.randint(0, 99999)) + "\n" + result

def dispatch_hwar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display patch-information")
    if str(expend_dic['hw_patch']) in result and "Patch Package State   :Running" in result:
        pass
    else:
        notes = '版本异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dispatch_hwce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display patch-information")
    notes = ''
    if expend_dic['hw_patch'] in result and "Patch Package State   :Running" in result:
        pass
    else:
        notes = '版本异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def dispatch_hwce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display patch-information")
    if expend_dic['hw_patch'] in result and "The state of the patch state file is: Running" \
            in result and "The current state is: Running" in result:
        pass
    else:
        notes = '版本异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dispatch_hwfm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display patch-information")
    if expend_dic['hw_patch'] in result and "Patch Package State   :Running":
        pass
    else:
        notes = '版本异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdir_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"(\d{1,3}(,\d{3})*)\s*KB free"
    match = re.search(pattern, result)
    pattern1 = r"(\d{1,3}(,\d{3})*)\s*KB total"
    match1 = re.search(pattern1, result)
    if match and match1:
        text = int(match.group(1).replace(",", ""))
        text1 = int(match1.group(1).replace(",", ""))
        if (text1 - text) <= 2850000:
            pass
    else:
        notes = '设备存储空间不足，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdir_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"(\d{1,3}(,\d{3})*)\s*KB free"
    match = re.search(pattern, result)
    pattern1 = r"(\d{1,3}(,\d{3})*)\s*KB total"
    match1 = re.search(pattern1, result)
    if match and match1:
        text = int(match.group(1).replace(",", ""))
        text1 = int(match1.group(1).replace(",", ""))
        if (text1 - text) <= 1750000:
            pass
    else:
        notes = '设备存储空间不足，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdir_ce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"(\d{1,3}(,\d{3})*)\s*KB free"
    match = re.search(pattern, result)
    pattern1 = r"(\d{1,3}(,\d{3})*)\s*KB total"
    match1 = re.search(pattern1, result)
    notes = ''
    if match and match1:
        text = int(match.group(1).replace(",", ""))
        text1 = int(match1.group(1).replace(",", ""))
        if (text1 - text) <= 2300000:
            pass
    else:
        notes = 'flash可用空间小于25%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdir_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"(\d{1,3}(,\d{3})*)\s*KB free"
    match = re.search(pattern, result)
    pattern1 = r"(\d{1,3}(,\d{3})*)\s*KB total"
    match1 = re.search(pattern1, result)
    notes = ''
    if match and match1:
        text = int(match.group(1).replace(",", ""))
        text1 = int(match1.group(1).replace(",", ""))
        if (text1 - text) <= 4400000:
            pass
    else:
        notes = 'flash可用空间小于25%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdir_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"(\d{1,3}(,\d{3})*)\s*KB free"
    match = re.search(pattern, result)
    pattern1 = r"(\d{1,3}(,\d{3})*)\s*KB total"
    match1 = re.search(pattern1, result)
    if match and match1:
        text = int(match.group(1).replace(",", ""))
        text1 = int(match1.group(1).replace(",", ""))
        if (text1 - text) <= 600000:
            pass
    else:
        notes = 'flash可用空间小于25%'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdev_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device")
    if result.count("Normal") == 10:
        pass
    else:
        notes = '硬件状态异常,请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdev_fw_ce_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device")
    notes = ''
    if result.count("Normal") == 7:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disdev_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device")
    if result.count("Normal") == 5:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dispic_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device pic-status")
    if result.count("SUCCESS") == 10:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disenv_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display temperature")
    if result.count("NORMAL") == 31:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disenv_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device temperature")
    if result.count("Normal") == 7:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disenv_ce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device temperature all")
    notes = ''
    if result.count("Normal") == 5:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disenv_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device temperature all")
    if result.count("Normal") == 4:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disenv_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display temperature all")
    if result.count("Normal") == 1:
        pass
    else:
        notes = '设备硬件状态异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disfan_fw_ce_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device fan")
    notes = ''
    if result.count("Normal") == 4:
        pass
    else:
        notes = '风扇异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disfan_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display fan")
    if result.count("Present   : YES") == 1 and result.count("Registered: YES") == 1:
        pass
    else:
        notes = '风扇异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disfan_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display fan")
    if result.count("Normal") == 2:
        pass
    else:
        notes = '风扇异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dispower_fw_ce_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device power")
    notes = ''
    if result.count("Supply") == 2:
        pass
    else:
        notes = '电源异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dispower_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display  power")
    if result.count("Supply") == 2:
        pass
    else:
        notes = '电源异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def discpu_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display cpu-usage")
    match = re.search(r"System CPU Using Percentage :  (\d+)%", result)
    if match:
        cpuuse = int(match.group(1))
        if cpuuse <= 75:
            pass
        else:
            notes = 'CPU利用率大于75%，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def discpu_ce_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display cpu")
    match = re.search(r"System CPU Using Percentage :  (\d+)%", result)
    if match:
        cpuuse = int(match.group(1))
        notes = ''
        if cpuuse <= 75:
            pass
        else:
            notes = 'CPU利用率大于75%，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def discpu_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display cpu-usage")
    match = re.search(r"CPU Usage            : (\d+)%", result)
    if match:
        cpuuse = int(match.group(1))
        if cpuuse <= 75:
            pass
        else:
            notes = 'CPU利用率大于75%，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismem_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display memory")
    match = re.search(r"Physical Memory Using Percentage: (\d+)%", result)
    if match:
        menuse = int(match.group(1))
        notes = ''
        if menuse <= 75:
            pass
        else:
            notes = '内存利用率大于75%'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismem(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display memory")
    match = re.search(r"Memory Using Percentage: (\d+)%", result)
    if match:
        menuse = int(match.group(1))
        if menuse <= 75:
            pass
        else:
            notes = '内存利用率大于75%'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismem_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display memory")
    match = re.search(r"Memory Using Percentage Is: (\d+)%", result)
    if match:
        menuse = int(match.group(1))
        if menuse <= 75:
            pass
        else:
            notes = '内存利用率大于75%'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismem_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display memory-usage")
    match = re.search(r"Memory Using Percentage Is: (\d+)%", result)
    if match:
        menuse = int(match.group(1))
        if menuse <= 75:
            pass
        else:
            notes = '内存利用率大于75%'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def discpu_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display cpu-usage")
    match = re.search(r"System cpu use rate is : (\d+)%", result)
    if match:
        cpuuse = int(match.group(1))
        if cpuuse <= 75:
            pass
        else:
            notes = 'CPU利用率大于75%，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disalarm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display alarm active")
    if result:
        text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result)
        if jixian:
            text2 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "",
                           jixian)
            if compare_text(text1, text2) == 1:
                pass
            else:
                notes = '设备存在异常告警，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
            notes = '告警基线异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result
    else:
        result='设备无异常告警'
        return result


def disintbrief(self, time, name, con, jixian, expend_dic):  # 接口,CRC,收发光
    result = self.send_command("display interface brief")
    pattern = r'(\S+)%'
    match1 = re.findall(pattern, result)
    for i in match1:
        if float(i) > 50:
                notes = '接口' + i + '利用率大于50%，请检查'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    c1 = jixian
    with open(disint_txm_path, encoding='utf8') as textfsm_file:
        template = TextFSM(textfsm_file)
        s2 = template.ParseTextToDicts(result)
    with open(disint_txm_path, encoding='utf8') as textfsm_file:
        template = TextFSM(textfsm_file)
        s3 = template.ParseTextToDicts(c1)
    if s2 and s3:
        intf_df2 = pd.DataFrame(s2)
        df_selected1 = intf_df2[
        ['INTERFACE', 'LINK_STATUS', 'PROTOCOL_STATUS', 'INERRORS', 'OUTERRORS']]
        contrast1 = str(df_selected1)
        intf_df3 = pd.DataFrame(s3)
        df_selected2 = intf_df3[
        ['INTERFACE', 'LINK_STATUS', 'PROTOCOL_STATUS', 'INERRORS', 'OUTERRORS']]
        contrast2 = str(df_selected2)
        if compare_text(contrast1, contrast2) == 1:
            pass
        else:
            notes = '接口异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result

def disint(self, time, name, con, jixian, expend_dic):  # 接口整体信息
    result = self.send_command("display interface")
    return result



def disipintbrief(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip interface brief")
    c1 = jixian
    if compare_text(result, c1):
        pass
    else:
        notes = 'IP接口异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result



def dishrp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display hrp state")
    if result.count("succeeded") == 1:
        pass
    else:
        notes = 'HRP状态异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disethtr_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display eth-trunk brief")
    if result.count("2/0/2") == 2:
        pass
    else:
        notes = '聚合口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disethtr_ce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display eth-trunk brief")
    notes = ''
    if result.count("2/0/2") == 2 and result.count("1/0/1") == 13:
        pass
    else:
        notes = '聚合口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disethtr_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display eth-trunk brief")
    if result.count("2/0/2") == 1 and result.count("1/0/1") == 3:
        pass
    else:
        notes = '聚合口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disethtr_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display eth-trunk")
    if result.find("Operate status: up") and result.find("Number Of Up Port In Trunk: 2") and result.count(
            "Selected") == 2:
        pass
    else:
        notes = '聚合口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disethtr_fw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display eth-trunk brief")
    if result.count("2/0/2") == 3:
        pass
    else:
        notes = '聚合口异常'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dislldp_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display lldp neighbor brief")
    pattern = r"\s{3}[0-9]+"
    text = re.sub(pattern, "", result, flags=re.MULTILINE)
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text)

    result1 = jixian

    text_ = re.sub(pattern, "", result1, flags=re.MULTILINE)
    text_1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text_)
    if compare_text(text1, text_1) == 1:
        pass
    else:
        notes = 'LLDP异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dislldp_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display lldp neighbor brief")
    text = re.sub(r"\s\d{1,3}\s", "", result, flags=re.MULTILINE)
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text)
    text3 = re.sub(r"\s\d{1,4}\s", "", text1, flags=re.MULTILINE)
    result1 = jixian
    text_ = re.sub(r"\s\d{1,3}\s", "", result1, flags=re.MULTILINE)
    text_1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text_)
    text3_ = re.sub(r"\s\d{1,4}\s", "", text_1, flags=re.MULTILINE)
    if compare_text(text3, text3_) == 1:
        pass
    else:
        notes = 'LLDP异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dislldp_fw_ce(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display lldp neighbor brief")
    text = re.sub(r'\s\d{1,4}\s', '', result, flags=re.M)
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text)
    notes = ''

    result1 = jixian
    text_ = re.sub(r'\s\d{1,4}\s', '', result1, flags=re.M)
    text_1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text_)

    if compare_text(text1, text_1) == 1:
        pass
    else:
        notes = 'lldp与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dislldp_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display lldp neighbor brief")
    text = re.sub(r'\s\d{2,3}\s', '', result, flags=re.M)
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text)

    result1 = jixian

    text_ = re.sub(r'\s\d{2,3}\s', '', result1, flags=re.M)
    text_1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", text_)
    if compare_text(text1, text_1) == 1:
        pass
    else:
        notes = 'lldp与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


#def dismac(self, time, name, con, jixian, expend_dic):
#    # 带外汇聚交换机会删除25GE端口前面的25
#    result = self.send_command("display mac-address")
#    pattern = r"\s{4}[0-9]+"
#    text = re.sub(pattern, '', result, flags=re.MULTILINE)
#
#    result1 = jixian
#    text_ = re.sub(pattern, '', result1, flags=re.MULTILINE)
#    if compare_text(text, text_) == 1:
#        pass
#    else:
#        notes = 'MAC地址与基线不一致，请对比检查'
#        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
#    return result


def dismac_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display mac-address")

    result1 =jixian
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = 'MAC地址与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def discrc(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display interface | i CRC")
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result)
    notes = ''
    result1 = jixian
    text1_ = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result1)
    if compare_text(text1, text1_) == 1:
        pass
    else:
        notes = '与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


#def disarp(self, time, name, con, jixian, expend_dic):
#    result = self.send_command("display arp")
#    text = re.sub(r'\s\d{1,2}\s', '', result, flags=re.M)
#    result1 = jixian
#    text_ = re.sub(r'\s\d{1,2}\s', '', result1, flags=re.M)
#    if compare_text(text, text_) == 1:
#        pass
#    else:
#        notes = '与基线不一致，请对比检查'
#        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
#    return result


def disstp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display stp brief")
    result1 = jixian

    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disfiresess(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display firewall session statistics all-systems")
    match = re.search(r"Total (\d+)", result)
    notes = ''
    if match:
        if int(match.group(1)) < 1000:
            pass
        else:
            notes = '防火墙会话数异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disospfnei_ar(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ospf peer brief")
    if result.count("Full") == 2 and result.count("0.0.0.0") == 2:
        pass
    else:
        notes = 'OSPF邻居异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    return result


def disospferror(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ospf error")
    result1 =jixian

    if compare_text(result, result1) == 1:
        pass
    else:
        notes = 'OSPF错误信息异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disospfrouting(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ospf routing")
    result1 = jixian

    if compare_text(result, result1) == 1:
        pass
    else:
        notes = 'OSPF路由表异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disospflsdb(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ospf lsdb brief")
    result1 = jixian
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = 'OSPFLSDB异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disiprouting(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip routing-table")
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result)
    result1 = jixian
    text1_ = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result1)
    if compare_text(text1, text1_) == 1:
        pass
    else:
        notes = '与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disiprouting_ce_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip routing-table all-vpn-instance")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disroutesstatis(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip routing-table all-routes statistics")
    text1 = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result)
    result1 = jixian
    text1_ = re.sub(r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}\.\d{1,3}\s\+\d{2}:\d{2}", "", result1)
    if compare_text(text1, text1_) == 1:
        pass
    else:
        notes = '与基线不一致，请对比检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismlag(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display dfs-group 1 m-lag brief")
    notes = ''
    if result.count(" success ") == 14:
        pass
    else:
        notes = 'success数量小于14，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismlag_fm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display dfs-group 1 m-lag brief")
    notes = ''
    if result.count("success") == 3:
        pass
    else:
        notes = 'success数量小于3，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dismlaghear(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display dfs-group 1 heartbeat")
    if result.count("Heart beat status  : OK") == 1:
        pass
    else:
        notes = 'Heart beat status  : OK数量小于1，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def extract_and_check_power(text):
    rx_power_pattern = r"Rx\s+Power:\s+(-?\d+\.\d+)dBm,\s+Warning range:\s+\[(-?\d+\.\d+),\s+(-?\d+\.\d+)\]dBm"
    tx_power_pattern = r"Tx\s+Power:\s+(-?\d+\.\d+)dBm,\s+Warning range:\s+\[(-?\d+\.\d+),\s+(-?\d+\.\d+)\]dBm"

    rx_powers = re.findall(rx_power_pattern, text)
    tx_powers = re.findall(tx_power_pattern, text)

    in_range_rx = []
    in_range_tx = []
    for rx in rx_powers:
        rx_value = float(rx[0])  # Remove 'dBm' before converting to float
        if rx_value >= float(rx[1]) and rx_value <= float(rx[2]):
            in_range_rx.append((rx_value, (float(rx[1]), float(rx[2]))))

    for tx in tx_powers:
        tx_value = float(tx[0])  # Remove 'dBm' before converting to float
        if tx_value >= float(tx[1]) and tx_value <= float(tx[2]):
            in_range_tx.append((tx_value, (float(tx[1]), float(tx[2]))))

    return in_range_rx, in_range_tx


def disintwarn(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display interface | include GigabitEthernet |Warning range")
    re1, re2 = extract_and_check_power(result)
    if len(re1) == 6 and len(re2) == 6:
        pass
    else:
        notes = '接口收发光异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result

#    text1 = re.sub(r"(-?\d+\.\d+)",
#                       lambda x: str(math.ceil(float(x.group(0)))) if float(x.group(0)) < 0 else str(
#                           math.floor(float(x.group(0)))), str(result))
#    if jixian:
#        result2=jixian
#        text2=re.sub(r"(-?\d+\.\d+)",
#                       lambda x: str(math.ceil(float(x.group(0)))) if float(x.group(0)) < 0 else str(
#                           math.floor(float(x.group(0)))), str(result2))
#        if compare_text(text1, text2)==1:
#            pass
#        else:
#            notes = '接口收发光异常，请检查'
#            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
#    else:
#        notes = '接口收发光异常，请检查'
#        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
#    return result


def distrans_ce57(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display transceiver verbose")
    pattern1 = r"RX Power.*$"
    match = re.findall(pattern1, result, flags=re.MULTILINE)
    output_list = []
    for xx in match:
        output_list.append(re.sub(r"(-?\d+\.\d+)",
                                  lambda x: str(math.ceil(float(x.group(0)))) if float(x.group(0)) < 0 else str(
                                      math.floor(float(x.group(0)))), xx))
    s = ''
    for i in output_list:
        s = s + i + '\n'

    result1 = jixian
    match1 = re.findall(pattern1, result1, flags=re.MULTILINE)
    if match1:
        output_list1 = []
        for xx in match1:
            output_list1.append(re.sub(r"(-?\d+\.\d+)",
                                       lambda x: str(math.ceil(float(x.group(0)))) if float(
                                           x.group(0)) < 0 else str(
                                           math.floor(float(x.group(0)))), xx))
        s1 = ''
        for i in output_list1:
            s1 = s1 + i + '\n'
        if compare_text(s, s1) == 1:
            pass
        else:
            notes = '接口收发光异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disinterror(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display interface | inc error")
    text1 = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,3} \+\d{2}:\d{2}', '', result)
    text2 = re.sub(r'\d* jumbo,', '', text1)
    match = re.findall(r'\d ', text2)
    flag=0
    if match:
        for i in match:
            if int(i) > 0:
                flag=1
    else:
        notes = '基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    if flag==1:
        notes = '接口异常错包，请检查'
        print(notes)
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def distrans(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display interface transceiver verbose")
    pattern1 = r"Current RX Power.*$"
    match = re.findall(pattern1, result, flags=re.MULTILINE)
    if match:
        output_list = []
        for xx in match:
            output_list.append(re.sub(r"(-?\d+\.\d+)",
                                      lambda x: str(math.ceil(float(x.group(0)))) if float(x.group(0)) < 0 else str(
                                          math.floor(float(x.group(0)))), xx))
        s = ''
        for i in output_list:
            s = s + i + '\n'

    result1 = jixian
    match1 = re.findall(pattern1, result1, flags=re.MULTILINE)
    if match1:
        output_list1 = []
        for xx in match1:
            output_list1.append(re.sub(r"(-?\d+\.\d+)",
                                       lambda x: str(math.ceil(float(x.group(0)))) if float(
                                           x.group(0)) < 0 else str(
                                           math.floor(float(x.group(0)))), xx))
        s1 = ''
        for i in output_list:
            s1 = s1 + i + '\n'
        if compare_text(s, s1) == 1:
            pass
        else:
            notes = '接口收发光异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)

    else:
        notes = '基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def dislog(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display logbuffer")
    return result

def disvrrp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display vrrp verbose")
    time_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{2,3} \+\d{2}:\d{2}'
    result_time = re.sub(time_pattern, '', result, flags=re.MULTILINE)
    result_time2 = re.sub(time_pattern, '', jixian, flags=re.MULTILINE)
    notes=''
    if compare_text(result_time, result_time2) == 1:
        pass
    else:
        notes = 'Vrrp状态异常，请检查！'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result






def h3cfw_disver(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display  version")
    pattern = r"^H3C SecPath F1000-AI-65 uptime is.*$"
    match = re.search(pattern, result, re.MULTILINE)
    notes = ''
    if match:
        s = match.group()
        match1 = re.search(r'(\d+) week\S?, (\d+) days?, (\d+) hours?, (\d+) minutes?', s)
        if match1:
            weeks = match1.group(1)
            if int(weeks) >= 1:
                    pass
            else:
                notes = '设备运行近期有重启，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        else:
                notes = '采集错误，请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disntp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display  ntp-service    status")
    notes = ''
    if "Clock status: synchronized" in result:
        pass
    else:
        notes = 'ntp状态异常，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disdir(self, time, name, con, jixian, expend_dic):
    result = self.send_command("dir")
    pattern = r"\d{1,7}\s*KB free"
    match = re.search(pattern, result)
    notes = ''
    if match:
        free = int(match.group().split(" ")[0])
        if free > 760000:
            pass
        else:
            notes = '存储空间不足，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disdev(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display device")
    notes = ''
    if "F1000-AI-65   Normal" in result:
        pass
    else:
        notes = '硬件状态异常，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disenv(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display  environment")
    text1 = re.findall(r"inflow\s+\d+\s+(\d+)", result)
    text2 = re.findall(r"outflow\s+\d+\s+(\d+)", result)
    text3 = re.findall(r"hotspot\s+\d+\s+(\d+)", result)
    notes = ''
    if text1[0] < 47 and text2[0] < 68 and text3[0] < 63 and text3[1] < 84:
        pass
    else:
        notes = '温度异常，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disfan(self, time, name, con, jixian, expend_dic):
    # 调用command()函数，显示风扇状态
    result = self.send_command("display fan")
    # 检查“Status: Normal”的数量是否为4
    notes = ''
    if result.count("Status: Normal") == 4:
        # 如果数量为4，返回结果和提示信息
        pass
    else:
        notes = '设备风扇硬件运行异常,请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_dispower(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display power")
    notes = ''
    if "1         Normal    AC" in result:
        pass
    else:
        notes = '设备电源硬件运行异常,请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_discpu(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display cpu-usage")
    pattern = r"(\d)%"
    match = re.findall(pattern, result)
    notes = ''
    if match:
        for i in match:
            if int(i) > 50:
                notes = '设备cpu利用率异常,请检查\n'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def disclock_h3cfw(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display clock")
    notes = ''
    if 'BJ add 08:00:00' in result:
        pass
    else:
        notes = '设备时区错误'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_dismem(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display  memory")
    pattern = r'(\d+\.\d+)%'
    match = re.search(pattern, result)
    if match:
        mem1 = int(float(match.group(0).split("%")[0]))
        notes = ''
        if mem1 > 25:
            pass
        else:
            notes = '设备cpu利用率异常,请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disethtrunk(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display link-aggregation verbose Route-Aggregation 1")
    notes = ''
    if 'XGE1/0/24        S       32768    2         {ACDEF}' in result and 'XGE1/0/25        S       32768    2         {ACDEF}' in result:
        pass
    if '  XGE1/0/24        U       32768    1         {AC}' in result and 'XGE1/0/25        U       32768    1         {AC}' in result:
        pass
    else:
        notes = '采集错误，请检查\n'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disintbrief(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display int brief")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disipintbrief(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip int brief")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disiproute(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display ip routing-table")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_dislldp(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display lldp neighbor-information list")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_disalarm(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display alarm")
    result1 = jixian
    if jixian:
        if compare_text(result, result1) == 1:
            pass
        else:
            notes = '设备存在异常告警，请检查\n'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    if not jixian and not result:
        result = '无异常告警'
    else:
        notes = '告警基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_dissession(self, time, name, con, jixian,
                     expend_dic):  # ----------------------------------------------------------------------------------------
    result = self.send_command("display session statistics ipv4")
    pattern = r"(?<=Current sessions: )\d+"
    match = re.search(pattern, result)
    notes = ''
    if match:
        if int(match.group()) < 1000:
            pass
        else:
            notes = '防火墙会话异常，请检查'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    else:
        notees = '采集异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


def h3cfw_discur(self, time, name, con, jixian, expend_dic):
    result = self.send_command("display current")
    result1 = jixian
    notes = ''
    if compare_text(result, result1) == 1:
        pass
    else:
        notes = '对比基线异常，请检查'
        result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
    return result


