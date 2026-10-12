import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import ensure_csrf_cookie


@require_GET
def home(request):
    return JsonResponse({
        "message": "Treasury Pulse API is running",
        "health": "/health",
        "docs": "/api/docs",
    })


@require_GET
def health(request):
    return JsonResponse({
        "status": "ok",
        "service": "treasury-pulse-api",
    })

@csrf_protect
@require_POST
def login_view(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"error": {"code": "INVALID_JSON", "message": "Invalid JSON body."}},
            status=400,
        )

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse(
            {"error": {"code": "INVALID_CREDENTIALS", "message": "Username and password are required."}},
            status=400,
        )

    user = authenticate(
        request,
        username=username,
        password=password,
    )

    if user is None:
        return JsonResponse(
            {"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid username or password."}},
            status=401,
        )

    login(request, user)

    profile = getattr(user, "profile", None)

    return JsonResponse({
        "message": "Login successful.",
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.get_full_name() or user.username,
            "role": profile.role if profile else None,
        },
    })


@csrf_protect
@require_POST
def logout_view(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "NOT_AUTHENTICATED", "message": "Please log in first."}},
            status=401,
        )

    logout(request)
    return JsonResponse({"message": "Logout successful."})

@require_GET
def me_view(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": {"code": "NOT_AUTHENTICATED", "message": "Please log in first."}},
            status=401,
        )

    profile = getattr(request.user, "profile", None)

    return JsonResponse({
        "id": request.user.id,
        "username": request.user.username,
        "name": request.user.get_full_name() or request.user.username,
        "role": profile.role if profile else None,
    })

@ensure_csrf_cookie
@require_GET
def csrf_view(request):
    return JsonResponse({"message": "CSRF cookie set."})