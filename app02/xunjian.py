import json
from netmiko import ConnectHandler
import re
from app02.models import device_table,function_table,group_table,function_group_relationship_table,result_overall_table,result_specific_table,result_notes_table
import logging
from textfsm import TextFSM
from paramiko import SSHClient, AutoAddPolicy
import math
import difflib
import paramiko
import os
import datetime
from django.conf import settings
from time import sleep

base_dir = settings.BASE_DIR
tapint_txm_path = os.path.join(base_dir, 'app02', 'tap_intcount.textfsm')

def compare_text(text1, text2):
    text1 = re.sub(r'\s+', ' ', text1).strip()  # 合并空白字符并去除两端的空白
    text2 = re.sub(r'\s+', ' ', text2).strip()  # 合并空白字符并去除两端的空白
    matcher = difflib.SequenceMatcher(None, text1, text2)
    return matcher.ratio()

def xunjian_device(device_name,ip,user,password,time,device_type,all_functions,logger):
    #try:
        device = {
            'device_type': device_type,
            'ip': ip,
            'username': user,
            'password': password,
        }
        logger.info(f'开始巡检{device_name}')
        device_info=device_table.objects.filter(device=device_name).first()
        group_name = device_info.group_name
        dict= device_info.expand
        dict1=json.loads(dict)
        logger.info('导入基线')
        if result_overall_table.objects.filter(jixian=True).first():
            jixian_time= result_overall_table.objects.filter(jixian=True).first()
        else:
            jixian_time= ''
        group_id = group_table.objects.filter(group_name=group_name).first().id
        logger.info('导入函数列表')
        func_obj=function_group_relationship_table.objects.filter(group_id=group_id).all()
        i=0
        net_connect = ConnectHandler(
            **device,
            global_delay_factor=1.5,  # 设置全局延迟因子
        )
        print( datetime.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")+device_name+'巡检开始')
        with net_connect as connect:
            for obj in func_obj:
                if obj.func in all_functions:
                    func=all_functions[obj.func]
                    command = function_table.objects.filter(func=obj.func).first().command
                    if jixian_time:
                        jixian_obj=result_specific_table.objects.filter(time=jixian_time.time, device=device_name, command=command).first()
                        if jixian_obj:
                            jixian= jixian_obj.result
                        else:
                            jixian = ''

                    else:
                        jixian = ''
                else:
                    jixian = ''
                    logger.info(f'{device_name}执行{obj.func}时，函数未定义或函数名错误')
                logger.info(f'{device_name}执行{obj.func}')
                result=func(connect,time,device_name,command,jixian,dict1)
                if result:
                    result_specific_table.objects.create(device=device_name,command=command,result=result,time=time)
                    #if command=='show running-config'or command=='display current-configuration':
                     #   if  result_notes_table.objects.filter(device=device_name,command=command,time=time):
                      #      if '配置不一致' in result_notes_table.objects.filter(device=device_name,command=command,time=time).first().notes:
                       #         result_specific_table.objects.filter(device=device_name,command=command,time=time).update(config_changed='配置对比不一致')
                    i = i + 1
                else:
                    notes = '设备采集为空，请检查'
                    result_notes_table.objects.create(time=time, device=device_name, notes=notes, confirm=False, command=command)
        print( datetime.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")+device_name+'巡检完成')
        return device_name,i
   # except Exception as e:
    #    logging.error(f'{device_name}巡检失败，原因{e}')

class ConnectDevice:
    def __init__(self, server, username, password):
        self.server = server
        self.username = username
        self.password = password

        self.client = self._get_client()
        self.cli = self.client.invoke_shell()

    def _get_client(self):
        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        client.connect(self.server, username=self.username, password=self.password)
        return client

    def command(self, cmd):  # 输入命令
        if cmd == "display interface | inc error" or cmd == "display interface transceiver verbose" or cmd == "display interface | i CRC" or cmd == "display logbuffer":
            self.cli.send("{}\n".format(cmd))
            sleep(15)
            return self.cli.recv(999999).decode("utf-8", "ignore")
        elif cmd == "display current" or cmd == "show interface info" or cmd == "show interface count" or cmd == "dir":
            self.cli.send("{}\n".format(cmd))
            sleep(5)
            return self.cli.recv(999999).decode("gb18030", "ignore")
        else:
            self.cli.send("{}\n".format(cmd))
            sleep(3)
            return self.cli.recv(99999).decode("utf-8", "ignore")


    def close_connection(self):
        """
        关闭 SSH 连接。
        """
        if self.cli:
            self.cli.close()
        if self.client:
            self.client.close()

    def __del__(self):
        """
        确保在对象被销毁时关闭连接。
        """
        self.close_connection()










    def tapdev(self, time, name, con, jixian, expend_dic):
        result= self.command("show device")
        notes = ''
        if '03' in name:
            text = re.search(r"Master temperature:\s+(\d+)'c", result)
            text2=re.search(r"Slave temperature:\s+(\d+)'c", result)
            if text:
                if result.count("OK") == 5 and int(text.group(1)) < 70 and int(text2.group(1)) < 70:
                    pass
                else:
                    notes = 'tap设备异常，请检查'
                    result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
            else:
                notes = '采集异常'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
            return result
        else:
            text = re.search(r"Temperature:\s+(\d+)'c", result)
            if text:
                if result.count("OK") == 8 and int(text.group(1)) < 70:
                    pass
                else:
                    notes = 'tap设备异常，请检查'
                    result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
            else:
                notes = '采集异常'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
            return result 


    def taprun(self, time, name, con, jixian, expend_dic):
        result = self.command("show running-config")
        result1 =jixian
        notes = ''
        if compare_text(result, result1) == 1:
            pass
        else:
            notes = '基线对比异常，请查看'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result


    def tapintstate(self, time, name, con, jixian, expend_dic):
        result = self.command("show interface state")
        result1 =jixian
        notes = ''
        if compare_text(result, result1) == 1:
            pass
        else:
            notes = '基线对比异常，请查看'
            result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result


    def taptrans(self, time, name, con, jixian, expend_dic):
        result = self.command("show interface info")
        text = re.sub(r"(-?\d+\.\d+)",
                      lambda x: str(math.ceil(float(x.group(0)))) if float(x.group(0)) < 0 else str(
                          math.floor(float(x.group(0)))), result)
        return result


    def tapcount(self, time, name, con, jixian, expend_dic):
        result = self.command("show interface count")
        with open(tapint_txm_path, encoding='utf8') as textfsm_file:
            template = TextFSM(textfsm_file)
            s2 = template.ParseTextToDicts(result)
        tap01 = ["4", '6', '16', '18', '24', '26', '36', '38', '40', '42', '44', '45', '46', '47', '48', '49', '50',
                 '51']
        tap02 = ['40', '41', '42', '43', '44', '45', '46', '47', '48', '49', '50', '51']
        tap03 = ['0', '1', '2', '3', '4', '5', '6', '7']
        if 'TAP' in name:
            if '01' in name:
                tap = tap01
            if '02' in name:
                tap = tap02
            if '03' in name:
                tap = tap03
        flag = 0
        for i in s2:
            if i['PktsIn'] == '0' and i['Interface'] not in tap:
                flag = 1
            if i['Errors'] != '0':
                flag = 1
        if flag == 0:
            pass
        else:
            if 'TAP' in name and '03' in name:
                pass
            else:
                notes = '接口异常错包，请查看'
                result_notes_table.objects.create(time=time, device=name, notes=notes, confirm=False, command=con)
        return result



def xunjian_paramiko(device_name,ip,user,password,time):
    logging.info(f'开始巡检{device_name}')
    device_info = device_table.objects.filter(device=device_name).first()
    dict = device_info.expand
    dict1 = json.loads(dict)
    logging.info('导入基线')
    if result_overall_table.objects.filter(jixian=True).first():
        jixian_time = result_overall_table.objects.filter(jixian=True).first()
    else:
        jixian_time = ''
    i = 0
    command_group=['show device','show running-config','show interface state','show interface count','show interface info']
    connect = ConnectDevice(ip, user, password)
    result2 = connect.command("./vtysh")
    sleep(1)
    result1 = connect.command("terminal length 0")
    sleep(1)
    for x in command_group:
        print(x)
        if jixian_time:
            jixian_obj = result_specific_table.objects.filter(time=jixian_time.time, device=device_name,
                                                              command=x).first()
            #xxxxx
            if jixian_obj:
                jixian = jixian_obj.result
            else:
                jixian = ''
        if 'dev' in x:
            resulttap= connect.tapdev(time, device_name, x, jixian, dict1)
        if 'run' in x:
            resulttap=connect.taprun(time, device_name, x, jixian, dict1)
        if 'state' in x:
            resulttap=connect.tapintstate(time, device_name, x, jixian, dict1)
        if 'count' in x:
            resulttap=connect.tapcount(time, device_name, x, jixian, dict1)
        if 'info' in x:
            resulttap=connect.taptrans(time, device_name, x, jixian, dict1)
        if resulttap:
            result_specific_table.objects.create(device=device_name, command=x, result=resulttap, time=time)
        else:
            notes = '设备采集为空，请检查'
            result_notes_table.objects.create(time=time, device=device_name, notes=notes, confirm=False, command=x)
    connect.close_connection()
    return device_name, i



