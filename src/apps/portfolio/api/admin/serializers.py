"""
Serializers for the dashboard. Writes accept JSON or multipart (for uploads): send an empty
value for a file field to remove the file, omit it to keep the current one.
"""

import json

from rest_framework import serializers

from apps.portfolio.media import absolute
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
    split_commas,
    split_lines,
)

# ---------- Field helpers ----------


class JoinedListField(serializers.Field):
    """A list in the API, stored as one comma- or newline-separated text column."""

    def __init__(self, separator=", ", **kwargs):
        self.separator = separator
        super().__init__(**kwargs)

    def to_representation(self, value):
        return split_lines(value) if self.separator == "\n" else split_commas(value)

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)  # multipart forms send lists as JSON text
            except ValueError:
                data = split_lines(data) if self.separator == "\n" else split_commas(data)
        if not isinstance(data, list):
            raise serializers.ValidationError("Expected a list.")
        items = [str(item).strip() for item in data if str(item).strip()]
        return self.separator.join(items)


class FileCleanupMixin(serializers.ModelSerializer):
    """Delete the old file from storage when a file field is replaced or cleared."""

    def update(self, instance, validated_data):
        for field in instance._meta.get_fields():
            if getattr(field, "upload_to", None) is None or field.name not in validated_data:
                continue
            old = getattr(instance, field.name)
            if old and old != validated_data[field.name]:
                old.delete(save=False)
        return super().update(instance, validated_data)


class PublicFileField(serializers.FileField):
    """File field whose URL respects PUBLIC_URL, like the public API."""

    def to_representation(self, value):
        return absolute(self.context.get("request"), value)


class PublicImageField(serializers.ImageField):
    def to_representation(self, value):
        return absolute(self.context.get("request"), value)


def file_field(**kwargs):
    return PublicFileField(required=False, allow_null=True, **kwargs)


def image_field():
    return PublicImageField(required=False, allow_null=True)


# ---------- Serializers ----------


class SocialLinkAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLink
        fields = ["id", "label", "url", "order"]


class ProfileAdminSerializer(FileCleanupMixin, serializers.ModelSerializer):
    photo = image_field()
    cv_file = file_field()

    class Meta:
        model = Profile
        exclude = ["id"]
        read_only_fields = ["updated_at"]


class SkillGroupAdminSerializer(serializers.ModelSerializer):
    skills = JoinedListField()

    class Meta:
        model = SkillGroup
        fields = ["id", "name", "skills", "order"]


class ExperienceAdminSerializer(serializers.ModelSerializer):
    highlights = JoinedListField(separator="\n", required=False)
    technologies = JoinedListField(required=False)

    class Meta:
        model = Experience
        fields = [
            "id",
            "role",
            "company",
            "location",
            "period",
            "is_current",
            "summary",
            "highlights",
            "technologies",
            "order",
        ]


class ProjectAdminSerializer(FileCleanupMixin, serializers.ModelSerializer):
    stack = JoinedListField(required=False)
    cover_image = image_field()

    class Meta:
        model = Project
        fields = [
            "id",
            "title",
            "slug",
            "tagline",
            "status",
            "featured",
            "url",
            "repo_url",
            "cover_image",
            "description",
            "problem",
            "approach",
            "stack",
            "order",
        ]


class LabAdminSerializer(FileCleanupMixin, serializers.ModelSerializer):
    highlights = JoinedListField(separator="\n", required=False)
    services = JoinedListField(required=False)
    diagram = image_field()

    class Meta:
        model = Lab
        fields = [
            "id",
            "title",
            "category",
            "provider",
            "completed",
            "repo_url",
            "diagram",
            "summary",
            "highlights",
            "services",
            "order",
        ]


class EducationAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = ["id", "degree", "institution", "period", "coursework", "order"]


class CertificationAdminSerializer(FileCleanupMixin, serializers.ModelSerializer):
    image = image_field()

    class Meta:
        model = Certification
        fields = ["id", "name", "issuer", "year", "credential_url", "image", "order"]


class ContactSubjectAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactSubject
        fields = ["id", "label", "is_active", "order"]


class ContactMessageAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["id", "name", "email", "subject", "message", "is_read", "created_at"]
        read_only_fields = ["name", "email", "subject", "message", "created_at"]
