from django.test import TestCase
from django.urls import reverse

from home_app.models import User


class LoginAndForgotPasswordTests(TestCase):
    def setUp(self):
        self.user = User(
            first_name='Ana',
            last_name='Cruz',
            email='ana@example.com',
            phone_number='+63 917 123 4567',
        )
        self.user.set_password('StrongPass123!')
        self.user.save()

    def test_user_can_login_with_email(self):
        res = self.client.post(reverse('login'), {
            'email': 'ANA@EXAMPLE.COM',
            'password': 'StrongPass123!',
        })
        self.assertRedirects(res, reverse('home'))

    def test_user_can_login_with_phone_number(self):
        res = self.client.post(reverse('login'), {
            'email': '09171234567',
            'password': 'StrongPass123!',
        })
        self.assertRedirects(res, reverse('home'))

    def test_user_login_rejects_duplicate_phone_number(self):
        other = User(
            first_name='Bea',
            last_name='Reyes',
            email='bea@example.com',
            phone_number='09171234567',
        )
        other.set_password('StrongPass123!')
        other.save()

        res = self.client.post(reverse('login'), {
            'email': '09171234567',
            'password': 'StrongPass123!',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Multiple accounts share that phone number')

    def test_forgot_password_resets_password_when_email_and_phone_match(self):
        get_res = self.client.get(reverse('forgot_password'))
        self.assertEqual(get_res.status_code, 200)

        res = self.client.post(reverse('forgot_password'), {
            'email': 'ana@example.com',
            'phone_number': '09171234567',
            'new_password1': 'NewStrongPass456!',
            'new_password2': 'NewStrongPass456!',
        })
        self.assertRedirects(res, reverse('login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass456!'))

    def test_forgot_password_rejects_mismatched_phone(self):
        res = self.client.post(reverse('forgot_password'), {
            'email': 'ana@example.com',
            'phone_number': '09990001111',
            'new_password1': 'NewStrongPass456!',
            'new_password2': 'NewStrongPass456!',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'No account matched that email and phone number.')

    def test_logout_displays_toast_notification_instead_of_inline_banner(self):
        self.client.post(reverse('login'), {
            'email': 'ana@example.com',
            'password': 'StrongPass123!',
        })
        res = self.client.get(reverse('logout'), follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'up-toast-stack')
        self.assertContains(res, 'You have been logged out.')
        self.assertNotContains(res, 'login-messages')
