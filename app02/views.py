from django.http import JsonResponse
from app02.models import device_table,result_overall_table,group_table,function_table,function_group_relationship_table,result_specific_table,result_notes_table
from app02 import xunjian
from django.views.decorators.csrf import csrf_exempt
import pandas as pd
import difflib
import json
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.shortcuts import render, redirect
from .forms import MyForm
import datetime
from django.conf import settings
import os
from app02.utils.pagination import Pagination
from app02 import methon
import logging
import pkgutil
import importlib
from concurrent.futures import ThreadPoolExecutor, as_completed

base_dir = settings.BASE_DIR
file_path = os.path.join(base_dir, 'app02', 'static', 'example.xlsx')




def device_add(request):
    if request.method=="GET":
        return  render(request, 'device_add.html')
    device = request.POST.get('device')
    ip = request.POST.get('ip')
    group_name = request.POST.get('group_name')
    user = request.POST.get('user')
    password = request.POST.get('pwd')
    device_type = request.POST.get('device_type')
    port_up= request.POST.get('port_up')
    lldp_nei = request.POST.get('lldp_nei')
    ospf_nei = request.POST.get('ospf_nei')
    pim_nei = request.POST.get('pim_nei')
    zb = request.POST.get('zb')
    hw_patch = request.POST.get('hw_patch')
    dict ={'port_up':port_up,'lldp_nei':lldp_nei,'ospf_nei':ospf_nei,'pim_nei':pim_nei,'zb':zb,'hw_patch':hw_patch}
    dict1=json.dumps(dict)
    device_table.objects.create(device=device,ip=ip,group_name=group_name,user=user,password=password,device_type=device_type,expand=dict1)
    return redirect("/info/list/")

def device_delete(request):
    nid=request.GET.get("nid")
    device_table.objects.filter(id=nid).delete()
    return redirect("/info/list/")



def test_test(request):
    df = pd.read_excel('example.xlsx', sheet_name='Sheet5')
    # dict_from_df = df.to_dict(orient='dict')
    result_dict = pd.Series(df.iloc[:, 1].values, index=df.iloc[:, 0]).to_dict()
    print(result_dict)
    for key, value in result_dict.items():
        if function_group_relationship_table.objects.filter(func=key,group_id=value).exists():  # 如果存在，不更新
            pass
        else:  # 如果不存在，则创建
            function_group_relationship_table.objects.create(func=key, group_id=value)
    return render(request, 'info_list.html')


def func_delete(request):
    nid = request.GET.get("nid")
    function_table.objects.filter(id=nid).delete()
    return redirect("/info/list/")
def group_add(request):
    if request.method=="GET":
        return  render(request, 'group_add.html')
    group = request.POST.get('group_name')
    group_table.objects.create(group_name=group)
    return redirect("/info/list/")

def test_add(request):
    if request.method=="GET":
        return  render(request, 'test.html')
    group = request.POST.get('group_name')
    group_table.objects.create(group_name=group)
    return redirect("/info/list/")

def func_add(request):
    if request.method=="GET":
        return  render(request, 'func_add.html')
    func = request.POST.get('func')
    command = request.POST.get('command')
    function_table.objects.create(func=func,command=command)
    return redirect("/info/list/")


def boundfunc_add(request):
    nid = request.GET.get("nid")
    nid = request.GET.get("nid")
    func_list1=function_group_relationship_table.objects.filter(group_id=nid).all()
    func_list = function_table.objects.all()
    group_list = group_table.objects.all()
    return render(request, 'boundfunc_edit.html',{"func_list":func_list,"func_list1":func_list1,"group_list": group_list})



def boundfunc_edit(request):
    nid = request.GET.get("nid")
    func_list1=function_group_relationship_table.objects.filter(group_id=nid).all()
    func_list = function_table.objects.all()
    group_list = group_table.objects.all()
    return render(request, 'boundfunc_edit.html',{"func_list":func_list,"func_list1":func_list1,"group_list": group_list})


def bound_funcgroup(request):
    if request.method == "POST":
        # 从POST请求中获取选中的函数和组
        selected_funcs = request.POST.getlist('func')
        group_id = request.POST.get('group_id')
        # if request.POST.get('button1'):
        #     print('button1')
        #     func_list = function_table.objects.all()
        #     group_list = group_table.objects.all()
        #     return render(request, "bound_funcgroup.html", {"func_list": func_list, "group_list": group_list,'selected_funcs':selected_funcs})
        # if request.POST.get('button2'):
        #     print('button2')
        for func in selected_funcs:
            if function_group_relationship_table.objects.filter(func=func).exists():
                if function_group_relationship_table.objects.filter(func=func).first().group_id != group_id:
                    function_group_relationship_table.objects.create(func=func, group_id=group_id)
            else:
                # 在数据库中创建新的关系
                function_group_relationship_table.objects.create(func=func, group_id=group_id)
        # 重定向到另一个页面
        return redirect("/info/list/")
    if request.method == "GET":
        # 获取所有函数和组，传递给模板
        func_list = function_table.objects.all()
        group_list = group_table.objects.all()
        return render(request, "bound_funcgroup.html", {"func_list": func_list, "group_list": group_list})

