from django.core.exceptions import ValidationError
from django.db import models


def split_lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def split_commas(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


class Ordered(models.Model):
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first.")

    class Meta:
        abstract = True
        ordering = ["order", "id"]


class Profile(models.Model):
    """Single profile record. The admin only allows one."""

    name = models.CharField(max_length=120)
    title = models.CharField(max_length=120, help_text="e.g. Backend Engineer")
    headline = models.CharField(max_length=200, help_text="One sentence shown large in the hero.")
    summary = models.TextField(help_text="Short professional summary.")
    about = models.TextField(blank=True, help_text="A more personal paragraph for the About section.")
    location = models.CharField(max_length=120, blank=True)
    email = models.EmailField()
    secondary_email = models.EmailField(blank=True, help_text="Optional second address shown under the main email.")
    phone = models.CharField(max_length=40, blank=True)
    photo = models.ImageField(upload_to="profile/", blank=True)
    cv_file = models.FileField(upload_to="cv/", blank=True, help_text="PDF visitors can download.")
    available_for_work = models.BooleanField(default=True)
    years_experience = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Shown as “N+ years” in the stats strip. Leave empty to hide it."
    )

    # Site copy: the headings and intros around each section, so wording changes need no code.
    availability_text = models.CharField(
        max_length=120,
        blank=True,
        default="Available for backend & full-stack roles",
        help_text="Badge at the top of the hero, shown while “available for work” is ticked.",
    )
    about_heading = models.CharField(max_length=120, default="Engineering systems people rely on")
    experience_intro = models.CharField(
        max_length=300,
        blank=True,
        default="Backend and full-stack engineering roles, building and running systems in production.",
    )
    projects_intro = models.CharField(
        max_length=300,
        blank=True,
        default="Systems built for real users. Each one covers the problem and how I solved it.",
    )
    skills_intro = models.CharField(
        max_length=300,
        blank=True,
        default="The languages, frameworks, and infrastructure I use to design, build, and run production systems.",
    )
    contact_heading = models.CharField(max_length=120, default="Let’s build something reliable")
    contact_intro = models.TextField(
        blank=True,
        default=(
            "Hiring for a backend or full-stack role, or have a system that needs building? "
            "I usually reply within two working days."
        ),
    )
    meta_description = models.CharField(
        max_length=300,
        blank=True,
        help_text="Short description used by search engines and link previews.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if not self.pk and Profile.objects.exists():
            raise ValidationError("Only one profile is allowed. Edit the existing one instead.")

    def __str__(self):
        return self.name


class SocialLink(Ordered):
    profile = models.ForeignKey(Profile, related_name="socials", on_delete=models.CASCADE)
    label = models.CharField(max_length=40)
    url = models.CharField(max_length=300, help_text="Full URL, or mailto:you@example.com")

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return self.label


class SkillGroup(Ordered):
    name = models.CharField(max_length=80)
    skills = models.TextField(help_text="Comma-separated, e.g. Python, Django, FastAPI")

    class Meta(Ordered.Meta):
        pass

    @property
    def skill_list(self):
        return split_commas(self.skills)

    def __str__(self):
        return self.name


class Experience(Ordered):
    role = models.CharField(max_length=120)
    company = models.CharField(max_length=120)
    location = models.CharField(max_length=120, blank=True)
    period = models.CharField(max_length=60, help_text="As it should appear, e.g. 2023 – Present")
    is_current = models.BooleanField(default=False)
    summary = models.CharField(max_length=240, blank=True)
    highlights = models.TextField(blank=True, help_text="One achievement per line.")
    technologies = models.CharField(max_length=300, blank=True, help_text="Comma-separated.")

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return f"{self.role} at {self.company}"


class Project(Ordered):
    class Status(models.TextChoices):
        PRODUCTION = "production", "In production"
        COMPLETED = "completed", "Completed"
        IN_PROGRESS = "in_progress", "In progress"

    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    tagline = models.CharField(max_length=200)
    description = models.TextField()
    problem = models.TextField(blank=True, help_text="What problem did it solve? Shown on the project page.")
    approach = models.TextField(blank=True, help_text="How you built it and your contribution.")
    url = models.URLField(blank=True, help_text="Live link, if public.")
    repo_url = models.URLField(blank=True)
    cover_image = models.ImageField(upload_to="projects/", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRODUCTION)
    stack = models.CharField(max_length=300, blank=True, help_text="Comma-separated.")
    featured = models.BooleanField(default=False, help_text="Featured projects get a full case study.")

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return self.title


class Lab(Ordered):
    """A hands-on cloud lab: infrastructure built and deployed from a repository, shown in its own section."""

    title = models.CharField(max_length=140, unique=True)
    category = models.CharField(max_length=60, help_text="Short topic shown as a badge, e.g. Networking & security.")
    provider = models.CharField(max_length=40, default="AWS", help_text="Cloud platform, e.g. AWS.")
    summary = models.TextField(help_text="Two or three sentences: what was built and why.")
    highlights = models.TextField(blank=True, help_text="One key outcome per line. The first three are shown.")
    services = models.CharField(max_length=400, blank=True, help_text="Comma-separated, e.g. VPC, ALB, ECS Fargate")
    repo_url = models.URLField(blank=True)
    diagram = models.ImageField(upload_to="labs/", blank=True, help_text="Architecture diagram, shown on the card.")
    completed = models.CharField(max_length=40, blank=True, help_text="As it should appear, e.g. Oct 2026")

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return self.title


class Education(Ordered):
    degree = models.CharField(max_length=160)
    institution = models.CharField(max_length=200)
    period = models.CharField(max_length=60, blank=True)
    coursework = models.TextField(blank=True)

    class Meta(Ordered.Meta):
        verbose_name_plural = "education"

    def __str__(self):
        return self.degree


class Certification(Ordered):
    name = models.CharField(max_length=160)
    issuer = models.CharField(max_length=120, blank=True)
    year = models.CharField(max_length=10, blank=True)
    credential_url = models.URLField(blank=True)
    image = models.ImageField(
        upload_to="certificates/", blank=True, help_text="Picture of the certificate, shown on the site."
    )

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return self.name


class ContactSubject(Ordered):
    """A subject visitors pick from in the contact form, so messages arrive already sorted."""

    label = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True, help_text="Only active subjects are offered on the site.")

    class Meta(Ordered.Meta):
        pass

    def __str__(self):
        return self.label


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=160, blank=True)
    message = models.TextField(max_length=5000)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}: {self.subject or self.message[:40]}"


class Resume(models.Model):
    """
    The CV built in the dashboard (single record). `content` holds its sections as structured data
    (see resume_pdf.py); publishing renders it to PDF, keeps a numbered version and makes that PDF
    the site's CV.
    """

    content = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "CV"


def resume_version_path(instance: "ResumeVersion", filename: str) -> str:
    # A folder per version keeps a clean file name for visitors (Name_CV.pdf) and gives every
    # publish a new URL, so browsers and caches never show an old copy.
    return f"cv/v{instance.number}/{filename}"


class ResumeVersion(models.Model):
    """A published CV: the content it was made from and the PDF visitors downloaded."""

    number = models.PositiveIntegerField(unique=True)
    content = models.JSONField()
    file = models.FileField(upload_to=resume_version_path)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]

    def __str__(self):
        return f"CV v{self.number}"
