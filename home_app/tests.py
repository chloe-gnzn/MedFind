from datetime import time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from pharmacy_app.models import Inventory, OperatingHours, Pharmacy

from .models import Favorite, Medicine, MedicineCategory, SearchHistory, User


class UserPortalTests(TestCase):
    def setUp(self):
        self.user = User(
            first_name='Juan',
            last_name='Dela Cruz',
            email='juan@example.com',
            phone_number='09171112222',
        )
        self.user.set_password('InitialPass123!')
        self.user.save()

        self.other_user = User(
            first_name='Maria',
            last_name='Santos',
            email='maria@example.com',
            phone_number='09173334444',
        )
        self.other_user.set_password('InitialPass123!')
        self.other_user.save()

        self.cat_pain = MedicineCategory.objects.create(
            category_name='Pain Relief',
            description='Analgesics and fever reducers.',
        )
        self.cat_vit = MedicineCategory.objects.create(
            category_name='Vitamins',
            description='Daily nutritional supplements.',
        )

        self.med_biogesic = Medicine.objects.create(
            category=self.cat_pain,
            medicine_name='Biogesic',
            generic_name='Paracetamol',
            form='Tablet',
            strength='500mg',
            description='For fever and mild pain.',
        )
        self.med_vitc = Medicine.objects.create(
            category=self.cat_vit,
            medicine_name='Ceelin',
            generic_name='Ascorbic Acid',
            form='Syrup',
            strength='100mg/5mL',
        )

        self.pharm_open = Pharmacy(
            email='open@pharmacy.com',
            business_name='Sunrise Pharmacy',
            contact_number='032-111-1111',
            address='Fuente Osmena, Cebu City',
            verification_status='approved',
            is_active=True,
        )
        self.pharm_open.set_password('PharmPass123!')
        self.pharm_open.save()

        self.pharm_closed = Pharmacy(
            email='closed@pharmacy.com',
            business_name='Midnight Closed Pharmacy',
            contact_number='032-222-2222',
            address='Colon St, Cebu City',
            verification_status='approved',
            is_active=True,
        )
        self.pharm_closed.set_password('PharmPass123!')
        self.pharm_closed.save()

        today = timezone.localtime().weekday()
        OperatingHours.objects.create(
            pharmacy=self.pharm_open,
            days_of_week=today,
            opening_time=time(0, 0),
            closing_time=time(23, 59),
            is_closed=False,
        )
        OperatingHours.objects.create(
            pharmacy=self.pharm_closed,
            days_of_week=today,
            is_closed=True,
        )

        Inventory.objects.create(
            pharmacy=self.pharm_open,
            medicine=self.med_biogesic,
            price='5.50',
            availability_status='available',
            stock_quantity=120,
        )
        Inventory.objects.create(
            pharmacy=self.pharm_closed,
            medicine=self.med_biogesic,
            price='4.00',
            availability_status='low_stock',
            stock_quantity=8,
        )
        Inventory.objects.create(
            pharmacy=self.pharm_open,
            medicine=self.med_vitc,
            price='95.00',
            availability_status='out_of_stock',
            stock_quantity=0,
        )

        self.client.post(reverse('login'), {
            'email': 'juan@example.com',
            'password': 'InitialPass123!',
        })

    def test_home_renders_and_filters_open_pharmacies(self):
        res = self.client.get(reverse('home'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Sunrise Pharmacy')
        self.assertContains(res, 'Midnight Closed Pharmacy')

        res_open = self.client.get(reverse('home'), {'open': '1'})
        self.assertEqual(res_open.status_code, 200)
        self.assertContains(res_open, 'Sunrise Pharmacy')
        self.assertNotContains(res_open, 'Midnight Closed Pharmacy')

    def test_search_filters_sort_and_records_history(self):
        res = self.client.get(reverse('search'), {
            'q': 'Biogesic',
            'category': str(self.cat_pain.category_id),
            'form': 'Tablet',
            'in_stock': '1',
            'open_now': '1',
            'sort': 'price_asc',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Biogesic')
        self.assertContains(res, 'Analgesics and fever reducers.')
        self.assertContains(res, '5.50')
        self.assertNotContains(res, 'Ceelin')
        self.assertTrue(SearchHistory.objects.filter(user=self.user, search_term='Biogesic').exists())

    def test_search_without_query_can_browse_pharmacies(self):
        res = self.client.get(reverse('search'), {'open_now': '1'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Sunrise Pharmacy')
        self.assertNotContains(res, 'Midnight Closed Pharmacy')

    def test_search_cards_collapse_and_show_expand_button_above_three_items(self):
        for i in range(3):
            Medicine.objects.create(
                category=self.cat_pain,
                medicine_name=f'ExtraMed {i}',
                generic_name='Ibuprofen',
                form='Tablet',
                strength='200mg',
            )
            p = Pharmacy(
                email=f'extra{i}@pharmacy.com',
                business_name=f'Extra Pharmacy {i}',
                contact_number='032-333-3333',
                address='Cebu City',
                verification_status='approved',
                is_active=True,
            )
            p.set_password('PharmPass123!')
            p.save()

        res = self.client.get(reverse('search'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="sr-med-card"')
        self.assertContains(res, 'Show all 5 medicines')
        self.assertContains(res, 'Show all 5 pharmacies')
        self.assertContains(res, 'class="sr-card is-collapsed"')

    def test_medicine_detail_filters_and_best_price(self):
        res = self.client.get(
            reverse('medicine_detail', args=[self.med_biogesic.medicine_id]),
            {'open_now': '1'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Sunrise Pharmacy')
        self.assertNotContains(res, 'Midnight Closed Pharmacy')
        self.assertContains(res, '120 in stock')

    def test_pharmacy_detail_filters_inventory(self):
        res = self.client.get(
            reverse('pharmacy_detail', args=[self.pharm_open.pharmacy_id]),
            {'q': 'Biogesic', 'status': 'in_stock'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Biogesic')
        self.assertNotContains(res, 'Ceelin')

    def test_favorites_toggle_and_list(self):
        toggle_med = self.client.post(
            reverse('toggle_favorite', args=['medicine', self.med_biogesic.medicine_id]),
            {'next': reverse('favorites')},
        )
        self.assertRedirects(toggle_med, reverse('favorites'))
        self.client.post(
            reverse('toggle_favorite', args=['pharmacy', self.pharm_open.pharmacy_id]),
            {'next': reverse('favorites')},
        )

        res = self.client.get(reverse('favorites'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Biogesic')
        self.assertContains(res, 'Sunrise Pharmacy')
        self.assertContains(res, '4.00')

    def test_favorites_ajax_toggle_returns_json_without_page_message(self):
        add_res = self.client.post(
            reverse('toggle_favorite', args=['medicine', self.med_biogesic.medicine_id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(add_res.status_code, 200)
        self.assertEqual(add_res.json(), {
            'favorited': True,
            'message': 'Added Biogesic to your favorites.',
            'kind': 'medicine',
        })

        rem_res = self.client.post(
            reverse('toggle_favorite', args=['medicine', self.med_biogesic.medicine_id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(rem_res.status_code, 200)
        self.assertEqual(rem_res.json(), {
            'favorited': False,
            'message': 'Removed Biogesic from your favorites.',
            'kind': 'medicine',
        })

        # Confirm the next page load does not show a leftover banner inside the panel
        home_res = self.client.get(reverse('home'))
        self.assertNotContains(home_res, 'Added Biogesic to your favorites.')
        self.assertNotContains(home_res, 'Removed Biogesic from your favorites.')

    def test_history_delete_individual_and_clear(self):
        s1 = SearchHistory.objects.create(user=self.user, search_term='Amoxicillin')
        s2 = SearchHistory.objects.create(user=self.user, search_term='Losartan')
        other_search = SearchHistory.objects.create(user=self.other_user, search_term='Secret')

        # Cannot delete another user's search item
        res_other = self.client.post(reverse('delete_history_item', args=[other_search.search_id]))
        self.assertEqual(res_other.status_code, 404)

        res_del = self.client.post(reverse('delete_history_item', args=[s1.search_id]))
        self.assertRedirects(res_del, reverse('history'))
        self.assertFalse(SearchHistory.objects.filter(pk=s1.search_id).exists())
        self.assertTrue(SearchHistory.objects.filter(pk=s2.search_id).exists())

        res_clear = self.client.post(reverse('clear_history'))
        self.assertRedirects(res_clear, reverse('history'))
        self.assertEqual(SearchHistory.objects.filter(user=self.user).count(), 0)

    def test_user_profile_update_and_password_change(self):
        res_get = self.client.get(reverse('user_profile'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, 'Account Details')
        self.assertContains(res_get, 'Change Password')

        res_upd = self.client.post(reverse('user_profile'), {
            'action': 'update_profile',
            'first_name': 'Juanito',
            'last_name': 'Dela Cruz',
            'email': 'juanito@example.com',
            'phone_number': '09179998888',
        })
        self.assertRedirects(res_upd, reverse('user_profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Juanito')
        self.assertEqual(self.user.email, 'juanito@example.com')

        res_pw = self.client.post(reverse('user_profile'), {
            'action': 'change_password',
            'current_password': 'InitialPass123!',
            'new_password1': 'UpdatedPass789!',
            'new_password2': 'UpdatedPass789!',
        })
        self.assertRedirects(res_pw, reverse('user_profile'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('UpdatedPass789!'))