def boundfg_delete(request):
    nid=request.GET.get("nid")
    function_group_relationship_table.objects.filter(id=nid).delete()
    return redirect("/info/list/")
@csrf_exempt
def info_xunjian(request):
    # try:
        all_functions = import_functions_from_package(methon)
        device = device_table.objects.all()
        name = request.session['info']['name']
        today = datetime.datetime.now().strftime("%Y-%m-%d_%H_%M_%S")
        log_file = os.path.join(base_dir, 'app02', 'logfile', today + '.log')

        # 创建新的日志记录器
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        # 创建文件处理器
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # 创建格式化器并添加到处理器
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        # 将处理器添加到日志记录器
        logger.addHandler(file_handler)
        xunjian_all_device = 0
        xunjian_all_func=0
        time=datetime.datetime.now()
        time_str=str(time)
        args_list=[]
        args_list1 = []
        xunjian_tap=0
        for i in device:
            print(i.device,i.ip,i.user,i.password, time_str,i.device_type)
            if 'TAP' in i.device:
                args_list1.append([i.device,i.ip,i.user,i.password, time_str])
            else:
                args_list.append([i.device,i.ip,i.user,i.password, time_str,i.device_type,all_functions,logger])
        with ThreadPoolExecutor(max_workers=32) as executor:
            # 提交任务到线程池
                results = executor.map(lambda args: xunjian.xunjian_device(*args), args_list)
                results2 = executor.map(lambda args: xunjian.xunjian_paramiko(*args), args_list1)
                # 获取已完成的线程的返回值
                for result in results:
                    if result is not None:
                        xunjian_all_device = xunjian_all_device + 1
                        xunjian_all_func=xunjian_all_func+result[1]
                    else:
                        logger.info(f"设备执行失败，返回值为 None")
                for result in results2:
                    if result is not None:
                        xunjian_all_device = xunjian_all_device + 1
                    else:
                        logger.info(f"tap设备执行失败，返回值为 None")
                logger.info("线程执行完毕")
        result_all= result_notes_table.objects.filter(time=time_str,confirm=False)
        if result_all.exists():
            result='异常'
        else:
            result='正常'
        result_overall_table.objects.create(time=time_str,user_xnjian=name, jixian=False, result=result)
        xunjian_all_device=xunjian_all_device+xunjian_tap
        logger.info(f"已完成{xunjian_all_device}台设备巡检,共执行{xunjian_all_func}个巡检项")
        return JsonResponse({'success': 'success', 'message': f'已完成{xunjian_all_device}台设备巡检,共执行{xunjian_all_func}个巡检项。'}, status=200)
    # except Exception as e:
    #     logging.error(f"An error occurred: {e}")
    #     return JsonResponse({'error': '错误', 'message': '巡检错误。'}, status=400)

def import_functions_from_package(package):
    functions = {}
    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__, package.__name__ + '.'):
        module = importlib.import_module(modname)
        for attr_name in dir(module):
            if not attr_name.startswith('__'):
                attr = getattr(module, attr_name)
                if callable(attr):
                    functions[attr_name] = attr
    return functions

