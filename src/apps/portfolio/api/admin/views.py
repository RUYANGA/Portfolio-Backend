"""Dashboard endpoints: overview, profile, CRUD + reorder for every content type, inbox."""

from django.db import transaction
from rest_framework import exceptions, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.portfolio.models import (
    Certification,
    ContactMessage,
    ContactSubject,
    Education,
    Experience,
    Lab,
    Profile,
    Project,
    SkillGroup,
    SocialLink,
)

from .auth import AdminAPIView, ExpiringTokenAuthentication
from .serializers import (
    CertificationAdminSerializer,
    ContactMessageAdminSerializer,
    ContactSubjectAdminSerializer,
    EducationAdminSerializer,
    ExperienceAdminSerializer,
    LabAdminSerializer,
    ProfileAdminSerializer,
    ProjectAdminSerializer,
    SkillGroupAdminSerializer,
    SocialLinkAdminSerializer,
)


class OverviewView(AdminAPIView):
    def get(self, request):
        profile = Profile.objects.first()
        return Response(
            {
                "counts": {
                    "projects": Project.objects.count(),
                    "featured_projects": Project.objects.filter(featured=True).count(),
                    "experiences": Experience.objects.count(),
                    "labs": Lab.objects.count(),
                    "skill_groups": SkillGroup.objects.count(),
                    "education": Education.objects.count(),
                    "certifications": Certification.objects.count(),
                    "messages": ContactMessage.objects.count(),
                    "unread_messages": ContactMessage.objects.filter(is_read=False).count(),
                },
                "profile": {
                    "name": profile.name if profile else "",
                    "available_for_work": profile.available_for_work if profile else False,
                    "updated_at": profile.updated_at if profile else None,
                    "has_cv": bool(profile and profile.cv_file),
                    "has_photo": bool(profile and profile.photo),
                },
                "recent_messages": ContactMessageAdminSerializer(ContactMessage.objects.all()[:5], many=True).data,
            }
        )


class AdminViewSet(viewsets.ModelViewSet):
    authentication_classes = [ExpiringTokenAuthentication]
    permission_classes = [IsAdminUser]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def perform_create(self, serializer):
        # New records go to the end of the list unless an order is given.
        model = self.get_queryset().model
        if "order" in [f.name for f in model._meta.fields] and "order" not in serializer.validated_data:
            last = model.objects.order_by("-order").values_list("order", flat=True).first()
            serializer.save(order=(last or 0) + 1)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        for field in instance._meta.get_fields():
            if getattr(field, "upload_to", None) is not None:
                file = getattr(instance, field.name)
                if file:
                    file.delete(save=False)
        instance.delete()

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """Body: {"ids": [3, 1, 2]}. Sets each record's order to its position."""
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response({"ids": ["Send a list of record ids."]}, status=400)
        model = self.get_queryset().model
        with transaction.atomic():
            for position, pk in enumerate(ids):
                model.objects.filter(pk=pk).update(order=position)
        return Response(self.get_serializer(self.get_queryset(), many=True).data)


class SocialLinkAdminViewSet(AdminViewSet):
    queryset = SocialLink.objects.all()
    serializer_class = SocialLinkAdminSerializer

    def perform_create(self, serializer):
        profile = Profile.objects.first()
        if profile is None:
            raise exceptions.ValidationError({"detail": "Create the profile first."})
        last = SocialLink.objects.order_by("-order").values_list("order", flat=True).first()
        serializer.save(profile=profile, order=serializer.validated_data.get("order", (last or 0) + 1))


class SkillGroupAdminViewSet(AdminViewSet):
    queryset = SkillGroup.objects.all()
    serializer_class = SkillGroupAdminSerializer


class ExperienceAdminViewSet(AdminViewSet):
    queryset = Experience.objects.all()
    serializer_class = ExperienceAdminSerializer


class ProjectAdminViewSet(AdminViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectAdminSerializer


class LabAdminViewSet(AdminViewSet):
    queryset = Lab.objects.all()
    serializer_class = LabAdminSerializer


class EducationAdminViewSet(AdminViewSet):
    queryset = Education.objects.all()
    serializer_class = EducationAdminSerializer


class CertificationAdminViewSet(AdminViewSet):
    queryset = Certification.objects.all()
    serializer_class = CertificationAdminSerializer


class ContactSubjectAdminViewSet(AdminViewSet):
    queryset = ContactSubject.objects.all()
    serializer_class = ContactSubjectAdminSerializer


class ContactMessageAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = [ExpiringTokenAuthentication]
    permission_classes = [IsAdminUser]
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageAdminSerializer
    pagination_class = None

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = ContactMessage.objects.filter(is_read=False).update(is_read=True)
        return Response({"updated": updated})


class ProfileAdminView(AdminAPIView):
    """The single profile record: GET to read, PATCH to change (JSON or multipart)."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        profile = Profile.objects.first()
        if profile is None:
            raise exceptions.NotFound("No profile yet. Run the seed or create one.")
        return profile

    def get(self, request):
        return Response(ProfileAdminSerializer(self.get_object(), context={"request": request}).data)

    def patch(self, request):
        serializer = ProfileAdminSerializer(
            self.get_object(), data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
