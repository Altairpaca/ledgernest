"""全局错误页处理器。"""
from django.shortcuts import render


def handler403(request, exception=None):
    return render(request, "core/403.html", status=403)


def handler404(request, exception=None):
    return render(request, "core/404.html", status=404)


def handler500(request):
    return render(request, "core/500.html", status=500)
