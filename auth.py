from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import HttpResponse, redirect

from django.http import HttpResponseForbidden

class AuthMiddleware(MiddlewareMixin):

    def __init__(self, get_response):
        self.get_response = get_response
        # 允许的IP列表
        self.allowed_ips = ['192.168.1.125', '192.168.1.126']
    def process_request(self, request):
        # 0.排除那些不需要登录就能访问的页面
        #   request.path_info 获取当前用户请求的URL /login/
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        if ip  in self.allowed_ips:
            if request.path_info in ["/login/", "/image/code/"]:
                return
            # 1.读取当前访问的用户的session信息，如果能读到，说明已登陆过，就可以继续向后走。
            info_dict = request.session.get("info")
            if info_dict:
                return
            else:
                return redirect('/login/')
        else:
            return HttpResponseForbidden("You are not allowed to access this site.")
    #
    # def __call__(self, request):
    #     # 获取请求的IP地址
    #
    #
    #     # 检查IP是否在允许列表中
    #     if ip not in self.allowed_ips:
    #         return HttpResponseForbidden("You are not allowed to access this site.")
    #
    #     response = self.get_response(request)
    #     return response