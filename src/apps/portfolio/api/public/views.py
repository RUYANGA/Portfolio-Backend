"""Public API: portfolio content, contact form, health check."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.portfolio.models import (
    Certification,
    ContactSubject,
    Education,
    Experience,
    Profile,
    Project,
    SkillGroup,
)

from .serializers import (
    CertificationSerializer,
    ContactMessageSerializer,
    EducationSerializer,
    ExperienceSerializer,
    ProfileSerializer,
    ProjectSerializer,
    SkillGroupSerializer,
)

logger = logging.getLogger(__name__)


class PortfolioView(APIView):
    """Everything the homepage needs, in one request."""

    def get(self, request):
        ctx = {"request": request}
        profile = Profile.objects.prefetch_related("socials").first()
        return Response(
            {
                "profile": ProfileSerializer(profile, context=ctx).data if profile else None,
                "skill_groups": SkillGroupSerializer(SkillGroup.objects.all(), many=True).data,
                "experiences": ExperienceSerializer(Experience.objects.all(), many=True).data,
                "projects": ProjectSerializer(Project.objects.all(), many=True, context=ctx).data,
                "education": EducationSerializer(Education.objects.all(), many=True).data,
                "certifications": CertificationSerializer(Certification.objects.all(), many=True, context=ctx).data,
                "contact_subjects": list(ContactSubject.objects.filter(is_active=True).values_list("label", flat=True)),
            }
        )


class ProfileView(APIView):
    """Small payload used by the live API panel in the hero."""

    def get(self, request):
        profile = get_object_or_404(Profile.objects.prefetch_related("socials"))
        data = ProfileSerializer(profile, context={"request": request}).data
        first_group = SkillGroup.objects.first()
        return Response(
            {
                "name": data["name"],
                "title": data["title"],
                "location": data["location"],
                "available_for_work": data["available_for_work"],
                "systems_in_production": Project.objects.filter(status=Project.Status.PRODUCTION).count(),
                "stack": first_group.skill_list[:6] if first_group else [],
            }
        )


class ProjectDetailView(APIView):
    def get(self, request, slug):
        project = get_object_or_404(Project, slug=slug)
        return Response(ProjectSerializer(project, context={"request": request}).data)


class ContactView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "contact"

    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save()

        notify = settings.CONTACT_NOTIFY_EMAIL or (Profile.objects.values_list("email", flat=True).first())
        if notify:
            try:
                send_mail(
                    subject=f"Portfolio message from {message.name}: {message.subject or 'New message'}",
                    message=f"From: {message.name} <{message.email}>\n\n{message.message}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[notify],
                )
            except Exception:  # The message is already saved; email is a bonus.
                logger.exception("Contact notification email failed")

        return Response({"detail": "Message sent."}, status=status.HTTP_201_CREATED)


class HealthView(APIView):
    """Liveness/readiness probe for Docker and uptime monitors: checks the database too."""

    def get(self, request):
        from django.db import connection

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:  # noqa: BLE001 - any DB failure means not ready
            return Response({"status": "error", "database": "unreachable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ok"})
