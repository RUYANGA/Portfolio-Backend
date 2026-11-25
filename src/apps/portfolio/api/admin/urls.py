"""Routes under /api/admin/."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import auth, views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("social-links", views.SocialLinkAdminViewSet, basename="admin-social-links")
router.register("skill-groups", views.SkillGroupAdminViewSet, basename="admin-skill-groups")
router.register("experiences", views.ExperienceAdminViewSet, basename="admin-experiences")
router.register("projects", views.ProjectAdminViewSet, basename="admin-projects")
router.register("education", views.EducationAdminViewSet, basename="admin-education")
router.register("certifications", views.CertificationAdminViewSet, basename="admin-certifications")
router.register("messages", views.ContactMessageAdminViewSet, basename="admin-messages")

urlpatterns = [
    path("auth/login/", auth.LoginView.as_view(), name="admin-login"),
    path("auth/logout/", auth.LogoutView.as_view(), name="admin-logout"),
    path("auth/me/", auth.MeView.as_view(), name="admin-me"),
    path("auth/password/", auth.PasswordView.as_view(), name="admin-password"),
    path("overview/", views.OverviewView.as_view(), name="admin-overview"),
    path("profile/", views.ProfileAdminView.as_view(), name="admin-profile"),
    path("", include(router.urls)),
]
