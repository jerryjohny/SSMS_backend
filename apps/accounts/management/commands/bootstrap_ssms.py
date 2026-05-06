from django.core.management.base import BaseCommand

from apps.accounts.models import Store, Tenant, User


class Command(BaseCommand):
    help = "Bootstrap a local SSMS tenant, shop, and starter users when the database is empty."

    def handle(self, *args, **options):
        tenant, _ = Tenant.objects.get_or_create(
            slug="ssms-demo",
            defaults={"name": "SSMS Demo Tenant", "is_active": True},
        )
        store, _ = Store.objects.get_or_create(
            tenant=tenant,
            code="BAIXA",
            defaults={
                "name": "Baixa Store",
                "address": "Maputo",
                "phone": "+258 84 111 0000",
                "is_active": True,
            },
        )

        starter_users = [
            {
                "username": "sysadmin",
                "email": "sysadmin@ssms.local",
                "first_name": "System",
                "last_name": "Admin",
                "role": User.Role.SYSADMIN,
            },
            {
                "username": "admin",
                "email": "admin@ssms.local",
                "first_name": "Store",
                "last_name": "Admin",
                "role": User.Role.ADMIN,
            },
            {
                "username": "seller",
                "email": "seller@ssms.local",
                "first_name": "Demo",
                "last_name": "Seller",
                "role": User.Role.SELLER,
            },
        ]

        for payload in starter_users:
            user, created = User.objects.get_or_create(
                username=payload["username"],
                defaults={
                    **payload,
                    "tenant": tenant,
                    "store": store,
                    "phone": "+258 84 000 0000",
                    "is_active": True,
                },
            )
            if created or not user.has_usable_password():
                user.set_password("ssms1234")
                user.tenant = tenant
                user.store = store
                user.role = payload["role"]
                user.email = payload["email"]
                user.first_name = payload["first_name"]
                user.last_name = payload["last_name"]
                user.phone = "+258 84 000 0000"
                user.is_active = True
                user.save()

            user.assigned_stores.add(store)

        self.stdout.write(
            self.style.SUCCESS(
                "Bootstrapped SSMS demo data. Users: sysadmin / admin / seller. Password: ssms1234"
            )
        )
