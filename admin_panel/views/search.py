from django.db.models import Q
from django.http import JsonResponse

from apps.delivery.models import Bazar, Container, Passage, Shipment
from apps.users.models import User

from admin_panel.access import staff_required


@staff_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"groups": []})

    users = User.objects.filter(
        Q(first_name__icontains=query) | Q(phone_number__icontains=query),
        is_staff=False,
    )[:5]
    order_filter = (
        Q(title__icontains=query)
        | Q(client__phone_number__icontains=query)
        | Q(carrier__phone_number__icontains=query)
    )
    if query.lstrip("#").isdigit():
        order_filter |= Q(pk=int(query.lstrip("#")))
    orders = Shipment.objects.exclude(is_demo=True).filter(order_filter)[:5]
    bazars = Bazar.objects.filter(name__icontains=query)[:3]
    passages = Passage.objects.select_related("bazar").filter(
        Q(number__icontains=query) | Q(bazar__name__icontains=query)
    )[:3]
    containers = Container.objects.select_related("passage__bazar").filter(
        Q(number__icontains=query) | Q(title__icontains=query)
    )[:4]

    groups = [
        {
            "label": "Пользователи",
            "items": [
                {
                    "title": user.first_name or user.phone_number,
                    "meta": user.phone_number,
                    "url": f"/panel/users/{user.pk}/",
                }
                for user in users
            ],
        },
        {
            "label": "Заказы",
            "items": [
                {
                    "title": f"Заказ #{order.public_code}",
                    "meta": order.title,
                    "url": f"/panel/orders/{order.pk}/",
                }
                for order in orders
            ],
        },
        {
            "label": "Карта",
            "items": [
                *[
                    {"title": bazar.name, "meta": "Базар", "url": f"/panel/map/{bazar.pk}/"}
                    for bazar in bazars
                ],
                *[
                    {
                        "title": passage.number,
                        "meta": f"Проход · {passage.bazar.name}",
                        "url": f"/panel/map/{passage.bazar_id}/",
                    }
                    for passage in passages
                ],
                *[
                    {
                        "title": container.number,
                        "meta": f"Контейнер · {container.passage.bazar.name}",
                        "url": f"/panel/map/{container.passage.bazar_id}/",
                    }
                    for container in containers
                ],
            ],
        },
    ]
    return JsonResponse({"groups": [group for group in groups if group["items"]]})
