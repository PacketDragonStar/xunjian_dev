"""
自定义的分页组件，以后如果想要使用这个分页组件，你需要做如下几件事：
在视图函数中：
    def pretty_list(request):
        # 1.根据自己的情况去筛选自己的数据
        queryset = models.PrettyNum.objects.all()
        # 2.实例化分页对象
        page_object = Pagination(request, queryset)
        context = {
            "queryset": page_object.page_queryset,  # 分完页的数据
            "page_string": page_object.html()       # 生成页码
        }
        return render(request, 'pretty_list.html', context)
在HTML页面中
    {% for obj in queryset %}
        {{obj.xx}}
    {% endfor %}

    <ul class="pagination">
        {{ page_string }}
    </ul>

"""

from django.utils.safestring import mark_safe


class Pagination(object):

    def __init__(self, request, queryset, page_size=10, page_size_options=(10, 20, 50, 100), page_param="page", plus=2):
        """
        :param request: 请求的对象
        :param queryset: 符合条件的数据（根据这个数据给他进行分页处理）
        :param page_size: 每页显示多少条数据
        :param page_param: 在URL中传递的获取分页的参数，例如：/etty/list/?page=12
        :param plus: 显示当前页的 前或后几页（页码）
        :param page_size_options: 每页显示记录数的选项列表
        """

        import copy
        query_dict = copy.deepcopy(request.GET)
        query_dict._mutable = True
        self.query_dict = query_dict

        # 计算总页数，并修正page_size
        total_count = queryset.count()
        self.total_page_count = (total_count + page_size - 1) // page_size  # 更精确的总页数计算方式

        # 处理page冲突，采用最后一个page_size的值
        self.page_size = int(request.GET.get('page_size', page_size))
        self.page_size = self.page_size if self.page_size in page_size_options else page_size  # 确保在允许的选项内

        # 确保请求的页码有效，否则重定向到第一页
        self.page = request.GET.get(page_param, "1")
        self.page = 1 if not self.page.isdecimal() or int(self.page) > self.total_page_count else int(self.page)

        page_param_with_size = f"{page_param}_size"
        self.query_dict.setlist(page_param_with_size, [self.page_size])

        self.page_param = page_param
        page = request.GET.get(page_param, "1")

        if page.isdecimal():
            page = int(page)
        else:
            page = 1

        self.page = page
        self.start = (page - 1) * self.page_size
        self.end = page * self.page_size

        self.page_queryset = queryset[self.start:self.end]

        # total_count = queryset.count()
        self.total_page_count, _ = divmod(total_count, self.page_size)
        if total_count % self.page_size:
            self.total_page_count += 1
        self.plus = plus
        self.page_size_options = page_size_options

    def html(self):
        # 计算出，显示当前页的前2页、后2页
        if self.total_page_count <= 2 * self.plus + 1:
            # 数据库中的数据比较少，都没有达到11页。
            start_page = 1
            end_page = self.total_page_count
        else:
            # 数据库中的数据比较多 > 11页。

            # 当前页<2时（小极值）
            if self.page <= self.plus:
                start_page = 1
                end_page = 2 * self.plus + 1
            else:
                # 当前页 > 2
                # 当前页+2 > 总页面
                if (self.page + self.plus) > self.total_page_count:
                    start_page = self.total_page_count - 2 * self.plus
                    end_page = self.total_page_count
                else:
                    start_page = self.page - self.plus
                    end_page = self.page + self.plus

        # 页码
        page_str_list = []

        self.query_dict.setlist(self.page_param, [1])
        page_str_list.append('<li><a href="?{}"> << </a></li>'.format(self.query_dict.urlencode()))

        # 上一页
        if self.page > 1:
            self.query_dict.setlist(self.page_param, [self.page - 1])
            prev = '<li><a href="?{}"> < </a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [1])
            prev = '<li><a href="?{}"> < </a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 页面
        for i in range(start_page, end_page + 1):
            self.query_dict.setlist(self.page_param, [i])
            if i == self.page:
                ele = '<li class="active"><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            else:
                ele = '<li><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            page_str_list.append(ele)

        # 下一页
        if self.page < self.total_page_count:
            self.query_dict.setlist(self.page_param, [self.page + 1])
            prev = '<li><a href="?{}"> > </a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [self.total_page_count])
            prev = '<li><a href="?{}"> > </a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)

        # 尾页
        self.query_dict.setlist(self.page_param, [self.total_page_count])
        page_str_list.append('<li><a href="?{}"> >> </a></li>'.format(self.query_dict.urlencode()))

        search_string = """
            <li>
                <form style="float: right;margin-left: -1px" method="get">
                    <input name="page"
                           style="position: relative;float:left;display: inline-block;width: 80px;border-radius: 0;"
                           type="text" class="form-control" placeholder="页码">
                    <button style="border-radius: 0" class="btn btn-default" type="submit">跳转</button>
                </form>
            </li>
            """
        page_str_list.append(search_string)

        # 添加每页显示数量的下拉菜单
        size_select = '<li class="dropdown">\n'
        size_select += '  <a href="#" class="dropdown-toggle" data-toggle="dropdown">每页显示 <span class="caret"></span></a>\n'
        size_select += '  <ul class="dropdown-menu dropdown-menu-up">\n'
        for size in self.page_size_options:
            # 移除旧的page_size参数，添加新的，并设置page为1
            updated_query_dict = self.query_dict.copy()
            updated_query_dict._mutable = True
            updated_query_dict.pop(self.page_param + '_size', None)  # 移除旧的page_size参数
            updated_query_dict.setlist(self.page_param + '_size', [size])  # 添加新的page_size
            updated_query_dict.setlist(self.page_param, [1])  # 重置页码为首页
            selected = 'selected' if size == self.page_size else ''

            size_link = f'<li><a href="?{updated_query_dict.urlencode()}" class="{selected}">{size}条/每页</a></li>\n'
            size_select += size_link
        size_select += '  </ul>\n'
        size_select += '</li>\n'
        # 添加到page_string_list中
        page_str_list.append(size_select)

        page_string = mark_safe("".join(page_str_list))
        return page_string
