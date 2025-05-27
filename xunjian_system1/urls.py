"""
URL configuration for xunjian_system1 project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from app02 import views
from django.contrib import admin
from django.urls import path, include
from django.urls import path, re_path
from django.conf.urls.static import serve
from django.conf import settings
from app02.views_01 import depart, admin, account, log_backup, device, config_backup, func, fbounc, host_xunjian,crc_query

urlpatterns = [
    path('', account.login),
    # path('device/add/', views.device_add),
    path('history/delete/', views.history_delete),
    # path('func/delete/', views.func_delete),
    path('group/add/', views.group_add),
    # path('func/add/', views.func_add),
    path('bound/funcgroup/', views.bound_funcgroup),
    path('boundfg/delete/', views.boundfg_delete),
    path('info/list/', views.info_list),
    path('info/xunjian/', views.info_xunjian),
    path('info/xunjiantest/', views.info_xunjiantest, name='xunjiantest'),  # test
    path('grappelli/', include('grappelli.urls')),  # Grappelli URLS
    path('search/history/', views.search_history),
    path('set/jixian/', views.set_jixian),
    path('info/history/', views.info_history),
    path('display/history/', views.display_history),
    path('text/compare/', views.text_compare),
    path('info/<int:nid>/edit/', views.info_edit),
    path('confirm/notes/', views.confirm_notes),
    path('peizhiguanli/device/', views.peizhiguanli_device),
    path('peizhiguanli/con/', views.peizhiguanli_con),
    path('peizhiguanli/result/', views.peizhiguanli_result),
    path('test/add/', views.test_add),
    path('boundfunc/edit/', views.boundfunc_edit),

    re_path('media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),

    # 部门
    path('depart/list/', depart.depart_list),
    path('depart/add/', depart.depart_add),
    path('depart/delete/', depart.depart_delete),
    path('depart/edit/<int:nid>/', depart.depart_edit),
    path('depart/multi/', depart.depart_multi),

    # 管理员的管理
    path('admin/list/', admin.admin_list),
    path('admin/add/', admin.admin_add),
    path('admin/<int:nid>/edit/', admin.admin_edit),
    # path('admin/<int:nid>/password/', admin.admin_password),
    # path('admin/<int:nid>/delete/', admin.admin_delete),
    path('admin/<int:nid>/reset/', admin.admin_reset),

    # 登录
    path('login/', account.login),
    path('logout/', account.logout),
    # path('image/code/', account.image_code),

    # 函数组管理
    path('fbounc/list/', fbounc.fbounc_list),
    path('fbounc/multi/', fbounc.fbounc_multi),
    path('fbounc/add/', fbounc.fbounc_add),
    path('fbounc/delete/', fbounc.fbounc_delete),

    # 函数管理
    path('func/list/', func.func_list),
    path('func/multi/', func.func_multi),
    path('func/add/', func.func_add),
    path('func/delete/', func.func_delete),

    # 设备管理
    path('device/list/', device.device_list),
    path('device/multi/', device.device_multi),
    path('device/add/', device.device_add),
    path('device/delete/', device.device_delete),
    path('device/detail/', device.device_detail),
    path('device/edit/', device.device_edit),

    # 配置备份
    path('configBackup/list/', config_backup.conf_backup_list, name='conf_backup_list'),
    path('configBackup/add/', config_backup.conf_backup_add, name='conf_backup_add'),
    path('configBackup/download/<int:uid>/', config_backup.conf_backup_download, name='conf_backup_download'),
    path('configBackup/view/<int:uid>/', config_backup.conf_backup_view, name='conf_backup_view'),
    path('configBackup/diff/<int:uid>/', config_backup.diff_view, name='diff_view'),
    path('configBackup/select/', config_backup.select_device, name='select_device'),
    path('configBackup/note/', config_backup.save_notes, name='save-notes'),

    # 新版-联动巡检-配置备份
    path('logBackup/list/', log_backup.log_backup_list, name='log_backup_list'),
    path('logBackup/note/', log_backup.save_notes, name='log_backup_notes'),
    path('logBackup/download/<int:uid>/', log_backup.log_backup_download, name='log_backup_download'),
    path('logBackup/download_backups/', log_backup.download_backups, name='download_backups'),
    path('change/password/', device.change_password),

    # 主机巡检
    path('host/list/', host_xunjian.host_list),
    path('host/detail/', host_xunjian.host_detail),
    path('confirm/all/', views.confirm_all),
    path('data/crc/', crc_query.crc_query),

]
