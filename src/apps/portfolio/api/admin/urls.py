"""Routes under /api/admin/."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import auth, resume, views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("social-links", views.SocialLinkAdminViewSet, basename="admin-social-links")
router.register("skill-groups", views.SkillGroupAdminViewSet, basename="admin-skill-groups")
router.register("experiences", views.ExperienceAdminViewSet, basename="admin-experiences")
router.register("projects", views.ProjectAdminViewSet, basename="admin-projects")
router.register("labs", views.LabAdminViewSet, basename="admin-labs")
router.register("education", views.EducationAdminViewSet, basename="admin-education")
router.register("certifications", views.CertificationAdminViewSet, basename="admin-certifications")
router.register("contact-subjects", views.ContactSubjectAdminViewSet, basename="admin-contact-subjects")
router.register("messages", views.ContactMessageAdminViewSet, basename="admin-messages")

urlpatterns = [
    path("auth/login/", auth.LoginView.as_view(), name="admin-login"),
    path("auth/logout/", auth.LogoutView.as_view(), name="admin-logout"),
    path("auth/me/", auth.MeView.as_view(), name="admin-me"),
    path("auth/password/", auth.PasswordView.as_view(), name="admin-password"),
    path("overview/", views.OverviewView.as_view(), name="admin-overview"),
    path("profile/", views.ProfileAdminView.as_view(), name="admin-profile"),
    path("resume/", resume.ResumeView.as_view(), name="admin-resume"),
    path("resume/preview/", resume.ResumePreviewView.as_view(), name="admin-resume-preview"),
    path("resume/publish/", resume.ResumePublishView.as_view(), name="admin-resume-publish"),
    path("resume/import/", resume.ResumeImportView.as_view(), name="admin-resume-import"),
    path("resume/versions/<int:number>/restore/", resume.ResumeRestoreView.as_view(), name="admin-resume-restore"),
    path("", include(router.urls)),
]
