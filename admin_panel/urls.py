from django.urls import path

from admin_panel.views import amanat, auth, dashboard, finance, kyc, map, orders, search, settings, tariffs, users

app_name = "admin_panel"

urlpatterns = [
    path("login/", auth.panel_login, name="login"),
    path("logout/", auth.panel_logout, name="logout"),
    path("", dashboard.dashboard, name="dashboard"),
    path("orders/", orders.order_list, name="orders"),
    path("orders/<int:pk>/", orders.order_detail, name="order_detail"),
    path("orders/<int:pk>/quick/", orders.order_quick, name="order_quick"),
    path("orders/<int:pk>/cancel/", orders.order_cancel, name="order_cancel"),
    path("orders/<int:pk>/recalculate/", orders.order_recalculate, name="order_recalculate"),
    path("users/", users.user_list, name="users"),
    path("users/<int:pk>/", users.user_detail, name="user_detail"),
    path("couriers/", users.courier_list, name="couriers"),
    path("couriers/<int:pk>/", users.courier_detail, name="courier_detail"),
    path("kyc/", kyc.kyc_list, name="kyc_list"),
    path("kyc/<int:pk>/", kyc.kyc_detail, name="kyc_detail"),
    path("kyc/<int:pk>/approve/", kyc.kyc_approve, name="kyc_approve"),
    path("kyc/<int:pk>/reject/", kyc.kyc_reject, name="kyc_reject"),
    path("map/", map.map_list, name="map_list"),
    path("map/<int:pk>/", map.map_editor, name="map_editor"),
    path("map/<int:pk>/save/", map.map_save, name="map_save"),
    path("map/<int:pk>/publish/", map.map_publish, name="map_publish"),
    path("tariffs/", tariffs.tariff_list, name="tariffs"),
    path("tariffs/global/save/", tariffs.global_tariff_save, name="global_tariff_save"),
    path("tariffs/district/new/", tariffs.district_tariff_save, name="district_tariff_create"),
    path("tariffs/district/<int:pk>/save/", tariffs.district_tariff_save, name="district_tariff_save"),
    path("tariffs/bazar/<int:pk>/save/", tariffs.bazar_tariff_save, name="bazar_tariff_save"),
    path("finance/", finance.finance, name="finance"),
    path("finance/payments/<uuid:pk>/", finance.payment_detail, name="payment_detail"),
    path("amanat/", amanat.amanat_list, name="amanat"),
    path("amanat/new/", amanat.amanat_create, name="amanat_create"),
    path("amanat/campaigns/<int:pk>/", amanat.amanat_detail, name="amanat_detail"),
    path("search/", search.global_search, name="search"),
    path("settings/", settings.settings_page, name="settings"),
]
