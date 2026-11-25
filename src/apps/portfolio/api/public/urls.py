from django.urls import path

from .views import ContactView, HealthView, PortfolioView, ProfileView, ProjectDetailView

urlpatterns = [
    path("portfolio/", PortfolioView.as_view(), name="portfolio"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("projects/<slug:slug>/", ProjectDetailView.as_view(), name="project-detail"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("health/", HealthView.as_view(), name="health"),
]
