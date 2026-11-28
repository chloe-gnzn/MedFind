from django.test import TestCase
from django.urls import reverse

from home_app.models import Medicine, MedicineCategory, User
from pharmacy_app.models import Inventory, Pharmacy, PharmacyVerification

from .models import ActivityLog, Admin


class AdminPortalTests(TestCase):
    def setUp(self):
        self.super_admin = Admin(
            email='super@medfind.test',
            first_name='Ana',
            last_name='Super',
            role=Admin.ROLE_SUPER_ADMIN,
        )
        self.super_admin.set_password('AdminPass123!')
        self.super_admin.save()

        self.regular_admin = Admin(
            email='mod@medfind.test',
            first_name='Ben',
            last_name='Mod',
            role=Admin.ROLE_ADMIN,
        )
        self.regular_admin.set_password('AdminPass123!')
        self.regular_admin.save()

        self.pharmacy = Pharmacy(
            email='pharm@medfind.test',
            business_name='Central Pharmacy',
            contact_number='09171234567',
            address='Cebu City',
            verification_status='pending',
            is_active=True,
        )
        self.pharmacy.set_password('PharmPass123!')
        self.pharmacy.save()

        self.user = User(
            first_name='Jane',
            last_name='Doe',
            email='jane@example.com',
            phone_number='09170001111',
        )
        self.user.set_password('UserPass123!')
        self.user.save()

        self.cat = MedicineCategory.objects.create(category_name='Pain Relief', description='Analgesics')
        self.med = Medicine.objects.create(
            category=self.cat,
            medicine_name='Biogesic',
            generic_name='Paracetamol',
            form='Tablet',
            strength='500mg',
        )
        Inventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=self.med,
            price='5.50',
            availability_status='available',
            stock_quantity=25,
        )

    def _login_as(self, admin_obj):
        self.client.get(reverse('admin_logout'))
        self.client.post(reverse('admin_login'), {
            'email': admin_obj.email,
            'password': 'AdminPass123!',
        })

    def test_admin_profile_update_and_password_change(self):
        self._login_as(self.regular_admin)

        res_get = self.client.get(reverse('admin_profile'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, 'Account Details')

        res_upd = self.client.post(reverse('admin_profile'), {
            'action': 'update_profile',
            'first_name': 'Benny',
            'last_name': 'Moderator',
            'email': 'benny@medfind.test',
        })
        self.assertRedirects(res_upd, reverse('admin_profile'))
        self.regular_admin.refresh_from_db()
        self.assertEqual(self.regular_admin.first_name, 'Benny')

        res_pw = self.client.post(reverse('admin_profile'), {
            'action': 'change_password',
            'current_password': 'AdminPass123!',
            'new_password1': 'NewAdminPass456!',
            'new_password2': 'NewAdminPass456!',
        })
        self.assertRedirects(res_pw, reverse('admin_profile'))
        self.regular_admin.refresh_from_db()
        self.assertTrue(self.regular_admin.check_password('NewAdminPass456!'))

    def test_super_admin_only_can_manage_admins(self):
        # Regular admin is blocked
        self._login_as(self.regular_admin)
        res_blocked = self.client.get(reverse('admin_admins'))
        self.assertRedirects(res_blocked, reverse('admin_dashboard'))

        # Super admin can list, create, toggle role, and delete
        self._login_as(self.super_admin)
        res_list = self.client.get(reverse('admin_admins'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, 'mod@medfind.test')

        res_add = self.client.post(reverse('admin_add'), {
            'first_name': 'Cara',
            'last_name': 'New',
            'email': 'cara@medfind.test',
            'role': Admin.ROLE_ADMIN,
            'password1': 'CaraPass123!',
            'password2': 'CaraPass123!',
        })
        self.assertRedirects(res_add, reverse('admin_admins'))
        cara = Admin.objects.get(email='cara@medfind.test')

        res_role = self.client.post(reverse('admin_toggle_role', args=[cara.pk]))
        self.assertRedirects(res_role, reverse('admin_admins'))
        cara.refresh_from_db()
        self.assertEqual(cara.role, Admin.ROLE_SUPER_ADMIN)

        res_del = self.client.post(reverse('admin_delete', args=[cara.pk]))
        self.assertRedirects(res_del, reverse('admin_admins'))
        self.assertFalse(Admin.objects.filter(pk=cara.pk).exists())

    def test_admin_search_filters_pharmacy_detail_and_inline_image_review(self):
        ver = PharmacyVerification.objects.create(
            pharmacy=self.pharmacy,
            document_path='verification_docs/permit.png',
            status=PharmacyVerification.STATUS_PENDING,
        )
        ActivityLog.objects.create(
            actor_type='user',
            actor_id=self.user.pk,
            action='login',
            description='Jane logged in.',
        )

        self._login_as(self.super_admin)

        self.assertContains(self.client.get(reverse('admin_verifications'), {'q': 'Central'}), 'Central Pharmacy')
        self.assertContains(self.client.get(reverse('admin_verification_review', args=[ver.pk])), 'am-doc-preview')
        self.assertContains(self.client.get(reverse('admin_pharmacies'), {'q': 'Central', 'status': 'pending'}), 'Central Pharmacy')
        self.assertContains(self.client.get(reverse('admin_pharmacy_detail', args=[self.pharmacy.pk])), 'Biogesic')
        self.assertContains(self.client.get(reverse('admin_users'), {'q': 'Jane'}), 'jane@example.com')
        self.assertContains(self.client.get(reverse('admin_categories'), {'q': 'Pain'}), 'Pain Relief')
        self.assertContains(self.client.get(reverse('admin_medicines'), {'q': 'Paracetamol', 'category': str(self.cat.pk)}), 'Biogesic')
        self.assertContains(self.client.get(reverse('admin_activity'), {'actor': 'user', 'q': 'Jane'}), 'Jane logged in.')
