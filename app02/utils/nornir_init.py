from nornir import InitNornir


def nornir_init(queryset, num_workers=100, ):
    """
    通过django Device数据对象集合queryset加载Nornir对象
    Args:
        queryset: Device的查询数据结合，QuerySet类型或者
        num_workers: 并发数，默认100 可以根据事情情况调整

    Returns:
        Nornir对象
    """

    data = []
    for device in queryset:
        device_dict = {
            'name': device.device,
            'hostname': device.ip,
            'platform': device.device_type,
            'username': device.user,
            'password': device.password,
            'port': 22,
        }
        data.append(device_dict)

    runner = {
        "plugin": "threaded",
        "options": {
            "num_workers": num_workers,
        },
    }
    inventory = {
        "plugin": "FlatDataInventory",
        "options": {
            "data": data,
        },
    }
    nr_init = InitNornir(runner=runner, inventory=inventory)
    return nr_init


