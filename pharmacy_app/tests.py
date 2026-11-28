import tempfile
from datetime import time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from admin_app.models import ActivityLog
from home_app.models import Favorite, Medicine, MedicineCategory, User

from .forms import InventoryForm
from .models import Inventory, OperatingHours, Pharmacy, PharmacyVerification, Reservation
from .utils import create_reservation, open_now_map


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

    def test_dashboard_shows_open_status_favorites_alerts_and_recent_activity(self):
        today = timezone.localtime().weekday()
        OperatingHours.objects.create(
            pharmacy=self.pharmacy,
            days_of_week=today,
            opening_time=time(0, 0),
            closing_time=time(23, 59),
            is_closed=False,
        )
        cat = MedicineCategory.objects.create(category_name='Pain Relief')
        med = Medicine.objects.create(
            category=cat,
            medicine_name='Biogesic',
            generic_name='Paracetamol',
            form='Tablet',
            strength='500mg',
        )
        Inventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=med,
            price='5.00',
            availability_status='low_stock',
            stock_quantity=4,
        )
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })

        res = self.client.get(reverse('pharmacy_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Open now')
        self.assertContains(res, '24 hours')
        self.assertContains(res, 'Biogesic')
        self.assertContains(res, 'Stock alerts')
        self.assertContains(res, 'Recent activity')

    def test_inventory_filters_sort_quick_update_and_form_validation(self):
        cat1 = MedicineCategory.objects.create(category_name='Antibiotics')
        cat2 = MedicineCategory.objects.create(category_name='Vitamins')
        m1 = Medicine.objects.create(
            category=cat1, medicine_name='Amoxicillin', generic_name='Amoxicillin', form='Capsule', strength='500mg'
        )
        m2 = Medicine.objects.create(
            category=cat2, medicine_name='Ascorbic', generic_name='Vitamin C', form='Tablet', strength='500mg'
        )
        inv1 = Inventory.objects.create(
            pharmacy=self.pharmacy, medicine=m1, price='12.00', availability_status='low_stock', stock_quantity=5
        )
        Inventory.objects.create(
            pharmacy=self.pharmacy, medicine=m2, price='8.00', availability_status='available', stock_quantity=50
        )

        # Form validation checks stock_quantity vs availability_status
        bad_zero = InventoryForm(
            data={'medicine': m1.pk, 'price': '10.00', 'stock_quantity': 0, 'availability_status': 'available'}
        )
        self.assertFalse(bad_zero.is_valid())
        self.assertIn('availability_status', bad_zero.errors)

        bad_out = InventoryForm(
            data={'medicine': m1.pk, 'price': '10.00', 'stock_quantity': 10, 'availability_status': 'out_of_stock'}
        )
        self.assertFalse(bad_out.is_valid())
        self.assertIn('availability_status', bad_out.errors)

        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })
        res_filter = self.client.get(reverse('pharmacy_inventory'), {
            'q': 'Amox',
            'category': str(cat1.pk),
            'status': 'low_or_out',
            'sort': 'price_asc',
        })
        self.assertEqual(res_filter.status_code, 200)
        self.assertContains(res_filter, 'Amoxicillin')
        self.assertNotContains(res_filter, 'Ascorbic')

        # Quick update to 0 stock auto-sets out_of_stock
        res_quick = self.client.post(reverse('inventory_quick_update', args=[inv1.pk]), {
            'price': '13.50',
            'stock_quantity': '0',
            'availability_status': 'available',
        })
        self.assertRedirects(res_quick, reverse('pharmacy_inventory'))
        inv1.refresh_from_db()
        self.assertEqual(str(inv1.price), '13.50')
        self.assertEqual(inv1.stock_quantity, 0)
        self.assertEqual(inv1.availability_status, Inventory.STATUS_OUT)

    def test_operating_hours_supports_24h_and_overnight_schedules(self):
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })
        payload = {}
        for day in range(7):
            if day == 0:
                payload[f'open_{day}'] = '00:00'
                payload[f'close_{day}'] = '00:00'
            elif day == 1:
                payload[f'open_{day}'] = '18:00'
                payload[f'close_{day}'] = '02:00'
            else:
                payload[f'closed_{day}'] = 'on'

        res = self.client.post(reverse('pharmacy_hours'), payload)
        self.assertRedirects(res, reverse('pharmacy_hours'))
        self.assertEqual(OperatingHours.objects.filter(pharmacy=self.pharmacy).count(), 7)

        today = timezone.localtime().weekday()
        OperatingHours.objects.update_or_create(
            pharmacy=self.pharmacy,
            days_of_week=today,
            defaults={'opening_time': time(0, 0), 'closing_time': time(0, 0), 'is_closed': False},
        )
        self.assertTrue(open_now_map([self.pharmacy.pk])[self.pharmacy.pk])

    def test_verification_can_withdraw_pending_submission(self):
        self.pharmacy.verification_status = Pharmacy.VERIFICATION_PENDING
        self.pharmacy.save(update_fields=['verification_status', 'updated_at'])

        PharmacyVerification.objects.create(
            pharmacy=self.pharmacy,
            document_path='verification_docs/old_rejected.pdf',
            status=PharmacyVerification.STATUS_REJECTED,
            remarks='Blurry image',
        )
        pending = PharmacyVerification.objects.create(
            pharmacy=self.pharmacy,
            document_path='verification_docs/wrong_upload.pdf',
            status=PharmacyVerification.STATUS_PENDING,
        )

        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })
        res = self.client.post(reverse('verification_cancel', args=[pending.pk]))
        self.assertRedirects(res, reverse('pharmacy_verification'))
        self.assertFalse(PharmacyVerification.objects.filter(pk=pending.pk).exists())
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.verification_status, Pharmacy.VERIFICATION_REJECTED)

    def test_pharmacy_can_upload_display_and_remove_storefront_photo(self):
        with tempfile.TemporaryDirectory() as tmp_media:
            with override_settings(MEDIA_ROOT=tmp_media):
                self.client.post(reverse('pharmacy_login'), {
                    'email': 'care@pharmacy.com',
                    'password': 'PharmPass123!',
                })

                # Reject non-image files
                bad_file = SimpleUploadedFile('notes.txt', b'not an image', content_type='text/plain')
                res_bad = self.client.post(reverse('pharmacy_profile'), {
                    'action': 'update_profile',
                    'business_name': 'CarePlus Pharmacy',
                    'email': 'care@pharmacy.com',
                    'contact_number': '09175551234',
                    'address': 'Osmena Blvd, Cebu City',
                    'photo': bad_file,
                })
                self.assertEqual(res_bad.status_code, 200)
                self.assertContains(res_bad, 'Please upload a JPG, PNG, or WebP image.')

                # Upload valid PNG image
                img_file = SimpleUploadedFile('storefront.png', b'\x89PNG\r\n\x1a\nfake', content_type='image/png')
                res_ok = self.client.post(reverse('pharmacy_profile'), {
                    'action': 'update_profile',
                    'business_name': 'CarePlus Pharmacy',
                    'email': 'care@pharmacy.com',
                    'contact_number': '09175551234',
                    'address': 'Osmena Blvd, Cebu City',
                    'photo': img_file,
                })
                self.assertRedirects(res_ok, reverse('pharmacy_profile'))
                self.pharmacy.refresh_from_db()
                self.assertTrue(bool(self.pharmacy.photo))
                photo_url = self.pharmacy.photo.url

                # Visible on Pharmacy Dashboard
                dash_res = self.client.get(reverse('pharmacy_dashboard'))
                self.assertContains(dash_res, photo_url)

                # Visible on User End (Home, Search, Pharmacy Detail)
                self.client.get(reverse('pharmacy_logout'))
                user = User(
                    first_name='Pat',
                    last_name='Lim',
                    email='pat2@example.com',
                    phone_number='09178887777',
                )
                user.set_password('UserPass123!')
                user.save()
                self.client.post(reverse('login'), {'email': 'pat2@example.com', 'password': 'UserPass123!'})

                self.assertContains(self.client.get(reverse('home')), photo_url)
                self.assertContains(self.client.get(reverse('search')), photo_url)
                self.assertContains(
                    self.client.get(reverse('pharmacy_detail', args=[self.pharmacy.pk])),
                    photo_url,
                )

                # Remove photo from Pharmacy Profile
                self.client.get(reverse('logout'))
                self.client.post(reverse('pharmacy_login'), {
                    'email': 'care@pharmacy.com',
                    'password': 'PharmPass123!',
                })
                res_rem = self.client.post(reverse('pharmacy_profile'), {'action': 'remove_photo'})
                self.assertRedirects(res_rem, reverse('pharmacy_profile'))
                self.pharmacy.refresh_from_db()
                self.assertFalse(bool(self.pharmacy.photo))

    def test_pharmacy_reservation_claimed_unclaimed_and_24h_expiry_folders(self):
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })
        customer = User(
            first_name='Ana',
            last_name='Reyes',
            email='ana.reyes@example.com',
            phone_number='09178889999',
        )
        customer.set_password('CustPass123!')
        customer.save()

        cat = MedicineCategory.objects.create(
            category_name='Fever & Pain',
            description='Analgesics',
        )
        med = Medicine.objects.create(
            category=cat,
            medicine_name='Biogesic',
            generic_name='Paracetamol',
            form='Tablet',
            strength='500mg',
        )
        inv = Inventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=med,
            price='12.50',
            stock_quantity=20,
            availability_status='available',
        )

        # Create three reservations totaling 20 units -> stock becomes 0 (out_of_stock)
        r1 = create_reservation(customer, inv.pk, 5)
        r2 = create_reservation(customer, inv.pk, 8)
        r3 = create_reservation(customer, inv.pk, 7)

        inv.refresh_from_db()
        self.assertEqual(inv.stock_quantity, 0)
        self.assertEqual(inv.availability_status, 'out_of_stock')

        # Pending folder renders reservation IDs, medicine names, and only Claimed / Not claimed buttons
        pending_page = self.client.get(reverse('pharmacy_reservations'), {'folder': 'pending'})
        self.assertEqual(pending_page.status_code, 200)
        self.assertContains(pending_page, r1.reservation_code)
        self.assertContains(pending_page, 'Claimed')
        self.assertContains(pending_page, 'Not claimed')

        # Mark r1 as Claimed -> moves to Claimed folder, stock stays deducted
        res_claim = self.client.post(
            reverse('pharmacy_reservation_resolve', args=[r1.pk]),
            {'decision': 'claimed'},
        )
        self.assertRedirects(res_claim, reverse('pharmacy_reservations'))
        r1.refresh_from_db()
        self.assertEqual(r1.status, Reservation.STATUS_CLAIMED)
        claimed_page = self.client.get(reverse('pharmacy_reservations'), {'folder': 'claimed'})
        self.assertContains(claimed_page, r1.reservation_code)

        # Mark r2 as Not claimed -> moves to Unclaimed folder and restores 8 units
        self.client.post(
            reverse('pharmacy_reservation_resolve', args=[r2.pk]),
            {'decision': 'unclaimed'},
        )
        r2.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(r2.status, Reservation.STATUS_UNCLAIMED)
        self.assertFalse(r2.is_auto_expired)
        self.assertEqual(inv.stock_quantity, 8)
        self.assertEqual(inv.availability_status, 'low_stock')

        # Expire r3 past 24 hours -> auto-moves to Unclaimed folder and restores remaining 7 units
        Reservation.objects.filter(pk=r3.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )
        unclaimed_page = self.client.get(reverse('pharmacy_reservations'), {'folder': 'unclaimed'})
        self.assertContains(unclaimed_page, r2.reservation_code)
        self.assertContains(unclaimed_page, r3.reservation_code)
        r3.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(r3.status, Reservation.STATUS_UNCLAIMED)
        self.assertTrue(r3.is_auto_expired)
        self.assertEqual(inv.stock_quantity, 15)
        self.assertEqual(inv.availability_status, 'available')

    def test_inventory_add_starts_empty_and_supports_typing_existing_or_new_medicine(self):
        self.client.post(reverse('pharmacy_login'), {
            'email': 'care@pharmacy.com',
            'password': 'PharmPass123!',
        })
        cat = MedicineCategory.objects.create(category_name='Pain Relief')
        existing_med = Medicine.objects.create(
            category=cat,
            medicine_name='Tempra',
            generic_name='Paracetamol',
            form='Syrup',
            strength='120mg/5mL',
        )

        # GET Add page uses type-ahead input + empty hidden menu (no pre-populated <select name="medicine">)
        get_res = self.client.get(reverse('inventory_add'))
        self.assertEqual(get_res.status_code, 200)
        self.assertNotContains(get_res, '<select name="medicine"')
        self.assertContains(get_res, 'id="id_medicine_query"')
        self.assertContains(get_res, 'id="pp-med-menu" role="listbox" hidden')

        # Typing an existing catalog medicine name links it to inventory
        post_existing = self.client.post(reverse('inventory_add'), {
            'medicine_query': 'Tempra',
            'price': '110.00',
            'availability_status': Inventory.STATUS_AVAILABLE,
            'stock_quantity': '25',
        })
        self.assertRedirects(post_existing, reverse('pharmacy_inventory'))
        self.assertTrue(
            Inventory.objects.filter(pharmacy=self.pharmacy, medicine=existing_med).exists()
        )

        # Duplicate typed medicine in the same pharmacy is rejected cleanly
        post_dup = self.client.post(reverse('inventory_add'), {
            'medicine_query': 'Tempra',
            'price': '110.00',
            'availability_status': Inventory.STATUS_AVAILABLE,
            'stock_quantity': '10',
        })
        self.assertEqual(post_dup.status_code, 200)
        self.assertContains(post_dup, 'is already in your inventory.')

        # Typing a brand-new medicine normalizes casing/spacing, adds to catalog, and avoids duplicates
        post_new = self.client.post(reverse('inventory_add'), {
            'medicine_query': '  bioflu  ',
            'new_category': str(cat.pk),
            'new_generic_name': 'Phenylephrine + Chlorphenamine + Paracetamol',
            'new_form': 'tablet',
            'new_strength': '500 mg',
            'price': '9.50',
            'availability_status': Inventory.STATUS_AVAILABLE,
            'stock_quantity': '40',
        })
        self.assertRedirects(post_new, reverse('pharmacy_inventory'))
        created_med = Medicine.objects.get(medicine_name='Bioflu')
        self.assertEqual(created_med.form, 'Tablet')
        self.assertEqual(created_med.strength, '500mg')
        self.assertTrue(
            Inventory.objects.filter(pharmacy=self.pharmacy, medicine=created_med, stock_quantity=40).exists()
        )

        # A second pharmacy typing BIOFLU (with differing case/spacing) reuses the same Medicine row cleanly
        self.client.get(reverse('pharmacy_logout'))
        self.client.post(reverse('pharmacy_login'), {
            'email': 'other@pharmacy.com',
            'password': 'PharmPass123!',
        })
        post_second_pharmacy = self.client.post(reverse('inventory_add'), {
            'medicine_query': 'BIOFLU',
            'new_form': 'Tablet',
            'new_strength': '500mg',
            'price': '10.00',
            'availability_status': Inventory.STATUS_AVAILABLE,
            'stock_quantity': '15',
        })
        self.assertRedirects(post_second_pharmacy, reverse('pharmacy_inventory'))
        self.assertEqual(Medicine.objects.filter(medicine_name__iexact='bioflu').count(), 1)
        self.assertTrue(
            Inventory.objects.filter(pharmacy=self.other_pharmacy, medicine=created_med, stock_quantity=15).exists()
        )

        # Browsing sees the combined availability across all pharmacies without duplicate Medicine cards
        browse_res = self.client.get(reverse('public_browse'), {'q': 'Bioflu'})
        self.assertContains(browse_res, 'In stock at 2 pharmacies')
