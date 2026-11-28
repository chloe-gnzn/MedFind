from django.test import TestCase
from django.urls import reverse

from admin_app.models import ActivityLog
from home_app.models import Favorite, User

from .models import Pharmacy


class PharmacyMissingScreensTests(TestCase):
    def setUp(self):
        self.pharmacy = Pharmacy(
            email='care@pharmacy.com',
            business_name='CarePlus Pharmacy',
            contact_number='+63 917 555 1234',
            address='Osmena Blvd, Cebu City',
            verification_status='approved',
            is_active=True,
        )
        self.pharmacy.set_password('PharmPass123!')
        self.pharmacy.save()

        self.other_pharmacy = Pharmacy(
            email='other@pharmacy.com',
            business_name='Other Pharmacy',
            contact_number='09170009999',
            address='Lahug, Cebu City',
            verification_status='approved',
            is_active=True,
        )
        self.other_pharmacy.set_password('PharmPass123!')
        self.other_pharmacy.save()

    def test_pharmacy_forgot_password_resets_when_email_and_contact_match(self):
        res_get = self.client.get(reverse('pharmacy_forgot_password'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, 'Pharmacy Portal')

        res_bad = self.client.post(reverse('pharmacy_forgot_password'), {
            'email': 'care@pharmacy.com',
            'phone_number': '09170000000',
            'new_password1': 'NewPharmPass456!',
            'new_password2': 'NewPharmPass456!',
        })
        self.assertEqual(res_bad.status_code, 200)
        self.assertContains(res_bad, 'No pharmacy account matched that email and contact number.')

        res_ok = self.client.post(reverse('pharmacy_forgot_password'), {
            'email': 'care@pharmacy.com',
            'phone_number': '09175551234',
            'new_password1': 'NewPharmPass456!',
            'new_password2': 'NewPharmPass456!',
        })
        self.assertRedirects(res_ok, reverse('pharmacy_login'))
        self.pharmacy.refresh_from_db()
        self.assertTrue(self.pharmacy.check_password('NewPharmPass456!'))

    def test_pharmacy_profile_view_update_and_password_change(self):
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })

        user = User(
            first_name='Pat',
            last_name='Lim',
            email='pat@example.com',
            phone_number='09178889999',
        )
        user.set_password('UserPass123!')
        user.save()
        Favorite.objects.create(user=user, pharmacy=self.pharmacy, favorite_type='pharmacy')

        res_get = self.client.get(reverse('pharmacy_profile'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, 'Business Details')
        self.assertContains(res_get, 'Change Password')

        # Reject duplicate email belonging to another pharmacy
        res_dup = self.client.post(reverse('pharmacy_profile'), {
            'action': 'update_profile',
            'business_name': 'CarePlus Pharmacy',
            'email': 'other@pharmacy.com',
            'contact_number': '09175551234',
            'address': 'Osmena Blvd, Cebu City',
        })
        self.assertEqual(res_dup.status_code, 200)
        self.assertContains(res_dup, 'Another pharmacy account is already using this email address.')

        res_upd = self.client.post(reverse('pharmacy_profile'), {
            'action': 'update_profile',
            'business_name': 'CarePlus Fuente',
            'email': 'careplus@pharmacy.com',
            'contact_number': '09175559999',
            'address': 'Fuente Circle, Cebu City',
        })
        self.assertRedirects(res_upd, reverse('pharmacy_profile'))
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.business_name, 'CarePlus Fuente')
        self.assertEqual(self.pharmacy.email, 'careplus@pharmacy.com')

        res_pw = self.client.post(reverse('pharmacy_profile'), {
            'action': 'change_password',
            'current_password': 'PharmPass123!',
            'new_password1': 'UpdatedPharm789!',
            'new_password2': 'UpdatedPharm789!',
        })
        self.assertRedirects(res_pw, reverse('pharmacy_profile'))
        self.pharmacy.refresh_from_db()
        self.assertTrue(self.pharmacy.check_password('UpdatedPharm789!'))

    def test_pharmacy_activity_shows_only_own_logs_and_filters(self):
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })

        ActivityLog.objects.create(
            actor_type='pharmacy',
            actor_id=self.pharmacy.pk,
            action='inventory_add',
            description='Added Biogesic.',
        )
        ActivityLog.objects.create(
            actor_type='pharmacy',
            actor_id=self.other_pharmacy.pk,
            action='inventory_add',
            description='Other pharmacy secret log.',
        )

        res = self.client.get(reverse('pharmacy_activity'), {'group': 'inventory'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Added Biogesic.')
        self.assertNotContains(res, 'Other pharmacy secret log.')
