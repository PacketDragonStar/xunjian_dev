"""
URL configuration for xunjian_system1 project — 巡检引擎 v2 统一路由
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from app02 import views

urlpatterns = [
    # ── 登录/登出 ──
    path('login/',  views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Django admin ──
    path('django-admin/', admin.site.urls),

    # ── 首页 / 仪表盘 ──
    path('',                    views.dashboard,              name='new_index'),
    path('dashboard/',          views.dashboard,              name='dashboard'),

    # ── 巡检执行 ──
    path('new/xunjian/',        views.new_xunjian_page,       name='new_xunjian_page'),
    path('new/xunjian/run/',    views.new_run_xunjian,        name='new_run_xunjian'),

    # ── 任务中心 ──
    path('task/center/',        views.task_center,            name='task_center'),
    path('task/<int:task_id>/',           views.task_detail,       name='task_detail'),
    path('task/<int:task_id>/detail/',    views.task_detail_json,  name='task_detail_json'),
    path('task/<int:task_id>/resume/',    views.task_resume,       name='task_resume'),

    # ── 历史记录 ──
    path('new/history/',             views.new_search_history,         name='new_search_history'),
    path('new/history/detail/',      views.new_history_detail,         name='new_history_detail'),
    path('new/history/delete/',      views.new_history_delete,         name='new_history_delete'),
    path('new/history/browse/',      views.xunjian_history_browse,     name='xunjian_history_browse'),
    path('new/history/raw_output/',  views.xunjian_history_raw_output, name='xunjian_history_raw_output'),
    path('new/baseline/set/',        views.new_set_baseline,           name='new_set_baseline'),

    # ── 异常确认 ──
    path('new/confirm/',        views.new_confirm_notes,      name='new_confirm_notes'),
    path('new/confirm/all/',    views.new_confirm_all,        name='new_confirm_all'),

    # ── 文本对比 ──
    path('new/compare/',        views.new_text_compare,       name='new_text_compare'),

    # ── 配置下载 ──
    path('new/config/download/', views.config_download,        name='config_download'),

    # ── 命令回显批量下载 ──
    path('new/cmd/download/',    views.cmd_download_page,     name='cmd_download_page'),
    path('new/cmd/download/zip/', views.cmd_download_zip,     name='cmd_download_zip'),
    path('new/cmd/download/commands/', views.cmd_download_commands, name='cmd_download_commands'),

    # ── 巡检项管理 ──
    path('new/checkitem/list/',   views.new_checkitem_list,   name='new_checkitem_list'),
    path('new/checkitem/add/',    views.new_checkitem_add,    name='new_checkitem_add'),
    path('new/checkitem/edit/',   views.new_checkitem_edit,   name='new_checkitem_edit'),
    path('new/checkitem/delete/', views.new_checkitem_delete, name='new_checkitem_delete'),
    path('new/checkitem/detail/', views.new_checkitem_detail, name='new_checkitem_detail'),

    # ── 设备分组管理 ──
    path('new/group/list/',     views.new_group_list,         name='new_group_list'),
    path('new/group/add/',      views.new_group_add,          name='new_group_add'),
    path('new/group/edit/',     views.new_group_edit,         name='new_group_edit'),
    path('new/group/delete/',   views.new_group_delete,       name='new_group_delete'),

    # ── 新设备管理 ──
    path('new/device/list/',    views.new_device_list,        name='new_device_list'),
    path('new/device/add/',     views.new_device_add,         name='new_device_add'),
    path('new/device/edit/',    views.new_device_edit,        name='new_device_edit'),
    path('new/device/delete/',  views.new_device_delete,      name='new_device_delete'),
    path('new/device/detail/',  views.new_device_detail,      name='new_device_detail'),
    path('new/device/capability/', views.new_device_capability, name='new_device_capability'),

    # ── 检查集管理 ──
    path('new/checkset/list/',  views.new_checkset_list,      name='new_checkset_list'),
    path('new/checkset/add/',   views.new_checkset_add,       name='new_checkset_add'),
    path('new/checkset/edit/',  views.new_checkset_edit,      name='new_checkset_edit'),
    path('new/checkset/delete/',views.new_checkset_delete,    name='new_checkset_delete'),
    path('new/checkset/detail/',views.new_checkset_detail,    name='new_checkset_detail'),

    # ── Checker 微调工具 ──
    path('new/tools/test_checker/',     views.test_checker_page, name='test_checker_page'),
    path('new/tools/test_checker/run/', views.test_checker_run,  name='test_checker_run'),
    path('new/tools/checker_script/source/',   views.checker_script_source,   name='checker_script_source'),
    path('new/tools/checker_script/save/',     views.checker_script_save,     name='checker_script_save'),
    path('new/tools/checker_script/rollback/', views.checker_script_rollback, name='checker_script_rollback'),


    # ── 验收报告 ──
    path('new/report/acceptance/', views.acceptance_report,   name='acceptance_report'),

    # ── 整体巡检报告（项目设备整体态势）──
    path('new/report/overview/',        views.fleet_report,        name='fleet_report'),
    path('new/report/overview/export/', views.fleet_report_export, name='fleet_report_export'),

    # ── CMDB 台账查询 ──
    path('cmdb/device/',    views.cmdb_device_list,    name='cmdb_device_list'),
    path('cmdb/device/detail/', views.cmdb_device_detail, name='cmdb_device_detail'),
    path('cmdb/interface/', views.cmdb_interface_list, name='cmdb_interface_list'),
    path('cmdb/link/',      views.cmdb_link_list,      name='cmdb_link_list'),
    path('cmdb/ip/',        views.cmdb_ip_list,        name='cmdb_ip_list'),
    path('new/report/acceptance/export/', views.acceptance_report_export, name='acceptance_report_export'),

    # ── 阶段 C：设备发现 + 配置合规 ──
    path('new/stagecd/',        views.stage_cd_page,  name='stage_cd_page'),
    path('new/stagecd/run/',    views.stage_cd_run,   name='stage_cd_run'),

    # ── 阶段 D：趋势图 ──
    path('new/trend/',          views.trend_page,    name='trend_page'),

    # ── 静态文件服务 ──
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
