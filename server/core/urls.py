from django.urls import path
from .views import health, home, login_view, logout_view, me_view
from .views import health, home, login_view, logout_view, me_view, csrf_view

urlpatterns = [
    path("", home, name="home"),
    path("health", health, name="health"),
    path("api/auth/login/", login_view, name="login"),
    path("api/auth/logout/", logout_view, name="logout"),
    path("api/auth/me/", me_view, name="me"),
    path("api/auth/csrf/", csrf_view, name="csrf"),
]