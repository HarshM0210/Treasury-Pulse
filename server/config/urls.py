
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter
from users.views import AdminUserViewSet

admin_router = DefaultRouter()
admin_router.register(
    "admin/users",
    AdminUserViewSet,
    basename="admin-users",
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # Treasury API
    path("api/v1/", include("treasury.urls")),
    path("api-auth/", include("rest_framework.urls")),


    # Core routes (home and health)
    path("", include("core.urls")),

    # API schema and documentation
    path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="schema",
    ),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/v1/", include(admin_router.urls)),
]
