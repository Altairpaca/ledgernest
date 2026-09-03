from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    return mapping.get(key)


_ICON_PALETTE = [
    "bg-orange-100 text-orange-700 dark:bg-orange-900/60 dark:text-orange-300",
    "bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300",
    "bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300",
    "bg-purple-100 text-purple-700 dark:bg-purple-900/60 dark:text-purple-300",
    "bg-pink-100 text-pink-700 dark:bg-pink-900/60 dark:text-pink-300",
    "bg-teal-100 text-teal-700 dark:bg-teal-900/60 dark:text-teal-300",
    "bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300",
    "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300",
]


@register.filter
def icon_color(icon):
    """按图标字符哈希从固定色板取色，保证同一图标全局同色。"""
    icon = icon or "▣"
    code = sum(ord(c) for c in icon)
    return _ICON_PALETTE[code % len(_ICON_PALETTE)]