def info_xunjiantest(request):
    try:
        all_functions = import_functions_from_package(methon)
        group_name = request.GET.get('selected_value',None)
        # group_name= group_table.objects.get(id=group_id).group_name
        device = device_table.objects.filter(group_name=group_name).all()
        name = request.session['info']['name']
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d_%H_%M_%S")
        logging.basicConfig(
            filename=os.path.join(base_dir, 'app02', 'logfile', today + '.log'),  # 日志文件名
            filemode='a',  # 模式，有追加和写入两种
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 日志格式
            level=logging.INFO  # 日志级别
        )
        xunjian_all_device = 0
        xunjian_all_func = 0
        time = datetime.datetime.now()
        time_str = str(time)
        args_list = []
        for i in device:
            args_list.append([i.device, i.ip, i.user, i.password, time_str, i.device_type, all_functions])
        with ThreadPoolExecutor(max_workers=5) as executor:
            # 提交任务到线程池
            results = executor.map(lambda args: xunjian.xunjian_device(*args), args_list)
            # 获取已完成的线程的返回值
            for result in results:
                if result is not None:
                    xunjian_all_device = xunjian_all_device + 1
                    logging.info(f"设备: {result[0]}, 执行函数共: {result[1]}")
                    xunjian_all_func = xunjian_all_func + result[1]
                else:
                    logging.info(f"设备执行失败，返回值为 None")
            logging.info("线程执行完毕")
        # try:
        #     logging.info("开始写入线程")
        #     for i in device:
        #         t = threading.Thread(target=xunjian.xunjian_device,
        #                              args=(i.device,i.ip,i.user,i.password, time_str,i.device_type,all_functions))
        #         threads.append(t)
        #         t.start()
        #         logging.info(f"写入完成 {i.device}")
        #         flag = flag + 1
        #     logging.info("开始执行线程")
        #     for thread in tqdm(threads):
        #         # 等待线程完成
        #         thread.join()
        result_all = result_notes_table.objects.filter(time=time_str, confirm=False)
        if result_all.exists():
            result = '异常'
        else:
            result = '正常'
        result_overall_table.objects.create(time=time_str, user_xnjian=name, jixian=False, result=result)
        logging.info(f"已完成{xunjian_all_device}台设备巡检,共执行{xunjian_all_func}个函数")
        return JsonResponse(
            {'success': 'success', 'message': f'已完成{xunjian_all_device}台设备巡检,共执行{xunjian_all_func}个函数。'},
            status=200)
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return JsonResponse({'error': '错误', 'message': '巡检错误。'}, status=400)


def info_list(request):
    data_list = device_table.objects.all()
    data_list1=function_table.objects.all()
    data_list2 = group_table.objects.all()
    data_list3 = function_group_relationship_table.objects.all()
    if result_overall_table.objects.filter(jixian=1).first():
        jixian=result_overall_table.objects.filter(jixian=1).first().time
    else:
        jixian= {'1':1}
    group_list = group_table.objects.all()
    return render(request,"info_list.html",{"data_list":data_list,'jixian':jixian,"data_list1":data_list1,"data_list2":data_list2,"data_list3":data_list3,"group_list": group_list})

# myapp/views.py



def my_view(request):
    if request.method == 'GET':
        form = MyForm(request.GET)
        if form.is_valid():
            form.save()
            return redirect('success_url')  # 替换为您的实际 URL 名称
    else:
        form = MyForm()
    return render(request, 'my_template.html', {'form': form})


def history_delete(request):
    nid=request.GET.get("nid")
    result_overall_table.objects.filter(time=nid).delete()
    result_specific_table.objects.filter(time=nid).delete()
    result_notes_table.objects.filter(time=nid).delete()
    return redirect("/search/history/")

import os
import glob

def find_latest_log_file(log_directory):
    # 构建日志文件的搜索模式
    log_pattern = os.path.join(log_directory, '*.log')
    # 使用 glob 获取所有匹配的文件列表
    log_files = glob.glob(log_pattern)
    # 按修改时间排序并获取最新的文件
    latest_file = max(log_files, key=os.path.getmtime, default=None)
    return latest_file

def find_errors_in_file(file_path):
    # 读取文件并查找包含 "ERROR" 和’已完成xx设备巡检‘的行
    error_lines = []
    with open(file_path, 'r', encoding='gbk') as file:
        for line in file:
            if "ERROR" in line:
                error_lines.append(line.strip())  # 将符合条件的行添加到列表中
            if '已完成' in line:
                error_lines.append(line.strip())
    return error_lines[0:5]  # 返回包含所有 "ERROR" 行的列表

def search_history(request):
    if request.method=="POST":
        text = request.POST.get('text')
        queryset=result_overall_table.objects.filter(time__icontains=text).all() | result_overall_table.objects.filter(user_xnjian__icontains=text).all() | result_overall_table.objects.filter(jixian__icontains=text).all() | result_overall_table.objects.filter(result__icontains=text).all()
        page_object = Pagination(request, queryset)
        context = {
            'search_data': 1,
            'page_string': page_object.html(),
            'data_list': page_object.page_queryset
        }
        return render(request, "search_history.html", context)

    if request.method=="GET":
        data_dict ={}
        search_data =request.GET.get('q','')
        if search_data:
            data_dict['name__contains'] = search_data
        confirm_notes_obj=result_notes_table.objects.filter()
        queryset = result_overall_table.objects.filter(**data_dict).order_by('-time')
        page_object =Pagination(request,queryset)
        if result_overall_table.objects.filter(jixian=1).first():
            jixian = result_overall_table.objects.filter(jixian=1).first().time
        else:
            jixian = {'1': 1}
        log_directory = os.path.join( base_dir, 'app02', 'logfile' )# 替换为你的日志目录
        latest_log_file = find_latest_log_file(log_directory)
        if latest_log_file:
            log_note=find_errors_in_file(latest_log_file)
        else:
            log_note="没有找到日志文件。"
        context={
            'search_data':search_data,
            'page_string':page_object.html(),
            'data_list':page_object.page_queryset,
            'jixian': jixian,
            'log_note':log_note,
        }
        return render(request, "search_history.html", context)


