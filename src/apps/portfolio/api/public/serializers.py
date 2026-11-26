"""Serializers for the public, read-only API the site uses."""

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


class SocialLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLink
        fields = ["label", "url"]


class ProfileSerializer(serializers.ModelSerializer):
    socials = SocialLinkSerializer(many=True, read_only=True)
    photo = serializers.SerializerMethodField()
    cv_file = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "name",
            "title",
            "headline",
            "summary",
            "about",
            "location",
            "email",
            "secondary_email",
            "phone",
            "photo",
            "cv_file",
            "available_for_work",
            "years_experience",
            "socials",
            "availability_text",
            "about_heading",
            "experience_intro",
            "projects_intro",
            "skills_intro",
            "contact_heading",
            "contact_intro",
            "meta_description",
            "updated_at",
        ]

    def get_photo(self, obj):
        return absolute(self.context.get("request"), obj.photo)

    def get_cv_file(self, obj):
        return absolute(self.context.get("request"), obj.cv_file)


class SkillGroupSerializer(serializers.ModelSerializer):
    skills = serializers.SerializerMethodField()

    class Meta:
        model = SkillGroup
        fields = ["name", "skills"]

    def get_skills(self, obj):
        return obj.skill_list


class ExperienceSerializer(serializers.ModelSerializer):
    highlights = serializers.SerializerMethodField()
    technologies = serializers.SerializerMethodField()

    class Meta:
        model = Experience
        fields = [
            "role",
            "company",
            "location",
            "period",
            "is_current",
            "summary",
            "highlights",
            "technologies",
        ]

    def get_highlights(self, obj):
        return split_lines(obj.highlights)

    def get_technologies(self, obj):
        return split_commas(obj.technologies)


class ProjectSerializer(serializers.ModelSerializer):
    stack = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Project
        fields = [
            "title",
            "slug",
            "tagline",
            "description",
            "problem",
            "approach",
            "url",
            "repo_url",
            "cover_image",
            "status",
            "status_label",
            "stack",
            "featured",
        ]

    def get_stack(self, obj):
        return split_commas(obj.stack)

    def get_cover_image(self, obj):
        return absolute(self.context.get("request"), obj.cover_image)


class LabSerializer(serializers.ModelSerializer):
    highlights = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    diagram = serializers.SerializerMethodField()

    class Meta:
        model = Lab
        fields = [
            "title",
            "category",
            "provider",
            "summary",
            "highlights",
            "services",
            "repo_url",
            "diagram",
            "completed",
        ]

    def get_highlights(self, obj):
        return split_lines(obj.highlights)

    def get_services(self, obj):
        return split_commas(obj.services)

    def get_diagram(self, obj):
        return absolute(self.context.get("request"), obj.diagram)


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = ["degree", "institution", "period", "coursework"]


class CertificationSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Certification
        fields = ["name", "issuer", "year", "credential_url", "image"]

    def get_image(self, obj):
        return absolute(self.context.get("request"), obj.image)


class ContactMessageSerializer(serializers.ModelSerializer):
    # Honeypot: real visitors never see or fill this field.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message", "website"]

    def validate_subject(self, value):
        """When subjects are set up, the visitor must pick one of the active ones."""
        value = value.strip()
        choices = list(ContactSubject.objects.filter(is_active=True).values_list("label", flat=True))
        if not choices:
            return value
        if not value:
            raise serializers.ValidationError("Choose a subject.")
        if value not in choices:
            raise serializers.ValidationError("Choose one of the subjects in the list.")
        return value

    def validate_message(self, value):
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Write at least 10 characters so I know how to help.")
        return value.strip()

    def validate(self, attrs):
        if attrs.pop("website", ""):
            raise serializers.ValidationError("Message could not be sent.")
        return attrs
