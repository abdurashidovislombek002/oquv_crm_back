from django.db import models
from django.utils.translation import gettext_lazy as _

ROLE_SUPER_ADMIN = "super_admin"
ROLE_BRANCH_ADMIN = "branch_admin"
ROLE_MANAGER = "manager"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_PARENT = "parent"


class Role(models.TextChoices):
    SUPER_ADMIN = ROLE_SUPER_ADMIN, _("Super Admin")
    BRANCH_ADMIN = ROLE_BRANCH_ADMIN, _("Filial Admini")
    MANAGER = ROLE_MANAGER, _("Menejer")
    TEACHER = ROLE_TEACHER, _("O'qituvchi")
    STUDENT = ROLE_STUDENT, _("O'quvchi")
    PARENT = ROLE_PARENT, _("Ota-ona")


MANAGEMENT_ROLES = (Role.SUPER_ADMIN, Role.BRANCH_ADMIN, Role.MANAGER)
TEACHING_ROLES = (Role.SUPER_ADMIN, Role.BRANCH_ADMIN, Role.MANAGER, Role.TEACHER)