def set_jixian(request):
    id1 = request.GET.get("nid")
    result_overall_table.objects.filter(jixian=True).update(jixian=False)
    result_overall_table.objects.filter(id=id1).update(jixian=True)
    return redirect("/search/history/")

def notes(con, time, device,notes):
    notes_new = '<div class="alert alert alert-info" role="alert"><a href="/display/history/?nid=' + con + '&nid3=' + str(time) + '&nid4=' + device + '"class="alert-link"">'+device+':      '+notes+'</a></div>'
    return notes_new

def notes_yc(con, time, device,notes):
    notes_new = '<div class="alert alert-danger" role="alert"><a href="/display/history/?nid=' + con + '&nid3=' + str(time) + '&nid4=' + device + '" class="alert-link" ">'+device+':      '+notes+'</a></div>'
    return notes_new


def info_history(request):
    time = request.GET.get("nid")
    row_obj13=result_notes_table.objects.filter(time=time).all().order_by('device')
    tag=''
    if row_obj13:
        for i in row_obj13:
            if i.confirm:
                i.notes=mark_safe(notes(i.command,i.time,i.device,i.notes))
            else:
                i.notes = mark_safe(notes_yc(i.command,i.time,i.device,i.notes))
    else:
        tag='本次巡检无异常'
    return render(request, "info_history.html", {"row_obj13": row_obj13,'tag':tag,'time':time})

def confirm_all(request):
    time = request.GET.get("nid1")
    print(time)
    result_notes_table.objects.filter(time=time).update(confirm=True)
    if result_notes_table.objects.filter(time=time,confirm=False).all():
        pass
    else:
        result_overall_table.objects.filter(time=time).update(result='正常')
    row_obj13 = result_notes_table.objects.filter(time=time).all().order_by('device')
    tag = ''
    if row_obj13:
        for i in row_obj13:
            if i.confirm:
                i.notes = mark_safe(notes(i.command, i.time, i.device, i.notes))
            else:
                i.notes = mark_safe(notes_yc(i.command, i.time, i.device, i.notes))
    return render(request, "info_history.html",
                  { "row_obj13": row_obj13,'time':time})


def display_history(request):#显示命令详情
    con=request.GET.get("nid")
    time = request.GET.get("nid3")
    device = request.GET.get("nid4")
    if result_specific_table.objects.filter(time=time,device = device ,command=con).first():
        data = result_specific_table.objects.filter(time=time,device = device ,command=con).first().result
    else:
        data='无'

    if result_notes_table.objects.filter(time =time ,device =device,command=con).first():
        notes = result_notes_table.objects.filter(time =time ,device =device,command=con).first().notes
    else:
        notes=''
    return render(request, "info_history.html", {"s1": data, "time": time, "device": device, "con": con,'notes':notes})



def text_compare(request):
    # 假设有两个文件内容
    con = request.GET.get("nid")
    time = request.GET.get("nid3")
    device = request.GET.get("nid4")
    if result_specific_table.objects.filter(time=time,device = device ,command=con).first():
        data = result_specific_table.objects.filter(time=time,device = device ,command=con).first().result
        if result_overall_table.objects.filter(jixian=True).first():
            jixian_time = result_overall_table.objects.filter(jixian=True).first().time
            jixian_obj = result_specific_table.objects.filter(time=jixian_time, device=device, command=con).first()
            if jixian_obj:
                jixian = jixian_obj.result
                diff_html = difflib.HtmlDiff().make_file(data.splitlines(), jixian.splitlines())
                return render(request, "text_compare.html",
                              {"s1": data, "time": time, "device": device, "con": con, 'diff_html': diff_html})
            else:
                messages.error(request, '基线为空，操作失败！')
                return render(request, "text_compare.html", {"time": time, "device": device, "con": con})
        else:
            messages.error(request, '基线为空，操作失败！')
            return render(request, "text_compare.html", {"time": time, "device": device, "con": con})
    else:
        messages.error(request, '配置为空，操作失败！')
        return render(request, "text_compare.html", {"time": time, "device": device, "con": con})


