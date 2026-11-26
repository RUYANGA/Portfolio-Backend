from django.contrib import admin
from django.utils.html import format_html

from apps.portfolio.models import (
    Certification,
    ContactMessage,
    Education,
    Experience,
    Lab,
    Profile,
    Project,
    SkillGroup,
    SocialLink,
)

admin.site.site_header = "Portfolio admin"
admin.site.site_title = "Portfolio admin"
admin.site.index_title = "Site content"


def preview(file, height=60):
    """Small thumbnail for image fields in lists and forms."""
    if not file:
        return "—"
    return format_html(
        '<img src="{}" style="height:{}px;border-radius:6px;border:1px solid #ddd;object-fit:cover">',
        file.url,
        height,
    )


class SocialLinkInline(admin.TabularInline):
    model = SocialLink
    extra = 0
    fields = ["label", "url", "order"]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    inlines = [SocialLinkInline]
    list_display = ["name", "title", "available_for_work", "updated_at"]
    readonly_fields = ["photo_preview", "updated_at"]
    fieldsets = [
        ("Identity", {"fields": ["name", "title", "headline", "location", "email", "phone"]}),
        ("About", {"fields": ["summary", "about", "years_experience"]}),
        ("Files", {"fields": ["photo", "photo_preview", "cv_file"]}),
        ("Availability", {"fields": ["available_for_work", "availability_text"]}),
        (
            "Section headings and intros",
            {
                "description": "Wording shown around each section of the site.",
                "fields": [
                    "about_heading",
                    "experience_intro",
                    "projects_intro",
                    "skills_intro",
                    "contact_heading",
                    "contact_intro",
                ],
            },
        ),
        ("Search engines", {"fields": ["meta_description"]}),
        (None, {"fields": ["updated_at"]}),
    ]

    @admin.display(description="Current photo")
    def photo_preview(self, obj):
        return preview(obj.photo, 120)

    def has_add_permission(self, request):
        return not Profile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SkillGroup)
class SkillGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "skills", "order"]
    list_editable = ["order"]
    search_fields = ["name", "skills"]


@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ["role", "company", "period", "is_current", "order"]
    list_editable = ["is_current", "order"]
    list_filter = ["is_current"]
    search_fields = ["role", "company", "highlights", "technologies"]
    fieldsets = [
        (None, {"fields": ["role", "company", "location", "period", "is_current", "order"]}),
        ("Details", {"fields": ["summary", "highlights", "technologies"]}),
    ]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["thumbnail", "title", "status", "featured", "order"]
    list_display_links = ["thumbnail", "title"]
    list_editable = ["status", "featured", "order"]
    list_filter = ["status", "featured"]
    prepopulated_fields = {"slug": ["title"]}
    search_fields = ["title", "tagline", "description", "stack"]
    readonly_fields = ["cover_preview"]
    fieldsets = [
        (None, {"fields": ["title", "slug", "tagline", "status", "featured", "order"]}),
        ("Links", {"fields": ["url", "repo_url"]}),
        ("Cover image", {"fields": ["cover_image", "cover_preview"]}),
        ("Case study", {"fields": ["description", "problem", "approach", "stack"]}),
    ]

    @admin.display(description="")
    def thumbnail(self, obj):
        return preview(obj.cover_image, 40)

    @admin.display(description="Current cover")
    def cover_preview(self, obj):
        return preview(obj.cover_image, 180)


@admin.register(Lab)
class LabAdmin(admin.ModelAdmin):
    list_display = ["thumbnail", "title", "category", "provider", "completed", "order"]
    list_display_links = ["thumbnail", "title"]
    list_editable = ["order"]
    list_filter = ["provider", "category"]
    search_fields = ["title", "summary", "services"]
    readonly_fields = ["diagram_preview"]
    fieldsets = [
        (None, {"fields": ["title", "category", "provider", "completed", "repo_url", "order"]}),
        ("Architecture diagram", {"fields": ["diagram", "diagram_preview"]}),
        ("Details", {"fields": ["summary", "highlights", "services"]}),
    ]

    @admin.display(description="")
    def thumbnail(self, obj):
        return preview(obj.diagram, 40)

    @admin.display(description="Current diagram")
    def diagram_preview(self, obj):
        return preview(obj.diagram, 180)


@admin.register(Education)
class EducationAdmin(admin.ModelAdmin):
    list_display = ["degree", "institution", "period", "order"]
    list_editable = ["order"]


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ["thumbnail", "name", "issuer", "year", "order"]
    list_display_links = ["thumbnail", "name"]
    list_editable = ["order"]
    list_filter = ["issuer", "year"]
    search_fields = ["name", "issuer"]
    readonly_fields = ["image_preview"]
    fields = ["name", "issuer", "year", "credential_url", "image", "image_preview", "order"]

    @admin.display(description="")
    def thumbnail(self, obj):
        return preview(obj.image, 40)

    @admin.display(description="Current image")
    def image_preview(self, obj):
        return preview(obj.image, 180)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "subject", "created_at", "is_read"]
    list_filter = ["is_read", "created_at"]
    list_editable = ["is_read"]
    readonly_fields = ["name", "email", "subject", "message", "created_at"]
    search_fields = ["name", "email", "subject", "message"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
