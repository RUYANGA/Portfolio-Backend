from django.urls import path

from .live import (
    CurrentExperienceView,
    RandomCertificationView,
    RandomLabView,
    RandomProjectView,
    RandomSkillGroupView,
    StatsView,
)
from .views import ContactView, HealthView, PortfolioView, ProfileView, ProjectDetailView

urlpatterns = [
    path("portfolio/", PortfolioView.as_view(), name="portfolio"),
    path("profile/", ProfileView.as_view(), name="profile"),
    # Live-panel endpoints; "projects/random/" must come before the project slug route.
    path("projects/random/", RandomProjectView.as_view(), name="project-random"),
    path("labs/random/", RandomLabView.as_view(), name="lab-random"),
    path("experience/current/", CurrentExperienceView.as_view(), name="experience-current"),
    path("skills/random/", RandomSkillGroupView.as_view(), name="skill-random"),
    path("certifications/random/", RandomCertificationView.as_view(), name="certification-random"),
    path("stats/", StatsView.as_view(), name="stats"),
    path("projects/<slug:slug>/", ProjectDetailView.as_view(), name="project-detail"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("health/", HealthView.as_view(), name="health"),
]