def info_edit(request,nid):
    if request.method=="GET":
        row_obj = device_table.objects.filter(id=nid).first()
        print(nid)
        dict =json.loads(row_obj.expand)
        port_up=dict['port_up']
        lldp_nei=dict['lldp_nei']
        ospf_nei=dict['ospf_nei']
        pim_nei=dict['pim_nei']
        zb=dict['zb']
        hw_patch=dict['hw_patch']
        return render(request,"info_edit.html",{"row_obj":row_obj,'port_up':port_up,'lldp_nei':lldp_nei,'ospf_nei':ospf_nei,'pim_nei':pim_nei,'zb':zb,'hw_patch':hw_patch})
    if request.method=="POST":
        device = request.POST.get('device')
        ip = request.POST.get('ip')
        group_name = request.POST.get('group_name')
        device_type = request.POST.get('device_type')
        user = request.POST.get('user')
        password = request.POST.get('password')
        device_type = request.POST.get('device_type')
        port_up = request.POST.get('port_up')
        lldp_nei = request.POST.get('lldp_nei')
        ospf_nei = request.POST.get('ospf_nei')
        pim_nei = request.POST.get('pim_nei')
        zb = request.POST.get('zb')
        hw_patch = request.POST.get('hw_patch')
        dict = {'port_up': port_up, 'lldp_nei': lldp_nei, 'ospf_nei': ospf_nei, 'pim_nei': pim_nei, 'zb': zb,
                'hw_patch': hw_patch}
        dict1 = json.dumps(dict)
        device_table.objects.filter(id=nid).update(device=device, ip=ip, group_name=group_name, device_type=device_type,user=user, password=password,
                                 expand=dict1)
        return redirect("/info/list/")

def confirm_notes(request):
    time = request.GET.get("nid1")
    device = request.GET.get("nid2")
    con = request.GET.get("nid3")
    result_notes_table.objects.filter(time=time,device=device,command=con).update(confirm=True)
    if result_notes_table.objects.filter(time=time,confirm=False).all():
        pass
    else:
        result_overall_table.objects.filter(time=time).update(result='正常')
        print(1)
    row_obj13 = result_notes_table.objects.filter(time=time).all()
    for i in row_obj13:
        if i.confirm:
            i.notes = mark_safe(notes(i.command, i.time, i.device, i.notes))
        else:
            i.notes = mark_safe(notes_yc(i.command, i.time, i.device, i.notes))
    return render(request, "info_history.html",
                  { "row_obj13": row_obj13})



def peizhiguanli_result(request):
    con=request.GET.get("nid")
    time = request.GET.get("nid3")
    device = request.GET.get("nid4")
    if result_specific_table.objects.filter(time=time, device=device, command=con).first():
        data = result_specific_table.objects.filter(time=time, device=device, command=con).first().result
    else:
        data = '无'

    if result_notes_table.objects.filter(time=time, device=device, command=con).first():
        notes = result_notes_table.objects.filter(time=time, device=device, command=con).first().notes
    else:
        notes = ''
    return render(request, "peizhiguanli_device.html",
                  {"s1": data, "time": time, "device": device, "con": con, 'notes': notes})

def peizhiguanli_device(request):
    time=request.GET.get("nid")
    # occ = result_specific_table.objects.filter(time=time).all()
    unique_devices = result_specific_table.objects.filter(time=time).values('device').distinct()
    highlighted_names = {
        note.device: True for note in result_notes_table.objects.filter(time=time,confirm=False).all()
    }

    # 将设备列表和需要高亮的名称字典传递给模板
    return render(request, 'peizhiguanli_device.html', {
        'time': time,
        # 'occ': occ,
        'unique_devices': unique_devices,
        'highlighted_names': highlighted_names
    })



def peizhiguanli_con(request):
    time=request.GET.get("nid")
    name=request.GET.get("nid1")
    occ = device_table.objects.filter(device=name).first().group_name
    group_id=group_table.objects.filter(group_name=occ).first().id
    func_obj= function_group_relationship_table.objects.filter(group_id=group_id).all()
    ddata=[]
    highlighted_names = {
        note.command: True for note in result_notes_table.objects.filter(time=time, confirm=False,device=name).all()
    }
    for func in func_obj:
        command=function_table.objects.filter(func=func.func).first().command
        print(command)
        ddata.append(command)
    return render(request, 'peizhiguanli_device.html', {
        'time': time,
        'device': name,
        'occ1': ddata,
        'highlighted_names': highlighted_names
    })
    # return render(request, 'peizhiguanli_device.html',{'time':time,'device':name,'occ1':ddata})
