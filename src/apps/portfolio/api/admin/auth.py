"""
Dashboard authentication: staff-only token sign-in with expiry.

POST /api/admin/auth/login/ returns a token for a staff user. Tokens expire after
settings.ADMIN_TOKEN_TTL; every other admin endpoint requires `Authorization: Token <key>`.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import exceptions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class ExpiringTokenAuthentication(TokenAuthentication):
    """Token auth where tokens stop working after ADMIN_TOKEN_TTL."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created < timezone.now() - timedelta(seconds=settings.ADMIN_TOKEN_TTL):
            token.delete()
            raise exceptions.AuthenticationFailed("Session expired. Sign in again.")
        if not user.is_staff:
            raise exceptions.AuthenticationFailed("This account has no admin access.")
        return user, token


class AdminAPIView(APIView):
    authentication_classes = [ExpiringTokenAuthentication]
    permission_classes = [IsAdminUser]


def user_payload(user):
    return {"username": user.get_username(), "email": user.email, "name": user.get_full_name() or user.get_username()}


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admin_login"

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            return Response({"detail": "Incorrect username or password."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.is_staff:
            return Response({"detail": "This account has no admin access."}, status=status.HTTP_403_FORBIDDEN)
        # A fresh token on every sign-in, so expiry counts from now.
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response({"token": token.key, "expires_in": settings.ADMIN_TOKEN_TTL, "user": user_payload(user)})


class LogoutView(AdminAPIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(AdminAPIView):
    def get(self, request):
        return Response(user_payload(request.user))


class PasswordView(AdminAPIView):
    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        if not request.user.check_password(current):
            return Response({"current_password": ["Current password is incorrect."]}, status=400)
        if len(new) < 10:
            return Response({"new_password": ["Use at least 10 characters."]}, status=400)
        request.user.set_password(new)
        request.user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
