"""
Small read-only endpoints for the "live API" panel in the hero. Each answers from the database
on every request (several pick a random record), so "Send again" shows something new each time.

GET /api/projects/random/        one project
GET /api/labs/random/            one cloud lab
GET /api/experience/current/     the current role (or the latest one)
GET /api/skills/random/          one skill group
GET /api/certifications/random/  one certification
GET /api/stats/                  counts across the whole portfolio
"""

from django.db.models import Model, QuerySet
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.booking.models import MeetingType
from apps.portfolio.models import Certification, Experience, Lab, Profile, Project, SkillGroup, split_commas

LIST_LIMIT = 5  # keep responses short enough to read in the panel


def random_from(queryset: QuerySet) -> Model | None:
    return queryset.order_by("?").first()


def not_found(what: str) -> Response:
    return Response({"detail": f"No {what} yet."}, status=404)


class RandomProjectView(APIView):
    def get(self, request):
        project = random_from(Project.objects.all())
        if not isinstance(project, Project):
            return not_found("projects")
        return Response(
            {
                "title": project.title,
                "tagline": project.tagline,
                "status": project.get_status_display(),
                "stack": split_commas(project.stack)[:LIST_LIMIT],
                "live_url": project.url or None,
            }
        )


class RandomLabView(APIView):
    def get(self, request):
        lab = random_from(Lab.objects.all())
        if not isinstance(lab, Lab):
            return not_found("labs")
        return Response(
            {
                "title": lab.title,
                "provider": lab.provider,
                "topic": lab.category,
                "services": split_commas(lab.services)[:LIST_LIMIT],
                "completed": lab.completed or None,
            }
        )


class CurrentExperienceView(APIView):
    def get(self, request):
        job = Experience.objects.filter(is_current=True).first() or Experience.objects.first()
        if job is None:
            return not_found("experience")
        return Response(
            {
                "role": job.role,
                "company": job.company,
                "period": job.period,
                "current": job.is_current,
                "technologies": split_commas(job.technologies)[:LIST_LIMIT],
            }
        )


class RandomSkillGroupView(APIView):
    def get(self, request):
        group = random_from(SkillGroup.objects.all())
        if not isinstance(group, SkillGroup):
            return not_found("skills")
        skills = group.skill_list
        return Response({"group": group.name, "count": len(skills), "skills": skills[: LIST_LIMIT + 1]})


class RandomCertificationView(APIView):
    def get(self, request):
        cert = random_from(Certification.objects.all())
        if not isinstance(cert, Certification):
            return not_found("certifications")
        return Response(
            {
                "name": cert.name,
                "issuer": cert.issuer or None,
                "year": cert.year or None,
                "verifiable": bool(cert.credential_url),
            }
        )


class StatsView(APIView):
    def get(self, request):
        profile = Profile.objects.first()
        return Response(
            {
                "projects": Project.objects.count(),
                "in_production": Project.objects.filter(status=Project.Status.PRODUCTION).count(),
                "cloud_labs": Lab.objects.count(),
                "certifications": Certification.objects.count(),
                "skills": sum(len(g.skill_list) for g in SkillGroup.objects.all()),
                "meeting_types": MeetingType.objects.filter(is_active=True).count(),
                "open_to_work": bool(profile and profile.available_for_work),
                "served_at": timezone.now().replace(microsecond=0),
            }
        )
